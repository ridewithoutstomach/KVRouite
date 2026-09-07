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

# widgets/video_surface.py
"""Zeichenflaeche fuer die Vorschau - Qt malt die Bilder selbst.

Warum es das gibt: bisher zeichnete GStreamer direkt in ein Fensterhandle
(d3d11videosink). Das ist schnell, aber es ist eine native Direct3D-Oberflaeche
- Qt kann darueber nicht zuverlaessig zeichnen. Alles, was ueber dem Video
liegen soll (Auswahlrahmen um ein Overlay, Anfasser zum Skalieren, Ziehen mit
der Maus), waere damit nicht machbar.

Hier liefert GStreamer die fertigen Bilder statt sie selbst anzuzeigen, und
Qt malt sie. Gemessen an 4K-Material in Vorschaugroesse (1280x720, 30 fps):
180 von 180 Bildern angekommen, groesste Luecke 66 ms bei 33 ms Bildabstand,
3,2 ms je Bild fuer die Umwandlung - rund ein Zehntel des Zeitbudgets.

Nebenbei loest das ein zweites Problem: das Einbetten ueber Fensterhandles ist
die Stelle, die unter Linux und besonders unter Wayland Aerger macht. Bilder
abzuholen und selbst zu malen funktioniert ueberall gleich.

Darauf sitzt die Overlay-Bearbeitung: anklicken, ziehen, an den Ecken
groesser und kleiner ziehen. Zwei Dinge sind dabei wichtig:

  * Gerechnet wird in EXPORTpixeln, nicht in Bildschirmpixeln. Die Vorschau
    ist kleiner als das fertige Video; wuerde die Lage aus Bildschirmpixeln
    gebildet, saesse das Overlay im Export woanders.
  * Beim Ziehen wird nur ein Rahmen gemalt. Das Bild selbst zeichnet
    GStreamer, und dessen Zeitleiste wird erst beim Loslassen neu gebaut -
    bei jeder Mausbewegung waere das viel zu teuer.

Die Groesse haengt an einem einzigen Faktor (`scale`), deshalb kann nur
proportional skaliert werden. Das ist keine Bequemlichkeit, sondern das, was
die Datenstruktur hergibt.
"""

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget


