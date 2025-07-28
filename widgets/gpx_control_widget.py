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

# gpx_control_widget.py 
## aufgeräumt

import copy
import math
import urllib.request
import urllib.error
import json

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QStyle,
    QVBoxLayout, QLabel, QSizePolicy, QFrame,
    QMenu, QDialog, QRadioButton, QButtonGroup,
    QDoubleSpinBox, QMessageBox, QFileDialog,
    QLineEdit
)

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QIcon

from datetime import timedelta
from core.gpx_parser import recalc_gpx_data, get_gpx_video_shift, set_gpx_video_shift


class GPXControlWidget(QWidget):
    """
    Enthält die Buttons (MarkB, MarkE, x, Delete, chTime, chEle, ch%, Undo, Smooth, Save)
    UND eine Info-Zeile darunter, in der wir vier Labels anzeigen:
    - Video: ...
    - Length(GPX): ...
    - Duration(GPX): ...
    - Elevation Gain: ...
    """

    # Signale
    markBClicked = Signal()
    markEClicked = Signal()
    deselectClicked = Signal()  # "x"
    cutClicked = Signal()
    removeClicked = Signal()
    chTimeClicked = Signal()
    chEleClicked = Signal()
    chPercentClicked = Signal()
    #undoClicked = Signal()
    smoothClicked = Signal()
    #saveClicked = Signal()
    showMaxSlopeClicked = Signal()
    showMinSlopeClicked = Signal()
    averageSpeedClicked = Signal()
    maxSpeedClicked = Signal()
    minSpeedClicked = Signal()
    closeGapsClicked = Signal()
    deleteWayErrorsClicked = Signal()
    deleteTimeErrorsClicked = Signal()


    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._mainwindow = None
        


        # SORGT DAFÜR, DASS DAS WIDGET NICHT ENDLOS IN DIE HÖHE WÄCHST
        self.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        )

        # Oberstes (vertikales) Layout, darin: Buttons-Zeile + Info-Zeile
        self.main_vbox = QVBoxLayout(self)
        self.main_vbox.setContentsMargins(5, 5, 5, 5)
        self.main_vbox.setSpacing(5)

        # ---------------------------------------------
        # (A) Erste Zeile: Buttons
        # ---------------------------------------------
        self._buttons_layout = QHBoxLayout()
        self._buttons_layout.setSpacing(5)
        self.main_vbox.addLayout(self._buttons_layout)

        # 1) MarkB
        self.markB_button = QPushButton("[-", self)
        self.markB_button.setToolTip("Mark the Begin of the Cut in the GPX")
        
        self.markB_button.setMaximumWidth(40)
        self.markB_button.clicked.connect(self.markBClicked.emit)
        self._buttons_layout.addWidget(self.markB_button)
        
        self._default_markB_style = self.markB_button.styleSheet() or ""

        # 2) MarkE
        self.markE_button = QPushButton("-]", self)
        self.markE_button.setToolTip("Mark the End of the Cut in the GPX")
        
        self.markE_button.setMaximumWidth(40)
        self.markE_button.clicked.connect(self.markEClicked.emit)
        self._buttons_layout.addWidget(self.markE_button)
        
        self._default_markE_style = self.markE_button.styleSheet() or ""

        # 3) x => "deselect"
        self.deselect_button = QPushButton("x", self)
        self.deselect_button.setToolTip("Deselect the marked Area")
        
        self.deselect_button.setMaximumWidth(40)
        self.deselect_button.clicked.connect(self.deselectClicked.emit)
        self._buttons_layout.addWidget(self.deselect_button)

        # 4) Delete
        self.cut_button = QPushButton("✂️", self)
        self.cut_button.setToolTip("Cut a marked Area and shift next points time")
        self.cut_button.setMinimumWidth(20)
        
        self.cut_button.clicked.connect(self.cutClicked.emit)
        self._buttons_layout.addWidget(self.cut_button)
        
        self.minus_button = QPushButton("➖", self)
        self.minus_button.setToolTip("Remove a marked Area without time shift")
        self.minus_button.setMinimumWidth(20)
        
        self.minus_button.clicked.connect(self.removeClicked.emit)
        self._buttons_layout.addWidget(self.minus_button)
        

        # 5) chTime
        self.chTime_button = QPushButton("chT", self)
        self.chTime_button.setToolTip("Change the Step (time) of a point")
        self.chTime_button.setMaximumWidth(50)
        self.chTime_button.clicked.connect(self.chTimeClicked.emit)
        self._buttons_layout.addWidget(self.chTime_button)

        # 6) chEle
        self.chEle_button = QPushButton("chEle", self)
        self.chEle_button.setToolTip("Change the height of a single point or move a complete height of a marked area")
        self.chEle_button.setMaximumWidth(50)
        self.chEle_button.clicked.connect(self.chEleClicked.emit)
        self._buttons_layout.addWidget(self.chEle_button)

        # 7) ch%
        #self.chPercent_button = QPushButton("%↗",self)
        self.chPercent_button = QPushButton("ch%",self)
        self.chPercent_button.setToolTip("Change the slope of a point/range of points")
        self.chPercent_button.setMaximumWidth(50)
        self.chPercent_button.clicked.connect(self.chPercentClicked.emit)
        self._buttons_layout.addWidget(self.chPercent_button)
            
        self.more_button = QPushButton("...", self)
        self.more_button.setToolTip("More...")
        self.more_button.setMaximumWidth(50)  
        self._buttons_layout.addWidget(self.more_button)

        # (Menü anlegen)
        self.more_menu = QMenu(self.more_button)
        
        #action_maxslope = self.more_menu.addAction("show max%")
        #action_maxslope.triggered.connect(self.showMaxSlopeClicked.emit)
        
        #action_minslope = self.more_menu.addAction("show min%")
        #action_minslope.triggered.connect(self.showMinSlopeClicked.emit)
        
        #action_maxspeed = self.more_menu.addAction("show MaxSpeed")
        #action_minispeed = self.more_menu.addAction("show MinSpeed")

        #action_maxspeed.triggered.connect(self.maxSpeedClicked.emit)
        #action_minispeed.triggered.connect(self.minSpeedClicked.emit)
        
        action_avgspeed = self.more_menu.addAction("Set AverageSpeed")
        action_avgspeed.triggered.connect(self.averageSpeedClicked.emit)
        
        self._action_closegaps = self.more_menu.addAction("Close Gaps")
        self._action_closegaps.triggered.connect(self.closeGapsClicked.emit)
        
        action_del_way_errors = self.more_menu.addAction("Delete Way Errors")
        action_del_way_errors.triggered.connect(self.deleteWayErrorsClicked.emit)
        
        
        action_delete_time_errors = self.more_menu.addAction("Delete Time Errors")
        action_delete_time_errors.triggered.connect(self.deleteTimeErrorsClicked.emit)
        
        action_cut_before_b = self.more_menu.addAction("Cut all before markB")
        action_cut_before_b.triggered.connect(self.on_cut_before_b_clicked)

        action_cut_after_e = self.more_menu.addAction("Cut all after markB")
        action_cut_after_e.triggered.connect(self.on_cut_after_e_clicked)
        
        
        self._action_set_gpx2video = self.more_menu.addAction("SetGPX2VideoTime")
        self._action_set_gpx2video.setEnabled(False)  # standard aus
        self._action_set_gpx2video.triggered.connect(self._on_set_gpx2video_triggered)
        
        #action_get_ele = self.more_menu.addAction("GetElevation from Open-Elevation")
        #action_get_ele.triggered.connect(self._on_get_ele_open_elevation)
        
        action_get_ele_mapbox = self.more_menu.addAction("GetElevation from Mapbox")
        action_get_ele_mapbox.triggered.connect(self._on_get_ele_mapbox)

        
        action_set_height_b2e = self.more_menu.addAction("setHeight(B2E)")
        action_set_height_b2e.triggered.connect(self.on_setHeight_B2E_clicked)
        
        action_resample = self.more_menu.addAction("Resample to 1s")
        action_resample.triggered.connect(self._on_resample_to_1s_clicked)
        
        
        # Menü dem Button zuweisen
        self.more_button.clicked.connect(self._on_more_button_clicked)
              

        # 8) Undo
        #self.undo_button = QPushButton("Undo", self)
        #self.undo_button.setMaximumWidth(50)
        #self.undo_button.clicked.connect(self.undoClicked.emit)
        #self._buttons_layout.addWidget(self.undo_button)

        # 9) Smooth
        self.smooth_button = QPushButton("Smooth", self)
        #self.undo_button.setMaximumWidth(50)
        self.smooth_button.setToolTip("Smooth the complete GPX \nChoose this only if you have complete edited!")
        self.smooth_button.clicked.connect(self.smoothClicked.emit)
        self._buttons_layout.addWidget(self.smooth_button)

        # 10) Save
        # self.save_button = QPushButton("", self)
        # self.save_button.setIcon(self.style().standardIcon(QStyle.SP_DriveHDIcon))
        # self.save_button.setMinimumWidth(60)
        # self.save_button.setMaximumWidth(80)
        
        # self.save_button.clicked.connect(self.saveClicked.emit)
        # self._buttons_layout.addWidget(self.save_button)

        self._buttons_layout.addStretch()  # optional: damit die Buttons nach links rücken

        # ---------------------------------------------
        # (B) Zweite Zeile: Info (Video/Length/Duration/Elev)
        # ---------------------------------------------
        self._info_layout = QHBoxLayout()
        self._info_layout.setSpacing(10)  # Zwischenraum zwischen Labels
        self.main_vbox.addLayout(self._info_layout)
        
        self.label_video = QLabel("Video: 00:00:00", self)
        self._info_layout.addWidget(self.label_video)

        self.label_length = QLabel("Length(GPX): 0.00 km", self)
        self._info_layout.addWidget(self.label_length)

        self.label_duration = QLabel("Duration(GPX): 00:00:00", self)
        self._info_layout.addWidget(self.label_duration)

        self.label_elev = QLabel("Elevation Gain: 0 m", self)
        self._info_layout.addWidget(self.label_elev)
        
        self.label_slope_max = QLabel("Max%: 0.0%", self)
        self._info_layout.addWidget(self.label_slope_max)
        
        self.label_slope_min = QLabel("Min%: 0.0%", self)
        self._info_layout.addWidget(self.label_slope_min)

        self.label_zerospeed = QLabel("ZeroSpeed: 0", self)
        self._info_layout.addWidget(self.label_zerospeed)
        
        self.label_paused = QLabel("Breaks: 0", self)
        self._info_layout.addWidget(self.label_paused)
        

        # Falls du sie mittig haben willst, kannst du z. B. links und rechts stretch:
        #self._info_layout.insertStretch(0)  # links
        self._info_layout.addStretch()      # rechts
        
    
    
    def on_setHeight_B2E_clicked(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        if b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range Selected",
                            "Please mark a range (markB..markE) first.")
            return

        # Falls markB > markE => tauschen
        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx

        if (e_idx - b_idx) < 1:
            QMessageBox.warning(self, "Invalid Range",
                            "The selected range must contain at least 2 points.")
            return

        # 1) Start/End-Höhen merken
        start_ele = gpx_data[b_idx].get("ele", 0.0)
        old_end_ele = gpx_data[e_idx].get("ele", 0.0)  # Original-Endhöhe vor Änderung

        # 2) Dialog: User wählt neue End-Höhe
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Set Height B..E (Wave-Preserve) – Range {b_idx}..{e_idx}")
        vbox = QVBoxLayout(dlg)

        lbl_info = QLabel(
            f"You have selected a range from index {b_idx} to {e_idx}.\n"
            "We will preserve the wave shape in [B..E], but shift the end to your new value.\n"
            "The start's elevation remains the same, the end's elevation is changed,\n"
            "and all in-between points keep their relative offsets.\n\n"
            "All subsequent points (after E) will be shifted by the difference from old_end_ele to new_end_ele."
        )
        vbox.addWidget(lbl_info)

        # Start-Höhe (read-only)
        row_start = QHBoxLayout()
        lbl_start = QLabel(f"Start Height ({b_idx}):")
        edit_start = QLineEdit(f"{start_ele:.2f}")
        edit_start.setReadOnly(True)
        row_start.addWidget(lbl_start)
        row_start.addWidget(edit_start)
        vbox.addLayout(row_start)

        # End-Höhe (editierbar)
        row_end = QHBoxLayout()
        lbl_end = QLabel(f"End Height ({e_idx}):")
        spin_end = QDoubleSpinBox()
        spin_end.setRange(-9999.0, 99999.0)  # je nach Bedarf anpassen
        spin_end.setDecimals(2)
        spin_end.setSingleStep(0.1)
        spin_end.setValue(old_end_ele)  # Vorbelegung
        row_end.addWidget(lbl_end)
        row_end.addWidget(spin_end)
        vbox.addLayout(row_end)

        # OK/Cancel
        h_btn = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        h_btn.addWidget(btn_ok)
        h_btn.addWidget(btn_cancel)
        vbox.addLayout(h_btn)
    
        def haversine_m(lat1, lon1, lat2, lon2):
            import math
            R = 6371000.0
            d_lat = math.radians(lat2 - lat1)
            d_lon = math.radians(lon2 - lon1)
            a = (math.sin(d_lat / 2.0) ** 2
                + math.cos(math.radians(lat1))
                * math.cos(math.radians(lat2))
                * math.sin(d_lon / 2.0) ** 2)
            return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        def calc_total_2d_distance(idxA, idxB):
            dist_sum = 0.0
            for x in range(idxA, idxB):
                lat1, lon1 = gpx_data[x]["lat"], gpx_data[x]["lon"]
                lat2, lon2 = gpx_data[x+1]["lat"], gpx_data[x+1]["lon"]
                dist_sum += haversine_m(lat1, lon1, lat2, lon2)
            return dist_sum
    
        def calc_cumulative_dist(idxA, idxI):
            # Distance from idxA to idxI
            return calc_total_2d_distance(idxA, idxI)
    
        def on_ok_dialog():
            new_end_val = spin_end.value()
            dlg.accept()

            # Undo-Snapshot
            #old_data = copy.deepcopy(gpx_data)
            #mw.gpx_widget.gpx_list._history_stack.append(old_data)
            self.register_gpx_undo_snapshot()
            

            # (A) Gesamtstrecke 2D in [b_idx.. e_idx]
            total_2d = calc_total_2d_distance(b_idx, e_idx)
            if total_2d < 0.001:
                QMessageBox.warning(
                    self, "Zero distance",
                    f"Range {b_idx}..{e_idx} has almost no 2D distance => can't do wave-based approach."
                )
                return
    
            # (B) Alte "Basislinie" + waveOffsets bestimmen
            #     Basislinie alt: L(i) = start_ele + frac*(old_end_ele - start_ele)
            #     waveOffset_i = oldEle_i - L(i)
            wave_offsets = {}
            for i in range(b_idx, e_idx + 1):
                dist_i = calc_cumulative_dist(b_idx, i)
                frac = dist_i / total_2d
                old_line_ele_i = start_ele + frac * (old_end_ele - start_ele)
                actual_ele_i   = gpx_data[i]["ele"]
                wave_offsets[i] = actual_ele_i - old_line_ele_i

            # (C) Neue Basislinie (start_ele -> new_end_val) + Wave Offset
            #     newEle_i = (start_ele + frac*(new_end_val - start_ele)) + waveOffset[i]
            for i in range(b_idx, e_idx + 1):
                dist_i = calc_cumulative_dist(b_idx, i)
                frac   = dist_i / total_2d
                new_line_ele_i = start_ele + frac * (new_end_val - start_ele)
                gpx_data[i]["ele"] = new_line_ele_i + wave_offsets[i]

            # (D) Konstanter Offset für alle Punkte ab e_idx+1
            offset = gpx_data[e_idx]["ele"] - old_end_ele

            # -- FIXED: Statt gpx_data[j]["ele"] + offset => old_data[j]["ele"] + offset 
            for j in range(e_idx + 1, len(gpx_data)):
                #old_ele_j = old_data[j]["ele"]  # der unveränderte Wert vor der Aktion
                #gpx_data[j]["ele"] = old_ele_j + offset
                gpx_data[j]["ele"] += offset
            # Recalc & Refresh
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()

            # -> Chart
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)

            QMessageBox.information(
                self, "Done",
                f"Range {b_idx}..{e_idx} wave-preserved.\n"
                f"Start remains {start_ele:.2f}m, end changed to {gpx_data[e_idx]['ele']:.2f}m.\n\n"
                f"All subsequent points (>{e_idx}) shifted by +{offset:.2f}m."
            )
            self.markB_index = None
            self.markE_index = None
            

            # Marker-Indexe zurücksetzen
            mw.gpx_widget.gpx_list._markB_idx = None
            mw.gpx_widget.gpx_list._markE_idx = None

            # Buttons zurücksetzen
            self.markB_button.setStyleSheet("")
            self.markE_button.setStyleSheet("")
            
            
        def on_cancel_dialog():
            dlg.reject()

        btn_ok.clicked.connect(on_ok_dialog)
        btn_cancel.clicked.connect(on_cancel_dialog)
        dlg.exec()
    """
    
    def update_from_open_elevation(self,latlon_list):
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data

        # => Rate Limits => Aufteilung in Blöcke
        CHUNK_SIZE = 200
        total_points = len(latlon_list)
        idx_start = 0

        while idx_start < total_points:
            idx_end = min(idx_start+CHUNK_SIZE, total_points)
            subset = latlon_list[idx_start:idx_end]

            # Open-Elevation erwartet: POST /api/v1/lookup => json={"locations":[{"latitude":..,"longitude":..},..]}
            locations_payload = []
            for (gpx_i, la, lo) in subset:
                locations_payload.append({"latitude": la, "longitude": lo})
            payload = {"locations": locations_payload}
            

            # => In JSON-Bytes wandeln
            data_bytes = json.dumps(payload).encode("utf-8")
            url = "https://api.open-elevation.com/api/v1/lookup"
        
            # Request-Objekt vorbereiten:
            req = urllib.request.Request(
                url=url,
                data=data_bytes,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
        
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    # Antwort lesen:
                    body = resp.read().decode("utf-8", errors="replace")
            
                result_json = json.loads(body)
                results_arr = result_json.get("results", [])
                if len(results_arr) != len(subset):
                    QMessageBox.warning(self, "Mismatch", 
                        f"Open-Elevation returned {len(results_arr)} results instead of {len(subset)}.\n"
                        "Maybe partial data or an error.")
                    return

                # => In gpx_data eintragen
                for idx_in_block, item in enumerate(results_arr):
                    elev = item.get("elevation", 0.0)
                    (gpx_i, lat_, lon_) = subset[idx_in_block]
                    gpx_data[gpx_i]["ele"] = float(elev)

            except urllib.error.HTTPError as http_err:
                QMessageBox.critical(
                    self, 
                    "Open-Elevation Error",
                    f"HTTP Error: {http_err.code}\n{http_err.reason}\n\nTry smaller ranges."
                )
                return
            except urllib.error.URLError as url_err:
                QMessageBox.critical(
                    self,
                    "Open-Elevation Error",
                    f"URL Error: {url_err}\nCheck your connection or try smaller ranges."
                )
                return
            except Exception as err:
                QMessageBox.critical(
                    self, 
                    "Open-Elevation Error",
                    f"Request failed:\n{err}\n\nPlease try smaller ranges."
                )
                return

            idx_start = idx_end

      
    """
    """        
    def _on_get_ele_open_elevation(self):
       
        

        mw = self._mainwindow
        if not mw:
            return
    
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return
    
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        if b_idx is None or e_idx is None or b_idx < 0 or e_idx < 0:
            QMessageBox.warning(self, "No Range", 
                "Please mark a GPX range (B..E) first.")
            return
        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx
        if (e_idx - b_idx) < 1:
            QMessageBox.information(self, "Invalid Range", 
                "At least 2 points needed in B..E range.")
            return
    
        # 1) Warnhinweis (englisch)
        warn_text = (
            "Open-Elevation is a free service with limited requests.\n"
            "If you have many points, the service might reject or fail.\n"
            "It is recommended to do it in smaller chunks if an error occurs.\n\n"
            "Do you want to proceed?"
        )
        reply = QMessageBox.question(
            self,
            "Open-Elevation Warning",
            warn_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
    
        # 2) Undo-Snapshot
        self.register_gpx_undo_snapshot()
        
        # 3) Alle lat/lon im Bereich B..E sammeln
        latlon_list = []
        for i in range(b_idx, e_idx+1):
            pt = gpx_data[i]
            lat = pt.get("lat", 0.0)
            lon = pt.get("lon", 0.0)
            latlon_list.append((i, lat, lon))  # index, lat, lon
    

        # 4) Schleife über Blöcke
        self.update_from_open_elevation(latlon_list)

        # 5) recalc + set
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()

        # 6) chart, mini_chart
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)

        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()

        # 7) Map => reload
        #route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        #mw.map_widget.loadRoute(route_geojson, do_fit=False)

        QMessageBox.information(
            self,
            "Done",
            f"Elevation updated for {e_idx-b_idx+1} points via Open-Elevation!"
        )
    
    """    
    def update_elevation_from_mapbox(self, latlon_list):
        """
        Holt Elevation für latlon_list via Mapbox Terrain-RGB Tiles.
        latlon_list: [(gpx_idx, lat, lon), ...]
        Gibt zurück: (successful_points, tile_count)
        """
        import math
        from PIL import Image
        import io

        mw = self._mainwindow
        if not mw:
            return (0, 0)

        token = mw._mapbox_key.strip()
        if not token:
            print("[INFO] No Mapbox key – skipping elevation update")
            #QMessageBox.warning(self, "No Mapbox Key", "No Mapbox API key found. Please set it in Config > Map Keys.")
            return (0, 0)

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        ZOOM = 14

        # Hilfsfunktionen
        def latlon_to_tile(lat, lon, zoom):
            n = 2 ** zoom
            x_tile = int((lon + 180.0) / 360.0 * n)
            y_tile = int((1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n)
            return x_tile, y_tile

        def latlon_to_pixel(lat, lon, zoom, tile_size):
            n = 2 ** zoom * tile_size
            x = (lon + 180.0) / 360.0 * n
            y = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
            return int(x), int(y)

        # Schritt 1: alle benötigten Tiles ermitteln
        needed_tiles = set()
        for _, lat, lon in latlon_list:
            xt, yt = latlon_to_tile(lat, lon, ZOOM)
            needed_tiles.add((xt, yt))

        # Schritt 2: Tiles herunterladen
        tile_images = {}
        tile_size = 256  # Standard
        tile_count = 0

        for (xtile, ytile) in needed_tiles:
            url = f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{ZOOM}/{xtile}/{ytile}.pngraw?access_token={token}"
            try:
                with urllib.request.urlopen(url) as response:
                    img_bytes = response.read()
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    tile_images[(xtile, ytile)] = img
                    tile_size = img.size[0]  # z. B. 256
                    tile_count += 1
            except Exception as e:
                QMessageBox.warning(self, "Tile Load Error",
                    f"Could not load tile {xtile},{ytile}:\n{e}")
                return (0, 0)
    
        if tile_count == 0:
            return (0, 0)

        # Schritt 3: Höhenwerte extrahieren
        successful_points = 0
    
        for gpx_i, lat, lon in latlon_list:
            x_pix, y_pix = latlon_to_pixel(lat, lon, ZOOM, tile_size)
            xtile, ytile = x_pix // tile_size, y_pix // tile_size
            x_in_tile, y_in_tile = x_pix % tile_size, y_pix % tile_size

            img = tile_images.get((xtile, ytile))
            if img is None:
                continue

            if 0 <= x_in_tile < img.width and 0 <= y_in_tile < img.height:
                r, g, b = img.getpixel((x_in_tile, y_in_tile))
                elevation = -10000 + ((r * 256 * 256 + g * 256 + b) * 0.1)
                gpx_data[gpx_i]["ele"] = elevation
                successful_points += 1
            else:
                print(f"[WARN] Out-of-bounds pixel: {x_in_tile},{y_in_tile} in tile {xtile},{ytile}")

        return (successful_points, tile_count)

    ###
    def _on_get_ele_mapbox(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        if b_idx is None and e_idx is None:
            QMessageBox.warning(self, "No Selection", "Please mark a GPX range or a single point with markB.")
            return

        if b_idx is not None and e_idx is None:
            # Nur ein Punkt (markB) ausgewählt
            if not (0 <= b_idx < len(gpx_data)):
                QMessageBox.warning(self, "Invalid Point", "Marked point index is invalid.")
                return

            reply = QMessageBox.question(
                self,
                "Get Elevation from Mapbox",
                f"This will fetch elevation data for point {b_idx}.\nDo you want to proceed?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            latlon_list = [(b_idx, gpx_data[b_idx]["lat"], gpx_data[b_idx]["lon"])]

        else:
            # Bereich (B..E) ausgewählt
            if b_idx is None or e_idx is None:
                QMessageBox.warning(self, "Invalid Selection", "Both markB and markE must be set for a range.")
                return

            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx

            if e_idx - b_idx < 1:
                QMessageBox.information(self, "Invalid Range", "At least 2 points needed in B..E range.")
                return

            reply = QMessageBox.question(
                self,
                "Get Elevation from Mapbox",
                f"This will fetch precise elevation data from Mapbox for the selected GPX range {b_idx} to {e_idx}.\nDo you want to proceed?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            latlon_list = [(i, gpx_data[i]["lat"], gpx_data[i]["lon"]) for i in range(b_idx, e_idx + 1)]
    
        # Elevation abrufen
        successful_points, tile_count = self.update_elevation_from_mapbox(latlon_list)

        #if tile_count == 0:
        if tile_count == 0 and successful_points == 0:
            #QMessageBox.warning(self, "Mapbox Error", "No elevation tiles could be loaded.\nCheck your Mapbox API key.")
            print("[INFO] No elevation loaded – possibly due to missing Mapbox key")
            return
        if successful_points == 0:
            QMessageBox.warning(self, "No Elevation Found", "Tiles were loaded, but no elevation values could be decoded.")
            return

        # GPX aktualisieren
        self.register_gpx_undo_snapshot()
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        mw.map_widget.clear_marked_range()
        mw.gpx_widget.gpx_list.clear_marked_range()
    
        QMessageBox.information(
            self, "Done",
            f"Elevation updated for {successful_points} point(s) via Mapbox Terrain-RGB."
        )

    
    
    ###
    #TODO: test this
    def _on_set_gpx2video_triggered(self):
        """
        Zeigt eine MessageBox mit den Zeitbereichen (Video + GPX).
        Fragt den User: "Do you want to sync GPX time to the Video time range?"
        Falls OK => wir skalieren den GPX-Bereich B..E auf dieselbe Länge wie Video-B..E
        und shiften alle nachfolgenden GPX-Punkte.
        """
        mw = self._mainwindow
        if not mw:
            return  # kein MainWindow => abbrechen
    
        #gom PySide6.QtWidgets import QMessageBox
        

        # --------------------------------------------------------------------
        # 1) Hilfsfunktion zur Formatierung in "xh ym zs" (siehe vorher)
        # --------------------------------------------------------------------
        def _format_duration(seconds: float) -> str:
            if seconds < 0:
                return "(not set)"
            total_s = int(round(seconds))
            hh = total_s // 3600
            rest = total_s % 3600
            mm = rest // 60
            ss = rest % 60
            parts = []
            if hh > 0:
                parts.append(f"{hh}h")
            if mm > 0:
                parts.append(f"{mm}min")
            if ss > 0 or (hh == 0 and mm == 0):
                parts.append(f"{ss}s")
            return " ".join(parts)

        # --------------------------------------------------------------------
        # 2) Video-Bereich: markB_time_s, markE_time_s
        # --------------------------------------------------------------------
        vB = mw.cut_manager.markB_time_s or -1
        vE = mw.cut_manager.markE_time_s or -1
        if vB < 0 or vE < 0 or vE <= vB:
            video_len = -1
        else:
            video_len = (vE - vB)

        video_start_str = _format_duration(vB)
        video_end_str   = _format_duration(vE)
        video_len_str   = _format_duration(video_len)

        # --------------------------------------------------------------------
        # 3) GPX-Bereich: b_idx, e_idx + rel_s
        # --------------------------------------------------------------------
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
        gpx_data = mw.gpx_widget.gpx_list._gpx_data

        # Start/End als Sekunden
        if b_idx is not None and 0 <= b_idx < len(gpx_data):
            gpx_b_sec = gpx_data[b_idx].get("time", -1)
        else:
            gpx_b_sec = -1
    
        if e_idx is not None and 0 <= e_idx < len(gpx_data):
            gpx_e_sec = gpx_data[e_idx].get("time", -1)
        else:
            gpx_e_sec = -1

        if gpx_b_sec < 0 or gpx_e_sec < 0 or gpx_e_sec <= gpx_b_sec:
            gpx_len_sec = -1
        else:
            gpx_len_sec = (gpx_e_sec - gpx_b_sec)

        gpx_rel_start = gpx_data[0].get("time",-1) + timedelta(seconds = get_gpx_video_shift())
        gpx_start_str = _format_duration(gpx_b_sec-gpx_rel_start)
        gpx_end_str   = _format_duration(gpx_e_sec-gpx_rel_start)
        gpx_len_str   = _format_duration(gpx_len_sec)
    
        # --------------------------------------------------------------------
        # 4) Info an den User (Anzeigen der Bereiche)
        # --------------------------------------------------------------------
        msg_text = (
            "Video Range:\n"
            f"  Start:  {video_start_str}\n"
            f"  End:    {video_end_str}\n"
            f"  Length: {video_len_str}\n\n"
            "GPX Range:\n"
            f"  Start:  {gpx_start_str}\n"
            f"  End:    {gpx_end_str}\n"
            f"  Length: {gpx_len_str}\n\n"
            "Do you want to synchronize the GPX range to the Video range?"
        )

        reply = QMessageBox.question(
            self,
            "SetGPX2VideoTime",
            msg_text,
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if reply != QMessageBox.Ok:
            # => Abbruch
            return
    
        # --------------------------------------------------------------------
        # 5) Nur wenn BEIDE Bereiche valide sind (>=0) => skalieren wir
        # --------------------------------------------------------------------
        if video_len <= 0 or gpx_len_sec <= 0:
            QMessageBox.information(
                self,
                "SetGPX2VideoTime",
                "Invalid range(s). Unable to synchronize."
            )
            return
    
        # => Undo-Snapshot
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()
    
        # alt = gpx_len_sec, neu = video_len
        old_duration = gpx_len_sec
        new_duration = video_len
        diff_s = new_duration - old_duration
    
        # (A) Skalierung: b_idx..e_idx
        # Wir gehen i von b_idx+1.. e_idx => berechnen fraction:
        # fraction = (time[i] - time[b_idx]) / old_duration
        # new_time[i] = time[b_idx] + fraction*new_duration
        t_b0 = gpx_data[b_idx]["time"]  # datetime
    
        if old_duration < 1e-9:
            # => Abbruch
            QMessageBox.warning(self, "Error", "GPX range is effectively 0s => cannot scale.")
            return

        for i in range(b_idx+1, e_idx+1):
            old_ti = gpx_data[i]["time"]
            # fraction
            fraction = (gpx_data[i]["time"] - gpx_b_sec) / old_duration
            # z. B. 0.0..1.0
            new_rel = fraction * new_duration
            # => new_abstime = t_b0 + new_rel sek
            gpx_data[i]["time"] = t_b0 + timedelta(seconds=new_rel)
    
        # (B) Shift aller Punkte nach e_idx um diff_s
        # => d. h. ab e_idx+1 bis zum Ende => time[j] += diff_s
        if e_idx < len(gpx_data)-1 and abs(diff_s) > 1e-9:
            for j in range(e_idx+1, len(gpx_data)):
                old_tj = gpx_data[j]["time"]
                gpx_data[j]["time"] = old_tj + timedelta(seconds=diff_s)
    
        # (C) recalc + set
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
    
        # => Chart, Map
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
    
        # Finale Info
        QMessageBox.information(
            self,
            "SetGPX2VideoTime",
            f"GPX range has been rescaled from { _format_duration(old_duration) } "
            f"to { _format_duration(new_duration) }.\n"
            "Subsequent points were shifted accordingly."
        )
    

     
     
    
        
    def update_set_gpx2video_state(self, video_edit_on: bool, auto_sync_on: bool):
        """
        Schaltet den Menüpunkt "SetGPX2VideoTime" an/aus.
        - Nur aktiv, wenn video_edit_on == True und auto_sync_on == False
        """
        enable_it = (video_edit_on and (not auto_sync_on))
        self._action_set_gpx2video.setEnabled(enable_it)    
        
    def set_directions_mode(self, enabled: bool):
        if enabled:
            self._action_closegaps.setText("Close Gaps (Directions)")
        else:
            self._action_closegaps.setText("Close Gaps")    
        
    
    def _on_more_button_clicked(self):
        # Menü manuell anzeigen, z.B. leicht unterhalb des Buttons:
        pos = self.more_button.mapToGlobal(QPoint(0, self.more_button.height()))
        self.more_menu.exec_(pos)    
        
    def set_mainwindow(self, mw):
        """
        Mit dieser Methode geben wir dem GPXControlWidget
        einen Zeiger auf das MainWindow, damit wir dort
        auf ._gpx_data, .gpx_widget, .map_widget usw. zugreifen können.
        """
        self._mainwindow = mw   
            


    # ----------------------------------------------------------
    # Methode zum Aktualisieren der Info-Zeile
    # ----------------------------------------------------------
   
    def update_info_line(self,
                     video_time_str: str,
                     length_km: float,
                     duration_str: str,
                     elev_gain: float,
                     slope_max: float = 0.0,
                     slope_min: float = 0.0,
                     zero_speed_count: int = 0,
                     paused_count: int = 0):                         
        """
        Aktualisiert die 4 Labels in der Infozeile:
        - Video
        - Length(GPX)
        - Duration(GPX)
        - Elevation Gain
        """
        self.label_video.setText(f"Video: {video_time_str}")
        self.label_length.setText(f"Length(GPX): {length_km:.2f} km")
        self.label_duration.setText(f"Duration(GPX): {duration_str}")
        self.label_elev.setText(f"Elevation Gain: {int(elev_gain)} m")
        self.label_slope_max.setText(f"Max%: {slope_max:.1f}%")
        self.label_slope_min.setText(f"Min%: {slope_min:.1f}%")
        self.label_zerospeed.setText(f"ZeroSpeed: {zero_speed_count}")
        self.label_paused.setText(f"Paused: {paused_count}")    
        
        
    def set_markE_visibility(self, visible: bool):
        """
        Zeigt oder versteckt den MarkE-Button.
        """
        self.markE_button.setVisible(visible)    
    
    def _process_delete_points(self,shift_next: bool = True):
        
        """
        Wird ausgelöst, wenn der Delete-Button (Mülleimer) 
        im gpx_control_widget geklickt wurde.
        => Leitet an die gpx_list weiter.
        """
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        mw.register_gpx_undo_snapshot()
        
        mw.map_widget.view.page().runJavaScript("showLoading('Deleting GPX-Range...');")
        mw.gpx_widget.gpx_list.delete_selected_range(shift_next)
        mw._update_gpx_overview()
        mw._gpx_data = mw.gpx_widget.gpx_list._gpx_data
        route_geojson = mw._build_route_geojson_from_gpx(mw._gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(mw._gpx_data)
        
        if mw.mini_chart_widget and mw._gpx_data:
            mw.mini_chart_widget.set_gpx_data(mw._gpx_data)
        
        mw.map_widget.view.page().runJavaScript("hideLoading();")

    def on_cut_range_clicked(self):
       self._process_delete_points(True)

    def on_remove_range_clicked(self):
       self._process_delete_points(False)
        
        
    def on_undo_range_clicked(self):
        mw = self._mainwindow
        """
        Wird ausgelöst, wenn der Undo-Button 
        im gpx_control_widget geklickt wurde.
        => Leitet an die gpx_list weiter.
        """
        mw.map_widget.view.page().runJavaScript("showLoading('Undo GPX-Range...');")
        mw.gpx_widget.gpx_list.undo_delete()
        mw._update_gpx_overview()
        mw._gpx_data = mw.gpx_widget.gpx_list._gpx_data
        route_geojson = mw._build_route_geojson_from_gpx(mw._gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(mw._gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(mw._gpx_data)

        mw.map_widget.view.page().runJavaScript("hideLoading();")    
        
        
    def _on_show_max_slope(self):
        mw = self._mainwindow
        # 1) Finde Index    
        #    z. B. idx_max = self._index_of_max_slope
        #    (woher? -> du hast es in _update_gpx_overview() schon)
        #    oder du rechnest hier nochmal:
        data = mw.gpx_widget.gpx_list._gpx_data
        if not data:
            return
        slopes = [pt["gradient"] for pt in data]
        idx_max = slopes.index(max(slopes))  # index des Max-Wertes

        # 2) Markieren in Chart, Map, GpxList, MiniChart
        mw._highlight_index_everywhere(idx_max)    
        
    def _on_show_min_slope(self):
        mw = self._mainwindow
        data = mw.gpx_widget.gpx_list._gpx_data
        if not data:
            return
        slopes = [pt["gradient"] for pt in data]
        idx_min = slopes.index(min(slopes))

        mw._highlight_index_everywhere(idx_min)    
        
    def check_data_for_avg(self) -> bool:
        mw = self._mainwindow 
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return False

        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return False
        
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
    
        if b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range Selected",
                "Please mark a range (markB..markE) first.")
            return False

        if (e_idx - b_idx) < 1:
            QMessageBox.warning(self, "Invalid Range",
                "The selected range must contain at least 2 points.")
            return False
        
        return True
        
    def on_average_speed_clicked(self):
        mw = self._mainwindow 
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        """
        Shows the current average speed for the selected range b_idx.. e_idx
        *without changing total time*.
        If the user accepts, we distribute the times so that
        each subsegment has the same local speed (i.e., flatten spikes),
        but overall time remains the same.
        """
        if not self.check_data_for_avg():
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
    
        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx
    
        # 1) Gesamt-Zeit
        t_start = gpx_data[b_idx]["time"]
        t_end   = gpx_data[e_idx]["time"]
        total_s = (t_end - t_start).total_seconds()
        if total_s <= 0:
            QMessageBox.warning(self, "Invalid Time",
                f"Time in the range {b_idx}..{e_idx} is zero or reversed.")
            return
    
        # 2) Distanz summieren
        total_dist_m = 0.0
        for i in range(b_idx, e_idx):
            lat1, lon1 = gpx_data[i]["lat"],   gpx_data[i]["lon"]
            lat2, lon2 = gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            d2 = self._haversine_m(lat1, lon1, lat2, lon2)
            total_dist_m += d2
        if total_dist_m < 0.001:
            QMessageBox.warning(self, "Zero Distance",
                f"Range {b_idx}..{e_idx} has almost no distance => speed meaningless.")
            return
    
        dist_km = total_dist_m / 1000.0
        time_h = total_s / 3600.0
        old_avg_speed = dist_km / time_h  # km/h
    
        # 3) Frage, ob wir flatten wollen
        msg = (
            f"Range {b_idx}..{e_idx}\n"
            f"Total distance: {dist_km:.3f} km\n"
            f"Total time: {total_s:.1f} s\n\n"
            f"Current average speed in this range: {old_avg_speed:.2f} km/h\n\n"
            "Do you want to flatten spikes so that every subsegment\n"
            "has the same local speed? (Total time remains unchanged!)"
        )
        reply = QMessageBox.question(
            self, "Flatten Speed?",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return  # aborted
    
        # 4) Undo-Snapshot
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()
        
        # 5) partial-dist array
        partial_dist = [0.0]
        cum = 0.0
        for i in range(b_idx, e_idx):
            d2 = self._haversine_m(
                gpx_data[i]["lat"], gpx_data[i]["lon"],
                gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            )
            cum += d2
            partial_dist.append(cum)
    
        # 6) Verteilen => time[i] = t_start + frac*total_s
        for k in range(1, e_idx - b_idx + 1):
            frac = partial_dist[k] / partial_dist[-1]  # last partial_dist is total_dist_m
            offset_s = total_s * frac
            gpx_data[b_idx + k]["time"] = t_start + timedelta(seconds=offset_s)
    
        # => e_idx bleibt t_end => identisch => also total_s bleibt 
        # => wir ändern NICHT time[e_idx], da offset_s=total_s an k = e_idx - b_idx
    
        # 7) recalc
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
    
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
    
        #route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        #mw.map_widget.loadRoute(route_geojson, do_fit=False)

        QMessageBox.information(
            self, "Flatten done",
            "All subsegments in this range now share the same local speed.\n"
            "Total time remained unchanged."
        )
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()

    def on_show_average_speed_info(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        if not gpx_data or b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range", "Please mark a GPX range (B..E) first.")
            return

        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx

        t_start = gpx_data[b_idx]["time"]
        t_end = gpx_data[e_idx]["time"]
        total_s = (t_end - t_start).total_seconds()
        if total_s <= 0:
            QMessageBox.warning(self, "Invalid Time",
                f"Time in the range {b_idx}..{e_idx} is zero or reversed.")
            return

        total_dist_m = 0.0
        for i in range(b_idx, e_idx):
            lat1 = gpx_data[i]["lat"]
            lon1 = gpx_data[i]["lon"]
            lat2 = gpx_data[i+1]["lat"]
            lon2 = gpx_data[i+1]["lon"]
            total_dist_m += self._haversine_m(lat1, lon1, lat2, lon2)

        if total_dist_m < 0.001:
            QMessageBox.information(self, "Zero Distance", "This range has almost no distance.")
            return

        dist_km = total_dist_m / 1000.0
        time_h = total_s / 3600.0
        avg_speed_kmh = dist_km / time_h

        QMessageBox.information(
            self, "Average Speed Info",
            f"Range {b_idx}..{e_idx}\n"
            f"Distance: {dist_km:.3f} km\n"
            f"Time: {total_s:.1f} s\n\n"
            f"Average Speed: {avg_speed_kmh:.2f} km/h"
        )

    
    
    def _haversine_m(self, lat1, lon1, lat2, lon2):
        """
        Evtl. Hilfsfunktion, 
        distance in Meter
        """
        
        R = 6371000
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat/2)**2 
            + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))
            * math.sin(d_lon/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R*c
        
        
    def on_max_speed_clicked(self):
        mw = self._mainwindow
        """
        Called when the user selects 'MaxSpeed' in the More-Menu.
        We find the GPX point with the highest speed_kmh, 
        then highlight and center that point in map, table, and chart.
        """
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return  # or show a warning

        # Liste der Geschwindigkeiten
        speeds = [pt.get("speed_kmh", 0.0) for pt in gpx_data]
        max_val = max(speeds)
        idx_max = speeds.index(max_val)

        # "Springen" => Map, Chart, Table
        mw._go_to_gpx_index(idx_max)    
        
    def on_min_speed_clicked(self):
        mw = self._mainwindow
        """
        Called when the user selects 'MinSpeed' in the More-Menu.
        We find the GPX point (except the very first point index=0)
        with the lowest speed_kmh, then highlight and center that point
        in map, table, and chart.
        """
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return
        if len(gpx_data) < 2:
            # Kein "echter" Punkt außer Index 0
            return

        # Erstelle eine Liste (speed, index), beginnend ab Index 1
        # => so wird der erste Punkt (Index 0) ausgeschlossen.
        spd_idx_pairs = [
            (pt.get("speed_kmh", 0.0), i)
            for i, pt in enumerate(gpx_data)
            if i > 0  # ab Index 1
        ]
        if not spd_idx_pairs:
            return

        # min(...) mit key=lambda x: x[0] => vergleicht speed
        min_speed, idx_min = min(spd_idx_pairs, key=lambda x: x[0])

        mw._go_to_gpx_index(idx_min)




    def on_smooth_clicked(self):
        mw = self._mainwindow
        """
        Wird aufgerufen, wenn im GPXControlWidget der 'Smooth' Button gedrückt wird.
        - Öffnet einen Dialog mit 2 Parametern: Box_Smoothing (default=10), Flatten_Value (default=2)
        - Bei OK => ruft _apply_smoothing(...) auf, das die komplette GPX glättet
        - Schreibt Undo-History, damit man zurück kann
        """
        
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX", "Keine GPX-Daten vorhanden zum Smoothen!")
            return

        # 1) Dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("GPX Smoothing Parameters")
        vbox = QVBoxLayout(dlg)

        lbl_info = QLabel(
            "Apply Slope Box Smoothing + Flatten Value\n\n"
            "Box_Smoothing: Average slope over +/- N points\n"
            "Flatten_Value: Max slope change between adjacent points\n"
            "Default: Box_Smoothing=10, Flatten_Value=2"
        )
        vbox.addWidget(lbl_info)

        # Box Smoothing
        row_box = QHBoxLayout()
        lbl_box = QLabel("Box_Smoothing:")
        spin_box = QDoubleSpinBox()
        spin_box.setRange(1.0, 9999.0)  # z. B. 1..9999
        spin_box.setDecimals(0)        # als ganze Zahl?
        spin_box.setValue(10.0)        # Standard=10
        row_box.addWidget(lbl_box)
        row_box.addWidget(spin_box)
        vbox.addLayout(row_box)
    
        # Flatten Value
        row_flat = QHBoxLayout()
        lbl_flat = QLabel("Flatten_Value:")
        spin_flat = QDoubleSpinBox()
        spin_flat.setRange(0.0, 50.0)
        spin_flat.setDecimals(2)
        spin_flat.setValue(2.0)  # Default=2
        row_flat.addWidget(lbl_flat)
        row_flat.addWidget(spin_flat)
        vbox.addLayout(row_flat)
    
        # Buttons OK/Cancel
        h_btns = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        vbox.addLayout(h_btns)
    
        def on_ok():
            dlg.accept()
        def on_cancel():
            dlg.reject()
        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(on_cancel)
    
        if not dlg.exec():
            return  # abgebrochen
    
        # Gelesene Werte
        box_smoothing = int(spin_box.value())      # ggf. Ganzzahl
        flatten_val   = spin_flat.value()
    
        # 2) Undo => Kopie
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()
        
        # 3) => smoothing
        self._apply_smoothing(gpx_data, box_smoothing, flatten_val)
    
        # 4) => Neu set + recalc
        from core.gpx_parser import recalc_gpx_data
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
    
        # => evtl. Map + Chart
        #route_geojson = self._build_route_geojson_from_gpx(gpx_data)
        #self.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
            
        QMessageBox.information(
            self, "Smooth done",
            f"Smoothing applied with Box={box_smoothing}, Flatten={flatten_val:.2f}"
        )    
        
    def _apply_smoothing(self, gpx_data, box_size=10, flatten_val=2.0):
        """
        wendet 2-stufiges Smoothing an:
        1) Box slope smoothing
        2) Flatten Value => wenn slope-Änderung > flatten_val => clamp
        => hinterher reconstruct elevation
        """
        import math
    
        n = len(gpx_data)
        if n < 2:
            return

        # 1) Dist2D:
        dist2d = [0.0]*n
        for i in range(1, n):
            lat1, lon1 = gpx_data[i-1]["lat"], gpx_data[i-1]["lon"]
            lat2, lon2 = gpx_data[i]["lat"],  gpx_data[i]["lon"]
            dist2d[i] = self._haversine_m(lat1, lon1, lat2, lon2)

        # 2) slope[i] = (ele[i]-ele[i-1]) / dist2d[i] * 100
        slope = [0.0]*n
        for i in range(1, n):
            d2 = dist2d[i]
            if d2 > 0.01:
                slope[i] = ((gpx_data[i]["ele"] - gpx_data[i-1]["ele"]) / d2)*100
            else:
                slope[i] = 0.0

        # 3) Box smoothing => slope_smooth[i] = average of slope[i-box..i+box], clamp 0..n-1
        slope_smooth = slope[:]  # copy
        for i in range(n):
            start_i = max(0, i-box_size)
            end_i   = min(n-1, i+box_size)
            count   = (end_i - start_i + 1)
            if count < 1:
                continue
            ssum = 0.0
            for j in range(start_i, end_i+1):
                ssum += slope[j]
            slope_smooth[i] = ssum / count

        # 4) Flatten => wir gehen i=1..n-1, check delta to slope_smooth[i-1]
        for i in range(1, n):
            delta_slope = slope_smooth[i] - slope_smooth[i-1]
            if abs(delta_slope) > flatten_val:
                # clamp => slope_smooth[i] = slope_smooth[i-1] + sign(delta)*flatten_val
                sign_ = 1.0 if delta_slope>0 else -1.0
                slope_smooth[i] = slope_smooth[i-1] + sign_*flatten_val
    
        # 5) Nun reconstruct elevation => 
        #    ele[0] bleibt wie es war
        #    ele[i] = ele[i-1] + dist2d[i] * (slope_smooth[i]/100)
        new_ele = gpx_data[0]["ele"]
        for i in range(1, n):
            old_ele = gpx_data[i]["ele"]  # nur debug
            new_ele = gpx_data[i-1]["ele"] + (dist2d[i]*(slope_smooth[i]/100))
            gpx_data[i]["ele"] = new_ele
        
    # ===========  NEU am Ende von mainwindow.py ============    
    
    
    
    def on_chEle_clicked(self):
        mw = self._mainwindow
        """
        Wird aufgerufen, wenn der Button 'chEle' im GPXControlWidget gedrückt wird.
        Erweiterung:
        - Falls (markB..markE) existieren und mehr als 1 Punkt umfasst sind,
            öffnet einen Dialog für einen Elevation-Offset (z.B. +1.25m => +1.25).
        - Sonst (kein B..E oder nur 1 Zeile) => alter Single-Point-Dialog.
        """
       
        

        # Referenz auf die GPX-Daten
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX", "No GPX data available.")
            return

        # (A) Prüfe, ob ein Bereich (B..E) vorliegt und mehr als 1 Punkt abdeckt
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        valid_range = False
        if b_idx is not None and e_idx is not None:
            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx  # tauschen
            if 0 <= b_idx < len(gpx_data) and 0 <= e_idx < len(gpx_data) and (e_idx - b_idx) >= 1:
                valid_range = True
    
        if valid_range:
            # -----------------------------------------------
            # (1) Dialog -> "Offset für B..E"
            # -----------------------------------------------
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Offset Elevation for Area {b_idx}..{e_idx}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                "Increase/decrease the elevation of all marked points.\n"
                "For example: +1.25 => +1.25 Meter\n"
                "          -2.00 => -2.00 Meter\n"
            )
            vbox.addWidget(lbl_info)
    
            # SpinBox für Offset
            spin_offset = QDoubleSpinBox()
            spin_offset.setRange(-9999.0, 9999.0)
            spin_offset.setDecimals(2)      # cm-Schritte
            spin_offset.setSingleStep(0.01) # 1 cm
            spin_offset.setValue(0.0)
            vbox.addWidget(spin_offset)
    
            # OK/Cancel
            h_btns = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            h_btns.addWidget(btn_ok)
            h_btns.addWidget(btn_cancel)
            vbox.addLayout(h_btns)
    
            def on_ok():
                dlg.accept()
    
            def on_cancel():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok)
            btn_cancel.clicked.connect(on_cancel)
    
            if not dlg.exec():
                return  # abgebrochen
    
            offset_val = spin_offset.value()
            if abs(offset_val) < 1e-9:
                QMessageBox.information(self, "No change", "Offset=0 => no change.")
                return
    
            # => Undo-Snapshot
            #old_data = copy.deepcopy(gpx_data)
            #mw.gpx_widget.gpx_list._history_stack.append(old_data)
            self.register_gpx_undo_snapshot()
            
            # => wende offset an: gpx_data[b_idx..e_idx]
            for i in range(b_idx, e_idx + 1):
                old_ele = gpx_data[i].get("ele", 0.0)
                gpx_data[i]["ele"] = old_ele + offset_val
    
            # => recalc
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            
            mw._update_gpx_overview()
    
            # => Chart, Map, MiniChart
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
            route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)
    
            QMessageBox.information(
                self, "Done",
                f"Elevation of all Points in {b_idx}..{e_idx} chamged by {offset_val:+.2f} m."
            )
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
    
        else:
            # -----------------------------------------------
            # (2) Einzel-Punkt-Dialog (alte Logik)
            # -----------------------------------------------
            row = mw.gpx_widget.gpx_list.table.currentRow()
            if row < 0:
                QMessageBox.warning(self, "No selection", "Please select a GPX point.")
                return
    
            if row >= len(gpx_data):
                return
    
            old_ele = gpx_data[row].get("ele", 0.0)
    
            # Undo
            
            #old_data = copy.deepcopy(gpx_data)
            #mw.gpx_widget.gpx_list._history_stack.append(old_data)
            self.register_gpx_undo_snapshot()
    
            # Dialog => neue absolute Höhe
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Elevation – Point {row}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                f"Current elevation: {old_ele:.2f} m\n"
                f"Please enter new absolute value:"
            )
            vbox.addWidget(lbl_info)
    
            spin_ele = QDoubleSpinBox()
            spin_ele.setRange(-500.0, 9000.0)  # z. B. +9k m, -500 m
            spin_ele.setDecimals(2)
            spin_ele.setSingleStep(0.01)
            spin_ele.setValue(old_ele)
            vbox.addWidget(spin_ele)
    
            hbox_btn = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            hbox_btn.addWidget(btn_ok)
            hbox_btn.addWidget(btn_cancel)
            vbox.addLayout(hbox_btn)
    
            def on_ok_single():
                dlg.accept()
    
            def on_cancel_single():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok_single)
            btn_cancel.clicked.connect(on_cancel_single)
    
            if not dlg.exec():
                return  # abgebrochen
    
            new_ele = spin_ele.value()
            if abs(new_ele - old_ele) < 1e-9:
                QMessageBox.information(self, "No change", "Elevation unchanged.")
                return
    
            # -> setze
            gpx_data[row]["ele"] = new_ele
    
            # -> partial recalc (oder full recalc)
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            
            mw._update_gpx_overview()
            
            
            # -> Chart, Map
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
            route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)
    
            QMessageBox.information(
                self, "OK",
                f"Elevation of Point {row} changed to {new_ele:.2f} m."
            )
            
    #################################################################    
    
    def on_chTime_clicked_gpx(self):
        mw = self._mainwindow

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        valid_range = False
        if b_idx is not None and e_idx is not None:
            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx
            if 0 <= b_idx < n and 0 <= e_idx < n and (e_idx - b_idx) >= 1:
                valid_range = True

        # --- CASE A: Einzelpunkt ---
        if not valid_range:
            row = mw.gpx_widget.gpx_list.table.currentRow()
    
            if row < 0 or row >= n:
                QMessageBox.warning(self, "Invalid Selection", "Please select a valid GPX point.")
                return
            ######
            if row == 0:
                # --- Neuer Sonderfall: GPX[0] erlaubt negativen Delta ---
                self.register_gpx_undo_snapshot()

                t0 = gpx_data[0].get("time", None)
                t1 = gpx_data[1].get("time", None)
                if not t0 or not t1:
                    QMessageBox.warning(self, "Missing Time", "First or second point has no time.")
                    return

                old_diff = (t1 - t0).total_seconds()
                dlg = QDialog(self)
                dlg.setWindowTitle("Shift Time: GPX[0]")
                vbox = QVBoxLayout(dlg)

                lbl = QLabel(
                    f"You are changing the time distance between GPX[0] and GPX[1].\n"
                    f"Current difference: {old_diff:.3f} s\n\n"
                    "Enter a **negative** shift (e.g. -10.0) to delay all points after GPX[0]:"
                )
                vbox.addWidget(lbl)
    
                spin = QDoubleSpinBox()
                spin.setRange(-99999.0, -0.001)
                spin.setDecimals(3)
                spin.setSingleStep(0.001)
                spin.setValue(-1.0)
                vbox.addWidget(spin)

                btns = QHBoxLayout()
                ok = QPushButton("OK")
                cancel = QPushButton("Cancel")
                btns.addWidget(ok)
                btns.addWidget(cancel)
                vbox.addLayout(btns)

                ok.clicked.connect(dlg.accept)
                cancel.clicked.connect(dlg.reject)

                if not dlg.exec():
                    return

                shift_val = spin.value()  # z. B. -10.0

                # Alle Punkte ab Index 1 verschieben um +abs(shift_val)
                for j in range(1, n):
                    gpx_data[j]["time"] += timedelta(seconds=abs(shift_val))

                recalc_gpx_data(gpx_data)
                mw.gpx_widget.set_gpx_data(gpx_data)
                mw._gpx_data = gpx_data
                mw._update_gpx_overview()
                mw.chart.set_gpx_data(gpx_data)
                if mw.mini_chart_widget:
                    mw.mini_chart_widget.set_gpx_data(gpx_data)
    
                QMessageBox.information(
                    self, "Done",
                    f"All GPX points after index 0 have been shifted by {abs(shift_val):.3f} seconds."
                )   
                return

            ###
            
            # --- Normalfall (row >= 1) ---
            if row < 1:
                QMessageBox.warning(self, "Invalid Selection",
                    "Please select a GPX point (row >= 1). The first point (row=0) has no predecessor.")
                return

            self.register_gpx_undo_snapshot()
    
            t_prev = gpx_data[row - 1].get("time", None)
            t_curr = gpx_data[row].get("time", None)
            if not t_prev or not t_curr:
                QMessageBox.warning(self, "Missing Time",
                    f"Point {row-1} or {row} has no 'time' set.")
                return
    
            old_diff_s = (t_curr - t_prev).total_seconds()
            if old_diff_s < 0:
                QMessageBox.warning(self, "Unsorted Track", "time[row] < time[row-1]? The track seems unsorted.")
                return
    
            dlg = QDialog(self)
            dlg.setWindowTitle("Change Step - Single Point")
            vbox = QVBoxLayout(dlg)
    
            info_lbl = QLabel(
                f"Current step = {old_diff_s:.3f} seconds.\n"
                "Please enter a new step (>= 0.001)."
            )
            vbox.addWidget(info_lbl)
    
            spin_new_step = QDoubleSpinBox()
            spin_new_step.setRange(0.001, 999999.0)
            spin_new_step.setValue(old_diff_s)
            spin_new_step.setDecimals(3)
            spin_new_step.setSingleStep(0.001)
            vbox.addWidget(spin_new_step)
    
            btn_box = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            btn_box.addWidget(btn_ok)
            btn_box.addWidget(btn_cancel)
            vbox.addLayout(btn_box)
    
            def on_ok():
                new_val = spin_new_step.value()
                if new_val < 0.001:
                    QMessageBox.warning(dlg, "Invalid Value", "New step cannot be < 0.001!")
                    return
                dlg.accept()
    
            def on_cancel():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok)
            btn_cancel.clicked.connect(on_cancel)
    
            if not dlg.exec():
                return
    
            new_step_s = spin_new_step.value()
            delta_s = new_step_s - old_diff_s
    
            for j in range(row, n):
                t_old = gpx_data[j]["time"]
                gpx_data[j]["time"] = t_old + timedelta(seconds=delta_s)
    
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
    
            QMessageBox.information(
                self, "Done",
                f"Row {row} step changed by {delta_s:+.3f} s.\n"
                "All subsequent points shifted accordingly."
            )
            return
    
        # --- CASE B: Range B..E ---
        else:
            self.register_gpx_undo_snapshot()
    
            t_start = gpx_data[b_idx]["time"]
            t_end   = gpx_data[e_idx]["time"]
            old_total_s = (t_end - t_start).total_seconds()
            if old_total_s < 0:
                QMessageBox.warning(self, "Unsorted Track", "Time in the selected range is reversed? (unsorted data)")
                return
    
            seg_count = e_idx - b_idx
    
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Step - Range {b_idx}..{e_idx}")
            vbox = QVBoxLayout(dlg)
    
            info_text = (
                f"You have selected a range from index {b_idx} to {e_idx}.\n"
                f"This corresponds to {seg_count} segments.\n\n"
                f"Current total duration in this range: {old_total_s:.3f} s\n"
                "Please enter a new step (in seconds) for each segment."
            )
            lbl_info = QLabel(info_text)
            vbox.addWidget(lbl_info)
    
            spin_range_step = QDoubleSpinBox()
            spin_range_step.setRange(0.001, 999999.0)
            if seg_count > 0:
                spin_range_step.setValue(old_total_s / seg_count)
            else:
                spin_range_step.setValue(1.0)
            spin_range_step.setDecimals(3)
            spin_range_step.setSingleStep(0.001)
            vbox.addWidget(spin_range_step)
    
            btn_box = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            btn_box.addWidget(btn_ok)
            btn_box.addWidget(btn_cancel)
            vbox.addLayout(btn_box)
    
            def on_ok_range():
                new_val = spin_range_step.value()
                if new_val < 0.001:
                    QMessageBox.warning(dlg, "Invalid Value", "New step cannot be < 0.001!")
                    return
                dlg.accept()
    
            def on_cancel_range():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok_range)
            btn_cancel.clicked.connect(on_cancel_range)
    
            if not dlg.exec():
                return
    
            new_step_s = spin_range_step.value()
            new_total_s = seg_count * new_step_s
            diff_s = new_total_s - old_total_s
    
            for i in range(b_idx + 1, e_idx + 1):
                offset_s = (i - b_idx) * new_step_s
                gpx_data[i]["time"] = t_start + timedelta(seconds=offset_s)
    
            if e_idx < n - 1 and abs(diff_s) > 1e-9:
                for j in range(e_idx + 1, n):
                    gpx_data[j]["time"] += timedelta(seconds=diff_s)
    
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
    
            QMessageBox.information(
                self, "Done",
                f"All segments in the range {b_idx}..{e_idx} have been set to {new_step_s:.3f} s.\n"
                f"Old duration was {old_total_s:.3f} s, new duration is {new_total_s:.3f} s.\n"
                f"Subsequent points have been shifted by {diff_s:+.3f} s."
            )
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
    
        
        
    
    
    #################################################################
    def on_chPercent_clicked(self):
        
        mw = self._mainwindow
        """
        Called when the user clicks the 'ch%' button.
        - If no valid range is selected (or only 1 point in that range),
        it changes the slope for a single point (row) relative to row-1.
        - If a valid range [markB..markE] with >=2 points is selected,
        it applies one consistent slope across that entire range,
        and shifts subsequent points accordingly.
        All user-facing texts are in English.
        """
        #from PySide6.QtWidgets import (
        #    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
        #    QDoubleSpinBox, QPushButton, QMessageBox
        #)
        
    
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return
    
        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return

        # --- Check if we have a valid markB..markE range ---
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
    
        valid_range = False
        if b_idx is not None and e_idx is not None:
            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx
            if 0 <= b_idx < n and 0 <= e_idx < n and (e_idx - b_idx) >= 1:
                valid_range = True

        # ------------------------------------------------------------------
        # CASE A) No valid range => single-point slope change
        # ------------------------------------------------------------------
        if not valid_range:
            row = mw.gpx_widget.gpx_list.table.currentRow()
            if row < 1:
                QMessageBox.warning(self, "Invalid Selection",
                    "Please select a point with row >= 1.\n"
                    "Cannot compute slope for the very first point (row=0).")
                return
            if row >= n:
                return
    
            # => Undo
            #old_data = copy.deepcopy(gpx_data)
            #mw.gpx_widget.gpx_list._history_stack.append(old_data)
            self.register_gpx_undo_snapshot()
    
            # lat/lon/ele for row-1 and row
            lat1, lon1, ele1 = (
                gpx_data[row-1].get("lat", 0.0),
                gpx_data[row-1].get("lon", 0.0),
                gpx_data[row-1].get("ele", 0.0)
            )
            lat2, lon2, ele2 = (
                gpx_data[row].get("lat", 0.0),
                gpx_data[row].get("lon", 0.0),
                gpx_data[row].get("ele", 0.0)
            )
    
            # Dist2D => we can reuse a small helper or do a direct haversine:
            dist_2d = self._haversine_m(lat1, lon1, lat2, lon2)
            if dist_2d < 0.01:
                QMessageBox.warning(self, "Zero Distance",
                    f"Points {row-1} and {row} have nearly no distance => slope undefined.")
                return
    
            old_slope = 100.0 * ((ele2 - ele1) / dist_2d)
    
            # Dialog => new slope
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Slope (Single Point) - Row {row}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                f"Current slope between row {row-1} and row {row}: {old_slope:.2f}%\n"
                "Please enter the new slope (in %)."
            )
            vbox.addWidget(lbl_info)
    
            spin_slope = QDoubleSpinBox()
            spin_slope.setRange(-200.0, 200.0)  # e.g. -200%.. 200%
            spin_slope.setDecimals(2)
            spin_slope.setSingleStep(0.01)
            spin_slope.setValue(old_slope)
            vbox.addWidget(spin_slope)
    
            h_btn = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            h_btn.addWidget(btn_ok)
            h_btn.addWidget(btn_cancel)
            vbox.addLayout(h_btn)
    
            def on_ok():
                dlg.accept()
    
            def on_cancel():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok)
            btn_cancel.clicked.connect(on_cancel)
    
            if not dlg.exec():
                return
    
            new_slope = spin_slope.value()
            if abs(new_slope - old_slope) < 1e-9:
                QMessageBox.information(self, "No change", "Slope unchanged.")
                return
    
            # => new ele2 = ele1 + dist_2d*(new_slope/100)
            new_ele2 = ele1 + dist_2d * (new_slope / 100.0)
            gpx_data[row]["ele"] = new_ele2
    
            # recalc
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
    
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
    
            # Map
            #route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            #mw.map_widget.loadRoute(route_geojson, do_fit=False)

            diff_val = new_slope - old_slope
            QMessageBox.information(
                self, "Done",
                f"Slope changed from {old_slope:.2f}% to {new_slope:.2f}%.\n"
                f"Elevation of row {row} updated accordingly."
            )
            return

        # ------------------------------------------------------------------
        # CASE B) Valid range => single linear slope for [b_idx..e_idx]
        # ------------------------------------------------------------------
        else:
            # => Undo
            #old_data = copy.deepcopy(gpx_data)
            #mw.gpx_widget.gpx_list._history_stack.append(old_data)
            self.register_gpx_undo_snapshot()
    
            lat_b, lon_b, ele_b = (
                gpx_data[b_idx].get("lat", 0.0),
                gpx_data[b_idx].get("lon", 0.0),
                gpx_data[b_idx].get("ele", 0.0)
            )
            lat_e, lon_e, ele_e = (
                gpx_data[e_idx].get("lat", 0.0),
                gpx_data[e_idx].get("lon", 0.0),
                gpx_data[e_idx].get("ele", 0.0)
            )
    
            # (1) Compute the total 2D distance from b_idx.. e_idx
            #     Summation of each segment's distance in [b_idx.. e_idx-1].
            total_2d = 0.0
            for i in range(b_idx, e_idx):
                la1, lo1 = gpx_data[i]["lat"], gpx_data[i]["lon"]
                la2, lo2 = gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
                dist_2d = self._haversine_m(la1, lo1, la2, lo2)
                total_2d += dist_2d
    
            if total_2d < 0.01:
                QMessageBox.warning(self, "Zero Distance",
                    f"The range {b_idx}..{e_idx} has almost no distance => slope undefined.")
                return
    
            # (2) old average slope
            old_dz = ele_e - ele_b
            old_slope = 100.0 * (old_dz / total_2d)
    
            # (3) Dialog => new slope
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Average Slope - Range {b_idx}..{e_idx}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                f"You have selected a range from {b_idx} to {e_idx}.\n"
                f"Current average slope in this range: {old_slope:.2f}%\n\n"
                "Please enter the new slope in % (e.g., 5.0 means 5%)."
            )
            vbox.addWidget(lbl_info)
    
            spin_slope = QDoubleSpinBox()
            spin_slope.setRange(-200.0, 200.0)  # e.g. -200..+200%
            spin_slope.setDecimals(2)
            spin_slope.setSingleStep(0.01)
            spin_slope.setValue(old_slope)
            vbox.addWidget(spin_slope)
    
            h_btn = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            h_btn.addWidget(btn_ok)
            h_btn.addWidget(btn_cancel)
            vbox.addLayout(h_btn)
    
            def on_ok_range():
                dlg.accept()
    
            def on_cancel_range():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok_range)
            btn_cancel.clicked.connect(on_cancel_range)
    
            if not dlg.exec():
                return
    
            new_slope = spin_slope.value()
            if abs(new_slope - old_slope) < 1e-9:
                QMessageBox.information(self, "No change", "Slope unchanged.")
                return
    
            # (4) new total height difference => new_dz
            new_dz = total_2d * (new_slope / 100.0)
            shift_dz = new_dz - old_dz   # how much we add from e_idx onward
    
            # (5) Recompute elevations linearly from b_idx.. e_idx
            #     Keep ele[b_idx] as it is, 
            #     then for each i in [b_idx+1.. e_idx], 
            #     compute the cumulative distance from b_idx to i.
            def cumulative_distance(b_i, i_i):
                dist_sum = 0.0
                for x in range(b_i, i_i):
                    la1, lo1 = gpx_data[x]["lat"], gpx_data[x]["lon"]
                    la2, lo2 = gpx_data[x+1]["lat"], gpx_data[x+1]["lon"]
                    dist_sum += self._haversine_m(la1, lo1, la2, lo2)
                return dist_sum
    
            for i in range(b_idx+1, e_idx+1):
                dist_i = cumulative_distance(b_idx, i)
                # slope-based new altitude
                new_ele_i = ele_b + (new_slope / 100.0) * dist_i
                gpx_data[i]["ele"] = new_ele_i
    
            # (6) Shift all points after e_idx by shift_dz
            if e_idx < n-1 and abs(shift_dz) > 1e-9:
                for j in range(e_idx+1, n):
                    gpx_data[j]["ele"] = gpx_data[j]["ele"] + shift_dz
    
            # (7) recalc + update
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
    
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
    
            #route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            #mw.map_widget.loadRoute(route_geojson, do_fit=False)

            QMessageBox.information(
                self, "Done",
                f"Average slope in {b_idx}..{e_idx} changed from {old_slope:.2f}% to {new_slope:.2f}%.\n"
                f"Subsequent points have been shifted by {shift_dz:+.2f} m in elevation."
            )
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
    
    def on_close_gaps_clicked(self):
        mw = self._mainwindow
        if not mw:
            return

        # 1) GPX-Daten + markB..markE prüfen
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
        if b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range Selected",
                "Please mark two consecutive points (markB..markE).")
            return

        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx

        # Prüfen, ob wirklich b_idx+1 == e_idx
        if e_idx != b_idx + 1:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Gap",
                "Close Gaps only works if exactly two consecutive points are selected.")
            return

        t1 = gpx_data[b_idx]["time"]
        t2 = gpx_data[e_idx]["time"]
        dt = (t2 - t1).total_seconds()
        if dt < 1.0:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Gap to Close",
                f"Time difference is only {dt:.2f}s (<1s). Nothing to insert.")
            return

        # 2) Check Directions-Flag
        if not mw._directions_enabled:
            # => Altes Verhalten
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
        else:
            # => Directions=True => zeige Profil-Auswahl (QDialog)
            #    Dann rufe _close_gaps_mapbox(..., profile)
            #    Du kannst standard=cycling, optional=driving/walking
            prof = self._ask_profile_mode()
            if not prof:
                # Abbruch
                return
        
            # Rufe neue Methode
            self._close_gaps_mapbox(b_idx, e_idx, dt, prof)

    def _ask_profile_mode(self) -> str:
        """
        Zeigt einen kleinen Dialog mit RadioButtons:
        Bike (cycling), Car (driving), Foot (walking).
        Gibt den Profil‐String zurück oder None bei Cancel.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Select Transport Mode")
        vbox = QVBoxLayout(dlg)

        lbl = QLabel("Directions: Please select a mode:")
        vbox.addWidget(lbl)
    
        group = QButtonGroup(dlg)
        rb_bike = QRadioButton("Bike (Default)")
        rb_car  = QRadioButton("Car")
        rb_walk = QRadioButton("Foot")
        rb_bike.setChecked(True)
        group.addButton(rb_bike)
        group.addButton(rb_car)
        group.addButton(rb_walk)

        vbox.addWidget(rb_bike)
        vbox.addWidget(rb_car)
        vbox.addWidget(rb_walk)

        hbtn = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        hbtn.addWidget(btn_ok)
        hbtn.addWidget(btn_cancel)
        vbox.addLayout(hbtn)

        def on_ok():
            dlg.accept()
        def on_cancel():
            dlg.reject()

        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(on_cancel)

        if not dlg.exec():
            return None  # abbruch

        if rb_car.isChecked():
            return "driving"
        elif rb_walk.isChecked():
            return "walking"
        else:
            return "cycling"
        
            
    
    def on_delete_way_errors_clicked(self):
        mw = self._mainwindow
        """
        Sucht alle aufeinanderfolgenden Duplikate in lat/lon,
        entfernt den zweiten Punkt und setzt einen neuen Interpolationspunkt
        zwischen 'ersten' und 'übernächsten' Punkt, um die Zeit
        wieder in zwei (annähernd) gleiche Schritte zu teilen.
        """
        #from PySide6.QtWidgets import QMessageBox
       

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 3:
            QMessageBox.information(self, "Not enough points",
                "At least 3 points are needed to fix Way Errors.")
            return

        # ---------------------------------------------
        # 1) Finde alle Paare (i, i+1) mit identischem lat/lon
        # ---------------------------------------------
        way_errors = []
        for i in range(len(gpx_data)-1):
            lat1, lon1 = gpx_data[i]["lat"], gpx_data[i]["lon"]
            lat2, lon2 = gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            # Wir prüfen "fast" identisch, z.B. |lat1-lat2|<1e-12
            if abs(lat1 - lat2) < 1e-12 and abs(lon1 - lon2) < 1e-12:
                way_errors.append(i)

        count_err = len(way_errors)
        if count_err == 0:
            QMessageBox.information(self, "No Way Errors",
                "No duplicate coordinates found.")
            return

        # ---------------------------------------------
        # 2) Nachfrage => "We found X errors. Fix them all?"
        # ---------------------------------------------
        answer = QMessageBox.question(
            self,
            "Delete Way Errors?",
            f"We found {count_err} Way Errors (duplicate lat/lon).\n"
            f"Should we fix them all?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        # ---------------------------------------------
        # 3) Undo-Snapshot
        # ---------------------------------------------
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()

        # ---------------------------------------------
        # 4) Fixen der Fehler - am besten in absteigender Index-Reihenfolge
        #
        #    Grund: Wenn wir i+1 entfernen, rückt i+2 -> i+1 usw.
        #           In absteigender Reihenfolge stören wir die
        #           kleineren Indizes nicht.
        # ---------------------------------------------
        way_errors.sort(reverse=True)

        for i in way_errors:
            if i >= len(gpx_data)-1:
                # Schon rausgeflogen oder am Ende -> skip
                continue

            # => i, i+1 haben identische lat/lon
            # => wir wollen i+1 löschen
            # => Dann haben wir Lücke => i.. i+2 (nach dem Löschen),
            #    wir teilen die Zeit. 
            # => ABER wir brauchen i+2 => check, ob i+2 existiert:
            if i+2 >= len(gpx_data):
                # wir können nicht vermitteln, da kein i+2
                # z.B. am Ende der Liste
                continue

            # (A) Hole Zeiten
            t_i   = gpx_data[i]["time"]
            t_ip2 = gpx_data[i+2]["time"]
            dt_total = (t_ip2 - t_i).total_seconds()
            if dt_total <= 0:
                # unsortiert => skip
                continue

            # (B) Hole Koordinaten i, i+2
            lat_i, lon_i, ele_i = (
                gpx_data[i]["lat"], gpx_data[i]["lon"], gpx_data[i]["ele"]
            )
            lat_ip2, lon_ip2, ele_ip2 = (
                gpx_data[i+2]["lat"], gpx_data[i+2]["lon"], gpx_data[i+2]["ele"]
            )

            # => Den zu entfernenden Punkt i+1
            # => wir schmeißen ihn raus
            gpx_data.pop(i+1)

            # => nun i+2 ist zum "i+1" geworden
            # => wir legen in der Mitte einen neuen Punkt an
            t_mid = t_i + timedelta(seconds=dt_total/2)
            lat_mid = lat_i + 0.5*(lat_ip2 - lat_i)
            lon_mid = lon_i + 0.5*(lon_ip2 - lon_i)
            ele_mid = ele_i + 0.5*(ele_ip2 - ele_i)

            new_pt = {
                "lat": lat_mid,
                "lon": lon_mid,
                "ele": ele_mid,
                "time": t_mid,
                "delta_m": 0.0,
                "speed_kmh": 0.0,
                "gradient": 0.0
            }
            # => Insert an i+1
            gpx_data.insert(i+1, new_pt)

            # => i+2 existiert weiterhin, plus wir haben i+1 als middle
            # => Zeit: i..(i+1) ~ dt_total/2, (i+1)..(i+2) ~ dt_total/2
            # => lat/lon linear

        # ---------------------------------------------
        # 5) Recalc + Updates
        # ---------------------------------------------
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()

        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)

        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)

        QMessageBox.information(
            self,
            "Delete Way Errors",
            f"{count_err} Way Errors fixed (where possible)."
        )
    
        
    def on_delete_time_errors_clicked(self):
        mw = self._mainwindow
        """
        Called when the user selects 'Delete Time Errors' in the More-menu.
        We look for all GPX points i where time[i] == time[i-1] => step=0.
        Then we ask the user if we should remove them all.
        After confirmation, we remove them from gpx_data, recalc, and update.
        """
        #from PySide6.QtWidgets import QMessageBox
      

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 2:
            QMessageBox.information(self, "Not enough points", 
                "There are not enough points to check for time errors.")
            return

        # 1) Alle Indizes i (1..n-1) suchen, bei denen time[i] == time[i-1]
        zero_step_indices = []
        for i in range(1, n):
            t_cur = gpx_data[i]["time"]
            t_prev = gpx_data[i-1]["time"]
            if t_cur == t_prev:
                zero_step_indices.append(i)

        count_err = len(zero_step_indices)
        if count_err == 0:
            QMessageBox.information(self, "No Time Errors",
                "No points with 0s step found.")
            return

        # 2) Nachfrage => "We found X time errors. Do you want to remove them?"
        answer = QMessageBox.question(
            self,
            "Delete Time Errors?",
            f"We found {count_err} time errors (0s step). Do you want to remove them all?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        # 3) Undo-Snapshot
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()

        # 4) Entfernen der betroffenen Indizes (in absteigender Reihenfolge!)
        zero_step_indices.sort(reverse=True)
        for i in zero_step_indices:
            # i < len(gpx_data) ?
            if i < len(gpx_data):
                gpx_data.pop(i)

        # 5) recalc + updates
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()

        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)

        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)

        QMessageBox.information(
            self, "Done",
            f"{count_err} Time Errors removed."
        )    
        
    def on_cut_before_b_clicked(self):
        """
        Deletes all GPX points from index 0 up to and including MarkB
        and then shifts the time so that the new first time = 0.
        Then update chart/map/minichart/table etc.
        """
        mw = self._mainwindow
        if mw is None:
            return  # kein MainWindow-Objekt gesetzt
    
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        if b_idx is None:
            # Falls gar kein MarkB existiert => Abbruch
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cut <B", "No MarkB set.")
            return
    
        # Schneller Zugriff
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return
        
        if b_idx < 0 or b_idx >= len(gpx_data):
            # Sicherheitscheck
            return
    
        # 1) Undo-Snapshot
        
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()
    
        # 2) Löschen der Daten von 0..b_idx (inkl. b_idx)
        del gpx_data[0 : b_idx+1]

        if not gpx_data:
            # Falls jetzt gar nichts mehr übrig bleibt
            # -> wir setzen die Liste leer und updaten
            mw.gpx_widget.set_gpx_data([])
            mw._gpx_data = []
            # Alle Widgets neu leeren
            mw.chart.set_gpx_data([])
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data([])
            mw.map_widget.loadRoute(None, do_fit=False)
            mw._update_gpx_overview()
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            return
    
        # 3) Zeiten so verschieben, dass neuer Startpunkt rel_s=0
        
        set_gpx_video_shift(0) #TODO: test this 
        recalc_gpx_data(gpx_data)
    
        # 4) Data neu in GUI setzen
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
    
        # 5) Tabellen/Charts/Map etc. neu aufbauen
        mw._update_gpx_overview()
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        
        # 6) Markierungen zurücksetzen
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
    
    
    def on_cut_after_e_clicked(self):
        """
        Löscht alle GPX-Punkte ab MarkE bis zum Ende (einschl. E).
        Falls kein MarkE existiert, aber ein MarkB gesetzt ist, 
        verwenden wir ersatzweise MarkB als E.
        """
        mw = self._mainwindow
        if mw is None:
            return
    
        # Primär: MarkE-Index
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        # Fallback: falls MarkE nicht gesetzt, nimm MarkB
        if e_idx is None:
            e_idx = mw.gpx_widget.gpx_list._markB_idx

        # Falls weder B noch E gesetzt => Fehlermeldung
        if e_idx is None:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cut >E", "No MarkE or MarkB set.")
            return
    
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return
    
        if e_idx < 0 or e_idx >= len(gpx_data):
            return
    
        # 1) Undo-Snapshot
        
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()
    
        # 2) Löschen ab e_idx (inkl.) bis zum Ende
        del gpx_data[e_idx:]

        if not gpx_data:
            # Falls dabei alles wegfällt
            mw.gpx_widget.set_gpx_data([])
            mw._gpx_data = []
            mw.chart.set_gpx_data([])
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data([])
            mw.map_widget.loadRoute(None, do_fit=False)
            mw._update_gpx_overview()
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            return
        
        # 3) recalc
        
        recalc_gpx_data(gpx_data)
        
        # 4) Neu setzen und Widgets aktualisieren
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        
        mw._update_gpx_overview()
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        
        # 5) Markierungen zurücksetzen
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
    
        
        
    def highlight_markB_button(self):
        """Zeigt MarkB-Button in roter Farbe an."""
        self.markB_button.setStyleSheet("background-color: red; color: white;")

    def highlight_markE_button(self):
        """Zeigt MarkE-Button in roter Farbe an."""
        self.markE_button.setStyleSheet("background-color: red; color: white;")

    def reset_mark_buttons(self):
        """Setzt MarkB- und MarkE-Button auf ihr ursprüngliches StyleSheet zurück."""
        self.markB_button.setStyleSheet(self._default_markB_style)
        self.markE_button.setStyleSheet(self._default_markE_style)
        
        
    def _close_gaps_local_interpolation(self, b_idx: int, e_idx: int, dt: float):
        """
        Das ist dein alter Code, der zwischen b_idx und e_idx
        lineare Punkte einfügt, damit jeder Schritt ~1s lang ist.
        """
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data

        # 1) Undo-Snapshot
        
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()

        # 2) Koordinaten
        lat1, lon1, ele1 = gpx_data[b_idx]["lat"], gpx_data[b_idx]["lon"], gpx_data[b_idx]["ele"]
        lat2, lon2, ele2 = gpx_data[e_idx]["lat"], gpx_data[e_idx]["lon"], gpx_data[e_idx]["ele"]
        t1 = gpx_data[b_idx]["time"]

        # 3) Wie bisher: Anzahl Intervalle = round(dt)
        
        num_intervals = int(round(dt))
        if num_intervals < 2:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Gap to Close",
                f"Time difference ~{dt:.2f}s => no extra points needed.")
            return

        sub_s = dt / num_intervals
        new_points = []
        for i in range(1, num_intervals):
            frac = i / num_intervals
            new_t = t1 + timedelta(seconds=sub_s * i)
            lat_new = lat1 + frac*(lat2 - lat1)
            lon_new = lon1 + frac*(lon2 - lon1)
            ele_new = ele1 + frac*(ele2 - ele1)
            pt = {
                "lat": lat_new,
                "lon": lon_new,
                "ele": ele_new,
                "time": new_t,
                "delta_m": 0.0,
                "speed_kmh": 0.0,
                "gradient": 0.0
            }
            new_points.append(pt)

        # 4) Einfügen
        for i, p in enumerate(new_points):
            gpx_data.insert(b_idx + 1 + i, p)
    
        # 5) recalc
        
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
    
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)

        #from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Close Gaps",
            f"Inserted {len(new_points)} new point(s)\n(time-based local interpolation).")

        # 6) Markierungen zurücksetzen
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
    
    
    def _close_gaps_mapbox(self, b_idx: int, e_idx: int, dt: float, profile: str):
        """
        Ruft die Mapbox Directions API auf (profil = 'driving','cycling','walking'),
        berechnet time-based Densify in 1s-Schritten,
        und ersetzt b_idx..e_idx im GPX durch die neue Route.
        """
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data

       
        #from PySide6.QtWidgets import QMessageBox
      
    
        # 1) Undo-Snapshot
        #old_data = copy.deepcopy(gpx_data)
        #mw.gpx_widget.gpx_list._history_stack.append(old_data)
        self.register_gpx_undo_snapshot()

        lat1, lon1 = gpx_data[b_idx]["lat"], gpx_data[b_idx]["lon"]
        lat2, lon2 = gpx_data[e_idx]["lat"], gpx_data[e_idx]["lon"]

        # 2) Key prüfen
        if not mw._mapbox_key:
            QMessageBox.warning(self, "Mapbox Key missing",
                "Directions=True, aber kein mapbox_key gesetzt.\nFalle zurück auf lokale Interpolation.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        # 3) URL bauen (Mapbox-Directions)
        base_url = "https://api.mapbox.com/directions/v5/mapbox"
        url = (f"{base_url}/{profile}/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
            f"?geometries=geojson&overview=full&access_token={mw._mapbox_key}")
    
        # 4) HTTP an Mapbox per urllib
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
        except Exception as ex:
            QMessageBox.critical(self, "Mapbox Error",
                f"Could not fetch route from Mapbox:\n{ex}\n\nFalle zurück auf lokale Interpolation.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        if "routes" not in data or not data["routes"]:
            QMessageBox.warning(self, "No Route",
                "Mapbox lieferte keine 'routes' zurück.\nFalle zurück auf lokal.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        coords = data["routes"][0]["geometry"]["coordinates"]  # => [[lon, lat], [lon, lat], ...]
    
        if len(coords) < 2:
            QMessageBox.warning(self, "Invalid route",
                "Zu wenige Punkte in Mapbox-Route.\nFalle zurück auf lokal.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        # 5) Distanzberechnung => wir bauen Segmente, 
        #    dann verteilen wir dt in 1s-Schritte => time-based densify
        def haversine_m(latA, lonA, latB, lonB):
            import math
            R = 6371000
            rLA = math.radians(latA)
            rLB = math.radians(latB)
            dLat = rLB - rLA
            dLon = math.radians(lonB - lonA)
            a = (math.sin(dLat/2)**2
                + math.cos(rLA)*math.cos(rLB)*math.sin(dLon/2)**2)
            return R*2*math.atan2(math.sqrt(a), math.sqrt(1-a))

        # Koords in (lat, lon) => big_coords
        big_coords = [(c[1], c[0]) for c in coords]  # c[0]=lon, c[1]=lat

        segments = []
        total_dist = 0.0
        for i in range(len(big_coords)-1):
            la1, lo1 = big_coords[i]
            la2, lo2 = big_coords[i+1]
            d = haversine_m(la1, lo1, la2, lo2)
            segments.append((la1, lo1, la2, lo2, d, total_dist))
            total_dist += d

        if total_dist < 0.01:
            QMessageBox.information(self, "No Distance", 
                "Mapbox lieferte quasi Start=End.\nFalle zurück auf lokal.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        # Hilfsfunc
        def get_coord_at_dist(dist_val):
            # dist_val=0 => Start, dist_val>=total_dist => End
            if dist_val<=0:
                return big_coords[0]
            if dist_val>=total_dist:
                return big_coords[-1]
            for seg in segments:
                la1, lo1, la2, lo2, dseg, segStart = seg
                segEnd = segStart + dseg
                if dist_val>=segStart and dist_val<=segEnd:
                    frac = (dist_val-segStart)/dseg
                    lat_ = la1 + frac*(la2-la1)
                    lon_ = lo1 + frac*(lo2-lo1)
                    return (lat_, lon_)
            # fallback
            return big_coords[-1]

        # => now 1s-Schritte
       
        new_points = []
        t_start = gpx_data[b_idx]["time"]
        # final => gpx_data[e_idx]["time"] => dt sek

        speed_ms = total_dist/dt
        # how many integer steps => floor(dt)
        steps_count = int(math.floor(dt))
        if steps_count<1:
            steps_count=1

        for i in range(steps_count+1):
            dist_i = i*speed_ms
            if dist_i>total_dist:
                dist_i=total_dist
            (lat_, lon_) = get_coord_at_dist(dist_i)
            t_new = t_start + timedelta(seconds=i)
            pt = {
                "lat": lat_,
                "lon": lon_,
                "ele": 0,  
                "time": t_new,
                "delta_m": 0.0,
                "speed_kmh": 0.0,
                "gradient": 0.0
            }
            new_points.append(pt)

        # Letzter Punkt => exaktes E
        latE, lonE = gpx_data[e_idx]["lat"], gpx_data[e_idx]["lon"]
        new_points[-1]["lat"] = latE
        new_points[-1]["lon"] = lonE
        new_points[-1]["time"] = gpx_data[e_idx]["time"]

        # Optional: Elevation linear B->E
        # eleB = gpx_data[b_idx]["ele"]
        # eleE = gpx_data[e_idx]["ele"]
        # total_count = len(new_points)
        # for i in range(1, total_count):
        #     frac = i/total_count
        #     new_points[i]["ele"] = eleB + frac*(eleE-eleB)

        # 6) b_idx+1.. e_idx entfernen
        del gpx_data[b_idx+1 : e_idx+1]

        mapbox_ele_update_list =[]
        # Füge new_points[1..] ein (index=0 ist b_idx selbst)
        for i, p in enumerate(new_points[1:], start=1):
            gpx_data.insert(b_idx + i, p)
            mapbox_ele_update_list.append((b_idx + i,p["lat"], p["lon"]))
        # 7) recalc
       
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()

        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)

        QMessageBox.information(self, "Close Gaps (Mapbox)",
            f"Inserted {len(new_points)-1} new point(s)\n"
            f"via Directions={profile}, total time {dt:.2f}s kept.")

        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()

        self.update_elevation_from_mapbox(mapbox_ele_update_list)

    def register_gpx_undo_snapshot(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return

        snapshot = copy.deepcopy(gpx_data)

        def undo():
            mw.gpx_widget.set_gpx_data(snapshot)
            mw._gpx_data = snapshot
            mw._update_gpx_overview()
            mw.chart.set_gpx_data(snapshot)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(snapshot)
            route_geojson = mw._build_route_geojson_from_gpx(snapshot)
            mw.map_widget.loadRoute(route_geojson, do_fit=False) 
        mw._undo_stack.append(undo)
        
        
    def on_show_gpx_summary(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data loaded.")
            return

        n_points = len(gpx_data)
        t_start = gpx_data[0]["time"]
        t_end = gpx_data[-1]["time"]
        duration_s = (t_end - t_start).total_seconds()
        duration_str = str(t_end - t_start)

        dist_m = sum(
            self._haversine_m(
                gpx_data[i]["lat"], gpx_data[i]["lon"],
                gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            )
            for i in range(n_points - 1)
        )
        #dist_km = dist_m / 1000.0
        label_text = self.label_length.text()  # z.B. "Length(GPX): 66.12 km"
        try:
            dist_km = float(label_text.split(":")[1].replace("km", "").strip())
        except Exception:
            dist_km = 0.0

            
        ele_start = gpx_data[0].get("ele", 0.0)
        ele_end   = gpx_data[-1].get("ele", 0.0)
        elev_text = self.label_elev.text()
        try:
            elev_gain = float(elev_text.split(":")[1].replace("m", "").strip())
        except Exception:
            elev_gain = 0.0

        speeds = [pt.get("speed_kmh", 0.0) for pt in gpx_data if "speed_kmh" in pt]
        max_speed = max(speeds) if speeds else 0.0
        min_speed = min(speeds) if speeds else 0.0

        # -- Neuen Dialog bauen
        dlg = QDialog(self)
        dlg.setWindowTitle("GPX Summary")
        dlg.setMinimumWidth(350)

        layout = QVBoxLayout(dlg)
        label = QLabel(dlg)
        label.setTextFormat(Qt.RichText)
        label.setText(
            f"<div style='margin-left:50px;'>"
            f"<b>GPX Summary</b><br><br>"
            f"<table>"
            f"<tr><td><b>Total Points:</b></td><td>{n_points}</td></tr>"
            f"<tr><td><b>Duration:</b></td><td>{duration_str} ({int(duration_s)} sec)</td></tr>"
            f"<tr><td><b>Distance:</b></td><td>{dist_km:.2f} km</td></tr>"
            f"<tr><td><b>Start Elevation:</b></td><td>{ele_start:.1f} m</td></tr>"
            f"<tr><td><b>End Elevation:</b></td><td>{ele_end:.1f} m</td></tr>"
            f"<tr><td><b>Elevation Gain:</b></td><td>{elev_gain:.1f} m</td></tr>"
            f"<tr><td><b>Max Speed:</b></td><td>{max_speed:.1f} km/h</td></tr>"
            f"<tr><td><b>Min Speed:</b></td><td>{min_speed:.1f} km/h</td></tr>"
            f"</table>"
        )
        layout.addWidget(label)

        btn = QPushButton("OK", dlg)
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, alignment=Qt.AlignRight)

        dlg.exec()
        
        
    def _on_resample_to_1s_clicked(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data or len(gpx_data) < 2:
            QMessageBox.warning(self, "No GPX Data", "No or insufficient GPX data loaded.")
            return

        reply = QMessageBox.question(
            self,
            "Resample to 1s",
            "Do you really want to resample the entire track to 1-second intervals?\n\n"
            "This may slightly change the total distance and elevation.\n"
            "If this GPX was already synchronized with the video, "
            "you should re-check the alignment afterwards.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Undo-Snapshot
        self.register_gpx_undo_snapshot()

        # Resample
        new_data = mw._resample_to_1s(gpx_data)

        # Setzen
        mw._gpx_data = new_data
        mw.gpx_widget.set_gpx_data(new_data)
        mw._update_gpx_overview()
        mw.chart.set_gpx_data(new_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(new_data)

        QMessageBox.information(self, "Done", "GPX track has been resampled to 1s intervals.")
    

    def export_fit_immersion(self, threshold: float = 1.0):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data or len(gpx_data) < 2:
            return "<difficulty></difficulty>"

        start_time = gpx_data[0].get("time")
        if not start_time:
            return "<difficulty></difficulty>"

        def format_time(seconds: float) -> str:
            total_seconds = int(seconds)
            minutes = total_seconds // 60
            secs = total_seconds % 60
            return f"{minutes}:{secs:02d}"

        def calc_avg_slope(start_idx, end_idx):
            segment = gpx_data[start_idx:end_idx+1]
            total_dist = sum(p.get("delta_m", 0.0) for p in segment[1:])
            elev_diff = segment[-1]["ele"] - segment[0]["ele"]
            if total_dist > 0:
                return (elev_diff / total_dist) * 100
            else:
                return 0.0

        def convert_slope(slope):
            return int(round(15 + (slope/15) * 85))

        output = []
        segment_start = 0
        last_slope = calc_avg_slope(segment_start, segment_start+1)
        last_value = convert_slope(last_slope)
        output.append(f"0:00/{last_value}")

        i = segment_start + 2
        while i < len(gpx_data):
            best_index = None
            best_delta = 0
            current_slope = last_slope

            for j in range(i, min(i + 60, len(gpx_data))):
                avg_slope = calc_avg_slope(segment_start, j)
                delta = convert_slope(avg_slope) - last_value

                if abs(delta) >= threshold and abs(delta) > abs(best_delta):
                    best_index = j
                    best_delta = delta
                    current_slope = avg_slope

            if best_index is not None:
                t = gpx_data[best_index]["time"]
                rel_sec = (t - start_time).total_seconds()
                new_val = convert_slope(current_slope)
                output.append(f"{format_time(rel_sec)}/{new_val}")
                segment_start = best_index
                last_slope = current_slope
                last_value = new_val
                i = best_index + 1
            else:
                i += 1

        t = gpx_data[-1]["time"]
        rel_sec = (t - start_time).total_seconds()
        output.append(f"{format_time(rel_sec)}/{convert_slope(last_slope)}")

        result = f"<difficulty>{';'.join(output)}</difficulty>"
        print(result)
        return result

