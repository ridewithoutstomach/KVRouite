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

import os
import sys
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QUrl, Signal, Slot, Qt, QTimer, QPoint
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QSettings

from core.gpx_parser import get_gpx_video_shift, is_gpx_video_shift_set


from .map_bridge import MapBridge

class MapWidget(QWidget):
    # Signal als Klassenattribut
    tracksDropped = Signal(list)  # list[str]
    """
    Neue Version: 2 Zustände => gelb (Video Play), blau (Pause-Klick).
    """
    # Signale
    pointClickedInPause = Signal(int)
    pointClickedInMap   = Signal(int)  # optional fürs MainWindow
    # Rechtsklick auf die Karte: (blauer Punkt oder -1, Position auf dem Schirm)
    contextMenuRequested = Signal(int, QPoint)

    def __init__(self, mainwindow=None, parent=None):
        super().__init__(parent)
        self._mainwindow = mainwindow

        # Zustands-Variablen
        self._video_is_playing = False
        self._yellow_idx = None
        self._blue_idx   = None
        self._num_points = 0
        self._markB_idx  = None
        self._markE_idx  = None
        self._curr_mapbox_profile = "cycling"
        # Was zuletzt in die Seite geschoben wurde - damit es nach einem
        # erzwungenen Neuladen zurueckgeholt werden kann. Siehe
        # neu_laden_und_wiederherstellen().
        self._letzte_route = None
        self._wiederherstellen = False

        # Layout + QWebEngineView
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        layout.addWidget(self.view)
        # View selbst soll Drops nicht übernehmen:
        self.view.setAcceptDrops(False)

        # Rechtsklick: nicht das Browser-Menue (Back, Reload, Save page...),
        # sondern unser eigenes. Gemeldet wird der zuletzt angeklickte Punkt
        # (der blaue) - so wandert ein auf der Karte gewaehlter Punkt ohne
        # Umweg ueber die Tabelle in die Lesezeichen. Das Menue selbst baut
        # das MainWindow, es kennt die Lesezeichen des Slots.
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)

        # Erlaubt: Remote URLs / z.B. OSM, MapTiler, Mapbox, Bing
        self.view.settings().setAttribute(
                QWebEngineSettings.LocalContentCanAccessRemoteUrls, True
        )

        # WebChannel + Bridge
        self._bridge = MapBridge()
        self._bridge.pointClickedSignal.connect(self.onMapPointClicked)

        self._channel = QWebChannel()
        self._channel.registerObject("mapBridge", self._bridge)
        self.view.page().setWebChannel(self._channel)

        # map_page.html laden
        from config import finde_datei
        html_path = finde_datei("map_page.html")
        self._html_url = QUrl.fromLocalFile(html_path)
        self.view.load(QUrl.fromLocalFile(html_path))

        # Callback, wenn HTML fertig geladen ist
        self.view.loadFinished.connect(self._on_map_page_load_finished)

        # Weitere Bridge-Signale
        self._bridge.pointMovedSignal.connect(self.on_point_moved)
        self._bridge.syncClickedNoArg.connect(self._on_sync_noarg_from_js)
        self._bridge.newPointInsertedSignal.connect(self._on_new_point_inserted)
        self._bridge.mapboxProfileChangedSignal.connect(self._on_mapbox_profile_changed)

        # --- Drag&Drop: GPX/FIT auf die Karte ---
        self.setAcceptDrops(True)
        from PySide6.QtWidgets import QLabel
        self._dnd_shield = QLabel("Drop GPX / FIT to import…", self)
        self._dnd_shield.setStyleSheet(
            "background: rgba(0,0,0,0.55); color: white; border: 2px dashed #ddd;"
            "border-radius: 12px; font-size: 18px; padding: 16px;"
        )
        self._dnd_shield.setAlignment(Qt.AlignCenter)
        self._dnd_shield.hide()
        
    @Slot(bool)
    def _on_map_page_load_finished(self, ok):
        """
        Wird aufgerufen, sobald map_page.html fertig geladen ist.
        Früher wurde hier der MapTiler-Key geladen,
        das macht jetzt aber NUR noch MainWindow (und sendet per JS).
        """
        if not ok:
            print("[WARN] Karte konnte nicht geladen werden.")
            return

        # Nach einem erzwungenen Neuladen (Zeilenwechsel des Fensters) die
        # Route und die Marker zurueckholen. Ueber den Zeitgeber, damit es
        # NACH den uebrigen loadFinished-Empfaengern laeuft - das
        # MainWindow setzt dort erst Punktgroessen und Schluessel.
        # Steht bewusst VOR dem print darunter: das enthaelt ein Zeichen,
        # das eine cp1252-Konsole nicht kennt, und wirft dann - alles,
        # was danach kaeme, liefe nicht mehr.
        if self._wiederherstellen:
            self._wiederherstellen = False
            QTimer.singleShot(0, self._route_wiederherstellen)

        print("[DEBUG] Karte ist geladen ⇒ wende jetzt ggf. QSettings-Einstellungen an.")
        # Beispiel: Du könntest hier nur noch "apply map-sizes" o. Ä. aufrufen.
        # Falls du eine Funktion in MainWindow hast, z. B. _apply_map_sizes_from_settings():
        if self._mainwindow and hasattr(self._mainwindow, "_apply_map_sizes_from_settings"):
            self._mainwindow._apply_map_sizes_from_settings()


    # ----------------------------
    # Drag&Drop (GPX/FIT)
    # ----------------------------
    def _extract_paths(self, mime):
        paths = []
        if mime and mime.hasUrls():
            for u in mime.urls():
                if u.isLocalFile():
                    paths.append(u.toLocalFile())
        elif mime and mime.hasText():
            for line in mime.text().splitlines():
                line = line.strip()
                if line:
                    paths.append(line)
        return paths

    def _is_track(self, path: str) -> bool:
        return path.lower().endswith((".gpx", ".fit"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._dnd_shield:
            self._dnd_shield.setGeometry(self.rect())
    
    
    @Slot(float, float, int)
    def _on_new_point_inserted(self, lat, lon, idx):
        """
        Ruft MainWindow.on_new_gpx_point_inserted(...) auf,
        falls vorhanden. So kann das GPX-Handling fortgesetzt werden.
        """
        if self._mainwindow and hasattr(self._mainwindow, "on_new_gpx_point_inserted"):
            self._mainwindow.on_new_gpx_point_inserted(lat, lon, idx)
            
        if self._blue_idx is not None:
            print(f"[DEBUG] Re-selecting blue_idx={self._blue_idx} after insert")
            self.set_selected_point(self._blue_idx)    

    @Slot()
    def _on_sync_noarg_from_js(self):
        """
        JS => channelObj.syncClickedNoArg() => rufe mainwindow.on_map_sync_any().
        """
        if self._mainwindow and hasattr(self._mainwindow, "on_map_sync_any"):
            self._mainwindow.on_map_sync_any()

    def on_point_moved(self, index: int, lat: float, lon: float):
        """
        Wird gerufen, wenn man im Browser (Karte) einen Punkt draggt.
        Reicht an MainWindow weiter, falls on_point_moved existiert.
        """
        if self._mainwindow and hasattr(self._mainwindow, "on_point_moved"):
            self._mainwindow.on_point_moved(index, lat, lon)

    def loadRoute(self, route_geojson: dict, do_fit: bool = True):
        """
        Ruft loadRoute(...) in JS auf, um ein GeoJSON in der Karte darzustellen.
        Leer -> schneller Blank-Pfad (Reload), damit 'New Project' sofort ist.
        """
        if not route_geojson or not isinstance(route_geojson, dict):
            return

        features = route_geojson.get("features", [])
        # --- FAST BLANK: Wenn keine Features -> Map schnell resetten (kein JS-Render) ---
        if not features:
            # internen State zurücksetzen
            self._num_points = 0
            self._blue_idx = None
            self._yellow_idx = None
            self._markB_idx = None
            self._markE_idx = None
            self._letzte_route = None
            try:
                # Seite neu laden = Startzustand, sehr schnell
                self.view.load(self._html_url)
            except Exception:
                pass
            return
        # --- normaler Render-Pfad ---
        self._num_points = sum(
            1 for feat in features
            if feat.get("geometry", {}).get("type") == "Point"
        )
        self._letzte_route = route_geojson
        do_fit_str = "true" if do_fit else "false"
        js = f"loadRoute({json.dumps(route_geojson)}, {do_fit_str});"
        self.view.page().runJavaScript(js)

    def neu_laden_und_wiederherstellen(self):
        """Seite neu laden und danach Route und Marker zurueckholen.

        Gebraucht, wenn die Karte in die andere Fensterzeile wandert: sie
        bekommt dann einen neuen Vater und ein neu erzeugtes natives
        Fenster, und ohne Neuladen bleibt die Seite weiss. Ein Neuladen
        laedt aber map_page.html von vorn - alles, was per JavaScript in
        die Seite kam, ist damit weg. Bis zum 04.09.2026 wurde nur neu
        geladen, und die Karte zeigte danach Europa ohne Strecke.

        Die Daten selbst sind nie weg gewesen - sie liegen im MainWindow.
        Die Karte hatte nur vergessen, was sie zeigen soll.
        """
        self._wiederherstellen = True
        self.view.reload()

    def _route_wiederherstellen(self):
        """Nach dem Neuladen: Route, B/E und den aktuellen Punkt zurueck."""
        route = self._letzte_route
        if not route:
            return
        # Indizes VOR loadRoute sichern - loadRoute laesst sie zwar stehen,
        # aber show_blue() prueft gegen _num_points, das erst dort entsteht.
        blau, markb, marke = self._blue_idx, self._markB_idx, self._markE_idx
        # do_fit=True: die frisch geladene Seite steht auf ihrem Startbild
        # (Europa), die Strecke soll gleich das Bild fuellen.
        self.loadRoute(route, do_fit=True)
        if markb is not None:
            self.set_markB_point(markb)
        if marke is not None:
            self.set_markE_point(marke)
        if blau is not None:
            self._blue_idx = None          # sonst haelt show_blue ihn fuer schon gesetzt
            self.show_blue(blau, do_center=False)

    # ----------------------------------------------------------
    # Markierungen B/E
    # ----------------------------------------------------------
    def set_markB_idx(self, b_idx: int):
        self._markB_idx = b_idx

    def set_markE_idx(self, e_idx: int):
        self._markE_idx = e_idx

    def set_markB_point(self, new_b: int):
        if new_b < 0:
            return
        self._markB_idx = new_b
        js_code = f"set_markB_point({new_b});"
        self.view.page().runJavaScript(js_code)

    def set_markE_point(self, new_e: int):
        if new_e < 0:
            return
        js_code = f"set_markE_point({new_e});"
        self.view.page().runJavaScript(js_code)

    def clear_marked_range(self):
        js_code = "clear_marked_range();"
        self.view.page().runJavaScript(js_code)

    # ----------------------------------------------------------
    # Play/Pause -> Video
    # ----------------------------------------------------------
    def set_video_playing(self, playing: bool):
        """
        Wird vom MainWindow aufgerufen, wenn Play/Pause umgeschaltet wird.
        """
        self._video_is_playing = playing

        if is_gpx_video_shift_set():
            js_bool = "true" if playing else "false"
            self.view.page().runJavaScript(f"setVideoPlayState({js_bool})")

            if playing:
                # alten blauen Marker entfernen
                if self._blue_idx is not None and self._blue_idx < len(self._mainwindow._gpx_data):
                    delta_ts = (
                        self._mainwindow._gpx_data[self._blue_idx].get("time", 0.0) -
                        self._mainwindow._gpx_data[0].get("time", 0.0)
                    ).total_seconds() + get_gpx_video_shift()
                    
                    self._color_point(self._blue_idx, "#000000" if delta_ts >= 0 else "gray") 
                    self._blue_idx = None
            else:
                # Bei Pause belassen wir ggf. den gelben Marker
                pass

    # ----------------------------------------------------------
    # Klick in der Karte => onMapPointClicked
    # ----------------------------------------------------------
    @Slot(int)
    def _on_context_menu(self, pos):
        """Rechtsklick auf die Karte -> contextMenuRequested(blauer Punkt oder -1, global)."""
        idx = self._blue_idx if self._blue_idx is not None else -1
        self.contextMenuRequested.emit(idx, self.view.mapToGlobal(pos))

    def onMapPointClicked(self, index_clicked: int):
        """
        Wenn das Video pausiert, machen wir 'show_blue'.
        Danach benachrichtigen wir MainWindow, dass index_clicked geklickt wurde.
        """
        if self._video_is_playing:
            return
        self.show_blue(index_clicked)

        if self._mainwindow and hasattr(self._mainwindow, "on_user_selected_index"):
            self._mainwindow.on_user_selected_index(index_clicked)

    # ----------------------------------------------------------
    # Hilfsfunktion: JS highlightPoint(...)
    # ----------------------------------------------------------
    def _color_point(self, index: int, color: str, size: int=None, do_center: bool=False):
        """
        Ruft in map_page.html => highlightPoint(index, color, size, do_center) auf.
        'color' ist jetzt nur noch 'black', 'red', 'blue', 'yellow'.
        Falls size=None, soll JS den Wert aus colorSizeMap[...] selbst holen.
        """
        if size is None:
            size_str = "null"
        else:
            size_str = str(size)
    
        do_center_str = "true" if do_center else "false"
    
        js_code = (
            f"highlightPoint({index}, '{color}', {size_str}, {do_center_str});"
        )
        self.view.page().runJavaScript(js_code)


    # ----------------------------------------------------------
    # show_blue / show_yellow
    # ----------------------------------------------------------
    def show_blue(self, index: int, do_center: bool=False):
        """
        Marker in 'blue', wenn das Video pausiert.
        Macht vorher den alten blue_idx rückgängig => 'black' oder 'red' (je nach B/E).
        Entfernt auch ggf. den yellow_idx, falls wir umschalten.
        """
        if index < 0 or index >= self._num_points:
            return
    
        # alten blauen Marker revertieren
        if self._blue_idx is not None and self._blue_idx != index:
            old_b = self._blue_idx
            color_old = self.get_default_color_for_index(old_b)
            self._color_point(old_b, color_old, None, False)
            self._blue_idx = None

        # alten gelben Marker revertieren
        if self._yellow_idx is not None:
            old_y = self._yellow_idx
            color_old_y = self.get_default_color_for_index(old_y)
            self._color_point(old_y, color_old_y, None, False)
            self._yellow_idx = None

        # jetzt den neuen Index blau
        self._blue_idx = index
        self._color_point(index, "blue", None, do_center)

    def show_yellow(self, index: int, do_center: bool=False):
        """
        Marker in 'yellow' während des Video-Playbacks.
        """
        if index == self._yellow_idx:
            return
        if index < 0 or index >= self._num_points:
            return

        # alten gelben Marker revertieren
        if self._yellow_idx is not None:
            old_y = self._yellow_idx
            color_old = self.get_default_color_for_index(old_y)
            self._color_point(old_y, color_old, None, False)
            self._yellow_idx = None

        # falls wir dasselbe Index in blau hatten => revertieren
        if self._blue_idx == index:
            color_old_b = self.get_default_color_for_index(index)
            self._color_point(index, color_old_b, None, False)
            self._blue_idx = None

        # Neuer Index => 'yellow'
        self._yellow_idx = index
        self._color_point(index, "yellow", None, do_center)

    

    # ----------------------------------------------------------
    # Farblogik (rot bei MarkB..MarkE, sonst schwarz)
    # ----------------------------------------------------------
    

    def get_default_color_for_index(self, i: int) -> str:
        """
        Gibt für den Index i die "normale" Farbe zurück:
        - 'red', wenn i in [markB_idx .. markE_idx]
        - sonst 'black'
        """
        if self._markB_idx is not None and self._markE_idx is not None:
            b = min(self._markB_idx, self._markE_idx)
            e = max(self._markB_idx, self._markE_idx)
            if b <= i <= e:
                return "red"
        elif self._markB_idx is not None:
            if i == self._markB_idx:
                return "red"
        elif self._markE_idx is not None:
            if i == self._markE_idx:
                return "red"

        # Sicherer Zugriff auf GPX-Daten
        gpx_data = getattr(self._mainwindow, "_gpx_data", None)
        if not isinstance(gpx_data, list) or len(gpx_data) == 0:
            # Keine Daten => neutrales Schwarz
            return "black"
        if i < 0 or i >= len(gpx_data):
            # Out-of-range gegenüber _gpx_data => neutrales Schwarz
            return "black"

        try:
            t_i = gpx_data[i].get("time", 0.0)
            t_0 = gpx_data[0].get("time", 0.0)
            # We count if both date-like
            if hasattr(t_i, "total_seconds") and hasattr(t_0, "total_seconds"):
                rel_s = (t_i - t_0).total_seconds() + get_gpx_video_shift()
                return "black" if rel_s >= 0 else "gray"
        except Exception:
            # On any unexpected case black
            pass

        return "black"
    
    def set_selected_point(self, idx: int):
        print(f"[DEBUG] MapWidget: selected_point set to idx={idx}")
        self._blue_idx = idx
        self._color_point(idx, "blue", None, False)  # ← blau färben
        js = f"selectPointByIndex({idx});"
        self.view.page().runJavaScript(js)
    
    def zoom_to_index(self, idx: int, zoom: int = 18):
        print(f"[DEBUG] MapWidget.zoom_to_index idx={idx} zoom={zoom}")
        js = f"zoomToIndex({idx}, {int(zoom)});"
        self.view.page().runJavaScript(js)

    def center_on_index(self, idx: int):
        """Karte auf den Punkt zentrieren, ohne Zoom und Farben anzufassen.
        show_blue() faerbt den Punkt blau und ueberdeckt damit eine rote
        Marke - hier soll die Marke sichtbar bleiben."""
        if idx is None or idx < 0:
            return
        self.view.page().runJavaScript(f"centerOnIndex({int(idx)});")
    
    def _on_mapbox_profile_changed(self, profile: str):
        print(f"[DEBUG] MapWidget: mapboxProfileChanged => profile={profile}")
        self._curr_mapbox_profile = profile