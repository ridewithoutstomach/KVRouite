# -*- coding: utf-8 -*-
#
# This file is part of KVRouite.
#
# Copyright (C) 2025 by Bernd Eller
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

# widgets/video_timeline_widget.py
import math

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor, QPolygon,
                          QLinearGradient, QWheelEvent)

def _nice_number(value: float) -> float:
    
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    f = value / (10 ** exp)
    if f < 2:
        nf = 1
    elif f < 5:
        nf = 2
    elif f < 10:
        nf = 5
    else:
        nf = 10
    return nf * (10 ** exp)

class VideoTimelineWidget(QWidget):
    markerMoved = Signal(float)
    overlayRemoveRequested = Signal(float, float)
    # Rechtsklick auf einen schwarzen Block: Blende <-> harte Kante
    cutHardToggleRequested = Signal(float, float)
    #: Zoom, Ausschnitt oder Breite haben sich geaendert - wer Bilder zu den
    #: sichtbaren Stellen vorhaelt, muss nachladen. Bewusst EIN Signal statt
    #: einer Meldung an jeder Stelle, die den Zoom oder den Versatz setzt:
    #: davon gibt es acht, und eine uebersehene waere ein Streifen, der
    #: gelegentlich nicht nachzieht.
    ansichtGeaendert = Signal()
    #: Ein Schnitt wurde mit der Maus verschoben: (alt_start, alt_ende,
    #: neu_start, neu_ende). Gemeldet wird erst beim Loslassen - waehrend des
    #: Ziehens wird nur gezeichnet. Ein Umzug kostet das Neurechnen der
    #: GPX-Spur und womoeglich eine neu gerenderte Blende; das je Pixel zu tun
    #: waere nicht zu bedienen.
    cutMoveRequested = Signal(float, float, float, float)
    #: Der ausgewaehlte Schnitt soll weg (Entf-Taste). Geloescht wird hier
    #: nicht: ob sich ein Schnitt zuruecknehmen laesst und was dabei mit der
    #: GPX-Spur geschieht, weiss nur das Fenster.
    cutDeleteRequested = Signal(float, float)
    #: Ein Overlay wurde gezogen: (alt_start, alt_ende, neu_start, neu_ende).
    #: Wie beim Schnitt erst beim Loslassen - waehrend des Ziehens wird nur
    #: gezeichnet.
    overlayMoveRequested = Signal(float, float, float, float)
    #: Rechtsklick auf ein Overlay. Frueher kam hier sofort die Frage
    #: "Remove Overlay?"; seit es mehr als eine Moeglichkeit gibt, stellt das
    #: Fenster ein Menue zusammen - so wie beim Schnitt auch.
    overlayMenuRequested = Signal(float, float, object)
    #: Das ausgewaehlte Overlay soll weg (Entf-Taste).
    overlayDeleteRequested = Signal(float, float)
    #: Rechtsklick auf einen Schnitt: das Fenster soll das Menue dazu zeigen.
    #: Was darin moeglich ist, weiss nur das MainWindow - ob es eine
    #: Aufzeichnung gibt, ob die GPX-Spur zwischenzeitlich bearbeitet wurde.
    cutMenuRequested = Signal(float, float, object)
    #: Rechtsklick auf eine Naht der Videoliste (die blaue Linie):
    #: (nummer, rohzeit, globale Position). Das Fenster stellt das Menue
    #: zusammen - Merge-Fade an, aus, Laenge.
    nahtMenuRequested = Signal(int, float, object)
    #: Rechtsklick auf ein Band (ab 7.0): (art, start, ende, globale
    #: Position); art "voice" (Sprechstelle, orange) oder "vehicle"
    #: (Fahrzeugstelle, blau). Das Fenster zeigt das Menue. Kommt nur auf
    #: Seite A des Video-Controls (set_bearbeitung("audio")).
    bandMenuRequested = Signal(str, float, float, object)
    #: Der Ansichtsknopf links oben wurde geschaltet: "off", "video",
    #: "audio", "beides". Das Fenster merkt sich das und holt Bilder.
    ansichtGewechselt = Signal(str)

    #: Reihenfolge des Ansichtsknopfs und seine Beschriftung.
    ANSICHTEN = ("off", "video", "audio", "beides")
    ANSICHT_TEXT = {"off": "-", "video": "Video", "audio": "Audio",
                    "beides": "V+A"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.total_duration = 0.0
        self._marker_position_s = 0.0
        self.boundaries = []
        # Merge-Fade je Naht: Nummer -> Laenge in Sekunden. Gesetzt vom
        # MainWindow, das Vorgabe und eingestellten Wert zusammenrechnet.
        # Eine Naht ohne Eintrag ist hart. Gezeichnet wird die Laenge als
        # Fluegel beiderseits der blauen Linie.
        self._merge_fades = {}
        # Die Naht unter dem Zeiger und die, deren Menue gerade offen ist.
        # Beide werden hervorgehoben: die blaue Linie ist drei Pixel breit,
        # die Trefferzone deutlich breiter - man soll sehen, dass man sie
        # gleich trifft.
        self._naht_unter_zeiger = None
        self._markierte_naht = None
        self.markB_time_s = -1.0
        self.markE_time_s = -1.0
        self._cut_intervals = []
        # Schluessel der Schnitte, die ohne Blende ausgefuehrt werden.
        # Wird vom VideoCutManager gesetzt, siehe set_hard_cut_keys().
        self._hard_cut_keys = set()
        # Blendenlaenge je Uebergang, in Sekunden, unter dem Schluessel des
        # zusammengefassten Bereichs. Gesetzt vom MainWindow - nur dort ist
        # bekannt, was Vorgabe, eingestellter Wert und harte Kante zusammen
        # ergeben.
        self._blenden_laengen = {}
        # Bereich, auf den gerade rechtsgeklickt wurde: (start_s, ende_s).
        # Er wird hervorgehoben, solange das Menue oder die Rueckfrage offen
        # ist - bei mehreren Schnitten dicht beieinander ist sonst nicht zu
        # sehen, welcher gemeint ist.
        self._markierter_bereich = None

        # Bildstreifen im Hintergrund. Gefuellt wird er von aussen (MainWindow
        # kennt die Playlist), hier wird nur gezeichnet.
        # Je Eintrag: (zeit_s in Gesamtzeit, QImage)
        self._vorschaubilder = []
        self._bilder_zeigen = True
        # Tonspur (ab 7.0): der Pegelverlauf je 100 ms in Gesamtzeit, als
        # Hintergrund ANSTELLE der Bilder gezeichnet - die Zeitleiste wird
        # dadurch nicht hoeher, sie wird umgeschaltet. Die Sprechstellen
        # (Baender des Voice Removers) werden in jedem Zustand gezeichnet.
        self._pegelkurve = []           # [(zeit_s, dB)]
        self._pegel_zeigen = False
        self._pegel_hinweis = ""        # Text, solange die Kurve noch gelesen wird
        self._sprechstellen = []        # [(von_s, bis_s)] in Gesamtzeit
        self._fahrzeugstellen = []      # [(von_s, bis_s)] in Gesamtzeit
        # Welche Seite das Video-Control zeigt: "video" - Rechtsklick
        # bedient Schnitt, Overlay, Naht; "audio" - nur die Sprechstellen.
        # So trifft man nie eine Aktion der anderen Seite.
        self._bearbeitung = "video"
        # Ansichtsknopf links oben: Nichts / Video / Audio / beides. Klein
        # und halb durchsichtig, er liegt auf dem Streifen.
        from PySide6.QtWidgets import QToolButton
        self._ansicht = "off"
        self._ansicht_knopf = QToolButton(self)
        self._ansicht_knopf.setToolTip(
            "Background of the timeline: nothing, video frames, sound "
            "level, or both. Click to switch.")
        self._ansicht_knopf.setAutoRaise(True)
        self._ansicht_knopf.setStyleSheet(
            "QToolButton { color: #dddddd; background: rgba(0,0,0,110); "
            "border: 1px solid #666666; border-radius: 3px; font-size: 8pt; "
            "padding: 0px 3px; }"
            "QToolButton:hover { background: rgba(60,60,60,200); }")
        self._ansicht_knopf.setFixedHeight(16)
        self._ansicht_knopf.move(3, 3)
        self._ansicht_knopf.clicked.connect(self._ansicht_weiter)
        self._ansicht_anwenden()
        self._dragging_marker = False
        self._dragging_timeline = False
        self._timeline_drag_start_x = 0
        self._horizontal_offset_start = 0
        self._marker_screen_x_at_drag_start = 0
        self._zoom_factor = 1.0
        self._min_zoom = 1.0
        self._max_zoom = 50.0
        self._horizontal_offset = 0
        self._scroll_speed_px = 50
        self.setStyleSheet("background-color: #333333;")
        self._overlay_intervals = []
        # Ein- und Ausblendlaenge je Overlay, in Sekunden, unter dem
        # Schluessel (start, ende). Beide liegen INNERHALB des Overlays.
        self._overlay_blenden = {}
        # Siehe set_overlays_wirksam: im Copy-Mode nur Rahmen statt Fuellung.
        self._overlays_wirksam = True
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        # ---- Schnitte mit der Maus verschieben --------------------------
        # Der laufende Umzug: welcher Schnitt, welche Kante, wo er gerade
        # laege. Solange _zieh_schnitt steht, wird nur gezeichnet.
        self._zieh_schnitt = None      # (start_s, ende_s) des Originals
        self._zieh_art = None          # "links", "rechts" oder "block"
        self._zieh_zeit_start = 0.0    # Zeit unter dem Zeiger beim Zugriff
        self._zieh_grenzen = (0.0, 0.0)
        self._zieh_neu = None          # (start_s, ende_s) der neuen Lage
        self._zieh_typ = "schnitt"     # "schnitt" oder "overlay"
        # Zeigerposition waehrend des Ziehens - daran haengt das Schild mit
        # der Verschiebung (siehe _draw_umzug). None, wenn nicht gezogen wird.
        self._zieh_maus = None
        # Feinstellung: nach dem Loslassen bleibt die neue Lage als Vorschau
        # stehen und laesst sich per Knopf und Pfeiltaste millisekundenweise
        # ruecken. Erst Haken/Enter fuehrt den Umzug aus - jeder Klick ein
        # ganzer Umzug (Ruecknahme, Neuschnitt, GPX, Undo-Schritt) waere zu
        # teuer. Gilt fuer Schnitte und Overlays gleich, _zieh_typ sagt
        # welches. _fein_knoepfe: Name -> QRectF der gezeichneten Knoepfe.
        self._fein = False
        self._fein_knoepfe = {}
        self._zeiger_form = None

        # Der ausgewaehlte Schnitt, (start_s, ende_s) oder None. Angeklickt
        # wird er, Entf nimmt ihn zurueck. Bewusst getrennt von
        # _markierter_bereich: der zeigt nur, welcher Schnitt gerade ein
        # Menue offen hat, und verschwindet sofort wieder.
        self._gewaehlter_schnitt = None
        # Dasselbe fuer Overlays. Ausgewaehlt ist immer nur EINES von beiden:
        # Entf muss eindeutig sein, sonst weiss niemand, was gleich
        # verschwindet.
        self._gewaehltes_overlay = None

        # Zwei Auskuenfte, die nur das MainWindow geben kann: in welchem
        # Bereich ein Schnitt liegen darf und ob er ueberhaupt umziehen darf.
        # Bewusst als schlichte Rueckrufe und nicht als eigene Regeln hier:
        # sonst staenden dieselben Bedingungen an zwei Stellen und wuerden
        # auseinanderlaufen. Gesetzt werden sie im MainWindow.
        self.grenzen_geber = None      # (start, ende) -> (links, rechts, art)
        self.umzug_pruefer = None      # (start, ende) -> (moeglich, grund)
        #: (start, ende) -> (frueh, spaet). Wo ein Overlay liegen darf,
        #: entscheidet der OverlayManager: es muss in EIN Keep-Segment passen
        #: und den Platz der Blenden freilassen.
        self.overlay_grenzen_geber = None

        # Ohne das kommt mouseMoveEvent nur bei gedrueckter Taste - die
        # Zeigerform ueber einer Kante braucht es aber vorher.
        self.setMouseTracking(True)
        # Ohne Fokus keine Tastatur: Entf kaeme nie hier an.
        self.setFocusPolicy(Qt.StrongFocus)
        
    def clear_all_cuts(self):
        """
        Entfernt alle Cut-Intervalle aus der Timeline.
        """
        self._cut_intervals = []
        self._hard_cut_keys = set()
        self._blenden_laengen = {}
        self._fein_abbrechen("schnitt")
        # Die Auswahl zeigte auf einen Schnitt, den es gleich nicht mehr gibt.
        # Jede Aenderung an den Schnitten laeuft hier durch - Zuruecknehmen,
        # Verschieben, Laden -, damit kann keine veraltete Auswahl stehen
        # bleiben.
        self._gewaehlter_schnitt = None
        self.update()

    def set_hard_cut_keys(self, keys):
        """Schnitte markieren, die ohne Blende ausgefuehrt werden.

        keys enthaelt (start, end)-Paare, gerundet auf 3 Nachkommastellen
        (VideoCutManager._cut_key).
        """
        self._hard_cut_keys = set(keys or ())
        self.update()

    def set_blenden_laengen(self, eintraege):
        """Blendenlaenge je Uebergang: [(start_s, ende_s, sekunden), ...].

        Die Zeitleiste zeichnet damit nicht nur den Schnitt, sondern auch die
        Ueberblendung darum herum. Eine Blende liegt MITTIG auf der Kante: je
        die halbe Laenge liegt VOR dem Schnittanfang und HINTER dem
        Schnittende, in Material, das im fertigen Video zu sehen ist. Dieser
        Platz ist belegt - dort noch einen Schnitt zu setzen geht schief, und
        das soll man sehen, bevor man es tut.

        Die Schluessel sind die der zusammengefassten Bereiche: aneinander
        stossende Schnitte sind im Video EIN Uebergang mit EINER Blende.
        """
        neu = {}
        for eintrag in (eintraege or []):
            try:
                a, b, sek = eintrag[0], eintrag[1], float(eintrag[2])
            except (TypeError, IndexError, ValueError):
                continue
            if sek > 0:
                neu[self._cut_key(a, b)] = sek
        if neu != self._blenden_laengen:
            self._blenden_laengen = neu
            self.update()

    @staticmethod
    def _cut_key(start_s, end_s):
        return (round(float(start_s), 3), round(float(end_s), 3))
    
        
    def add_overlay_interval(self, start_s: float, end_s: float):
        """
        Speichert ein Overlay-Zeitintervall, damit wir es in Blau markieren können.
        """
        self._overlay_intervals.append((start_s, end_s))
        self.update()

    def clear_overlay_intervals(self):
        self._overlay_intervals.clear()
        self._overlay_blenden = {}
        self._fein_abbrechen("overlay")
        # Die Auswahl zeigte auf ein Overlay, das es gleich nicht mehr gibt.
        self._gewaehltes_overlay = None
        self.update()

    def set_overlay_blenden(self, eintraege):
        """Ein- und Ausblendlaenge je Overlay: [(start, ende, ein, aus), ...].

        Anders als bei einem Schnitt liegen diese Blenden INNERHALB des
        Balkens: ein Overlay blendet an seinem eigenen Anfang ein und an
        seinem Ende aus. Gezeichnet werden sie deshalb als Rampen im Balken
        und nicht als Fluegel daneben.
        """
        neu = {}
        for eintrag in (eintraege or []):
            try:
                a, b = eintrag[0], eintrag[1]
                ein, aus = float(eintrag[2] or 0), float(eintrag[3] or 0)
            except (TypeError, IndexError, ValueError):
                continue
            if ein > 0 or aus > 0:
                neu[self._cut_key(a, b)] = (ein, aus)
        if neu != self._overlay_blenden:
            self._overlay_blenden = neu
            self.update()

    def set_overlays_wirksam(self, wirksam: bool):
        """Ob die Overlays im aktuellen Modus ueberhaupt im Export landen.

        Nur im Encode-Mode tun sie das. Im Copy-Mode wird das Material
        durchgereicht, ein Logo kommt im Ergebnis nicht vor - dann wird der
        Balken nur als Rahmen gezeichnet, ohne Fuellung. Gleiche Lage,
        gleiche Farbe, aber sichtbar leer: das Overlay ist da, es wirkt hier
        nur nicht.
        """
        wirksam = bool(wirksam)
        if wirksam != self._overlays_wirksam:
            self._overlays_wirksam = wirksam
            self.update()
    

    def set_marker_position(self, time_s: float):
        if self.total_duration <= 0:
            self._marker_position_s = 0.0
            return
        if time_s < 0:
            time_s = 0
        if time_s > self.total_duration:
            time_s = self.total_duration
        self._marker_position_s = time_s
        self._keep_marker_visible()
        self.update()

    def marker_position(self) -> float:
        return self._marker_position_s

    def _update_marker_by_mouse_x(self, x_mouse: int):
        w = self.width()
        if w <= 0 or self.total_duration <= 0:
            return
        timeline_real_width = w * self._zoom_factor
        x_timeline = x_mouse + self._horizontal_offset
        if x_timeline < 0:
            x_timeline = 0
        if x_timeline > timeline_real_width:
            x_timeline = timeline_real_width
        ratio = x_timeline / timeline_real_width if timeline_real_width > 0 else 0.0
        new_time_s = ratio * self.total_duration
        self.set_marker_position(new_time_s)
        self.markerMoved.emit(new_time_s)

    def _offset_begrenzen(self):
        """Den sichtbaren Ausschnitt in die Zeitleiste zwingen.

        Sichtbar ist [offset, offset + Fensterbreite] von einer Zeitleiste
        der Breite Fensterbreite * Zoom. Damit weder links vor 0 noch rechts
        hinter dem Ende Leere zu sehen ist, muss gelten:

            0 <= offset <= Fensterbreite * Zoom - Fensterbreite

        Bei Zoom 1.0 ist die rechte Grenze 0, der Offset also zwingend 0:
        ganz herausgezoomt ist IMMER alles zu sehen, egal wo der Marker
        steht und was vorher gezogen wurde.

        Bis zum 04.09.2026 wurde nur die Untergrenze geprueft, und die auch
        nicht ueberall. Folge: nach Abspielen und Herauszoomen setzte
        _center_marker_at_ratio() einen positiven Offset, obwohl die ganze
        Zeitleiste ins Fenster passte - links fehlte der Anfang, rechts war
        es schwarz. Beim Ziehen mit der Maus fehlte jede Grenze, damit
        rutschte der Anfang der Zeitleiste in die Fenstermitte und links
        davon stand tote Zeit. Und nichts fuehrte je wieder auf 0 zurueck.
        """
        w = self.width()
        hoechstens = max(0.0, w * self._zoom_factor - w)
        self._horizontal_offset = max(0.0, min(float(self._horizontal_offset),
                                               hoechstens))

    def _keep_marker_visible(self):
        w = self.width()
        if w <= 0 or self.total_duration <= 0:
            return
        timeline_real_width = w * self._zoom_factor
        ratio = self._marker_position_s / self.total_duration
        marker_x = ratio * timeline_real_width - self._horizontal_offset
        if marker_x < 0:
            self._horizontal_offset = ratio * timeline_real_width
            self._offset_begrenzen()
            return
        right_threshold = 0.95 * w
        left_position = 0.05 * w
        if marker_x > right_threshold:
            if ratio < 0.95:
                shift = marker_x - left_position
                self._horizontal_offset += shift
        self._offset_begrenzen()

    def set_total_duration(self, dur_s: float):
        self.total_duration = max(0.0, dur_s)
        if self._marker_position_s > self.total_duration:
            self._marker_position_s = self.total_duration
        self._keep_marker_visible()
        self.update()

    def set_boundaries(self, boundary_list):
        self.boundaries = boundary_list

    def set_merge_fades(self, eintraege):
        """Merge-Fade je Naht: {nummer: sekunden}. Fehlt eine Naht, ist sie hart."""
        neu = {}
        for naht, sekunden in (eintraege or {}).items():
            try:
                if float(sekunden) > 0:
                    neu[int(naht)] = float(sekunden)
            except (TypeError, ValueError):
                continue
        if neu != self._merge_fades:
            self._merge_fades = neu
            self.update()

    #: Wie nah der Zeiger an einer Naht sein muss, um sie zu treffen. In
    #: Pixeln, nicht in Sekunden: die Trefferzone ist damit bei jedem Zoom
    #: gleich breit. Bewusst mehr als _KANTE_PX: eine Naht ist eine Linie
    #: ohne Block daneben, an dem man sonst noch fassen koennte.
    _NAHT_PX = 10

    def _naehte(self):
        """(nummer, rohzeit) je Naht - nur die INNEREN Grenzen.

        self.boundaries traegt die kumulierten Dauern, der letzte Eintrag ist
        das Videoende und keine Naht.
        """
        gesamt = self.total_duration
        return [(i, float(b)) for i, b in enumerate(self.boundaries)
                if 0.0 < float(b) < gesamt - 1e-6]

    def _naht_unter(self, x_mouse):
        """Welche Naht liegt unter dem Zeiger? (nummer, rohzeit) oder (None, None)."""
        if self.total_duration <= 0:
            return None, None
        beste = None
        for (naht, zeit) in self._naehte():
            abstand = abs(x_mouse - self._x_bei_zeit(zeit))
            if abstand <= self._NAHT_PX and (beste is None or abstand < beste[0]):
                beste = (abstand, naht, zeit)
        if beste is None:
            return None, None
        return beste[1], beste[2]

    def _naht_markieren(self, naht):
        """Naht hervorheben (None loescht), solange ihr Menue offen ist."""
        self._markierte_naht = naht
        self.update()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        self.update()

    def set_markB_time(self, time_s: float):
        self.markB_time_s = time_s
        self.update()

    def set_markE_time(self, time_s: float):
        self.markE_time_s = time_s
        self.update()

    def add_cut_interval(self, start_s: float, end_s: float):
        self._cut_intervals.append((start_s, end_s))
        self.update()

    def remove_last_cut_interval(self):
        if self._cut_intervals:
            self._cut_intervals.pop()
            self._fein_abbrechen("schnitt")
            self.update()

    # ------------------------------------------------------------------
    # Schnitte mit der Maus verschieben
    # ------------------------------------------------------------------
    #: Wie nah der Zeiger an einer Kante sein muss, um sie zu fassen.
    _KANTE_PX = 5
    #: Kuerzer darf ein Schnitt beim Ziehen nicht werden. on_cut_clicked()
    #: weist alles unter 0.01 s ohnehin ab; hier etwas mehr Luft, damit ein
    #: Schnitt nicht versehentlich auf Pixelbreite zusammenfaellt.
    _MIN_LAENGE_S = 0.05

    def _zeit_bei_x(self, x_mouse):
        """Bildschirm-x zu Rohzeit, oder None ausserhalb der Zeitleiste."""
        w = self.width()
        if w <= 0 or self.total_duration <= 0:
            return None
        breite = w * self._zoom_factor
        if breite <= 0:
            return None
        x = x_mouse + self._horizontal_offset
        x = max(0.0, min(float(x), breite))
        return (x / breite) * self.total_duration

    def _x_bei_zeit(self, zeit_s):
        """Rohzeit zu Bildschirm-x. Gegenstueck zu _zeit_bei_x()."""
        w = self.width()
        if w <= 0 or self.total_duration <= 0:
            return 0.0
        breite = w * self._zoom_factor
        return (float(zeit_s) / self.total_duration) * breite \
            - self._horizontal_offset

    def _kante_unter(self, x_mouse):
        """Was liegt unter dem Zeiger? ((start, ende), art) oder (None, None).

        art ist "links", "rechts" oder "block". Kanten werden in einem
        eigenen Durchgang zuerst gesucht: stossen zwei Schnitte aneinander,
        laege die gemeinsame Kante sonst im Block des einen und waere nicht
        mehr zu fassen.
        """
        for (a, b) in self._cut_intervals:
            if abs(x_mouse - self._x_bei_zeit(a)) <= self._KANTE_PX:
                return (a, b), "links"
            if abs(x_mouse - self._x_bei_zeit(b)) <= self._KANTE_PX:
                return (a, b), "rechts"
        for (a, b) in self._cut_intervals:
            if self._x_bei_zeit(a) <= x_mouse <= self._x_bei_zeit(b):
                return (a, b), "block"
        return None, None

    def _schnitt_waehlen(self, schnitt):
        """Schnitt auswaehlen oder mit None abwaehlen. Hebt eine
        Overlay-Auswahl auf - es ist immer nur eines ausgewaehlt."""
        if schnitt == self._gewaehlter_schnitt and (
                schnitt is None or self._gewaehltes_overlay is None):
            return
        self._gewaehlter_schnitt = schnitt
        if schnitt is not None:
            self._gewaehltes_overlay = None
        self.update()

    def _overlay_waehlen(self, overlay):
        """Overlay auswaehlen oder mit None abwaehlen."""
        if overlay == self._gewaehltes_overlay and (
                overlay is None or self._gewaehlter_schnitt is None):
            return
        self._gewaehltes_overlay = overlay
        if overlay is not None:
            self._gewaehlter_schnitt = None
        self.update()

    def _overlay_unter(self, x_mouse):
        """Wie _kante_unter(), nur fuer die blauen Overlay-Balken."""
        for (a, b) in self._overlay_intervals:
            if abs(x_mouse - self._x_bei_zeit(a)) <= self._KANTE_PX:
                return (a, b), "links"
            if abs(x_mouse - self._x_bei_zeit(b)) <= self._KANTE_PX:
                return (a, b), "rechts"
        for (a, b) in self._overlay_intervals:
            if self._x_bei_zeit(a) <= x_mouse <= self._x_bei_zeit(b):
                return (a, b), "block"
        return None, None

    def _zeiger_setzen(self, form):
        """Zeigerform nur bei Aenderung setzen - das laeuft bei jeder
        Mausbewegung durch."""
        if form == self._zeiger_form:
            return
        self._zeiger_form = form
        if form is None:
            self.unsetCursor()
        else:
            self.setCursor(form)

    def _hinweis(self, global_pos, text):
        """Kurzer Hinweis am Zeiger, warum gerade nichts passiert.

        Ohne Position - etwa aus einer Pruefung heraus aufgerufen - bleibt es
        beim Protokoll. QToolTip.showText() wirft bei None.
        """
        if global_pos is None:
            print("[CUT-MOVE] " + text.replace(chr(10), " "))
            return
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(global_pos, text, self)

    def _umzug_beginnen(self, schnitt, art, x_mouse, global_pos,
                        typ="schnitt"):
        """Umzug vorbereiten. False heisst: es bleibt beim Marker.

        Schnitt und Overlay teilen sich diese Mechanik. Verschieden sind nur
        die Anschlaege und die Frage, ob eine Kante festliegt: ein Overlay hat
        keine feste Kante, es muss nur in sein Keep-Segment passen.
        """
        a0, b0 = schnitt

        if typ == "overlay":
            if self.overlay_grenzen_geber is None:
                return False
            frueh, spaet = self.overlay_grenzen_geber(a0, b0)
            if spaet - frueh < self._MIN_LAENGE_S:
                self._hinweis(global_pos,
                              "There is no room to move this overlay: the "
                              "crossfades take up the space next to it.")
                return False
            zeit = self._zeit_bei_x(x_mouse)
            if zeit is None:
                return False
            self._zieh_typ = "overlay"
            self._zieh_schnitt = (float(a0), float(b0))
            self._zieh_art = art
            self._zieh_zeit_start = zeit
            self._zieh_grenzen = (float(frueh), float(spaet))
            self._zieh_neu = (float(a0), float(b0))
            self._zeiger_setzen(Qt.SizeAllCursor if art == "block"
                                else Qt.SizeHorCursor)
            self.update()
            return True

        if self.grenzen_geber is None:
            return False

        if self.umzug_pruefer is not None:
            erlaubt, grund = self.umzug_pruefer(a0, b0)
            if not erlaubt:
                # Diese Pruefung rechnet einen Abdruck ueber die ganze
                # GPX-Spur. Fuer jede Mausbewegung waere das zu teuer, deshalb
                # steht sie hier beim Zugriff und nicht schon beim Wechsel der
                # Zeigerform.
                self._hinweis(global_pos,
                              grund or "This cut cannot be moved.")
                return False

        links, rechts, schnittart = self.grenzen_geber(a0, b0)

        # Anfangs- und Endschnitt haben je eine feste Kante. Sie zu loesen
        # hiesse, die Art des Schnitts zu aendern: der Endschnitt wird vor dem
        # Zusammenfuegen weggetrimmt, der Anfangsschnitt verschiebt zusaetzlich
        # die Zeitachse. Beides soll nicht beilaeufig durch Ziehen passieren.
        if schnittart == "ende" and art in ("rechts", "block"):
            self._hinweis(
                global_pos,
                "The last cut always reaches the end of the video.\n"
                "Only its beginning can be moved.")
            return False
        if schnittart == "anfang" and art in ("links", "block"):
            self._hinweis(
                global_pos,
                "The first cut always starts at the beginning of the video.\n"
                "Only its end can be moved.")
            return False

        zeit = self._zeit_bei_x(x_mouse)
        if zeit is None:
            return False

        self._zieh_typ = "schnitt"
        self._zieh_schnitt = (float(a0), float(b0))
        self._zieh_art = art
        self._zieh_zeit_start = zeit
        self._zieh_grenzen = (float(links), float(rechts))
        self._zieh_neu = (float(a0), float(b0))
        # Das Schild steht schon beim Anfassen (mit +0.000 s), nicht erst
        # nach der ersten Bewegung.
        self._zieh_maus = (self.mapFromGlobal(global_pos)
                           if global_pos is not None else None)
        self._zeiger_setzen(Qt.SizeAllCursor if art == "block"
                            else Qt.SizeHorCursor)
        self.update()
        return True

    def _umzug_aktualisieren(self, x_mouse, pos=None):
        """Neue Lage aus der Mausposition. Rechnet nur, zeichnet nur.

        pos ist der ganze Zeigerpunkt; daran haengt das Schild mit der
        Verschiebung. Es wandert auch dann mit, wenn die Lage sich nicht
        mehr aendert, weil ein Anschlag erreicht ist.
        """
        if pos is not None and pos != self._zieh_maus:
            self._zieh_maus = QPoint(pos)
            self.update()
        zeit = self._zeit_bei_x(x_mouse)
        if zeit is None or self._zieh_schnitt is None:
            return
        a0, b0 = self._zieh_schnitt
        links, rechts = self._zieh_grenzen
        delta = zeit - self._zieh_zeit_start
        mind = self._MIN_LAENGE_S

        if self._zieh_art == "links":
            a = min(max(a0 + delta, links), b0 - mind)
            b = b0
        elif self._zieh_art == "rechts":
            a = a0
            b = max(min(b0 + delta, rechts), a0 + mind)
        else:
            laenge = b0 - a0
            a = min(max(a0 + delta, links), rechts - laenge)
            b = a + laenge

        neu = (a, b)
        if neu != self._zieh_neu:
            self._zieh_neu = neu
            self.update()

    # ------------------------------------------------------------------
    # Feinstellung nach dem Ziehen
    # ------------------------------------------------------------------
    @staticmethod
    def _fein_schritt(modifiers):
        """Schrittweite je Taste: ohne 1 ms, Shift 10 ms, Alt 100 ms. Strg
        bleibt frei - Strg+Pfeil dreht im Fenster den 360-Blick."""
        if modifiers & Qt.AltModifier:
            return 0.1
        if modifiers & Qt.ShiftModifier:
            return 0.01
        return 0.001

    def _fein_beginnen(self):
        """Vom Ziehen in die Feinstellung: Zustand bleibt, Maus loslassen."""
        self._fein = True
        self._zieh_maus = None
        self._zeiger_setzen(None)
        self.setFocus()
        self.update()

    def _fein_zuruecksetzen(self):
        self._fein = False
        self._fein_knoepfe = {}
        self._zieh_schnitt = None
        self._zieh_neu = None
        self._zieh_art = None
        self._zieh_maus = None
        self._zeiger_setzen(None)

    def _fein_abbrechen(self, typ=None):
        """Vorschau verwerfen, nichts wird verschoben.

        typ "schnitt" oder "overlay" bricht nur eine Feinstellung dieses
        Typs ab: werden die Overlays neu gezeichnet, soll eine offene
        Schnitt-Vorschau davon nichts merken - und umgekehrt.
        """
        if not self._fein:
            return
        if typ is not None and typ != self._zieh_typ:
            return
        self._fein_zuruecksetzen()
        self.update()

    def _fein_anwenden(self):
        """Den Umzug ausfuehren - EIN Signal, EIN Schritt fuer Strg+Z."""
        if not self._fein or self._zieh_schnitt is None:
            return
        a0, b0 = self._zieh_schnitt
        a, b = self._zieh_neu or (a0, b0)
        typ = self._zieh_typ
        self._fein_zuruecksetzen()
        self.update()
        if abs(a - a0) < 0.0005 and abs(b - b0) < 0.0005:
            return
        if typ == "overlay":
            self.overlayMoveRequested.emit(a0, b0, round(a, 3), round(b, 3))
        else:
            self.cutMoveRequested.emit(a0, b0, round(a, 3), round(b, 3))

    def _fein_ruecken(self, schritt_s):
        """Vorschau um schritt_s ruecken, mit denselben Anschlaegen wie beim
        Ziehen: Nachbarn, Mindestlaenge, feste Kante."""
        if not self._fein or self._zieh_neu is None:
            return
        a0, b0 = self._zieh_schnitt
        a, b = self._zieh_neu
        links, rechts = self._zieh_grenzen
        mind = self._MIN_LAENGE_S
        if self._zieh_art == "links":
            a = min(max(a + schritt_s, links), b0 - mind)
        elif self._zieh_art == "rechts":
            b = max(min(b + schritt_s, rechts), a0 + mind)
        else:
            laenge = b0 - a0
            a = min(max(a + schritt_s, links), rechts - laenge)
            b = a + laenge
        # Auf ganze Millisekunden, sonst sammeln sich Rundungsreste.
        neu = (round(a, 3), round(b, 3))
        if neu != self._zieh_neu:
            self._zieh_neu = neu
            self.update()

    def _fein_kante_x(self):
        """Bildschirm-x der Kante, die gerade bewegt wird."""
        a, b = self._zieh_neu
        return self._x_bei_zeit(b if self._zieh_art == "rechts" else a)

    def _fein_im_block(self, x_mouse):
        """Liegt x im Block der Vorschau? Nur beim Block-Umzug von Belang."""
        if self._zieh_art != "block" or self._zieh_neu is None:
            return False
        a, b = self._zieh_neu
        return self._x_bei_zeit(a) <= x_mouse <= self._x_bei_zeit(b)

    def _fein_knopf_unter(self, pos):
        for name, r in self._fein_knoepfe.items():
            if r.contains(QPointF(pos)):
                return name
        return None

    def _fein_wieder_ziehen(self, x_mouse, pos):
        """Aus der Feinstellung heraus die Kante erneut mit der Maus fassen.

        Der Nullpunkt wird so gelegt, dass die Vorschau beim ersten Ruck
        nicht springt: die bisherige Verschiebung bleibt erhalten.
        """
        zeit = self._zeit_bei_x(x_mouse)
        if zeit is None:
            return False
        a0, b0 = self._zieh_schnitt
        a, b = self._zieh_neu
        bisher = (b - b0) if self._zieh_art == "rechts" else (a - a0)
        self._zieh_zeit_start = zeit - bisher
        self._fein = False
        self._fein_knoepfe = {}
        self._zieh_maus = QPoint(pos)
        self._zeiger_setzen(Qt.SizeAllCursor if self._zieh_art == "block"
                            else Qt.SizeHorCursor)
        self.update()
        return True

    def _draw_fein(self, painter, w, h, farbe):
        """Die Leiste der Feinstellung neben der bewegten Kante:
        [<] [>]  Lage  Verschiebung  [Haken] [Kreuz]."""
        from PySide6.QtGui import QPolygonF
        a0, b0 = self._zieh_schnitt
        a, b = self._zieh_neu
        if self._zieh_art == "links":
            lage = "Start %.3f s" % a
            delta = a - a0
        elif self._zieh_art == "rechts":
            lage = "End %.3f s" % b
            delta = b - b0
        else:
            lage = "%.3f - %.3f s" % (a, b)
            delta = a - a0
        schub = "%+.3f s" % delta

        fm = painter.fontMetrics()
        hoehe = fm.height() + 10
        q = hoehe - 6                      # Knopfkante
        luecke = 6
        b_lage = fm.horizontalAdvance(lage)
        b_schub = fm.horizontalAdvance(schub)
        breite = (3 + 2 * (q + luecke) + luecke + b_lage + 2 * luecke
                  + b_schub + 3 * luecke + 2 * (q + luecke) + 3 - luecke)

        kante_x = self._fein_kante_x()
        x = kante_x + 12
        if x + breite > w:
            x = max(0.0, kante_x - 12 - breite)
        y = max(0.0, (h - hoehe) / 2.0)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 225))
        painter.drawRect(QRectF(x, y, breite, hoehe))
        painter.setPen(QPen(farbe, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(x, y, breite, hoehe))

        knoepfe = {}
        lauf = [x + 3]

        def knopf(name):
            r = QRectF(lauf[0], y + 3, q, q)
            knoepfe[name] = r
            painter.setPen(QPen(farbe, 1))
            painter.setBrush(QColor(255, 204, 0, 40))
            painter.drawRect(r)
            lauf[0] += q + luecke
            return r

        d = q * 0.28

        def pfeil(r, nach_rechts):
            m = r.center()
            if nach_rechts:
                pts = [QPointF(m.x() - d, m.y() - d), QPointF(m.x() + d, m.y()),
                       QPointF(m.x() - d, m.y() + d)]
            else:
                pts = [QPointF(m.x() + d, m.y() - d), QPointF(m.x() - d, m.y()),
                       QPointF(m.x() + d, m.y() + d)]
            painter.setPen(Qt.NoPen)
            painter.setBrush(farbe)
            painter.drawPolygon(QPolygonF(pts))

        pfeil(knopf("zurueck"), False)
        pfeil(knopf("vor"), True)

        lauf[0] += luecke
        y_text = y + 5 + fm.ascent()
        painter.setPen(farbe)
        painter.drawText(QPointF(lauf[0], y_text), lage)
        lauf[0] += b_lage + 2 * luecke
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QPointF(lauf[0], y_text), schub)
        lauf[0] += b_schub + 3 * luecke

        r = knopf("ok")
        m = r.center()
        painter.setPen(QPen(QColor("#7CFC00"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(QPolygonF([QPointF(m.x() - d, m.y()),
                                        QPointF(m.x() - d * 0.2, m.y() + d),
                                        QPointF(m.x() + d, m.y() - d)]))
        r = knopf("abbruch")
        m = r.center()
        painter.setPen(QPen(QColor("#ff5555"), 2))
        painter.drawLine(QPointF(m.x() - d, m.y() - d),
                         QPointF(m.x() + d, m.y() + d))
        painter.drawLine(QPointF(m.x() - d, m.y() + d),
                         QPointF(m.x() + d, m.y() - d))

        self._fein_knoepfe = knoepfe

    @staticmethod
    def _zeit_kurz(sekunden):
        s = max(0.0, float(sekunden))
        return "%d:%04.1f" % (int(s // 60), s % 60)

    def _draw_umzug(self, painter, w, h):
        """Die neue Lage waehrend des Ziehens: Rahmen und Zeiten.

        Der schwarze Block bleibt derweil an seiner alten Stelle stehen. So
        ist beim Ziehen zu sehen, WOHIN es geht und woher es kam - ein
        mitwanderender Block zeigte nur noch das eine.
        """
        if self._zieh_neu is None or self.total_duration <= 0:
            return
        a, b = self._zieh_neu
        x0 = self._x_bei_zeit(a)
        x1 = self._x_bei_zeit(b)
        if x1 < 0 or x0 > w:
            return

        painter.save()
        try:
            farbe = QColor("#ffcc00")
            painter.setPen(QPen(farbe, 2))
            painter.setBrush(QColor(255, 204, 0, 45))
            painter.drawRect(QRectF(x0, 0, max(1.0, x1 - x0), h - 1))

            text = "%s - %s  (%.1fs)" % (self._zeit_kurz(a),
                                         self._zeit_kurz(b), b - a)
            breite_text = painter.fontMetrics().horizontalAdvance(text) + 8
            x_text = x0 + 4
            if x_text + breite_text > w:
                x_text = max(0.0, w - breite_text)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.drawRect(QRectF(x_text - 4, 2, breite_text, 16))
            painter.setPen(farbe)
            painter.drawText(QPointF(x_text, 14), text)
            if self._fein:
                self._draw_fein(painter, w, h, farbe)
            else:
                self._draw_umzug_schild(painter, w, h, farbe)
        finally:
            painter.restore()

    def _draw_umzug_schild(self, painter, w, h, farbe):
        """Das Schild am Zeiger: WIE WEIT wird gerade verschoben?

        Der Rahmen oben zeigt die neue Lage grob (Zehntelsekunden). Beim
        Feinziehen um wenige Millisekunden ist daran nichts zu erkennen,
        deshalb hier am Zeiger die bewegte Kante auf die Millisekunde und
        der Unterschied zur alten Lage mit Vorzeichen, nur in Sekunden -
        eine zweite Angabe in ms daneben war doppelt. Beim Block wandern
        beide Kanten um denselben Betrag, dann stehen beide vorn.

        Gilt fuer Schnitte und Overlays gleichermassen - wer einen Schnitt
        auf die Millisekunde setzen kann, erwartet das beim Overlay auch.

        Die Tausendstel passen zu round(a, 3) beim Loslassen - genauer
        wird der Schnitt ohnehin nicht uebernommen.

        Einzeilig und auf Zeigerhoehe: die Leiste ist nur gut 80 px hoch,
        ein Schild ueber dem Zeiger laege in der Zeile oben.
        """
        if self._zieh_maus is None or self._zieh_schnitt is None:
            return
        a0, b0 = self._zieh_schnitt
        a, b = self._zieh_neu
        if self._zieh_art == "links":
            lage = "Start %.3f s" % a
            delta = a - a0
        elif self._zieh_art == "rechts":
            lage = "End %.3f s" % b
            delta = b - b0
        else:
            lage = "%.3f - %.3f s" % (a, b)
            delta = a - a0
        schub = "%+.3f s" % delta

        fm = painter.fontMetrics()
        b_lage = fm.horizontalAdvance(lage)
        b_schub = fm.horizontalAdvance(schub)
        luecke = fm.horizontalAdvance("   ")
        breite = b_lage + luecke + b_schub + 10
        hoehe = fm.height() + 6

        # Rechts neben dem Zeiger, damit die Hand nichts verdeckt; wo rechts
        # kein Platz ist, links davon. Oben und unten im Fenster halten.
        mx, my = self._zieh_maus.x(), self._zieh_maus.y()
        x = mx + 16
        if x + breite > w:
            x = max(0.0, mx - 16 - breite)
        y = my - hoehe / 2.0
        y = max(0.0, min(y, h - hoehe))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 210))
        painter.drawRect(QRectF(x, y, breite, hoehe))
        painter.setPen(QPen(farbe, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(x, y, breite, hoehe))
        y_text = y + 3 + fm.ascent()
        painter.setPen(farbe)
        painter.drawText(QPointF(x + 5, y_text), lage)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QPointF(x + 5 + b_lage + luecke, y_text), schub)

    def _schieben_beginnen(self, x_mouse):
        """Das Verschieben des sichtbaren Ausschnitts anfangen (Shift + links).

        Bis zum 04.09.2026 lag das auf der rechten Maustaste - und dort lag
        seit dem Vortag auch das Kontextmenue. Die beiden vertragen sich
        nicht, und zwar je nach System verschieden: Windows schickt das
        Kontextmenue beim Loslassen (nach dem Schieben springt das Menue
        auf), macOS und Linux beim Druecken (das Menue kommt sofort, das
        Schieben nie). Deshalb jetzt Shift + linke Taste: Shift heisst in
        dieser Zeitleiste ohnehin "horizontal bewegen" (Shift + Rad), Strg
        heisst "Zoom" (Strg + Rad), und die rechte Taste heisst nur noch
        Menue. Jede Taste eine Bedeutung.
        """
        self._dragging_timeline = True
        self._timeline_drag_start_x = x_mouse
        self._horizontal_offset_start = self._horizontal_offset
        w = self.width()
        if w > 0 and self.total_duration > 0:
            timeline_real_width = w * self._zoom_factor
            marker_x_current = (self._marker_position_s / self.total_duration) \
                * timeline_real_width - self._horizontal_offset
            self._marker_screen_x_at_drag_start = marker_x_current
        else:
            self._marker_screen_x_at_drag_start = 0

    def mousePressEvent(self, event):
        if self._fein:
            # Feinstellung offen: Knoepfe, die Kante nochmal fassen - sonst
            # nichts. Ein Klick daneben soll die Arbeit weder verwerfen noch
            # ausfuehren; dafuer gibt es Haken, Kreuz, Enter und Esc.
            if event.button() != Qt.LeftButton:
                event.ignore()
                return
            x = event.pos().x()
            name = self._fein_knopf_unter(event.pos())
            if name is None and event.modifiers() & Qt.ShiftModifier:
                # Shift + linke Taste schiebt die Leiste - auch jetzt, damit
                # man die Kante ins Bild holen kann. Die Leiste wandert mit.
                self._schieben_beginnen(x)
                event.accept()
                return
            if name == "zurueck":
                self._fein_ruecken(-self._fein_schritt(event.modifiers()))
            elif name == "vor":
                self._fein_ruecken(+self._fein_schritt(event.modifiers()))
            elif name == "ok":
                self._fein_anwenden()
            elif name == "abbruch":
                self._fein_abbrechen()
            elif abs(x - self._fein_kante_x()) <= self._KANTE_PX \
                    or self._fein_im_block(x):
                self._fein_wieder_ziehen(x, event.pos())
            else:
                self._hinweis(event.globalPos(),
                              "Finish the move first: tick or Enter applies "
                              "it, cross or Esc discards it.")
            event.accept()
            return
        if event.button() == Qt.LeftButton \
                and event.modifiers() & Qt.ShiftModifier:
            # Vor allem anderen: mit Shift wird geschoben, nicht geschnitten
            # und nicht der Marker gesetzt. Siehe _schieben_beginnen.
            self._schieben_beginnen(event.pos().x())
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            # Zuerst die Schnitte fragen: liegt der Zeiger auf einer Kante
            # oder in einem Block, wird gezogen statt der Marker gesetzt.
            schnitt, art = self._kante_unter(event.pos().x())
            # Auswaehlen unabhaengig davon, ob ein Umzug daraus wird: ein
            # Schnitt kann zurueckzunehmen sein, ohne verschiebbar zu sein.
            # Auf freier Flaeche hebt der Klick die Auswahl auf.
            self._schnitt_waehlen(schnitt)
            if schnitt is not None and self._umzug_beginnen(
                    schnitt, art, event.pos().x(), event.globalPos()):
                event.accept()
                return
            # Schnitte haben Vorrang: wo ein Schnitt liegt, ist kein Bild, und
            # ein Overlay dort waere ohnehin nicht erlaubt.
            overlay, o_art = self._overlay_unter(event.pos().x())
            # Auswaehlen unabhaengig davon, ob ein Umzug daraus wird - genau
            # wie beim Schnitt. Auf freier Flaeche faellt beides weg.
            if schnitt is None:
                self._overlay_waehlen(overlay)
            if overlay is not None and self._umzug_beginnen(
                    overlay, o_art, event.pos().x(), event.globalPos(),
                    typ="overlay"):
                event.accept()
                return
            self._dragging_marker = True
            self._update_marker_by_mouse_x(event.pos().x())
            event.accept()
        else:
            # Rechte Taste: nichts anfassen. Das Kontextmenue kommt ueber
            # contextMenuEvent, und das soll es ungestoert tun.
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._fein and not self._dragging_timeline:
            x = event.pos().x()
            if self._fein_knopf_unter(event.pos()) is not None:
                self._zeiger_setzen(Qt.PointingHandCursor)
            elif abs(x - self._fein_kante_x()) <= self._KANTE_PX:
                self._zeiger_setzen(Qt.SizeHorCursor)
            elif self._fein_im_block(x):
                self._zeiger_setzen(Qt.SizeAllCursor)
            else:
                self._zeiger_setzen(None)
            event.accept()
            return
        if self._zieh_schnitt is not None and not self._fein:
            self._umzug_aktualisieren(event.pos().x(), event.pos())
            event.accept()
            return
        if not (self._dragging_marker or self._dragging_timeline):
            # Ohne gedrueckte Taste nur die Zeigerform. Rein geometrisch -
            # ob der Schnitt umziehen DARF, wird erst beim Zugriff geprueft.
            # Die Naht zuerst, wie im Kontextmenue: wer nahe an die blaue
            # Linie zeigt, meint die Naht.
            naht, _z = self._naht_unter(event.pos().x())
            if naht != self._naht_unter_zeiger:
                self._naht_unter_zeiger = naht
                self.update()
            _s, art = self._kante_unter(event.pos().x())
            if art is None:
                _o, art = self._overlay_unter(event.pos().x())
            if naht is not None:
                self._zeiger_setzen(Qt.PointingHandCursor)
            elif art in ("links", "rechts"):
                self._zeiger_setzen(Qt.SizeHorCursor)
            elif art == "block":
                self._zeiger_setzen(Qt.SizeAllCursor)
            else:
                self._zeiger_setzen(None)
        if self._dragging_marker:
            self._update_marker_by_mouse_x(event.pos().x())
            event.accept()
        elif self._dragging_timeline:
            delta_x = event.pos().x() - self._timeline_drag_start_x
            self._horizontal_offset = self._horizontal_offset_start - delta_x
            self._offset_begrenzen()
            w = self.width()
            if w > 0 and self.total_duration > 0:
                timeline_real_width = w * self._zoom_factor
                new_marker_x_abs = self._marker_screen_x_at_drag_start + self._horizontal_offset
                ratio = new_marker_x_abs / timeline_real_width
                if ratio < 0:
                    ratio = 0
                elif ratio > 1:
                    ratio = 1
                new_time_s = ratio * self.total_duration
                self._marker_position_s = new_time_s
                self.markerMoved.emit(new_time_s)
            self.update()
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._zieh_schnitt is not None \
                and not self._fein:
            a0, b0 = self._zieh_schnitt
            a, b = self._zieh_neu or (a0, b0)
            typ = self._zieh_typ
            unveraendert = abs(a - a0) < 0.001 and abs(b - b0) < 0.001
            if not (unveraendert and self._zieh_art == "block"):
                # Nicht gleich umziehen: erst die Feinstellung - fuer Schnitt
                # und Overlay gleich. Nur der blosse Klick in den Block
                # bleibt, was er war: Marker setzen. Ein Klick auf eine Kante
                # oeffnet die Feinstellung auch ohne Ziehen, so kommt man
                # ohne Maus-Zittern hinein.
                self._fein_beginnen()
                event.accept()
                return
            self._zieh_schnitt = None
            self._zieh_neu = None
            self._zieh_art = None
            self._zieh_maus = None
            self._zeiger_setzen(None)
            self.update()
            if unveraendert:
                # Nur geklickt, nicht gezogen - dann war der Marker gemeint.
                # Ohne das waere ein Klick in einen Schnitt wirkungslos.
                self._update_marker_by_mouse_x(event.pos().x())
            elif typ == "overlay":
                self.overlayMoveRequested.emit(a0, b0, round(a, 3), round(b, 3))
            else:
                self.cutMoveRequested.emit(a0, b0, round(a, 3), round(b, 3))
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._dragging_marker:
            self._dragging_marker = False
            event.accept()
        elif event.button() == Qt.LeftButton and self._dragging_timeline:
            self._dragging_timeline = False
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        """Entf nimmt den ausgewaehlten Schnitt zurueck, Esc hebt die Auswahl auf.

        Zurueckgenommen wird nicht hier. Ob ein Schnitt sich ueberhaupt
        zuruecknehmen laesst und was dabei mit der GPX-Spur geschieht, weiss
        nur das Fenster - die Taste ist derselbe Weg wie der Menuepunkt, nur
        ein zweiter Zugang dorthin.
        """
        if self._fein:
            taste = event.key()
            if taste == Qt.Key_Left:
                self._fein_ruecken(-self._fein_schritt(event.modifiers()))
            elif taste == Qt.Key_Right:
                self._fein_ruecken(+self._fein_schritt(event.modifiers()))
            elif taste in (Qt.Key_Return, Qt.Key_Enter):
                self._fein_anwenden()
            elif taste == Qt.Key_Escape:
                self._fein_abbrechen()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._gewaehlter_schnitt is not None:
                a, b = self._gewaehlter_schnitt
                self.cutDeleteRequested.emit(float(a), float(b))
                event.accept()
                return
            if self._gewaehltes_overlay is not None:
                a, b = self._gewaehltes_overlay
                self.overlayDeleteRequested.emit(float(a), float(b))
                event.accept()
                return
        elif event.key() == Qt.Key_Escape:
            if (self._gewaehlter_schnitt is not None
                    or self._gewaehltes_overlay is not None):
                self._schnitt_waehlen(None)
                self._overlay_waehlen(None)
                event.accept()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        if event.modifiers() & Qt.ShiftModifier:
            if delta > 0:
                self._horizontal_offset -= self._scroll_speed_px
            else:
                self._horizontal_offset += self._scroll_speed_px
            self._offset_begrenzen()
            self._keep_marker_visible()
            self.update()
            event.accept()
            return
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.1 if delta > 0 else (1.0 / 1.1)
            new_zoom = self._zoom_factor * factor
            if new_zoom < self._min_zoom:
                new_zoom = self._min_zoom
            if new_zoom > self._max_zoom:
                new_zoom = self._max_zoom
            self._zoom_factor = new_zoom
            self._center_marker_at_ratio(0.3)
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def _center_marker_at_ratio(self, widget_ratio: float):
        w = self.width()
        if w <= 0 or self.total_duration <= 0:
            return
        timeline_real_width = w * self._zoom_factor
        marker_x_absolute = (self._marker_position_s / self.total_duration)*timeline_real_width
        desired_x_in_widget = widget_ratio * w
        self._horizontal_offset = marker_x_absolute - desired_x_in_widget
        self._offset_begrenzen()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QBrush, QPolygon
        from PySide6.QtCore import QPoint

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect_ = self.rect()
        w = rect_.width()
        h = rect_.height()
        painter.fillRect(rect_, QColor("#333333"))
        painter.setClipRect(rect_)

        timeline_real_width = w * self._zoom_factor

        # Hat sich der sichtbare Ausschnitt geaendert, Bescheid geben. Der
        # Empfaenger stoesst davon nur einen Zeitgeber an, es kann also nicht
        # zu einer Schleife aus Melden und Neuzeichnen kommen.
        zustand = (round(self._zoom_factor, 4),
                   round(float(self._horizontal_offset), 1), w)
        if zustand != getattr(self, "_letzte_ansicht", None):
            self._letzte_ansicht = zustand
            self.ansichtGeaendert.emit()

        # Bilder und Tonspur sind unabhaengig; die Kurve liegt halb
        # durchsichtig ueber den (abgedunkelten) Bildern.
        self._draw_vorschaubilder(painter, w, h, timeline_real_width)
        if self._pegel_zeigen:
            self._draw_pegelkurve(painter, w, h, timeline_real_width)
            self._draw_pegel_hinweis(painter, w, h)
        self._draw_sprechstellen(painter, w, h, timeline_real_width)
        self._draw_time_ticks(painter, w, h, timeline_real_width)
        self._draw_boundaries_and_markers(painter, w, h, timeline_real_width)
        self._draw_umzug(painter, w, h)

    # ------------------------------------------------------------------
    # Bildstreifen
    # ------------------------------------------------------------------
    def set_vorschaubilder(self, bilder):
        """bilder: Liste aus (zeit_s in Gesamtzeit, QImage)."""
        self._vorschaubilder = list(bilder or [])
        self.update()

    def vorschaubilder_zeigen(self, an: bool):
        self._bilder_zeigen = bool(an)
        self.update()

    def _draw_vorschaubilder(self, painter, w, h, timeline_real_width):
        """Die Bilder als Hintergrund, jeweils an ihrer Zeitstelle.

        Sie werden abgedunkelt gezeichnet. Ohne das waeren die Zeitmarken und
        die Beschriftung darauf nicht mehr zu lesen, und die schwarzen
        Schnittbloecke wuerden sich kaum noch abheben.

        Gezeigt wird ROHZEIT, wie die ganze Zeitleiste. Die Schnittbloecke
        liegen also darueber - man sieht dadurch, welches Material
        weggeschnitten wird.
        """
        if (not self._bilder_zeigen or not self._vorschaubilder
                or self.total_duration <= 0 or timeline_real_width <= 0):
            return

        def x_von(zeit_s):
            return (zeit_s / self.total_duration) * timeline_real_width \
                - self._horizontal_offset

        bilder = self._vorschaubilder
        for i, (zeit_s, bild) in enumerate(bilder):
            if bild is None or bild.isNull():
                continue
            x = x_von(zeit_s)
            # Bis zum naechsten Bild reichen - das ergibt einen lueckenlosen
            # Streifen. Wuerde jedes Bild nur in seiner eigenen Breite
            # gezeichnet, klafften dazwischen schwarze Spalten, sobald der
            # Abstand groesser ist als das Bild breit.
            if i + 1 < len(bilder):
                x_ende = x_von(bilder[i + 1][0])
            else:
                x_ende = x + bild.width()
            abschnitt = x_ende - x
            if abschnitt <= 0 or x + abschnitt < 0 or x > w:
                continue

            quelle = None
            if abschnitt < bild.width():
                # Schmaler als das Bild: mittigen Ausschnitt nehmen statt zu
                # stauchen - gestauchte Bilder sind im Streifen nicht mehr zu
                # erkennen.
                links = int((bild.width() - abschnitt) / 2)
                quelle = QRectF(links, 0, abschnitt, bild.height())

            ziel = QRectF(x, 0, abschnitt, min(h, bild.height()))
            if quelle is not None:
                painter.drawImage(ziel, bild, quelle)
            else:
                painter.drawImage(ziel, bild)

        # Gleichmaessig abdunkeln, damit alles Weitere darauf lesbar bleibt.
        painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 120))

    # ------------------------------------------------------------------
    # Tonspur und Sprechstellen (ab 7.0)
    # ------------------------------------------------------------------
    #: Farbe der Sprechstellen - dieselbe wie im Audio Zoom.
    SPRECHSTELLE_FARBE = QColor(255, 140, 0, 120)
    SPRECHSTELLE_RAND = QColor(255, 170, 60)
    #: Fahrzeugstellen - dieselbe Farbe wie im Audio Zoom.
    FAHRZEUG_FARBE = QColor(80, 160, 255, 120)
    FAHRZEUG_RAND = QColor(120, 190, 255)
    #: Hoehe der Baender in Pixeln, ueber den Zeitmarken.
    SPRECHSTELLE_HOEHE = 6

    def set_pegelkurve(self, punkte):
        """punkte: Liste aus (zeit_s in Gesamtzeit, dB), sortiert."""
        self._pegelkurve = list(punkte or [])
        self._pegel_zeiten = [p[0] for p in self._pegelkurve]
        self.update()

    def pegel_zeigen(self, an: bool):
        """Tonspur als Hintergrund, auch zusammen mit den Bildern."""
        self._pegel_zeigen = bool(an)
        self.update()

    def set_pegel_hinweis(self, text: str):
        """Hinweis in der Leiste, solange die Tonspur im Hintergrund gelesen
        wird (leer: keiner). Gezeichnet nur in der Ton-Ansicht - der Nutzer
        soll sehen, dass die Kurve kommt und warum sie dauert (Bernd,
        11.09.2026)."""
        text = text or ""
        if text != self._pegel_hinweis:
            self._pegel_hinweis = text
            self.update()

    def _draw_pegel_hinweis(self, painter, w, h):
        if not self._pegel_hinweis:
            return
        from PySide6.QtGui import QPen, QBrush, QFontMetrics
        fm = QFontMetrics(painter.font())
        breite = min(w - 16, fm.horizontalAdvance(self._pegel_hinweis) + 16)
        hoehe = fm.height() + 8
        x = max(4, (w - breite) / 2)
        y = max(2, (h - 14 - hoehe) / 2)
        kasten = QRectF(x, y, breite, hoehe)
        painter.setPen(QPen(QColor(0, 200, 220, 200), 1))
        painter.setBrush(QBrush(QColor(20, 20, 20, 190)))
        painter.drawRoundedRect(kasten, 4, 4)
        painter.setPen(QPen(QColor(230, 230, 230)))
        painter.drawText(kasten, Qt.AlignCenter, fm.elidedText(
            self._pegel_hinweis, Qt.ElideRight, int(breite - 12)))

    # ---- Ansichtsknopf ---------------------------------------------------
    def ansicht(self) -> str:
        return self._ansicht

    def bilder_an(self) -> bool:
        return self._ansicht in ("video", "beides")

    def audio_an(self) -> bool:
        return self._ansicht in ("audio", "beides")

    def audio_moeglich(self, an: bool):
        """Ohne Tonspur (z. B. Mac-Buendel ohne Pegelscan) schaltet der
        Knopf nur zwischen Nichts und Video. Seit dem 10.09.2026 auch in
        Lite an - der Pegel kommt von GStreamer."""
        self._audio_moeglich = bool(an)
        if not self._audio_moeglich and self.audio_an():
            self.ansicht_setzen("video" if self.bilder_an() else "off")

    def _ansichten(self):
        if getattr(self, "_audio_moeglich", True):
            return self.ANSICHTEN
        return tuple(a for a in self.ANSICHTEN if a in ("off", "video"))

    def ansicht_setzen(self, name: str, melden: bool = True):
        """Von aussen (gemerkter Zustand). melden: ansichtGewechselt senden,
        damit das Fenster Bilder holt oder verwirft."""
        if name not in self.ANSICHTEN:
            name = "off"
        if name not in self._ansichten():
            name = "video" if name == "beides" else "off"
        geaendert = name != self._ansicht
        self._ansicht = name
        self._ansicht_anwenden()
        if melden and geaendert:
            self.ansichtGewechselt.emit(self._ansicht)

    def _ansicht_weiter(self):
        reihe = self._ansichten()
        i = reihe.index(self._ansicht) if self._ansicht in reihe else -1
        self.ansicht_setzen(reihe[(i + 1) % len(reihe)])

    def _ansicht_anwenden(self):
        self._bilder_zeigen = self.bilder_an()
        self._pegel_zeigen = self.audio_an()
        self._ansicht_knopf.setText(self.ANSICHT_TEXT[self._ansicht])
        self._ansicht_knopf.adjustSize()
        self.update()

    def set_bearbeitung(self, seite: str):
        """"video" oder "audio" - siehe _bearbeitung."""
        self._bearbeitung = "audio" if seite == "audio" else "video"

    def set_sprechstellen(self, stellen):
        """stellen: Liste aus (von_s, bis_s) in Gesamtzeit."""
        self._sprechstellen = [(float(a), float(b)) for a, b in (stellen or [])]
        self.update()

    def sprechstelle_bei(self, zeit_s):
        for a, b in self._sprechstellen:
            if a <= zeit_s <= b:
                return (a, b)
        return None

    def set_fahrzeugstellen(self, stellen):
        """stellen: Liste aus (von_s, bis_s) in Gesamtzeit - Fahrzeugstellen
        (blau, eine Reihe ueber den Sprechstellen)."""
        self._fahrzeugstellen = [(float(a), float(b)) for a, b in (stellen or [])]
        self.update()

    def band_bei(self, zeit_s):
        """(art, von, bis) des Bandes unter der Zeit, oder None. Faehrt
        eine Fahrzeugstelle ueber einer Sprechstelle, gewinnt das schmalere
        Band - meist ist das die Fahrzeugstelle."""
        treffer = []
        for a, b in self._fahrzeugstellen:
            if a <= zeit_s <= b:
                treffer.append(("vehicle", a, b))
        for a, b in self._sprechstellen:
            if a <= zeit_s <= b:
                treffer.append(("voice", a, b))
        if not treffer:
            return None
        return min(treffer, key=lambda t: t[2] - t[1])

    def _draw_pegelkurve(self, painter, w, h, timeline_real_width):
        """Der Pegel als Flaeche von unten, je Pixelspalte der hoechste Wert
        im Zeitfenster der Spalte - wie im Audio Zoom, nur in Rohzeit der
        ganzen Leiste. Ohne Kurve bleibt der Hintergrund leer."""
        if (not self._pegelkurve or self.total_duration <= 0
                or timeline_real_width <= 0):
            return
        import bisect
        from PySide6.QtGui import QPolygonF, QBrush
        from PySide6.QtCore import QPointF
        zeiten = getattr(self, "_pegel_zeiten", None)
        if zeiten is None or len(zeiten) != len(self._pegelkurve):
            zeiten = [p[0] for p in self._pegelkurve]
            self._pegel_zeiten = zeiten
        db_unten, db_oben = -60.0, 0.0
        oben = 2
        unten = h - 14      # ueber den Zeitmarken
        sek_je_px = self.total_duration / timeline_real_width
        poly = QPolygonF()
        poly.append(QPointF(0, unten))
        t0 = self._horizontal_offset * sek_je_px
        i0 = bisect.bisect_left(zeiten, t0)
        for x in range(w):
            t1 = t0 + sek_je_px
            i1 = bisect.bisect_left(zeiten, t1, i0)
            if i1 > i0:
                db = max(self._pegelkurve[i][1] for i in range(i0, i1))
            elif i0 < len(self._pegelkurve):
                db = self._pegelkurve[i0][1]
            else:
                db = db_unten
            i0 = max(i0, i1 - 1)
            anteil = (max(db_unten, min(db_oben, db)) - db_unten) / (db_oben - db_unten)
            poly.append(QPointF(x, unten - anteil * (unten - oben)))
            t0 = t1
        poly.append(QPointF(w, unten))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 200, 220, 150)))
        painter.drawPolygon(poly)

    def _draw_sprechstellen(self, painter, w, h, timeline_real_width):
        """Die Sprechstellen als schmale Baender ueber den Zeitmarken - in
        jedem Zustand der Leiste, damit man sie auch mit Bildern sieht."""
        if self.total_duration <= 0 or timeline_real_width <= 0:
            return
        if not self._sprechstellen and not self._fahrzeugstellen:
            return
        from PySide6.QtGui import QPen, QBrush
        y = h - 14 - self.SPRECHSTELLE_HOEHE
        reihen = (
            (self._sprechstellen, y, self.SPRECHSTELLE_FARBE, self.SPRECHSTELLE_RAND),
            (self._fahrzeugstellen, y - self.SPRECHSTELLE_HOEHE - 2,
             self.FAHRZEUG_FARBE, self.FAHRZEUG_RAND),
        )
        for stellen, yy, farbe, rand in reihen:
            painter.setPen(QPen(rand, 1))
            painter.setBrush(QBrush(farbe))
            for a, b in stellen:
                xa = (a / self.total_duration) * timeline_real_width - self._horizontal_offset
                xb = (b / self.total_duration) * timeline_real_width - self._horizontal_offset
                if xb < 0 or xa > w:
                    continue
                painter.drawRect(QRectF(xa, yy, max(2.0, xb - xa), self.SPRECHSTELLE_HOEHE))

    def _draw_time_ticks(self, painter, w, h, timeline_real_width):
        if self.total_duration <= 0 or timeline_real_width <= 0:
            return
        desired_px_between_major_ticks = 100.0
        num_subticks = 4
        px_per_sec = timeline_real_width / self.total_duration
        raw_step_sec = desired_px_between_major_ticks / px_per_sec
        step_sec = _nice_number(raw_step_sec)
        sub_tick_sec = step_sec / (num_subticks + 1)

        from PySide6.QtGui import QPen
        pen_major = QPen(QColor("#CCCCCC"), 2)
        pen_minor = QPen(QColor("#AAAAAA"), 1)

        main_tick_height = 10
        sub_tick_height  = 6
        text_offset_y = h - main_tick_height - 3
        end_time = self.total_duration
        t = 0.0
        while t <= end_time + 0.0001:
            x_timeline = (t * px_per_sec) - self._horizontal_offset
            if -50 < x_timeline < w + 50:
                index_float = t / step_sec
                is_major = abs(index_float - round(index_float)) < 0.001
                if is_major:
                    painter.setPen(pen_major)
                    y_start = h - main_tick_height
                    painter.drawLine(x_timeline, y_start, x_timeline, h)
                    mm = int(t // 60)
                    ss = int(t % 60)
                    time_label = f"{mm:02d}:{ss:02d}"
                    painter.drawText(x_timeline - 15, text_offset_y, time_label)
                else:
                    painter.setPen(pen_minor)
                    y_start = h - sub_tick_height
                    painter.drawLine(x_timeline, y_start, x_timeline, h)
            t += sub_tick_sec

    #: Abstand der Schraffurlinien in einem Schnittblock.
    SCHRAFFUR_ABSTAND = 9
    #: Enger bei der harten Kante - das dichtere Muster liest sich als
    #: "geschlossen", das weitere als "durchlaessig".
    SCHRAFFUR_ABSTAND_HART = 5

    def _schraffur(self, painter, x_start, breite, h, hart=False):
        """Diagonale Linien ueber einen Schnittblock.

        Das Muster macht den Block auch dort erkennbar, wo das Videobild
        selbst dunkel ist. Es wird auf den Block begrenzt, damit die Linien
        nicht in benachbartes Material laufen.

        Blende und harte Kante bekommen VERSCHIEDENE Muster, und das ist der
        eigentliche Unterschied zwischen beiden - nicht die Randfarbe. Ein
        Schnitt von wenigen Zehntelsekunden ist nur ein paar Pixel breit; eine
        kraeftigere Kante waere dort fast der ganze Block und liesse ihn
        groesser wirken, als er ist. Das Muster wird dagegen mitgeschnitten
        und bleibt in jeder Breite ehrlich.

          Blende       "/"   hell, weit stehend, in Richtung der Blende
          harte Kante  "\\"  orange, eng stehend und gegenlaeufig

        Richtung und Abstand bleiben zusaetzlich verschieden. Wer Farben
        schlecht unterscheidet, erkennt den Unterschied dann immer noch am
        Muster.
        """
        if breite < 3:
            return
        painter.save()
        painter.setClipRect(QRectF(x_start, 0, breite, h))
        # Die FARBE traegt den Unterschied, nicht die Richtung: Richtung und
        # Abstand allein waren auf bewegtem Bild kaum auseinanderzuhalten.
        # Orange gehoert der harten Kante - dieselbe Farbe wie ihre
        # Schnittkanten -, die Blende bleibt hell und neutral.
        # Deckkraft gemessen und nicht geschaetzt: eine 1 px breite Diagonale
        # wird kantengeglaettet, von der eingestellten Deckkraft kommt rund
        # die Haelfte an. Bei 105 lag der Orangeanteil im Bild bei 40 von 255
        # und war kaum zu sehen - 160 ergibt gut 60 und liest sich sofort.
        painter.setPen(QPen(QColor(255, 138, 61, 160) if hart
                            else QColor(255, 255, 255, 70), 1))
        abstand = (self.SCHRAFFUR_ABSTAND_HART if hart
                   else self.SCHRAFFUR_ABSTAND)
        # Um h versetzt beginnen, damit die Linien den Block unabhaengig von
        # seiner Breite treffen.
        x = x_start - h
        while x < x_start + breite + h:
            if hart:
                # von links oben nach rechts unten
                painter.drawLine(QPointF(x, 0.0), QPointF(x + h, h))
            else:
                # von links unten nach rechts oben
                painter.drawLine(QPointF(x, h), QPointF(x + h, 0.0))
            x += abstand
        painter.restore()

    def _draw_overlay_blenden(self, painter, start_s, end_s, x_start, x_end, h):
        """Die Ein- und Ausblendung als Rampen im Overlay-Balken.

        Die Rampe steigt ueber die Einblendlaenge von unten nach oben und
        faellt am Ende wieder ab - so, wie das Bild kommt und geht. Damit ist
        auf einen Blick zu sehen, wie viel des Overlays ueberhaupt voll
        sichtbar ist; bei einem kurzen Overlay mit langen Blenden ist das
        ueberraschend wenig.
        """
        from PySide6.QtGui import QPolygonF

        ein, aus = self._overlay_blenden.get(
            self._cut_key(start_s, end_s), (0.0, 0.0))
        if (ein <= 0 and aus <= 0) or self.total_duration <= 0:
            return
        je_sekunde = (x_end - x_start) / max(1e-9, (end_s - start_s))

        painter.save()
        try:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(120, 170, 255, 110))
            if ein > 0:
                breite = min(ein * je_sekunde, x_end - x_start)
                if breite >= 1:
                    painter.drawPolygon(QPolygonF([
                        QPointF(x_start, h),
                        QPointF(x_start + breite, 0.0),
                        QPointF(x_start + breite, h)]))
            if aus > 0:
                breite = min(aus * je_sekunde, x_end - x_start)
                if breite >= 1:
                    painter.drawPolygon(QPolygonF([
                        QPointF(x_end - breite, 0.0),
                        QPointF(x_end, h),
                        QPointF(x_end - breite, h)]))
        finally:
            painter.restore()

    #: Farbe des Merge-Fade in der Zeitleiste. Eigene Farbe, damit er sich
    #: von der Blende eines Schnitts (weiss), der harten Kante (orange), den
    #: Overlays (blau) und den Marken (gelb) unterscheidet.
    MERGE_FADE_FARBE = QColor(80, 220, 140)

    def _draw_blendenfluegel(self, painter, x_start, x_end, halb_px, h, w,
                             farbe=None):
        """Die Ueberblendung, die links und rechts ins Videobild hineinreicht.

        farbe: Grundfarbe der Fluegel, ohne Angabe weiss (Blende eines
        Schnitts). Der Merge-Fade uebergibt seine eigene Farbe.

        Gezeichnet als Verlauf, der an der Schnittkante am kraeftigsten ist
        und nach aussen verschwindet - so, wie die Blende dort wirkt. Die
        gepunktete Linie am aeusseren Ende sagt, wie weit sie reicht.

        Bewusst weiss und nicht farbig: Blau gehoert den Overlays, Orange der
        harten Kante. Und der Verlauf sieht aus, als loese sich der schwarze
        Block ins Bild auf - genau das tut die Blende.
        """
        grund = QColor(255, 255, 255) if farbe is None else QColor(farbe)
        innen = QColor(grund.red(), grund.green(), grund.blue(), 95)
        aussen_farbe = QColor(grund.red(), grund.green(), grund.blue(), 0)
        rand = QColor(grund.red(), grund.green(), grund.blue(), 70)
        painter.save()
        try:
            for x_kante, richtung in ((x_start, -1.0), (x_end, +1.0)):
                x_aussen = x_kante + richtung * halb_px
                links = min(x_kante, x_aussen)
                breite = abs(x_aussen - x_kante)
                if breite < 1.0 or links > w or links + breite < 0:
                    continue
                verlauf = QLinearGradient(x_kante, 0.0, x_aussen, 0.0)
                verlauf.setColorAt(0.0, innen)
                verlauf.setColorAt(1.0, aussen_farbe)
                painter.setPen(Qt.NoPen)
                painter.fillRect(QRectF(links, 0, breite, h), QBrush(verlauf))
                painter.setPen(QPen(rand, 1, Qt.DotLine))
                painter.drawLine(QPointF(x_aussen, 0), QPointF(x_aussen, h))
        finally:
            painter.restore()

    def _cut_bloecke(self, eps: float = 0.001):
        """Die Schnitte so, wie sie im Video wirklich aussehen.

        Aneinandergrenzende oder ueberlappende Schnitte sind dort EIN Loch -
        zwischen ihnen liegt kein Bild. Gezeichnet wurde bisher aber jeder
        einzeln, mit einem an beiden Raendern auslaufenden Verlauf. An der
        Stossstelle trafen dadurch zwei helle Kanten aufeinander und sahen
        aus wie ein kurzes Stueck Video.

        Zusammengefasst wird nur fuers Zeichnen. self._cut_intervals bleibt
        unangetastet, damit der Rechtsklick weiterhin den einzelnen Schnitt
        trifft.

        Liefert (start, ende, hart) - hart, wenn irgendein Schnitt der
        Gruppe eine harte Kante ist; im Video ist die Gruppe ja ein Uebergang.

        Der ERSTE und der LETZTE Schnitt zaehlen dabei immer als harte Kante.
        Sie werden vor dem Zusammenfuegen weggetrimmt und hatten noch nie eine
        Blende - sie als Blende zu zeichnen waere schlicht falsch, auch wenn
        in _hard_cut_keys nichts zu ihnen steht.
        """
        gueltig = sorted((min(a, b), max(a, b)) for (a, b) in self._cut_intervals
                         if b > a)
        gesamt = self.total_duration
        bloecke = []
        for (a, b) in gueltig:
            hart = (self._cut_key(a, b) in self._hard_cut_keys
                    or a < 0.1
                    or (gesamt > 0 and abs(b - gesamt) < 0.1))
            if bloecke and a <= bloecke[-1][1] + eps:
                vorher = bloecke[-1]
                bloecke[-1] = (vorher[0], max(vorher[1], b), vorher[2] or hart)
            else:
                bloecke.append((a, b, hart))
        return bloecke

    def _draw_boundaries_and_markers(self, painter, w, h, timeline_real_width):
        from PySide6.QtGui import QPen, QBrush, QPolygon
        pen_blue = QPen(QColor("blue"), 3)
        painter.setBrush(Qt.NoBrush)
        if self.total_duration > 0:
            for (naht, b_sec) in self._naehte():
                ratio_b = b_sec / self.total_duration
                x_b = ratio_b*timeline_real_width - self._horizontal_offset
                if not (-50 < x_b < w+50):
                    continue
                # Der Merge-Fade als Fluegel beiderseits der Naht in seiner
                # eigenen Farbe - dieselbe Zeichnung wie die Ueberblendung um
                # einen Schnitt, nur ohne Block dazwischen: hier wird ja
                # nichts weggenommen. Die Naht selbst wird dann in derselben
                # Farbe gezeichnet statt blau, damit ein Merge-Fade auch bei
                # Zoom 1, wo die Fluegel nur wenige Pixel breit sind, auf
                # einen Blick von einer harten Naht zu unterscheiden ist.
                blende = self._merge_fades.get(naht, 0.0)
                if blende > 0:
                    halb_px = ((blende / 2.0) / self.total_duration
                               ) * timeline_real_width
                    if halb_px >= 1.0:
                        self._draw_blendenfluegel(painter, x_b, x_b,
                                                  halb_px, h, w,
                                                  farbe=self.MERGE_FADE_FARBE)
                # Unter dem Zeiger oder mit offenem Menue: die Trefferzone
                # als helles Band, damit man sieht, dass die Linie
                # anklickbar ist und wie breit sie trifft.
                if naht in (self._naht_unter_zeiger, self._markierte_naht):
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QBrush(QColor(120, 170, 255, 60)))
                    painter.drawRect(QRectF(x_b - self._NAHT_PX, 0,
                                            2 * self._NAHT_PX, h))
                    painter.setBrush(Qt.NoBrush)
                    painter.setPen(QPen(QColor(150, 190, 255), 3))
                elif blende > 0:
                    painter.setPen(QPen(self.MERGE_FADE_FARBE, 3))
                else:
                    painter.setPen(pen_blue)
                painter.drawLine(x_b, 0, x_b, h)
        painter.setPen(pen_blue)

        pen_marker = QPen(QColor("white"), 2)
        painter.setPen(pen_marker)
        painter.setBrush(QBrush(QColor("white")))
        if self.total_duration > 0:
            ratio = self._marker_position_s / self.total_duration
            marker_x = ratio*timeline_real_width - self._horizontal_offset
            if -50 < marker_x < w+50:
                painter.drawLine(marker_x, 0, marker_x, h)
                arrow_height = 10
                arrow_half = 6
                arrow_points = [
                    QPoint(marker_x - arrow_half, 0),
                    QPoint(marker_x + arrow_half, 0),
                    QPoint(marker_x, arrow_height),
                ]
                painter.drawPolygon(QPolygon(arrow_points))

        pen_yellow = QPen(QColor("yellow"), 2)
        painter.setPen(pen_yellow)
        painter.setBrush(Qt.NoBrush)
        xB = xE = -1
        #if 0 <= self.markB_time_s <= self.total_duration:
        if self.markB_time_s is not None and 0 <= self.markB_time_s <= self.total_duration:
            xB = (self.markB_time_s/self.total_duration)*timeline_real_width - self._horizontal_offset
            if -50 < xB < w+50:
                painter.drawLine(xB, 0, xB, h)

        if self.markE_time_s is not None and 0 <= self.markE_time_s <= self.total_duration:
        #if 0 <= self.markE_time_s <= self.total_duration:
            xE = (self.markE_time_s/self.total_duration)*timeline_real_width - self._horizontal_offset
            if -50 < xE < w+50:
                painter.drawLine(xE, 0, xE, h)

        if xB >= 0 and xE >= 0:
            left_x = min(xB, xE)
            right_x = max(xB, xE)
            if right_x > left_x:
                brush_yellow = QBrush(QColor(255,255,0,80))
                painter.fillRect(left_x, 0, right_x-left_x, h, brush_yellow)

        # Deutlich deckender als frueher (150): unter dem Block liegt jetzt
        # das Videobild, und auf dunklem Material war der Schnitt sonst nicht
        # als solcher zu erkennen.
        brush_black = QBrush(QColor(0, 0, 0, 215))
        pen_black = QPen(QColor("black"), 1)
        # Bewusst nur ein Pixel: bei einem Schnitt von wenigen Zehntel-
        # sekunden ist der Block selbst nur ein paar Pixel breit, und zwei
        # Pixel Kante links und rechts waeren dann fast der ganze Block. Die
        # Unterscheidung zur Blende traegt die Schraffur, siehe _schraffur().
        pen_hard = QPen(QColor("#FF8A3D"), 1)
        painter.setPen(pen_black)
        for (start_s, end_s, gruppe_hart) in self._cut_bloecke():
            if start_s < 0 or end_s <= 0 or self.total_duration <= 0:
                continue
            start_ratio = max(0.0, start_s/self.total_duration)
            end_ratio   = min(1.0, end_s/self.total_duration)
            if end_ratio <= start_ratio:
                continue
            x_start = start_ratio*timeline_real_width - self._horizontal_offset
            x_end   = end_ratio*timeline_real_width - self._horizontal_offset
            if x_end < -50 or x_start > w+50:
                continue
            rect_width = x_end - x_start
            if rect_width < 1:
                rect_width = 1

            if gruppe_hart:
                # Harte Kante: Block bleibt schwarz, die Schnittkanten werden
                # orange markiert. Bei sehr schmalen Bloecken wuerden zwei
                # Linien ineinanderlaufen, deshalb dort nur eine.
                painter.fillRect(QRectF(x_start, 0, rect_width, h), brush_black)
                painter.setPen(pen_hard)
                painter.drawLine(x_start, 0, x_start, h)
                if rect_width >= 4:
                    painter.drawLine(x_start + rect_width, 0,
                                     x_start + rect_width, h)
                painter.setPen(pen_black)
            elif rect_width < 4:
                # Zu schmal fuer einen Verlauf - der Block waere sonst kaum
                # noch zu sehen.
                painter.fillRect(QRectF(x_start, 0, rect_width, h), brush_black)
            else:
                # Blende: der Block laeuft an beiden Raendern weich aus.
                # Der Verlauf ist rund 6 px breit, unabhaengig vom Zoom.
                #
                # Seit dem Bildstreifen laufen die Raender NICHT mehr auf
                # durchsichtig aus, sondern nur noch auf halbe Deckung: auf
                # dunklem Material - Schatten, Mauern, Tunnel - war der Block
                # sonst kaum vom Bild zu unterscheiden. Der Verlauf zeigt
                # weiterhin, dass hier eine Blende liegt.
                edge = min(0.35, 6.0 / rect_width)
                grad = QLinearGradient(x_start, 0.0, x_start + rect_width, 0.0)
                grad.setColorAt(0.0, QColor(0, 0, 0, 90))
                grad.setColorAt(edge, QColor(0, 0, 0, 215))
                grad.setColorAt(1.0 - edge, QColor(0, 0, 0, 215))
                grad.setColorAt(1.0, QColor(0, 0, 0, 90))
                painter.fillRect(QRectF(x_start, 0, rect_width, h),
                                 QBrush(grad))

            # Die Ueberblendung ringsum. Nur bei einer Blende - eine harte
            # Kante greift nicht ins behaltene Material.
            if not gruppe_hart and self.total_duration > 0:
                blende = self._blenden_laengen.get(
                    self._cut_key(start_s, end_s), 0.0)
                if blende > 0:
                    halb_px = ((blende / 2.0) / self.total_duration
                               ) * timeline_real_width
                    if halb_px >= 1.0:
                        self._draw_blendenfluegel(
                            painter, x_start, x_start + rect_width,
                            halb_px, h, w)
                        painter.setPen(pen_black)

            # Schraffur und Kanten - erst dadurch ist ein Schnitt auf jedem
            # Untergrund als Schnitt zu erkennen. Eine weitere Vollfarbe waere
            # dafuer untauglich: Blau ist fuer Overlays vergeben, Orange fuer
            # die harte Kante, und jede andere kann im Bild selbst vorkommen.
            # Ein Muster kann das nicht.
            self._schraffur(painter, x_start, rect_width, h, hart=gruppe_hart)
            if not gruppe_hart:
                # Bei harter Kante sind die Raender bereits orange markiert -
                # weisse Linien wuerden sie nur ueberdecken.
                painter.setPen(QPen(QColor(255, 255, 255, 110), 1))
                painter.drawLine(QPointF(x_start, 0), QPointF(x_start, h))
                painter.drawLine(QPointF(x_start + rect_width, 0),
                                 QPointF(x_start + rect_width, h))
            painter.setPen(pen_black)

        # Zeichnen der Overlay-Intervalle (blau)
        if self.total_duration > 0 and self._overlay_intervals:
            pen_blue = QPen(QColor("blue"), 2)
            painter.setPen(pen_blue)
            if self._overlays_wirksam:
                # halbtransparentes Blau
                painter.setBrush(QBrush(QColor(0, 0, 255, 80)))
            else:
                # Copy-Mode: das Overlay landet nicht im Export. Gleiche Lage,
                # gleiche Farbe, aber ohne Fuellung - der leere Rahmen sagt,
                # dass hier nichts herauskommt.
                painter.setBrush(Qt.NoBrush)
            for (start_s, end_s) in self._overlay_intervals:
                if end_s <= start_s:
                    continue
                start_ratio = start_s / self.total_duration
                end_ratio   = end_s   / self.total_duration
                x_start = (start_ratio * timeline_real_width) - self._horizontal_offset
                x_end   = (end_ratio   * timeline_real_width) - self._horizontal_offset
                if x_end < -50 or x_start > w+50:
                    continue
                rect_w = x_end - x_start
                if rect_w < 2:
                    rect_w = 2
                painter.drawRect(x_start, 0, rect_w, h)
                self._draw_overlay_blenden(painter, start_s, end_s,
                                           x_start, x_end, h)

        # Das Ausgewaehlte: nur ein Rahmen, keine Fuellung. Der Schnittblock
        # ist schwarz; eine Fuellung wuerde ihn aufhellen und dabei aussehen
        # wie die Hervorhebung des Menues darunter. Dieselbe Farbe fuer
        # Schnitt und Overlay - Gelb heisst hier "ausgewaehlt", und mehr als
        # eines ist es nie.
        gewaehlt = self._gewaehlter_schnitt or self._gewaehltes_overlay
        if gewaehlt and self.total_duration > 0:
            g_start, g_end = gewaehlt
            gx0 = (max(0.0, g_start) / self.total_duration
                   ) * timeline_real_width - self._horizontal_offset
            gx1 = (min(self.total_duration, g_end) / self.total_duration
                   ) * timeline_real_width - self._horizontal_offset
            painter.setPen(QPen(QColor("#ffcc00"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(gx0, 1, max(2.0, gx1 - gx0), h - 3))

        # Der angeklickte Bereich, solange sein Menue offen ist. Zuletzt
        # gezeichnet, damit er ueber Schnitt und Overlay liegt.
        if self._markierter_bereich and self.total_duration > 0:
            m_start, m_end = self._markierter_bereich
            x_start = (max(0.0, m_start) / self.total_duration
                       ) * timeline_real_width - self._horizontal_offset
            x_end = (min(self.total_duration, m_end) / self.total_duration
                     ) * timeline_real_width - self._horizontal_offset
            breite = max(2.0, x_end - x_start)
            # Leicht aufhellen, damit der Bereich auch auf dem schwarzen
            # Schnittblock zu erkennen ist, dazu ein gestrichelter Rahmen.
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 45)))
            painter.drawRect(QRectF(x_start, 0, breite, h))
            stift = QPen(QColor(255, 255, 255, 230), 2, Qt.DashLine)
            painter.setPen(stift)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(x_start + 1, 1, breite - 2, h - 2))
                
                    

    def leaveEvent(self, event):
        # Der Zeiger ist weg - die hervorgehobene Naht auch.
        if self._naht_unter_zeiger is not None:
            self._naht_unter_zeiger = None
            self.update()
        super().leaveEvent(event)

    def _markieren(self, start_s, end_s=None):
        """Bereich hervorheben (oder mit None die Hervorhebung loeschen)."""
        self._markierter_bereich = None if start_s is None else (start_s, end_s)
        self.update()
        # Sofort neu zeichnen: der Aufrufer oeffnet gleich ein Menue oder eine
        # Rueckfrage und blockiert dabei. Ohne das Durchreichen der Ereignisse
        # erschiene die Markierung erst, wenn alles schon vorbei ist.
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMessageBox
        # Das Menue kann denselben Schnitt verschieben oder zuruecknehmen;
        # eine offene Vorschau darauf waere danach falsch.
        self._fein_abbrechen()
        # 1) Falls kein Video oder Overlays => Abbruch
        if self.total_duration <= 0:
            event.ignore()
            return
        w = self.width()
        if w <= 0:
            event.ignore()
            return
        timeline_real_width = w * self._zoom_factor
        x_timeline = event.pos().x() + self._horizontal_offset
        if x_timeline < 0 or x_timeline > timeline_real_width:
            event.ignore()
            return
        ratio = x_timeline / timeline_real_width
        time_clicked = ratio * self.total_duration
        found_any = False
        # Seite A des Video-Controls: nur die Sprechstellen. Schnitt,
        # Overlay und Naht gehoeren zu Seite V und bleiben dort.
        if self._bearbeitung == "audio":
            band = self.band_bei(time_clicked)
            if band is None:
                event.ignore()
                return
            art, a, b = band
            self._markieren(a, b)
            try:
                self.bandMenuRequested.emit(art, a, b, event.globalPos())
            finally:
                self._markieren(None)
            event.accept()
            return
        # 1b) Zuerst die Naehte der Videoliste, in Pixeln geprueft (siehe
        # _naht_unter). Sie kommen VOR Overlays und Schnitten: wer nahe an
        # die blaue Linie klickt, meint die Naht. Ein Schnitt oder ein
        # Overlay daneben laesst sich weiterhin ueberall sonst in seiner
        # Breite anklicken.
        naht, naht_zeit = self._naht_unter(event.pos().x())
        if naht is not None:
            found_any = True
            self._naht_markieren(naht)
            try:
                self.nahtMenuRequested.emit(naht, naht_zeit, event.globalPos())
            finally:
                self._naht_markieren(None)
        # 2) Prüfen, ob time_clicked in einem Overlay-Intervall liegt
        for (start_s, end_s) in self._overlay_intervals:
            if found_any:
                break
            if start_s <= time_clicked <= end_s:
                found_any = True
                # Frueher kam hier sofort "Remove Overlay?". Seit sich ein
                # Overlay auch verschieben laesst und eigene Blendenlaengen
                # hat, ist Loeschen nur noch eine von mehreren
                # Moeglichkeiten - deshalb ein Menue, wie beim Schnitt.
                # Zusammengestellt wird es im Fenster.
                self._markieren(start_s, end_s)
                try:
                    self.overlayMenuRequested.emit(start_s, end_s,
                                                   event.globalPos())
                finally:
                    self._markieren(None)
                break
        # 3) Sonst pruefen, ob der Klick in einem Schnitt liegt
        #
        # Bis 6.01 schaltete der Rechtsklick sofort zwischen Blende und harter
        # Kante um. Seit dem Zuruecknehmen von Schnitten gibt es dort mehr als
        # eine Moeglichkeit, deshalb ein Menue. Zusammengestellt wird es im
        # MainWindow - nur dort ist bekannt, ob sich der Schnitt zuruecknehmen
        # laesst.
        if not found_any:
            for (start_s, end_s) in self._cut_intervals:
                if start_s <= time_clicked <= end_s:
                    found_any = True
                    # Das Menue laeuft in einer eigenen Ereignisschleife, der
                    # markierte Bereich wird also waehrenddessen gezeichnet.
                    self._markieren(start_s, end_s)
                    try:
                        self.cutMenuRequested.emit(start_s, end_s,
                                                   event.globalPos())
                    finally:
                        self._markieren(None)
                    break

        if not found_any:
            event.ignore()
        else:
            event.accept()

    
            