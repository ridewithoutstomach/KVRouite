# -*- coding: utf-8 -*-
#
# This file is part of VGSync.
#
# Copyright (C) 2025 by Bernd Eller
#
# VGSync is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# VGSync is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with VGSync. If not, see <https://www.gnu.org/licenses/>.
#

import os
import sys
import json
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QUrl, Signal, Slot
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QSettings

from core.gpx_parser import is_gpx_video_shift_set


from .map_bridge import MapBridge

class MapWidget(QWidget):
    """
    Neue Version: 2 Zustände => gelb (Video Play), blau (Pause-Klick).
    """
    # Signale
    pointClickedInPause = Signal(int)
    pointClickedInMap   = Signal(int)  # optional fürs MainWindow

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

        # Layout + QWebEngineView
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        layout.addWidget(self.view)

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
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        html_path = os.path.join(base_dir, "map_page.html")
        self.view.load(QUrl.fromLocalFile(html_path))

        # Callback, wenn HTML fertig geladen ist
        self.view.loadFinished.connect(self._on_map_page_load_finished)

        # Weitere Bridge-Signale
        self._bridge.pointMovedSignal.connect(self.on_point_moved)
        self._bridge.syncClickedNoArg.connect(self._on_sync_noarg_from_js)
        self._bridge.newPointInsertedSignal.connect(self._on_new_point_inserted)

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

        print("[DEBUG] Karte ist geladen ⇒ wende jetzt ggf. QSettings-Einstellungen an.")
        # Beispiel: Du könntest hier nur noch "apply map-sizes" o. Ä. aufrufen.
        # Falls du eine Funktion in MainWindow hast, z. B. _apply_map_sizes_from_settings():
        if self._mainwindow and hasattr(self._mainwindow, "_apply_map_sizes_from_settings"):
            self._mainwindow._apply_map_sizes_from_settings()

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
        """
        if not route_geojson or not isinstance(route_geojson, dict):
            return

        # Anzahl Points ermitteln
        features = route_geojson.get("features", [])
        self._num_points = sum(
            1 for feat in features
            if feat.get("geometry", {}).get("type") == "Point"
        )

        
        do_fit_str = "true" if do_fit else "false"
        js = f"loadRoute({json.dumps(route_geojson)}, {do_fit_str});"
        self.view.page().runJavaScript(js)

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
                if self._blue_idx is not None:
                    
                    
                    self._color_point(self._blue_idx, "#000000")
                    self._blue_idx = None
            else:
                # Bei Pause belassen wir ggf. den gelben Marker
                pass

    # ----------------------------------------------------------
    # Klick in der Karte => onMapPointClicked
    # ----------------------------------------------------------
    @Slot(int)
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
    def is_in_marked_range(self, idx: int) -> bool:
        if self._markB_idx is not None and self._markE_idx is not None:
            b = min(self._markB_idx, self._markE_idx)
            e = max(self._markB_idx, self._markE_idx)
            return (b <= idx <= e)
        elif self._markB_idx is not None:
            return (idx == self._markB_idx)
        elif self._markE_idx is not None:
            return (idx == self._markE_idx)
        else:
            return False

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

        return "black"
        
        

    def get_default_size_for_color(self, color: str) -> int:
        s = QSettings("VGSync", "VGSync")

        c = color.lower()
        if c in ("#ff0000"):
            color_key = "#FF0000"  # wir speichern dann in QSettings => mapSize/#FF0000
        elif c in ("#0000ff"):
            color_key = "#0000FF"
        elif c in ("#ffff00"):
            color_key = "#FFFF00"
        else:
            color_key = "#000000"

        # Standardwert 6 bei gelb, sonst 4
        if color_key == "#FFFF00":
            default_val = 6
        else:
            default_val = 4

        val = s.value(f"mapSize/{color_key}", default_val, type=int)
        return val

    def set_selected_point(self, idx: int):
        print(f"[DEBUG] MapWidget: selected_point set to idx={idx}")
        self._blue_idx = idx
        self._color_point(idx, "blue", None, False)  # ← blau färben
        js = f"selectPointByIndex({idx});"
        self.view.page().runJavaScript(js)
        
    