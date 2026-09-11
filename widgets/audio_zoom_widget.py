# -*- coding: utf-8 -*-
#
# This file is part of KVRouite.
#
# Copyright (C) 2026 by Bernd Eller
#
# KVRouite is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# KVRouite is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with KVRouite. If not, see <https://www.gnu.org/licenses/>.
#

# widgets/audio_zoom_widget.py
"""
Audio Zoom (ab 7.0): der Pegelverlauf der Tonspur, gezoomt um die
Abspielposition, mit den Sprechstellen als Baender.

Ein Modul fuer die waehlbaren Fenster wie Chart und Chart-Flow (siehe
widgets/slot_widget.py). Es zeigt einen Ausschnitt von FENSTER_S Sekunden
(Mausrad aendert ihn), der beim Abspielen mitlaeuft - solange die Maus
nicht im Fenster ist, damit man in Ruhe arbeiten kann. Die Zeitleiste
zeigt dieselben Baender in Klein; hier sind Sekunden breit genug, um sie
nachzubessern:

    Rechtsklick auf ein Band     -> Menue (entfernen)
    Ziehen ueber die Kurve       -> neues Band ueber den gezogenen Bereich
    Klick ohne Ziehen            -> Abspielposition dorthin

Die Daten kommen vom Hauptfenster: der Pegel je 100 ms aus dem Sucher
(core/verkehr, Zwischenspeicher) in GESAMTZEIT der Videoliste, die
Sprechstellen ebenso. Das Modul rechnet nichts selbst.
"""

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont
from PySide6.QtWidgets import QWidget

#: Sichtbarer Ausschnitt in Sekunden, Vorgabe und Grenzen.
FENSTER_S = 60.0
FENSTER_MIN_S = 8.0
FENSTER_MAX_S = 900.0

#: Pegelbereich der Zeichnung (dBFS).
DB_UNTEN = -60.0
DB_OBEN = 0.0

#: Farbe der Sprechstellen - dieselbe wie in der Zeitleiste.
BAND_FARBE = QColor(255, 140, 0, 110)
BAND_RAND = QColor(255, 170, 60)

#: Ziehen kuerzer als das zaehlt als Klick.
ZIEHEN_MIN_PX = 6

#: Wie nah der Zeiger an einer Bandkante sein muss, um sie zu fassen.
KANTE_PX = 6
#: Kuerzer darf ein Band beim Bearbeiten nicht werden.
MIN_LAENGE_S = 0.1


#: Fahrzeugstellen - dieselbe Farbe wie in der Zeitleiste.
FAHRZEUG_FARBE = QColor(80, 160, 255, 110)
FAHRZEUG_RAND = QColor(120, 190, 255)