class VideoSurface(QWidget):
    """Zeigt die von GStreamer gelieferten Bilder und laesst Overlays ziehen."""

    #: index (Platz in der Overlay-Liste des Managers), x, y in Exportpixeln,
    #: neuer Skalierungsfaktor. Wird erst beim Loslassen der Maus gesendet.
    overlayGeaendert = Signal(int, int, int, float)
    #: Welches Overlay gerade ausgewaehlt ist, -1 fuer keines.
    auswahlGeaendert = Signal(int)
    #: 360-Zug mit der Maus: Weg in Bildschirmpunkten seit dem letzten
    #: Ereignis. In Winkel rechnet das VideoEditorWidget um, weil dort der
    #: aktuelle Bildwinkel bekannt ist.
    blick360Gezogen = Signal(float, float)
    #: 360-Zoom mit dem Mausrad: Rastschritte, positiv heisst naeher heran.
    blick360Gezoomt = Signal(float)
    #: Die Flaeche, auf der das Bild liegt, hat sich geaendert (erstes Bild,
    #: anderes Seitenverhaeltnis, andere Fenstergroesse).
    bildbereichGeaendert = Signal()

    #: Halbe Kantenlaenge eines Anfassers in Bildschirmpunkten.
    GRIFF = 5
    #: Wie weit daneben ein Anfasser noch trifft.
    GRIFF_TREFFER = 8
    #: Kleinste Overlaybreite in Exportpixeln - darunter ist nichts mehr zu
    #: greifen.
    MINDESTBREITE = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bild = None
        self._bildbereich = QRect()

        self._overlays = []
        self._export = None
        self._zeit = 0.0
        self._auswahl = -1

        self._modus = None          # None | "verschieben" | "skalieren"
        self._griff = None          # (rechts, unten) des angefassten Eckpunkts
        self._start_maus = None     # Mausposition in Exportpixeln
        self._start_rect = None     # (x, y, w, h) in Exportpixeln
        self._zug_rect = None       # laufender Zustand, Exportpixel
        self._ueber_flaeche = False

        # 360: Schwenken mit der Maus. Nachrangig zu den Overlays - erst wenn
        # weder ein Anfasser noch ein Overlay getroffen ist, wird geschwenkt.
        self._360_aktiv = False
        self._blick_von = None      # letzte Mausposition des laufenden Zugs

        # Der Hintergrund wird selbst gemalt; ohne das blitzt beim Groesse-
        # aendern kurz die Fensterfarbe durch.
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setMinimumSize(1, 1)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------ Bild
    @Slot(object)
    def bild_setzen(self, bild):
        """Neues Bild anzeigen. Wird aus dem Hauptthread aufgerufen.

        Das Backend schickt es ueber ein Qt-Signal herueber - GStreamer
        liefert auf einem eigenen Thread, und Qt-Widgets duerfen nur aus dem
        Hauptthread angefasst werden. Ein Signal wird dabei von Qt selbst in
        die Warteschlange des Hauptthreads gelegt.
        """
        if isinstance(bild, QImage) and not bild.isNull():
            self._bild = bild
            self.update()

    def bild_leeren(self):
        self._bild = None
        self.update()

    def bildbereich(self):
        """Rechteck, in dem das Bild zuletzt gezeichnet wurde (Widget-Koordinaten)."""
        return QRect(self._bildbereich)

    def zu_bildpunkt(self, punkt):
        """Mausposition -> Bildpunkt im Video, oder None ausserhalb."""
        if self._bild is None or self._bildbereich.isEmpty():
            return None
        if not self._bildbereich.contains(punkt):
            return None
        rel_x = (punkt.x() - self._bildbereich.x()) / self._bildbereich.width()
        rel_y = (punkt.y() - self._bildbereich.y()) / self._bildbereich.height()
        return (rel_x * self._bild.width(), rel_y * self._bild.height())

    # -------------------------------------------------------------- Overlays
    def overlays_setzen(self, liste, export_groesse=None):
        """Die Overlays, die bearbeitet werden koennen.

        Erwartet dieselben Rechtecke, die auch das Backend bekommt: Lage und
        Groesse in Exportpixeln, dazu `index` (Platz in der Liste des
        Managers) und `scale`.
        """
        neu = []
        for ovl in liste or []:
            try:
                neu.append({
                    "index": int(ovl["index"]),
                    "start": float(ovl.get("start", 0.0)),
                    "end": float(ovl.get("end", 0.0)),
                    "x": float(ovl.get("x", 0)), "y": float(ovl.get("y", 0)),
                    "w": float(ovl.get("w", 0)), "h": float(ovl.get("h", 0)),
                    "scale": float(ovl.get("scale", 1.0) or 1.0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        self._overlays = [o for o in neu if o["w"] > 0 and o["h"] > 0]
        self._export = (tuple(export_groesse) if export_groesse else None)
        if self._auswahl not in [o["index"] for o in self._overlays]:
            self._auswahl_setzen(-1)
        self.update()

    def zeit_setzen(self, sekunden):
        """Aktuelle Rohzeit - danach richtet sich, welche Overlays sichtbar sind."""
        try:
            neu = float(sekunden)
        except (TypeError, ValueError):
            return
        if abs(neu - self._zeit) < 0.001:
            return
        vorher = self._sichtbare()
        self._zeit = neu
        if self._sichtbare() != vorher:
            if self._auswahl not in [o["index"] for o in self._sichtbare()]:
                self._auswahl_setzen(-1)
            self.update()

    def auswahl(self):
        return self._auswahl

    def _auswahl_setzen(self, index):
        if index == self._auswahl:
            return
        self._auswahl = index
        self.auswahlGeaendert.emit(index)

    def _sichtbare(self):
        """Overlays, die zur aktuellen Zeit im Bild stehen."""
        return [o for o in self._overlays
                if o["start"] <= self._zeit <= o["end"]]

    # ---------------------------------------------------------- Umrechnungen
    def _faktoren(self):
        """Exportpixel -> Bildschirmpunkte, je Achse. None, wenn unbekannt."""
        if not self._export or self._bildbereich.isEmpty():
            return None
        breite, hoehe = self._export
        if breite <= 0 or hoehe <= 0:
            return None
        return (self._bildbereich.width() / float(breite),
                self._bildbereich.height() / float(hoehe))

    def _nach_widget(self, x, y, w, h):
        f = self._faktoren()
        if f is None:
            return None
        fx, fy = f
        return QRectF(self._bildbereich.x() + x * fx,
                      self._bildbereich.y() + y * fy,
                      max(1.0, w * fx), max(1.0, h * fy))

    def _nach_export(self, punkt):
        f = self._faktoren()
        if f is None:
            return None
        fx, fy = f
        return ((punkt.x() - self._bildbereich.x()) / fx,
                (punkt.y() - self._bildbereich.y()) / fy)

    def _rechteck(self, ovl):
        """Das Rechteck eines Overlays in Bildschirmpunkten - ggf. das gezogene."""
        if self._zug_rect is not None and ovl["index"] == self._auswahl:
            x, y, w, h = self._zug_rect
        else:
            x, y, w, h = ovl["x"], ovl["y"], ovl["w"], ovl["h"]
        return self._nach_widget(x, y, w, h)

    def _griffpunkte(self, rechteck):
        """Die vier Eckpunkte, als (rechts, unten) -> Punkt."""
        return {
            (False, False): rechteck.topLeft(),
            (True, False):  rechteck.topRight(),
            (False, True):  rechteck.bottomLeft(),
            (True, True):   rechteck.bottomRight(),
        }

    # ---------------------------------------------------------------- Maus
    def _getroffener_griff(self, punkt):
        if self._auswahl < 0:
            return None
        for ovl in self._sichtbare():
            if ovl["index"] != self._auswahl:
                continue
            rechteck = self._rechteck(ovl)
            if rechteck is None:
                return None
            for kennung, ecke in self._griffpunkte(rechteck).items():
                if (abs(punkt.x() - ecke.x()) <= self.GRIFF_TREFFER and
                        abs(punkt.y() - ecke.y()) <= self.GRIFF_TREFFER):
                    return kennung
        return None

    def _getroffenes_overlay(self, punkt):
        """Oberstes Overlay unter dem Zeiger, oder None.

        Rueckwaerts, damit bei Ueberdeckung das zuletzt gezeichnete - also
        das obenliegende - gewinnt.
        """
        for ovl in reversed(self._sichtbare()):
            rechteck = self._rechteck(ovl)
            if rechteck is not None and rechteck.contains(punkt):
                return ovl
        return None

    def set_360_aktiv(self, aktiv):
        """Ob mit der Maus geschwenkt werden darf."""
        self._360_aktiv = bool(aktiv)
        if not self._360_aktiv:
            self._blick_von = None

    def _blick_zug_starten(self, punkt):
        """Einen 360-Zug beginnen. True, wenn er wirklich begonnen hat."""
        if not self._360_aktiv:
            return False
        self._blick_von = punkt
        self.setCursor(Qt.ClosedHandCursor)
        return True

    def mousePressEvent(self, ereignis):
        if ereignis.button() != Qt.LeftButton:
            super().mousePressEvent(ereignis)
            return
        punkt = ereignis.position().toPoint()
        if not self._overlays:
            # Ohne Overlays gibt es nichts zu treffen - direkt schwenken.
            if not self._blick_zug_starten(punkt):
                super().mousePressEvent(ereignis)
            return
        in_export = self._nach_export(punkt)
        if in_export is None:
            return

        griff = self._getroffener_griff(punkt)
        if griff is not None:
            ovl = self._nach_index(self._auswahl)
            if ovl is not None:
                self._modus = "skalieren"
                self._griff = griff
                self._start_maus = in_export
                self._start_rect = (ovl["x"], ovl["y"], ovl["w"], ovl["h"])
                self._zug_rect = self._start_rect
                self.update()
                return

        treffer = self._getroffenes_overlay(punkt)
        if treffer is None:
            # Daneben geklickt: Auswahl aufheben und - wenn 360 laeuft - den
            # Schwenk beginnen. Die Overlays behalten also den Vortritt.
            self._auswahl_setzen(-1)
            self.update()
            self._blick_zug_starten(punkt)
            return

        self._auswahl_setzen(treffer["index"])
        self._modus = "verschieben"
        self._griff = None
        self._start_maus = in_export
        self._start_rect = (treffer["x"], treffer["y"],
                            treffer["w"], treffer["h"])
        self._zug_rect = self._start_rect
        self.update()

    def mouseMoveEvent(self, ereignis):
        punkt = ereignis.position().toPoint()

        if self._blick_von is not None:
            weg = punkt - self._blick_von
            self._blick_von = punkt
            if weg.x() or weg.y():
                self.blick360Gezogen.emit(float(weg.x()), float(weg.y()))
            return

        if self._modus is None:
            self._zeiger_anpassen(punkt)
            super().mouseMoveEvent(ereignis)
            return

        jetzt = self._nach_export(punkt)
        if jetzt is None or self._start_rect is None:
            return
        x, y, w, h = self._start_rect

        if self._modus == "verschieben":
            dx = jetzt[0] - self._start_maus[0]
            dy = jetzt[1] - self._start_maus[1]
            self._zug_rect = (x + dx, y + dy, w, h)
        else:
            # Die gegenueberliegende Ecke bleibt stehen, das Verhaeltnis
            # bleibt erhalten. Der Faktor ergibt sich aus der groesseren der
            # beiden Strecken - so folgt das Rechteck dem Zeiger, egal in
            # welche Richtung gezogen wird.
            rechts, unten = self._griff
            fest_x = x if rechts else x + w
            fest_y = y if unten else y + h
            strecke_x = abs(jetzt[0] - fest_x)
            strecke_y = abs(jetzt[1] - fest_y)
            faktor = max(strecke_x / w if w else 0.0,
                         strecke_y / h if h else 0.0)
            neue_breite = max(self.MINDESTBREITE, w * faktor)
            neue_hoehe = neue_breite * h / w if w else h
            neu_x = fest_x if rechts else fest_x - neue_breite
            neu_y = fest_y if unten else fest_y - neue_hoehe
            self._zug_rect = (neu_x, neu_y, neue_breite, neue_hoehe)

        self.update()

    def mouseReleaseEvent(self, ereignis):
        if self._blick_von is not None:
            self._blick_von = None
            self.unsetCursor()
            return

        if self._modus is None or self._zug_rect is None:
            super().mouseReleaseEvent(ereignis)
            return

        ovl = self._nach_index(self._auswahl)
        modus, (x, y, w, _h) = self._modus, self._zug_rect
        start = self._start_rect
        self._modus = self._griff = self._start_maus = None
        self._zug_rect = self._start_rect = None
        self.update()

        if ovl is None or start is None:
            return
        # Ein Klick ohne echte Bewegung darf nichts veraendern - sonst
        # schreibt jedes Anwaehlen die Datei um.
        if (abs(x - start[0]) < 0.5 and abs(y - start[1]) < 0.5 and
                abs(w - start[2]) < 0.5):
            return

        neue_skalierung = ovl["scale"] * (w / start[2]) if start[2] else ovl["scale"]
        if modus == "verschieben":
            neue_skalierung = ovl["scale"]
        self.overlayGeaendert.emit(ovl["index"], int(round(x)), int(round(y)),
                                   float(neue_skalierung))

    def wheelEvent(self, ereignis):
        """Mausrad zoomt den 360-Blickwinkel."""
        if not self._360_aktiv:
            super().wheelEvent(ereignis)
            return
        # angleDelta ist in Achtelgrad, eine Raste sind 120 Achtelgrad.
        schritte = ereignis.angleDelta().y() / 120.0
        if schritte:
            self.blick360Gezoomt.emit(float(schritte))
        ereignis.accept()

    def keyPressEvent(self, ereignis):
        if ereignis.key() == Qt.Key_Escape and self._blick_von is not None:
            self._blick_von = None
            self.unsetCursor()
            return
        if ereignis.key() == Qt.Key_Escape and self._modus is not None:
            self._modus = self._griff = self._start_maus = None
            self._zug_rect = self._start_rect = None
            self.update()
            return
        super().keyPressEvent(ereignis)

    def enterEvent(self, ereignis):
        self._ueber_flaeche = True
        self.update()
        super().enterEvent(ereignis)

    def leaveEvent(self, ereignis):
        self._ueber_flaeche = False
        self.unsetCursor()
        self.update()
        super().leaveEvent(ereignis)

    def _nach_index(self, index):
        for ovl in self._overlays:
            if ovl["index"] == index:
                return ovl
        return None

    def _zeiger_anpassen(self, punkt):
        griff = self._getroffener_griff(punkt)
        if griff is not None:
            rechts, unten = griff
            self.setCursor(Qt.SizeFDiagCursor if rechts == unten
                           else Qt.SizeBDiagCursor)
        elif self._getroffenes_overlay(punkt) is not None:
            self.setCursor(Qt.SizeAllCursor)
        elif self._360_aktiv:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    # --------------------------------------------------------------- Zeichnen
    def paintEvent(self, event):
        maler = QPainter(self)
        maler.fillRect(self.rect(), QColor(0, 0, 0))
        if self._bild is None or self._bild.isNull():
            self._bildbereich = QRect()
            return

        flaeche = self.rect()
        bw, bh = self._bild.width(), self._bild.height()
        if bw <= 0 or bh <= 0 or flaeche.width() <= 0 or flaeche.height() <= 0:
            return

        # Seitenverhaeltnis halten, mittig, schwarze Balken aussen.
        skala = min(flaeche.width() / bw, flaeche.height() / bh)
        zw, zh = max(1, int(bw * skala)), max(1, int(bh * skala))
        ziel = QRect((flaeche.width() - zw) // 2, (flaeche.height() - zh) // 2,
                     zw, zh)
        if ziel != self._bildbereich:
            # Beim ersten Bild und bei jedem Wechsel des Seitenverhaeltnisses
            # springt der Bildbereich. Wer sich daran ausrichtet - etwa die
            # Hoehenprofil-Einblendung - muss davon erfahren; ein resizeEvent
            # gibt es dabei nicht.
            self._bildbereich = ziel
            self.bildbereichGeaendert.emit()
        maler.setRenderHint(QPainter.SmoothPixmapTransform, True)
        maler.drawImage(ziel, self._bild)

        self._overlays_zeichnen(maler)

    def _overlays_zeichnen(self, maler):
        """Rahmen und Anfasser.

        Ohne Maus ueber dem Bild und ohne Auswahl wird nichts gezeichnet -
        beim blossen Ansehen soll das Video nicht mit Hilfslinien zugestellt
        sein.
        """
        sichtbare = self._sichtbare()
        if not sichtbare or (not self._ueber_flaeche and self._auswahl < 0):
            return

        maler.setRenderHint(QPainter.Antialiasing, False)
        for ovl in sichtbare:
            rechteck = self._rechteck(ovl)
            if rechteck is None:
                continue
            ausgewaehlt = (ovl["index"] == self._auswahl)
            if not ausgewaehlt:
                if not self._ueber_flaeche:
                    continue
                maler.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.DashLine))
                maler.setBrush(Qt.NoBrush)
                maler.drawRect(rechteck)
                continue

            # Zweifarbig, damit der Rahmen auf hellem wie dunklem Bild sichtbar
            # bleibt.
            maler.setBrush(Qt.NoBrush)
            maler.setPen(QPen(QColor(0, 0, 0, 160), 3))
            maler.drawRect(rechteck)
            maler.setPen(QPen(QColor(255, 210, 0), 1))
            maler.drawRect(rechteck)

            maler.setPen(QPen(QColor(0, 0, 0, 200), 1))
            maler.setBrush(QColor(255, 210, 0))
            for ecke in self._griffpunkte(rechteck).values():
                maler.drawRect(QRectF(ecke.x() - self.GRIFF,
                                      ecke.y() - self.GRIFF,
                                      self.GRIFF * 2, self.GRIFF * 2))
