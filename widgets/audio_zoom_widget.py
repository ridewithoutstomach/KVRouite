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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._punkte = []           # [(t_s, dB)] sortiert
        self._stellen = []          # [(von_s, bis_s)] Sprechstellen
        self._fahrzeuge = []        # [(von_s, bis_s)] Fahrzeugstellen
        self._schnitte = []         # [(von_s, bis_s)] weggeschnitten
        self._zeit = 0.0
        self._gesamt = 0.0
        self._fenster = FENSTER_S
        self._mitte = 0.0           # Mitte des Ausschnitts (Gesamtzeit)
        self._maus_drin = False
        self._zieh_start = None     # x beim Druecken
        self._zieh_jetzt = None
        self._band_unter_zeiger = None

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
        if not treffer:
            return None
        return min(treffer, key=lambda t: t[2] - t[1])

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
        if event.button() == Qt.LeftButton:
            self._zieh_start = event.position().x()
            self._zieh_jetzt = self._zieh_start
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        w = max(1, self.width())
        von, _bis = self._von_bis()
        if self._zieh_start is not None:
            self._zieh_jetzt = event.position().x()
            self.update()
        else:
            band = self._band_bei(self._t(event.position().x(), w, von))
            if band != self._band_unter_zeiger:
                self._band_unter_zeiger = band
                self.setCursor(Qt.PointingHandCursor if band else Qt.ArrowCursor)
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
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

        # Abspielposition
        if von <= self._zeit <= bis:
            x = self._x(self._zeit, w, von)
            painter.setPen(QPen(QColor("white"), 2))
            painter.drawLine(QPointF(x, 0), QPointF(x, h))

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