class AudioZoomWidget(QWidget):
    bandEntfernen = Signal(float, float)        # Anfang, Ende (Gesamtzeit)
    bandAnlegen = Signal(float, float)
    zeitGewaehlt = Signal(float)
    #: Rechtsklick auf ein Band: (art, von, bis, globale Position) - das
    #: Fenster zeigt dasselbe Menue wie bei der Zeitleiste.
    bandMenuRequested = Signal(str, float, float, object)
    #: Start/Ende/Laenge eines Bandes bearbeitet (dieselbe Technik wie beim
    #: Verschieben eines Videocuts): (art, a0, b0, a, b) in Gesamtzeit. Das
    #: Fenster nimmt die alte Stelle weg und legt die neue an, ein
    #: Undo-Schritt (Bernd, 11.09.2026: nur im Audio Zoom, saubere Methode
    #: wie beim Videocut statt Zahlen-Dialog).
    bandGeaendert = Signal(str, float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._punkte = []           # [(t_s, dB)] sortiert
        self._stellen = []          # [(von_s, bis_s)] Sprechstellen
        self._fahrzeuge = []        # [(von_s, bis_s)] Fahrzeugstellen
        self._vorschlaege = []      # [(von_s, bis_s)] Fahrzeug-Vorschlaege (Detect)
        self._sprechvorschlaege = []  # [(von_s, bis_s)] Voice-Vorschlaege (Detect)
        self._markB = -1.0          # gelbe Marke [- der Zeitleiste (Gesamtzeit)
        self._markE = -1.0          # gelbe Marke -] der Zeitleiste (Gesamtzeit)
        self._schnitte = []         # [(von_s, bis_s)] weggeschnitten
        self._zeit = 0.0
        self._gesamt = 0.0
        self._fenster = FENSTER_S
        self._mitte = 0.0           # Mitte des Ausschnitts (Gesamtzeit)
        self._maus_drin = False
        self._zieh_start = None     # x beim Druecken
        self._zieh_jetzt = None
        self._band_unter_zeiger = None
        # Feinsteller fuer Start/Ende/Laenge eines Bandes.
        self._edit = None           # (art, a0, b0) in Gesamtzeit, oder None
        self._edit_neu = None       # (a, b) Vorschau
        self._edit_kante = None     # "links" / "rechts" / "block"
        self._edit_fein = False     # True: Knopfleiste statt Ziehen
        self._edit_knoepfe = {}     # Name -> QRectF
        self._edit_zeit_start = 0.0 # Zeit unter dem Zeiger beim Zugriff

    # ------------------------------------------------------------ Daten
    def set_pegelkurve(self, punkte):
        self._punkte = list(punkte or [])
        self.update()

    def set_sprechstellen(self, stellen):
        self._stellen = [(float(a), float(b)) for a, b in (stellen or [])]
        self.update()

    def set_fahrzeugstellen(self, stellen):
        self._fahrzeuge = [(float(a), float(b)) for a, b in (stellen or [])]
        self.update()

    def set_fahrzeugvorschlaege(self, stellen):
        """Vorschlaege von "Detect vehicles": gestrichelter Rahmen, kein
        Band - sie gelten erst, wenn der Nutzer sie uebernimmt."""
        self._vorschlaege = [(float(a), float(b)) for a, b in (stellen or [])]
        self.update()

    def set_sprechvorschlaege(self, stellen):
        """Vorschlaege von "Detect voices": gestrichelter orange Rahmen."""
        self._sprechvorschlaege = [(float(a), float(b)) for a, b in (stellen or [])]
        self.update()

    def set_marken(self, von_s, bis_s):
        """Die gelben Marken [- und -] der Zeitleiste (Gesamtzeit), damit
        man auch im Audio Zoom sieht, was markiert ist (Bernd, 11.09.2026).
        Negativ heisst: nicht gesetzt."""
        self._markB = float(von_s) if von_s is not None else -1.0
        self._markE = float(bis_s) if bis_s is not None else -1.0
        self.update()

    def set_schnitte(self, schnitte):
        """Die weggeschnittenen Bereiche: werden wie in der Zeitleiste
        abgedunkelt und schraffiert gezeichnet; Sprechstellen darin sind
        weder zu sehen noch anzuklicken - der Export laesst sie weg."""
        self._schnitte = [(float(a), float(b)) for a, b in (schnitte or [])]
        self.update()

    def _geschnitten(self, t_s):
        return any(a <= t_s <= b for a, b in self._schnitte)

    def set_gesamt(self, dauer_s):
        self._gesamt = max(0.0, float(dauer_s or 0.0))
        self.update()

    def set_zeit(self, zeit_s):
        """Abspielposition. Der Ausschnitt folgt ihr, solange die Maus
        nicht im Fenster ist."""
        self._zeit = float(zeit_s or 0.0)
        if not self._maus_drin and self._zieh_start is None:
            self._mitte = self._zeit
        self.update()

    # ------------------------------------------------------------ Geometrie
    def _von_bis(self):
        halb = self._fenster / 2.0
        von = self._mitte - halb
        if self._gesamt > 0:
            von = max(0.0, min(von, max(0.0, self._gesamt - self._fenster)))
        return von, von + self._fenster

    def _x(self, t_s, w, von):
        return (t_s - von) / self._fenster * w

    def _t(self, x, w, von):
        return von + x / float(max(1, w)) * self._fenster

    def _band_bei(self, t_s):
        """(art, von, bis) unter der Zeit, oder None. Bei Ueberlappung das
        schmalere Band."""
        if self._geschnitten(t_s):
            return None
        treffer = [("vehicle", a, b) for a, b in self._fahrzeuge if a <= t_s <= b]
        treffer += [("voice", a, b) for a, b in self._stellen if a <= t_s <= b]
        treffer += [("vehicle_hint", a, b) for a, b in self._vorschlaege if a <= t_s <= b]
        treffer += [("voice_hint", a, b) for a, b in self._sprechvorschlaege if a <= t_s <= b]
        if not treffer:
            return None
        return min(treffer, key=lambda t: t[2] - t[1])

    def _band_kante_unter(self, x, w, von):
        """Was liegt an Bildschirm-x? ((art, a, b), kante) mit kante
        "links"/"rechts"/"block", oder (None, None). Nur markierte Baender
        (Sprech- und Fahrzeugstellen), nicht die Vorschlaege. Kanten zuerst,
        damit die gemeinsame Kante zweier Baender fassbar bleibt."""
        reihen = (("voice", self._stellen), ("vehicle", self._fahrzeuge))
        for art, stellen in reihen:
            for a, b in stellen:
                if abs(x - self._x(a, w, von)) <= KANTE_PX:
                    return (art, a, b), "links"
                if abs(x - self._x(b, w, von)) <= KANTE_PX:
                    return (art, a, b), "rechts"
        for art, stellen in reihen:
            for a, b in stellen:
                if self._x(a, w, von) <= x <= self._x(b, w, von):
                    return (art, a, b), "block"
        return None, None

    # ------------------------------------------------------------ Maus
    def enterEvent(self, event):
        self._maus_drin = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._maus_drin = False
        self._band_unter_zeiger = None
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        schritt = event.angleDelta().y()
        if schritt == 0:
            return
        faktor = 0.8 if schritt > 0 else 1.25
        self._fenster = max(FENSTER_MIN_S, min(FENSTER_MAX_S, self._fenster * faktor))
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        w = max(1, self.width())
        von, _bis = self._von_bis()
        x = event.position().x()
        # Offener Feinsteller: nur Knoepfe und das erneute Fassen der Kante.
        if self._edit_fein:
            if event.button() != Qt.LeftButton:
                event.ignore(); return
            name = self._edit_knopf_unter(event.position())
            if name == "zurueck":
                self._edit_ruecken(-self._edit_schritt(event.modifiers()))
            elif name == "vor":
                self._edit_ruecken(+self._edit_schritt(event.modifiers()))
            elif name == "ok":
                self._edit_anwenden()
            elif name == "abbruch":
                self._edit_abbrechen()
            elif abs(x - self._edit_kante_x(w, von)) <= KANTE_PX:
                self._edit_wieder_ziehen(x, w, von)
            event.accept(); return
        if event.button() == Qt.LeftButton:
            # Zuerst fragen: liegt der Zeiger an einer Bandkante oder in einem
            # Band? Dann bearbeiten statt ein neues Band ziehen.
            band, kante = self._band_kante_unter(x, w, von)
            if band is not None:
                art, a0, b0 = band
                self._edit = (art, float(a0), float(b0))
                self._edit_kante = kante
                self._edit_neu = (float(a0), float(b0))
                self._edit_zeit_start = self._t(x, w, von)
                self._edit_press_x = x
                self._edit_fein = False
                self.setCursor(Qt.SizeAllCursor if kante == "block"
                               else Qt.SizeHorCursor)
                self.setFocus()
                event.accept(); return
            self._zieh_start = x
            self._zieh_jetzt = x
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        w = max(1, self.width())
        von, _bis = self._von_bis()
        x = event.position().x()
        # Beim Bearbeiten ziehen wir die Kante / den Block.
        if self._edit is not None and not self._edit_fein:
            self._edit_aktualisieren(x, w, von)
            event.accept(); return
        if self._edit_fein:
            if self._edit_knopf_unter(event.position()) is not None:
                self.setCursor(Qt.PointingHandCursor)
            elif abs(x - self._edit_kante_x(w, von)) <= KANTE_PX:
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            event.accept(); return
        if self._zieh_start is not None:
            self._zieh_jetzt = x
            self.update()
        else:
            # Zeigerform: an einer Bandkante der Groessenpfeil, sonst wie bisher.
            band, kante = self._band_kante_unter(x, w, von)
            if kante in ("links", "rechts"):
                self.setCursor(Qt.SizeHorCursor)
            else:
                b2 = self._band_bei(self._t(x, w, von))
                self.setCursor(Qt.PointingHandCursor if b2 else Qt.ArrowCursor)
            b2 = self._band_bei(self._t(x, w, von))
            if b2 != self._band_unter_zeiger:
                self._band_unter_zeiger = b2
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Bearbeiten losgelassen: in die Knopfleiste wechseln (nicht sofort
        # anwenden), wie beim Videocut. Ein Klick MITTEN in ein Band, ohne zu
        # ziehen, bleibt ein Sprung zur Position - nur Kanten und ein
        # gezogener Block oeffnen den Feinsteller.
        if self._edit is not None and not self._edit_fein \
                and event.button() == Qt.LeftButton:
            gezogen = abs(event.position().x() - getattr(self, "_edit_press_x", event.position().x())) >= ZIEHEN_MIN_PX
            if self._edit_kante == "block" and not gezogen:
                w = max(1, self.width()); von, _b = self._von_bis()
                self._edit = self._edit_neu = self._edit_kante = None
                self.setCursor(Qt.ArrowCursor)
                self.zeitGewaehlt.emit(max(0.0, self._t(event.position().x(), w, von)))
                self.update()
                event.accept(); return
            self._edit_fein = True
            self.setCursor(Qt.ArrowCursor)
            self.setFocus()
            self.update()
            event.accept(); return
        if event.button() == Qt.LeftButton and self._zieh_start is not None:
            w = max(1, self.width())
            von, _bis = self._von_bis()
            x0, x1 = self._zieh_start, event.position().x()
            self._zieh_start = self._zieh_jetzt = None
            self.update()
            if abs(x1 - x0) < ZIEHEN_MIN_PX:
                self.zeitGewaehlt.emit(max(0.0, self._t(x0, w, von)))
            else:
                a, b = sorted((self._t(x0, w, von), self._t(x1, w, von)))
                a = max(0.0, a)
                if self._gesamt > 0:
                    b = min(self._gesamt, b)
                # Ganz im Schnitt gezogen: nichts anlegen, dort wird nichts
                # exportiert.
                if b - a >= 0.2 and not (self._geschnitten(a) and self._geschnitten(b)
                                         and any(sa <= a and b <= sb for sa, sb in self._schnitte)):
                    self.bandAnlegen.emit(a, b)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self._edit_fein:
            if event.key() in (Qt.Key_Left,):
                self._edit_ruecken(-self._edit_schritt(event.modifiers()))
            elif event.key() in (Qt.Key_Right,):
                self._edit_ruecken(+self._edit_schritt(event.modifiers()))
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._edit_anwenden()
            elif event.key() == Qt.Key_Escape:
                self._edit_abbrechen()
            else:
                super().keyPressEvent(event); return
            event.accept(); return
        super().keyPressEvent(event)

    # -------------------------------------------------- Feinsteller Band
    @staticmethod
    def _edit_schritt(modifiers):
        """Schrittweite: ohne 1 ms, Shift 10 ms, Alt 100 ms."""
        if modifiers & Qt.AltModifier:
            return 0.1
        if modifiers & Qt.ShiftModifier:
            return 0.01
        return 0.001

    def start_bearbeiten(self, art, a, b):
        """Vom Menue: den Feinsteller fuer dieses Band oeffnen, Ende fassen,
        und den Ausschnitt darauf zentrieren, damit man es sieht."""
        self._edit = (art, float(a), float(b))
        self._edit_neu = (float(a), float(b))
        self._edit_kante = "rechts"
        self._edit_fein = True
        self._mitte = (float(a) + float(b)) / 2.0
        if self._fenster < (b - a) * 1.5:
            self._fenster = min(FENSTER_MAX_S, max(FENSTER_MIN_S, (b - a) * 3))
        self.setFocus()
        self.update()

    def _edit_grenzen_werte(self):
        lo = 0.0
        hi = self._gesamt if self._gesamt > 0 else (self._edit_neu[1] + 3600.0)
        return lo, hi

    def _edit_aktualisieren(self, x, w, von):
        if self._edit is None:
            return
        _art, a0, b0 = self._edit
        lo, hi = self._edit_grenzen_werte()
        delta = self._t(x, w, von) - self._edit_zeit_start
        if self._edit_kante == "links":
            a = min(max(a0 + delta, lo), b0 - MIN_LAENGE_S); b = b0
        elif self._edit_kante == "rechts":
            a = a0; b = max(min(b0 + delta, hi), a0 + MIN_LAENGE_S)
        else:
            laenge = b0 - a0
            a = min(max(a0 + delta, lo), hi - laenge); b = a + laenge
        neu = (a, b)
        if neu != self._edit_neu:
            self._edit_neu = neu
            self.update()

    def _edit_ruecken(self, schritt_s):
        if self._edit is None or self._edit_neu is None:
            return
        _art, a0, b0 = self._edit
        a, b = self._edit_neu
        lo, hi = self._edit_grenzen_werte()
        if self._edit_kante == "links":
            a = min(max(a + schritt_s, lo), b0 - MIN_LAENGE_S)
        elif self._edit_kante == "rechts":
            b = max(min(b + schritt_s, hi), a0 + MIN_LAENGE_S)
        else:
            laenge = b0 - a0
            a = min(max(a + schritt_s, lo), hi - laenge); b = a + laenge
        neu = (round(a, 3), round(b, 3))
        if neu != self._edit_neu:
            self._edit_neu = neu
            self.update()

    def _edit_wieder_ziehen(self, x, w, von):
        """Aus der Knopfleiste heraus die Kante erneut mit der Maus fassen."""
        _art, a0, b0 = self._edit
        a, b = self._edit_neu
        bisher = (b - b0) if self._edit_kante == "rechts" else (a - a0)
        self._edit_zeit_start = self._t(x, w, von) - bisher
        self._edit_fein = False
        self.setCursor(Qt.SizeAllCursor if self._edit_kante == "block"
                       else Qt.SizeHorCursor)
        self.update()

    def _edit_abbrechen(self):
        self._edit = self._edit_neu = self._edit_kante = None
        self._edit_fein = False
        self._edit_knoepfe = {}
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def _edit_anwenden(self):
        if self._edit is None:
            self._edit_abbrechen(); return
        art, a0, b0 = self._edit
        a, b = self._edit_neu or (a0, b0)
        self._edit = self._edit_neu = self._edit_kante = None
        self._edit_fein = False
        self._edit_knoepfe = {}
        self.setCursor(Qt.ArrowCursor)
        self.update()
        if abs(a - a0) < 0.0005 and abs(b - b0) < 0.0005:
            return
        self.bandGeaendert.emit(art, a0, b0, round(a, 3), round(b, 3))

    def _edit_kante_x(self, w, von):
        a, b = self._edit_neu
        return self._x(b if self._edit_kante == "rechts" else a, w, von)

    def _edit_knopf_unter(self, pos):
        for name, r in self._edit_knoepfe.items():
            if r.contains(QPointF(pos)):
                return name
        return None

    def _draw_edit(self, painter, w, h, von, bis, oben, unten):
        """Vorschau des bearbeiteten Bandes (gelber Rahmen) und, in der
        Knopfleiste, die Leiste [<] [>] Lage Verschiebung [Haken] [Kreuz] -
        wie beim Verschieben eines Videocuts."""
        art, a0, b0 = self._edit
        a, b = self._edit_neu
        gelb = QColor(255, 204, 0)
        # Vorschau-Rahmen (nur wenn im Ausschnitt sichtbar).
        if not (b < von or a > bis):
            xa = max(0.0, self._x(a, w, von)); xb = min(float(w), self._x(b, w, von))
            if xb > xa:
                painter.setPen(QPen(gelb, 1, Qt.DashLine))
                painter.setBrush(QBrush(QColor(255, 204, 0, 40)))
                painter.drawRect(QRectF(xa, oben, xb - xa, unten - oben))
        if not self._edit_fein:
            return
        # Beschriftung der Leiste.
        if self._edit_kante == "links":
            lage = "Start %.3f s" % a; delta = a - a0
        elif self._edit_kante == "rechts":
            lage = "End %.3f s" % b; delta = b - b0
        else:
            lage = "%.3f - %.3f s" % (a, b); delta = a - a0
        schub = "%+.3f s" % delta
        fm = painter.fontMetrics()
        hoehe = fm.height() + 10
        q = hoehe - 6
        luecke = 6
        b_lage = fm.horizontalAdvance(lage)
        b_schub = fm.horizontalAdvance(schub)
        breite = (3 + 2 * (q + luecke) + luecke + b_lage + 2 * luecke
                  + b_schub + 3 * luecke + 2 * (q + luecke) + 3 - luecke)
        kante_x = self._edit_kante_x(w, von)
        x = kante_x + 12
        if x + breite > w:
            x = max(0.0, kante_x - 12 - breite)
        y = max(0.0, (h - hoehe) / 2.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 225))
        painter.drawRect(QRectF(x, y, breite, hoehe))
        painter.setPen(QPen(gelb, 1)); painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(x, y, breite, hoehe))
        knoepfe = {}
        lauf = [x + 3]
        d = q * 0.28

        def knopf(name):
            r = QRectF(lauf[0], y + 3, q, q)
            knoepfe[name] = r
            painter.setPen(QPen(gelb, 1)); painter.setBrush(QColor(255, 204, 0, 40))
            painter.drawRect(r)
            lauf[0] += q + luecke
            return r

        def pfeil(r, nach_rechts):
            m = r.center()
            if nach_rechts:
                pts = [QPointF(m.x() - d, m.y() - d), QPointF(m.x() + d, m.y()),
                       QPointF(m.x() - d, m.y() + d)]
            else:
                pts = [QPointF(m.x() + d, m.y() - d), QPointF(m.x() - d, m.y()),
                       QPointF(m.x() + d, m.y() + d)]
            painter.setPen(Qt.NoPen); painter.setBrush(gelb)
            painter.drawPolygon(QPolygonF(pts))

        pfeil(knopf("zurueck"), False)
        pfeil(knopf("vor"), True)
        lauf[0] += luecke
        y_text = y + 5 + fm.ascent()
        painter.setPen(gelb); painter.drawText(QPointF(lauf[0], y_text), lage)
        lauf[0] += b_lage + 2 * luecke
        painter.setPen(QColor("#ffffff")); painter.drawText(QPointF(lauf[0], y_text), schub)
        lauf[0] += b_schub + 3 * luecke
        r = knopf("ok"); m = r.center()
        painter.setPen(QPen(QColor("#7CFC00"), 2)); painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(QPolygonF([QPointF(m.x() - d, m.y()),
                                        QPointF(m.x() - d * 0.2, m.y() + d),
                                        QPointF(m.x() + d, m.y() - d)]))
        r = knopf("abbruch"); m = r.center()
        painter.setPen(QPen(QColor("#ff5555"), 2))
        painter.drawLine(QPointF(m.x() - d, m.y() - d), QPointF(m.x() + d, m.y() + d))
        painter.drawLine(QPointF(m.x() - d, m.y() + d), QPointF(m.x() + d, m.y() - d))
        self._edit_knoepfe = knoepfe

    def contextMenuEvent(self, event):
        w = max(1, self.width())
        von, _bis = self._von_bis()
        band = self._band_bei(self._t(event.pos().x(), w, von))
        if band is None:
            event.ignore()
            return
        # Das Menue stellt das Fenster zusammen - dasselbe wie in der
        # Zeitleiste (Listen, Fill, Start and end, Remove).
        art, a, b = band
        self.bandMenuRequested.emit(art, a, b, event.globalPos())
        event.accept()

    # ------------------------------------------------------------ Zeichnen
    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if w <= 0 or h <= 0:
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        von, bis = self._von_bis()

        # Kurve: je Pixelspalte der hoechste Pegel im Zeitfenster der Spalte.
        oben = 18       # Platz fuer die Zeitmarken
        unten = h - 4
        if self._punkte:
            import bisect
            zeiten = getattr(self, "_zeiten", None)
            if zeiten is None or len(zeiten) != len(self._punkte):
                zeiten = [p[0] for p in self._punkte]
                self._zeiten = zeiten
            poly = QPolygonF()
            poly.append(QPointF(0, unten))
            sek_je_px = self._fenster / w
            i0 = bisect.bisect_left(zeiten, von)
            for x in range(w):
                t0 = von + x * sek_je_px
                t1 = t0 + sek_je_px
                i1 = bisect.bisect_left(zeiten, t1, i0)
                if i1 > i0:
                    db = max(self._punkte[i][1] for i in range(i0, i1))
                elif i0 < len(self._punkte):
                    db = self._punkte[min(i0, len(self._punkte) - 1)][1]
                else:
                    db = DB_UNTEN
                i0 = max(i0, i1 - 1)
                anteil = (max(DB_UNTEN, min(DB_OBEN, db)) - DB_UNTEN) / (DB_OBEN - DB_UNTEN)
                poly.append(QPointF(x, unten - anteil * (unten - oben)))
            poly.append(QPointF(w, unten))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0, 200, 220, 170)))
            painter.drawPolygon(poly)

        # Sprechstellen (orange) und Fahrzeugstellen (blau) ueber die volle
        # Hoehe; das Band unter dem Zeiger etwas kraeftiger.
        for art, stellen, farbe, rand, hell in (
                ("voice", self._stellen, BAND_FARBE, BAND_RAND, QColor(255, 170, 60, 160)),
                ("vehicle", self._fahrzeuge, FAHRZEUG_FARBE, FAHRZEUG_RAND, QColor(120, 190, 255, 160))):
            for a, b in stellen:
                if b < von or a > bis:
                    continue
                xa, xb = self._x(a, w, von), self._x(b, w, von)
                painter.setPen(QPen(rand, 1))
                painter.setBrush(QBrush(hell if (art, a, b) == self._band_unter_zeiger else farbe))
                painter.drawRect(QRectF(xa, oben, xb - xa, unten - oben))
        # Vorschlaege von Detect: gestrichelter Rahmen ohne Fuellung, unter
        # dem Zeiger leicht gefuellt - je in ihrer Farbe (Fahrzeug blau,
        # Voice orange), klar getrennt von den gefuellten, markierten
        # Baendern (Bernd, 11.09.2026).
        for art, stellen, rand, fuell in (
                ("vehicle_hint", self._vorschlaege, FAHRZEUG_RAND, QColor(120, 190, 255, 60)),
                ("voice_hint", self._sprechvorschlaege, BAND_RAND, QColor(255, 170, 60, 60))):
            for a, b in stellen:
                if b < von or a > bis:
                    continue
                xa, xb = self._x(a, w, von), self._x(b, w, von)
                stift = QPen(rand, 1)
                stift.setStyle(Qt.DashLine)
                painter.setPen(stift)
                painter.setBrush(QBrush(fuell) if (art, a, b) == self._band_unter_zeiger
                                 else Qt.NoBrush)
                painter.drawRect(QRectF(xa, oben, xb - xa, unten - oben))

        # Schnitte: abgedunkelt und schraffiert wie in der Zeitleiste, ueber
        # Kurve und Baendern - was darunter liegt, ist weg.
        for a, b in self._schnitte:
            if b < von or a > bis:
                continue
            xa, xb = max(0.0, self._x(a, w, von)), min(float(w), self._x(b, w, von))
            if xb <= xa:
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 190)))
            painter.drawRect(QRectF(xa, oben, xb - xa, unten - oben))
            painter.setPen(QPen(QColor(120, 120, 120, 160), 1))
            painter.setClipRect(QRectF(xa, oben, xb - xa, unten - oben))
            x = xa - (unten - oben)
            while x < xb:
                painter.drawLine(QPointF(x, unten), QPointF(x + (unten - oben), oben))
                x += 9
            painter.setClipping(False)

        # Ziehen: der neue Bereich
        if self._zieh_start is not None and self._zieh_jetzt is not None:
            x0, x1 = sorted((self._zieh_start, self._zieh_jetzt))
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(255, 255, 255, 40)))
            painter.drawRect(QRectF(x0, oben, x1 - x0, unten - oben))

        # Zeitmarken
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        painter.setFont(QFont("Arial", 8))
        schritt = _tick_schritt(self._fenster)
        t = (int(von / schritt)) * schritt
        while t <= bis:
            x = self._x(t, w, von)
            painter.drawLine(QPointF(x, oben - 4), QPointF(x, oben))
            painter.drawText(QPointF(x + 2, 12), _kurz(t))
            t += schritt

        # Gelbe Marken [- und -] wie in der Zeitleiste, dazwischen leicht
        # gelb hinterlegt.
        xB = xE = None
        if self._markB >= 0 and von <= self._markB <= bis:
            xB = self._x(self._markB, w, von)
        if self._markE >= 0 and von <= self._markE <= bis:
            xE = self._x(self._markE, w, von)
        if (self._markB >= 0 and self._markE >= 0
                and min(self._markB, self._markE) <= bis
                and max(self._markB, self._markE) >= von):
            lx = self._x(max(von, min(self._markB, self._markE)), w, von)
            rx = self._x(min(bis, max(self._markB, self._markE)), w, von)
            if rx > lx:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(255, 255, 0, 60)))
                painter.drawRect(QRectF(lx, oben, rx - lx, unten - oben))
        painter.setPen(QPen(QColor(255, 255, 0), 1))
        for x in (xB, xE):
            if x is not None:
                painter.drawLine(QPointF(x, 0), QPointF(x, h))

        # Abspielposition
        if von <= self._zeit <= bis:
            x = self._x(self._zeit, w, von)
            painter.setPen(QPen(QColor("white"), 2))
            painter.drawLine(QPointF(x, 0), QPointF(x, h))

        # Feinsteller eines Bandes ueber allem.
        if self._edit is not None:
            self._draw_edit(painter, w, h, von, bis, oben, unten)

        # Beschriftung
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        # Gezaehlt wird, was nicht im Schnitt liegt.
        def zaehlen(stellen):
            return sum(1 for a, b in stellen
                       if not any(sa <= a and b <= sb for sa, sb in self._schnitte))
        painter.drawText(QPointF(4, h - 8),
                         "Audio  %s – %s   %d voice, %d vehicle stretch(es)"
                         % (_kurz(von), _kurz(bis), zaehlen(self._stellen), zaehlen(self._fahrzeuge)))


def _kurz(sekunden):
    sekunden = max(0.0, float(sekunden))
    m = int(sekunden // 60)
    s = sekunden - m * 60
    return "%d:%04.1f" % (m, s)


def _tick_schritt(fenster_s):
    for schritt in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if fenster_s / schritt <= 12:
            return schritt
    return 900
