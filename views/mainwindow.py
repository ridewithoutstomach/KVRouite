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

# views/mainwindow.py
import os
import sys
import subprocess
import json
import shutil
import base64
import config
import path_manager  # your module above
from path_manager import (COPY_MODE_FEHLT, copy_mode_fehlgrund,
                          copy_mode_moeglich)
import copy
import tempfile
import datetime
import math
import subprocess
import re
import hashlib
import statistics
import fitparse
import gc


            


from PySide6.QtCore import QUrl
from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QSettings
from PySide6.QtCore import QByteArray

from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import QGuiApplication
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtGui import QIcon
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import QPoint, QRect, QEvent
from PySide6.QtCore import QSize


from PySide6.QtWidgets import (
    QMainWindow, QWidget, QGridLayout, QFrame,
    QFileDialog, QMessageBox, QVBoxLayout,
    QLabel, QProgressBar, QHBoxLayout, QPushButton, QDialog,
    QApplication, QInputDialog, QSplitter, QSystemTrayIcon,
    QFormLayout, QComboBox, QSpinBox, QMenu, QTextEdit
)
from PySide6.QtWidgets import QDoubleSpinBox
from PySide6.QtWidgets import QLineEdit, QDialogButtonBox
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtWidgets import QToolButton, QLabel, QStyle

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtGui import QTextCursor


#updates
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QDesktopServices

from .encoder_setup_dialog import EncoderSetupDialog  # Import Dialog
from .export_bestaetigung import ExportBestaetigung

from config import TMP_KEYFRAME_DIR, MY_GLOBAL_TMP_DIR, is_soft_opengl_enabled
from core.mp4_keyframes import keyframe_times_from_index
from core import view360
from core import sprache
from core import stimme
from core import verkehr
from core.fade_cache import FadeJob, FadeRenderer
from core.thumb_cache import ThumbCache
from .dialogs import PreviewPrepareDialog, OutputFrameRateDialog
from core import framerate

from widgets.video_editor_widget import VideoEditorWidget
from widgets.video_timeline_widget import VideoTimelineWidget
from widgets.video_control_widget import VideoControlWidget
from widgets.chart_widget import ChartWidget
from widgets.map_widget import MapWidget
from widgets.gpx_widget import GPXWidget
from widgets.gpx_control_widget import GPXControlWidget

from managers.step_manager import StepManager
from managers.end_manager import EndManager
from managers.cut_manager import VideoCutManager
from core.gpx_parser import is_gpx_video_shift_set, parse_gpx  # Hier hinzufügen!

from managers.overlay_manager import OverlayManager

# ggf. import_export_manager, safe_manager etc.
from .dialogs import _IndexingDialog, _SafeExportDialog
from widgets.mini_chart_widget import MiniChartWidget
from widgets.slot_widget import SlotWidget
from widgets.audio_zoom_widget import AudioZoomWidget
from config import is_edit_video_enabled
from core.gpx_parser import parse_gpx
from core.gpx_parser import recalc_gpx_data, get_gpx_video_shift, set_gpx_video_shift
from tools.merge_keyframes_incremental import merge_keyframes_incremental
from config import APP_VERSION

from config import reset_config
from managers.encoder_manager import EncoderDialog

from datetime import datetime, timedelta




from core.gopro_extractor import (
    get_video_duration, extract_metadata, get_video_start_time,
    parse_gps5_data, adjust_gpx_to_video_duration,
    create_gpx_with_time, resample_to_1s_auto
)




FIT_BUILD = False  # Set to True if you want to enable Fit Immersion export functionality


### CLASS ####
class GoProExtractorDialog(QDialog):
    def __init__(self, video_list, parent=None, keep_append=False):  # <--- NEU
        super().__init__(parent)
        self.video_list = video_list
        self.parent = parent
        self.setWindowTitle("Extracting GoPro GPS...")
        self.setMinimumSize(600, 400)
        self.keep_append = keep_append
        self._update_check_is_manual = False
        
        layout = QVBoxLayout()
        self.status_label = QLabel(f"Processing 1/{len(video_list)} videos...")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(len(video_list))
        layout.addWidget(self.progress_bar)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_process)
        layout.addWidget(self.cancel_button)

        self.setLayout(layout)

        self.current_video_index = 0
        self.is_cancelled = False
        self._temp_gpx_files = []  # Liste der temporären GPX-Dateien


    def start_extraction(self):
        self.text_append("Starting GoPro GPS extraction...")
        self.text_append(f"Found {len(self.video_list)} video(s) to process")
        self.text_append("Experimental - Only works with GoPro files containing GPS")
        self.text_append("=" * 50)
        QTimer.singleShot(100, self.process_next_video)

    def process_next_video(self):
        if self.is_cancelled:
            self.text_append("\nProcess cancelled by user")
            self.set_finished_state()
            return

        if self.current_video_index >= len(self.video_list):
            # Alle Videos fertig -> kombinieren
            self._combine_all_temp_files()
            return

        video_path = self.video_list[self.current_video_index]
        self.status_label.setText(
            f"Processing {self.current_video_index + 1}/{len(self.video_list)}: {os.path.basename(video_path)}"
        )
        self.progress_bar.setValue(self.current_video_index + 1)

        self.text_append(f"\n--- Processing: {os.path.basename(video_path)} ---")
        QApplication.processEvents()

        try:
            # Extrahiere und speichere als temporäre Datei
            temp_gpx_path = self._process_single_video(video_path)
            if temp_gpx_path:
                self._temp_gpx_files.append(temp_gpx_path)
                self.text_append(f"✓ Saved temporary GPX: {os.path.basename(temp_gpx_path)}")
            else:
                self.text_append(f"✗ No GPS data for {os.path.basename(video_path)}")
        except Exception as e:
            import traceback
            self.text_append(f"✗ Error in extraction: {e}")
            self.text_append(traceback.format_exc())

        # nächstes Video
        self.current_video_index += 1
        QTimer.singleShot(400, self.process_next_video)

    
    def _process_single_video(self, video_path: str):
        """Verarbeitet ein einzelnes Video und speichert es als temporäre GPX-Datei"""
        try:
            import gc
            video_duration = get_video_duration(video_path)
            if not video_duration:
                self.text_append("✗ Could not get video duration")
                return None
    
            metadata = extract_metadata(video_path)
            if not metadata:
                self.text_append("✗ No GPS metadata found in video")
                return None
    
            # Rohpunkte extrahieren (Liste von Tuples (lat,lon,alt,datetime))
            points = parse_gps5_data(metadata)
            if not points:
                self.text_append("✗ No GPS points extracted")
                return None
    
            # -------------------------------------------------------
            # 1) Sofort in Temp JSON speichern (RAM entlasten)
            #    save_temp_points kommt aus core.gopro_extractor
            # -------------------------------------------------------
            try:
                from core.gopro_extractor import save_temp_points, load_temp_points
                temp_json_path = save_temp_points(points, video_path)
            except Exception as e:
                temp_json_path = None
                self.text_append(f"⚠ Could not save temp JSON: {e}")
    
            # RAM freigeben (Metadata + raw points)
            try:
                del metadata
                del points
            except Exception:
                pass
            gc.collect()
    
            # -------------------------------------------------------
            # 2) Lade die Punkte (als dicts mit datetime) - nur jetzt
            # -------------------------------------------------------
            if temp_json_path:
                points_dict = load_temp_points(temp_json_path)
            else:
                # Fallback: falls save fehlgeschlagen, versuche nochmal parse direkt
                points = parse_gps5_data(extract_metadata(video_path))
                points_dict = [
                    {"lat": lat, "lon": lon, "ele": alt, "time": timestamp}
                    for (lat, lon, alt, timestamp) in points
                ]
    
            if not points_dict:
                self.text_append("✗ No GPS points after loading temp JSON")
                return None
    
            # -------------------------------------------------------
            # 3) Video-Dauer grob anpassen (>0,5s)
            # -------------------------------------------------------
            points_adjusted = adjust_gpx_to_video_duration(points_dict, video_duration)
    
            # -------------------------------------------------------
            # 4) Resample auf 1 Hz (import lokal, bereits vorhanden)
            # -------------------------------------------------------
            try:
                from core.gopro_extractor import resample_to_1s_auto
                points_final = resample_to_1s_auto(points_adjusted)
                self.text_append(f"→ Resampled to {len(points_final)} points (1s grid)")
            except Exception as e:
                self.text_append(f"⚠ Resample skipped due to error: {e}")
                points_final = points_adjusted
    
            # -------------------------------------------------------
            # 5) Letzten Punkt exakt auf Videolänge bringen (ms auffüllen)
            # -------------------------------------------------------
            points_final = self.extend_last_point_to_video(points_final, video_duration)
    
            # -------------------------------------------------------
            # 6) Temporäre GPX-Datei erstellen
            # -------------------------------------------------------
            temp_filename = f"KVR_GOPRO_{self.current_video_index:04d}.tmp.gpx"
            temp_path = os.path.join(MY_GLOBAL_TMP_DIR, temp_filename)
    
            from core.gopro_extractor import create_gpx_with_time
            create_gpx_with_time(points_final, temp_path)
    
            # -------------------------------------------------------
            # 7) Aufräumen: Lösche optional die Temp-JSON-Datei
            # -------------------------------------------------------
            try:
                if temp_json_path and os.path.exists(temp_json_path):
                    os.remove(temp_json_path)
                    self.text_append(f"✓ Deleted temp JSON: {os.path.basename(temp_json_path)}")
            except Exception as e:
                self.text_append(f"⚠ Could not delete temp JSON: {e}")
    
            return temp_path
    
        except Exception as e:
            import traceback
            self.text_append(f"✗ Extraction error: {e}")
            self.text_append(traceback.format_exc())
            return None
    
    
    def extend_last_point_to_video(self, points, video_duration):
        """
        Stellt sicher, dass die letzte GPX-Zeit dem Video entspricht.
        Fügt die Differenz in Millisekunden nur dem letzten Punkt hinzu.
        Keine Interpolation von lat/lon/ele.
        """
        if not points or len(points) < 1:
            return points

        gpx_start = points[0]["time"]
        gpx_end = points[-1]["time"]
        gpx_duration = (gpx_end - gpx_start).total_seconds()
        diff = video_duration - gpx_duration

        if diff <= 0 or diff < 0.001:  # Kleine Differenz ignorieren
            return points

        points[-1]["time"] += timedelta(seconds=diff)
        return points
        

    def _combine_all_temp_files(self):
        """Kombiniert alle temporären GPX-Dateien mit korrekter Zeitfortführung"""
        self.text_append("\n✓ All videos processed successfully!")
        if not self._temp_gpx_files:
            self.text_append("✗ No GPS data found in any video.")
            self.set_finished_state()
            return

        try:
            from datetime import datetime, timedelta
            
            all_combined_data = []
            current_end_time = None
            if getattr(self, "keep_append", False):
                try:
                    existing = self.parent._gpx_slots[2]["gpx_data"] or []
                except Exception:
                    existing = []
                if existing:
                    # Vorhandene Punkte übernehmen und Endzeit merken
                    all_combined_data.extend(existing)
                    try:
                        current_end_time = existing[-1]["time"]
                    except Exception:
                        current_end_time = None
                    self.text_append(f"↪ Appending to existing Slot 2 (ends at {current_end_time})")
        
            for i, temp_gpx_path in enumerate(self._temp_gpx_files):
                self.text_append(f"\n--- Combining file {i+1}/{len(self._temp_gpx_files)} ---")
                
                # Parse temporäre GPX-Datei
                temp_data = parse_gpx(temp_gpx_path)
                if not temp_data:
                    self.text_append(f"⚠ Could not parse {os.path.basename(temp_gpx_path)}")
                    continue
            
                if current_end_time is None:
                    # Erste Datei: Komplett übernehmen
                    #start_time = datetime.now().replace(microsecond=0)
                    from datetime import timezone

                    start_time = datetime.now(timezone.utc).replace(microsecond=0)
                    
                    self.text_append(f"📅 First file starts at: {start_time}")
                    
                    #for j, pt in enumerate(temp_data):
                    #    pt["time"] = start_time + timedelta(seconds=j)
                    offset = start_time - temp_data[0]["time"]
                    for pt in temp_data:
                        pt["time"] += offset  # Millisekunden bleiben erhalten
                    
                    all_combined_data.extend(temp_data)
                    current_end_time = temp_data[-1]["time"]
                    self.text_append(f"✓ Added {len(temp_data)} points, track ends at: {current_end_time}")
                else:
                    # Folgedateien: ERSTEN PUNKT ENTFERNEN und dann anhängen
                    if len(temp_data) <= 1:
                        self.text_append(f"⚠ File has only {len(temp_data)} point, skipping")
                        continue
                    
                    # Ersten Punkt entfernen
                    temp_data_without_first = temp_data[1:]
                    expected_start = current_end_time + timedelta(seconds=1)
                    
                    self.text_append(f"📅 Next file starts at: {expected_start} (first point removed)")
                    self.text_append(f"   Original: {len(temp_data)} points, After removal: {len(temp_data_without_first)} points")
                    
                    # Zeitstempel für die verbleibenden Punkte setzen
                    #for j, pt in enumerate(temp_data_without_first):
                    #    pt["time"] = expected_start + timedelta(seconds=j)
                    
                    offset = expected_start - temp_data_without_first[0]["time"]
                    for pt in temp_data_without_first:
                        pt["time"] += offset  # Millisekunden bleiben erhalten
                
                    all_combined_data.extend(temp_data_without_first)
                    current_end_time = temp_data_without_first[-1]["time"]
                    self.text_append(f"✓ Added {len(temp_data_without_first)} points, track ends at: {current_end_time}")
            
            # Finale kombinierte Datei schreiben
            combined_path = os.path.join(MY_GLOBAL_TMP_DIR, "KVR_GOPRO_Combined.tmp.gpx")
            from core.gopro_extractor import create_gpx_with_time
            create_gpx_with_time(all_combined_data, combined_path)
            
            self.text_append(f"\n🎉 Successfully combined {len(all_combined_data)} points from {len(self._temp_gpx_files)} files")
            self.text_append(f"✓ Final GPX: {combined_path}")
            
            # Importieren
            self.text_append(">>> Starting GPX import...")
            self.parent._import_gopro_gpx(combined_path, True)
            self.text_append(">>> GPX import finished")
            
            # Aufräumen
            self._cleanup_temp_files(combined_path)
            
        except Exception as e:
            import traceback
            self.text_append(f"✗ Error combining GPX files: {e}")
            self.text_append(traceback.format_exc())
        
        self.set_finished_state()
        
    
    def _cleanup_temp_files(self, combined_path):
        """Löscht alle temporären Dateien"""
        try:
            # Lösche kombinierte Datei
            os.remove(combined_path)
            self.text_append("✓ Combined temp file deleted")
            
            # Lösche einzelne temporäre Dateien
            for temp_path in self._temp_gpx_files:
                try:
                    os.remove(temp_path)
                except Exception as e:
                    self.text_append(f"⚠ Could not delete {os.path.basename(temp_path)}: {e}")
            
            self.text_append("✓ All temp files cleaned up")
            
        except Exception as e:
            self.text_append(f"⚠ Cleanup error: {e}")

    def text_append(self, text):
        self.text_edit.append(text)
        QApplication.processEvents()

    def cancel_process(self):
        self.is_cancelled = True
        self.text_append("\nProcess cancelled by user")
        # Aufräumen der temporären Dateien
        self._cleanup_temp_files(None)
        self.set_finished_state()

    def set_finished_state(self):
        self.cancel_button.setText("Close")
        try:
            self.cancel_button.clicked.disconnect()
        except Exception:
            pass
        self.cancel_button.clicked.connect(self.show_elevation_notice)

    def show_elevation_notice(self):
        QMessageBox.information(
            self,
            "Elevation Data Quality Notice",
            "Raw GoPro elevation data is often inaccurate.\n"
            "Use 'Update Elevation' or smoothing for better results."
        )
        self.accept()


### CLASS

class MainWindow(QMainWindow):
    def __init__(self, user_wants_editing=False):
        
        super().__init__()
        
        self._undo_stack = []
        
        self._maptiler_key = ""
        self._mapbox_key   = ""
        
        self._load_map_keys_from_settings()
        
        
               
       
        self._userDeclinedIndexing = False
        
        
        self._video_at_end = False   # Merker, ob wir wirklich am Ende sind
        self._autoSyncVideoEnabled = False
        self._autoSyncNewPointsWithVideoTime = False
        self.user_wants_editing = user_wants_editing
        
        
        
        self._projekt_datei = None      # Pfad des geladenen Projekts, oder None
        self._titel_setzen()
            
        
        self._sync_prompt_answer = None   # None = unknown / not asked yet, True/False = user's first answer
        self._last_gpx_load_mode = None   # "new" | "append" | None 
            
        
        
        
        
               
        self._gpx_data = []
        
        self._gpx_slots = {
            1: {
                "gpx_data": [],
                "gpx_video_shift": None,
                "markB": None,
                "markE": None,
                "sync_enabled": False,         # per-Slot „Sync all with video“
                "sync_marker": None,           # per-Slot „Set Sync“ (Index)
                # Lesezeichen auf Punkte dieser Spur, je {name, lat, lon}.
                # Je Slot, weil die Koordinaten zu genau einer Spur gehoeren
                # - siehe core/lesezeichen.py.
                "bookmarks": [],
            },
            2: {
                "gpx_data": [],
                "gpx_video_shift": None,
                "markB": None,
                "markE": None,
                "sync_enabled": True,          # GoPro-Slot startet ON
                "sync_marker": None,
                "bookmarks": [],
            }
        }

        self._active_gpx_slot = 1  # 1 = Standard-Import, 2 = GoPro-Extractor

        # Playlist / Keyframe-Daten
        self.playlist = []
        self.video_durations = []
        # Sprechstellen des Voice Removers (ab 7.0): je Videopfad eine Liste
        # [[von, bis], ...] in Sekunden DER DATEI. Gefunden vom Detektor
        # (stimmen_suchen) oder von Hand gesetzt; Projektdatei "voice_regions".
        # Der Export trennt nur dort - siehe ges_encoder_manager.
        self._sprechstellen = {}
        # 360-Blickwinkel, ein Eintrag je Video - siehe _blick360_liste().
        self.view360_views = []
        # True, sobald ein Projekt den 360-Zustand mitgebracht hat. Dann
        # schaltet die Automatik nicht mehr dazwischen.
        self._360_aus_projekt = False
        self.playlist_counter = 0
        self.first_video_frame_shown = False
        self.real_total_duration = 0.0
        self.global_keyframes = []

        # Menüs
        self.statusBar().showMessage("Ready")
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        dummy_action = QAction("New Project", self)
        dummy_action.setStatusTip("Closed all loaded files/cuts/edits and open a new Project.")

        file_menu.addAction(dummy_action)
        dummy_action.triggered.connect(self._on_new_project_triggered)

        file_menu.addSeparator()

        load_project_action = QAction("Load Project...", self)
        load_project_action.setStatusTip("Open a already saved Project.")
        load_project_action.triggered.connect(self.load_project)
        file_menu.addAction(load_project_action)
        
        self.recent_menu = QMenu("Open Recent", self)
        file_menu.addMenu(self.recent_menu)    
        self.update_recent_files_menu()
        file_menu.addSeparator()

        load_track_action = QAction("Import GPX/FIT", self)
        load_track_action.setStatusTip("Load a GPX or FIT track file")
        load_track_action.triggered.connect(self.load_track_file)
        file_menu.addAction(load_track_action)

        load_mp4_action = QAction("Import Video", self)
        load_mp4_action.setStatusTip("Load one or more Videos.")
        load_mp4_action.triggered.connect(self.load_mp4_files)
        file_menu.addAction(load_mp4_action)
        
        
        file_menu.addSeparator()
        extract_gopro_gps_action = QAction("*Gopo-Extractor", self)
        extract_gopro_gps_action.setStatusTip("Extract GPS from all loaded GoPro videos")
        extract_gopro_gps_action.triggered.connect(self._on_extract_gopro_gps)
        file_menu.addSeparator()
        file_menu.addAction(extract_gopro_gps_action)
        file_menu.addSeparator()
        
        
        
        save_project_action = QAction("Save Project...", self)
        save_project_action.setStatusTip("Safe the loaded files and edits as project.")
        save_project_action.triggered.connect(self.save_project)
        file_menu.addAction(save_project_action)

        save_gpx_action = QAction("Export GPX...", self)
        save_gpx_action.setStatusTip("Safe/Export the edited GPX File.")
        save_gpx_action.triggered.connect(self.on_save_gpx_clicked)
        file_menu.addAction(save_gpx_action)

        render_action = QAction("Export Video...", self)
        render_action.setStatusTip("Export in Copy-Mode or Encode-Mode the edited Video.")
        render_action.triggered.connect(self.on_render_clicked)
        file_menu.addAction(render_action)

        # --- Shortcuts-Menü (ehemals "Edit") ---
        shortcuts_menu = menubar.addMenu("Edit")
        shortcuts_menu.setStatusTip("Keyboard shortcuts and player controls")

        # 1) Undo
        undo_action = QAction("Undo", self)
        undo_action.setStatusTip("Revert the last action.")
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        shortcuts_menu.addAction(undo_action)

        # Die Schritte mit Namen, und "bis hierher zurueck" - siehe
        # _show_undo_history().
        undo_history_action = QAction("Undo history...", self)
        undo_history_action.setStatusTip(
            "Show the steps Ctrl+Z would undo, and undo back to one of them.")
        undo_history_action.triggered.connect(self._show_undo_history)
        shortcuts_menu.addAction(undo_history_action)
        # (Deine bestehende Zeile unten im Code behalten:)
        # undo_action.triggered.connect(self.on_global_undo)

        # Die Shortcut-Uebersicht steht seit 6.13 unter Help, nicht mehr
        # hier: sie ist eine Hilfeseite, keine Bearbeitung.

        

        self.playlist_menu = menubar.addMenu("Playlist")
        
        self._playlist_reorder_action = QAction("Reorder…", self)
        self._playlist_reorder_action.setStatusTip("Change the order of the loaded videos")
        self._playlist_reorder_action.triggered.connect(self._on_open_reorder_playlist_dialog)

        # Beim initialen Aufbau oben in das Playlist-Menü einsetzen
        self.playlist_menu.addAction(self._playlist_reorder_action)
        self.playlist_menu.addSeparator()
        
        view_menu = menubar.addMenu("View")

        # Die Kopfzeilen der Fenster kosten je rund 20 px. Ausgeschaltet
        # bleiben Schwebeknopf und Rechtsklick als Wege zum Umschalten.
        self.action_slot_kopf = QAction("Window Headers", self, checkable=True)
        self.action_slot_kopf.setStatusTip(
            "Show or hide a slim bar with the module name on each window.")
        self.action_slot_kopf.setChecked(
            QSettings("KVRouite", "KVRouite").value(
                self._KOPFZEILEN_KEY, False, type=bool))
        self.action_slot_kopf.toggled.connect(self._kopfzeilen_umschalten)
        # Eingehaengt wird weiter unten im Config-Menue - siehe dort.

        # Wo die GPX-Leiste (Knoepfe und Infozeile) steht: unter oder ueber
        # der Tabelle, unter oder ueber der Karte, oder frei schwebend mit
        # Griff. Gleiche Leiste, nur umgehaengt - siehe _gpx_leiste_anwenden.
        self.gpx_leiste_menu = QMenu("GPX Bar Position", self)
        self._gpx_leiste_gruppe = QActionGroup(self)
        self._gpx_leiste_gruppe.setExclusive(True)
        self._gpx_leiste_actions = {}
        gespeichert = self._gpx_leiste_ort_gespeichert()
        for ort, text in self._GPX_LEISTE_ORTE:
            a = QAction(text, self, checkable=True)
            a.setChecked(ort == gespeichert)
            a.triggered.connect(lambda _=False, o=ort: self._gpx_leiste_umschalten(o))
            self._gpx_leiste_gruppe.addAction(a)
            self.gpx_leiste_menu.addAction(a)
            self._gpx_leiste_actions[ort] = a

        # Hoehenprofil ins Videobild einblenden. Frei verschiebbar, am
        # Punktraster-Griff; die Stelle wird gemerkt (_OVERLAY_POS_KEY).
        self.action_hoehen_overlay = QAction(
            "Elevation Profile in Video", self, checkable=True)
        self.action_hoehen_overlay.setStatusTip(
            "Shows the elevation profile as an overlay in the video image. "
            "Drag it by its handle to wherever you want it.")
        self.action_hoehen_overlay.setChecked(
            QSettings("KVRouite", "KVRouite").value(
                self._OVERLAY_KEY, False, type=bool))
        self.action_hoehen_overlay.toggled.connect(self._hoehen_overlay_umschalten)
        # Eingehaengt wird weiter unten im Config-Menue - siehe dort.

         # 360° Video Toggle (Taste V)
        self.action_toggle_360 = QAction("360° Video", self, checkable=True)
        self.action_toggle_360.setStatusTip(
            "Toggle 360° view - drag to look around, wheel to zoom (key: V). "
            "Needs the GES backend.")
        self.action_toggle_360.setShortcut(QKeySequence("V"))
        view_menu.addAction(self.action_toggle_360)

        self.action_toggle_360.triggered.connect(self._on_toggle_360_from_menu)

        # Der Blickwinkel gehoert zu je einem Video. Material aus derselben
        # Kamera hat aber praktisch immer dieselbe Ausrichtung - deshalb der
        # Weg, ihn in einem Schritt auf alle zu uebertragen.
        self.action_360_auf_alle = QAction("Apply 360° view to all videos", self)
        self.action_360_auf_alle.setStatusTip(
            "Copy the current viewing direction and zoom to every video")
        view_menu.addAction(self.action_360_auf_alle)
        self.action_360_auf_alle.triggered.connect(self._on_blick360_auf_alle)
        
        setup_menu = menubar.addMenu("Config")
        
        
        # Neues Untermenü "Edit Video" mit drei checkbaren Actions
        edit_video_menu = setup_menu.addMenu("Edit Video")

        self.off_action = QAction("Off", self, checkable=True)
        self.off_action.setStatusTip("Video Editing OFF / Only GPX Editing.")
        self.copy_action = QAction("Copy-Mode", self, checkable=True)
        self.copy_action.setStatusTip("Copy-Mode: Video will be produce in Copy-Mode: Fast, but with hard Cuts.")
        self.encode_action = QAction("Encode-Mode", self, checkable=True)
        self.encode_action.setStatusTip("Encode-Mode: Video will be encoded with the settings of Encoder-Setup: Slow, but with Xfades/Ovrlays")

        self.edit_mode_group = QActionGroup(self)
        self.edit_mode_group.setExclusive(True)

        self.edit_mode_group.addAction(self.off_action)
        self.edit_mode_group.addAction(self.copy_action)
        self.edit_mode_group.addAction(self.encode_action)

        edit_video_menu.addAction(self.off_action)
        edit_video_menu.addAction(self.copy_action)
        edit_video_menu.addAction(self.encode_action)

        # Standard = Off
        self.off_action.setChecked(True)
        self._edit_mode = "off"
        self._userDeclinedIndexing = False  # Falls du es schon hattest

        # Verknüpfe klick => _set_edit_mode(...)
        self.off_action.triggered.connect(lambda: self._set_edit_mode("off"))
        self.copy_action.triggered.connect(lambda: self._set_edit_mode("copy"))
        self.encode_action.triggered.connect(lambda: self._set_edit_mode("encode"))

        # Copy-Mode braucht ffmpeg UND ffprobe: er schneidet an Keyframes mit
        # "-c copy" (ffmpeg), indiziert die Keyframes und misst die
        # Segmentlaengen (beides ffprobe). Seit 6.0 wird nichts davon mehr
        # mitgeliefert - fehlt eines von beiden im PATH, wird der Modus gar
        # nicht erst angeboten.
        if not copy_mode_moeglich():
            self.copy_action.setEnabled(False)
            self.copy_action.setStatusTip(COPY_MODE_FEHLT)
            self.copy_action.setToolTip(COPY_MODE_FEHLT)
            print("[INFO] Copy-Mode ist abgeschaltet: " + copy_mode_fehlgrund())
       
        
        
        
        self.encoder_setup_action = QAction("Encoder-Setup", self)
        self.encoder_setup_action.setStatusTip("Setup for Encoder: like Resulution/Quality/Hardware ...")
        self.encoder_setup_action.setEnabled(False)  # am Anfang ausgegraut
        setup_menu.addAction(self.encoder_setup_action)
        self.encoder_setup_action.triggered.connect(self._on_encoder_setup_clicked)
        
        self.overlay_setup_action = QAction("Overlay Library", self)
        self.overlay_setup_action.setStatusTip(
            "Manage the images offered when inserting an overlay.")
        self.overlay_setup_action.setEnabled(False)  # Standard: ausgegraut
        setup_menu.addAction(self.overlay_setup_action)
        self.overlay_setup_action.triggered.connect(self._on_overlay_setup_clicked)
        
        
        
        
        self.action_auto_sync_video = QAction("AutoCutVideo+GPX", self)
        self.action_auto_sync_video.setStatusTip("Cuts the Video and the GPX in one step.")
        self.action_auto_sync_video.setCheckable(True)
        self.action_auto_sync_video.setChecked(False)  # Standard = OFF
        self.action_auto_sync_video.triggered.connect(self._on_auto_sync_video_toggled)
        setup_menu.addAction(self.action_auto_sync_video)
        
        player_setup_menu = setup_menu.addMenu("Player-Setup")

       
        
        # "Show Endcut Warning" Option (standardmäßig an)
        self.action_show_endcut_warning = QAction("Show Endcut Warning", self)
        self.action_show_endcut_warning.setStatusTip("Show popup warning when endcut is detected")
        self.action_show_endcut_warning.setCheckable(True)
        self.action_show_endcut_warning.setChecked(True)  # Standard: an
        self.action_show_endcut_warning.triggered.connect(self._on_show_endcut_warning_toggled)
        player_setup_menu.addAction(self.action_show_endcut_warning)

        # ▼ Time-Untermenü in Player-Setup (statt Top-Level)
        time_submenu = player_setup_menu.addMenu("Time: Final/Global")

        self.timer_action_group = QActionGroup(self)
        self.timer_action_group.setExclusive(True)

        self.action_global_time = QAction("Global Time", self)
        self.action_global_time.setStatusTip("Shows the global time in the Video Editor  (cuts are NOT calculated).")
        self.action_global_time.setCheckable(True)

        self.action_final_time = QAction("Final Time", self)
        self.action_final_time.setStatusTip("Shows the final time in the Video Editor  (cuts are calculated).")
        self.action_final_time.setCheckable(True)

        self.timer_action_group.addAction(self.action_global_time)
        self.timer_action_group.addAction(self.action_final_time)

        # HIER war vorher timer_menu.addAction(...): jetzt ins time_submenu hängen
        time_submenu.addAction(self.action_global_time)
        time_submenu.addAction(self.action_final_time)

        
        
        
        
        ffmpeg_menu = setup_menu.addMenu("FFmpeg")

        action_show_ffmpeg_path = QAction("Show current path", self)
        action_show_ffmpeg_path.setStatusTip("shows the current path of ffmpeg")
        action_show_ffmpeg_path.triggered.connect(self._on_show_ffmpeg_path)
        ffmpeg_menu.addAction(action_show_ffmpeg_path)
        
        action_set_ffmpeg_path = QAction("Set ffmpeg Path...", self)
        action_set_ffmpeg_path.setStatusTip(
            "Point KVRouite at your ffmpeg if it is not in your PATH")
        action_set_ffmpeg_path.triggered.connect(self._on_set_ffmpeg_path)
        ffmpeg_menu.addAction(action_set_ffmpeg_path)
    
        action_clear_ffmpeg_path = QAction("Clear ffmpeg Path", self)
        action_clear_ffmpeg_path.setStatusTip(
            "forget the stored path and look for ffmpeg in your PATH again")
        action_clear_ffmpeg_path.triggered.connect(self._on_clear_ffmpeg_path)
        ffmpeg_menu.addAction(action_clear_ffmpeg_path)
        
        # Ein Menue fuer die Wahl des Wiedergabewegs gibt es seit 6.0 nicht
        # mehr: es laeuft nur noch GStreamer / GES. Ebenso entfaellt der
        # libmpv-Pfad.

        temp_dir_menu = setup_menu.addMenu("Temp Directory")

        action_show_temp_dir = QAction("Show current Temp Directory", self)
        action_show_temp_dir.setStatusTip("Shows the current Temp Directory.")
        action_show_temp_dir.triggered.connect(self._on_show_temp_dir)
        temp_dir_menu.addAction(action_show_temp_dir)
        
        
        
        action_set_temp_dir = QAction("Set Temp Dir...", self)
        action_set_temp_dir.setStatusTip("in case you need your own Temp-Directory (space), change it here ")
        action_set_temp_dir.triggered.connect(self._on_set_temp_dir)
        temp_dir_menu.addAction(action_set_temp_dir)

        action_clear_temp_dir = QAction("Reset Temp Dir", self)
        action_clear_temp_dir.setStatusTip("reset the temp-direrctory to KVRouite-standard")
        action_clear_temp_dir.triggered.connect(self._on_clear_temp_dir)
        temp_dir_menu.addAction(action_clear_temp_dir)


        
        
        chart_menu = setup_menu.addMenu("Chart-Settings")
        limit_speed_action = QAction("Limit Speed...", self)
        limit_speed_action.setStatusTip("Set the limit speed that we intersect in the graph above. The higher the speed, the flatter the graph")
        chart_menu.addAction(limit_speed_action)
        limit_speed_action.triggered.connect(self._on_set_limit_speed)
        
        zero_speed_action = QAction("Mark ZeroSpeed...", self)
        zero_speed_action.setStatusTip("Set the ZeroSpeed we mark in the chart, all speeds lower are marked")
        zero_speed_action.triggered.connect(self._on_zero_speed_action)
        chart_menu.addAction(zero_speed_action)
        
        
        action_mark_stops = QAction("Mark TimeGaps...", self)
        action_mark_stops.setStatusTip("Set the MarkStops Value, all GPX-Points with a higher value will be marked in the chart")
        action_mark_stops.triggered.connect(self._on_set_stop_threshold)
        chart_menu.addAction(action_mark_stops)
        
        map_setup_menu = setup_menu.addMenu("Map Setup")
        
        self._directions_enabled = False  # beim Start immer aus

        # 2) Eine neue Check-Action anlegen
        self.action_map_directions = QAction("Directions", self)
        self.action_map_directions.setStatusTip("Activate the Directions-Feature to build routes wit mapbox Directions ( Autobuold on known tracks)")
        self.action_map_directions.setCheckable(True)
        self.action_map_directions.setChecked(False)  # standard: aus
        

        # 3) Ins Menü einfügen
        map_setup_menu.addAction(self.action_map_directions)

        # 4) Signal verknüpfen
        self.action_map_directions.triggered.connect(self._on_map_directions_toggled)
        
        
        mapviews_menu = map_setup_menu.addMenu("Map Keys")
        
        # --> About Keys
        about_keys_action = QAction("About Keys...", self)
        about_keys_action.triggered.connect(self._on_about_keys)
        mapviews_menu.addAction(about_keys_action)


        action_set_maptiler_key = QAction("Set MapTiler Key...", self)
        action_set_maptiler_key.triggered.connect(self._on_set_maptiler_key)
        mapviews_menu.addAction(action_set_maptiler_key)

       

        # --> Set Mapbox Key
        action_set_mapbox_key = QAction("Set Mapbox Key...", self)
        action_set_mapbox_key.triggered.connect(self._on_set_mapbox_key)
        mapviews_menu.addAction(action_set_mapbox_key)

        
        self.action_new_pts_video_time = QAction("Sync all with video", self)
        self.action_new_pts_video_time.setStatusTip("If activates we automatically sync the video to a select gpx point without using V-Sync-Button")
        self.action_new_pts_video_time.setCheckable(True)
        self.action_new_pts_video_time.setChecked(False)  # Standard = OFF
        self.action_new_pts_video_time.triggered.connect(self._on_sync_point_video_time_toggled)
        setup_menu.addAction(self.action_new_pts_video_time)               
        
        pts_size_menu = map_setup_menu.addMenu("Points Size")

        action_size_black = QAction("Black Point", self)
        action_size_black.setStatusTip("Change the Size of the GPX-Dot in the map")
        action_size_black.triggered.connect(lambda: self._on_set_map_point_size("black"))
        pts_size_menu.addAction(action_size_black)
        
        action_size_red = QAction("Red Point", self)
        action_size_red.setStatusTip("Change the Size of the GPX-Dot in the map")
        action_size_red.triggered.connect(lambda: self._on_set_map_point_size("red"))
        pts_size_menu.addAction(action_size_red)
        
        # Action 2: Size blue Point
        action_size_blue = QAction("Blue Point", self)
        action_size_blue.setStatusTip("Change the Size of the GPX-Dot in the map")
        action_size_blue.triggered.connect(lambda: self._on_set_map_point_size("blue"))
        pts_size_menu.addAction(action_size_blue)
        
        map_setup_menu.addMenu(pts_size_menu)
        
        action_size_yellow = QAction("Yellow Point", self)
        action_size_yellow.setStatusTip("Change the Size of the GPX-Dot in the map")
        action_size_yellow.triggered.connect(lambda: self._on_set_map_point_size("yellow"))
        pts_size_menu.addAction(action_size_yellow)
        
        
        
        
        self.action_lock_width = QAction("Lock Window Width", self, checkable=True)
        self.action_lock_width.setStatusTip(
            "Keep the window from resizing itself when buttons appear. "
            "The window can still be resized by hand, but not below the width "
            "the toolbars need.")
        self.action_lock_width.setChecked(
            QSettings("KVRouite", "KVRouite").value("ui/freeze_width", False, type=bool))
        self.action_lock_width.toggled.connect(self._on_lock_width_toggled)
        # Eingehaengt wird ganz unten im Config-Menue, vor den Resets.

        # Vorschaubilder und Tonspur in der Zeitleiste: bis 7.0 ein
        # Menuepunkt hier ("Thumbnails in Timeline"), seit 7.0 der kleine
        # Ansichtsknopf links oben in der Zeitleiste selbst - siehe
        # _timeline_ansicht_gewechselt.

        # Stand bis zum 04.09.2026 im View-Menue. Ist aber keine Ansicht,
        # die man staendig wechselt, sondern eine Einstellung, die man
        # einmal trifft - wie die Thumbnails darueber. Angelegt wird die
        # Aktion beim View-Menue; hier haengt sie nur. Die Kopfzeilen
        # (action_slot_kopf) haengen weiter unten, bei Lock Window Width.
        setup_menu.addAction(self.action_hoehen_overlay)

        # Farbgebung: hell, dunkel oder wie das System es haelt (core/theme.py).
        from core import theme
        # "Theme" und nicht "Appearance": so heisst es in Shotcut und Blender, und
        # "Style" waere doppeldeutig - Qt nennt seine Zeichensaetze fuer
        # Bedienelemente ebenfalls Style (windows11, Fusion).
        appearance_menu = setup_menu.addMenu("Theme")
        self._theme_gruppe = QActionGroup(self)
        self._theme_gruppe.setExclusive(True)
        gewaehlt = theme.gespeicherter_modus()
        for schluessel, beschriftung, tipp in (
                ("light", "Light", "The colours the program has always had."),
                ("dark", "Dark", "Dark frame around the picture, chart and timeline.")):
            eintrag = QAction(beschriftung, self, checkable=True)
            eintrag.setStatusTip(tipp)
            eintrag.setChecked(schluessel == gewaehlt)
            eintrag.triggered.connect(
                lambda _geklickt=False, s=schluessel: self._theme_waehlen(s))
            self._theme_gruppe.addAction(eintrag)
            appearance_menu.addAction(eintrag)

        # Der Schluss des Config-Menues: erst die Fensterbreite sperren,
        # dann ein Trenner, dann die beiden Resets. So stehen die Eingriffe
        # ins Fenster beieinander, und die Resets sind sichtbar abgesetzt -
        # man greift nicht versehentlich daneben.
        setup_menu.addAction(self.action_slot_kopf)
        setup_menu.addAction(self.action_lock_width)
        setup_menu.addMenu(self.gpx_leiste_menu)
        setup_menu.addSeparator()

        action_reset_layout = QAction("Reset Window Layout", self)
        action_reset_layout.setStatusTip(
            "Forget the stored window size, position and splitter position "
            "and go back to the default layout.")
        action_reset_layout.triggered.connect(self._on_reset_window_layout)
        setup_menu.addAction(action_reset_layout)

        reset_config_action = QAction("Reset Config", self)
        reset_config_action.setStatusTip("Reset your configuration like map-keys etc.")
        reset_config_action.triggered.connect(self._on_reset_config_triggered)
        setup_menu.addAction(reset_config_action)
        
        
        gpx_info_menu = menubar.addMenu("GPX-Info")

        # Lesezeichen auf GPX-Punkte. Die Eintraege je Lesezeichen entstehen
        # beim Aufklappen (aboutToShow), weil sie je Slot verschieden sind.
        # Ctrl+1..9 springen; das sind QShortcuts auf dem Fenster, nicht
        # Shortcuts der dynamischen Eintraege - die gaebe es vor dem ersten
        # Aufklappen noch nicht. 1..9 ohne Ctrl bleibt das Abspieltempo.
        self.bookmarks_menu = menubar.addMenu("Bookmarks")
        self.action_add_bookmark = QAction("Add bookmark for selected row...", self)
        self.action_add_bookmark.setShortcut(QKeySequence("Ctrl+B"))
        self.action_add_bookmark.triggered.connect(self._lesezeichen_fuer_auswahl)
        self.action_manage_bookmarks = QAction("Bookmarks...", self)
        self.action_manage_bookmarks.triggered.connect(self._lesezeichen_dialog)
        self.bookmarks_menu.aboutToShow.connect(
            lambda: self._lesezeichen_menue_fuellen(self.bookmarks_menu))
        for n in range(1, 10):
            sc = QShortcut(QKeySequence("Ctrl+%d" % n), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(lambda n=n: self._lesezeichen_nummer_anspringen(n))

        help_menu = menubar.addMenu("Help")

        docs_action = QAction("Show Documentation...", self)
        docs_action.triggered.connect(self._on_show_documentation)
        help_menu.addAction(docs_action)

        # Shortcut-Uebersicht - bis 6.12 im Edit-Menue, dort suchte sie niemand.
        self.action_show_shortcuts = QAction("Shortcuts", self)
        self.action_show_shortcuts.setStatusTip("Open a quick reference of all available shortcuts")
        self.action_show_shortcuts.triggered.connect(self._show_shortcuts_help)
        help_menu.addAction(self.action_show_shortcuts)

        tutorials_action = QAction("Youtube-Tutorials", self)
        tutorials_action.setStatusTip("Open KVRouite YouTube channel with tutorials")
        tutorials_action.triggered.connect(self._on_open_tutorials)
        help_menu.addAction(tutorials_action)

        # Der Datenschutztext steht im erzwungenen Disclaimer, den der
        # Anwender aber nur einmal je Version sieht. Ohne diesen Menuepunkt
        # waere er danach nicht mehr auffindbar.
        privacy_action = QAction("Privacy", self)
        privacy_action.setStatusTip("What KVRouite sends over the network, and when")
        privacy_action.triggered.connect(self._on_show_privacy)
        help_menu.addAction(privacy_action)
        
        #updatecheck
        # --- Updates (GitHub Releases) ---
        self.action_check_updates = QAction("Check for Updates", self)
        self.action_check_updates.setStatusTip("Check GitHub releases for newer versions")
        #self.action_check_updates.triggered.connect(self._kickoff_update_check)
        #self.action_check_updates.triggered.connect(self._check_updates_interactive)
        self.action_check_updates.triggered.connect(lambda: (setattr(self, "_updates_manual", True), self._kickoff_update_check()))
        help_menu.addAction(self.action_check_updates)

        self.action_auto_update_check = QAction("Auto Check for Updates", self, checkable=True)
        self.action_auto_update_check.setStatusTip("Check for updates on startup")
        s = QSettings("KVRouite","KVRouite")
        auto_on = s.value("updates/auto_check", True, type=bool)
        self.action_auto_update_check.setChecked(bool(auto_on))
        self.action_auto_update_check.toggled.connect(
            lambda on: QSettings("KVRouite","KVRouite").setValue("updates/auto_check", bool(on))
        )
        help_menu.addAction(self.action_auto_update_check)

        # Default-Repo fest verdrahten (einmalig setzen, wenn leer)
        if not s.value("updates/repo", None, type=str):
            s.setValue("updates/repo", "ridewithoutstomach/KVRouite")

        # Auto-Check einige Sekunden nach Start
        if self.action_auto_update_check.isChecked():
            QTimer.singleShot(4000, self._kickoff_update_check)

        #updatecheck

        copyright_action = help_menu.addAction("Copyright + License")
        copyright_action.triggered.connect(self._show_copyright_dialog)
        
        self.action_global_time.setChecked(True)
        time_submenu.addAction(self.action_global_time)
        time_submenu.addAction(self.action_final_time)

        self.action_global_time.triggered.connect(self._on_timer_mode_changed)
        self.action_final_time.triggered.connect(self._on_timer_mode_changed)
        self._time_mode = "global"


        self._load_player_settings()

        # Breiten-Sperre erst anwenden, wenn das Layout fertig aufgebaut ist.
        QTimer.singleShot(0, self._apply_width_lock)

        
        # ========================= Zentrales Layout =========================
        #
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Seit 6.02 liegt die Oberflaeche in drei Zeilen uebereinander statt in
        # zwei Spalten nebeneinander: oben Video und Karte, in der Mitte die
        # Timeline ueber die ganze Fensterbreite, unten Chart und GPX-Tabelle.
        # Deshalb ist das Haupt-Layout senkrecht.
        main_v_layout = QVBoxLayout(central_widget)
        main_v_layout.setContentsMargins(0, 0, 0, 0)
        main_v_layout.setSpacing(0)

        # Das Geruest der drei Zeilen wird ZUERST fertig ineinander gesteckt -
        # erst danach entsteht irgendein Inhalt. Jedes Widget haengt damit ab
        # seiner Erzeugung an seinem endgueltigen Platz und wird nie umgehaengt.
        #
        # Das ist keine Kosmetik: die Karte ist eine QWebEngineView, die schon
        # im Konstruktor zu laden beginnt. Haengt man sie - oder einen Splitter
        # ueber ihr - spaeter um, wird ihr natives Fenster dabei neu erzeugt.
        # Deshalb bekommen auch die beiden Zeilen-Splitter sofort ihren Platz
        # im Haupt-Splitter und nicht erst am Ende des Layoutblocks.
        #
        # setChildrenCollapsible(False): sonst laesst sich die Timeline mit dem
        # Griff auf null ziehen und ist danach nicht wiederzufinden.
        self._main_splitter = QSplitter(Qt.Vertical, central_widget)
        self._main_splitter.setChildrenCollapsible(False)
        main_v_layout.addWidget(self._main_splitter)

        self._top_splitter = QSplitter(Qt.Horizontal)       # Video | Karte
        self._main_splitter.addWidget(self._top_splitter)

        # Die Timeline gehoert zwischen die beiden Zeilen, muss also vor dem
        # unteren Splitter eingehaengt werden. Sie rechnet durchgehend mit
        # self.width(); der Umzug ueber die volle Breite macht sie damit von
        # allein feiner aufloesend - aus rund 920 px werden gut 1900.
        self.timeline = VideoTimelineWidget()
        # Feste Hoehe, nicht nur ein Minimum: seit dem Bildstreifen haengt die
        # Groesse der Vorschaubilder an der Hoehe der Zeile. Zoege man sie auf
        # 300 px, muesste fuer jede Aenderung alles neu geholt werden, und die
        # Bilder waeren riesig. Oben und unten laesst sich weiterhin ziehen.
        self.timeline.setFixedHeight(self._TIMELINE_START_H)
        self._main_splitter.addWidget(self.timeline)

        self._bottom_splitter = QSplitter(Qt.Horizontal)    # Chart | GPX-Tabelle
        self._main_splitter.addWidget(self._bottom_splitter)

        # Die vier Fenster ("Slots"). Sie bleiben immer an ihrem Platz -
        # gewechselt wird nur, welches Modul darin liegt. Auch sie gehoeren
        # zum Geruest und stehen deshalb vor jedem Inhalt.
        self._slots = {}
        for slot_id, splitter in (("ol", self._top_splitter),
                                  ("or", self._top_splitter),
                                  ("ul", self._bottom_splitter),
                                  ("ur", self._bottom_splitter)):
            slot = SlotWidget(slot_id, parent=splitter)
            splitter.addWidget(slot)
            slot.modulGewuenscht.connect(self._modul_wechseln)
            self._slots[slot_id] = slot

        # Wohin ein Modul kommt, das gerade nirgends angezeigt wird. Ohne
        # diesen Halter waere es nach setParent(None) ein eigenes Fenster.
        self._modul_reserve = QWidget(self)
        self._modul_reserve.hide()
        QVBoxLayout(self._modul_reserve).setContentsMargins(0, 0, 0, 0)

        #
        # ============== Oben rechts: Video mit eigener Bedienleiste =============
        #
        # Video-Bereich. Vater ist gleich die Buehne seines Slots - so wird
        # beim Einsetzen nichts umgehaengt.
        self.video_area_widget = QWidget(self._slots["or"].buehne())
        video_area_layout = QVBoxLayout(self.video_area_widget)
        video_area_layout.setContentsMargins(0, 0, 0, 0)
        video_area_layout.setSpacing(0)
    
        # 1) Videobild - nimmt allen Platz, den die Bedienleiste uebrig laesst
        self.video_editor = VideoEditorWidget()
        if hasattr(self, "action_toggle_360"):
            self.action_toggle_360.setChecked(bool(getattr(self.video_editor, "_is_360_mode", False)))

        # Blenden fuer die Vorschau werden im Hintergrund vorgerendert.
        self._fade_jobs = {}
        self._fade_dialog = None
        self._fade_renderer = FadeRenderer(self)
        self._fade_renderer.progress.connect(self._on_fades_progress)
        self._fade_renderer.meldung.connect(self._on_fades_meldung)
        self._fade_renderer.finished.connect(self._on_fades_ready)

            
            
        
        video_area_layout.addWidget(self.video_editor, stretch=1)

        # 2) Die Bedienleiste gehoert zum Player und sitzt deshalb direkt unter
        #    dem Bild. Zieht das Video spaeter in einen anderen Slot, wandert
        #    seine Bedienung mit - sie zeigt sonst ins Leere. stretch=0: die
        #    Leiste behaelt ihre Wunschhoehe, alles andere bekommt das Bild.
        self.video_control = VideoControlWidget()
        video_area_layout.addWidget(self.video_control, stretch=0)

        # 3) Die Timeline steht nicht mehr neben dem Video, sondern bekommt
        #    weiter unten eine eigene Zeile ueber die ganze Fensterbreite.
        #    Sie rechnet durchgehend mit self.width(), der Umzug allein macht
        #    sie also feiner aufloesend - aus rund 920 px werden gut 1900.
        self.timeline.overlayRemoveRequested.connect(self._on_timeline_overlay_remove)
        self.timeline.overlayMoveRequested.connect(self._on_overlay_move)
        self.timeline.overlayMenuRequested.connect(self._on_overlay_menu)
        self.timeline.overlayDeleteRequested.connect(self._on_overlay_delete)
        # Wo ein Overlay liegen darf, weiss der OverlayManager: es muss in EIN
        # Keep-Segment passen und den Platz der Blenden freilassen.
        self.timeline.overlay_grenzen_geber = self._overlay_grenzen
        self.timeline.cutHardToggleRequested.connect(self._on_cut_hard_toggle)
        self.timeline.cutMenuRequested.connect(self._on_cut_menu)
        self.timeline.nahtMenuRequested.connect(self._on_naht_menu)
        self.timeline.sprechstelleMenuRequested.connect(self._on_sprechstelle_menu)
        self.timeline.ansichtGewechselt.connect(self._timeline_ansicht_gewechselt)
        self.timeline.cutMoveRequested.connect(self._on_cut_move)
        # Entf auf einem ausgewaehlten Schnitt geht denselben Weg wie der
        # Menuepunkt "Undo Cut" - mit denselben Pruefungen und derselben
        # Rueckfrage. Die Taste ist nur ein zweiter Zugang dorthin.
        self.timeline.cutDeleteRequested.connect(self._schnitt_zuruecknehmen)
        # Zwei Auskuenfte, die nur hier zu geben sind: in welchem Bereich ein
        # Schnitt liegen darf und ob er ueberhaupt umziehen darf. Die
        # Zeitleiste holt sie sich darueber, statt die Bedingungen ein zweites
        # Mal zu fuehren - siehe die Erlaeuterung dort.
        self.timeline.grenzen_geber = self._verschiebe_grenzen
        self.timeline.umzug_pruefer = self._verschieben_moeglich

        # ---- Bildstreifen in der Zeitleiste --------------------------------
        # Die Bilder werden im Hintergrund geholt (core/thumb_cache.py). Beim
        # Zoomen und Schieben aendern sich die Zeitpunkte; nachgeladen wird
        # aber erst, wenn die Bewegung steht - sonst rappelt die Platte bei
        # jeder Radbewegung.
        self._thumbs = ThumbCache(self)
        self._thumbs.bilderBereit.connect(self._thumbs_anzeigen)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(400)
        self._thumb_timer.timeout.connect(self._thumbs_nachladen)
        self.timeline.ansichtGeaendert.connect(self.thumbs_anstossen)
        # Gemerkte Ansicht der Zeitleiste herstellen (Knopf links oben).
        # Aeltere Einstellungen kennen nur "Thumbnails an/aus".
        s = QSettings("KVRouite", "KVRouite")
        ansicht = s.value(self._TIMELINE_ANSICHT_KEY, "", type=str)
        if not ansicht:
            ansicht = "video" if s.value(self._THUMBS_KEY, False, type=bool) else "off"
        # Die Ton-Ansicht (Pegel ueber GStreamer) gibt es auch in Lite.
        self.timeline.audio_moeglich(True)
        self.timeline.ansicht_setzen(ansicht, melden=False)
        self._timeline_ansicht_gewechselt(self.timeline.ansicht())

        # 4) Der ehemalige Mini-Chart ist ab 6.02 der "Chart-Flow" und als
        #    vollwertiges Modul waehlbar. Er bleibt bewusst ein eigenes
        #    Diagramm und kein gezoomter grosser Chart: seine Hoehenachse
        #    skaliert nur ueber die sichtbaren Punkte, deshalb fuellt jede
        #    Kuppe das Bild. Der grosse Chart skaliert ueber den ganzen
        #    Track - dort ist dieselbe Kuppe eine flache Linie.
        #    Nebenbei behalten so alle rund 60 vorhandenen Aufrufstellen
        #    (set_gpx_data / set_current_index) ihre Wirkung.
        self.mini_chart_widget = MiniChartWidget(self._modul_reserve)

        # ============== Karte (Start: oben links) ==============
        #
        # Vater direkt mitgeben, nicht nachtraeglich umhaengen (siehe oben).
        self.map_widget = MapWidget(mainwindow=self, parent=self._slots["ol"].buehne())

        # ============== Chart (Start: unten links) ==============
        #
        self.chart = ChartWidget(self._slots["ul"].buehne())

        # Der Chart-Flow ist der Mini-Chart von oben - er steht schon bereit.
        self.chart_flow = self.mini_chart_widget
        # Die Einblendung im Videobild bekommt Daten und Index vom Modul -
        # so bleiben die rund 60 vorhandenen Aufrufstellen unveraendert.
        self.mini_chart_widget.set_zwilling(self.video_editor.hoehen_overlay)

        # ============== GPX-Leiste + Tabelle (Start: unten rechts) ==============
        #
        # Buttonleiste und Tabelle bleiben zusammen - die Leiste bearbeitet
        # ausschliesslich GPX-Daten und gehoert damit zur Tabelle.
        self.bottom_right_widget = QWidget(self._slots["ur"].buehne())
        self.bottom_right_layout = QVBoxLayout(self.bottom_right_widget)
        self.bottom_right_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_right_layout.setSpacing(0)
        
        self.gpx_control = GPXControlWidget()
        self.gpx_control.set_mainwindow(self)
        # Die GPX-Leiste kommt UNTER die Tabelle - genau wie die Player-
        # Leiste unter das Videobild. Das haelt oben Platz frei, wo sonst
        # der Schwebeknopf den "..."-Button verdeckt hat.
        # Eingehaengt wird sie weiter unten, nach der Tabelle.
        
        undo_action.triggered.connect(self.on_global_undo)
        
        self.gpx_widget = GPXWidget()
        self.gpx_widget.gpx_list.rowSelected.connect(self._on_gpx_row_selected)
        
          
        
        
        #self.statusBar().showMessage("Ready")
        
        #menueinträge aktivieren:
        
        action_gpx_summary = QAction("GPX Summary", self)
        action_gpx_summary.setStatusTip("Show full GPX summary with stats and elevation info.")
        gpx_info_menu.addAction(action_gpx_summary)
        action_gpx_summary.triggered.connect(self.gpx_control.on_show_gpx_summary)
        
        
        action_maxslope = QAction("Show Max Slope", self)
        action_maxslope.setToolTip("Displays the GPX Point with the max Slope")
        gpx_info_menu.addAction(action_maxslope)
        action_maxslope.triggered.connect(self.gpx_control.showMaxSlopeClicked.emit)
        action_maxslope.setStatusTip("Show the GPX-Point with the maximum Slope")
        
        
        action_minslope = QAction("Show Min Slope", self)
        gpx_info_menu.addAction(action_minslope)
        action_minslope.triggered.connect(self.gpx_control.showMinSlopeClicked.emit)
        action_minslope.setStatusTip("Show the GPX-Point with the minimum Slope")
        
        action_maxspeed = QAction("Show Max Speed", self)
        gpx_info_menu.addAction(action_maxspeed)
        action_maxspeed.triggered.connect(self.gpx_control.maxSpeedClicked.emit)
        action_maxspeed.setStatusTip("Show the GPX-Point with the highest Speed")
        
        action_minspeed = QAction("Show Min Speed", self)
        gpx_info_menu.addAction(action_minspeed)
        action_minspeed.triggered.connect(self.gpx_control.minSpeedClicked.emit)
        action_minspeed.setStatusTip("Show the GPX-Point withe the lowest Speed")
        
                
        action_avgspeed = QAction("Show Average Speed", self)
        gpx_info_menu.addAction(action_avgspeed)
        action_avgspeed.triggered.connect(self.gpx_control.on_show_average_speed_info)
        action_avgspeed.setStatusTip("Show average speed for current GPX selection.")
        
        if FIT_BUILD:
            export_fit = QAction("Export to Fit Immersion", self)
            gpx_info_menu.addAction(export_fit)
            export_fit.triggered.connect(self.gpx_control.export_fit_immersion)

        
        self.bottom_right_layout.addWidget(self.gpx_widget, stretch=5)
        self.bottom_right_layout.addWidget(self.gpx_control, stretch=0)

        #
        # ============== Module in die Fenster setzen ==============
        #
        # Alles, was sich umschalten laesst, steht hier an einer Stelle. Das
        # Video ist bewusst NICHT dabei: es bleibt immer in der oberen Zeile
        # und wechselt nur die Seite (View-Menue). Ein Zeilenwechsel wuerde
        # sein natives Fenster neu erzeugen und das Bild kosten.
        # ============== Karte mit Platz fuer die GPX-Leiste ==============
        #
        # Die Karte lag bisher nackt im Slot. Seit 6.13 kann die GPX-Leiste
        # wahlweise unter der Karte stehen (Config > "GPX buttons under Map"),
        # deshalb bekommt sie denselben Container wie die Tabelle: Karte
        # oben, darunter Platz fuer die Leiste. Das Modul "map" ist jetzt
        # dieser Container; der Modultausch merkt davon nichts.
        self.map_area_widget = QWidget(self._slots["ol"].buehne())
        self.map_area_layout = QVBoxLayout(self.map_area_widget)
        self.map_area_layout.setContentsMargins(0, 0, 0, 0)
        self.map_area_layout.setSpacing(0)
        self.map_area_layout.addWidget(self.map_widget, stretch=1)

        # Audio Zoom (ab 7.0): Pegelverlauf um die Abspielposition mit den
        # Sprechstellen, zum Nachbessern. Ein Modul wie der Chart-Flow -
        # zum Start verdeckt, waehlbar in jedem umschaltbaren Fenster.
        self.audio_zoom = AudioZoomWidget(self._modul_reserve)
        self.audio_zoom.bandEntfernen.connect(self._sprechstelle_entfernen)
        self.audio_zoom.bandAnlegen.connect(self._sprechstelle_anlegen)
        self.audio_zoom.zeitGewaehlt.connect(self._on_timeline_marker_moved)

        self._module = {
            "map":   ("Map",         self.map_area_widget),
            "chart": ("Chart",       self.chart),
            "flow":  ("Chart-Flow",  self.chart_flow),
            "gpx":   ("GPX Table", self.bottom_right_widget),
        }
        # Der Audio Zoom dient den Sprechstellen - ohne Voice-Zusatz gibt es
        # das Modul nicht. Die Ton-Ansicht der Zeitleiste dagegen ist reines
        # GStreamer und bleibt auch in Lite.
        if stimme.verfuegbar()[0]:
            self._module["audio"] = ("Audio Zoom", self.audio_zoom)
        self._slots["or"].inhalt_setzen("video", self.video_area_widget, "Video")
        self._slots["ol"].inhalt_setzen("map", self.map_area_widget, "Map")
        self._slots["ul"].inhalt_setzen("chart", self.chart, "Chart")
        self._slots["ur"].inhalt_setzen("gpx", self.bottom_right_widget, "GPX Table")
        # Die GPX-Leiste an den gemerkten Ort haengen.
        self._gpx_leiste_anwenden(self._gpx_leiste_ort_gespeichert())
        # Fenstergroesse aendert sich -> schwebende Leiste im Fenster halten.
        self.centralWidget().installEventFilter(self)
        # Vier Module auf drei waehlbare Fenster - eines ist immer verdeckt.
        # Zum Start ist das der Chart-Flow.
        self._auswahllisten_auffrischen()
        # Gemerkte Belegung darueberlegen - VOR dem Anzeigen, solange es
        # noch kein natives Fenster gibt, das ein Umhaengen kosten koennte.
        # Die Splittergroessen kommen spaeter in showEvent; sie gelten fuer
        # Positionen, nicht fuer Module, und passen deshalb auf jede Belegung.
        self._modulbelegung_wiederherstellen()
        self._kopfzeilen_anwenden(self.action_slot_kopf.isChecked())
        # Gemerkten Zustand der Video-Einblendung herstellen.
        self.video_editor.overlayPositionGeaendert.connect(
            self._overlay_position_gemerkt)
        _s = QSettings("KVRouite", "KVRouite")
        _pos = _s.value(self._OVERLAY_POS_KEY, "", type=str)
        if _pos and ";" in _pos:
            try:
                _rx, _ry = (float(t) for t in _pos.split(";", 1))
                self.video_editor.set_overlay_position(_rx, _ry)
            except ValueError:
                pass
        self.video_editor.hoehen_overlay_zeigen(
            self.action_hoehen_overlay.isChecked())

        # ============== Aufteilung der fertigen Zeilen ==============
        #
        # Geruest und Inhalte haengen bereits - hier steht nur noch, wie sich
        # der Platz verteilt.
        self._top_splitter.setStretchFactor(0, 1)
        self._top_splitter.setStretchFactor(1, 1)
        self._bottom_splitter.setStretchFactor(0, 1)
        self._bottom_splitter.setStretchFactor(1, 1)
        # Die Timeline behaelt ihre Hoehe, oben und unten teilen sich den Rest.
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)
        self._main_splitter.setStretchFactor(2, 1)
        
        
        
        
        
    
        #   Layout Ende
        ################################################################
        
        
        
        
        # ==    ============ Signale / z.B. chart, gpx_widget, etc. ==============
               
        #
        self.chart.markerClicked.connect(self._on_chart_marker_clicked)
        self.chart.set_gpx_data([])
        s = QSettings("KVRouite", "KVRouite")
        speed_cap = s.value("chart/speedCap", 70.0, type=float)
        self.chart.set_speed_cap(speed_cap)
        
        self.chart.raiseTrackRequested.connect(self._on_raise_track_above_sea)
        
        # GpxControl -> GpxList
        self.gpx_widget.gpx_list.markBSet.connect(self._on_markB_in_list)
        self.gpx_widget.gpx_list.markESet.connect(self._on_markE_in_list)
        self.gpx_widget.gpx_list.markRangeCleared.connect(self._on_clear_in_list)
        
        self.gpx_widget.gpx_list.markBSet.connect(self.gpx_control.highlight_markB_button)
        self.gpx_widget.gpx_list.markESet.connect(self.gpx_control.highlight_markE_button)

        # Wenn markRangeCleared (z.B. durch Deselect, Delete, Undo usw.) auftritt:
        self.gpx_widget.gpx_list.markRangeCleared.connect(self.gpx_control.reset_mark_buttons)
        
        self.gpx_control.cutClicked.connect(self.gpx_control.on_cut_range_clicked)
        self.gpx_control.removeClicked.connect(self.gpx_control.on_remove_range_clicked)
        
                # --- GPX-List -> Chart: Sync-Range als graues Overlay  ---
        self._marked_B = None
        self._marked_E = None

        def _sync_update():
            if self._marked_B is not None and self._marked_E is not None:
                self.chart.set_sync_range(self._marked_B, self._marked_E)
            else:
                self.chart.clear_sync_range()

        def _on_markB(idx: int):
            self._marked_B = idx
            _sync_update()

        def _on_markE(idx: int):
            self._marked_E = idx
            _sync_update()

        def _on_clear():
            self._marked_B = None
            self._marked_E = None
            _sync_update()

        self.gpx_widget.gpx_list.markBSet.connect(_on_markB)
        self.gpx_widget.gpx_list.markESet.connect(_on_markE)
        self.gpx_widget.gpx_list.markRangeCleared.connect(_on_clear)

            
        
        
        self.gpx_control.set_mainwindow(self)
        
        self.gpx_control.deleteWayErrorsClicked.connect(self.gpx_control.on_delete_way_errors_clicked)
        self.gpx_control.deleteTimeErrorsClicked.connect(self.gpx_control.on_delete_time_errors_clicked)
        self.gpx_control.closeGapsClicked.connect(self.gpx_control.on_close_gaps_clicked)
        self.gpx_control.minSpeedClicked.connect(self.gpx_control.on_min_speed_clicked)
        self.gpx_control.maxSpeedClicked.connect(self.gpx_control.on_max_speed_clicked)
        self.gpx_control.averageSpeedClicked.connect(self.gpx_control.on_average_speed_clicked)
        self.gpx_control.showMinSlopeClicked.connect(self.gpx_control._on_show_min_slope)
        self.gpx_control.showMaxSlopeClicked.connect(self.gpx_control._on_show_max_slope)







        
        
        # Ende Zentrales Layout
        ####################################################################################

        #
        # ============== StepManager, CutManager, EndManager, ... ==============
        #
        
        
        self.gpx_widget.gpx_list.rowClickedInPause.connect(self.on_user_selected_index)
        self.gpx_widget.gpx_list.contextMenuRequested.connect(self._lesezeichen_kontextmenue)
        self.map_widget.contextMenuRequested.connect(self._lesezeichen_kontextmenue)
        self.map_widget.pointClickedInPause.connect(self._on_map_pause_clicked)
        
        self.step_manager = StepManager(self.video_editor)
        self.step_manager.set_mainwindow(self)

        self.video_control.play_pause_clicked.connect(self.on_play_pause)
        self.video_control.stop_clicked.connect(self.on_stop)
        self.video_control.goto_video_end_clicked.connect(self.on_goto_video_end_clicked)
        self.video_control.step_value_changed.connect(self.on_step_mode_changed)
        self.video_control.multiplier_value_changed.connect(self.on_multiplier_changed)
        self.video_control.backward_clicked.connect(self.step_manager.step_backward)
        self.video_control.forward_clicked.connect(self.step_manager.step_forward)
        
        self.video_control.overlayClicked.connect(self._on_overlay_button_clicked)
       
        self.cut_manager = VideoCutManager(self.video_editor, self.timeline, self)
        self._overlay_manager = OverlayManager(self.timeline, self)
        # Overlays sofort in der Vorschau zeigen, wenn eines dazukommt,
        # verschwindet oder geaendert wird. Sie werden nicht vorgerendert
        # wie die Blenden, sondern live auf die oberste Ebene gelegt -
        # es fehlte nur der Anstoss, dass sich etwas geaendert hat.
        self._overlay_manager.overlaysChanged.connect(self._overlays_an_vorschau)
        self._overlay_manager.overlaysChanged.connect(
            self._overlay_blenden_an_timeline)
        # Overlay-Aenderungen landen im selben Strg+Z wie Schnitte und GPX.
        self._overlay_manager.vorAenderung.connect(self._overlay_undo_merken)
        
        
        self.end_manager = EndManager(
            video_editor=self.video_editor,
            timeline=self.timeline,
            cut_manager=self.cut_manager,  # <-- NEU
            mainwindow=self,
            parent=self
        )

        self.video_control.goToEndClicked.connect(self.end_manager.go_to_end)
        self.video_control.markBClicked.connect(self.cut_manager.on_markB_clicked)
        self.video_control.markEClicked.connect(self.cut_manager.on_markE_clicked)
        self.video_control.cutClicked.connect(self.on_cut_clicked_video)
        # Seite A des Video-Controls (Sprechstellen, ab 7.0).
        self.video_control.voiceClicked.connect(self._on_voice_button_clicked)
        self.video_control.findVoicesClicked.connect(self._on_find_voices_clicked)
        self.video_control.sensitivityChanged.connect(self._on_sensitivity_changed)
        self.video_control.seiteGewechselt.connect(self.timeline.set_bearbeitung)
        self.video_control.set_sensitivity(QSettings("KVRouite", "KVRouite").value(
            sprache.EINSTELLUNG_KEY, sprache.EMPFINDLICHKEIT_VORGABE, type=int))
        self.video_control.gotoNextEditRequested.connect(self._on_goto_next_edit_requested)
        self.video_control.gotoPrevEditRequested.connect(self._on_goto_prev_edit_requested)
        
        self.video_control.markClearClicked.connect(self.cut_manager.on_markClear_clicked)
        self.cut_manager.cutsChanged.connect(self._on_cuts_changed)
        self.step_manager.set_cut_manager(self.cut_manager)
        self.video_control.syncClicked.connect(self.on_sync_clicked)
        self.video_control.setSyncClicked.connect(self.on_set_video_gpx_sync_clicked)
        
        self.gpx_control.markBClicked.connect(self.on_markB_clicked_gpx)
        self.gpx_control.deselectClicked.connect(self.on_deselect_clicked)
        
        self.video_control.markBClicked.connect(self.on_markB_clicked_video)
        self.video_control.markEClicked.connect(self._on_markE_from_video)
        self.gpx_control.markEClicked.connect(self._on_markE_from_gpx)
        self.video_control.markClearClicked.connect(self.on_deselect_clicked)
        
        # Geschwindigkeiten / Rate

        # Video-Abspiel-Ende
        self.video_editor.play_ended.connect(self.on_play_ended)

        # Marker Timer
        self.marker_timer = QTimer(self)
        self.marker_timer.timeout.connect(self.update_timeline_marker)
        self.marker_timer.start(200)

        self.timeline.markerMoved.connect(self._on_timeline_marker_moved)

        # Drossel fuer den Marker-Zug, siehe _on_timeline_marker_moved().
        self._marker_zug_timer = QTimer(self)
        self._marker_zug_timer.setSingleShot(True)
        self._marker_zug_timer.timeout.connect(self._marker_zug_abgelaufen)
        self._marker_zug_offen = None
        self.video_control.timeHMSSetClicked.connect(self.on_time_hms_set_clicked)
        
        self.gpx_widget.gpx_list.rowClickedInPause.connect(self._on_gpx_list_pause_clicked)
        self.map_widget.pointClickedInPause.connect(self._on_map_pause_clicked)
        
        self.gpx_control.chTimeClicked.connect(self.gpx_control.on_chTime_clicked_gpx)
        self.gpx_control.chEleClicked.connect(self.gpx_control.on_chEle_clicked)
        self.gpx_control.chPercentClicked.connect(self.gpx_control.on_chPercent_clicked)
        
        self.gpx_control.smoothClicked.connect(self.gpx_control.on_smooth_clicked)
        self.video_control.set_beginClicked.connect(self.on_set_begin_clicked)
        
        edit_on = is_edit_video_enabled()
        cut_on = edit_on and (not self.gpx_widget.gpx_list._gpx_data or is_gpx_video_shift_set())
        self.video_control.set_editing_mode(edit_on,cut_on)
        self.map_widget.view.loadFinished.connect(self._on_map_page_loaded)
        self.video_editor.set_final_time_callback(self._compute_final_time)
        
        self.video_editor.videosDropped.connect(self._on_videos_dropped)       # Player
        self.video_editor.overlayImBildGeaendert.connect(
            self._overlay_im_bild_geaendert)                                   # Overlay ziehen
        self.video_editor.blick360Geaendert.connect(
            self._on_blick360_geaendert)                                       # 360 schwenken
        self.gpx_widget.gpx_list.tracksDropped.connect(self._on_tracks_dropped)  # GPX-Liste
        self.map_widget.tracksDropped.connect(self._on_tracks_dropped)    
        
    
    def _on_gpx_row_selected(self, row_idx: int):
        self.map_widget.set_selected_point(row_idx)
        # Auch beim Waehlen einer Tabellenzeile soll der Chart-Flow folgen.
        if getattr(self, "mini_chart_widget", None):
            self.mini_chart_widget.set_current_index(row_idx)



    def _on_overlay_button_clicked(self):
        """
        Beim Setzen eines Overlays sicherstellen, dass am aktuellen Marker
        links und rechts mindestens 'xfade' Sekunden Abstand zu Cut-Grenzen
        bzw. Video-Start/-Ende vorhanden sind. Sonst warnen und abbrechen.
        """
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QSettings

        marker_s = self.timeline.marker_position()

        # 1) Xfade-Länge aus Encoder-Settings
        s = QSettings("KVRouite", "KVRouite")
        try:
            xfade_sec = s.value("encoder/xfade", 2, type=int)
        except Exception:
            xfade_sec = 2
        if xfade_sec is None:
            xfade_sec = 2
        if xfade_sec < 0:
            xfade_sec = 0

        # 2) Gesamt-Dauer prüfen
        total = getattr(self, "real_total_duration", 0.0)
        if total <= 0:
            QMessageBox.warning(self, "Overlay not possible",
                                "No video loaded.")
            return

        # 3) Keep-Segmente (alles, was NICHT herausgeschnitten wird)
        cut_intervals = self.cut_manager.get_cut_intervals()
        keep_intervals = self._compute_keep_intervals(cut_intervals, total)  # vorhanden
        # -> finde das Keep-Intervall, das den Marker enthält
        containing = None
        for (kst, ken) in keep_intervals:
            if kst <= marker_s <= ken:
                containing = (kst, ken)
                break

        if containing is None:
            # Marker steht in einem Cut -> dort ist Overlay grundsätzlich unzulässig
            QMessageBox.warning(
                self,
                "Overlay not possible",
                "The current position lies inside a removed (cut) section.\n"
                "Move the marker into a kept section."
            )
            return

        # 4) Abstand links/rechts zu den Segmentgrenzen
        kst, ken = containing
        left_space = marker_s - kst
        right_space = ken - marker_s

        # Wie viel Platz noetig ist, haengt an der Blende des jeweiligen
        # Schnitts - seit 6.03 kann die je Schnitt verschieden sein.
        noetig_links = self._blende_am_rand(kst)
        noetig_rechts = self._blende_am_rand(ken)

        if left_space < noetig_links or right_space < noetig_rechts:
            QMessageBox.warning(
                self,
                "Not enough space for crossfade",
                (f"You need {noetig_links:.1f}s free before and "
                 f"{noetig_rechts:.1f}s after the overlay position.\n\n"
                 f"Available: left {left_space:.2f}s, right {right_space:.2f}s.\n\n"
                 "Move the marker further away from cut boundaries, video start or end.")
            )
            return

        # 5) OK -> Overlay-Dialog öffnen
        self._overlay_manager.ask_user_for_overlay(marker_s, parent=self)
    
    
    def _on_map_directions_toggled(self, checked: bool):
        """
        Wird aufgerufen, wenn im Menü 'Map Setup -> Directions' an/aus gehakt wird.
        """
        # Nur wenn der Nutzer das Häkchen setzt (checked=True) prüfen wir den Key
        if checked:
            # Nehmen wir an, self._mapbox_key hält den entschlüsselten Mapbox-Key
            if not self._mapbox_key or not self._mapbox_key.strip():
                # => Kein gültiger Key => Warnung und Abbruch
                
                QMessageBox.warning(
                    self,
                    "Directions not available",
                    "This feature requires a valid Mapbox key.\n"
                    "Please set your Mapbox key first in the Config menu."
                )
                # Häkchen sofort zurücksetzen
                self.action_map_directions.setChecked(False)
                return

        # An dieser Stelle Key vorhanden oder Häkchen = False => fortfahren
        self._directions_enabled = checked
        if self.gpx_control:
            self.gpx_control.set_directions_mode(checked)

        # map_page.html aufrufen
        if self.map_widget and self.map_widget.view:
            page = self.map_widget.view.page()
            js_bool = "true" if checked else "false"
            code = f"setDirectionsEnabled({js_bool});"
            page.runJavaScript(code)

        print(f"[DEBUG] Directions enabled => {checked}")
        
    def _compute_final_time(self, g_s: float) -> float:
        return self.get_final_time_for_global(g_s)    
        
    def _on_show_privacy(self):
        """Zeigt denselben Datenschutztext wie der Disclaimer beim ersten Start.

        Der Wortlaut kommt aus views/disclaimer_dialog.NETWORK_HTML - bewusst
        nicht kopiert, sonst beschreiben die beiden Texte irgendwann
        verschiedene Programme.
        """
        from views.disclaimer_dialog import NETWORK_HTML

        msg = QMessageBox(self)
        msg.setWindowTitle("Privacy")
        msg.setTextFormat(Qt.RichText)
        msg.setText(NETWORK_HTML)
        msg.setTextInteractionFlags(Qt.TextBrowserInteraction
                                    | Qt.LinksAccessibleByMouse)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()


    def _on_show_documentation(self):
        # Pfad zum PDF ermitteln
        # Ueber config.finde_datei(), weil die PDF je nach Build woanders
        # liegt: unter Windows in _internal/doc, im macOS-Buendel in
        # Contents/Resources/doc.
        from config import finde_datei
        pdf_path = finde_datei("doc", "Documentation.pdf")

        if not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "Not found", f"File not found: {pdf_path}")
            return

        # => Im Standard-PDF-Reader öffnen
        

        QDesktopServices.openUrl(QUrl.fromLocalFile(pdf_path))    

    def _load_map_keys_from_settings(self):
        """
        Liest aus QSettings:
         - mapTiler/key
         - mapbox/key
        (jeweils Base64-kodiert) und schreibt sie in self._maptiler_key etc.
        """
        s = QSettings("KVRouite", "KVRouite")

        def decode(b64text):
            if not b64text:
                return ""
            try:
                return base64.b64decode(b64text.encode("utf-8")).decode("utf-8")
            except:
                return ""

        enc_mt = s.value("mapTiler/key", "", str)
        enc_mb = s.value("mapbox/key", "", str)

        self._maptiler_key = decode(enc_mt)
        self._mapbox_key   = decode(enc_mb)
    
    def _save_map_key_to_settings(self, provider: str, plain_key: str):
        """
        Speichert den Key in Base64, z. B. provider='mapTiler'|'mapbox'.
        """
        s = QSettings("KVRouite", "KVRouite")
        enc = base64.b64encode(plain_key.encode("utf-8")).decode("utf-8")

        if provider == "mapTiler":
            s.setValue("mapTiler/key", enc)
            self._maptiler_key = plain_key
        elif provider == "mapbox":
            s.setValue("mapbox/key", enc)
            self._mapbox_key = plain_key

        # Jetzt sofort updaten => an map_page.html schicken
        self._update_map_page_keys()    
    
    def _update_map_page_keys(self):
        """
        Sendet die aktuellen Keys an map_page.html.
        Dort definieren wir setMapTilerKey(...) und setMapboxKey(...).
        """
        if not self.map_widget or not self.map_widget.view:
            return

        page = self.map_widget.view.page()
        # JS-Aufrufe
        js_mt = f"setMapTilerKey('{self._maptiler_key}')"
        page.runJavaScript(js_mt)

        js_mb = f"setMapboxKey('{self._mapbox_key}')"
        page.runJavaScript(js_mb)



    def _on_set_maptiler_key(self):
        self._show_key_dialog("mapTiler", self._maptiler_key)
    
    def _on_set_mapbox_key(self):
        self._show_key_dialog("mapbox", self._mapbox_key)

    def _show_key_dialog(self, provider_name: str, current_val: str):
        """
        Generischer Dialog zum Eingeben des neuen Keys.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Set {provider_name} Key")

        vbox = QVBoxLayout(dlg)
        lbl = QLabel(f"Enter your {provider_name} key:")
        vbox.addWidget(lbl)

        edit = QLineEdit()
        edit.setText(current_val)
        vbox.addWidget(edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        vbox.addWidget(btns)

        def on_ok():
            new_key = edit.text().strip()
            self._save_map_key_to_settings(provider_name, new_key)
            dlg.accept()

        def on_cancel():
            dlg.reject()

        btns.accepted.connect(on_ok)
        btns.rejected.connect(on_cancel)

        dlg.exec()


    ###############################################################################
        
    def _on_about_keys(self):
        """
        Zeigt einen Hinweis, wozu die Keys da sind, Links zu den 
        Anbietern, Limits, etc. (Demo-Text).
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("About Map Keys")
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            "<h3>Information about Map Keys</h3>"
            "<p>You can use different satellite tile providers. "
            "Enter your own API keys for MapTiler or Mapbox. "
            "Each provider has its own usage limits and Terms of Service.</p>"
            "<ul>"
            "<li><b>MapTiler:</b> <a href='https://www.maptiler.com/'>maptiler.com</a></li>"
            "<li><b>Mapbox:</b> <a href='https://www.mapbox.com/'>mapbox.com</a></li>"
            "</ul>"
            "<p>Please ensure you comply with each provider's usage policies.</p>"
        )
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()    
        
        
    def _on_set_stop_threshold(self):
        # Aktuellen Wert holen (z.B. aus chart._stop_threshold)
        current_val = self.chart._stop_threshold
    
        
        new_val, ok = QInputDialog.getDouble(
            self,
            "Stop Threshold",
            "Mark TimeGAPS greater than X seconds:",
            current_val,
            0.1,    # minimaler Wert
            1000.0, # maximaler Wert
            1       # 1 Nachkommastelle
        )
        if not ok:
            return

        # Im ChartWidget setzen
        self.chart.set_stop_threshold(new_val)    
    
    def _on_map_page_loaded(self, ok: bool):
        """
        Wird aufgerufen, sobald deine map.html im QWebEngineView fertig geladen ist.
        Dann existieren erst die JS-Funktionen.
        """
        if not ok:
            print("[WARN] Karte konnte nicht geladen werden.")
            return
        #print("[DEBUG] Karte ist geladen ⇒ wende jetzt die Größen aus QSettings an.")
        self._apply_map_sizes_from_settings()  # ruft erst hier de    
        self._update_map_page_keys()
        # NEU: Directions-Status an JS geben
        js_bool = "true" if self._directions_enabled else "false"
        js_code = f"setDirectionsEnabled({js_bool});"
        self.map_widget.view.page().runJavaScript(js_code)

        self._map_page_loaded = True
        pending = getattr(self, "_pending_open_file", None)
        if pending:
            self._pending_open_file = None
            QTimer.singleShot(0, lambda: self.open_recent(pending))

    def open_file_when_map_ready(self, path: str):
        """Datei aus der Kommandozeile oeffnen, sobald die Karte bereit ist.

        Beim Doppelklick auf ein Projekt oder eine GPX im Explorer wurde die
        Route bisher sofort nach dem Anzeigen des Fensters gepusht - also
        bevor map_page.html geladen war und die JS-Funktionen ueberhaupt
        existierten. Die Karte blieb dadurch leer. Deshalb wird der Aufruf
        aufgeschoben, bis _on_map_page_loaded gelaufen ist.
        """
        if getattr(self, "_map_page_loaded", False):
            QTimer.singleShot(0, lambda: self.open_recent(path))
        else:
            self._pending_open_file = path

    def _apply_map_sizes_from_settings(self):
        """
        Liest aus QSettings *nur noch* "black", "red", "blue", "yellow"
        und setzt fallback=4 für black/red/blue, fallback=6 für yellow.
        Anschließend wird colorSizeMap[...] in JavaScript aktualisiert.
        """
        s = QSettings("KVRouite", "KVRouite")

        defaults = {
            "black": 4,
            "red": 4,
            "blue": 4,
            "yellow": 6
        }

        for color_name, default_size in defaults.items():
            size_val = s.value(f"mapSize/{color_name}", default_size, type=int)
            # An JS: colorSizeMap['black']=4 etc.
            js_code = f"colorSizeMap['{color_name}'] = {size_val};"
            self.map_widget.view.page().runJavaScript(js_code)

        print("[DEBUG] colorSizeMap updated in JS with QSettings (color names).")

        
    def _on_set_map_point_size(self, color_str: str):
        """
        Bekommt z.B. 'black', 'red', 'blue', 'yellow' rein.
        Fragt neuen Wert ab und speichert in QSettings => "mapSize/black" etc.
        Übergibt dann an JS => updateAllPointsByColor('black', new_val).
        """
        s = QSettings("KVRouite", "KVRouite")

        default_size = 6 if color_str == "yellow" else 4
        current_val = s.value(f"mapSize/{color_str}", default_size, type=int)

        new_val, ok = QInputDialog.getInt(
            self,
            f"Set Map Size for {color_str}",
            f"Current size = {current_val}. Enter new size (1..20):",
            current_val,
            1, 20
        )
        if not ok:
            return  # User hat abgebrochen

        # In QSettings speichern
        s.setValue(f"mapSize/{color_str}", new_val)
        s.sync()

        # Jetzt JS-Funktion anstoßen: updateAllPointsByColor("black", new_val)
        self.map_widget.view.page().runJavaScript(
            f"updateAllPointsByColor('{color_str}', {new_val});"
        )
    
        QMessageBox.information(
            self,
            "Map Size Updated",
            f"{color_str.capitalize()} points changed to size={new_val}."
        )
    
        
        
    def _on_zero_speed_action(self):
        """
        Wird aufgerufen, wenn der Nutzer im Menü "Config -> Chart-Settings -> ZeroSpeed..." klickt.
        Öffnet einen Dialog, in dem der Anwender die 'Zero-Speed-Grenze' in km/h eingeben kann.
        """
        # Aktuellen Wert holen (z.B. 1.0 km/h als Default)
        current_value = self.chart.zero_speed_threshold()

        # QInputDialog für einen float-Wert
        #   Titel: Zero Speed Threshold
        #   Label: "Enter km/h"
        #   Default-Wert: current_value
        #   Min: 0.0 / Max: 200.0 / Schrittweite: 1 Stelle nach dem Komma
        new_value, ok = self.QInputDialog.getDouble(
            self,
            "Zero Speed Threshold",
            "Enter km/h:",
            current_value,
            0.0,
            200.0,
            1
        )

        if ok:
            # Den Wert ans ChartWidget weitergeben
            self.chart.set_zero_speed_threshold(new_value)    
            self._update_gpx_overview()
        
        
    from PySide6.QtWidgets import QInputDialog

    def _on_set_limit_speed(self):
        """
        Wird aufgerufen, wenn der Menüpunkt 'Limit Speed...' angeklickt wird.
        Fragt per QInputDialog den Speed-Limit-Wert ab und wendet ihn an.
        """
        # 1) Aktuellen Wert vom Chart holen
        current_limit = self.chart._speed_cap  # Oder self.chart.get_speed_cap() falls du eine Getter-Methode hast

        # 2) QInputDialog: Eingabe eines float-Wertes
    
        new_val, ok = self.QInputDialog.getDouble(
            self,
            "Set Speed Limit",
            "Enter max. speed (km/h):",
            current_limit,
            0.0,    # min
            9999.0, # max
            1       # decimals
        )
        if not ok:
            return  # User hat abgebrochen

        # 3) Wert im ChartWidget setzen
        self.chart.set_speed_cap(new_val)

        # 4) Optional: in QSettings speichern
       
        s = QSettings("KVRouite", "KVRouite")
        s.setValue("chart/speedCap", new_val)
    
        
    def _on_show_ffmpeg_path(self):
        
        

        # Ueber path_manager, nicht direkt ueber QSettings: auf dem Mac heisst
        # der Eintrag anders, und frueher schrieb dieses Menue immer nach
        # "paths/ffmpeg" - die Suche dort las aber "paths/ffmpeg_mac".
        from path_manager import gespeicherter_ffmpeg_ordner
        path_stored = gespeicherter_ffmpeg_ordner()
        if path_stored and os.path.isdir(path_stored):
            msg = f"Currently stored FFmpeg path:\n{path_stored}"
        else:
            msg = "No FFmpeg path stored in QSettings (or path is invalid)."
        QMessageBox.information(self, "FFmpeg Path", msg)

    def _on_set_ffmpeg_path(self):
        """
        Manually pick a folder with ffmpeg.exe
        """
       

        QMessageBox.information(
            self,
            "Set FFmpeg Path",
            "Please select the folder that contains ffmpeg and ffprobe.\n"
            "e.g. C:\\ffmpeg\\bin"
        )

        folder = QFileDialog.getExistingDirectory(self, "Select FFmpeg Folder")
        if not folder:
            return
        
        # Beide Programme muessen da sein: ffmpeg schneidet, ffprobe indiziert
        # die Keyframes. Ein Ordner mit nur einem der beiden wurde frueher
        # angenommen - der Copy-Mode blieb danach trotzdem aus, ohne dass
        # jemand sagte warum.
        from path_manager import fehlende_werkzeuge_im_ordner, programmname
        fehlt = fehlende_werkzeuge_im_ordner(folder)
        if fehlt:
            QMessageBox.critical(
                self, "Invalid FFmpeg folder",
                "%s not found in:\n%s\n\n"
                "Copy mode needs %s and %s in the same folder."
                % (" and ".join(programmname(n) for n in fehlt), folder,
                   programmname("ffmpeg"), programmname("ffprobe")))
            return
    
        # store in QSettings (Name je nach System - siehe path_manager)
        from path_manager import ffmpeg_ordner_merken
        ffmpeg_ordner_merken(folder)
    
        # optionally add to PATH
        old_path = os.environ.get("PATH", "")
        new_path = folder + os.pathsep + old_path
        os.environ["PATH"] = new_path
        
        QMessageBox.information(
            self,
            "FFmpeg Path updated",
            f"FFmpeg path set to:\n{folder}\n\n"
            "Please restart the application to ensure the new setting takes effect."
        )

        
        
    def _set_edit_mode(self, new_mode: str):
        # Nach dem Wechsel die Vorschau nachziehen: Copy-Mode hat keine
        # Blenden, Encode-Mode schon.
        QTimer.singleShot(0, self._refresh_preview_timeline)
        # Ein gespeichertes Projekt kann "copy" enthalten. Ohne ffmpeg geht das
        # nicht, dann wird auf Encode ausgewichen statt in einen Modus zu
        # schalten, der beim Export scheitert.
        if new_mode == "copy" and not copy_mode_moeglich():
            print("[WARN] Copy-Mode nicht moeglich (" + copy_mode_fehlgrund()
                  + ") - schalte auf Encode-Mode.")
            new_mode = "encode"

        old_mode = self._edit_mode
        if new_mode == old_mode:
            return  # Nichts geändert
        self. off_action.setChecked(new_mode== "off")
        self.copy_action.setChecked(new_mode== "copy")
        self.encode_action.setChecked(new_mode== "encode")

        self._edit_mode = new_mode

        # Overlays nachziehen: sie gehoeren nur in den Encode-Mode. Beim
        # Wechsel nach Copy oder Off muessen sie aus der Vorschau
        # verschwinden, beim Wechsel nach Encode wieder erscheinen. In der
        # Timeline bleiben sie sichtbar, dort aber nur als leerer Rahmen -
        # man soll wissen, dass eines da ist, ohne dass es wirkt.
        QTimer.singleShot(0, self._overlays_an_vorschau)
        try:
            self.timeline.set_overlays_wirksam(new_mode == "encode")
        except Exception as exc:
            print(f"[WARN] Overlay-Markierung in der Timeline: {exc}")

        # "k" (Keyframe-Schritt) nur im Copy-Mode anbieten. Dort landet ein
        # Schnitt am naechsten Keyframe und "k" zeigt, wo das waere. Im
        # Encode-Mode sitzt jeder Schnitt auf dem gewaehlten Bild, und der
        # Keyframe-Index wird gar nicht gebaut - ein Knopf, der dann nur eine
        # Fehlermeldung bringt, gehoert nicht in die Oberflaeche.
        if new_mode == "copy":
            self.video_control.set_step_values(["s", "m", "k", "f", "c"])
        else:
            self.video_control.set_step_values(["s", "m", "f", "c"])

        if new_mode == "off" and self._autoSyncVideoEnabled:
            print("[DEBUG] EditMode=off => deaktiviere AutoCutVideo+GPX")
            self._autoSyncVideoEnabled = False
            self.action_auto_sync_video.setChecked(False)
            self._on_auto_sync_video_toggled(False)
        if new_mode == "off":
            self.video_editor.hinweis_setzen("edit", "")
            self.video_control.set_editing_mode(False, False)
            print("[DEBUG] => OFF")
            self.encoder_setup_action.setEnabled(False)
            self.video_control.show_ovl_button(False)
            self.video_control.voice_seite_anbieten(False)
            self.overlay_setup_action.setEnabled(False)
        elif new_mode == "copy":
            # Nur der Sonderfall meldet sich. Groesse und Kasten kommen aus
            # dem Video-Widget, hier steht nur noch die Farbe - sonst waeren
            # die Hinweisfelder wieder unterschiedlich gross.
            self.video_editor.hinweis_setzen("edit", "Copymode", "orange")
            cut_on= not self.gpx_widget.gpx_list._gpx_data or is_gpx_video_shift_set()
            self.video_control.set_editing_mode(True,cut_on)
            print("[DEBUG] => COPY")
            self.encoder_setup_action.setEnabled(False)
            self.video_control.show_ovl_button(False)
            self.video_control.voice_seite_anbieten(False)
            self.overlay_setup_action.setEnabled(False)
        elif new_mode == "encode":
            # Encode ist der Normalfall - dafuer braucht es keine Beschriftung
            # ueber dem Bild. Auch der Stil muss weg, sonst bliebe vom
            # dunklen Kasten ein kleiner Rest stehen.
            self.video_editor.hinweis_setzen("edit", "")

            cut_on= not self.gpx_widget.gpx_list._gpx_data or is_gpx_video_shift_set()
            self.video_control.set_editing_mode(True,cut_on)
            print("[DEBUG] => ENCODE")
            self.encoder_setup_action.setEnabled(True)
            self.video_control.show_ovl_button(True)
            # Seite A (Sprechstellen) nur mit Voice-Zusatz und eingeschaltetem
            # Voice Remover - siehe _sprechstellen_bedienung_nachziehen.
            self._sprechstellen_bedienung_nachziehen()
            self.overlay_setup_action.setEnabled(True)

        # Abfrage: nur wenn alter Modus 'off' war + neuer Modus copy/encode.
        #
        # Sie wird nur VORGEMERKT und spaeter gestellt. Beim Laden eines
        # Projekts laeuft dieser Modus-Wechsel mitten im Ladevorgang - die
        # Frage waere dann ueber dem Ladefenster aufgeploppt und gleich
        # darauf vom Blenden-Fenster ueberdeckt worden. Sie kommt jetzt zum
        # Schluss, wenn nichts anderes mehr offen ist.
        if old_mode == "off" and new_mode in ("copy", "encode"):
            self._index_question_pending = True
            QTimer.singleShot(0, self._maybe_ask_index)
        
        self._update_set_gpx2video_enabled()

    def _fps_nach_laden(self, nur_bei_abweichung=False):
        """Bildrate aus dem Material lesen und die Ausgaberate danach setzen.

        Wird nach dem Laden eines Projekts und nach der ersten Videodatei
        aufgerufen, ausserdem bei jeder weiteren Datei - dann aber nur, wenn
        deren Bildrate von der ersten abweicht (nur_bei_abweichung).

        Gesetzt wird ausschliesslich die Bildrate. Aufloesung, Container,
        Hardware, CRF, Preset, Bitrate und X-Fade bleiben unangetastet.

        Der Sinn: laeuft die Ausgabe mit der Rate der Quelle, ist jedes
        Ausgabebild genau ein Quellbild - keine Umrechnung, kein Versatz. Mit
        30 statt 30000/1001 war der Export eines 4:26-Projekts 35 ms zu lang
        und lag durchgehend ein Bild hinter dem Quellmaterial (gemessen am
        29.08.2026). Mit der Quellrate: 0 ms und 0 Bilder.
        """
        if not self.playlist:
            return
        try:
            raten, alle_gleich = framerate.liste_lesen(self.playlist)
        except Exception as exc:
            print(f"[WARN] Bildraten nicht lesbar: {exc}")
            return
        quelle = next((r for r in raten if r), None)
        if quelle is None:
            return
        if nur_bei_abweichung and alle_gleich:
            return

        s = QSettings("KVRouite", "KVRouite")
        s.setValue("encoder/fps_source", framerate.als_text(*quelle))
        gespeichert = framerate.parsen(s.value("encoder/fps", "", type=str), None)
        werte = framerate.auswahl(quelle, zusaetzlich=gespeichert)

        # Vorgeschlagen wird die Rate der Quelle.
        index = 0
        for i, w in enumerate(werte):
            if framerate.gleich(w, quelle):
                index = i
                break

        warnung = details = None
        if not alle_gleich:
            warnung = "The loaded videos do not all have the same frame rate."
            zeilen = []
            for pfad, rate in zip(self.playlist, raten):
                text = framerate.anzeige(*rate) if rate else "unknown"
                zeilen.append(f"    {os.path.basename(pfad)}   {text} fps")
            details = ("\n".join(zeilen) + "\n\n"
                       "Everything is exported at the rate you choose below, so "
                       "the files with a different rate have to be converted - "
                       "that costs accuracy. Best keep one rate throughout.")

        dlg = OutputFrameRateDialog(
            framerate.anzeige(*quelle),
            [framerate.anzeige(*w) for w in werte],
            index, warnung, details, self)
        dlg.exec()

        gewaehlt = werte[max(0, min(dlg.gewaehlt(), len(werte) - 1))]
        s.setValue("encoder/fps", framerate.als_text(*gewaehlt))
        print(f"[INFO] Quelle {framerate.anzeige(*quelle)} fps, Ausgabe "
              f"{framerate.anzeige(*gewaehlt)} fps "
              f"({framerate.als_text(*gewaehlt)})")

    def _fragen_nach_dem_laden(self):
        """Die Fragen nach dem Laden nacheinander stellen, nicht uebereinander.

        Zwei getrennt eingereihte Aufrufe reichten nicht: das erste Fenster
        laeuft mit exec() in einer eigenen Ereignisschleife, und darin wird der
        zweite Aufruf sofort abgearbeitet - die Fenster lagen uebereinander.
        """
        self._fps_nach_laden()
        self._maybe_ask_index()
        self._liste_auf_zeile_nach_laden()

    def _liste_auf_zeile_nach_laden(self):
        """Nach dem Projektladen und den Fragen: die GPX-Liste auf MarkB.

        Zwei Anlaeufe davor griffen nicht (07.09.2026): einer waehrend des
        Ladens hinter dem modalen Ladefenster, einer per Timer, der in die
        Bildraten-Frage hineinfiel. Hier ist alles vorbei, die Tabelle steht.
        Ohne Vorbedingung: select_row_in_pause() steigt aus, wenn die Liste
        das Video fuer laufend haelt - hier soll die Zeile in jedem Fall
        gezeigt werden. Die Konsolenzeilen bleiben, bis es gesehen ist.
        """
        zeile = getattr(self, "_liste_zeile_nach_laden", None)
        if zeile is None:
            return
        self._liste_zeile_nach_laden = None
        from PySide6.QtWidgets import QAbstractItemView
        gl = self.gpx_widget.gpx_list
        it = gl.table.item(zeile, 0)
        print(f"[LADEN] Liste auf B={zeile}: item={'ja' if it else 'nein'}, "
              f"rows={gl.table.rowCount()}, playing={gl._video_is_playing}, "
              f"viewport={gl.table.viewport().height()}px")
        if it is None:
            return
        gl.table.blockSignals(True)
        gl.table.setCurrentCell(zeile, 0)
        gl.table.selectRow(zeile)
        gl.table.blockSignals(False)
        gl.table.scrollToItem(it, QAbstractItemView.PositionAtCenter)
        print(f"[LADEN] Liste gescrollt: currentRow={gl.table.currentRow()}, "
              f"rowAt(0)={gl.table.rowAt(0)}, "
              f"scroll={gl.table.verticalScrollBar().value()}/"
              f"{gl.table.verticalScrollBar().maximum()}")

    def _maybe_ask_index(self):
        """
        Stellt die Indexierungsfrage - aber erst, wenn nichts anderes offen ist.

        Laeuft noch das Laden oder das Vorrendern der Blenden, passiert
        nichts; beide rufen hier am Ende erneut herein.
        """
        if not getattr(self, "_index_question_pending", False):
            return
        # Der Keyframe-Index hat genau einen Abnehmer: Step-Modus "k" im
        # step_manager, und den gibt es nur, um zu zeigen, wo COPY-Mode
        # schneiden wuerde. Der Encoder holt sich seine Keyframes selbst aus
        # merged.mp4, der Cut-Manager rastet gar nicht auf Keyframes ein.
        # Im Encode-Modus indiziert die Anwendung also fuer nichts - deshalb
        # wird dort auch nicht mehr gefragt.
        if getattr(self, "_edit_mode", "") != "copy":
            self._index_question_pending = False
            return
        if getattr(self, "_loading_project", False):
            return
        if getattr(self, "_fade_dialog", None) is not None:
            return

        self._index_question_pending = False
        answer = QMessageBox.question(
            self,
            "Index Videos?",
            "Do you want to index all currently loaded videos now?" + chr(10) +
            "(Currently loaded videos: %d)" % len(self.playlist) + chr(10) + chr(10) +
            "Any *new* video you load from now on will also be indexed automatically.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer == QMessageBox.Yes:
            for video_path in self.playlist:
                self.start_indexing_process(video_path)
        else:
            self._userDeclinedIndexing = True

    def _on_encoder_setup_clicked(self):
        # xfade vor dem Öffnen merken
        s = QSettings("KVRouite", "KVRouite")
        old_xfade = s.value("encoder/xfade", 2, type=int)

        dlg = EncoderSetupDialog(self)
        result = dlg.exec()

        # "Remove voices" koennte umgeschaltet worden sein: Seite A und die
        # Baender folgen dem Schalter.
        self._sprechstellen_bedienung_nachziehen()

        # xfade nach dem Schließen erneut lesen
        new_xfade = s.value("encoder/xfade", 2, type=int)

        if result == dlg.accepted:
            print("[DEBUG] => Encoder-Setup saved.")
        else:
            print("[DEBUG] => Encoder-Setup canceled.")

        # WICHTIG: auch bei 'canceled' prüfen, falls der Dialog Werte geschrieben hat
        if new_xfade != old_xfade:
            print(f"[DEBUG] encoder/xfade changed: {old_xfade} -> {new_xfade} (validating overlays)")
            self._validate_overlays_after_xfade_change()
            self._refresh_preview_timeline()

    
            
    def _on_overlay_setup_clicked(self):
        """Menue "Overlay Library": die Bibliothek pflegen.

        Frueher stand hier das Overlay-Setup mit drei festen Plaetzen. Die
        Bibliothek hat es abgeloest - dieselbe Stelle im Menue, aber ohne die
        Beschraenkung auf drei Bilder.
        """
        from .overlay_library_dialog import OverlayLibraryDialog
        dlg = OverlayLibraryDialog(self)
        if dlg.exec() == QDialog.Accepted:
            print("[DEBUG] => Overlay-Bibliothek: gespeichert.")
        else:
            print("[DEBUG] => Overlay-Bibliothek: abgebrochen.")
        

    def _on_clear_ffmpeg_path(self):
        """
        Removes ffmpeg path from QSettings, 
        so that next time it might auto-detect or prompt again.
        """
       
        from path_manager import ffmpeg_ordner_vergessen
        ffmpeg_ordner_vergessen()
    
        QMessageBox.information(self, "FFmpeg Path cleared",
            "The FFmpeg path has been removed from QSettings.")
            
        QMessageBox.information(
            self,
            "FFmpeg Path cleared",
            "Please restart the application to ensure the new setting takes effect."
        )    
        
            
    
    
    def on_set_begin_clicked(self):
        # get_current_position_s() liefert die GLOBALE Zeit ueber alle
        # Videos hinweg - der Versatz der vorherigen Dateien steckt also
        # schon darin. Frueher hiess die Groesse hier current_local_s und
        # der Versatz wurde ein zweites Mal addiert; ab dem zweiten Video
        # lag der Schnitt dadurch um die Laenge der vorherigen Videos zu
        # weit. Bei zwei Dateien und dem Marker in der zweiten war das
        # mehr als die Gesamtlaenge - der Schnitt nahm dann alles weg.
        # Nachgestellt am 31.08.2026 mit zwei Dateien, Marker bei 00:43:58
        # von 01:10:28: die ganze Zeitachse wurde schwarz.
        #
        # CutEnd hat den Fehler nicht, siehe EndManager.go_to_end() - dort
        # wird derselbe Wert direkt als globale Zeit genommen.
        global_video_s = self.video_editor.get_current_position_s()
        self._startschnitt_setzen(global_video_s)

    def _startschnitt_setzen(self, global_video_s, nachfragen=True):
        """Den Anfangsschnitt an einer bestimmten Stelle setzen.

        Herausgeloest aus on_set_begin_clicked(), damit das VERSCHIEBEN eines
        Startschnitts denselben Weg nehmen kann: erst zuruecknehmen, dann hier
        neu setzen. Es gibt damit keinen zweiten Rechenweg fuer den
        Startschnitt, der neben dem ersten veralten koennte.

        Der Startschnitt ist der einzige, der nicht nur Punkte entfernt: er
        setzt die ganze Zeitachse auf den alten Anfangszeitstempel zurueck und
        stellt den Video/GPX-Versatz auf 0. Beides wird aufgezeichnet, sonst
        waere er nicht umkehrbar.

        Rueckgabe False, wenn nichts geaendert wurde.
        """
        # Rueckfrage und Erfolgsmeldung entfallen beim Verschieben - dort hat
        # der Nutzer laengst entschieden, und ein Meldungsfenster mitten im
        # Umzug waere nur im Weg. Als Ersatzfunktionen statt als Verzweigung,
        # damit der Rumpf darunter Zeile fuer Zeile derselbe bleibt.
        fragen = (QMessageBox.question if nachfragen
                  else (lambda *a, **k: QMessageBox.Yes))
        melden = (QMessageBox.information if nachfragen
                  else (lambda *a, **k: None))

        if self._autoSyncVideoEnabled:
            ret = fragen(
                self,
                "Confirm Cut Begin",
                f"Cut gpx and video before {global_video_s}s?\n"
                "Press Yes to proceed, No to abort.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            ret = fragen(
                self,
                "Confirm Cut Begin",
                f"Cut video before {global_video_s}s?\n"
                "Press Yes to proceed, No to abort.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

        if ret != QMessageBox.Yes:
            return False

        if global_video_s < 0:
            global_video_s = 0.0
        print(f"[DEBUG] set_begin => global_video_s={global_video_s:.2f}")

        # Dieselbe Vorabpruefung wie beim gewoehnlichen Schnitt: der
        # Anfangsschnitt selbst hat nie eine Blende, aber er kann dem ersten
        # Schnitt dahinter den Platz nehmen.
        blende_kuerzungen = []
        if (global_video_s > 0.01
                and not getattr(self, "_verschiebe_schritt", False)):
            weiter, blende_kuerzungen = self._blenden_konflikt_fragen(
                self._cuts_mit((0.0, float(global_video_s))),
                "Placing the first cut here")
            if not weiter:
                return False
    
        # GPX-Bearbeitung nur bei AutoSync
        if self._autoSyncVideoEnabled and self._edit_mode in ("copy", "encode"):
            gpx_data = self.gpx_widget.gpx_list._gpx_data
            
            if gpx_data and len(gpx_data) >= 2:
                # Undo-Snapshots erstellen
                self.register_gpx_undo_snapshot("Set begin (video + GPX)")
                self.register_video_undo_snapshot(True, "Set begin (video + GPX)")
                    
                # Finalzeit berechnen
                final_s = self.get_final_time_for_global(global_video_s)
                
                # Basis-Datetime + Video-Shift
                base_dt = gpx_data[0].get("time", None)
                try:
                    video_shift = get_gpx_video_shift()
                    if video_shift is None:
                        video_shift = 0.0
                except Exception:
                    video_shift = 0.0
    
                if base_dt is None:
                    print("[DEBUG] on_set_begin_clicked: GPX base time missing, skipping GPX cut.")
                    return False
    
                # Gewünschte absolute GPX-Datetime für den Schnitt
                desired_cut_dt = base_dt + timedelta(seconds=(final_s - video_shift))
                print(f"[DEBUG] on_set_begin_clicked => trimming GPX at {desired_cut_dt}")
    
                # Hilfsfunktion: lineare Interpolation zwischen zwei Punkten
                def _interp_point(pt1, pt2, new_time):
                    t1 = pt1.get("time")
                    t2 = pt2.get("time")
                    if t1 is None or t2 is None or t2 == t1:
                        ratio = 0.0
                    else:
                        ratio = (new_time - t1).total_seconds() / (t2 - t1).total_seconds()
                    
                    def _val(k):
                        return pt1.get(k, 0.0) + ratio * (pt2.get(k, 0.0) - pt1.get(k, 0.0))
                    
                    new_pt = {
                        "lat": _val("lat"),
                        "lon": _val("lon"),
                        "ele": _val("ele"),
                        "time": new_time,
                        "delta_m": 0.0,
                        "speed_kmh": 0.0,
                        "gradient": 0.0
                    }
                    return new_pt
    
                # Neuen GPX-Track erstellen: alles nach desired_cut_dt behalten
                import copy as _cpy
                new_gpx = []
                n = len(gpx_data)
                i = 0
    
                # Ersten Punkt finden, der >= desired_cut_dt ist
                while i < n and gpx_data[i].get("time") < desired_cut_dt:
                    i += 1
    
                interpolierter_punkt = None
                # Wenn wir nicht genau auf einem Punkt sind, interpolieren
                if i > 0 and i < n and gpx_data[i].get("time") != desired_cut_dt:
                    prev_pt = gpx_data[i-1]
                    next_pt = gpx_data[i]
                    if prev_pt.get("time") < desired_cut_dt < next_pt.get("time"):
                        cut_pt = _interp_point(prev_pt, next_pt, desired_cut_dt)
                        new_gpx.append(cut_pt)
                        interpolierter_punkt = _cpy.deepcopy(cut_pt)
                
                # Restliche Punkte hinzufügen
                for j in range(i, n):
                    new_gpx.append(_cpy.deepcopy(gpx_data[j]))
    
                if len(new_gpx) < 2:
                    QMessageBox.warning(self, "Truncation", 
                        "After shortening to the video length, no meaningful GPX remains!")
                    return
    
                # WICHTIG: GPX-Zeiten auf 0 zurücksetzen
                # Der erste Punkt der neuen GPX sollte bei 0 Sekunden beginnen
                new_base_time = new_gpx[0]["time"]
                for pt in new_gpx:
                    # Zeit relativ zum neuen Startpunkt setzen
                    pt["time"] = pt["time"] - new_base_time + base_dt
    
                # Fuer die Ruecknahme festhalten, solange es noch da ist:
                # der weggeschnittene Kopf mit seinen Originalzeiten, um wie
                # viel die Achse gleich verschoben wird, und der
                # Video/GPX-Versatz von jetzt. gpx_data selbst bleibt dabei
                # unberuehrt - new_gpx besteht aus Kopien.
                entfernte_punkte = [_cpy.deepcopy(p) for p in gpx_data[:i]]
                achsen_versatz_s = (new_base_time - base_dt).total_seconds()
                versatz_vorher = (get_gpx_video_shift()
                                  if is_gpx_video_shift_set() else None)

                # Video-Shift komplett zurücksetzen, da GPX jetzt bei 0 beginnt
                set_gpx_video_shift(0.0)
    
                # Metriken neu berechnen
                recalc_gpx_data(new_gpx)
                self.gpx_widget.set_gpx_data(new_gpx)
                self._gpx_data = new_gpx
    
                # UI aktualisieren
                self._update_gpx_overview()
                self.chart.set_gpx_data(new_gpx)
                if self.mini_chart_widget:
                    self.mini_chart_widget.set_gpx_data(new_gpx)
                
                route_geojson = self._build_route_geojson_from_gpx(new_gpx)
                self.map_widget.loadRoute(route_geojson, do_fit=False)

                # Aufzeichnung fuer die Ruecknahme. Der Startschnitt ist der
                # einzige, der die ganze Zeitachse verschiebt und den
                # Video/GPX-Versatz zurueckstellt - beides steht deshalb mit
                # in der Aufzeichnung, sonst waere er nicht umkehrbar.
                #
                # Erst die uebrigen Aufzeichnungen nachfuehren: sie stehen im
                # alten Zeitrahmen und muessen die Neubasierung mitmachen.
                # ALLE, nicht nur die dahinter - hier wandert die ganze Achse.
                self.cut_manager.aufzeichnungen_nachfuehren(
                    None, -achsen_versatz_s, alle=True)
                self.cut_manager.aufzeichnung_merken(
                    0.0, global_video_s,
                    entfernt=entfernte_punkte,
                    verworfen=[],
                    interpoliert=interpolierter_punkt,
                    dauer_s=0.0,
                    beginn_dt=desired_cut_dt,
                    achsen_versatz_s=achsen_versatz_s,
                    video_shift_vorher=versatz_vorher,
                )
                # Bis 6.03 blieb der Fingerabdruck hier absichtlich stehen:
                # nach einem Startschnitt war jede Ruecknahme gesperrt, weil
                # die verschobene Achse sonst still falsche Ergebnisse
                # geliefert haette. Die Verschiebung wird jetzt oben
                # ausgeglichen, deshalb darf - und muss - der Abdruck nach.
                self.cut_manager.fingerabdruck_merken(self._gpx_data)
                print(f"[CUT-REC] Startschnitt 0.000-{global_video_s:.3f}: "
                      f"{len(entfernte_punkte)} entfernt, Nahtpunkt "
                      f"{'erzeugt' if interpolierter_punkt else 'keiner'}, "
                      f"Achse um {achsen_versatz_s:.3f}s verschoben, "
                      f"Spur {len(gpx_data)} -> {len(new_gpx)}")
                self._ruecknahme_probe(0.0, global_video_s, new_gpx, gpx_data)
    
        else:
            # Nur Video-Cut (kein AutoSync)
            self.register_video_undo_snapshot(False, "Set begin (video)")
    
        # Video-Cut durchführen (0 bis global_video_s)
        if global_video_s <= 0.01:
            melden(
                self, "Set Begin",
                "Video near 0s => no cut.\n"
                "GPX cut at the point.\n"
                "Undo possible."
            )
        else:
            # WICHTIG: Vorhandenen Cut am Anfang entfernen, falls vorhanden
            # Suche nach Cuts, die bei 0 beginnen
            existing_begin_cut = None
            for cut_start, cut_end in self.cut_manager._cut_intervals:
                if abs(cut_start - 0.0) < 0.001:
                    existing_begin_cut = (cut_start, cut_end)
                    break
            
            # Entferne den vorhandenen Cut am Anfang
            if existing_begin_cut:
                #self.cut_manager._cut_intervals.remove(existing_begin_cut)
                if not self._remove_interval_with_tol(self.cut_manager._cut_intervals, existing_begin_cut, tol=0.10):
                    # Fallback: wenn 'existing_begin_cut' nicht exakt passt, entferne "das Begin-Intervall",
                    # also jenes mit Start sehr nahe 0.0 (typisch für Anfangsschnitt)
                    for i, (cs, ce) in enumerate(list(self.cut_manager._cut_intervals)):
                        if cs <= 0.10:  # 100 ms Toleranz am Anfang
                            self.cut_manager._cut_intervals.pop(i)
                            break
                 # Timeline aktualisieren, indem wir alle Cuts löschen und neu hinzufügen
                self.timeline.clear_all_cuts()
                for cut in self.cut_manager._cut_intervals:
                    self.timeline.add_cut_interval(cut[0], cut[1])
            
            # Füge neuen Cut hinzu
            self.cut_manager.markB_time_s = 0.0
            self.cut_manager.markE_time_s = global_video_s
            self.timeline.set_markB_time(0.0)
            self.timeline.set_markE_time(global_video_s)
            self.cut_manager.on_cut_clicked()
            self._blenden_kuerzen(blende_kuerzungen)
    
            # Frueher stand hier ein Meldungsfenster mit "Video and GPX
            # cut at ...s". Es sagte nur, was in der Zeitleiste ohnehin
            # zu sehen ist, und musste jedes Mal weggeklickt werden.
            print(f"[DEBUG] set_begin: Schnitt bei {global_video_s:.2f}s gesetzt")
    
        print("[DEBUG] on_set_begin_clicked => done.")
        return True
        
    
    
    
                
    def on_new_gpx_point_inserted(self, lat: float, lon: float, idx: int):
        """
        Wird aufgerufen, wenn aus dem map_page.html-JavaScript
        channelObj.newPointInserted(lat, lon, idx) getriggert wurde.
        
        - lat, lon: Koordinaten des neu eingefügten Punktes
        - idx: Kann sein:
            - -3 => kein Punkt selektiert (also "vor dem ersten" GPX-Punkt)
            - -2 => Punkt VOR dem ersten
            - -1 => Punkt HINTER dem letzten
            - >=0 => Punkt zwischen idx und idx+1 (also 'zwischen zwei vorhandenen GPX-Punkten').

        NEU/ERWEITERT:
        Wenn Directions aktiviert sind (self._directions_enabled=True) und
        in der GPX-Liste aktuell der erste oder letzte Punkt selektiert ist,
        überschreiben wir das idx-Verhalten:

        1) Falls letzter Punkt selektiert => idx = -1 (Ans Ende anhängen)
        2) Falls erster Punkt selektiert  => idx = -2 (Vorne einfügen)

        Dadurch wird die Route – je nach gewähltem Startpunkt (B/E) – vorn oder hinten angefügt.
        """
        old_data = copy.deepcopy(self._gpx_data)
        self._undo_ablegen(lambda: self._restore_gpx_data(old_data), "Insert point")
        print("[UNDO] InsertPoint => alter Zustand gesichert")

        gpx_data = self._gpx_data
        row_selected = self.gpx_widget.gpx_list.table.currentRow()

        insert_pos = -1
        if self._autoSyncNewPointsWithVideoTime and self.playlist_counter > 0: #if video loaded, insert a new point at current video time without shift
            # Undo-Snapshot
            self.register_gpx_undo_snapshot("Insert point")

            video_time = self.video_editor.get_current_position_s()
            final_s = self.get_final_time_for_global(video_time)
            insert_pos = self.ordered_insert_new_point(lat,lon,final_s)

            if(self._directions_enabled and len(gpx_data) > 1):
                pt1idx = insert_pos-1 if insert_pos>0 else insert_pos
                pt2idx = insert_pos if insert_pos>0 else insert_pos+1 
                t1 = gpx_data[pt1idx]["time"]
                t2 = gpx_data[pt2idx]["time"]
                dt = (t2 - t1).total_seconds()
                if dt > 2 :
                    prof = self.map_widget._curr_mapbox_profile
                    # Ohne Dialog gilt fuer die Hoehen die zuletzt im Dialog
                    # getroffene Wahl (Haken "Get elevation from Mapbox").
                    hoehen_holen = QSettings("KVRouite", "KVRouite").value(
                        "gpx/closegaps_elevation", True, type=bool)
                    if not prof:
                        prof, hoehen_holen = self.gpx_control._ask_profile_mode()
                    if prof:
                        self.gpx_control._close_gaps_mapbox(
                            pt1idx, pt2idx, dt, prof, hoehen_holen)

        else: #insert with shift
            if idx == -3:
                QMessageBox.information(
                self,
                "No point selected",
                "No point selected ⇒ cannot insert new point."
            )
                
            # --- NEU: Falls Directions aktiv und es ist eindeutig "erster" oder "letzter" Punkt selektiert ---
            if self._directions_enabled:
                # Prüfen, welcher GPX-Punkt in der Liste selektiert ist
                n = len(gpx_data)

                if row_selected >= 0 and n > 0:
                    is_first = (row_selected == 0)
                    is_last  = (row_selected == n-1)

                    if is_last:
                        # => Wir wollen unbedingt ans Ende anfügen
                        idx = -1
                        # (markB=letzter, markE=neuer => B->E => "append")
                    elif is_first:
                        # => Vor dem ersten einfügen
                        idx = -2
                        # (markE=erster, markB=neuer => B->E => "prepend")
                    # Falls weder erster noch letzter => idx bleibt wie vom JS gesendet (z.B. -1 oder "zwischen")
        
            # --- Nun das "alte" Einfüge-Verhalten ---
            # Undo-Snapshot
            self.register_gpx_undo_snapshot("Insert point")

            now = datetime.now()  # Fallback, falls Zeit gar nicht existiert

            if idx == -2:
                # =============== Punkt VOR dem ersten einfügen ===============
                if not gpx_data:
                    # Noch gar nichts drin => erster Punkt
                    new_pt = {
                        "lat": lat,
                        "lon": lon,
                        "ele": 0.0,
                        "time": now,
                        "delta_m": 0.0,
                        "speed_kmh": 0.0,
                        "gradient": 0.0
                    }
                    gpx_data.append(new_pt)
                else:
                    t_first = gpx_data[0]["time"]
                    if not t_first:
                        t_first = now
                    # NEUEN Punkt "vorne" einfügen => 
                    # wir geben ihm dieselbe Zeit wie den alten ersten oder 1s davor
                    new_time = t_first  # oder t_first - timedelta(seconds=1)
                    new_pt = {
                        "lat": lat,
                        "lon": lon,
                        "ele": gpx_data[0].get("ele", 0.0),
                        "time": new_time,
                        "delta_m": 0.0,
                        "speed_kmh": 0.0,
                        "gradient": 0.0
                    }
                    gpx_data.insert(0, new_pt)
                    insert_pos=0
        
                    # jetzt alle nachfolgenden +1s verschieben
                    for i in range(1, len(gpx_data)):
                            oldt = gpx_data[i]["time"]
                            if oldt:
                                gpx_data[i]["time"] = oldt + timedelta(seconds=1)
                    
            elif idx == -1:
                # =============== Insert point AFTER the last one ===============
                if not gpx_data:
                    # ganz leer => erster Punkt
                    new_pt = {
                        "lat": lat,
                        "lon": lon,
                        "ele": 0.0,
                        "time": now,
                        "delta_m": 0.0,
                        "speed_kmh": 0.0,
                        "gradient": 0.0
                    }
                    gpx_data.append(new_pt)
                    insert_pos=0
                else:
                    last_pt = gpx_data[-1]
                    t_last = last_pt.get("time")
                    if not t_last:
                        t_last = now
                    new_time = t_last + timedelta(seconds=1)
                    new_pt = {
                        "lat": lat,
                        "lon": lon,
                        "ele": last_pt.get("ele", 0.0),
                        "time": new_time, 
                        "delta_m": 0.0,
                        "speed_kmh": 0.0,
                        "gradient": 0.0
                    }
                    gpx_data.append(new_pt)
                    insert_pos=len(gpx_data)-1
            else:
                # =============== Punkt "zwischen" idx..idx+1 einfügen ===============
                if idx < 0:
                    idx = 0
                if idx >= len(gpx_data):
                    idx = len(gpx_data) -1  # safety

                if not gpx_data:
                    # Falls wirklich nix da => wie "ende"
                    new_pt = {
                        "lat": lat,
                        "lon": lon,
                        "ele": 0.0,
                        "time": now,
                        "delta_m": 0.0,
                        "speed_kmh": 0.0,
                        "gradient": 0.0
                    }
                    gpx_data.append(new_pt)
                    insert_pos=0
                else:
                    base_pt = gpx_data[idx]
                    t_base = base_pt.get("time")
                    if not t_base:
                        t_base = now
                    new_time = t_base + timedelta(seconds=1)

                    new_pt = {
                        "lat": lat,
                        "lon": lon,
                        "ele": base_pt.get("ele", 0.0),
                        "time": new_time,
                        "delta_m": 0.0,
                        "speed_kmh": 0.0,
                        "gradient": 0.0
                    }
                    insert_pos = idx + 1
                    if insert_pos > len(gpx_data):
                        insert_pos = len(gpx_data)
                    gpx_data.insert(insert_pos, new_pt)

                    # alle folgenden => +1s
                    for j in range(insert_pos+1, len(gpx_data)):
                            t_old = gpx_data[j].get("time")
                            if t_old:
                                gpx_data[j]["time"] = t_old + timedelta(seconds=1)      
                                
        
        self.gpx_widget.set_gpx_data(gpx_data) #need to update gpx_widget data before update elevation
        self.gpx_control.update_elevation_from_mapbox([(insert_pos, lat, lon)])

        #  => recalc
        recalc_gpx_data(gpx_data)
        self.gpx_widget.set_gpx_data(gpx_data)
        self._gpx_data = gpx_data
        self._update_gpx_overview()
        
        # Chart, Mini-Chart usw. aktualisieren
        self.chart.set_gpx_data(gpx_data)
        if self.mini_chart_widget:
            self.mini_chart_widget.set_gpx_data(gpx_data)

        # Map neu laden
        route_geojson = self._build_route_geojson_from_gpx(gpx_data)
        self.map_widget.loadRoute(route_geojson, do_fit=False)
        

        print(f"[INFO] Inserted new GPX point (DirectionsEnabled={self._directions_enabled}); total now {len(gpx_data)} pts.")

    def _restore_gpx_data(self, gpx_snapshot):
        self._gpx_data = copy.deepcopy(gpx_snapshot)
        self.gpx_widget.set_gpx_data(self._gpx_data)
        self.chart.set_gpx_data(self._gpx_data)
        geojson = self._build_route_geojson_from_gpx(self._gpx_data)
        self.map_widget.loadRoute(geojson, do_fit=False)
        if self.mini_chart_widget:
            self.mini_chart_widget.set_gpx_data(self._gpx_data)
        self._update_gpx_overview() 
        print("[UNDO] GPX-Zustand erfolgreich wiederhergestellt")    
        row = self.gpx_widget.gpx_list.table.currentRow()
        if row >= 0:
            self.map_widget.set_selected_point(row)
            print(f"[UNDO] Punkt {row} nach Undo erneut in Map selektiert")

            
    
    # Laengste Texte, die update_info_line() je erzeugen kann (siehe die
    # Formatstrings dort). Nur zum Messen - die Labels behalten ihr normales
    # Verhalten, hier wird nichts dauerhaft reserviert.
    # ------------------------------------------------------------------
    # Fenster-Layout merken (Groesse, Position, Splitter-Teilung)
    # ------------------------------------------------------------------
    # Ohne das muss sich jeder Nutzer die Aufteilung bei jedem Start neu
    # zurechtziehen. Gespeichert wird beim Schliessen, geladen beim Start.
    # "Reset Window Layout" im Config-Menue stellt den Auslieferungszustand
    # wieder her: Standardgroesse, zentriert, Splitter 50/50.

    # Die Namen tragen seit 6.02 die Kennung der Fensteraufteilung, und zwar
    # aus einem gemessenen Grund: bis 6.01 lag EIN waagerechter Splitter im
    # Fenster (links | rechts), seit 6.02 ist es ein senkrechter mit drei
    # Reihen und zwei waagerechten darin. Beide Fassungen schrieben ihren
    # Zustand unter denselben Schluessel "ui/splitter_state". Wer abwechselnd
    # 6.01 und 6.02 startet, bekam deshalb den Zustand der jeweils anderen
    # Aufteilung auf seine eigene gelegt - das Fenster stand danach falsch,
    # und "Reset Window Layout" half nur bis zum naechsten Wechsel.
    #
    # Die alten Namen ohne "_grid" bleiben unangetastet: sie gehoeren 6.01 und
    # werden hier weder gelesen noch geschrieben. Beide Versionen duerfen
    # damit nebeneinander laufen.
    #
    # Alles andere in QSettings bleibt bewusst GEMEINSAM - Encoder-Setup,
    # Karten-Keys, ffmpeg-Pfad, Dateihistorie. Das ist derselbe Rechner und
    # dieselben Vorlieben; doppelt einrichten will sie niemand.
    _GEOMETRY_KEY = "ui/window_geometry_grid"
    _SPLITTER_KEY = "ui/splitter_state_grid"          # senkrecht: oben | Timeline | unten
    _TOP_SPLITTER_KEY = "ui/top_splitter_state_grid"       # Video | Karte
    _BOTTOM_SPLITTER_KEY = "ui/bottom_splitter_state_grid" # Chart | GPX-Tabelle
    # Welches Modul in welchem Fenster liegt, z.B. "ol:map,or:video,ul:chart,ur:gpx".
    # Bis zum 04.09.2026 wurden nur Groessen gemerkt - die Belegung fiel bei
    # jedem Start auf den Standard zurueck.
    _MODULE_LAYOUT_KEY = "ui/module_layout_grid"
    _STANDARD_BELEGUNG = {"ol": "map", "or": "video", "ul": "chart", "ur": "gpx"}

    # Hoehe der Timeline-Zeile. Die Timeline hat die Zeile seit 6.02 fuer sich
    # allein - die Bedienleiste sitzt beim Player, der Mini-Chart ist weg.
    _TIMELINE_MIN_H = 56
    _TIMELINE_START_H = 84

    def _default_window_size(self):
        """Standardgroesse wie beim allerersten Start: 16:9, 90% des Schirms.

        Dieselbe Rechnung wie in KVRouite.main(), damit "Reset Window Layout"
        wirklich dorthin zurueckfuehrt und nicht auf einen zweiten Wert.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QSize(1280, 720)
        geo = screen.availableGeometry()
        target_ratio = 16 / 9
        if geo.height() > 0 and (geo.width() / geo.height()) >= target_ratio:
            h = int(geo.height() * 0.9)
            w = int(h * target_ratio)
        else:
            w = int(geo.width() * 0.9)
            h = int(w / target_ratio)
        return QSize(w, h)

    def apply_saved_window_geometry(self) -> bool:
        """Gespeicherte Fenstergroesse/-position setzen.

        Rueckgabe True, wenn etwas geladen wurde. Nur dann darf der Aufrufer
        das Zentrieren ueberspringen - sonst bliebe das alte Startverhalten
        (Standardgroesse, mittig) nicht erhalten.
        """
        data = QSettings("KVRouite", "KVRouite").value(
            self._GEOMETRY_KEY, None, type=QByteArray)
        if data is None or data.isEmpty():
            return False
        return bool(self.restoreGeometry(data))

    # ------------------------------------------------------------------
    # Module in den Fenstern tauschen
    # ------------------------------------------------------------------
    def _auswahllisten_auffrischen(self):
        """Jedem umschaltbaren Fenster sagen, was es anbieten darf.

        Das Video-Fenster bekommt keine Liste - dort wechselt man ueber das
        View-Menue nur die Seite.
        """
        eintraege = [(mid, name) for mid, (name, _w) in self._module.items()]
        for slot_id, slot in self._slots.items():
            if self._zeile_von_slot(slot_id) == "oben":
                # Oben steht Video zusaetzlich zur Wahl - dort ist es nur ein
                # Seitenwechsel. Nach unten kann es nicht, siehe _modul_wechseln.
                slot.auswahl_setzen([("video", "Video")] + eintraege)
            else:
                slot.auswahl_setzen(eintraege)

    def _zeile_von_slot(self, slot_id: str) -> str:
        return "oben" if slot_id in ("ol", "or") else "unten"

    def _modul_wechseln(self, slot_id: str, modul_id: str):
        """Modul in ein Fenster holen.

        Liegt es schon in einem anderen Fenster, tauschen die beiden ihre
        Inhalte. Liegt es in der Reserve, wandert der bisherige Inhalt des
        Ziels dorthin.

        Das Video ist der Sonderfall: es bleibt immer in der oberen Zeile und
        wechselt dort nur die Seite. Soll in seinem Fenster etwas anderes
        stehen, weicht es zuvor auf die andere Seite aus.
        """
        ziel = self._slots.get(slot_id)
        if ziel is None:
            return
        if ziel.modul_id() == modul_id:
            return

        # --- Sonderfall Video ---
        # Das Video bleibt immer in der oberen Zeile. Ein Wechsel nach unten
        # wuerde sein natives Fenster neu erzeugen und das Bild kosten.
        if modul_id == "video":
            if self._zeile_von_slot(slot_id) == "oben":
                self._video_seite_wechseln()
            return

        if ziel.modul_id() == "video":
            # Hier soll etwas anderes hin, also muss das Video zur Seite
            # weichen - in das andere obere Fenster. Danach steht in diesem
            # Fenster dessen bisheriger Inhalt, und der normale Tausch unten
            # macht den Rest.
            self._video_seite_wechseln()
            ziel = self._slots.get(slot_id)
            if ziel is None or ziel.modul_id() == modul_id:
                return

        if modul_id not in self._module:
            return

        name_neu, widget_neu = self._module[modul_id]
        quelle = next((s for s in self._slots.values()
                       if s.modul_id() == modul_id), None)

        # Merken, wo was herkam - fuer das Neuladen der Karte weiter unten.
        zeile_ziel = self._zeile_von_slot(slot_id)
        zeile_quelle = self._zeile_von_slot(quelle.slot_id) if quelle else None

        alt_id = ziel.modul_id()
        alt_widget = ziel.inhalt_entnehmen()

        if quelle is not None:
            quelle.inhalt_entnehmen()
            if alt_widget is not None and alt_id in self._module:
                quelle.inhalt_setzen(alt_id, alt_widget, self._module[alt_id][0])
        elif alt_widget is not None:
            # Ziel-Inhalt geht in die Reserve und ist damit verdeckt.
            self._modul_reserve.layout().addWidget(alt_widget)
            alt_widget.hide()

        ziel.inhalt_setzen(modul_id, widget_neu, name_neu)
        self._auswahllisten_auffrischen()
        # Der Audio Zoom bekommt den Pegelverlauf erst, wenn er zu sehen ist
        # - fuer ein verdecktes Fenster lohnt das Umrechnen nicht. Fehlt der
        # Verlauf noch, wird jetzt abgefahren.
        if modul_id == "audio":
            self._tonspur_holen()
            self._sprechstellen_anzeigen()

        # Die Karte ist eine QWebEngineView. Wechselt sie die Zeile, bekommt
        # sie einen neuen Vater und damit ein neu erzeugtes natives Fenster -
        # der Kompositor haengt dann noch am alten und die Seite bleibt weiss.
        # Ein Neuladen baut sie im neuen Fenster sauber auf. Innerhalb einer
        # Zeile passiert das nicht, dort ist es nur ein Positionswechsel.
        #
        # Bis zum 04.09.2026 stand hier ein nacktes view.reload() - und
        # danach zeigte die Karte Europa ohne Strecke, weil das Neuladen
        # alles vergisst, was per JavaScript in der Seite war. Die Karte
        # holt sich Route und Marker jetzt selbst zurueck.
        betroffen = [(modul_id, zeile_quelle, zeile_ziel)]
        if quelle is not None and alt_id in self._module:
            betroffen.append((alt_id, zeile_ziel, zeile_quelle))
        for mid, von, nach in betroffen:
            if mid == "map" and von is not None and von != nach:
                self.map_widget.neu_laden_und_wiederherstellen()
                break
        # Eine schwebende GPX-Leiste muss ueber dem neu gesetzten Inhalt bleiben.
        QTimer.singleShot(0, self._gpx_leiste_oben_halten)

    def _modulbelegung_lesen(self):
        """{slot_id: modul_id} fuer die vier Fenster, oder None bei Luecken."""
        belegung = {}
        for sid in ("ol", "or", "ul", "ur"):
            slot = self._slots.get(sid)
            if slot is None or not slot.modul_id():
                return None
            belegung[sid] = slot.modul_id()
        return belegung

    def _modulbelegung_wiederherstellen(self):
        """Die beim letzten Beenden gemerkte Belegung anwenden - wenn es sie gibt."""
        roh = QSettings("KVRouite", "KVRouite").value(self._MODULE_LAYOUT_KEY, "", type=str)
        if not roh:
            return
        belegung = {}
        for eintrag in roh.split(","):
            if ":" not in eintrag:
                return
            sid, mid = eintrag.split(":", 1)
            belegung[sid.strip()] = mid.strip()
        self._modulbelegung_anwenden(belegung)

    def _modulbelegung_anwenden(self, belegung):
        """Module so verteilen, wie belegung es sagt. True, wenn angewendet.

        Alles Unbrauchbare wird abgewiesen statt halb angewendet: fehlende
        Fenster, unbekannte Module (aus einer aelteren oder neueren Fassung),
        ein Modul doppelt, Video ausserhalb der oberen Zeile. Dann bleibt
        die Startbelegung - ein alter Eintrag darf keinen Start verhindern.

        Reihenfolge: zuerst die Video-Seite ueber _video_seite_wechseln (das
        Video darf nur dort umziehen), dann die drei uebrigen Fenster ueber
        _modul_wechseln - das kennt Tausch und Reserve schon, das vierte
        Modul landet von selbst in der Reserve.
        """
        fenster = ("ol", "or", "ul", "ur")
        if set(belegung) != set(fenster):
            return False
        bekannt = set(self._module) | {"video"}
        werte = list(belegung.values())
        if any(m not in bekannt for m in werte) or len(set(werte)) != 4:
            return False
        video_slot = None
        for sid, mid in belegung.items():
            if mid == "video":
                video_slot = sid
        if video_slot not in ("ol", "or"):
            return False
        if self._slots[video_slot].modul_id() != "video":
            self._video_seite_wechseln()
        for sid in fenster:
            if sid != video_slot:
                self._modul_wechseln(sid, belegung[sid])
        return True

    def _video_seite_wechseln(self):
        """Die beiden oberen Fenster tauschen die Seite.

        Getauscht werden die FENSTER im Splitter, nicht ihre Inhalte. Das ist
        eine reine Indexaenderung im selben Splitter - kein Vaterwechsel, das
        Videobild bleibt also stehen. Wuerde man die Inhalte tauschen, bekaeme
        das Video eine neue native Fenster-ID und das Bild waere weg.

        Damit "ol" weiterhin "links oben" bedeutet, wandern die Bezeichnungen
        mit.
        """
        sp = getattr(self, "_top_splitter", None)
        links, rechts = self._slots.get("ol"), self._slots.get("or")
        if sp is None or links is None or rechts is None:
            return

        groessen = sp.sizes()
        sp.insertWidget(0, rechts)          # rechtes Fenster nach links
        sp.setSizes(list(reversed(groessen)))

        self._slots["ol"], self._slots["or"] = rechts, links
        rechts.slot_id, links.slot_id = "ol", "or"
        self._auswahllisten_auffrischen()

    # Standardmaessig AUS. Gemessen am fertigen Fenster kostet die Leiste in
    # jedem der vier Fenster rund 20 px Hoehe, ohne etwas beizutragen, was
    # Schwebeknopf und Rechtsklick nicht auch koennten. Der Schalter bleibt,
    # weil die Leiste als einzige den Modulnamen anzeigt.
    # Eigener Schluessel: der alte hatte den Auslieferungswert "an".
    _KOPFZEILEN_KEY = "ui/fenster_kopfzeilen"
    _OVERLAY_KEY = "ui/hoehen_overlay"

    _OVERLAY_POS_KEY = "ui/hoehen_overlay_pos"

    def _overlay_position_gemerkt(self, rx: float, ry: float):
        """Frei gezogene Stelle der Einblendung merken.

        Gespeichert wird relativ zur Bildgroesse, damit sie bei einer anderen
        Fenstergroesse an derselben Stelle im Bild sitzt. -1 heisst: keine
        freie Stelle, es gilt wieder der Standardplatz unten links.
        """
        s = QSettings("KVRouite", "KVRouite")
        if rx < 0 or ry < 0:
            s.remove(self._OVERLAY_POS_KEY)
        else:
            s.setValue(self._OVERLAY_POS_KEY, f"{rx:.5f};{ry:.5f}")


    def _hoehen_overlay_umschalten(self, an: bool):
        """Hoehenprofil im Videobild ein- oder ausblenden."""
        self.video_editor.hoehen_overlay_zeigen(an)
        QSettings("KVRouite", "KVRouite").setValue(self._OVERLAY_KEY, bool(an))


    def _kopfzeilen_anwenden(self, an: bool):
        """Nur die Sichtbarkeit setzen - ohne zu speichern."""
        for slot in self._slots.values():
            slot.kopf_zeigen(an)

    def _kopfzeilen_umschalten(self, an: bool):
        """Vom Menue: umschalten und die Wahl merken."""
        self._kopfzeilen_anwenden(an)
        QSettings("KVRouite", "KVRouite").setValue(self._KOPFZEILEN_KEY, bool(an))

    # ------------------------------------------------------------------
    # Ort der GPX-Leiste: unter/ueber Tabelle, unter/ueber Karte, schwebend.
    # ------------------------------------------------------------------
    _GPX_LEISTE_KEY = "ui/gpx_leiste_ort"
    _GPX_LEISTE_POS_KEY = "ui/gpx_leiste_pos"
    _GPX_LEISTE_ORTE = (
        ("unter_tabelle", "Under GPX Table"),
        ("ueber_tabelle", "Over GPX Table"),
        ("unter_karte",   "Under Map"),
        ("ueber_karte",   "Over Map"),
        ("schwebend",     "Floating"),
    )

    def _gpx_leiste_ort_gespeichert(self):
        s = QSettings("KVRouite", "KVRouite")
        ort = str(s.value(self._GPX_LEISTE_KEY, "", type=str) or "")
        if ort in dict(self._GPX_LEISTE_ORTE):
            return ort
        # Vorstufe vom selben Tag (nie ausgeliefert): ein Ja/Nein-Schalter
        # "unter der Karte". Wer ihn gesetzt hatte, landet am selben Ort.
        if s.value("ui/gpx_leiste_unter_karte", False, type=bool):
            s.remove("ui/gpx_leiste_unter_karte")
            return "unter_karte"
        return "unter_tabelle"

    def _gpx_leiste_anwenden(self, ort: str):
        """Die GPX-Leiste an den Ort `ort` haengen.

        Es ist dasselbe Widget; nur der Container wechselt. Signale und
        Zustand (rote Marken, Infozeile) haengen am Widget und bleiben.
        Angedockt: erstes (ueber) oder letztes (unter) Element im Container
        der Tabelle bzw. der Karte. Schwebend: Kind des zentralen Fensters,
        damit sie ueber Karte, Tabelle, Chart und Video liegen darf - Qt
        macht sie dort von selbst nativ, und gemessen am 08.09.2026 liegt
        sie damit auch ueber der WebEngine-Karte sichtbar oben. Bei der
        Karte und schwebend flacher (kompakt), 44 statt 58 px.
        """
        leiste = self.gpx_control
        alt = leiste.parentWidget()
        if alt is not None and alt.layout() is not None:
            alt.layout().removeWidget(leiste)
        schwebend = (ort == "schwebend")
        leiste.schwebend(schwebend, bewegt=self._gpx_leiste_schwebend_nachziehen,
                         losgelassen=self._gpx_leiste_position_merken)
        leiste.kompakt(schwebend or ort in ("unter_karte", "ueber_karte"),
                       logo_voll=schwebend)
        if schwebend:
            leiste.setParent(self.centralWidget())
            leiste.adjustSize()
            leiste.resize(leiste.sizeHint())
            self._gpx_leiste_schwebend_platzieren()
            leiste.show()
            leiste.raise_()
        else:
            ziel = (self.map_area_layout if ort in ("unter_karte", "ueber_karte")
                    else self.bottom_right_layout)
            if ort.startswith("ueber"):
                ziel.insertWidget(0, leiste, stretch=0)
            else:
                ziel.addWidget(leiste, stretch=0)
            leiste.show()
        self._gpx_leiste_ort = ort
        self._gpx_leiste_tabelle_freihalten()

    def _gpx_leiste_umschalten(self, ort: str):
        """Vom Menue: umhaengen und die Wahl merken."""
        self._gpx_leiste_anwenden(ort)
        QSettings("KVRouite", "KVRouite").setValue(self._GPX_LEISTE_KEY, ort)

    def _gpx_leiste_schwebend_platzieren(self):
        """Gemerkte Position anwenden, sonst unten ueber der Tabelle beginnen.

        Gemerkt sind Pixel UND die Flaeche, in der sie galten ("x,y,w,h").
        Ist die Flaeche heute dieselbe, sitzt die Leiste auf den Pixel genau
        dort, wo sie beim Beenden stand; ist das Fenster anders gross, wird
        proportional umgerechnet. Bis zum 08.09.2026 stand nur ein Anteil
        drin, und der wurde beim Start auf das noch winzige Fenster
        angewendet - nach dem Neustart lag die Leiste woanders.
        """
        leiste = self.gpx_control
        flaeche = self.centralWidget().rect()
        s = QSettings("KVRouite", "KVRouite")
        roh = str(s.value(self._GPX_LEISTE_POS_KEY, "", type=str) or "")
        x = y = None
        try:
            teile = [float(t) for t in roh.split(",")]
            if len(teile) == 4:
                px, py, w, h = teile
                if int(w) == flaeche.width() and int(h) == flaeche.height():
                    x, y = int(px), int(py)
                elif w > 0 and h > 0:
                    x = int(round(px * flaeche.width() / w))
                    y = int(round(py * flaeche.height() / h))
            elif len(teile) == 2:
                # Altes Format vom selben Tag: Anteile.
                x = int(teile[0] * flaeche.width())
                y = int(teile[1] * flaeche.height())
        except (ValueError, TypeError):
            pass
        if x is None:
            tab = self.bottom_right_widget
            ecke = tab.mapTo(self.centralWidget(), QPoint(0, tab.height()))
            x = ecke.x()
            y = ecke.y() - leiste.height()
        leiste.move(self._gpx_leiste_klemmen(QPoint(x, y)))

    def _gpx_leiste_klemmen(self, pos: QPoint) -> QPoint:
        """Position so begrenzen, dass die Leiste ganz im Fenster bleibt."""
        leiste = self.gpx_control
        flaeche = self.centralWidget().rect()
        x = max(0, min(pos.x(), flaeche.width() - leiste.width()))
        y = max(0, min(pos.y(), flaeche.height() - leiste.height()))
        return QPoint(x, y)

    def _gpx_leiste_schwebend_nachziehen(self):
        """Waehrend des Ziehens: im Fenster halten, Tabelle freihalten."""
        leiste = self.gpx_control
        leiste.move(self._gpx_leiste_klemmen(leiste.pos()))
        self._gpx_leiste_tabelle_freihalten()

    def _gpx_leiste_position_merken(self):
        """Nach dem Loslassen: Pixel und Flaeche merken (siehe platzieren)."""
        leiste = self.gpx_control
        flaeche = self.centralWidget().rect()
        if flaeche.width() > 0 and flaeche.height() > 0:
            QSettings("KVRouite", "KVRouite").setValue(
                self._GPX_LEISTE_POS_KEY,
                "%d,%d,%d,%d" % (leiste.x(), leiste.y(), flaeche.width(), flaeche.height()))

    def _gpx_leiste_tabelle_freihalten(self):
        """Liegt die schwebende Leiste ueber dem unteren Rand der Tabelle,
        bekommt die Tabelle unten einen Leerraum in dieser Hoehe - so bleibt
        die letzte Zeile per Scrollen sichtbar. Liegt sie woanders oder ist
        sie angedockt, ist der Leerraum null."""
        tabelle = self.gpx_widget.gpx_list.table
        rand = 0
        if getattr(self, "_gpx_leiste_ort", "") == "schwebend":
            leiste = self.gpx_control
            l_oben = leiste.mapToGlobal(QPoint(0, 0))
            l_rect = QRect(l_oben, leiste.size())
            t_oben = tabelle.mapToGlobal(QPoint(0, 0))
            t_rect = QRect(t_oben, tabelle.size())
            schnitt = l_rect.intersected(t_rect)
            if not schnitt.isEmpty() and schnitt.bottom() >= t_rect.bottom() - 2:
                rand = schnitt.height()
        tabelle.setViewportMargins(0, 0, 0, rand)

    def _gpx_leiste_oben_halten(self):
        """Nach Modultausch oder Groessenaenderung: schwebende Leiste oben
        und im Fenster.

        Bei jeder Groessenaenderung wird aus dem gemerkten Stand neu
        platziert - beim Start ist das Fenster erst winzig und waechst dann
        auf seine gespeicherte Groesse; die letzte Aenderung setzt die
        Leiste damit auf den Pixel genau dorthin, wo sie beim Beenden stand.
        """
        if getattr(self, "_gpx_leiste_ort", "") != "schwebend":
            return
        leiste = self.gpx_control
        self._gpx_leiste_schwebend_platzieren()
        leiste.move(self._gpx_leiste_klemmen(leiste.pos()))
        leiste.raise_()
        self._gpx_leiste_tabelle_freihalten()

    def eventFilter(self, obj, event):
        if obj is self.centralWidget() and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._gpx_leiste_oben_halten)
        return super().eventFilter(obj, event)

    @staticmethod
    def _halve(sp):
        """Einen waagerechten Splitter exakt halbieren.

        Die Griffbreite muss raus, bevor geteilt wird. Sonst ist die Summe der
        beiden Wunschbreiten groesser als der Splitter und Qt kuerzt selbst -
        das Ergebnis ist dann um ein paar Pixel schief.
        """
        if sp is None:
            return
        avail = sp.width() - sp.handleWidth() * (sp.count() - 1)
        if avail < 2:
            return
        half = avail // 2
        sp.setSizes([half, avail - half])

    def _split_5050(self):
        """Auslieferungszustand: beide Zeilen halbiert, Timeline auf Starthoehe.

        Senkrecht wird NICHT gleichmaessig geteilt. Die obere Zeile bekommt
        genau so viel Hoehe, dass ein 16:9-Bild die Breite seines Platzes voll
        ausfuellt - sonst startet der Player mit schwarzen Balken links und
        rechts. Gerechnet wird mit der halben Breite der oberen Zeile, daraus
        16:9, plus die Bedienleiste darunter. Den Rest bekommt die untere Zeile.

        16:9 ist eine Annahme fuer den Startzustand: beim Start ist noch kein
        Video geladen, das Seitenverhaeltnis also unbekannt.
        """
        self._halve(getattr(self, "_top_splitter", None))
        self._halve(getattr(self, "_bottom_splitter", None))

        sp = getattr(self, "_main_splitter", None)
        if sp is None:
            return
        avail = sp.height() - sp.handleWidth() * (sp.count() - 1)
        rest = avail - self._TIMELINE_START_H
        if rest < 2:
            return

        oben = rest // 2
        top = getattr(self, "_top_splitter", None)
        if top is not None and top.width() > 0:
            platz = (top.width() - top.handleWidth() * (top.count() - 1)) // 2
            leiste = 0
            if getattr(self, "video_control", None) is not None:
                leiste = self.video_control.sizeHint().height()
            kopf = 0
            slot_or = self._slots.get("or") if getattr(self, "_slots", None) else None
            if slot_or is not None and slot_or._kopf.isVisible():
                kopf = slot_or._kopf.height()
            gewuenscht = int(platz * 9 / 16) + leiste + kopf
            # Der unteren Zeile muss genug bleiben, damit Chart und Tabelle
            # nicht auf einen Streifen zusammenfallen.
            oben = max(200, min(gewuenscht, rest - 200))

        sp.setSizes([oben, self._TIMELINE_START_H, rest - oben])

    def _restore_or_balance_splitter(self):
        """Splitter-Teilung laden - oder, wenn nichts gespeichert ist, halbieren.

        50/50 ist der gewuenschte Auslieferungszustand. Qt wuerde sonst nach
        den sizeHints der beiden Spalten aufteilen, und weil die rechte Spalte
        (Info-Zeile der GPX-Leiste) einen groesseren Hint hat als die linke,
        bekaeme rechts dauerhaft ein paar hundert Pixel mehr.

        Unter die Mindestbreite einer Spalte kommt auch 50/50 nicht - Qt
        korrigiert das dann selbst nach oben.

        Seit 6.02 sind es drei Splitter. Geladen wird nur, wenn fuer alle drei
        etwas gespeichert ist und auch alle drei sich wiederherstellen lassen -
        sonst gaebe eine halb geladene Aufteilung ein schiefes Fenster.
        """
        sp = getattr(self, "_main_splitter", None)
        top = getattr(self, "_top_splitter", None)
        bottom = getattr(self, "_bottom_splitter", None)
        if sp is None or top is None or bottom is None:
            return

        s = QSettings("KVRouite", "KVRouite")
        paare = (
            (sp, self._SPLITTER_KEY),
            (top, self._TOP_SPLITTER_KEY),
            (bottom, self._BOTTOM_SPLITTER_KEY),
        )
        zustaende = []
        for widget, key in paare:
            data = s.value(key, None, type=QByteArray)
            if data is None or data.isEmpty():
                self._split_5050()
                return
            zustaende.append((widget, data))

        for widget, data in zustaende:
            if not widget.restoreState(data):
                self._split_5050()
                return

    def _save_window_layout(self):
        s = QSettings("KVRouite", "KVRouite")
        # Im Vollbild/maximiert speichert saveGeometry() zusaetzlich die
        # normale Groesse mit - deshalb reicht der eine Aufruf.
        s.setValue(self._GEOMETRY_KEY, self.saveGeometry())
        for attr, key in (("_main_splitter", self._SPLITTER_KEY),
                          ("_top_splitter", self._TOP_SPLITTER_KEY),
                          ("_bottom_splitter", self._BOTTOM_SPLITTER_KEY)):
            sp = getattr(self, attr, None)
            if sp is not None:
                s.setValue(key, sp.saveState())
        belegung = self._modulbelegung_lesen()
        if belegung:
            s.setValue(self._MODULE_LAYOUT_KEY,
                       ",".join("%s:%s" % (sid, mid) for sid, mid in belegung.items()))

    def _on_reset_window_layout(self):
        s = QSettings("KVRouite", "KVRouite")
        s.remove(self._GEOMETRY_KEY)
        s.remove(self._SPLITTER_KEY)
        s.remove(self._TOP_SPLITTER_KEY)
        s.remove(self._BOTTOM_SPLITTER_KEY)
        s.remove(self._MODULE_LAYOUT_KEY)
        # Auch die Belegung zurueck - sonst hiesse Reset nur "Groessen
        # zurueck, Fenster bleiben vertauscht".
        self._modulbelegung_anwenden(self._STANDARD_BELEGUNG)

        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        size = self._default_window_size()
        self.resize(size)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)

        self._split_5050()

    def showEvent(self, event):
        super().showEvent(event)
        # Die Fensterleiste gehoert Windows, nicht Qt - sie muss beim ersten
        # Anzeigen eigens eingefaerbt werden, sonst steht ein weisser Balken
        # ueber einem dunklen Fenster.
        from core import theme
        theme.titelleiste_anpassen(self)
        if not getattr(self, "_layout_restored", False):
            self._layout_restored = True
            # Erst wenn das Fenster seine endgueltige Breite hat, sonst wird
            # die Haelfte von einer Zwischengroesse berechnet.
            QTimer.singleShot(0, self._restore_or_balance_splitter)
            # Und danach das Hoehenprofil im Video: seine Stelle wird aus der
            # Bildgroesse gerechnet, die erst nach dem Aufteilen der Splitter
            # feststeht. Ohne diesen zweiten Durchgang sass es nach dem Start
            # in der Bildmitte statt unten links.
            QTimer.singleShot(0, self.video_editor._hoehen_overlay_platzieren)

    def closeEvent(self, event):
        # Laeuft ein Export, entscheidet der Encoder-Dialog: er fragt nach
        # und stoppt bei Ja. Solange er laeuft, bleibt das Hauptfenster
        # offen - sonst rechnete der Encoder ohne Fenster weiter.
        enc = getattr(self, "_encoder_dialog", None)
        if enc is not None and enc.laeuft():
            enc.close()
            if enc.laeuft():
                event.ignore()
                return
        try:
            self._save_window_layout()
        except Exception as e:
            print("[WARN] window layout not saved:", e)
        try:
            self.video_editor.shutdown_player()
        except Exception as e:
            print("[WARN] player not shut down:", e)
        super().closeEvent(event)

    _INFO_SAMPLES = (
        ("label_video",     "V: 00:00:00.000"),
        ("label_gpx",       "GPX: 999.99km/00:00:00.000"),
        ("label_elev",      "Ele: 99999m"),
        ("label_slope_max", "Max%: -99.9%"),
        ("label_slope_min", "Min%: -99.9%"),
        ("label_zerospeed", "Zero: 99999"),
        ("label_paused",    "Gaps: 99999"),
    )

    def _measure_max_needed_width(self):
        """Breite messen, die das Fenster im Vollausbau braucht.

        Vollausbau heisst: alle Buttons eingeblendet, die je eingeblendet werden
        koennen, und die laengsten Texte in der Info-Zeile. Genau dieser Zustand
        laesst Qt heute das Fenster groesser ziehen. Wird er einmal gemessen und
        als Minimum gesetzt, aendert sich das Minimum spaeter nicht mehr - und
        damit springt nichts.

        Gemessen wird mit abgeschalteten Updates, es ist also nichts davon zu
        sehen. Der Ausgangszustand wird vollstaendig wiederhergestellt.
        """
        vc = getattr(self, "video_control", None)
        gc = getattr(self, "gpx_control", None)
        central = self.centralWidget()
        if vc is None or gc is None or central is None or central.layout() is None:
            return 0

        optional = [getattr(vc, n, None) for n in (
            "hour_edit", "min_edit", "sec_edit", "markB_button", "markE_button",
            "clear_button", "cut_button", "cut_begin_button", "cut_end_button",
            "ovl_button", "autocut_button", "seite_button")]
        optional += [getattr(gc, n, None) for n in (
            "markB_button", "markE_button", "deselect_button", "cut_button",
            "slot_sync_button")]
        was_hidden = [x for x in optional if x is not None and x.isHidden()]

        saved_text = []
        for attr, sample in self._INFO_SAMPLES:
            lbl = getattr(gc, attr, None)
            if lbl is not None:
                saved_text.append((lbl, lbl.text()))

        def relayout():
            # Es reicht NICHT, nur die beiden Leisten und das zentrale Layout zu
            # invalidieren: dazwischen liegen Spalten-Widgets und der Splitter,
            # die sonst ihre alten Minima behalten. Dann meldet das zentrale
            # Layout den Ist- statt den Vollausbau-Wert. Also die komplette
            # Kette von der jeweiligen Leiste bis zum Fenster hoch.
            for start in (vc, gc):
                widget = start
                while widget is not None:
                    lay = widget.layout()
                    if lay is not None:
                        lay.invalidate()
                    widget.updateGeometry()
                    if widget is self:
                        break
                    widget = widget.parentWidget()
            lay = central.layout()
            if lay is not None:
                lay.activate()

        # Kein setUpdatesEnabled(False): das blockiert die Layout-Neuberechnung,
        # dann misst man den Ist- statt den Vollausbau-Zustand. Sichtbar wird
        # trotzdem nichts, weil hier kein processEvents() laeuft und damit bis
        # zum Zuruecksetzen kein Neuzeichnen stattfindet.
        try:
            for x in was_hidden:
                x.setVisible(True)
            for attr, sample in self._INFO_SAMPLES:
                lbl = getattr(gc, attr, None)
                if lbl is not None:
                    lbl.setText(sample)
            relayout()
            needed = central.layout().totalMinimumSize().width()
        finally:
            for x in was_hidden:
                x.setVisible(False)
            for lbl, text in saved_text:
                lbl.setText(text)
            relayout()

        # Rahmen/Raender des Fensters kommen zur Layoutbreite noch dazu.
        return needed + (self.width() - central.width())

    def _apply_width_lock(self):
        """Breiten-Sperre an- oder abschalten (Config > Lock Window Width)."""
        on = QSettings("KVRouite", "KVRouite").value(
            "ui/freeze_width", False, type=bool)
        if not on:
            # setMinimumSize(0, 0) statt setMinimumWidth(0): Qt merkt sich in
            # explicitMinSize, dass hier von Hand ein Minimum gesetzt wurde,
            # und rechnet dann nie wieder selbst nach. setMinimumWidth() VERODERT
            # dieses Flag nur (expl | (w ? Horizontal : 0)) - eine 0 loescht es
            # also nicht, das Flag vom Einschalten bliebe stehen und das Fenster
            # liesse sich auf 0 px ziehen. setMinimumSize() setzt das Flag
            # dagegen direkt und raeumt es damit weg.
            self.setMinimumSize(0, 0)
            central = self.centralWidget()
            if central is not None and central.layout() is not None:
                central.layout().invalidate()
                central.layout().activate()
            # Das Fenster-Minimum setzt QMainWindowLayout, nicht das zentrale
            # Layout - also auch das anstossen.
            if self.layout() is not None:
                self.layout().invalidate()
                self.layout().activate()
            return
        needed = self._measure_max_needed_width()
        if needed > 0:
            self.setMinimumWidth(needed)

    def _on_lock_width_toggled(self, on: bool):
        QSettings("KVRouite", "KVRouite").setValue("ui/freeze_width", bool(on))
        self._apply_width_lock()

    def _on_reset_config_triggered(self):
       
    
        answer = QMessageBox.question(
            self,
            "Reset Config",
            "Do you really want to reset all QSettings?\n"
            "This will remove disclaimers, keys etc.\n"
            "You may have to restart the application.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer == QMessageBox.Yes:
            reset_config()  # ruft s.clear()
            QMessageBox.information(
                self,
                "Reset done",
                "All config settings have been removed.\n"
                "Please restart the application."
            )
    
    
    def on_cut_clicked_video(self):
        """
        Neuer, genauer Cut-Workflow mit End-Cut Erkennung
        """
        from datetime import timedelta
        import copy
        try:
            from core.gpx_parser import recalc_gpx_data
        except Exception:
            recalc_gpx_data = None
    
        # Bevor irgendetwas passiert: nimmt dieser Schnitt einer bereits
        # eingestellten Blende den Platz? Wenn ja, entscheidet der Nutzer -
        # kuerzen lassen oder abbrechen. Waehrend eines Umzugs wird hier nicht
        # gefragt: der fragt vorher selbst, und zwar fuer die neue Lage im
        # Ganzen.
        blende_kuerzungen = []
        if not getattr(self, "_verschiebe_schritt", False):
            kandidat = self._kandidat_aus_marken()
            if kandidat is not None:
                weiter, blende_kuerzungen = self._blenden_konflikt_fragen(
                    self._cuts_mit(kandidat), "Placing this cut")
                if not weiter:
                    return

        do_gpx_edit = (self._autoSyncVideoEnabled and self._edit_mode in ("copy", "encode"))
        
        # --- 0) Wenn GPX-Edit gewünscht: Zeiten VOR dem Video-Cut speichern ---
        final_start = None
        final_end = None
        if do_gpx_edit:
            # Mark-Zeiten aus cut_manager (global)
            if not hasattr(self.cut_manager, "markB_time_s") or not hasattr(self.cut_manager, "markE_time_s"):
                print("[WARN] on_cut_clicked_video: cut_manager missing mark times, skipping GPX cut.")
                # trotzdem Video-Cut ausführen (kein GPX)
                self.register_video_undo_snapshot(False, "Cut (video)")
                self.cut_manager.on_cut_clicked()
                return

            if self.cut_manager.markB_time_s < 0 or self.cut_manager.markE_time_s < 0:
                print("[WARN] on_cut_clicked_video: mark times missing, skipping GPX cut.")
                # Video-Cut trotzdem ausführen
                self.register_video_undo_snapshot(False, "Cut (video)")
                self.cut_manager.on_cut_clicked()
                return
    
            start_global = min(self.cut_manager.markB_time_s, self.cut_manager.markE_time_s)
            end_global = max(self.cut_manager.markB_time_s, self.cut_manager.markE_time_s)
    
            total_dur = sum(self.video_durations) if self.video_durations else getattr(self, "real_total_duration", 0.0)
            start_global = max(0.0, start_global)
            end_global = min(end_global, total_dur)
            if (end_global - start_global) < 0.01:
                print("[DEBUG] Cut-Bereich zu klein, Abbruch. Start:", start_global, "Ende:", end_global)
                return

            # 🔥 END-CUT ERKENNUNG (muss VOR dem Mapping stehen, siehe unten)
            is_end_cut = abs(end_global - total_dur) < 0.1  # Toleranz 0.1 Sekunden

            # Ein neuer End-Schnitt ersetzt den alten. Fuer die Umrechnung
            # muessen wir den alten End-Schnitt deshalb schon ausblenden -
            # sonst laege start_global bei einem nach hinten verschobenen Ende
            # innerhalb des alten Cuts und wuerde falsch abgebildet.
            mapping_cuts = self.cut_manager._cut_intervals
            if is_end_cut:
                mapping_cuts = [
                    iv for iv in self.cut_manager._cut_intervals
                    if not self.cut_manager.is_end_cut(iv[1])
                ]

            # final times (vor dem Anlegen des Cuts!!) -> damit das Mapping korrekt ist
            final_start = self.get_final_time_for_global(start_global, mapping_cuts)
            final_end = self.get_final_time_for_global(end_global, mapping_cuts)
            print(f"[DEBUG] on_cut_clicked_video => captured marks: global [{start_global:.3f}..{end_global:.3f}] -> final [{final_start:.3f}..{final_end:.3f}], is_end_cut={is_end_cut}")
        
            # Undo-Snapshots (GPX + Video)
            schritt = f"Cut {start_global:.3f}-{end_global:.3f} s (video + GPX)"
            self.register_gpx_undo_snapshot(schritt)
            self.register_video_undo_snapshot(True, schritt)
        else:
            # nur Video-Undo
            self.register_video_undo_snapshot(False, "Cut (video)")
        
        # --- 1) Video-Cut anlegen (macht auch timeline update, reset MarkB/E intern) ---
        self.cut_manager.on_cut_clicked()
        # Erst jetzt kuerzen: die Schluessel haengen an den Schnitten, und
        # der neue gehoert dazu.
        self._blenden_kuerzen(blende_kuerzungen)
        
        # --- 2) Wenn kein GPX-Edit erwünscht -> fertig ---
        if not do_gpx_edit:
            return
        
        # --- 3) GPX bearbeiten ---
        gpx_data = self.gpx_widget.gpx_list._gpx_data
        if not gpx_data or len(gpx_data) < 2:
            print("[DEBUG] on_cut_clicked_video: no GPX data or too few points, skipping GPX cut.")
            return
        
        # Basis-Datetime + Video-Shift
        base_dt = gpx_data[0].get("time", None)
        try:
            video_shift = get_gpx_video_shift()
            if video_shift is None:
                video_shift = 0.0
        except Exception:
            video_shift = 0.0
        
        if base_dt is None:
            print("[DEBUG] on_cut_clicked_video: GPX base time missing, skipping GPX cut.")
            return
        
        # 🔥 END-CUT BEHANDLUNG
        ####
        
        if is_end_cut:
            print("[DEBUG] End-Cut Behandlung: Schneide GPX komplett ab Startpunkt")
    
            # 🔥 MILLISEKUNDENGENAUE BERECHNUNG
            # Basis-Datetime des GPX
            base_dt = gpx_data[0].get("time", None)
        
            # Video-Start in GPX-Zeit berechnen (unter Berücksichtigung des Sync)
            video_start_gpx = base_dt + timedelta(seconds=-video_shift)
    
            # Gewünschte GPX-Zeit für den Schnitt berechnen
            # Hier müssen wir die genaue Position im Video in GPX-Zeit umrechnen
            desired_cut_dt = video_start_gpx + timedelta(seconds=final_start)
    
            # Stelle sicher, dass wir nicht vor dem ersten GPX-Punkt schneiden
            desired_cut_dt = max(desired_cut_dt, base_dt)
        
            print(f"[DEBUG] End-Cut: Schneide GPX ab {desired_cut_dt}")
            print(f"[DEBUG] Berechnung: video_start_gpx={video_start_gpx}, final_start={final_start}, video_shift={video_shift}")
    
            # 🔥 INTERPOLATION FÜR MILLISEKUNDENGENAUEN SCHNITT
            # Hilfsfunktion: lineare Interpolation zwischen zwei Punkten
            def _interp_point(pt1, pt2, new_time):
                t1 = pt1.get("time")
                t2 = pt2.get("time")
                if t1 is None or t2 is None or t2 == t1:
                    ratio = 0.0
                else:
                    ratio = (new_time - t1).total_seconds() / (t2 - t1).total_seconds()
        
                def _val(k):
                    return pt1.get(k, 0.0) + ratio * (pt2.get(k, 0.0) - pt1.get(k, 0.0))
        
                new_pt = {
                    "lat": _val("lat"),
                    "lon": _val("lon"),
                    "ele": _val("ele"),
                    "time": new_time,
                    "delta_m": 0.0,
                    "speed_kmh": 0.0,
                    "gradient": 0.0
                }
                return new_pt
                
            # Neuen GPX-Track erstellen mit millisekundengenauer Interpolation
            new_gpx = []
            n = len(gpx_data)
            
            # Finde den Punkt, an dem wir schneiden müssen
            cut_index = -1
            for i in range(n-1):
                if gpx_data[i].get("time") <= desired_cut_dt <= gpx_data[i+1].get("time"):
                    cut_index = i
                    break
    
            if cut_index >= 0:
                # Interpoliere einen exakten Punkt am Schnittzeitpunkt
                interpolated_point = _interp_point(
                    gpx_data[cut_index], 
                    gpx_data[cut_index+1], 
                    desired_cut_dt
                )
                
                # Übernehme alle Punkte bis zum Schnitt + den interpolierten Punkt
                for i in range(cut_index + 1):
                    new_gpx.append(copy.deepcopy(gpx_data[i]))
            
                new_gpx.append(interpolated_point)
                print(f"[DEBUG] Millisekundengenauer Schnitt: interpoliert zwischen Index {cut_index} und {cut_index+1}")
            else:
                # Fallback: Einfach alle Punkte bis zum gewünschten Zeitpunkt übernehmen
                for pt in gpx_data:
                    if pt.get("time") <= desired_cut_dt:
                        new_gpx.append(copy.deepcopy(pt))
                
                # Wenn wir keinen Punkt gefunden haben, der genau passt, nimm den letzten Punkt vor desired_cut_dt
                if not new_gpx:
                    for i in range(n):
                        if gpx_data[i].get("time") <= desired_cut_dt:
                            new_gpx.append(copy.deepcopy(gpx_data[i]))
                
                print(f"[DEBUG] Einfacher Schnitt: {len(new_gpx)} Punkte übernommen")
    
            # Was der End-Schnitt aus der Spur nimmt, aufzeichnen - wie beim
            # Mittelschnitt. Hier rueckt nichts nach vorn, es wird nur hinten
            # abgeschnitten; dauer_s ist deshalb 0. Damit reicht die
            # vorhandene spur_ohne_schnitt() ohne Aenderung aus: Punkte vor
            # der Naht bleiben, die Naht faellt weg, das Aufgezeichnete kommt
            # zurueck.
            #
            # Faellt der Schnittzeitpunkt genau auf einen vorhandenen Punkt,
            # ist der eben erzeugte Nahtpunkt eine Kopie davon und die Spur
            # endet mit zwei gleichen Zeiten. spur_ohne_schnitt() entfernt
            # beim Zuruecknehmen ALLE Punkte auf der Naht - dann muss der
            # vorhandene mit aufgezeichnet werden, sonst fehlt er nachher.
            if cut_index >= 0:
                if gpx_data[cut_index].get("time") == desired_cut_dt:
                    erster_entfernter = cut_index
                else:
                    erster_entfernter = cut_index + 1
                entfernte_punkte = [copy.deepcopy(p)
                                    for p in gpx_data[erster_entfernter:]]
                interpolierter_punkt = copy.deepcopy(interpolated_point)
            else:
                entfernte_punkte = [copy.deepcopy(p) for p in gpx_data
                                    if p.get("time") is not None
                                    and p.get("time") > desired_cut_dt]
                interpolierter_punkt = None

            if len(new_gpx) < 2:
                QMessageBox.warning(self, "Truncation", 
                    "After shortening to the video length, no meaningful GPX remains!")
                return
    
            # Metriken neu berechnen
            if recalc_gpx_data is not None:
                recalc_gpx_data(new_gpx)
            else:
                print("[WARN] recalc_gpx_data nicht verfügbar")
            
            self.gpx_widget.set_gpx_data(new_gpx)
            self._gpx_data = new_gpx
            
            # UI updates
            self._update_gpx_overview()
            self.chart.set_gpx_data(new_gpx)
            if self.mini_chart_widget:
                self.mini_chart_widget.set_gpx_data(new_gpx)
            
            route_geojson = self._build_route_geojson_from_gpx(new_gpx)
            self.map_widget.loadRoute(route_geojson, do_fit=False)
    
            print(f"[DEBUG] End-Cut abgeschlossen: GPX von {len(gpx_data)} auf {len(new_gpx)} Punkte gekürzt")

            # Aufzeichnung ablegen, damit sich auch der End-Schnitt
            # zuruecknehmen laesst. Ein Nachfuehren der uebrigen
            # Aufzeichnungen braucht es hier nicht: hinter einem End-Schnitt
            # liegt nichts mehr, und davor verschiebt er nichts.
            self.cut_manager.aufzeichnung_merken(
                start_global, end_global,
                entfernt=entfernte_punkte,
                verworfen=[],
                interpoliert=interpolierter_punkt,
                dauer_s=0.0,
                beginn_dt=desired_cut_dt,
            )
            print(f"[CUT-REC] End-Schnitt {start_global:.3f}-{end_global:.3f}: "
                  f"{len(entfernte_punkte)} entfernt, Nahtpunkt "
                  f"{'erzeugt' if interpolierter_punkt else 'keiner'}, "
                  f"Spur {len(gpx_data)} -> {len(new_gpx)}")
            # Die Probe rechnet die Ruecknahme durch und vergleicht sie mit
            # dem Stand von vorher. Eine Stueckzahl-Bilanz wie beim
            # Mittelschnitt taugt hier nicht: faellt die Naht auf einen
            # vorhandenen Punkt, steht der zweimal in der Rechnung.
            self._ruecknahme_probe(start_global, end_global, new_gpx, gpx_data)
        ###    
        else:
            # --- NORMALE MIDDLE-CUT LOGIK (existierender Code) ---
            print("[DEBUG] Normaler Middle-Cut")
            
            # Gewünschte absolute GPX-Datetimes (vor dem Cut)
            desired_start_dt = base_dt + timedelta(seconds=(final_start - video_shift))
            desired_end_dt   = base_dt + timedelta(seconds=(final_end - video_shift))
            
            if desired_end_dt <= desired_start_dt:
                print("[DEBUG] on_cut_clicked_video: invalid desired GPX interval, skipping.")
                return
            
            delta_to_remove = (desired_end_dt - desired_start_dt).total_seconds()
            if delta_to_remove <= 0.0:
                print("[DEBUG] on_cut_clicked_video: zero removal interval, skipping.")
                return
            
            print(f"[DEBUG] on_cut_clicked_video => trimming GPX times from {desired_start_dt} to {desired_end_dt} (delta {delta_to_remove:.3f}s)")
            
            # Hilfsfunktion: lineare Interpolation zwischen zwei Punkten
            def _interp_point(pt1, pt2, new_time):
                t1 = pt1.get("time")
                t2 = pt2.get("time")
                if t1 is None or t2 is None or t2 == t1:
                    ratio = 0.0
                else:
                    ratio = (new_time - t1).total_seconds() / (t2 - t1).total_seconds()
                def _val(k):
                    return pt1.get(k, 0.0) + ratio * (pt2.get(k, 0.0) - pt1.get(k, 0.0))
                new_pt = {
                    "lat": _val("lat"),
                    "lon": _val("lon"),
                    "ele": _val("ele"),
                    "time": new_time,
                    "delta_m": 0.0,
                    "speed_kmh": 0.0,
                    "gradient": 0.0
                }
                return new_pt
            
            # Build new GPX: keep everything before desired_start_dt (incl. interpolated start),
            # skip region [desired_start_dt .. desired_end_dt], then append remainder with times shifted by delta_to_remove.
            new_gpx = []
            new_start_pt = None      # der an der Naht erzeugte Punkt, falls es einen gibt
            n = len(gpx_data)
            i = 0
            
            # copy points strictly before desired_start_dt
            while i < n and gpx_data[i].get("time") < desired_start_dt:
                new_gpx.append(copy.deepcopy(gpx_data[i]))
                i += 1
            
            # if the next point is after desired_start_dt and we have a previous point -> insert interpolated start
            if i < n and gpx_data[i].get("time") != desired_start_dt:
                if new_gpx:
                    prev_pt = new_gpx[-1]
                    next_pt = gpx_data[i]
                    if prev_pt.get("time") < desired_start_dt < next_pt.get("time"):
                        new_start_pt = _interp_point(prev_pt, next_pt, desired_start_dt)
                        new_gpx.append(new_start_pt)
                else:
                    # There is no prev_pt: desired_start before first point -> nothing to interpolate, we simply start from later points
                    pass
            elif i < n and gpx_data[i].get("time") == desired_start_dt:
                # exact match: include that exact point (but we consider it as the "last kept" and will remove it if desired)
                new_gpx.append(copy.deepcopy(gpx_data[i]))
                i += 1
            
            # skip all points up to and including desired_end_dt
            #
            # Ab 6.02 werden diese Punkte nicht mehr nur uebersprungen, sondern
            # mit ihren ORIGINALZEITEN aufgezeichnet - sie sind alles, was zum
            # Zuruecknehmen des Schnitts noetig ist. Ebenso der an der Naht neu
            # erzeugte Punkt (er muss dabei wieder verschwinden) und weiter
            # unten die von der Ordnungspruefung verworfenen.
            entfernte_punkte = []
            while i < n and gpx_data[i].get("time") <= desired_end_dt:
                entfernte_punkte.append(copy.deepcopy(gpx_data[i]))
                i += 1
            interpolierter_punkt = copy.deepcopy(new_start_pt) if new_start_pt else None

            # Hier sitzt die Naht: alles davor ist behalten (ggf. mit dem
            # interpolierten Punkt), ab hier rueckt der Rest nach. Die
            # Ordnungspruefung unten wirft hoechstens Punkte ab hier weg, der
            # Index bleibt also der erste Punkt hinter der Luecke.
            naht_idx = len(new_gpx)

            # now append remaining points shifted backward by delta_to_remove
            for j in range(i, n):
                pt = copy.deepcopy(gpx_data[j])
                pt_time = pt.get("time")
                if pt_time is not None:
                    pt["time"] = pt_time - timedelta(seconds=delta_to_remove)
                new_gpx.append(pt)
            
            # Edge-case: if the point immediately after the removed region started before desired_start_dt
            # we may end up with the last point being duplicated or out-of-order; enforce ordering & sanity:
            verworfene_punkte = []
            if len(new_gpx) >= 2:
                # ensure strictly increasing times (small eps tolerance)
                cleaned = [new_gpx[0]]
                for k in range(1, len(new_gpx)):
                    if new_gpx[k].get("time") is None or cleaned[-1].get("time") is None:
                        cleaned.append(new_gpx[k])
                    else:
                        if new_gpx[k]["time"] > cleaned[-1]["time"]:
                            cleaned.append(new_gpx[k])
                        else:
                            # Hier wurde bisher stillschweigend etwas
                            # weggelassen. Fuers Zuruecknehmen ist gerade das
                            # gefaehrlich: der Punkt waere unwiederbringlich
                            # weg. Deshalb wird er mit aufgezeichnet - mit der
                            # bereits verschobenen Zeit, so wie er an dieser
                            # Stelle gestanden haette.
                            verworfene_punkte.append(copy.deepcopy(new_gpx[k]))
                new_gpx = cleaned
            
            if len(new_gpx) < 2:
                QMessageBox.warning(self, "Truncation", "After shortening to the video length, no meaningful GPX remains!")
                print("[WARN] on_cut_clicked_video: truncation removed too much GPX.")
                return
            
            # 4) Recalc metrics & set new GPX data
            if recalc_gpx_data is not None:
                recalc_gpx_data(new_gpx)
            else:
                print("[WARN] on_cut_clicked_video: recalc_gpx_data not available; times changed but metrics not recalculated.")

            self.gpx_widget.set_gpx_data(new_gpx)
            self._gpx_data = new_gpx
            # Rechtsklick auf [- / -] in der GPX-Leiste (V&G Off) markiert
            # nachher die beiden Nachbarn dieser Luecke.
            self.gpx_widget.gpx_list.luecke_merken(naht_idx)
            
            # UI updates
            self._update_gpx_overview()
            self.chart.set_gpx_data(new_gpx)
            if self.mini_chart_widget:
                self.mini_chart_widget.set_gpx_data(new_gpx)
            
            route_geojson = self._build_route_geojson_from_gpx(new_gpx)
            self.map_widget.loadRoute(route_geojson, do_fit=False)

            # Liegt dieser Schnitt VOR bereits aufgezeichneten Schnitten,
            # sind deren Punkte gerade um delta_to_remove nach vorn
            # gerueckt. Ihre Aufzeichnungen muessen mit, sonst zeigen sie
            # ins Leere. Vor dem eigenen Merken, damit die frische
            # Aufzeichnung unberuehrt bleibt.
            self.cut_manager.aufzeichnungen_nachfuehren(
                desired_start_dt, -delta_to_remove)

            # Aufzeichnung ablegen: alles, was noetig waere, um genau diesen
            # Schnitt wieder zurueckzunehmen. Der Schluessel ist die ROHZEIT
            # des Schnitts, die sich nicht mehr aendert.
            self.cut_manager.aufzeichnung_merken(
                start_global, end_global,
                entfernt=entfernte_punkte,
                verworfen=verworfene_punkte,
                interpoliert=interpolierter_punkt,
                dauer_s=delta_to_remove,
                beginn_dt=desired_start_dt,
            )
            # Bilanz: die alte Spur muss sich vollstaendig aus dem ergeben,
            # was jetzt da ist, plus dem Aufgezeichneten. Geht sie nicht auf,
            # fehlt der Aufzeichnung etwas - und dann waere ein Zuruecknehmen
            # von vornherein falsch. Die Zahl steht im Log, damit das nicht
            # erst beim Zuruecknehmen auffaellt.
            naht = 1 if interpolierter_punkt else 0
            bilanz = len(new_gpx) - naht + len(entfernte_punkte) + len(verworfene_punkte)
            print(f"[CUT-REC] Schnitt {start_global:.3f}-{end_global:.3f}: "
                  f"{len(entfernte_punkte)} entfernt, "
                  f"{len(verworfene_punkte)} von der Ordnungspruefung verworfen, "
                  f"Nahtpunkt {'erzeugt' if naht else 'keiner'}, "
                  f"Spur {len(gpx_data)} -> {len(new_gpx)}")
            print(f"[CUT-REC] Bilanz: {len(new_gpx)} - {naht} + {len(entfernte_punkte)}"
                  f" + {len(verworfene_punkte)} = {bilanz}, alt = {len(gpx_data)}"
                  f"  -> {'OK' if bilanz == len(gpx_data) else 'FEHLT ETWAS'}")
            self._ruecknahme_probe(start_global, end_global, new_gpx, gpx_data)

        # Zustand der Spur nach dieser eigenen Aktion festhalten. Weicht der
        # Abdruck spaeter ab, hat jemand anders die Spur bearbeitet.
        self.cut_manager.fingerabdruck_merken(self._gpx_data)

        # Clear any red-marked range in GPX list (we've applied the change)
        self.gpx_widget.gpx_list.clear_marked_range()

        print("[DEBUG] on_cut_clicked_video => GPX trimmed and UI updated.")
        
    # ------------------------------------------------------------------
    # Bildstreifen in der Zeitleiste
    # ------------------------------------------------------------------
    #: Ungefaehrer Abstand zweier Vorschaubilder auf dem Schirm. Enger waere
    #: keine zusaetzliche Information - die Bilder ueberlappten sich nur.
    _THUMB_ABSTAND_PX = 150

    #: Bis 7.0: "Thumbnails in Timeline" an/aus. Wird nur noch gelesen, um
    #: die alte Einstellung in die Ansicht zu uebernehmen.
    _THUMBS_KEY = "ui/timeline_thumbs"
    #: Seit 7.0: Ansicht der Zeitleiste ("off", "video", "audio", "beides").
    _TIMELINE_ANSICHT_KEY = "ui/timeline_view"

    def thumbs_an(self) -> bool:
        return self.timeline.bilder_an()

    def _timeline_ansicht_gewechselt(self, name: str):
        """Der Ansichtsknopf der Zeitleiste wurde geschaltet (oder der
        gemerkte Zustand hergestellt): Bilder holen oder verwerfen, die
        Tonspur nachziehen, merken."""
        QSettings("KVRouite", "KVRouite").setValue(self._TIMELINE_ANSICHT_KEY, name)
        bilder = self.timeline.bilder_an()
        if bilder != getattr(self, "_bilder_vorher", None):
            self._bilder_vorher = bilder
            self._thumbs_umschalten(bilder)
        if self.timeline.audio_an() and getattr(self, "audio_zoom", None) is not None:
            self._tonspur_holen()
            self._sprechstellen_anzeigen()

    def _tonspur_holen(self):
        """Die Ton-Ansicht braucht den Pegelverlauf: fehlt er fuer eine Datei
        im Zwischenspeicher, wird sie jetzt abgefahren (Fortschrittsdialog,
        abbrechbar). Die Sprechstellen werden dabei NICHT gesetzt, das tut
        nur "Detect". Der Pegel kommt von GStreamer, das geht auch in Lite;
        die Sprachwerte bleiben dort leer."""
        if not self.playlist:
            return
        if all(verkehr.aus_cache(p) is not None for p in self.playlist):
            return
        if self._audio_abfahren("Sound track") is None:
            self.statusBar().showMessage(
                "Audio scan cancelled - the sound track stays empty.", 6000)

    def _thumbs_umschalten(self, an: bool):
        """Vorschaubilder holen oder verwerfen.

        Aus heisst wirklich aus: es wird nichts mehr geholt und der
        Zwischenspeicher wird geleert, damit er nicht ungenutzt Speicher
        haelt. Ob gezeichnet wird, entscheidet die Zeitleiste selbst
        (Ansichtsknopf). Die Schraffur der Schnitte bleibt in beiden Faellen
        - sie hilft auch ohne Bilder, Schnitte zu erkennen.
        """
        if an:
            self.thumbs_anstossen(sofort=True)
            QTimer.singleShot(0, self.thumbs_grundstock)
        else:
            self._thumb_timer.stop()
            self._thumbs.verwerfen()
            self.timeline.set_vorschaubilder([])

    #: Kleinster Abstand zweier Bilder in Sekunden. Alle Raster sind
    #: Vielfache davon, verdoppelt: 2, 4, 8, 16, 32 ... So ist jedes groebere
    #: Raster eine Teilmenge des feineren.
    _THUMB_BASIS_S = 2.0

    def _thumb_raster_s(self):
        """Zeitabstand der Bilder bei der aktuellen Zoomstufe.

        Der springende Punkt ist, dass die Zeitpunkte NICHT an Pixel haengen.
        Waeren sie es, ergaebe jede noch so kleine Zoomaenderung voellig neue
        Stellen - nichts im Zwischenspeicher passte je wieder, und beim Zoomen
        muesste alles neu geholt werden.

        Stattdessen liegen sie auf einem festen Raster, das sich in
        Verdopplungen aendert. Innerhalb einer Stufe bleiben die Stellen
        gleich, beim Wechsel ist die Haelfte schon da.
        """
        import math
        dauern = getattr(self, "video_durations", None) or []
        gesamt = sum(dauern)
        breite = max(1, self.timeline.width())
        zoom = max(1.0, getattr(self.timeline, "_zoom_factor", 1.0))
        if gesamt <= 0:
            return self._THUMB_BASIS_S
        sek_je_px = gesamt / (breite * zoom)
        wunsch_s = self._THUMB_ABSTAND_PX * sek_je_px
        # ABRUNDEN, nicht aufrunden: die Bilder muessen dichter liegen als sie
        # breit sind, sonst klaffen zwischen ihnen Luecken. Lieber eines zu
        # viel und beschneiden als eine schwarze Spalte dazwischen.
        stufen = max(0, math.floor(math.log2(max(1e-6, wunsch_s / self._THUMB_BASIS_S))))
        return self._THUMB_BASIS_S * (2 ** stufen)

    def _thumb_stellen(self):
        """Welche Stellen des Rohmaterials der Streifen gerade braucht.

        Liefert [(gesamtzeit_s, datei, zeit_in_der_datei_s), ...] - nur fuer
        den sichtbaren Ausschnitt, und immer auf dem Raster von
        _thumb_raster_s().
        """
        dauern = getattr(self, "video_durations", None) or []
        dateien = getattr(self, "playlist", None) or []
        gesamt = sum(dauern)
        if not dateien or len(dauern) != len(dateien) or gesamt <= 0:
            return []

        breite = max(1, self.timeline.width())
        zoom = max(1.0, getattr(self.timeline, "_zoom_factor", 1.0))
        offset = getattr(self.timeline, "_horizontal_offset", 0.0)
        sek_je_px = gesamt / (breite * zoom)

        raster = self._thumb_raster_s()
        von_s = max(0.0, offset * sek_je_px)
        bis_s = min(gesamt, (offset + breite) * sek_je_px)
        # Eine Rasterstelle vor dem Ausschnitt beginnen: das erste Bild ragt
        # sonst nicht in den sichtbaren Bereich hinein.
        k = int(von_s // raster)

        stellen = []
        while True:
            t = k * raster
            k += 1
            if t > bis_s + raster:
                break
            if t < 0 or t > gesamt:
                continue
            lauf = 0.0
            for datei, laenge in zip(dateien, dauern):
                if t < lauf + laenge or datei is dateien[-1]:
                    stellen.append((t, datei, max(0.0, t - lauf)))
                    break
                lauf += laenge
            if len(stellen) > 200:      # Notbremse
                break
        return stellen

    def _thumbs_nachladen(self):
        """Fehlende Bilder anfordern und zeichnen, was schon da ist."""
        if not self.thumbs_an():
            return
        stellen = self._thumb_stellen()
        if not stellen:
            self.timeline.set_vorschaubilder([])
            return
        hoehe = max(24, self.timeline.height())
        self._thumbs.anfordern([(datei, t_datei) for _, datei, t_datei in stellen],
                               hoehe)
        self._thumbs_anzeigen()

    def _thumbs_anzeigen(self):
        """Was im Zwischenspeicher liegt, an die Zeitleiste geben.

        Fehlt fuer eine Stelle noch das genaue Bild, wird ein benachbartes
        genommen. Sonst waere der Streifen nach jedem Zoomschritt leer, bis
        alles nachgeladen ist - und gerade dann braucht man ihn.
        """
        if not self.thumbs_an():
            return
        raster = self._thumb_raster_s()
        bilder = []
        for t_gesamt, datei, t_datei in self._thumb_stellen():
            bild, _genau = self._thumbs.bild_oder_nachbar(
                datei, t_datei, toleranz_s=raster)
            if bild is not None:
                bilder.append((t_gesamt, bild))
        self.timeline.set_vorschaubilder(bilder)

    def thumbs_anstossen(self, sofort: bool = False):
        """Nachladen anstossen - verzoegert, damit Zoomen fluessig bleibt."""
        if not self.thumbs_an():
            return
        if sofort:
            self._thumb_timer.stop()
            self._thumbs_nachladen()
        else:
            self._thumb_timer.start()

    def thumbs_grundstock(self):
        """Einmal ein grobes Raster ueber die ganze Laenge holen.

        Ohne das ist der Streifen beim ersten Hineinzoomen leer, bis die
        neuen Stellen geladen sind - und gerade dann braucht man ihn zum
        Wiederfinden. Mit dem Grundstock steht immer schon ein benachbartes
        Bild zur Verfuegung (siehe bild_oder_nachbar), das sofort gezeigt und
        spaeter durch das genaue ersetzt wird.

        Die Bilder sind zugleich das groebste Raster - beim Herauszoomen
        werden genau sie gebraucht, es ist also nichts verschenkt.
        """
        if not self.thumbs_an():
            return
        dauern = getattr(self, "video_durations", None) or []
        dateien = getattr(self, "playlist", None) or []
        gesamt = sum(dauern)
        if not dateien or len(dauern) != len(dateien) or gesamt <= 0:
            return

        # So grob wie die Zeitleiste bei Zoom 1 zeichnet.
        raster = self._thumb_raster_s()
        wuensche = []
        k = 0
        while k * raster <= gesamt and len(wuensche) < 120:
            t = k * raster
            k += 1
            lauf = 0.0
            for datei, laenge in zip(dateien, dauern):
                if t < lauf + laenge or datei is dateien[-1]:
                    wuensche.append((datei, max(0.0, t - lauf)))
                    break
                lauf += laenge
        anzahl = self._thumbs.anfordern(wuensche, max(24, self.timeline.height()))
        if anzahl:
            print(f"[THUMB] Grundstock: {anzahl} Bilder ueber {gesamt:.0f}s "
                  f"(Raster {raster:.0f}s)")

    def _on_cut_menu(self, start_s, end_s, global_pos):
        """Rechtsklick auf einen Schnitt in der Zeitleiste.

        Bis 6.01 schaltete der Klick sofort zwischen Blende und harter Kante.
        Jetzt gibt es ein Menue, weil das Zuruecknehmen dazugekommen ist.
        """
        from PySide6.QtWidgets import QMenu

        menue = QMenu(self)
        titel = menue.addAction(f"Cut {self._sek_kurz(start_s)} – {self._sek_kurz(end_s)}")
        titel.setEnabled(False)
        menue.addSeparator()

        hart = self.cut_manager.is_hard_cut(start_s, end_s)
        total_dur = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        # Start- und Endschnitt werden vor dem Zusammenfuegen weggetrimmt und
        # haben deshalb nie eine Blende - dort ist auch nichts einzustellen.
        rand = (abs(start_s) < 0.1
                or (total_dur > 0 and abs(end_s - total_dur) < 0.1))

        eigen = self.cut_manager.get_blende(start_s, end_s)
        laenge = self._blende_vorgabe() if eigen is None else eigen
        beschriftung = "With Crossfade" if not hart else "Switch to Crossfade"
        if not hart and not rand:
            beschriftung += " (%.1f s%s)" % (
                laenge, "" if eigen is not None else ", default")
        a_blende = menue.addAction(beschriftung)
        a_blende.setCheckable(True)
        a_hart = menue.addAction("Hard Cut")
        a_hart.setCheckable(True)
        if rand:
            # Der erste und der letzte Schnitt werden vor dem Zusammenfuegen
            # weggetrimmt: sie sind IMMER eine harte Kante. Das Menue hat sie
            # bisher als Blende angehakt und beim Klick abgewiesen - der Haken
            # sagt jetzt gleich die Wahrheit, und umschalten laesst sich
            # nichts.
            a_blende.setChecked(False)
            a_hart.setChecked(True)
            a_blende.setEnabled(False)
            a_hart.setEnabled(False)
            hinweis = ("The first and the last cut are trimmed away before "
                       "encoding, so they are always a hard cut.")
            a_blende.setToolTip(hinweis)
            a_hart.setToolTip(hinweis)
        else:
            a_blende.setChecked(not hart)
            a_hart.setChecked(hart)

        a_laenge = menue.addAction("Crossfade length …")
        a_laenge.setEnabled(not rand and not hart)
        if rand:
            a_laenge.setToolTip("The first and the last cut are trimmed away "
                                "before encoding, so they are always a hard "
                                "cut.")
        elif hart:
            a_laenge.setToolTip("This cut is a hard cut. Switch it to a "
                                "crossfade first.")
        menue.addSeparator()

        moeglich, grund, warnung = self.cut_manager.ruecknahme_moeglich(
            start_s, end_s, self._gpx_data)
        # Der Tastenhinweis steht hinter einem Tabulator - Qt setzt ihn
        # dadurch rechtsbuendig, wie bei jedem anderen Menuepunkt mit Kuerzel.
        a_weg = menue.addAction("Undo Cut"
                                + (" …" if warnung else "")
                                + "\tDel")
        a_weg.setEnabled(moeglich)
        a_weg.setToolTip(grund or warnung)

        v_moeglich, v_grund = self._verschieben_moeglich(start_s, end_s)
        a_move = menue.addAction("Move Cut …")
        a_move.setEnabled(v_moeglich)
        a_move.setToolTip(v_grund)

        gewaehlt = menue.exec(global_pos)
        if gewaehlt is None:
            return
        if gewaehlt in (a_blende, a_hart):
            if (gewaehlt is a_hart) != hart:
                self._on_cut_hard_toggle(start_s, end_s)
        elif gewaehlt is a_weg:
            self._schnitt_zuruecknehmen(start_s, end_s)
        elif gewaehlt is a_laenge:
            self._blende_dialog(start_s, end_s)
        elif gewaehlt is a_move:
            self._verschiebe_dialog(start_s, end_s)

    @staticmethod
    def _sek_kurz(s: float) -> str:
        s = max(0.0, float(s))
        return f"{int(s // 60):02d}:{int(s % 60):02d}"

    # ------------------------------------------------------------------
    # Merge-Fade an den Naehten der Videoliste
    # ------------------------------------------------------------------
    # Ein Uebergang an einer Dateigrenze, der NICHTS wegnimmt: beide Videos
    # laufen ungekuerzt weiter, vor der Naht wird das erste Bild des
    # folgenden Videos als Standbild eingeblendet, danach das letzte Bild des
    # vorigen wieder ausgeblendet (siehe ges_encoder_manager
    # ._merge_fades_setzen). Kein Schnitt, keine GPX-Aenderung, keine
    # Laengenaenderung - deshalb auch keine Aufzeichnung und keine
    # Ruecknahme. Ob an einer Naht nichts, ein Merge-Fade oder ein Schnitt
    # liegt, entscheidet allein der Benutzer.

    def _naht_zeit(self, naht: int):
        """Rohzeit der Naht Nummer `naht` (0 = zwischen Video 1 und 2), oder None."""
        dauern = getattr(self, "video_durations", None) or []
        if naht < 0 or naht >= len(dauern) - 1:
            return None
        return float(sum(dauern[:naht + 1]))

    def _merge_fade_laenge(self, naht: int) -> float:
        """Laenge des Merge-Fade an dieser Naht, 0 wenn keiner gesetzt ist.

        Nur im Encode-Mode: im Copy-Mode wird das Material durchgereicht,
        dort gibt es keinen Uebergang - wie bei den Blenden der Schnitte.
        """
        if getattr(self, "_edit_mode", "") != "encode":
            return 0.0
        return self.cut_manager.merge_fade_laenge(naht, self._blende_vorgabe())

    def _merge_fades_aktiv(self):
        """[(naht, rohzeit, laenge)] fuer alle Naehte mit Merge-Fade.

        EINE Quelle fuer Vorschau, Nachreichen, Zeitleiste und Export, damit
        keiner der vier etwas anderes zeigt als die anderen.
        """
        liste = []
        dauern = getattr(self, "video_durations", None) or []
        for naht in range(max(0, len(dauern) - 1)):
            laenge = self._merge_fade_laenge(naht)
            if laenge <= 0:
                continue
            zeit = self._naht_zeit(naht)
            if zeit is None:
                continue
            liste.append((naht, zeit, laenge))
        return liste

    def _merge_fade_hoechstwert(self, naht: int) -> float:
        """Wie lang der Merge-Fade an dieser Naht hoechstens sein darf.

        Je die halbe Laenge liegt vor und hinter der Naht. Beide Haelften
        muessen in das Material passen, das dort im Ergebnis zu sehen ist:
        bis zum naechsten Schnitt oder bis zum Anfang beziehungsweise Ende
        des Videos. Liegt die Naht selbst in einem Schnitt, kommt sie im
        Ergebnis nicht vor, dann ist hier nichts einzustellen.
        """
        zeit = self._naht_zeit(naht)
        gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        if zeit is None or gesamt <= 0:
            return 0.0
        links, rechts = zeit, gesamt - zeit
        for (a, b) in self.cut_manager.get_merged_cut_intervals():
            if a < zeit < b:
                return 0.0
            if b <= zeit:
                links = min(links, zeit - b)
            if a >= zeit:
                rechts = min(rechts, a - zeit)
        return max(0.0, min(30.0, 2.0 * min(links, rechts)))

    # ------------------------------------------------------------------
    # Sprechstellen des Voice Removers (ab 7.0)
    # ------------------------------------------------------------------
    # Gehalten werden sie je Datei in Sekunden der Datei (_sprechstellen);
    # Zeitleiste und Audio Zoom zeigen sie in Gesamtzeit der Videoliste.
    # Die Umrechnung geht ueber die Laengen in video_durations - dieselbe
    # Achse wie beim Marker und den Schnitten.

    def _datei_versatz(self, pfad):
        """Beginn der Datei in Gesamtzeit, oder None wenn nicht geladen."""
        try:
            idx = self.playlist.index(pfad)
        except ValueError:
            return None
        return sum(self.video_durations[:idx])

    def _global_zu_datei(self, zeit_s):
        """Gesamtzeit -> (pfad, Sekunde der Datei). Am Ende: letzte Datei."""
        if not self.playlist:
            return None, 0.0
        versatz = 0.0
        for pfad, dauer in zip(self.playlist, self.video_durations):
            if zeit_s < versatz + dauer:
                return pfad, max(0.0, zeit_s - versatz)
            versatz += dauer
        return self.playlist[-1], max(0.0, zeit_s - (versatz - self.video_durations[-1]))

    def _sprechstellen_global(self):
        """Alle Stellen als [(von, bis)] in Gesamtzeit, sortiert."""
        liste = []
        for pfad, stellen in self._sprechstellen.items():
            versatz = self._datei_versatz(pfad)
            if versatz is None:
                continue
            for von, bis in stellen:
                liste.append((versatz + float(von), versatz + float(bis)))
        liste.sort()
        return liste

    def _sprechstellen_export(self):
        """Der Abschnitt fuer Export und Projektdatei: nur geladene Dateien,
        nur nichtleere Listen."""
        return {pfad: [[round(float(a), 3), round(float(b), 3)] for a, b in stellen]
                for pfad, stellen in self._sprechstellen.items()
                if stellen and pfad in self.playlist}

    def _schnitte_global(self):
        """Die Schnitte als [(von, bis)] in Gesamtzeit, oder []."""
        try:
            return [(float(a), float(b)) for a, b in self.cut_manager.get_cut_intervals()]
        except Exception:
            return []

    def _sprechstellen_summe(self):
        """(Anzahl, Sekunden) ueber alle geladenen Dateien - nur der Teil,
        der NICHT weggeschnitten ist: nur der wird beim Export getrennt."""
        gesamt = float(sum(self.video_durations))
        behalten = self._compute_keep_intervals(self._schnitte_global(), gesamt) \
            if gesamt > 0 else []
        anzahl, sekunden = 0, 0.0
        for a, b in self._sprechstellen_global():
            teil = sum(max(0.0, min(b, kb) - max(a, ka)) for ka, kb in behalten)
            if teil > 0:
                anzahl += 1
                sekunden += teil
        return anzahl, sekunden

    def _pegelkurve_global(self):
        """Der Pegelverlauf aller Dateien aus dem Zwischenspeicher, in
        Gesamtzeit. Dateien ohne Eintrag fehlen - dort bleibt es leer."""
        punkte = []
        for pfad in self.playlist:
            versatz = self._datei_versatz(pfad)
            daten = verkehr.aus_cache(pfad)
            if versatz is None or daten is None:
                continue
            for i, db in enumerate(daten.get("pegel") or []):
                punkte.append((versatz + i * verkehr.RAHMEN_S, float(db)))
        return punkte

    def sprechstellen_bedienbar(self) -> bool:
        """Ob Seite A und die Baender ueberhaupt zu sehen sind: nur im
        Encode-Mode, mit Voice-Zusatz (Lite: nie), und wenn im Encoder Setup
        "Remove voices" an ist. Sonst ergibt Markieren keinen Sinn (Bernd,
        10.09.2026: "dann darf ich das ganze Audio-Gedoens eigentlich nicht
        sehen"). Die Stellen selbst bleiben gespeichert."""
        if getattr(self, "_edit_mode", "") != "encode":
            return False
        if not stimme.verfuegbar()[0]:
            return False
        return bool(QSettings("KVRouite", "KVRouite").value("encoder/voice", 0, type=int))

    def _sprechstellen_bedienung_nachziehen(self):
        """Seite A des Video-Controls und die Baender an den Schalter
        "Remove voices" haengen."""
        self.video_control.voice_seite_anbieten(self.sprechstellen_bedienbar())
        self._sprechstellen_anzeigen()

    def _sprechstellen_anzeigen(self):
        """Zeitleiste und Audio Zoom nachziehen. Ohne eingeschalteten Voice
        Remover bleiben die Baender unsichtbar (sprechstellen_bedienbar)."""
        stellen = self._sprechstellen_global() if self.sprechstellen_bedienbar() else []
        self.timeline.set_sprechstellen(stellen)
        self.audio_zoom.set_sprechstellen(stellen)
        self.audio_zoom.set_schnitte(self._schnitte_global())
        self.audio_zoom.set_gesamt(sum(self.video_durations))
        if not self.playlist:
            # Keine Videos, keine Tonspur - auch nicht die alte.
            self.timeline.set_pegelkurve([])
            self.audio_zoom.set_pegelkurve([])
            self.audio_zoom.set_zeit(0.0)
            return
        if self.timeline.audio_an() or self.audio_zoom.isVisible():
            kurve = self._pegelkurve_global()
            self.timeline.set_pegelkurve(kurve)
            self.audio_zoom.set_pegelkurve(kurve)

    def _sprechstellen_laden(self, project_data):
        """"voice_regions" aus einer Projektdatei. Aeltere Projekte haben
        den Schluessel nicht - dann gibt es keine Stellen."""
        daten = project_data.get("voice_regions")
        self._sprechstellen = {}
        if isinstance(daten, dict):
            for pfad, stellen in daten.items():
                if pfad not in self.playlist:
                    continue
                sauber = []
                for eintrag in stellen or []:
                    try:
                        a, b = float(eintrag[0]), float(eintrag[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                    if b > a >= 0:
                        sauber.append([a, b])
                if sauber:
                    self._sprechstellen[pfad] = sorted(sauber)
        self._sprechstellen_anzeigen()

    def stimmen_suchen(self, empfindlichkeit):
        """Der Suchlauf hinter "Detect voices" (views/audio_setup_seite).

        Faehrt jede Datei der Videoliste ab (core/verkehr, aus dem
        Zwischenspeicher wenn schon geschehen) und setzt die Sprechstellen
        aus dem Detektor (core/sprache) - vorhandene Stellen werden ERSETZT,
        auch die von Hand gesetzten. Rueckgabe (Anzahl, Sekunden), oder None
        wenn abgebrochen.
        """
        if not self.playlist:
            QMessageBox.information(self, "Detect voices", "No videos loaded.")
            return (0, 0.0)
        ok, grund = sprache.verfuegbar()
        if not ok:
            QMessageBox.warning(self, "Detect voices", "Detector not available: " + grund)
            return (0, 0.0)
        empfindlichkeit = max(1, min(sprache.EMPFINDLICHKEIT_MAX, int(empfindlichkeit)))
        alle = self._audio_abfahren("Detect voices")
        if alle is None:
            return None
        gefunden = {}
        for pfad, daten in alle.items():
            name = os.path.basename(pfad)
            werte = daten.get("sprache")
            if werte is None:
                print(f"[VOICE] {name}: no speech probabilities - detector "
                      f"not available while scanning")
                continue
            stellen = sprache.stellen(werte, empfindlichkeit, daten.get("dauer"))
            if stellen:
                gefunden[pfad] = [[float(a), float(b)] for a, b in stellen]
            print(f"[VOICE] {name}: sensitivity {empfindlichkeit}, "
                  f"{len(stellen)} stretch(es), {sprache.gesamt_s(stellen):.0f}s")
        self._sprechstellen_undo_merken("Voices detected")
        self._sprechstellen = gefunden
        self._sprechstellen_anzeigen()
        return self._sprechstellen_summe()

    def _audio_abfahren(self, titel):
        """Die Tonspur jeder Datei der Videoliste abfahren (core/verkehr:
        Pegel und Sprachwerte, aus dem Zwischenspeicher wenn schon
        geschehen), mit Fortschrittsdialog. Rueckgabe {pfad: daten} oder
        None bei Abbruch. Gemeinsamer Unterbau von "Detect" und der
        Ton-Ansicht der Zeitleiste."""
        from PySide6.QtWidgets import QProgressDialog, QApplication
        offen = [p for p in self.playlist if verkehr.aus_cache(p) is None]
        ergebnis = {}
        if not offen:
            for pfad in self.playlist:
                ergebnis[pfad] = verkehr.aus_cache(pfad)
            return ergebnis
        dialog = QProgressDialog("Scanning the audio...", "Cancel", 0,
                                 100 * len(offen), self)
        dialog.setWindowTitle(titel)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        QApplication.processEvents()

        def abbruch():
            QApplication.processEvents()
            return dialog.wasCanceled()

        try:
            nr = 0
            for pfad in self.playlist:
                name = os.path.basename(pfad)
                daten = verkehr.aus_cache(pfad)
                if daten is None:
                    dialog.setLabelText(f"{name}: scanning the audio track...")

                    def fortschritt(prozent, _nr=nr):
                        dialog.setValue(_nr * 100 + int(prozent))
                        QApplication.processEvents()

                    daten = verkehr.analyse(pfad, print, fortschritt, abbruch)
                    nr += 1
                    if dialog.wasCanceled():
                        return None
                ergebnis[pfad] = daten
        except verkehr.Abgebrochen:
            return None
        except Exception as exc:
            dialog.close()
            QMessageBox.critical(self, titel, f"Scan failed:\n{exc}")
            return None
        finally:
            dialog.close()
        return ergebnis

    def _sprechstellen_undo_merken(self, name):
        """Den Stand der Sprechstellen vor einer Aenderung auf den
        Strg+Z-Stapel legen - in derselben Reihe wie Schnitte, Overlays und
        GPX-Aenderungen (Bernd, 10.09.2026: Voice fehlte im Undo-Verlauf)."""
        stand = {pfad: [list(s) for s in stellen]
                 for pfad, stellen in self._sprechstellen.items()}

        def zuruecknehmen():
            self._sprechstellen = stand
            self._sprechstellen_anzeigen()

        self._undo_ablegen(zuruecknehmen, name)

    def _sprechstelle_entfernen(self, von_s, bis_s, merken=True):
        """Die Stelle, die (in Gesamtzeit) bei von_s..bis_s liegt, weg."""
        pfad, lokal = self._global_zu_datei((von_s + bis_s) / 2.0)
        stellen = self._sprechstellen.get(pfad) or []
        rest = [s for s in stellen if not (s[0] <= lokal <= s[1])]
        if len(rest) == len(stellen):
            return
        if merken:
            self._sprechstellen_undo_merken("Voices removed")
        if rest:
            self._sprechstellen[pfad] = rest
        else:
            self._sprechstellen.pop(pfad, None)
        self._sprechstellen_anzeigen()

    def _sprechstelle_anlegen(self, von_s, bis_s, merken=True):
        """Neue Stelle in Gesamtzeit; ueber eine Naht hinweg wird sie je
        Datei geteilt. Ueberlappende Stellen werden verschmolzen."""
        if bis_s - von_s < 0.2 or not self.playlist:
            return
        if merken:
            self._sprechstellen_undo_merken("Voices marked")
        versatz = 0.0
        for pfad, dauer in zip(self.playlist, self.video_durations):
            a = max(von_s, versatz) - versatz
            b = min(bis_s, versatz + dauer) - versatz
            versatz += dauer
            if b - a < 0.05:
                continue
            liste = sorted((self._sprechstellen.get(pfad) or []) + [[a, b]])
            neu = []
            for s in liste:
                if neu and s[0] <= neu[-1][1]:
                    neu[-1][1] = max(neu[-1][1], s[1])
                else:
                    neu.append([float(s[0]), float(s[1])])
            self._sprechstellen[pfad] = neu
        self._sprechstellen_anzeigen()

    def _on_sprechstelle_menu(self, von_s, bis_s, global_pos):
        """Rechtsklick auf ein Band in der Zeitleiste (Seite A) - gebaut
        wie das Menue eines Overlays."""
        from PySide6.QtWidgets import QMenu
        menue = QMenu(self)
        titel = menue.addAction(
            "Voices %s - %s  (%.1fs)"
            % (self._sek_kurz(von_s), self._sek_kurz(bis_s), bis_s - von_s))
        titel.setEnabled(False)
        menue.addSeparator()
        a_zeit = menue.addAction("Start and end …")
        menue.addSeparator()
        a_weg = menue.addAction("Remove stretch")
        a_alle = menue.addAction("Remove all stretches")
        gewaehlt = menue.exec(global_pos)
        if gewaehlt is a_weg:
            self._sprechstelle_entfernen(von_s, bis_s)
        elif gewaehlt is a_zeit:
            self._sprechstelle_zeit_dialog(von_s, bis_s)
        elif gewaehlt is a_alle:
            anzahl, _sek = self._sprechstellen_summe()
            antwort = QMessageBox.question(
                self, "Remove all stretches?",
                "Remove all %d marked stretches with voices?" % anzahl,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if antwort == QMessageBox.Yes:
                self._sprechstellen_undo_merken("All voices removed")
                self._sprechstellen = {}
                self._sprechstellen_anzeigen()

    def _sprechstelle_zeit_dialog(self, von_s, bis_s):
        """Anfang und Ende einer Sprechstelle als Zahlen (Gesamtzeit)."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                                       QFormLayout, QLabel, QVBoxLayout)
        gesamt = float(sum(self.video_durations))
        dlg = QDialog(self)
        dlg.setWindowTitle("Voices start and end")
        aussen = QVBoxLayout(dlg)
        form = QFormLayout()

        def _feld(wert):
            sb = QDoubleSpinBox(dlg)
            sb.setDecimals(1)
            sb.setSingleStep(0.5)
            sb.setRange(0.0, gesamt)
            sb.setValue(float(wert))
            sb.setSuffix(" s")
            return sb

        sb_a = _feld(von_s)
        sb_b = _feld(bis_s)
        form.addRow("Start", sb_a)
        form.addRow("End", sb_b)
        aussen.addLayout(form)
        hinweis = QLabel(dlg)
        hinweis.setWordWrap(True)
        aussen.addWidget(hinweis)
        knoepfe = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        aussen.addWidget(knoepfe)
        knoepfe.accepted.connect(dlg.accept)
        knoepfe.rejected.connect(dlg.reject)

        def _pruefen():
            laenge = sb_b.value() - sb_a.value()
            ok = laenge >= 0.2
            hinweis.setText("Length %.1f s" % laenge
                            + ("" if ok else "\nThe end must lie behind the start."))
            knoepfe.button(QDialogButtonBox.Ok).setEnabled(ok)

        sb_a.valueChanged.connect(_pruefen)
        sb_b.valueChanged.connect(_pruefen)
        _pruefen()
        if dlg.exec() != QDialog.Accepted:
            return
        self._sprechstellen_undo_merken("Voices moved")
        self._sprechstelle_entfernen(von_s, bis_s, merken=False)
        self._sprechstelle_anlegen(round(sb_a.value(), 3), round(sb_b.value(), 3), merken=False)

    def _on_voice_button_clicked(self):
        """Knopf "Voice" auf Seite A: der Bereich [- bis -] wird eine
        Sprechstelle - wie "Ovl" aus demselben Bereich ein Overlay macht."""
        von, bis = self.timeline.markB_time_s, self.timeline.markE_time_s
        if von is None or bis is None or von < 0 or bis < 0:
            QMessageBox.information(
                self, "Voices",
                "Mark the stretch first: [- at its begin, -] at its end.")
            return
        if bis - von < 0.2:
            QMessageBox.information(
                self, "Voices", "The end must lie behind the start.")
            return
        self._sprechstelle_anlegen(float(von), float(bis))
        # Die Markierung ist verbraucht - weg damit, wie nach "x". Sonst
        # sieht es aus, als waere nichts geschehen.
        self.cut_manager.on_markClear_clicked()
        self.timeline.set_markB_time(-1)
        self.timeline.set_markE_time(-1)
        self.on_deselect_clicked()
        self.statusBar().showMessage(
            "Voices %s - %s marked" % (self._sek_kurz(von), self._sek_kurz(bis)), 4000)

    def _on_find_voices_clicked(self):
        """Knopf "Detect" auf Seite A: Stimmen finden und sofort markieren."""
        if not self.playlist:
            QMessageBox.information(self, "Detect voices", "No videos loaded.")
            return
        anzahl, _sek = self._sprechstellen_summe()
        if anzahl:
            antwort = QMessageBox.question(
                self, "Detect voices",
                "The search replaces the %d marked stretches. Continue?" % anzahl,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if antwort != QMessageBox.Yes:
                return
        ergebnis = self.stimmen_suchen(self.video_control.sensitivity())
        if ergebnis is None:
            self.statusBar().showMessage("Detect voices cancelled.", 4000)
            return
        anzahl, sekunden = ergebnis
        if anzahl == 0:
            QMessageBox.information(
                self, "Detect voices",
                "No speech found. Raise the sensitivity (Sens) or mark the "
                "stretches by hand ([-, -], Voice).")
        else:
            self.statusBar().showMessage(
                "%d stretch(es) with voices marked, %.0f s - check them in the "
                "timeline; detection is never complete." % (anzahl, sekunden), 10000)

    def _on_sensitivity_changed(self, wert: int):
        QSettings("KVRouite", "KVRouite").setValue(sprache.EINSTELLUNG_KEY, int(wert))

    def _on_naht_menu(self, naht: int, zeit: float, global_pos):
        """Rechtsklick auf eine Naht der Videoliste in der Zeitleiste."""
        from PySide6.QtWidgets import QMenu

        dateien = getattr(self, "playlist", None) or []
        if naht < 0 or naht + 1 >= len(dateien):
            return
        menue = QMenu(self)
        titel = menue.addAction(
            f"Join {naht + 1} | {naht + 2} at {self._sek_kurz(zeit)}")
        titel.setEnabled(False)
        namen = menue.addAction(
            f"{os.path.basename(dateien[naht])}  →  "
            f"{os.path.basename(dateien[naht + 1])}")
        namen.setEnabled(False)
        menue.addSeparator()

        an = self.cut_manager.hat_merge_fade(naht)
        eigen = self.cut_manager.get_merge_fade(naht)
        laenge = self._blende_vorgabe() if eigen is None else eigen
        beschriftung = "Merge-Fade"
        if an:
            beschriftung += " (%.1f s%s)" % (
                laenge, "" if eigen is not None else ", default")
        a_fade = menue.addAction(beschriftung)
        a_fade.setCheckable(True)
        a_fade.setChecked(an)
        a_hart = menue.addAction("Hard join")
        a_hart.setCheckable(True)
        a_hart.setChecked(not an)
        a_laenge = menue.addAction("Merge-Fade length …")
        a_laenge.setEnabled(an)
        if not an:
            a_laenge.setToolTip("This join is hard. Switch on the Merge-Fade "
                                "first.")
        if getattr(self, "_edit_mode", "") != "encode":
            menue.addSeparator()
            hinweis = menue.addAction("Shown and exported in Encode-Mode only")
            hinweis.setEnabled(False)

        gewaehlt = menue.exec(global_pos)
        if gewaehlt is None:
            return
        if gewaehlt is a_fade:
            self._merge_fade_setzen(naht, not an)
        elif gewaehlt is a_hart:
            if an:
                self._merge_fade_setzen(naht, False)
        elif gewaehlt is a_laenge:
            self._merge_fade_dialog(naht)

    def _merge_fade_setzen(self, naht: int, an: bool, laenge=None):
        """Merge-Fade an dieser Naht an- oder abschalten - EIN Undo-Schritt."""
        if an:
            hoechst = self._merge_fade_hoechstwert(naht)
            if hoechst <= 0.0:
                QMessageBox.information(
                    self, "No room for a Merge-Fade",
                    "This join lies inside a cut or directly next to one, so "
                    "there is no material on both sides to fade over.")
                return
            if laenge is None and self._blende_vorgabe() > hoechst + 1e-6:
                # Die Vorgabe passt nicht - dann die groesste Laenge, die
                # passt, als eigene Laenge festhalten, und das sagen.
                laenge = self._blende_abrunden(hoechst)
                QMessageBox.information(
                    self, "Merge-Fade shortened",
                    "The default of %.1f s does not fit here; the Merge-Fade "
                    "is set to %.1f s." % (self._blende_vorgabe(), laenge))
        self.register_video_undo_snapshot(
            False, "Merge-Fade %s at join %d" % ("on" if an else "off", naht + 1))
        self.cut_manager.set_merge_fade(naht, an, laenge)
        print(f"[MERGE-FADE] Naht {naht + 1} => "
              f"{('%.1f s' % self._merge_fade_laenge(naht)) if an else 'hart'}")
        self.timeline.update()
        self._refresh_preview_timeline()

    def _merge_fade_dialog(self, naht: int):
        """Laenge des Merge-Fade an dieser Naht einstellen."""
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QDoubleSpinBox, QFormLayout, QLabel,
                                       QVBoxLayout)

        vorgabe = self._blende_vorgabe()
        eigen = self.cut_manager.get_merge_fade(naht)
        hoechst = self._merge_fade_hoechstwert(naht)

        dlg = QDialog(self)
        dlg.setWindowTitle("Merge-Fade length")
        aussen = QVBoxLayout(dlg)

        kasten = QCheckBox("Use the default from Encoder Setup (%.1f s)"
                           % vorgabe, dlg)
        kasten.setChecked(eigen is None)
        aussen.addWidget(kasten)

        form = QFormLayout()
        sb = QDoubleSpinBox(dlg)
        sb.setDecimals(1)
        sb.setSingleStep(0.1)
        sb.setRange(0.1, max(0.1, hoechst))
        sb.setValue(float(vorgabe if eigen is None else eigen))
        sb.setSuffix(" s")
        form.addRow("Length", sb)
        aussen.addLayout(form)

        hinweis = QLabel(dlg)
        hinweis.setWordWrap(True)
        hinweis.setText(
            "At most %.1f s here. Half of it lies before the join, half "
            "behind it. Nothing is cut away: before the join the first frame "
            "of the next video fades in as a still, after the join the last "
            "frame of the previous video fades out.\n\n"
            "Arrows and mouse wheel step 0.1 s, Page Up/Down 1 s." % hoechst)
        aussen.addWidget(hinweis)

        knoepfe = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        aussen.addWidget(knoepfe)
        knoepfe.accepted.connect(dlg.accept)
        knoepfe.rejected.connect(dlg.reject)

        def _umschalten():
            sb.setEnabled(not kasten.isChecked())
            if kasten.isChecked():
                sb.setValue(float(vorgabe))
        kasten.toggled.connect(_umschalten)
        _umschalten()

        if hoechst <= 0.0:
            hinweis.setText("There is no room for a Merge-Fade here: the join "
                            "lies inside a cut or directly next to one.")
            sb.setEnabled(False)
            kasten.setEnabled(False)
            knoepfe.button(QDialogButtonBox.Ok).setEnabled(False)

        if dlg.exec() != QDialog.Accepted:
            return
        neu = None if kasten.isChecked() else round(sb.value(), 1)
        if neu is None and vorgabe > hoechst + 1e-6:
            neu = self._blende_abrunden(hoechst)
            QMessageBox.information(
                self, "Merge-Fade shortened",
                "The default of %.1f s does not fit here; the Merge-Fade is "
                "set to %.1f s." % (vorgabe, neu))
        self._merge_fade_setzen(naht, True, neu)

    def _make_merge_fade_job(self, naht: int, zeit: float, laenge: float):
        """Der Vorschau-Schnipsel fuer einen Merge-Fade.

        Seite A ist das durchlaufende Material von einer halben Laenge vor
        bis eine halbe Laenge nach der Naht - zwei Stuecke, je Datei eins.
        Darueber die beiden Standbilder, GEDREHT gezogen: fade_cache rendert
        den Schnipsel aufgerichtet, mit der Bildlage der Quellen, und die
        Vorschau legt ihm keine Drehung mehr auf (siehe fade_cache).
        """
        from core.standbild import pfad_fuer

        dateien = getattr(self, "playlist", None) or []
        durations = getattr(self, "video_durations", None) or []
        if (laenge <= 0 or naht + 1 >= len(dateien)
                or len(durations) != len(dateien)):
            return None
        halb = laenge / 2.0
        gesamt = sum(durations)
        if zeit - halb < -1e-6 or zeit + halb > gesamt + 1e-6:
            print(f"[DEBUG] Merge-Fade an Naht {naht + 1}: Fenster reicht "
                  f"ueber Anfang oder Ende des Videos hinaus, bleibt hart")
            return None

        teile = []
        start = 0.0
        for pfad, d in zip(dateien, durations):
            von = max(zeit - halb, start)
            bis = min(zeit + halb, start + d)
            if bis - von > 0:
                teile.append((pfad, von - start, bis - von))
            start += d
        if not teile:
            return None

        # Nur die PFADE der Standbilder - gezogen werden sie erst beim
        # Rendern, wenn das Vorbereitungsfenster steht. Hier zu ziehen hiess
        # bei 4K-Material mehrere Sekunden ohne jedes Fenster.
        png_erstes = pfad_fuer(dateien[naht + 1], 0.0, True)
        png_letztes = pfad_fuer(dateien[naht], None, True)
        standbilder = [
            (png_erstes, 0.0, halb, 0.0, 0.5),
            (png_letztes, halb, halb, 0.5, 0.0),
        ]
        quellen = [
            (png_erstes, dateien[naht + 1], 0.0, True),
            (png_letztes, dateien[naht], None, True),
        ]
        fps = framerate.lesen(dateien[naht]) or (30000, 1001)
        return FadeJob(teile, [], float(laenge),
                       self.video_editor.preview_width(), fps,
                       standbilder=standbilder, standbild_quellen=quellen)

    def _schnitt_zuruecknehmen(self, start_s, end_s):
        """Einen Schnitt rueckgaengig machen - Video und GPX-Spur.

        Reihenfolge: erst die Spur zurueckrechnen, dann den Schnitt aus der
        Video-Seite nehmen. Schlaegt das Zurueckrechnen fehl, bleibt alles
        wie es war.
        """
        moeglich, grund, warnung = self.cut_manager.ruecknahme_moeglich(
            start_s, end_s, self._gpx_data)
        if not moeglich:
            QMessageBox.information(self, "Undo not possible", grund)
            return

        if warnung:
            antwort = QMessageBox.warning(
                self, "Track was edited in the meantime", warnung,
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if antwort != QMessageBox.Yes:
                return

        # Beides zusammen ist EIN Schritt fuer Strg+Z.
        schritt = f"Take back cut {start_s:.3f}-{end_s:.3f} s"
        self.register_gpx_undo_snapshot(schritt)
        self.register_video_undo_snapshot(True, schritt)

        if not self._ruecknahme_ausfuehren(start_s, end_s):
            QMessageBox.warning(self, "Undo failed",
                                "The GPX track could not be restored. "
                                "Nothing was changed.")

    def _ruecknahme_ausfuehren(self, start_s, end_s) -> bool:
        """Die Ruecknahme selbst - ohne Rueckfragen, ohne Schnappschuesse.

        Getrennt vom Pruefteil, weil das Verschieben eines Schnitts denselben
        Weg geht: erst zuruecknehmen, dann an der neuen Stelle neu schneiden.
        Beide Aufrufer bringen ihre eigenen Rueckfragen und ihren eigenen
        Strg+Z-Schritt mit.

        Rueckgabe False, wenn nichts geaendert wurde.
        """
        from core.gpx_parser import recalc_gpx_data

        vorher_n = len(self._gpx_data or [])
        neue_spur = self.cut_manager.spur_ohne_schnitt(
            start_s, end_s, self._gpx_data)
        if not neue_spur or len(neue_spur) < 2:
            return False

        # Anfang und Dauer merken, BEVOR schnitt_entfernen() die Aufzeichnung
        # wegwirft - beides wird gleich zum Nachfuehren gebraucht.
        aufz = self.cut_manager.aufzeichnung(start_s, end_s) or {}
        nachfuehr_ab = aufz.get("beginn_dt")
        nachfuehr_um = float(aufz.get("dauer_s") or 0.0)
        # Der Startschnitt verschiebt zusaetzlich die ganze Zeitachse und
        # stellt den Video/GPX-Versatz auf 0. Beides gehoert zurueckgedreht.
        nachfuehr_achse = float(aufz.get("achsen_versatz_s") or 0.0)
        shift_vorher = aufz.get("video_shift_vorher")

        if not self.cut_manager.schnitt_entfernen(start_s, end_s):
            print("[CUT-UNDO] Schnitt war nicht mehr vorhanden, Abbruch")
            return False

        # Alles hinter dem zurueckgenommenen Schnitt liegt jetzt wieder um
        # dessen Dauer spaeter. Die Aufzeichnungen der dahinterliegenden
        # Schnitte muessen das mitmachen, sonst zeigen sie ins Leere und die
        # Spur kaeme dort still falsch zurueck.
        if nachfuehr_achse:
            # Startschnitt: die ganze Achse kommt zurueck, also muessen ALLE
            # uebrigen Aufzeichnungen mit - nicht nur die dahinter.
            nachgefuehrt = self.cut_manager.aufzeichnungen_nachfuehren(
                None, +nachfuehr_achse, alle=True)
        else:
            nachgefuehrt = self.cut_manager.aufzeichnungen_nachfuehren(
                nachfuehr_ab, +nachfuehr_um)

        recalc_gpx_data(neue_spur)
        self.gpx_widget.set_gpx_data(neue_spur)
        self._gpx_data = neue_spur
        self._update_gpx_overview()
        self.chart.set_gpx_data(neue_spur)
        if self.mini_chart_widget:
            self.mini_chart_widget.set_gpx_data(neue_spur)
        self.map_widget.loadRoute(
            self._build_route_geojson_from_gpx(neue_spur), do_fit=False)

        if nachfuehr_achse:
            # Der Startschnitt hatte den Video/GPX-Versatz auf 0 gesetzt.
            # Ohne das Zurueckstellen laege die Spur nach der Ruecknahme um
            # den alten Versatz neben dem Video. Gleiches Muster wie in
            # register_gpx_undo_snapshot(): None heisst "gar nicht gesetzt".
            set_gpx_video_shift(shift_vorher)
            if not is_gpx_video_shift_set():
                # Nur dann umschalten. enableVideoGpxSync(True) geht ueber
                # _on_autocut_toggle_clicked(), und das SCHALTET UM - bei
                # bereits eingeschaltetem AutoCut haette es ihn ausgemacht.
                # Dieselbe Bedingung wie in register_gpx_undo_snapshot().
                self.enableVideoGpxSync(False)
            self.video_control.activate_controls()
            print(f"[CUT-UNDO] Video/GPX-Versatz zurueck auf {shift_vorher}")

        # Eigene Aktion: den Zustand der Spur neu festhalten, sonst waeren
        # alle uebrigen Schnitte danach faelschlich gesperrt.
        self.cut_manager.fingerabdruck_merken(self._gpx_data)

        self._refresh_preview_timeline()
        self.timeline.update()
        print(f"[CUT-UNDO] Schnitt {start_s:.3f}-{end_s:.3f} zurueckgenommen, "
              f"Spur {vorher_n} -> {len(neue_spur)}, "
              f"{nachgefuehrt} Aufzeichnung(en) nachgefuehrt")
        return True


    # ------------------------------------------------------------------
    # Schnitte verschieben
    # ------------------------------------------------------------------
    #: Abstand, den ein Mittelschnitt von 0 und vom Videoende haelt. Derselbe
    #: Wert, mit dem is_end_cut() einen Endschnitt erkennt - waere er kleiner,
    #: koennte ein verschobener Mittelschnitt in die Endschnitt-Erkennung
    #: rutschen und beim naechsten Mal ganz anders behandelt werden.
    _VERSCHIEBE_EPS = 0.1

    def _ist_startschnitt(self, start_s, end_s) -> bool:
        """Stammt dieser Schnitt von "Set Begin"?

        Erkannt am Achsenversatz in der Aufzeichnung und nicht daran, dass er
        bei 0 beginnt: ein Mittelschnitt kann ebenfalls bei 0 anfangen, wenn
        MarkB dort gesetzt wurde. Der Unterschied ist nicht die Lage, sondern
        was der Schnitt getan hat - nur "Set Begin" verschiebt die Zeitachse.
        """
        aufz = self.cut_manager.aufzeichnung(start_s, end_s) or {}
        return bool(aufz.get("achsen_versatz_s"))

    def _verschiebe_grenzen(self, start_s, end_s):
        """In welchem Bereich darf dieser Schnitt liegen?

        Rueckgabe (links, rechts, art) mit art aus "anfang", "ende",
        "mitte". Anschlag sind die Nachbarschnitte und die Videogrenzen.

        Ein Schnitt behaelt dabei seine Art. Zoege man einen Mittelschnitt bis
        ans Videoende, waere er beim naechsten Mal ein Endschnitt - der wird
        vor dem Zusammenfuegen weggetrimmt, hat nie eine Blende und behandelt
        die GPX-Spur anders. Diese Verwandlung soll nicht beilaeufig durch
        Ziehen passieren, deshalb der Abstand von _VERSCHIEBE_EPS.
        """
        gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        eps = self._VERSCHIEBE_EPS
        links, rechts = 0.0, gesamt

        for (a, b) in self.cut_manager._cut_intervals:
            if abs(a - start_s) < 1e-9 and abs(b - end_s) < 1e-9:
                continue
            if b <= start_s + 1e-9:
                links = max(links, float(b))
            elif a >= end_s - 1e-9:
                rechts = min(rechts, float(a))

        # Die Art entscheidet die LAGE, nicht die Aufzeichnung: ein Schnitt
        # bei 0 wird auch vom Export als Anfangsschnitt behandelt
        # (skip_array-Wert -2), unabhaengig davon, wie er entstanden ist.
        if start_s < eps:
            art = "anfang"
        elif gesamt > 0 and abs(end_s - gesamt) < eps:
            art = "ende"
        else:
            art = "mitte"

        if art != "ende":
            rechts = min(rechts, max(0.0, gesamt - eps))
        if art != "anfang":
            links = max(links, eps)
        return links, rechts, art

    def _verschieben_moeglich(self, start_s, end_s):
        """Darf dieser Schnitt umziehen? Rueckgabe (moeglich, grund).

        Verschieben IST Zuruecknehmen plus Neuschneiden, es gelten deshalb
        dieselben Bedingungen wie fuers Zuruecknehmen. Ohne GPX-Spur gibt es
        nichts zurueckzurechnen - dann ist es ein reiner Video-Umzug.
        """
        links, rechts, _art = self._verschiebe_grenzen(start_s, end_s)
        if rechts - links < 0.02:
            return False, ("There is no room between the neighbouring cuts.")

        if not self._gpx_data:
            return True, ""

        # Ein Schnitt, der die Spur mitgeschnitten hat, darf nur umziehen,
        # solange AutoCutVideo+GPX an ist. Sonst kaeme die Spur zurueck, aber
        # nur der Video-Schnitt zoege um - danach haette das Video weniger
        # Material als die Spur.
        do_gpx = (self._autoSyncVideoEnabled
                  and self._edit_mode in ("copy", "encode"))
        if self.cut_manager.hat_aufzeichnung(start_s, end_s) and not do_gpx:
            return False, ("This cut removed points from the GPX track. Moving "
                           "it would put the track back but move only the video "
                           "cut. Switch AutoCutVideo+GPX on first.")

        moeglich, grund, _warnung = self.cut_manager.ruecknahme_moeglich(
            start_s, end_s, self._gpx_data)
        if not moeglich:
            return False, grund
        return True, ""

    def _schnitt_verschieben(self, alt_start, alt_ende, neu_start, neu_ende):
        """Einen Schnitt an eine andere Stelle setzen.

        Der Weg ist genau der, den man von Hand ginge: den alten Schnitt
        zuruecknehmen und an der neuen Stelle neu schneiden. Beides laeuft
        durch dieselben Funktionen wie sonst auch - das Zuruecknehmen durch
        _ruecknahme_ausfuehren(), das Schneiden durch on_cut_clicked_video().
        Es gibt damit KEINEN zweiten Rechenweg fuer einen Schnitt, der neben
        dem ersten veralten koennte; jede Verbesserung am Schneiden gilt
        automatisch auch fuer den Umzug.

        Waehrend der beiden Teilschritte steht _verschiebe_schritt. Das haelt
        zweierlei zurueck: die Schnappschuesse (fuer Strg+Z ist der Umzug EIN
        Schritt) und den Aufbau der Vorschau (fuer den Zwischenzustand
        wuerden Blenden gerendert, die niemand sieht).

        Rueckgabe True, wenn der Umzug ausgefuehrt wurde.
        """
        moeglich, grund = self._verschieben_moeglich(alt_start, alt_ende)
        if not moeglich:
            QMessageBox.information(self, "Move not possible", grund)
            return False

        if self._gpx_data:
            _m, _g, warnung = self.cut_manager.ruecknahme_moeglich(
                alt_start, alt_ende, self._gpx_data)
            if warnung:
                antwort = QMessageBox.warning(
                    self, "Track was edited in the meantime", warnung,
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
                if antwort != QMessageBox.Yes:
                    return False

        hat_aufz = self.cut_manager.hat_aufzeichnung(alt_start, alt_ende)
        # VOR der Ruecknahme merken: sie wirft die Aufzeichnung weg. Nur ein
        # Schnitt, der die Zeitachse verschoben hat, darf auch wieder ueber
        # den Startschnitt-Weg gesetzt werden. Ein Schnitt, der bloss bei 0
        # anfaengt (MarkB auf 0 und Cut), ist ein gewoehnlicher Schnitt und
        # bleibt einer.
        mit_achse = self._ist_startschnitt(alt_start, alt_ende)

        # Die Blende zieht mit um. Laenge und harte Kante haengen am
        # Schluessel (start, ende); der Umzug nimmt den alten Schnitt zurueck
        # und setzt einen neuen, damit waere die Einstellung weg und der
        # Schnitt fiele auf die Vorgabe zurueck. Wer einen Schnitt um ein paar
        # Millisekunden rueckt, meint aber DIESEN Schnitt samt seiner Blende.
        blende_eigen = self.cut_manager.get_blende(alt_start, alt_ende)
        blende_hart = self.cut_manager.is_hard_cut(alt_start, alt_ende)

        # Nimmt der Schnitt an seiner neuen Stelle einer eingestellten Blende
        # den Platz? Gefragt wird VOR dem Zuruecknehmen - bei Abbruch soll
        # nichts angefangen und wieder rueckgaengig gemacht werden muessen.
        # Die mitziehende Blende steht fuer die Pruefung kurz schon unter dem
        # neuen Schluessel: so prueft dieselbe Rechnung auch, ob SIE an der
        # neuen Stelle noch Platz hat, und die zugesagte Kuerzung haengt
        # gleich am richtigen Schnitt.
        self._blende_vormerken(neu_start, neu_ende, blende_eigen, blende_hart)
        try:
            weiter, blende_kuerzungen = self._blenden_konflikt_fragen(
                self._cuts_mit((float(neu_start), float(neu_ende)),
                               ohne=(alt_start, alt_ende)),
                "Moving this cut")
        finally:
            self._blende_vormerken(neu_start, neu_ende, None, False)
        if not weiter:
            return False

        # Ein Schritt fuer Strg+Z, angelegt bevor irgendetwas passiert.
        schritt = f"Move cut to {neu_start:.3f}-{neu_ende:.3f} s"
        self.register_gpx_undo_snapshot(schritt)
        self.register_video_undo_snapshot(True, schritt)

        self._verschiebe_schritt = True
        try:
            if hat_aufz:
                if not self._ruecknahme_ausfuehren(alt_start, alt_ende):
                    QMessageBox.warning(
                        self, "Move failed",
                        "The GPX track could not be restored. "
                        "Nothing was changed.")
                    return False
            elif not self.cut_manager.schnitt_entfernen(alt_start, alt_ende):
                print("[CUT-MOVE] Schnitt war nicht mehr vorhanden, Abbruch")
                return False

            if mit_achse:
                # Startschnitt: er verschiebt die Zeitachse und stellt den
                # Video/GPX-Versatz. Ueber den gewoehnlichen Weg gesetzt waere
                # er anschliessend ein Mittelschnitt bei 0 - gleiche Lage,
                # andere Wirkung.
                self._startschnitt_setzen(float(neu_ende), nachfragen=False)
            else:
                # Neu schneiden ueber den gewoehnlichen Weg. Die Mark-Zeiten
                # sind dessen Eingabe; on_cut_clicked() setzt sie
                # anschliessend selbst wieder zurueck.
                self.cut_manager.markB_time_s = float(neu_start)
                self.cut_manager.markE_time_s = float(neu_ende)
                self.timeline.set_markB_time(float(neu_start))
                self.timeline.set_markE_time(float(neu_ende))
                self.on_cut_clicked_video()
        finally:
            self._verschiebe_schritt = False

        # Erst die mitgezogene Blende setzen, dann die zugesagte Kuerzung -
        # die darf sie ueberschreiben. Ohne eigene Einstellung wird nichts
        # angefasst: der neue Schnitt folgt dann der Vorgabe, wie bisher.
        if blende_hart or blende_eigen is not None:
            self._blende_vormerken(neu_start, neu_ende,
                                   blende_eigen, blende_hart)
            print("[CUT-MOVE] " + ("harte Kante zieht mit" if blende_hart
                                   else "Blende %.1f s zieht mit"
                                   % blende_eigen))
        self._blenden_kuerzen(blende_kuerzungen)
        self._refresh_preview_timeline()
        self.timeline.update()
        print(f"[CUT-MOVE] Schnitt {alt_start:.3f}-{alt_ende:.3f} -> "
              f"{neu_start:.3f}-{neu_ende:.3f} "
              f"({'mit' if hat_aufz else 'ohne'} GPX-Aufzeichnung)")

        # Overlays koennen durch den Umzug in einen Schnitt geraten oder den
        # Platz fuer ihre Blende verlieren. Die Pruefung dafuer gibt es schon.
        self._validate_overlays_after_xfade_change()
        return True

    def _blende_vormerken(self, start_s, end_s, eigen, hart):
        """Blendeneinstellung unter (start_s, end_s) eintragen oder loeschen.

        eigen None und hart False raeumt den Schluessel. Harte Kante und
        eigene Laenge schliessen sich aus (siehe _blende_dialog): hart steht
        in _hard_cuts, nicht als Laenge 0 daneben.
        """
        if hart:
            self.cut_manager.set_blende(start_s, end_s, None)
            self.cut_manager.set_hard_cut(start_s, end_s, True)
        else:
            self.cut_manager.set_hard_cut(start_s, end_s, False)
            self.cut_manager.set_blende(start_s, end_s, eigen)

    #: Wie viel Vorlauf nach einem Umzug vor der neuen Kante gezeigt wird.
    _UMZUG_VORLAUF_S = 2.0

    def _on_cut_move(self, alt_start, alt_ende, neu_start, neu_ende):
        """Ein Schnitt wurde in der Zeitleiste gezogen.

        Danach wird gleich vor die neue Kante gesprungen, damit man die
        Stelle nur noch abspielen muss, um sie zu beurteilen. Von selbst
        losspielen tut es nicht: der Umzug ist ein Bearbeitungsschritt, und
        eine Bearbeitung soll die Wiedergabe nicht an sich reissen.
        """
        if not self._schnitt_verschieben(alt_start, alt_ende,
                                         neu_start, neu_ende):
            return
        self._umzug_vorfuehren(neu_start)

    def _umzug_vorfuehren(self, neu_start):
        """Kurz vor die neue Schnittkante springen - ohne abzuspielen."""
        ziel = max(0.0, float(neu_start) - self._UMZUG_VORLAUF_S)

        # Nicht in einen anderen Schnitt hinein zuruecksetzen - dort gibt es
        # kein Bild. Das Ende des davorliegenden Schnitts ist die Grenze.
        for (a, bb) in self.cut_manager._cut_intervals:
            if bb <= neu_start + 1e-9 and bb > ziel:
                ziel = float(bb)

        try:
            self.video_editor.seek_global(ziel)
            self.timeline.set_marker_position(ziel)
        except Exception as e:
            print(f"[WARN] Sprung nach dem Umzug: {e}")

    def _blende_dialog(self, start_s, end_s):
        """Blendenlaenge dieses Schnitts einstellen.

        Aendert nur das Video. Die GPX-Spur bleibt unberuehrt - die Blende
        verschiebt keine Zeiten, sie liegt mittig auf der Kante und laesst die
        Gesamtlaenge gleich.
        """
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QDoubleSpinBox, QFormLayout, QLabel,
                                       QVBoxLayout)

        vorgabe = self._blende_vorgabe()
        eigen = self.cut_manager.get_blende(start_s, end_s)
        hoechst = self._blende_hoechstwert(start_s, end_s)

        dlg = QDialog(self)
        dlg.setWindowTitle("Crossfade length")
        aussen = QVBoxLayout(dlg)

        kasten = QCheckBox("Use the default from Encoder Setup (%.1f s)"
                           % vorgabe, dlg)
        kasten.setChecked(eigen is None)
        aussen.addWidget(kasten)

        form = QFormLayout()
        sb = QDoubleSpinBox(dlg)
        sb.setDecimals(1)
        # 0,1 s ist die Aufloesung, mit der gerechnet und gespeichert wird
        # (_blende_abrunden, eine Nachkommastelle). Der Schritt der Pfeile
        # soll nicht groeber sein als das, was man eintippen kann. Fuer die
        # grossen Spruenge gibt es Bild auf/ab: das Zehnfache, also 1 s.
        sb.setSingleStep(0.1)
        sb.setRange(0.0, max(0.0, hoechst))
        sb.setValue(float(vorgabe if eigen is None else eigen))
        sb.setSuffix(" s")
        form.addRow("Length", sb)
        aussen.addLayout(form)

        hinweis = QLabel(dlg)
        hinweis.setWordWrap(True)
        hinweis.setText(
            "At most %.1f s here. The fade lies centred on the cut, so half "
            "of it has to fit into the kept material on each side and half "
            "into the cut itself.\n\n"
            "Arrows and mouse wheel step 0.1 s, Page Up/Down 1 s.\n\n"
            "0 s means a hard cut. This changes the video only - the GPX "
            "track is not touched." % hoechst)
        aussen.addWidget(hinweis)

        knoepfe = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        aussen.addWidget(knoepfe)
        knoepfe.accepted.connect(dlg.accept)
        knoepfe.rejected.connect(dlg.reject)

        def _umschalten():
            sb.setEnabled(not kasten.isChecked())
            if kasten.isChecked():
                sb.setValue(float(vorgabe))
        kasten.toggled.connect(_umschalten)
        _umschalten()

        if hoechst <= 0.0:
            hinweis.setText("There is no room for a crossfade here: the kept "
                            "material next to this cut, or the cut itself, is "
                            "too short.")
            sb.setEnabled(False)
            kasten.setEnabled(False)
            knoepfe.button(QDialogButtonBox.Ok).setEnabled(False)

        if dlg.exec() != QDialog.Accepted:
            return

        neu = None if kasten.isChecked() else round(sb.value(), 1)
        if neu is not None and neu <= 0.0:
            # 0 heisst harte Kante. Die steht in _hard_cuts und nicht als
            # Laenge 0 daneben - sonst gaebe es zwei Schreibweisen dafuer.
            self.cut_manager.set_blende(start_s, end_s, None)
            self.cut_manager.set_hard_cut(start_s, end_s, True)
            print(f"[BLENDE] Schnitt {start_s:.3f}-{end_s:.3f} => harte Kante")
        else:
            self.cut_manager.set_blende(start_s, end_s, neu)
            print(f"[BLENDE] Schnitt {start_s:.3f}-{end_s:.3f} => "
                  f"{'Vorgabe' if neu is None else ('%.1f s' % neu)}")

        self.timeline.update()
        self._refresh_preview_timeline()

    def _verschiebe_dialog(self, start_s, end_s):
        """Anfang und Ende des Schnitts als Zahlen eingeben.

        Der Vorlaeufer zum Ziehen mit der Maus: dieselbe Rechnung dahinter,
        nur ohne Zeigegeraet - und damit ohne die Frage, ob man die richtige
        Kante erwischt hat.
        """
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                                       QFormLayout, QLabel, QVBoxLayout)

        links, rechts, art = self._verschiebe_grenzen(start_s, end_s)

        dlg = QDialog(self)
        dlg.setWindowTitle("Move Cut")
        aussen = QVBoxLayout(dlg)
        form = QFormLayout()

        def _feld(wert):
            sb = QDoubleSpinBox(dlg)
            sb.setDecimals(3)
            sb.setSingleStep(0.5)
            sb.setRange(links, rechts)
            sb.setValue(float(wert))
            sb.setSuffix(" s")
            return sb

        sb_start = _feld(start_s)
        if art == "anfang":
            # Ein Anfangsschnitt beginnt per Definition bei 0. Nur sein Ende
            # laesst sich verschieben.
            sb_start.setEnabled(False)
        form.addRow("Start", sb_start)
        sb_ende = _feld(end_s)
        if art == "ende":
            # Ein Endschnitt reicht per Definition bis ans Videoende. Nur sein
            # Anfang laesst sich verschieben - waere das Ende frei, waere er
            # beim naechsten Mal ein Mittelschnitt.
            sb_ende.setEnabled(False)
        form.addRow("End", sb_ende)
        aussen.addLayout(form)

        hinweis = QLabel(dlg)
        hinweis.setWordWrap(True)
        aussen.addWidget(hinweis)

        knoepfe = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        aussen.addWidget(knoepfe)
        knoepfe.accepted.connect(dlg.accept)
        knoepfe.rejected.connect(dlg.reject)

        def _pruefen():
            laenge = sb_ende.value() - sb_start.value()
            ok = laenge >= 0.01
            text = (f"Length {laenge:.3f} s\n"
                    f"Allowed range {links:.3f} – {rechts:.3f} s"
                    + (f"\nWas {start_s:.3f} – {end_s:.3f} s"))
            if not ok:
                text += "\nThe end must lie behind the start."
            hinweis.setText(text)
            knoepfe.button(QDialogButtonBox.Ok).setEnabled(ok)

        sb_start.valueChanged.connect(_pruefen)
        sb_ende.valueChanged.connect(_pruefen)
        _pruefen()

        if dlg.exec() != QDialog.Accepted:
            return
        neu_start = round(sb_start.value(), 3)
        neu_ende = round(sb_ende.value(), 3)
        if abs(neu_start - start_s) < 0.001 and abs(neu_ende - end_s) < 0.001:
            print("[CUT-MOVE] unveraendert, nichts zu tun")
            return
        self._schnitt_verschieben(start_s, end_s, neu_start, neu_ende)

    def _ruecknahme_probe(self, start_s, end_s, spur_jetzt, spur_vorher):
        """Selbsttest: wuerde die Ruecknahme dieses Schnitts exakt zurueckfuehren?

        Rechnet die Ruecknahme nur durch und vergleicht sie Punkt fuer Punkt
        mit dem Zustand vor dem Schnitt. Es wird nichts veraendert - die Probe
        laeuft auf Kopien und dient allein dazu, im Betrieb an echten Daten zu
        belegen, dass die Aufzeichnung traegt, bevor irgendjemand sie benutzt.

        Etappe 2 von 6.02. Faellt spaeter weg oder wandert hinter einen
        Schalter, sobald die Ruecknahme wirklich angeboten wird.
        """
        try:
            probe = self.cut_manager.spur_ohne_schnitt(start_s, end_s, spur_jetzt)
        except Exception as e:
            print(f"[CUT-PROBE] Ruecknahme warf eine Ausnahme: {e!r}")
            return

        if probe is None:
            print("[CUT-PROBE] keine Aufzeichnung vorhanden")
            return

        if len(probe) != len(spur_vorher):
            print(f"[CUT-PROBE] ANZAHL WEICHT AB: zurueckgerechnet {len(probe)}, "
                  f"vorher {len(spur_vorher)}")
            return

        # Die Metriken rechnet recalc_gpx_data() aus den Grundwerten neu, sie
        # werden deshalb nicht verglichen - nur Lage, Hoehe und Zeit.
        abw = 0
        erste = None
        for i, (a, b) in enumerate(zip(probe, spur_vorher)):
            if (round(float(a.get("lat", 0.0)), 9) != round(float(b.get("lat", 0.0)), 9)
                    or round(float(a.get("lon", 0.0)), 9) != round(float(b.get("lon", 0.0)), 9)
                    or round(float(a.get("ele", 0.0)), 4) != round(float(b.get("ele", 0.0)), 4)
                    or a.get("time") != b.get("time")):
                abw += 1
                if erste is None:
                    erste = (i, a.get("time"), b.get("time"))

        if abw == 0:
            print(f"[CUT-PROBE] Ruecknahme fuehrt exakt zurueck: {len(probe)} Punkte identisch")
        else:
            print(f"[CUT-PROBE] {abw} von {len(probe)} Punkten weichen ab; "
                  f"erster bei Index {erste[0]}: zurueck={erste[1]} vorher={erste[2]}")

    def _on_auto_sync_video_toggled(self, checked: bool):
        """
        Wird aufgerufen, wenn der Menüpunkt "AutoSyncVideo" an-/abgehakt wird.
        => Speichere den Zustand in self._autoSyncVideoEnabled
        """    
        if checked and self._edit_mode == "off":
            # -> nicht erlaubt
            QMessageBox.warning(
                self,
                "AutoCutVideo+GPX requires Edit Mode",
                "You can only enable AutoCutVideo+GPX if 'Edit Video' is enabled.\n"
                "Please enable 'Edit Video' first."
            )
            # Checkbox zurücksetzen
            self.action_auto_sync_video.setChecked(False)
            return

        
        print(f"[DEBUG] _on_auto_sync_video_toggled => {checked}")
        self._autoSyncVideoEnabled = checked
        if hasattr(self, "_gpx_slots"):
            self._gpx_slots[self._active_gpx_slot]["sync_enabled"] = bool(checked)
            print(f"[DEBUG] Slot {self._active_gpx_slot} sync_enabled set to {checked}")

        # --- NEU: Sync-Status im aktuellen Slot persistieren ---
        try:
            self._gpx_slots[self._active_gpx_slot]["sync_enabled"] = bool(checked)
        except Exception:
            pass

        self.gpx_control.set_markE_visibility(not checked)
        self.video_control._update_autocut_icon()
        
        if checked:
            self.video_editor.hinweis_setzen("acut", "V&G:On", "#ff5555")
        else:
            self.video_editor.hinweis_setzen("acut", "")
            #self.video_editor.acut_status_label.setText("V&G:Off")
            #self.video_editor.acut_status_label.setStyleSheet(
            #    "background-color: rgba(0,0,0,120); "
            #    "color: grey; "
            #    "font-size: 14px; "
            #    "font-weight: normal;"
            #    "padding: 2px;"
            #)
        
        self._update_set_gpx2video_enabled()    
        

        
    def _on_sync_point_video_time_toggled(self, checked: bool):
        print(f"[DEBUG] _on_sync_point_video_time_toggled {checked}")
        self._autoSyncNewPointsWithVideoTime = checked
        self.action_new_pts_video_time.setChecked(checked)
        self.map_widget.view.page().runJavaScript(f"enableVSyncMode({str(checked).lower()});")
        
        if hasattr(self, "_active_gpx_slot") and self._active_gpx_slot in self._gpx_slots:
            self._gpx_slots[self._active_gpx_slot]["sync_enabled"] = checked
        
   
    
    def _format_duration_with_ms(self, total_seconds: float) -> str:
        """
        Formatiert Sekunden in HH:MM:SS.mmm Format mit Millisekunden.
        """
        if total_seconds < 0:
            return "00:00:00.000"
    
        total_ms = int(round(total_seconds * 1000))
        hours = total_ms // (3600 * 1000)
        minutes = (total_ms % (3600 * 1000)) // (60 * 1000)
        seconds = (total_ms % (60 * 1000)) // 1000
        milliseconds = total_ms % 1000
    
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _update_gpx_overview(self):
        data = self.gpx_widget.gpx_list._gpx_data
        if not data:
            self.gpx_control.update_info_line(
                video_time_str="00:00:00.000",  # Mit Millisekunden
                length_km=0.0,
                duration_str="00:00:00.000",    # Mit Millisekunden
                elev_gain=0.0
            )
            return
        
                # --- Trim-Setup: effektiven Start und Index ermitteln (bei grauem Vorlauf) ---
        try:
            _shift = get_gpx_video_shift()
        except Exception:
            _shift = 0

        effective_start_t = data[0].get("time")
        if _shift is not None and _shift < 0 and effective_start_t:
            from datetime import timedelta
            effective_start_t = effective_start_t + timedelta(seconds=abs(_shift))

        # Index des ersten Punkts, der im "sichtbaren" (nicht-grauen) Bereich liegt
        start_idx = 0
        if effective_start_t:
            for _i, _pt in enumerate(data):
                _ti = _pt.get("time")
                if _ti and _ti >= effective_start_t:
                    start_idx = _i
                    break

        

        # 1) Länge in km (ggf. ab "grauem" Start trimmen)
        
        total_dist_m = 0.0
        for i in range(max(1, start_idx + 1), len(data)):
            total_dist_m += data[i].get("delta_m", 0.0)
        length_km = total_dist_m / 1000.0


        
        ####
    
        # 2) Höhengewinn
        
        elev_gain = 0.0
        for i in range(max(1, start_idx + 1), len(data)):
            dh = data[i].get("ele", 0.0) - data[i-1].get("ele", 0.0)
            if dh > 0:
                elev_gain += dh


        

                
        # 3) GPX-Dauer berechnen (ggf. ab "grauem" Start)
        start_t = data[0].get("time")
        end_t   = data[-1].get("time")

        # Standard: originaler Beginn
        effective_start_t_dur = start_t

        # Bei negativem Shift: effektiven Beginn verschieben
        try:
            shift = get_gpx_video_shift()
        except Exception:
            shift = 0

        if shift is not None and shift < 0 and start_t:
            from datetime import timedelta
            effective_start_t_dur = start_t + timedelta(seconds=abs(shift))

        if end_t and effective_start_t_dur:
            total_sec = (end_t - effective_start_t_dur).total_seconds()
        else:
            total_sec = 0.0
        
        if total_sec < 0:
            total_sec = 0.0

        
        # => In h:mm:ss formatieren
        gpx_duration_str = self._format_duration_with_ms(total_sec)
    
        # 4) Videolänge (z.B. final nach Cuts)
        total_dur = self.real_total_duration        # Roh-Gesamtlänge aller Videos
        sum_cuts  = self.cut_manager.get_total_cuts()
        final_dur = total_dur - sum_cuts
        if final_dur < 0:
            final_dur = 0
        #vid_hh = int(final_dur // 3600)
        #vid_mm = int((final_dur % 3600) // 60)
        #vid_ss = int(final_dur % 60)
        #video_time_str = f"{vid_hh:02d}:{vid_mm:02d}:{vid_ss:02d}"
        video_time_str = self._format_duration_with_ms(final_dur)
        # 5) Weitere Werte wie slope_max/min etc.
        # 5) Slope/Gradient (ab start_idx)
        slope_vals = [pt.get("gradient", 0.0) for pt in data[start_idx:]]
        slope_max = max(slope_vals) if slope_vals else 0.0
        slope_min = min(slope_vals) if slope_vals else 0.0

    
        zero_thr = self.chart.zero_speed_threshold()
        zero_speed_count = 0
        for i in range(max(1, start_idx + 1), len(data)):
            if data[i].get("speed_kmh", 0.0) < zero_thr:
                zero_speed_count += 1

    
        # Pausen/Lücken (ab start_idx)
        paused_count = 0
        t0 = data[start_idx].get("time")
        if t0:
            for i in range(max(1, start_idx + 1), len(data)):
                t_prev = data[i-1].get("time")
                t_cur  = data[i].get("time")
                if t_prev and t_cur:
                    dt = (t_cur - t_prev).total_seconds()
                    if dt > 1.0:
                        paused_count += 1
        else:
            paused_count = len(data) - start_idx

    
        # 6) An Dein gpx_control_widget übergeben
        self.gpx_control.update_info_line(
            video_time_str=video_time_str,     # Das ist Deine Video-Dauer
            length_km=length_km,
            duration_str=gpx_duration_str,     # DAS ist die Track-Dauer 
            elev_gain=elev_gain,
            slope_max=slope_max,
            slope_min=slope_min,
            zero_speed_count=zero_speed_count,
            paused_count=paused_count
        )


        
        
    def on_user_selected_index(self, new_index: int):
        """
        Zentrale Methode für Klicks in Map oder GPX-Liste (im Pause-Modus).
        Wir entfernen die 'Loch'-Logik, sodass ein roter Punkt beim Anklicken
        NICHT mehr schwarz wird, sondern auch gelb.

        1) Alten gelben Punkt revertieren,
        2) Neuer Punkt => immer gelb (egal ob B..E oder nicht),
        3) Liste -> dieselbe Zeile gelb selektieren.
        """

        # 1) Bisherigen gelben Punkt in Map revertieren, falls vorhanden
       
        if self.video_editor.is_playing and is_gpx_video_shift_set():
            self.map_widget.show_yellow(new_index)
        else:
            self.map_widget.show_blue(new_index)
        

        # 3) Liste: dieselbe Zeile gelb machen
        #    => so bleibt Map und Liste synchron
        self.gpx_widget.gpx_list.select_row_in_pause(new_index)
        self.chart.highlight_gpx_index(new_index)


    
        
    def _on_markB_in_list(self, b_idx: int):
        """ 
        Wird ausgelöst, wenn die GPXList MarkB gesetzt hat.
        => Wir rufen jetzt map_widget.set_markB_point(...) (neue JS-Funktion).
        """
        if self.map_widget:
            self.map_widget.set_markB_point(b_idx)
            self.map_widget.set_markB_idx(b_idx)

    def _on_markE_in_list(self, e_idx: int):
        if self.map_widget:
            self.map_widget.set_markE_point(e_idx)
            self.map_widget.set_markE_idx(e_idx)

    def _on_clear_in_list(self):
        if self.map_widget:
            self.map_widget.clear_marked_range()
            self.map_widget.set_markB_idx(None)
            self.map_widget.set_markE_idx(None)
        
    
    def on_point_moved(self, index: int, lat: float, lon: float):
        
        gpx_data = self.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return
    
        # 1) Undo-Snapshot (gesamte GPX-Daten kopieren)

        self.register_gpx_undo_snapshot(
            self.gpx_widget.gpx_list.schritt_text("Move point on map", index))
        
        """
        Wird aufgerufen, wenn der User in der Karte einen GPX-Punkt verschoben hat.
        """
        print(f"[MainWindow] on_point_moved => idx={index}, lat={lat}, lon={lon}")

        if 0 <= index < len(self._gpx_data):
            self._gpx_data[index]["lat"] = lat
            self._gpx_data[index]["lon"] = lon
            
            recalc_gpx_data(self._gpx_data)
            

            # Falls du Distanz/Speed neu berechnen willst => optional
            #new_geojson = self._build_route_geojson_from_gpx(self._gpx_data)

            # ENTSCHEIDUNG: 
            # => do_fit=False => bleibe im aktuellen Ausschnitt 
            # => do_fit=True  => zoome wieder raus
            #self.map_widget.loadRoute(new_geojson, do_fit=False)

            # Tabelle updaten (damit man es auch sieht)
            self.gpx_widget.set_gpx_data(self._gpx_data)  
            self._update_gpx_overview()
            self.chart.set_gpx_data(self._gpx_data)
        else:
            print("[WARN] Index war außerhalb des GPX-Datenbereichs.")

    

    def _build_route_geojson_from_gpx(self, data):
        
        if not data:
            return {"type": "FeatureCollection", "features": []}
        """
        data: Liste von Dicts => [{'lat':..., 'lon':...}, ...]
        Gibt FeatureCollection mit 1x Linestring + Nx Points zurück,
        wobei jeder Point => properties.index = i hat.
        """
        features = []
        positive_time = data[0].get("time") or 0.0
        if get_gpx_video_shift() < 0: #extra points at begin
            positive_time = positive_time + timedelta(seconds = abs(get_gpx_video_shift()))

        # Linestring-Koords
        coords_line = []
        outside_line = []
        for i, pt in enumerate(data):
            if pt.get("time") or 0.0 >= positive_time:
                coords_line.append([pt["lon"], pt["lat"]])
            else:
                outside_line.append([pt["lon"], pt["lat"]])

        line_feat = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords_line
            },
            "properties": { "color":"#000000"  }
        }
        features.append(line_feat)

        if outside_line:
            outside_line.append(coords_line[0])
            outside_line_feat = {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": outside_line
                },
                "properties": { "color":"grey" }
            }
            features.append(outside_line_feat)

        # Einzelne Punkt-Features
        for i, pt in enumerate(data):
            point_feat = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [pt["lon"], pt["lat"]]
                },
                "properties": {
                    "index": i,
                    "color": "#000000" if (pt.get("time") or 0.0) >= positive_time else "grey", 
                }
            }
            features.append(point_feat)

        return {
            "type": "FeatureCollection",
            "features": features
        }

    
    # -----------------------------------------------------------------------
    # Methoden und Slots (weitgehend unverändert)
    # -----------------------------------------------------------------------
    
    
    def on_markB_clicked_video(self):
        """
        Setzt MarkB aus dem VideoControl.
        - Falls AutoSync=OFF: Nur Video-Markierung setzen, keine GPX-Markierung
        - Falls AutoSync=ON: berechne final_s und markiere den besten GPX-Index (closest).
        """
        # Kein Video/GPX -> Abbruch
        if not self._autoSyncVideoEnabled:
            # Nur Video-Markierung setzen, keine GPX-Markierung
            global_s = self.video_editor.get_current_position_s()
            self.cut_manager.markB_time_s = global_s
            self.timeline.set_markB_time(global_s)
            return

        # AutoSync = ON: determine the closest GPX entry to the current final video time
        global_s = self.video_editor.get_current_position_s()
        final_s = self.get_final_time_for_global(global_s)
        best_idx = self.gpx_widget.get_closest_index_for_time(final_s)
    
        # clamp
        maxrow = len(self.gpx_widget.gpx_list._gpx_data) - 1
        if best_idx < 0:
            return
        if best_idx > maxrow:
            best_idx = maxrow

        # Validity check: cannot set B behind existing E
        E_s = self.cut_manager.markE_time_s
        if E_s >= 0 and global_s >= E_s:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Invalid MarkB",
                f"You cannot set MarkB ({global_s:.2f}s) behind MarkE ({E_s:.2f}s)!"
            )
            return
    
        # Set GPX Mark and timeline/cut_manager
        self.gpx_widget.gpx_list.set_markB_row(best_idx)
        self.map_widget.set_markB_point(best_idx)
        self.cut_manager.markB_time_s = global_s
        self.timeline.set_markB_time(global_s)
        
    def on_markE_clicked(self):
        print("[DEBUG] Alter markE")
        return
        
       

    
    def _on_markE_from_video(self):
        print("[DEBUG] MarkE from Video")
        
        if not self._autoSyncVideoEnabled:
            row = self.gpx_widget.gpx_list.table.currentRow()
            if row < 0:
                return
            #self.gpx_widget.gpx_list.set_markE_row(row)
            self.map_widget.set_markE_point(row)
            
            global_s = self.video_editor.get_current_position_s()
            self.cut_manager.markE_time_s = global_s
            self.timeline.set_markE_time(global_s)
        else:
            # AutoSync=ON
            global_s = self.video_editor.get_current_position_s()
            final_s  = self.get_final_time_for_global(global_s)
            best_idx = self.gpx_widget.get_closest_index_for_time(final_s)
            
           
            row = best_idx
            # clamp ...
            if row < 0:
                return
            maxrow = len(self.gpx_widget.gpx_list._gpx_data)-1
            if row > maxrow:
                row = maxrow
                
            B_s = self.cut_manager.markB_time_s
            if B_s >= 0 and global_s <= B_s:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Invalid MarkE",
                    f"You cannot set MarkE ({global_s:.2f}s) in front of MarkB ({B_s:.2f}s)!"
                )
                return  # => Abbruch    
            
            self.gpx_widget.gpx_list.set_markE_row(row)
            self.map_widget.set_markE_point(row)
            
            self.cut_manager.markE_time_s = global_s
            self.timeline.set_markE_time(global_s)
    
    def _on_markE_from_gpx(self):
        print("[DEBUG] Mark E from gpx")
        
        
        if not self._autoSyncVideoEnabled:
            row = self._gpx_zeile_fuer_marke("markE")
            if row is None:
                return
            self.gpx_widget.gpx_list.set_markE_row(row)
            self.map_widget.set_markE_point(row)
            
            #global_s = self.video_editor.get_current_position_s()
            #self.cut_manager.markE_time_s = global_s
            #self.timeline.set_markE_time(global_s)
        else:
            # AutoSync=ON
            global_s = self.video_editor.get_current_position_s()
            final_s  = self.get_final_time_for_global(global_s)
            best_idx = self.gpx_widget.get_closest_index_for_time(final_s)
            
           
            row = best_idx
            # clamp ...
            if row < 0:
                return
            maxrow = len(self.gpx_widget.gpx_list._gpx_data)-1
            if row > maxrow:
                row = maxrow
                
            B_s = self.cut_manager.markB_time_s
            if B_s >= 0 and global_s <= B_s:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Invalid MarkE",
                    f"You cannot set MarkE ({global_s:.2f}s) in front of MarkB ({B_s:.2f}s)!"
                )
                return  # => Abbruch    
            
            self.gpx_widget.gpx_list.set_markE_row(row)
            self.map_widget.set_markE_point(row)
            
            self.cut_manager.markE_time_s = global_s
            self.timeline.set_markE_time(global_s)
    
    
    
    
    
    def _on_gpx_list_pause_clicked(self, row_idx: int):
        if not self.video_editor.is_playing:
            # Statt select_point_in_pause => show_blue
            #self.map_widget.show_blue(row_idx)
            self.map_widget.show_blue(row_idx, do_center=True)
            self.chart.highlight_gpx_index(row_idx)
            if self._autoSyncNewPointsWithVideoTime and self.playlist_counter > 0:
                self.on_map_sync_any()

    def _on_map_pause_clicked(self, index: int):
        """
        Wird aufgerufen, wenn im Pause-Modus in der Karte
        ein Punkt geklickt wurde.
        => Markiere denselben Index in der GPX-Liste!
        """
        if not self.video_editor.is_playing:
            self.gpx_widget.gpx_list.select_row_in_pause(index)
            self.chart.highlight_gpx_index(index)
            if self.mini_chart_widget:
                self.mini_chart_widget.set_current_index(index)



    def _show_copyright_dialog(self):
        """Hilfe -> Copyright + License: die Hinweise zum Nachlesen.

        Ein eigener Dialog mit rollbarem Text statt einer QMessageBox: die
        Box waechst mit ihrem Inhalt, und seit dem Voice Remover (7.0) fuellte
        sie die ganze Bildschirmhoehe. Und ohne den Satz "By clicking 'I
        Accept'": der gehoert in den Disclaimer beim ersten Start, hier gibt
        es nichts anzunehmen, nur zu lesen. Beides von Bernd am 10.09.2026
        gemeldet.
        """
        from PySide6.QtWidgets import QTextBrowser
        from PySide6.QtCore import Qt
        import os
        import base64

        msg = QDialog(self)
        msg.setWindowTitle("Copyright + License")
    
        # Ueber config.finde_datei() - siehe dort, warum mehrere Orte.
        from config import finde_datei
        logo_path = finde_datei("doc", "Kinomap_Logo.png")
    
        # Logo als Base64 kodieren für direkte Einbettung in HTML
        logo_base64 = ""
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as img_file:
                logo_base64 = base64.b64encode(img_file.read()).decode('utf-8')
        
        # Text mit Logo am Ende
        message_text = f"""
        <div>
            <h3>KVRouite - Video and GPX Sync Tool</h3>
            Version: {APP_VERSION}<br><br>
            
            Copyright (C) 2025-2026 Bernd Eller<br>
            This program is free software: you can redistribute it and/or modify 
            it under the terms of the GNU General Public License as published by 
            the Free Software Foundation, either version 3 of the License, or 
            (at your option) any later version.<br><br>
        
            This program is distributed in the hope that it will be useful, 
            but WITHOUT ANY WARRANTY; without even the implied warranty of 
            MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. 
            See the GNU General Public License for more details.<br><br>
            
            You should have received a copy of the GNU General Public License 
            along with this program. If not, see 
            <a href='https://www.gnu.org/licenses/'>https://www.gnu.org/licenses/</a>.<br><br>
            
            <h3>Third-Party Libraries &amp; Patent Notice</h3>
            This application includes and distributes open-source libraries:<br>
            <b>1. Qt 6.11.2</b> with PySide6 and shiboken6 -
            <a href='https://pyside.org'>pyside.org</a> (LGPL-3.0-only). The Qt
            libraries are ordinary DLL files in <code>_internal/PySide6</code> -
            you may replace them with a compatible build of your own, as the
            LGPL provides for.<br>
            <b>2. OpenLayers 7.3.0</b> -
            <a href='https://openlayers.org'>openlayers.org</a> (BSD-2-Clause),
            the map library<br>
            <b>3. CPython {sys.version_info.major}.{sys.version_info.minor}</b> (PSF), <b>OpenSSL 3</b> (Apache-2.0),
            <b>Pillow</b> (MIT-CMU), <b>fitparse</b> (MIT)<br>
            <b>4. GStreamer 1.28.6</b>, incl. GStreamer Editing Services (GES) and
            PyGObject -
            <a href='https://gstreamer.freedesktop.org'>gstreamer.freedesktop.org</a>
            (LGPL-2.1-or-later; the bundled x264 and x265 encoder plugins are
            GPL-2.0-or-later). The bundle also contains the FFmpeg 7.1 shared
            libraries (LGPL build) used by its gst-libav plugin - see
            <code>COMPONENTS.txt</code>.<br>
            <b>5. Voice remover</b> (since 7.0) -
            <a href='https://github.com/nomadkaraoke/python-audio-separator'>python-audio-separator</a>
            (MIT) with <b>PyTorch</b> (BSD-3-Clause), <b>ONNX Runtime</b> (MIT),
            NumPy, SciPy, librosa and further packages (BSD, MIT, ISC, Apache-2.0,
            MPL-2.0), listed with their license texts in
            <code>_internal/third-party-licenses/voice</code>. Two of them are
            LGPL-2.1-or-later and replaceable shared libraries: <b>libsndfile</b>
            and <b>libsoxr</b>. The separation models are the MDX-Net model
            trained by the <a href='https://github.com/Anjok07/ultimatevocalremovergui'>Ultimate
            Vocal Remover</a> team (Anjok07, aufr33; MIT) and <b>Demucs v4</b>
            by Meta (MIT); their architecture code comes from Meta, tsurumeso,
            kuielab and ZFTurbo (all MIT) - see
            <code>_internal/third-party-licenses/LICENSE.UVR-upstreams</code>.<br><br>

            GStreamer is what plays, cuts and renders video in KVRouite, so it is
            always loaded. On Linux it is not distributed with KVRouite at all -
            it comes from your distribution's own packages.<br><br>

            Copy mode additionally calls the <b>ffmpeg</b> and <b>ffprobe</b>
            programs. Those are <b>not</b> part of this distribution - KVRouite
            uses whatever is installed on your system, and copy mode stays
            disabled without them.<br><br>

            Full license texts are located in the
            <code>_internal/gstreamer</code>, <code>_internal/qt</code> and
            <code>_internal/third-party-licenses</code> folders.<br>
            The GStreamer binaries are the GStreamer Project's own, passed on unchanged;
            their source is published by that project at
            <a href='https://gstreamer.freedesktop.org/src/'>gstreamer.freedesktop.org/src</a>
            - see <code>_internal/gstreamer/CORRESPONDING-SOURCE.txt</code>.
            KVRouite compiles none of these binaries. If one of those links ever
            stops working, write to
            <a href='mailto:bernd@kvrouite.com'>bernd@kvrouite.com</a> and you will
            be pointed at a working source for the version you received.<br><br>

            <b>Patent Encumbrance Notice:</b><br>
            Some codecs (such as x264, x265, AAC, MP3, AC-3, DTS) may be
            patent-encumbered in certain jurisdictions.
            It is the user's responsibility to ensure compliance with all applicable
            laws and regulations, and to obtain any necessary patent licenses.<br><br>

            <b>Acknowledgements:</b><br>
            GPS extraction for GoPro cameras is based on <i>gopro2gpx</i> by
            Juan M. Casillas (GPL-3.0), modified.<br>
            Parts of this release were developed with the assistance of
            <i>Claude</i> (Anthropic). Copyright and responsibility for the code
            remain with the author named above.<br><br>

            <div style='text-align: center; margin-top: 20px;'>
                <img src='data:image/png;base64,{logo_base64}' width='200' style='max-width: 200px;'>
            </div>
        </div>
        """

        text = QTextBrowser(msg)
        text.setOpenExternalLinks(True)
        text.setHtml(message_text)
        knopf = QDialogButtonBox(QDialogButtonBox.Ok, msg)
        knopf.accepted.connect(msg.accept)
        aussen = QVBoxLayout(msg)
        aussen.addWidget(text, 1)
        aussen.addWidget(knopf, 0, Qt.AlignRight)
        # Feste, bildschirmtaugliche Groesse; der Text rollt darin.
        msg.resize(720, 640)
        msg.exec()
    
    
    
        
    def _on_timer_mode_changed(self):
        if self.action_global_time.isChecked():
            self._time_mode = "global"
        elif self.action_final_time.isChecked():
            self._time_mode = "final"
        self.update_timeline_marker()
        self.video_editor.set_time_mode(self._time_mode)    
        self.video_editor.set_final_time_callback(self.get_final_time_for_global)

    def _get_offset_for_filepath(self, video_path):
        try:
            idx = self.playlist.index(video_path)
        except ValueError:
            return 0.0
        return sum(self.video_durations[:idx])

   

   
    def _index_keyframes_from_container(self, video_path):
        """
        Schnellweg fuer den Keyframe-Index: liest die Tabelle direkt aus der
        MP4/MOV-Datei, statt ffprobe ueber jedes Paket laufen zu lassen.

        Gemessen an GX010089.MP4 (11,9 GB, 4K HEVC), Dateicache jeweils
        geleert: 3 min 25 s mit ffprobe gegen 0,006 s hier - bei identischer
        Liste (2112 von 2112 Keyframes, auf die Mikrosekunde).

        Liefert True, wenn die CSV geschrieben wurde. Bei False laeuft der
        bisherige Weg unveraendert weiter - er hat immer Vorrang. Abgelehnt
        wird unter anderem alles, was nicht MP4/MOV ist, was B-Frames hat,
        was fragmentiert ist und was gar keine Keyframe-Tabelle mitbringt
        (siehe core/mp4_keyframes.py).
        """
        try:
            times = keyframe_times_from_index(video_path)
            if not times:
                print("[INFO] Keyframe index not usable for "
                      f"{os.path.basename(video_path)} - using ffprobe.")
                return False
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            csv_path = os.path.join(TMP_KEYFRAME_DIR,
                                    f"keyframes_{base_name}_ffprobe.csv")
            os.makedirs(TMP_KEYFRAME_DIR, exist_ok=True)
            # Format wie ffprobe: key_frame,pts_time,pict_type. Die vierte,
            # leere Spalte, die ffprobe manchmal anhaengt, ist nur die
            # side_data_list - merge_keyframes_incremental liest ohnehin nur
            # die ersten drei Felder.
            with open(csv_path, "w", encoding="utf-8") as f:
                for t in times:
                    f.write(f"1,{t:.6f},I\n")
            print(f"[INFO] Read {len(times)} keyframes from the file index "
                  f"of {os.path.basename(video_path)}.")
        except Exception as e:
            print(f"[WARN] Fast keyframe index failed ({e}) - using ffprobe.")
            return False
        self.on_extract_finished(video_path, TMP_KEYFRAME_DIR)
        return True

    # Im MainWindow (oder ImportExportManager, wo du es hast)
    def start_indexing_process(self, video_path):

        # Erst der Schnellweg. Klappt er nicht, bleibt alles wie bisher.
        if self._index_keyframes_from_container(video_path):
            return

        dlg = _IndexingDialog(video_path, parent=self)
        dlg.indexing_extracted.connect(self.on_extract_finished)
        dlg.start_indexing()

        # => Wichtig:
        dlg.show()
        
        QApplication.processEvents()

        dlg.raise_()
        dlg.activateWindow()

        result = dlg.exec()
        if result == QDialog.Accepted:
            print("[DEBUG] IndexingDialog => Accepted")
        else:
            print("[DEBUG] IndexingDialog => Rejected/Closed")

   


    def on_extract_finished(self, video_path, temp_dir):
        """
        Wird aufgerufen, wenn das Indexing-Tool die CSV-Datei erstellt hat.
        Hier rufen wir dann self.run_merge(...) auf.
        """
        print("[DEBUG] on_extract_finished => rufe run_merge an ...")
    
        
        base_name = os.path.splitext(os.path.basename(video_path))[0]
    
        # BAUE den CSV-Dateinamen
        csv_path = os.path.join(temp_dir, f"keyframes_{base_name}_ffprobe.csv")
    
        # Jetzt run_merge aufrufen
        self.run_merge(
            video_path=video_path,
            csv_file=csv_path,     # <-- Hier definieren wir csv_path
            temp_dir=temp_dir
        )
    

    
   
    def load_mp4_files(self):
       
        
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Load MP4 files",
            "",
            "Video Files (*.mp4 *.MP4 *.mov *.mkv *.avi)",
        )
        if not files:
            return

        files = self._videos_in_aufnahmefolge(files)
        self.process_open_mp4(files)
        self.save_recent_file(files[0])

    def _videos_in_aufnahmefolge(self, files):
        """Mehrere Dateien in Aufnahmereihenfolge - siehe core/videoreihenfolge.
        Der Dateidialog liefert sie in Klickreihenfolge, nach Namen staenden
        GoPro-Kapitel falsch. Die Folge steht in der Konsole."""
        if len(files) < 2:
            return list(files)
        from core import videoreihenfolge
        try:
            sortiert = videoreihenfolge.sortieren(files)
            for zeile in videoreihenfolge.erklaeren(files):
                print(f"[IMPORT] {zeile}")
            return sortiert
        except Exception as exc:
            print(f"[IMPORT] Reihenfolge nicht bestimmbar, wie ausgewaehlt: {exc}")
            return list(files)

    def process_open_mp4(self, files):
     # 1) Alle ausgewählten Dateien in die Playlist hängen,
        #    ohne zwischendurch den Player zu starten:
        first_load= self.playlist_counter == 0
        files = self._videos_in_aufnahmefolge(files)
        for file_path in files:
            self.add_to_playlist(file_path)

        # 2) Timeline neu berechnen
        self.rebuild_timeline()

        # 3) Erst am Ende einmal den ersten Frame vom allerersten Video zeigen:
        if self.playlist:
            self.video_editor.show_first_frame_at_index(0)

        if self.playlist_counter > 1:
            QMessageBox.information(self, "Loaded", f"{len(files)} video(s) added to the playlist.")

        if first_load:
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Edit video")

            vbox = QVBoxLayout(dlg)
            lbl = QLabel("Select video edition mode")
            vbox.addWidget(lbl)

            # Button Box
            btns = QDialogButtonBox()

            # Add "Copy" button - nur wenn ffmpeg und ffprobe da sind.
            # Copy-Mode schneidet an Keyframes mit "-c copy"; ohne die beiden
            # fuehrt die Wahl nur in einen Modus, der beim Export scheitert.
            if copy_mode_moeglich():
                btn_copy = QPushButton("Copy")
                btns.addButton(btn_copy, QDialogButtonBox.YesRole)
                btn_copy.clicked.connect(lambda: dlg.done(1))

            # Add "Encode" button
            btn_encode = QPushButton("Encode")
            btns.addButton(btn_encode, QDialogButtonBox.ActionRole)
            btn_encode.clicked.connect(lambda: dlg.done(2) )

            # Add "No Edit" button (acts like Cancel)
            btn_cancel = QPushButton("No Edit")
            btns.addButton(btn_cancel, QDialogButtonBox.RejectRole)
            btn_cancel.clicked.connect(lambda: dlg.reject())

            vbox.addWidget(btns)

            result = dlg.exec()
            if result == 1:
                self._set_edit_mode("copy")
            elif result == 2:
                self._set_edit_mode("encode")

            if not getattr(self, "_360_aus_projekt", False):
                w, h = self.video_editor.get_video_size()
                if view360.ist_equirect(w, h) and not self.video_editor.is_360_mode():
                    self._on_toggle_360_from_menu(True)
            self.proposeVideoGpxSync()

    def proposeVideoGpxSync(self):
        # show only if we have both GPX and at least one video
        if not (self._gpx_data and self.playlist_counter > 0):
            return

        # if last GPX operation was an append => never ask here
        if getattr(self, "_last_gpx_load_mode", None) == "append":
            return

        # if we've already asked for this (and not explicitly reset), do not ask again
        if self._sync_prompt_answer is not None:
            return

        # ask once
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Video & GPX Sync")
        yes_btn = msg_box.addButton("Yes", QMessageBox.AcceptRole)
        msg_box.setText("Do your GPX and video start at the same time?\n "
                        "If so, let's activate video / GPX sync mode.")
        no_btn = msg_box.addButton("No", QMessageBox.RejectRole)
    
        msg_box.setWindowModality(Qt.WindowModal)
        msg_box.show()
        QApplication.processEvents()
    
        msg_box.exec()
        clicked = msg_box.clickedButton()
        if clicked == yes_btn:
            # remember and apply
            self._sync_prompt_answer = True
            set_gpx_video_shift(0)
            self.enableVideoGpxSync(True)
            if self._edit_mode != "off":
                self.video_control.set_editing_mode(True, True)  # refresh button state
        else:
            # remember and give the hint
            self._sync_prompt_answer = False
            # Der Hinweis zeigt den Knopf, statt ihn zu beschreiben: das
            # Abbild wird hier vom echten Knopf genommen, damit es auch nach
            # einem Icon- oder Groessenwechsel noch stimmt.
            hinweis = QMessageBox(self)
            hinweis.setWindowTitle("Video & GPX Sync")
            hinweis.setIcon(QMessageBox.Information)
            hinweis.setText(
                "In this case it is advised to define the sync point.\n"
                "Select a GPX point, find it in the video, "
                "then click this button:")
            knopf = self.video_control.set_sync_button
            war_an = knopf.isEnabled()
            knopf.setEnabled(True)   # ausgegraut waere das Abbild nicht zu erkennen
            abbild = knopf.grab()
            knopf.setEnabled(war_an)
            knopf_bild = QLabel()
            knopf_bild.setPixmap(abbild)
            hinweis.layout().addWidget(knopf_bild, 1, 2)   # Zeile unter dem Text
            hinweis.exec()
    
                
    def _theme_waehlen(self, modus: str):
        """Farbgebung umschalten und merken.

        Die gemalten Flaechen - Zeitleiste, Chart, Videobild - bleiben davon
        unberuehrt: sie zeichnen mit eigenen Farben und fragen keine Palette.
        Schnittmarken sehen danach also aus wie vorher.
        """
        from core import theme
        theme.modus_merken(modus)
        theme.anwenden(QApplication.instance(), modus)

    def enableVideoGpxSync(self,enable = True):
        #self.video_control.set_editing_mode(enable)
        self._on_auto_sync_video_toggled(enable and self._edit_mode != "off")
        if enable and self._edit_mode != "off":
            self.video_control._on_autocut_toggle_clicked()
        
        self.video_control.activate_controls()
        self._on_sync_point_video_time_toggled(enable)

    def _set_gpx_data(self, gpx_data):
        """Integriere die Daten in UI + merke sie in self._gpx_data."""
        self._gpx_data = gpx_data
        self.gpx_widget.set_gpx_data(gpx_data)

        self.chart.set_gpx_data(gpx_data)
        if self.mini_chart_widget:
            self.mini_chart_widget.set_gpx_data(gpx_data)

        route_geojson = self._build_route_geojson_from_gpx(gpx_data)
        self.map_widget.loadRoute(route_geojson, do_fit=True)
        self._apply_map_sizes_from_settings()
        self._update_gpx_overview()
        self.check_gpx_errors(gpx_data)

        # === NEU: Slot-Utilities ===
    def _get_active_slot_store(self):
        return self._gpx_slots[self._active_gpx_slot]

    def _apply_slot_to_ui(self):
        store = self._get_active_slot_store()
        data = store["gpx_data"] or []

        # 1) Shift ZUERST setzen, damit nachfolgende Widgets korrekt rechnen/färben
        from core.gpx_parser import set_gpx_video_shift
        set_gpx_video_shift(store["gpx_video_shift"])

        # 2) Interne Referenz aktualisieren
        self._gpx_data = data

        # 3) Jetzt erst Widgets mit Daten versorgen (Liste, Chart, Mini-Chart)
        self.gpx_widget.set_gpx_data(data)
        self.chart.set_gpx_data(data)
        if self.mini_chart_widget:
            self.mini_chart_widget.set_gpx_data(data)

        # 4) Map zuletzt – sie benutzt nun den korrekten Shift
        route_geojson = self._build_route_geojson_from_gpx(data)
        self.map_widget.loadRoute(route_geojson, do_fit=True)

        # 5) Slot-spezifische B/E-Markierungen wiederherstellen
        lw = self.gpx_widget.gpx_list
        lw.clear_marked_range()  # einmal zu Beginn, NICHT später nochmal löschen
        if store["markB"] is not None:
            lw.set_markB_row(store["markB"])
        if store["markE"] is not None:
            lw.set_markE_row(store["markE"])

        # 6) Übersicht updaten
        self._update_gpx_overview()

        # 7) Nur Auswahl/visuelle Highlights neutralisieren (NICHT clear_marked_range!)
        # 7) Nur Auswahl/visuelle Highlights neutralisieren (NICHT clear_marked_range!)
        try:
            sm = getattr(lw, "selectionModel", None)
            if sm:
                sm.clearSelection() 
            # KEIN direkter Aufruf von lw.clearSelection()

            if hasattr(self.map_widget, "clear_selected_point"):
                self.map_widget.clear_selected_point()
            if hasattr(self.chart, "clear_highlight"):
                self.chart.clear_highlight()
        except Exception as e:
            print(f"[DEBUG] clear visuals in _apply_slot_to_ui failed: {e}")


        # 8) Slot-spezifischen „Set Sync“-Marker (Index) wiederherstellen, falls vorhanden
        marker_idx = store.get("sync_marker")
        if marker_idx is not None:
            try:
                lw.select_row_in_pause(marker_idx)
                self.map_widget.show_blue(marker_idx, do_center=True)
                self.chart.highlight_gpx_index(marker_idx)
                print(f"[DEBUG] Restored sync marker for Slot {self._active_gpx_slot}: idx={marker_idx}")
            except Exception as e:
                print(f"[DEBUG] Restore sync marker failed: {e}")

        # 9) VideoControl-Icon aktualisieren (falls vorhanden)
        if hasattr(self.video_control, "update_set_sync_highlight"):
            self.video_control.update_set_sync_highlight()

    def _save_ui_into_current_slot(self):
        """
        Sichert den aktuellen UI-Zustand (GPX, Markierungen, gpx_video_shift)
        im aktiven Slot.
        """
        store = self._get_active_slot_store()
        store["gpx_data"] = self._gpx_data or []

        lw = self.gpx_widget.gpx_list
        store["markB"] = lw._markB_idx
        store["markE"] = lw._markE_idx

        from core.gpx_parser import get_gpx_video_shift
        try:
            store["gpx_video_shift"] = get_gpx_video_shift()
        except Exception:
            store["gpx_video_shift"] = None

    def switch_gpx_slot(self, new_slot: int):
        """Slot 1 ↔ 2 umschalten: speichert/restauriert GPX- und Sync-Zustände."""
        if new_slot not in (1, 2):
            return
        if new_slot == self._active_gpx_slot:
            return

        if new_slot == 2 and not (self._gpx_slots.get(2, {}).get("gpx_data") or []):
            QMessageBox.information(
                self,
                "No GoPro data in Slot 2",
                "No GoPro data in Slot 2.\nPlease extract GoPro GPS first (File → GoPro-Extractor) before switching to Slot 2."
            )
            return False
            
        # 1) Vorherigen Slot-Status sichern
        prev_slot = self._active_gpx_slot
        prev_sync = self.action_new_pts_video_time.isChecked()
        self._gpx_slots[prev_slot]["sync_enabled"] = prev_sync
        # GPX/Markierungen usw. sichern
        self._save_ui_into_current_slot()

        # 2) Slot umschalten
        self._active_gpx_slot = new_slot

        # 3) UI für neuen Slot anwenden (lädt Daten, Karte, Markierungen)
        self._apply_slot_to_ui()

        # 4) Sync-Action programmgesteuert setzen – ohne Rückkopplung
        sync_state = bool(self._gpx_slots[new_slot].get("sync_enabled", False))
        self.action_new_pts_video_time.blockSignals(True)
        self.action_new_pts_video_time.setChecked(sync_state)
        self.action_new_pts_video_time.blockSignals(False)

        # internen Zustand und Engine schalten (ohne _on_sync_point_video_time_toggled aufzurufen!)
        self._autoSyncVideoEnabled = sync_state
        self.enableVideoGpxSync(sync_state)
                # --- NEU: zentraler Button-Refresh, auch für Rechtsklick-Wechsel ---
        try:
            self.gpx_control.apply_slot_button_style(new_slot)
        except Exception as e:
            print(f"[DEBUG] Slot button style update failed: {e}")

        print(f"[DEBUG] Switched to Slot {new_slot} – Sync = {sync_state}")



    def process_open_gpx(self, file_path, mode="new"):
        self.map_widget.view.page().runJavaScript("showLoading('Loading GPX...');")
        QApplication.processEvents()
    
        # parse, ensureIDs, etc.
        new_data = parse_gpx(file_path)
        
        for pt in new_data:
            if isinstance(pt.get("time"), str):
                try:
                    pt["time"] = datetime.fromisoformat(pt["time"].replace("Z", "+00:00"))
                except Exception:
                    pass

        # Prüfen ob Resample nötig ist
        if self._check_gpx_step_intervals(new_data):
            new_data = self._resample_to_1s(new_data)
        
        if not new_data:
            QMessageBox.warning(self, "Load GPX", "File is empty or invalid.")
            self.map_widget.view.page().runJavaScript("hideLoading();")
            return
    
        if mode == "new":
            # --- NEU: Immer Slot 1 füllen ---
            self._gpx_slots[1]["gpx_data"] = new_data
            self._gpx_slots[1]["gpx_video_shift"] = None
            self._gpx_slots[1]["markB"] = None
            self._gpx_slots[1]["markE"] = None
            self._gpx_slots[1]["bookmarks"] = []   # neue Spur, alte Punkte weg

            # UI nur überschreiben, wenn Slot 1 aktiv ist
            if self._active_gpx_slot == 1:
                self._apply_slot_to_ui()    
            if self._active_gpx_slot == 2:
                self.switch_gpx_slot(1)
                try:
                    btn = self.gpx_control.slot_button
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.setText("Slot 1")
                    btn.setStyleSheet(self.gpx_control._slot1_style)
                    btn.blockSignals(False)
                except Exception as e:
                    print(f"[DEBUG] Slot1-AutoActivate UI update skipped: {e}")
                    
                    
        elif mode == "append":
            if not self._gpx_data:
                # --- Append ausschließlich in Slot 1 ---
                base = self._gpx_slots[1]["gpx_data"] or []
                merged = (base + new_data) if base else list(new_data)
                self._gpx_slots[1]["gpx_data"] = merged
                # Slot-1 UI nur aktualisieren, wenn Slot 1 aktiv ist
                if self._active_gpx_slot == 1:
                    self._apply_slot_to_ui()
                return    
            else:
                # => alte + neue zusammen
                old_data = self._gpx_data
    
                # optional Undo
                old_snapshot = copy.deepcopy(old_data)
                self.gpx_widget.gpx_list._history_stack.append(old_snapshot)
    
                from datetime import timedelta
                old_end_time = old_data[-1]["time"]
                gap_start = old_end_time + timedelta(seconds=1)
                shift_dt = gap_start - new_data[0]["time"]
    
                shift_s = shift_dt.total_seconds()
                for pt in new_data:
                    pt["time"] = pt["time"] + shift_dt
    
                merged_data = old_data + new_data
                recalc_gpx_data(merged_data)
                self._set_gpx_data(merged_data)
                QMessageBox.information(self, "Load GPX", "GPX appended successfully.")
    
        self.map_widget.view.page().runJavaScript("hideLoading();")
        self.proposeVideoGpxSync()
    
    def update_timeline_marker(self):
        
        self.check_and_handle_video_end()        
        
        """
        Wird periodisch aufgerufen (z.B. alle 200ms) und aktualisiert:
        - Timeline:   Setzt den Marker
        - VideoEditor-Label:  Zeigt die aktuelle Zeit
        - VideoControl:       Setzt h:m:s
        - GPX/Map/Chart:      Wandert mit, solange is_playing=True
        """
        # 1) Aktuelle (globale) Videoposition abfragen:
        global_s = self.video_editor.get_current_global_time()
        if global_s < 0:
            global_s = 0.0
    
        # 2) Unterscheide, ob wir final oder global anzeigen wollen:
        if self._time_mode == "final":
            display_time = self.get_final_time_for_global(global_s)
        else:
            display_time = global_s
        
        # 3) Timeline-Marker (immer in "global" Koordinaten):
        self.timeline.set_marker_position(global_s)
        self.audio_zoom.set_zeit(global_s)
        
        # 4) Zeit im VideoEditor-Label & VideoControl anzeigen
        #
        # Das Label hatte bis 6.01 einen eigenen 200-ms-Timer im
        # VideoEditorWidget. Der fragte die Position ein zweites Mal ab und
        # lief gegen diesen hier - Marker und Anzeige konnten deshalb bis zu
        # einem Takt auseinanderliegen. Jetzt bekommt es die Sekunde, die
        # oben schon ermittelt wurde.
        self.video_editor.zeit_anzeigen(global_s)

        s_rounded = round(display_time)
        hh = s_rounded // 3600
        mm = (s_rounded % 3600) // 60
        ss = s_rounded % 60
    
        #self.video_editor.set_current_time(display_time)
        self.video_control.set_hms_time(hh, mm, ss)

        # 5) Wenn das Video gerade läuft => aktualisieren wir GPX/Map/Chart
        if self.video_editor.is_playing:
            # a) Welche "finale" Zeit markiert werden soll, hängt wieder vom Mode ab
            if self._time_mode == "final":
                final_s = display_time
            else:
                # falls _time_mode == "global", konvertieren wir global_s zu final_s
                final_s = self.get_final_time_for_global(global_s)
        
            if is_gpx_video_shift_set():
                # b) GPX-Widget highlighten
                self.gpx_widget.highlight_video_time(final_s, is_playing=True)

                # c) Index im GPX finden
                i = self.gpx_widget.get_closest_index_for_time(final_s)
        
                # d) Chart-Index highlighten
                self.chart.highlight_gpx_index(i)
        
                # e) Mini-Chart ebenfalls
                if self.mini_chart_widget:
                    self.mini_chart_widget.set_current_index(i)
        
                # f) Map => gelben Marker
                self.map_widget.show_yellow(i)
        else:
            # Video pausiert => kein automatisches "Mitlaufen" in Map/GPX
            pass

    
    
    def _on_chart_marker_clicked(self, index: int):
        """
        Wird aufgerufen, wenn man im ChartWidget an Position index klickt.
        => Dann selektieren wir diesen index in gpx_list und Map, 
        und ggf. Video an diese Stelle spulen.
        """
        print(f"[DEBUG] _on_chart_marker_clicked => idx={index}")
        # 1) gpx_list => select_row_in_pause
        if not self.video_editor.is_playing:
            self.gpx_widget.gpx_list.select_row_in_pause(index)
            # => map
            #self.map_widget.select_point_in_pause(index)
            self.map_widget.show_blue(index, do_center=True)
            #self.map_widget.show_blue(index)
            self.chart.highlight_gpx_index(index)
            # Der Chart-Flow soll denselben Punkt zeigen, nicht erst beim
            # Abspielen nachziehen.
            if self.mini_chart_widget:
                self.mini_chart_widget.set_current_index(index)
            if self._autoSyncNewPointsWithVideoTime and self.playlist_counter > 0:
                self.on_map_sync_any()
        else:
            # Wenn Video gerade läuft => evtl. jump dorthin
            # ... oder du pausierst / oder was du willst
            pass

       
        self.chart.highlight_gpx_index(index)


    

    
    def add_to_playlist(self, filepath):
        if filepath not in self.playlist:
            self.playlist.append(filepath)
            self.playlist_counter += 1
            label_text = f"{self.playlist_counter}: {os.path.basename(filepath)}"
            action = self.playlist_menu.addAction(label_text)
            action.triggered.connect(lambda checked, f=filepath, a=action: self.confirm_remove(f, a))

            
            # Auch hier kann das Oeffnen dauern: GES analysiert jede Datei
            # beim Laden durch (gemessen 6 s bei 8,6 GB). Ohne Fenster
            # steht die App scheinbar.
            ladefenster = PreviewPrepareDialog(0, self, titel="Loading video…")
            ladefenster.label_info.setText(
                "Opening the video and preparing the preview. "
                "Large source files can take a moment.")
            ladefenster.btn_cancel.hide()
            ladefenster.show()
            ladefenster.raise_()
            QApplication.processEvents()
            try:
                self.video_editor.set_playlist(
                    self.playlist,
                    lambda nr, ges, pfad: ladefenster.schritt(
                        f"Opening video {nr} of {ges}: {os.path.basename(pfad)}"))
            finally:
                try:
                    ladefenster.close()
                    ladefenster.deleteLater()
                except Exception:
                    pass
            self.video_control.activate_controls(True)

            # Bildrate: bei der ERSTEN Datei immer fragen - auch nach "New
            # Project", denn dann soll die Ausgaberate neu bestimmt werden.
            # Bei jeder weiteren Datei nur, wenn sie von der ersten abweicht;
            # dann aber deutlich. Beim Laden eines Projekts nicht: dort wird
            # die Liste am Stueck gesetzt und einmal am Ende gefragt.
            if not getattr(self, "_loading_project", False):
                self._fps_nach_laden(nur_bei_abweichung=len(self.playlist) > 1)

            # Nur Copy-Mode braucht den Keyframe-Index (siehe _maybe_ask_index).
            if self._edit_mode == "copy" and (not self._userDeclinedIndexing):
                self.start_indexing_process(filepath)
            else:
                print("[DEBUG] Kein Indexing, weil der User es abgelehnt hat oder EditVideo=OFF.")                
           

    def confirm_remove(self, filepath, action):
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete?")
        msg.setText(f"Delete {os.path.basename(filepath)} from playlist?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        r = msg.exec()
        if r == QMessageBox.Yes:
            self.remove_from_playlist(filepath, action)
   
   
    def remove_from_playlist(self, filepath, action):
        if filepath in self.playlist:
            idx = self.playlist.index(filepath)
            self.playlist.remove(filepath)
            self._sprechstellen.pop(filepath, None)
            if idx < len(self.video_durations):
                self.video_durations.pop(idx)

            # Der Keyframe-Index rechnet in globaler Zeit. Faellt ein Video
            # heraus, verschiebt sich alles dahinter - die gespeicherten Zeiten
            # stimmen dann fuer kein einziges Video mehr. Neu indiziert wird bei
            # Bedarf ohnehin, aber nur im Copy-Mode (siehe _maybe_ask_index).
            if self.global_keyframes:
                print("[INFO] Keyframe-Index verworfen: die Playlist hat sich "
                      "geaendert")
                self.global_keyframes = []

            self.playlist_menu.removeAction(action)
            
            # STATT rebuild_vlc_playlist():
            self.video_editor.set_playlist(self.playlist)
            #self.video_control.activate_controls(
            #    True if self.playlist.length() > 0 else False)
            # Timeline anpassen:
            self.video_control.activate_controls(len(self.playlist) > 0)
            self.rebuild_timeline()
            self._rebuild_playlist_menu()    
    
    
    def rebuild_timeline(self):
        self.video_durations = []
        offset = 0.0
        for path in self.playlist:
            dur = self.get_video_length(path)
            self.video_durations.append(dur)
            offset += dur
        self.real_total_duration = offset
        self.timeline.set_total_duration(self.real_total_duration)
        # Bildstreifen fuer das neue Material holen.
        self._thumbs.verwerfen()
        self.thumbs_anstossen()
        QTimer.singleShot(0, self.thumbs_grundstock)

        boundaries = []
        ofs = 0.0
        for d in self.video_durations:
            ofs += d
            boundaries.append(ofs)
        self.timeline.set_boundaries(boundaries)
        # Sprechstellen und Tonspur liegen in Gesamtzeit - mit neuen
        # Laengen oder Reihenfolge neu umrechnen.
        self._sprechstellen_anzeigen()
        # Naehte, die es bei dieser Videoliste nicht mehr gibt, fallen weg.
        self.cut_manager.prune_merge_fades(len(self.playlist))
        self._blenden_an_timeline()

        self.video_editor.set_total_length(self.real_total_duration)
        self.video_editor.set_multi_durations(self.video_durations)
        self.cut_manager.set_video_durations(self.video_durations)
        self._update_gpx_overview()

    def get_video_length(self, filepath):
        """Laenge einer Videodatei in Sekunden.

        Kommt aus core.framerate: dort wird zuerst GStreamer gefragt und nur
        dann ffprobe. Das ist ein Schritt weg von ffmpeg, und nebenbei
        schneller - der Discoverer braucht keinen Prozessstart, und die
        Eckdaten je Datei werden gemerkt. rebuild_timeline() laeuft nach jeder
        Aenderung der Wiedergabeliste, ohne das Merken oeffnete die Anwendung
        jedes Mal wieder jede Datei.

        Hiess frueher get_video_length_ffprobe(); der Name stimmte nicht mehr.
        """
        return framerate.dauer(filepath)

    def run_merge(self, video_path, csv_file, temp_dir):
        print("[DEBUG] run_merge => direkt merge_keyframes_incremental aufrufen ...")
        offset_value = self._get_offset_for_filepath(video_path)
        label = os.path.basename(video_path)
        json_file = os.path.join(temp_dir, "merged_keyframes.json")
    
        try:
            merge_keyframes_incremental(
                csv_file=csv_file,
                json_file=json_file,
                label=label,
                offset=offset_value,
                do_sort=True
            )
            # Danach ggf. self.on_indexing_finished(temp_dir) aufrufen
            self.on_indexing_finished(temp_dir)

        except Exception as e:
            print("Fehler beim Merge:", e)
            QMessageBox.warning(self, "Merge Error", "Merge step failed.")

    def on_indexing_finished(self, temp_dir):
        merged_json = os.path.join(temp_dir, "merged_keyframes.json")
        if not os.path.exists(merged_json):
            print("[DEBUG] merged_keyframes.json nicht gefunden in", temp_dir)
            return

        try:
            with open(merged_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            new_kfs = []
            for entry in data:
                try:
                    gt = float(entry.get("global_time", 0.0))
                    new_kfs.append(gt)
                except:
                    pass
            new_kfs.sort()

            # Setzen, nicht anhaengen.
            #
            # merged_keyframes.json ist bereits die vollstaendige Liste ueber
            # alle bisher indizierten Videos - der Merge traegt jedes Video mit
            # seinem Zeitversatz dort ein. Anhaengen war deshalb schon immer
            # ueberfluessig und hat zwei Fehler gemacht: es schleppte die
            # Keyframes frueher geladener Videos mit, und seit die Liste beim
            # Projektladen direkt aus den Dateien abgeleitet wird, standen dort
            # dieselben Zeiten in zwei Genauigkeiten nebeneinander - die CSV
            # wird mit sechs Nachkommastellen geschrieben, die Ableitung
            # rechnet mit voller Fliesskomma-Genauigkeit, und set() sieht darin
            # zwei verschiedene Zahlen. Gemessen am 30.08.2026: aus 725 echten
            # Keyframes wurden nach dem Indizieren 1208.
            self.global_keyframes = sorted(set(new_kfs))
            print("[DEBUG] %d Keyframes global geladen (gesamt)." % len(self.global_keyframes))

        except Exception as e:
            print("[DEBUG] Fehler beim Laden der JSON:", e)

    # -----------------------------------------------------------------------
    # Marker- und Player-Funktionen ...
    # -----------------------------------------------------------------------
    
    def on_play_pause(self):
        if self.video_editor.is_playing:
            # => Pause
            self.video_editor.play_pause()
            self.video_control.update_play_pause_icon(False)

            # GPX-List / Map: Pause
            self.gpx_widget.set_video_playing(False)
            self.map_widget.set_video_playing(False)

            # (A) => Falls wir noch einen gelben Play-Marker hatten, revertieren:
            #if self._last_map_idx is not None:
            #    # => Schwarz oder Rot? Da du ggf. in "update_timeline_marker" 
            #    #    den gelben Marker setzt, revertieren wir hier einfach auf schwarz:
            #    self.map_widget.highlight_gpx_point(self._last_map_idx, "#000000", 4, False)
            #    self._last_map_idx = None
            

        else:
            
            if not self.cut_manager._has_active_file():
                if self.playlist:
                    self.video_editor.show_first_frame_at_index(0)
            
            if self._video_at_end:
                # => Wir waren am Ende => also erst "stoppen"
                self.on_stop()             # ruft dein Stop-Verhalten auf
                self._video_at_end = False # Reset dieses Merkers
            
            
            # => PLAY
            self.video_editor.play_pause()
            self.video_control.update_play_pause_icon(True)

            # GPX-List / Map: Play
            self.gpx_widget.set_video_playing(True)
            self.map_widget.set_video_playing(True)

            # Optional: Einmalig Karte zentrieren
            ...
    
    def on_stop(self):
        self.video_editor.stop()

    
    def on_goto_video_end_clicked(self):
        try:
            total_duration = self.real_total_duration
            cut_intervals = getattr(self.cut_manager, "_cut_intervals", [])

            # Finale Endposition bestimmen (Ende des letzten Keep-Segments)
            final_end_position = total_duration
            if cut_intervals:
                keep_intervals = self._compute_keep_intervals(cut_intervals, total_duration)
                if keep_intervals:
                    final_end_position = keep_intervals[-1][1]

            # Endcut vorhanden?
            has_endcut = abs(final_end_position - total_duration) > 0.1
            
            # Stabil pausieren & UI setzen, aber NICHT als 'am Ende' markieren
            self._handle_video_end_state(mark_as_end=False)
            # Optional Popup wie in der Laufzeit-Erkennung
            #if has_endcut and getattr(self, "action_show_endcut", None) and self.action_show_endcut.isChecked():
            #    if getattr(self, "action_show_endcut_warning", None) and self.action_show_endcut_warning.isChecked():
            #        self._show_endcut_popup(final_end_position)

            # Ein Sprung genuegt. Frueher standen hier drei auf dasselbe
            # Ziel (10/100/250 ms) - ein Notbehelf aus der Zeit, als Spruenge
            # unzuverlaessig wirkten. GesPlayerBackend._seek_ns() wartet das
            # Ende des Sprungs blockierend ab; danach ist nichts mehr
            # nachzubessern, die beiden Wiederholungen kosteten nur je einen
            # weiteren Pipeline-Neustart samt Wartezeit.
            #
            # Die kurze Verzoegerung bleibt: _handle_video_end_state() hat
            # gerade pausiert, und der Sprung soll erst danach kommen.
            QTimer.singleShot(10, lambda: self.video_editor.seek_global(final_end_position))

            print(f"[GOTO_END] jumped to {final_end_position:.3f}s (total={total_duration:.3f}, endcut={has_endcut})")
        except Exception as e:
            print(f"[ERROR] on_goto_video_end_clicked: {e}")   
   
   
   
   
    
    def on_play_ended(self):
        """Wird aufgerufen, wenn das Video natürlich endet"""
        # Stelle sicher, dass alle Zustände korrekt zurückgesetzt werden
        self.video_editor.set_paused(True)

        self.video_control.update_play_pause_icon(False)
        self.gpx_widget.set_video_playing(False)
        self.map_widget.set_video_playing(False)
        
        # Gelben Marker entfernen
        lw = self.gpx_widget.gpx_list
        if lw._last_video_row is not None:
            lw._mark_row_bg_except_markcol(lw._last_video_row, Qt.white)
            lw._last_video_row = None
            
        self._video_at_end = True
        
        # Zusätzlich: Stelle sicher, dass der Player wirklich pausiert ist
        QTimer.singleShot(50, lambda: self.video_control.update_play_pause_icon(False))


    def on_step_mode_changed(self, new_value):
        self.step_manager.set_step_mode(new_value)

    def on_multiplier_changed(self, new_value):
        numeric = new_value.replace("x", "")
        try:
            val = float(numeric)
        except:
            val = 1.0
        self.step_manager.set_step_multiplier(val)

    # Beim Ziehen kommt zu JEDER Mausbewegung ein Wunsch herein
    # (VideoTimelineWidget.mouseMoveEvent). Jeden davon anzuspringen hiesse,
    # die Pipeline hundertfach zu leeren und neu zu dekodieren - und jeder
    # dieser Spruenge wartet blockierend im GUI-Thread.
    #
    # Derselbe Wert wie beim 360-Schwenk, wo dasselbe Problem schon geloest
    # ist: GesPlayerBackend.BLICK_AUFFRISCHEN_MS.
    MARKER_ZUG_MS = 60

    def _on_timeline_marker_moved(self, new_time_s: float):
        """Sprung zum gezogenen Marker, hoechstens alle MARKER_ZUG_MS.

        Der zuletzt genannte Wunsch gewinnt, ueberholte werden verworfen, und
        der letzte geht nie verloren - er wird nachgeholt, sobald die Sperre
        faellt. Gebaut wie GesPlayerBackend._blick_auffrischen_anstossen().

        Die Marker-LINIE laeuft davon unberuehrt sofort mit der Maus mit; die
        zeichnet das Timeline-Widget selbst. Gedrosselt wird nur der Sprung
        im Video.
        """
        if self._marker_zug_timer.isActive():
            self._marker_zug_offen = new_time_s
            return
        self._marker_zug_offen = None
        self.video_editor.seek_global(new_time_s)
        self._marker_zug_timer.start(self.MARKER_ZUG_MS)

    def _marker_zug_abgelaufen(self):
        if self._marker_zug_offen is not None:
            ziel, self._marker_zug_offen = self._marker_zug_offen, None
            self.video_editor.seek_global(ziel)
            self._marker_zug_timer.start(self.MARKER_ZUG_MS)
        
    # ------------------------------------------------------------------
    # Overlays: verschieben, Laenge, Ein- und Ausblendung
    # ------------------------------------------------------------------
    def _overlay_blenden_an_timeline(self):
        """Der Zeitleiste die Ein- und Ausblendlaengen der Overlays geben."""
        try:
            self.timeline.set_overlay_blenden(
                [(float(o.get("start", 0.0)), float(o.get("end", 0.0)),
                  float(o.get("fade_in", 0) or 0),
                  float(o.get("fade_out", 0) or 0))
                 for o in self._overlay_manager.get_all_overlays()])
        except Exception as e:
            print(f"[WARN] Overlay-Blenden an die Zeitleiste: {e}")

    def _overlay_grenzen(self, start_s, end_s):
        """(frueh, spaet) fuer die Anschlaege beim Ziehen."""
        try:
            return self._overlay_manager.grenzen_fuer(start_s, end_s)
        except Exception as e:
            print(f"[WARN] Overlay-Grenzen: {e}")
            return float(start_s), float(end_s)

    def _on_overlay_move(self, alt_start, alt_ende, neu_start, neu_ende):
        """Ein Overlay wurde in der Zeitleiste gezogen."""
        ok, grund = self._overlay_manager.overlay_verschieben(
            alt_start, alt_ende, neu_start, neu_ende)
        if not ok:
            QMessageBox.warning(self, "Overlay not possible", grund)
            return
        self.timeline.update()

    def _on_overlay_delete(self, start_s, end_s):
        """Entf auf einem ausgewaehlten Overlay.

        Mit Rueckfrage, wie im Menue auch: ein Overlay ist schnell wieder
        angelegt, aber Bild, Groesse und Lage waeren neu einzustellen.
        """
        antwort = QMessageBox.question(
            self, "Remove Overlay?",
            "Remove the overlay from %.1fs to %.1fs?" % (start_s, end_s),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if antwort == QMessageBox.Yes:
            self._overlay_manager.remove_overlay_interval(start_s, end_s)

    def _on_overlay_menu(self, start_s, end_s, global_pos):
        """Rechtsklick auf ein Overlay.

        Bis 6.03 kam hier sofort die Frage "Remove Overlay?". Seit sich ein
        Overlay auch verschieben laesst und eigene Blendenlaengen hat, ist
        Loeschen nur noch eine von mehreren Moeglichkeiten.
        """
        from PySide6.QtWidgets import QMenu

        ovl = self._overlay_suchen(start_s, end_s)
        ein = float((ovl or {}).get("fade_in", 0) or 0)
        aus = float((ovl or {}).get("fade_out", 0) or 0)

        menue = QMenu(self)
        titel = menue.addAction(
            "Overlay %s - %s  (%.1fs)"
            % (self._sek_kurz(start_s), self._sek_kurz(end_s),
               end_s - start_s))
        titel.setEnabled(False)
        menue.addSeparator()

        a_blenden = menue.addAction("Fade in %.1f s / out %.1f s …" % (ein, aus))
        a_zeit = menue.addAction("Start and end …")
        menue.addSeparator()
        a_weg = menue.addAction("Remove Overlay\tDel")

        gewaehlt = menue.exec(global_pos)
        if gewaehlt is None:
            return
        if gewaehlt is a_weg:
            antwort = QMessageBox.question(
                self, "Remove Overlay?",
                "Remove the overlay from %.1fs to %.1fs?" % (start_s, end_s),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if antwort == QMessageBox.Yes:
                self._overlay_manager.remove_overlay_interval(start_s, end_s)
        elif gewaehlt is a_blenden:
            self._overlay_blenden_dialog(start_s, end_s)
        elif gewaehlt is a_zeit:
            self._overlay_zeit_dialog(start_s, end_s)

    def _overlay_suchen(self, start_s, end_s):
        """Das Overlay mit diesen Zeiten, oder None."""
        for ovl in self._overlay_manager.get_all_overlays():
            if (abs(float(ovl.get("start", 0.0)) - start_s) < 0.001
                    and abs(float(ovl.get("end", 0.0)) - end_s) < 0.001):
                return ovl
        return None

    def _overlay_blenden_dialog(self, start_s, end_s):
        """Ein- und Ausblendlaenge eines Overlays einstellen.

        Beide liegen INNERHALB des Overlays: es blendet an seinem eigenen
        Anfang ein und an seinem Ende aus. Zusammen duerfen sie deshalb nicht
        laenger sein als das Overlay selbst.
        """
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                                       QFormLayout, QLabel, QVBoxLayout)

        ovl = self._overlay_suchen(start_s, end_s)
        if ovl is None:
            return
        dauer = float(end_s) - float(start_s)

        dlg = QDialog(self)
        dlg.setWindowTitle("Overlay fade")
        aussen = QVBoxLayout(dlg)
        form = QFormLayout()

        def _feld(wert):
            sb = QDoubleSpinBox(dlg)
            sb.setDecimals(1)
            sb.setSingleStep(0.5)
            sb.setRange(0.0, max(0.0, dauer))
            sb.setValue(float(wert or 0))
            sb.setSuffix(" s")
            return sb

        sb_ein = _feld(ovl.get("fade_in", 0))
        sb_aus = _feld(ovl.get("fade_out", 0))
        form.addRow("Fade in", sb_ein)
        form.addRow("Fade out", sb_aus)
        aussen.addLayout(form)

        hinweis = QLabel(dlg)
        hinweis.setWordWrap(True)
        aussen.addWidget(hinweis)

        knoepfe = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        aussen.addWidget(knoepfe)
        knoepfe.accepted.connect(dlg.accept)
        knoepfe.rejected.connect(dlg.reject)

        def _pruefen():
            summe = sb_ein.value() + sb_aus.value()
            passt = summe <= dauer + 1e-9
            hinweis.setText(
                "The overlay is %.1f s long. Fade in and fade out lie inside "
                "it, so together they cannot be longer than that.\n"
                "Used: %.1f s of %.1f s." % (dauer, summe, dauer)
                + ("" if passt else "\nToo long."))
            knoepfe.button(QDialogButtonBox.Ok).setEnabled(passt)

        sb_ein.valueChanged.connect(_pruefen)
        sb_aus.valueChanged.connect(_pruefen)
        _pruefen()

        if dlg.exec() != QDialog.Accepted:
            return
        ok, grund = self._overlay_manager.blenden_setzen(
            start_s, end_s, round(sb_ein.value(), 1), round(sb_aus.value(), 1))
        if not ok:
            QMessageBox.warning(self, "Overlay fade", grund)
            return
        self.timeline.update()

    def _overlay_zeit_dialog(self, start_s, end_s):
        """Anfang und Ende eines Overlays als Zahlen eingeben.

        Dasselbe wie das Ziehen in der Zeitleiste, nur ohne Zeigegeraet -
        und mit denselben Anschlaegen.
        """
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                                       QFormLayout, QLabel, QVBoxLayout)

        frueh, spaet = self._overlay_grenzen(start_s, end_s)

        dlg = QDialog(self)
        dlg.setWindowTitle("Overlay start and end")
        aussen = QVBoxLayout(dlg)
        form = QFormLayout()

        def _feld(wert):
            sb = QDoubleSpinBox(dlg)
            sb.setDecimals(3)
            sb.setSingleStep(0.5)
            sb.setRange(float(frueh), float(spaet))
            sb.setValue(float(wert))
            sb.setSuffix(" s")
            return sb

        sb_a = _feld(start_s)
        sb_b = _feld(end_s)
        form.addRow("Start", sb_a)
        form.addRow("End", sb_b)
        aussen.addLayout(form)

        hinweis = QLabel(dlg)
        hinweis.setWordWrap(True)
        aussen.addWidget(hinweis)

        knoepfe = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        aussen.addWidget(knoepfe)
        knoepfe.accepted.connect(dlg.accept)
        knoepfe.rejected.connect(dlg.reject)

        def _pruefen():
            laenge = sb_b.value() - sb_a.value()
            ok = laenge >= 0.1
            hinweis.setText(
                "Length %.3f s\nAllowed here %.3f s - %.3f s: the overlay has "
                "to stay inside one kept segment and leave room for the "
                "crossfades next to it."
                % (laenge, frueh, spaet)
                + ("" if ok else "\nThe end must lie behind the start."))
            knoepfe.button(QDialogButtonBox.Ok).setEnabled(ok)

        sb_a.valueChanged.connect(_pruefen)
        sb_b.valueChanged.connect(_pruefen)
        _pruefen()

        if dlg.exec() != QDialog.Accepted:
            return
        neu_a, neu_b = round(sb_a.value(), 3), round(sb_b.value(), 3)
        if abs(neu_a - start_s) < 0.001 and abs(neu_b - end_s) < 0.001:
            return
        self._on_overlay_move(start_s, end_s, neu_a, neu_b)

    def _on_timeline_overlay_remove(self, start_s, end_s):
        self._overlay_manager.remove_overlay_interval(start_s, end_s)    

    def _on_cut_hard_toggle(self, start_s: float, end_s: float):
        """Rechtsklick auf einen schwarzen Block: Blende <-> harte Kante.

        Start- und Endschnitt bleiben aussen vor: die werden schon vor dem
        Zusammenfuegen weggetrimmt (Werte -2 bzw. -1 in den
        skip_instructions) und haben deshalb noch nie eine Blende gehabt.
        """
        total_dur = getattr(self, "real_total_duration", 0.0) or 0.0
        is_start_cut = abs(start_s - 0.0) < 0.1
        is_end_cut = total_dur > 0 and abs(end_s - total_dur) < 0.1
        if is_start_cut or is_end_cut:
            QMessageBox.information(
                self,
                "No crossfade here",
                "The first and the last cut are trimmed away before "
                "encoding, so they never had a crossfade."
            )
            return

        hard_now = self.cut_manager.is_hard_cut(start_s, end_s)
        if hard_now:
            question = (f"Cut {start_s:.2f}s - {end_s:.2f}s is a hard cut.\n"
                        "Use a crossfade again?")
        else:
            question = (f"Cut {start_s:.2f}s - {end_s:.2f}s uses a crossfade.\n"
                        "Make it a hard cut instead?")

        reply = QMessageBox.question(
            self, "Cut mode", question,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        new_state = self.cut_manager.toggle_hard_cut(start_s, end_s)
        print(f"[DEBUG] cut {start_s:.3f}-{end_s:.3f} => "
              f"{'hard cut' if new_state else 'crossfade'}")
        # Aus einer harten Kante wird eine Blende: die braucht jetzt Platz.
        # Passt sie nicht, wird gefragt - und bei Abbruch bleibt es bei der
        # harten Kante.
        if not new_state:
            weiter, kuerzungen = self._blenden_konflikt_fragen(
                None, "Switching this cut back to a crossfade")
            if not weiter:
                self.cut_manager.set_hard_cut(start_s, end_s, True)
                self.timeline.update()
                return
            self._blenden_kuerzen(kuerzungen)
        self.timeline.update()
        self._refresh_preview_timeline()

    def on_time_hms_set_clicked(self, hh: int, mm: int, ss: int, ms=0):
        """
        Empfängt das Signal vom VideoControlWidget (SetTime-Button).
        Rechnet hh:mm:ss => globale Sekunde => springt dorthin.
        """
        # 1) h/m/s in float-Sekunden
        total_s = hh * 3600 + mm * 60 + ss + (ms / 1000.0)
        
        
        if self.cut_manager.is_in_cut_segment(total_s):
            QMessageBox.warning(
                self,
                "Invalid Time",
                "This time is inside a cut segment.\nCannot jump there!"
            )
            return  # Abbruch

    
        # 2) Begrenzen auf [0 .. real_total_duration]
        if total_s < 0:
            total_s = 0.0
        if total_s > self.real_total_duration:
            total_s = self.real_total_duration
    
        # 3) Globaler Sprung im Player
        self.video_editor.set_time(total_s)
        #
        # Damit ruft Ihr intern video_editor.seek_global(total_s) auf,
        # das berechnet, in welchem Clip wir landen und spult dorthin.
        #
    
    
    
    def _on_cuts_changed(self, sum_of_cuts_s):
        print("[DEBUG] _on_cuts_changed => sum_of_cuts_s:", sum_of_cuts_s)
        new_duration = self.real_total_duration - sum_of_cuts_s
        if new_duration < 0:
            new_duration = 0
        self.video_editor.set_old_time(self.real_total_duration)
        self.video_editor.set_cut_time(new_duration)
        self._update_gpx_overview()
        self._refresh_preview_timeline()
        # Der Audio Zoom zeigt die Schnitte mit - Sprechstellen darin
        # zaehlen nicht, der Export laesst sie ohnehin weg.
        self._sprechstellen_anzeigen()

    def _refresh_preview_timeline(self):
        """
        Schnitte und Blenden an die Vorschau geben.

        Die Vorschau zeigt danach das FERTIGE Video: geschnittene Bereiche
        fehlen, an den Schnitten liegt die Blende.

        Die Verteilung der Blenden ist bewusst dieselbe wie beim Export
        (siehe skip_array in on_render_clicked): Start- und Endschnitt werden
        nur weggetrimmt, harte Kanten bekommen keine Blende, und Copy-Mode hat
        ueberhaupt keine. Sonst wuerde die Vorschau etwas anderes zeigen als
        das, was hinterher herauskommt.
        """
        if not hasattr(self, "video_editor"):
            return
        # Waehrend ein Projekt geladen wird, hier nicht anfassen.
        #
        # Der Ladevorgang setzt den Bearbeitungsmodus erst am Ende. Wer vorher
        # hereinruft, arbeitet noch mit dem Modus des VORIGEN Projekts - stand
        # der auf "encode", wurden mitten im Laden Blenden gerendert, waehrend
        # der Player noch seine Dateien oeffnete. Gemessen am 30.08.2026: drei
        # Vorschau-Neuaufbauten und zwei Renderlaeufe desselben Auftrags
        # innerhalb eines einzigen Ladevorgangs.
        #
        # Nach "New Project" stand der Modus auf "off", deshalb trat das dort
        # nie auf - das war der ganze Unterschied zwischen den beiden Wegen.
        #
        # Dasselbe Muster benutzen _maybe_ask_index und _fps_nach_laden schon.
        # Der Aufbau kommt gleich nach dem Laden von selbst: _set_edit_mode
        # reiht dafuer ohnehin einen Aufruf ein.
        # Die Anzeige der Blenden zuerst: sie haengt weder am Player noch
        # daran, ob gerade geladen wird.
        self._blenden_an_timeline()

        if getattr(self, "_loading_project", False):
            print("[DEBUG] preview-cuts: Projekt wird geladen => spaeter")
            return
        if getattr(self, "_verschiebe_schritt", False):
            # Mitten im Umzug stuenden hier die Schnitte eines
            # Zwischenzustands. Die Blenden dazu waeren umsonst gerendert -
            # und das kostet Sekunden, nicht Millisekunden. Der Umzug ruft
            # am Ende selbst herein.
            print("[DEBUG] preview-cuts: Umzug laeuft => spaeter")
            return
        if not self.video_editor.supports_preview_cuts():
            print("[DEBUG] preview-cuts: Player kann das nicht "
                  "=> uebersprungen")
            return
        try:
            # ZUSAMMENGEFASSTE Schnitte, nicht die einzelnen.
            #
            # Grenzen zwei Schnitte aneinander oder ueberlappen sie, ist das im
            # Video EIN Loch. Aus den Einzelschnitten wurden bisher zwei
            # Blenden gebaut, und die innere blendete auf Material, das der
            # Nachbarschnitt bereits entfernt hat - im Bild ein kurzes
            # Standbild an der Stossstelle. Der Export war davon nie
            # betroffen: _compute_keep_intervals() fasst selbst zusammen.
            cuts = self.cut_manager.get_merged_cut_intervals()
        except Exception as e:
            print(f"[WARN] preview-cuts: Schnitte nicht lesbar: {e}")
            return

        total_dur = getattr(self, "real_total_duration", 0.0) or 0.0
        # Nur fuer die Protokollzeile: die tatsaechliche Laenge kann je
        # Schnitt abweichen, siehe _blende_fuer().
        vorgabe = self._blende_vorgabe()

        preview = []
        for (cstart, cend) in sorted(cuts, key=lambda x: x[0]):
            # Start- und Endschnitt, harte Kante und eingestellte Laenge
            # stecken alle in _blende_fuer(). cstart/cend koennen ein
            # zusammengefasster Bereich aus mehreren Schnitten sein, dessen
            # Schluessel es in _hard_cuts gar nicht gibt - deshalb loest die
            # Funktion ueber blende_fuer_bereich() auf und nicht ueber den
            # einzelnen Schluessel.
            preview.append((cstart, cend, self._blende_fuer(cstart, cend,
                                                            total_dur)))

        mit_blende = sum(1 for c in preview if c[2] > 0)
        naehte = self._merge_fades_aktiv()
        print(f"[DEBUG] preview-cuts: mode={getattr(self, '_edit_mode', '?')} "
              f"Vorgabe {vorgabe:.1f}s total={total_dur:.3f}s "
              f"=> {len(preview)} Schnitt(e), davon {mit_blende} mit Blende, "
              f"{len(naehte)} Merge-Fade(s)")

        # Blenden werden vorgerendert (siehe core/fade_cache.py). Was schon
        # fertig ist, kommt sofort mit; der Rest wird angefordert und per
        # _on_fades_ready nachgereicht. Bis dahin zeigt die Vorschau dort
        # einen harten Schnitt.
        self._fade_jobs = {}
        angereichert = []
        for (cstart, cend, fade) in preview:
            job = self._make_fade_job(cstart, cend, fade)
            pfad = None
            if job is not None:
                self._fade_jobs[(cstart, cend)] = job
                pfad = self._fade_renderer.ready_path(job)
            angereichert.append((cstart, cend, fade, pfad))
        # Merge-Fades gehen denselben Weg: ein Auftrag je Naht, in der
        # Vorschau ein Eintrag der Breite 0 mit dem Schnipsel (siehe
        # ges_backend.set_cuts). Ohne fertigen Schnipsel bleibt die Naht
        # vorerst hart, wie ein Schnitt ohne fertige Blende.
        for (naht, zeit, laenge) in naehte:
            job = self._make_merge_fade_job(naht, zeit, laenge)
            if job is None:
                continue
            self._fade_jobs[(zeit, zeit)] = job
            pfad = self._fade_renderer.ready_path(job)
            if pfad:
                angereichert.append((zeit, zeit, laenge, pfad))

        ok = self.video_editor.set_preview_cuts(angereichert)
        self._overlays_an_vorschau()
        print(f"[DEBUG] preview-cuts: uebernommen={ok}")
        offen = self._fade_renderer.request(list(self._fade_jobs.values()))

        # Immer anzeigen, sobald wirklich gerendert werden muss - egal von
        # welcher Stelle der Aufruf kam.
        #
        # Frueher haing das am Projektladen. Das ging daneben: der Ladevorgang
        # ruft hier zuerst im Modus "off" herein, da gibt es noch keine
        # Blenden. Die Arbeit entsteht erst beim anschliessenden Wechsel in den
        # Encode-Modus - und der lief ohne Fenster. Fertige Blenden werden
        # ohnehin wiederverwendet, das Fenster erscheint also nur, wenn
        # tatsaechlich etwas zu tun ist.
        if offen > 0:
            self._close_fade_dialog()
            self._fade_dialog = PreviewPrepareDialog(offen, self)
            self._fade_dialog.abgebrochen.connect(self._on_fades_abort)
            self._fade_dialog.show()
            self._fade_dialog.raise_()
            QApplication.processEvents()

    def _overlays_an_vorschau(self):
        """Overlays an die Vorschau geben, sofern das Backend sie zeigen kann.

        Nur im Encode-Mode. Nur dort gehen Overlays ueberhaupt in den Export -
        im Copy-Mode wird das Material durchgereicht, ein Logo kommt im
        Ergebnis nicht vor. Es trotzdem in der Vorschau zu zeigen, wuerde
        etwas versprechen, was hinterher fehlt. Dieselbe Ueberlegung wie bei
        den Blenden, die im Copy-Mode als harter Schnitt gezeigt werden.
        """
        try:
            if not self.video_editor.supports_preview_overlays():
                return
            if getattr(self, "_edit_mode", "") != "encode":
                self.video_editor.set_preview_overlays([], None)
                return
            liste, groesse = self._overlay_rechtecke()
            self.video_editor.set_preview_overlays(liste, groesse)
        except Exception as exc:
            print(f"[WARN] Overlays fuer die Vorschau: {exc}")

    def _overlay_rechtecke(self):
        """Overlays mit Lage und Groesse in Pixeln der EXPORTaufloesung.

        Rueckgabe: (liste, (export_breite, export_hoehe)) oder ([], None).

        Warum hier und nicht im Player: die Overlay-Daten enthalten
        ffmpeg-Ausdruecke wie "(W-w)-30". Die werden mit derselben Funktion
        ausgewertet, die auch der Export benutzt - so kann die Vorschau gar
        nicht anders rechnen als das fertige Video. Die Vorschau bekommt nur
        noch fertige Rechtecke und skaliert sie auf ihre eigene Groesse.

        Die Exporthoehe wird genauso bestimmt wie im Encoder: aus der
        eingestellten Breite und dem Seitenverhaeltnis der ersten Quelldatei,
        auf eine gerade Zahl gebracht. Sie steckt in Ausdruecken wie
        "(H-h)-70" und muss deshalb stimmen.
        """
        try:
            alle = self._overlay_manager.get_all_overlays()
        except Exception:
            return [], None
        if not alle or not getattr(self, "playlist", None):
            return [], None

        groesse = self._export_groesse()
        if groesse is None:
            return [], None
        breite, hoehe = groesse

        from managers.ges_encoder_manager import _zahl
        from PySide6.QtGui import QImage

        liste = []
        for platz, ovl in enumerate(alle):
            bild = ovl.get("image") or ""
            if not bild or not os.path.isfile(bild):
                continue
            bildgroesse = QImage(bild).size()
            bw, bh = bildgroesse.width(), bildgroesse.height()
            faktor = float(ovl.get("scale", 1.0) or 1.0)
            zw = max(1, int(round(bw * faktor))) if bw > 0 else 0
            zh = max(1, int(round(bh * faktor))) if bh > 0 else 0
            liste.append({
                # Platz in get_all_overlays(): damit ein im Bild verschobenes
                # Overlay wieder dem richtigen Eintrag zugeordnet werden kann.
                # Ueber den Listenplatz ginge das nicht - Overlays ohne
                # vorhandene Bilddatei fallen hier heraus.
                "index": platz,
                "start": float(ovl.get("start", 0.0)),
                "end": float(ovl.get("end", 0.0)),
                "fade_in": float(ovl.get("fade_in", 0) or 0),
                "fade_out": float(ovl.get("fade_out", 0) or 0),
                "image": bild,
                "scale": faktor,
                "x": _zahl(ovl.get("x", 0), (breite, hoehe), (zw, zh)),
                "y": _zahl(ovl.get("y", 0), (breite, hoehe), (zw, zh)),
                "w": zw, "h": zh,
            })
        return liste, (breite, hoehe)

    def _export_groesse(self):
        """(Breite, Hoehe) der Ausgabe, genauso bestimmt wie im Encoder.

        Aus der eingestellten Breite und dem Seitenverhaeltnis der ersten
        Quelldatei, auf eine gerade Zahl gebracht. Die Hoehe steckt in
        Ausdruecken wie "(H-h)-70" und muss deshalb stimmen.
        """
        if not getattr(self, "playlist", None):
            return None
        s = QSettings("KVRouite", "KVRouite")
        breite = int(s.value("encoder/res_w", 1280, type=int) or 1280)
        daten = framerate.eckdaten(self.playlist[0]) or {}
        qb, qh = daten.get("breite", 0), daten.get("hoehe", 0)
        if qb > 0 and qh > 0:
            hoehe = int(round(qh * breite / float(qb)))
            if hoehe % 2:
                hoehe += 1
        else:
            hoehe = int(s.value("encoder/res_h", 720, type=int) or 720)
        return breite, hoehe

    def _overlay_undo_merken(self, stand):
        """Overlay-Stand vor einer Aenderung auf den Strg+Z-Stapel legen.

        Overlays hatten bisher einen eigenen, von nirgendwo aufgerufenen
        Verlaufsstapel - Anlegen und Verschieben liessen sich also gar nicht
        zuruecknehmen. Jetzt liegen sie in derselben Reihe wie Schnitte und
        GPX-Aenderungen, und das gewohnte Strg+Z erfasst sie mit.
        """
        def zuruecknehmen():
            self._overlay_manager.set_all_overlays(stand)

        self._undo_ablegen(zuruecknehmen, "Overlay")

    def _overlay_im_bild_geaendert(self, index, x, y, skalierung):
        """Ein Overlay wurde im Vorschaubild verschoben oder skaliert.

        Ankommend sind Lage und Groesse in Exportpixeln. Zurueckgeschrieben
        wird mit der Verankerung, die im Overlay schon steht: was "30 Pixel
        vom rechten Rand" war, bleibt rechts verankert und bekommt nur einen
        anderen Abstand. Sonst saesse das Bild bei geaenderter
        Ausgabegroesse ploetzlich woanders.
        """
        from PySide6.QtGui import QImage
        from core import overlay_library

        try:
            alle = self._overlay_manager.get_all_overlays()
            if not (0 <= index < len(alle)):
                return
            ovl = alle[index]
            groesse = self._export_groesse()
            if groesse is None:
                return
            breite, hoehe = groesse

            bildgroesse = QImage(ovl.get("image") or "").size()
            bw, bh = bildgroesse.width(), bildgroesse.height()
            if bw <= 0 or bh <= 0:
                return
            faktor = max(0.01, float(skalierung))
            zw = max(1, int(round(bw * faktor)))
            zh = max(1, int(round(bh * faktor)))

            self._overlay_manager.update_overlay(
                index,
                x=overlay_library.lage_zurueck(ovl.get("x", 0), x, breite, zw, "x"),
                y=overlay_library.lage_zurueck(ovl.get("y", 0), y, hoehe, zh, "y"),
                scale=faktor,
            )
        except Exception as exc:
            print(f"[WARN] Overlay im Bild geaendert: {exc}")

    # ------------------------------------------------------------------
    # Blendenlaenge
    # ------------------------------------------------------------------
    def _blende_vorgabe(self) -> float:
        """Vorgabe aus dem Encoder Setup, in Sekunden.

        Sie gilt fuer jeden Schnitt, fuer den nichts Eigenes eingestellt ist.
        """
        try:
            return float(QSettings("KVRouite", "KVRouite").value(
                "encoder/xfade", 2, type=int))
        except Exception:
            return 2.0

    def _blende_fuer(self, cstart, cend, total_dur=None) -> float:
        """Blendenlaenge fuer diesen Schnitt oder Bereich, in Sekunden.

        EINE Stelle fuer alle drei Abnehmer - Vorschau, Nachreichen der
        fertig gerenderten Blenden und Export. Vorher stand die Entscheidung
        dreimal fast gleich da, mit dem globalen Wert als einziger Quelle;
        eine eingestellte Laenge haette man an allen dreien nachtragen
        muessen.
        """
        if getattr(self, "_edit_mode", "") != "encode":
            # Nur im Encode-Mode kommen Blenden ueberhaupt in den Export.
            return 0.0
        if total_dur is None:
            total_dur = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        if abs(cstart - 0.0) < 0.1:
            return 0.0      # Startschnitt: wird vor dem Zusammenfuegen getrimmt
        if total_dur > 0 and abs(cend - total_dur) < 0.1:
            return 0.0      # Endschnitt: ebenso
        return self.cut_manager.blende_fuer_bereich(
            cstart, cend, self._blende_vorgabe())

    def _blende_hoechstwert(self, start_s, end_s, cuts=None) -> float:
        """Wie lang die Blende dieses Schnitts hoechstens sein darf.

        Die Blende liegt MITTIG auf der Kante (siehe _make_fade_job): das
        abgehende Fenster reicht von cstart - fade/2 bis cstart + fade/2, das
        ankommende von cend - fade/2 bis cend + fade/2. Die halbe Laenge kommt
        also aus dem behaltenen Material davor beziehungsweise dahinter, die
        andere Haelfte aus dem Schnitt selbst.

        Entscheidend ist dabei, dass ein Zwischenraum ZWEI Blenden bedienen
        muss: die des Schnitts davor und die des Schnitts dahinter. Steht
        zwischen zwei Schnitten nur 5 s Material, darf keine der beiden
        Blenden mehr als 5 s lang sein - sonst greifen sie ineinander und
        holen sich Bilder aus dem Bereich, den der Nachbar schon
        weggeschnitten hat. Deshalb zaehlt ein Zwischenraum nur zur Haelfte,
        sobald an seinem anderen Ende ein weiterer Schnitt liegt. Grenzt er an
        den Videoanfang oder das Videoende, steht er ganz zur Verfuegung.

        Gerechnet wird auf den ZUSAMMENGEFASSTEN Bereichen. Aneinander
        stossende Schnitte sind im Video ein einziger Uebergang mit einer
        einzigen Blende; fuer einen inneren Schnitt einzeln zu rechnen ergaebe
        die Grenze 0, obwohl an dieser Stelle sehr wohl Platz ist.

        Dateigrenzen spielen keine Rolle: laeuft ein Fenster in die naechste
        Datei, rendert _make_fade_job() die Blende dateiuebergreifend, so
        wie der Export.
        """
        gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        try:
            # cuts erlaubt das Rechnen auf einer GEDACHTEN Schnittliste - so
            # laesst sich vor dem Setzen eines Schnitts sagen, was er den
            # Nachbarn wegnehmen wuerde.
            if cuts is None:
                bereiche = self.cut_manager.get_merged_cut_intervals()
            else:
                bereiche = self._zusammenfassen(cuts)
            keeps = self._compute_keep_intervals(bereiche, gesamt)
        except Exception:
            return 0.0

        # Den zusammengefassten Bereich suchen, zu dem dieser Schnitt gehoert.
        bereich = None
        for (a, b) in bereiche:
            if a <= start_s + 1e-6 and b >= end_s - 1e-6:
                bereich = (float(a), float(b))
                break
        if bereich is None:
            return 0.0
        a, b = bereich

        davor = danach = 0.0
        for (ks, ke) in keeps:
            if abs(ke - a) < 1e-6:
                # Zwischenraum direkt davor. Beginnt er am Videoanfang, steht
                # er ganz zur Verfuegung; sonst teilt ihn sich der Schnitt an
                # seinem anderen Ende.
                davor = (ke - ks) if ks <= 1e-6 else (ke - ks) / 2.0
            elif abs(ks - b) < 1e-6:
                danach = ((ke - ks) if ke >= gesamt - 1e-6
                          else (ke - ks) / 2.0)
        schnitt = max(0.0, b - a)
        return max(0.0, min(30.0, 2.0 * min(davor, danach, schnitt)))

    @staticmethod
    def _zusammenfassen(cuts):
        """Ueberlappende oder aneinander stossende Schnitte zusammenfassen.

        Dasselbe wie VideoCutManager.get_merged_cut_intervals(), nur fuer eine
        uebergebene Liste - gebraucht fuer die gedachte Schnittliste in der
        Vorabpruefung.
        """
        if not cuts:
            return []
        sortiert = sorted(((float(a), float(b)) for (a, b) in cuts),
                          key=lambda x: x[0])
        zusammen = []
        s_akt, e_akt = sortiert[0]
        for (a, b) in sortiert[1:]:
            if a <= e_akt:
                e_akt = max(e_akt, b)
            else:
                zusammen.append((s_akt, e_akt))
                s_akt, e_akt = a, b
        zusammen.append((s_akt, e_akt))
        return zusammen

    def _blenden_konflikte(self, cuts=None):
        """Welche Blenden passen bei dieser Schnittliste nicht mehr?

        cuts=None rechnet auf dem jetzigen Stand, sonst auf einer gedachten
        Liste - damit laesst sich ein Schnitt pruefen, BEVOR er gesetzt wird.

        Rueckgabe: Liste aus (start, ende, jetzige_laenge, hoechstwert), nur
        fuer Schnitte, deren Blende nicht mehr hineinpasst.
        """
        gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        vorgabe = self._blende_vorgabe()
        liste = list(self.cut_manager._cut_intervals if cuts is None else cuts)
        konflikte = []

        for (a, b) in liste:
            a, b = float(a), float(b)
            if abs(a) < 0.1 or (gesamt > 0 and abs(b - gesamt) < 0.1):
                continue                  # Start-/Endschnitt: nie eine Blende
            if self.cut_manager.is_hard_cut(a, b):
                continue                  # harte Kante braucht keinen Platz
            eigen = self.cut_manager.get_blende(a, b)
            jetzt = float(vorgabe if eigen is None else eigen)
            hoechst = self._blende_hoechstwert(a, b, cuts=liste)
            if jetzt > hoechst + 1e-6:
                konflikte.append((a, b, jetzt, hoechst))
        return konflikte

    @staticmethod
    def _blende_abrunden(hoechst) -> float:
        """Auf 0,1 s abrunden. Aufgerundet waere die Grenze wieder ueberschritten."""
        import math
        return math.floor(max(0.0, float(hoechst)) * 10.0) / 10.0

    def _blenden_konflikt_fragen(self, neue_cuts, anlass):
        """Vor einer Aenderung fragen, wenn eine Blende dadurch nicht mehr passt.

        Gekuerzt wird NICHTS von selbst. Eine eingestellte Blendenlaenge ist
        eine Entscheidung des Nutzers; sie hinter seinem Ruecken zu aendern
        waere schlimmer als die Rueckfrage. Er hat zwei Moeglichkeiten:
        kuerzen lassen - dann steht im Fenster, auf welchen Wert - oder
        abbrechen und den betroffenen Schnitt erst selbst in Ordnung bringen.

        Rueckgabe (weiter, kuerzungen):
          weiter     False heisst: der Nutzer hat abgebrochen, die Aenderung
                     unterbleibt vollstaendig
          kuerzungen Liste (start, ende, neue_laenge), die NACH der Aenderung
                     anzuwenden ist - vorher gibt es den neuen Schnitt noch
                     nicht, und die Schluessel haengen an den Schnitten.
        """
        konflikte = self._blenden_konflikte(neue_cuts)
        if not konflikte:
            return True, []

        zeilen = []
        kuerzungen = []
        for (a, b, jetzt, hoechst) in konflikte:
            neu = self._blende_abrunden(hoechst)
            kuerzungen.append((a, b, None if neu < 0.1 else neu))
            zeilen.append(
                "    %s - %s:  crossfade %.1f s, only %.1f s would fit"
                % (self._sek_kurz(a), self._sek_kurz(b), jetzt, neu))

        kasten = QMessageBox(self)
        kasten.setIcon(QMessageBox.Warning)
        kasten.setWindowTitle("Not enough room for the crossfade")
        kasten.setText(
            "%s would leave too little material for a crossfade that is "
            "already set:\n\n%s\n\n"
            "The fade lies centred on the cut, so half of it has to fit into "
            "the kept material on each side - and a gap between two cuts has "
            "to serve both of them.\n\n"
            "Shorten the crossfade of the cut named above, or cancel and "
            "adjust it yourself first."
            % (anlass, "\n".join(zeilen)))
        b_kuerzen = kasten.addButton("Shorten crossfade",
                                     QMessageBox.AcceptRole)
        kasten.addButton("Cancel", QMessageBox.RejectRole)
        kasten.setDefaultButton(b_kuerzen)
        kasten.exec()

        if kasten.clickedButton() is not b_kuerzen:
            print("[BLENDE] Konflikt: der Nutzer hat abgebrochen")
            return False, []
        return True, kuerzungen

    def _blenden_kuerzen(self, kuerzungen):
        """Die im Fenster zugesagten Kuerzungen anwenden."""
        for (a, b, neu) in (kuerzungen or []):
            if neu is None:
                self.cut_manager.set_blende(a, b, None)
                self.cut_manager.set_hard_cut(a, b, True)
                print(f"[BLENDE] {a:.3f}-{b:.3f}: kein Platz mehr, harte Kante")
            else:
                self.cut_manager.set_blende(a, b, neu)
                print(f"[BLENDE] {a:.3f}-{b:.3f}: gekuerzt auf {neu:.1f} s")

    def _kandidat_aus_marken(self):
        """Der Schnitt, den on_cut_clicked() aus den Marken machen wuerde.

        Dieselbe Klemmung wie dort. None, wenn daraus kein Schnitt wird.
        """
        cm = self.cut_manager
        if cm.markB_time_s < 0 or cm.markE_time_s < 0:
            return None
        a = min(cm.markB_time_s, cm.markE_time_s)
        b = max(cm.markB_time_s, cm.markE_time_s)
        gesamt = sum(self.video_durations) if self.video_durations else 0.0
        a = max(0.0, a)
        b = min(b, gesamt) if gesamt > 0 else b
        if (b - a) < 0.01:
            return None
        return (float(a), float(b))

    def _cuts_mit(self, kandidat, ohne=None):
        """Die gedachte Schnittliste: aktuelle, ohne 'ohne', plus 'kandidat'.

        Ein neuer Endschnitt ersetzt einen vorhandenen, ein neuer
        Anfangsschnitt ebenso - das muss die gedachte Liste abbilden, sonst
        rechnet die Pruefung mit einem Schnitt, den es gleich nicht mehr gibt.
        """
        gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        a, b = kandidat
        ist_ende = gesamt > 0 and abs(b - gesamt) < 0.1
        ist_anfang = a < 0.1

        liste = []
        for (ca, cb) in self.cut_manager._cut_intervals:
            if ohne is not None and (abs(ca - ohne[0]) < 1e-9
                                     and abs(cb - ohne[1]) < 1e-9):
                continue
            if ist_ende and gesamt > 0 and abs(cb - gesamt) < 0.1:
                continue
            if ist_anfang and ca < 0.1:
                continue
            liste.append((float(ca), float(cb)))
        liste.append((float(a), float(b)))
        return liste

    def _blenden_lage_melden(self):
        """Nach dem Laden: passt noch alles? Nur melden, nichts aendern.

        Ein geladenes Projekt war beim Speichern stimmig. Weicht es jetzt ab,
        wurde zwischenzeitlich die Vorgabe im Encoder Setup geaendert - dann
        ist es erst recht nicht an uns, die Laengen zu verstellen.
        """
        konflikte = self._blenden_konflikte()
        if not konflikte:
            return
        zeilen = ["    %s - %s:  crossfade %.1f s, only %.1f s fits"
                  % (self._sek_kurz(a), self._sek_kurz(b), jetzt, hoechst)
                  for (a, b, jetzt, hoechst) in konflikte]
        for z in zeilen:
            print("[BLENDE] passt nicht mehr:" + z)
        QMessageBox.information(
            self, "Crossfades do not fit",
            "In this project there is not enough room for every crossfade:"
            "\n\n%s\n\n"
            "Nothing was changed. Adjust the length with the right-click menu "
            "on the cut, or move the cuts apart." % "\n".join(zeilen))

    def _alte_schnitte_melden(self):
        """Nach dem Laden: welche Schnitte lassen sich nicht mehr anfassen?

        Verschieben und Zuruecknehmen brauchen die Aufzeichnung dessen, was
        der Schnitt aus der GPX-Spur genommen hat (cut_points in der
        Projektdatei, seit 6.03) und einen Fingerabdruck der Spur, der noch
        stimmt. Fehlt eines davon, sperrt ruecknahme_moeglich() den Schnitt -
        bisher erfuhr der Nutzer das erst, wenn er die Kante schon in der
        Hand hatte. Vorschlag von Bernd am 05.09.2026: gleich beim Laden
        sagen, woran er ist. Nur melden, nichts aendern.

        Ohne GPX-Spur gibt es nichts zurueckzurechnen, dann sind alle
        Schnitte frei und es gibt nichts zu melden.
        """
        if not self._gpx_data:
            return
        schnitte = list(self.cut_manager._cut_intervals)
        if not schnitte:
            return
        ohne = [(a, b) for (a, b) in schnitte
                if not self.cut_manager.hat_aufzeichnung(a, b)]
        mit = len(schnitte) - len(ohne)
        spur_passt = self.cut_manager.zeiten_unveraendert(self._gpx_data)

        if not ohne and spur_passt:
            return

        zeilen = []
        if ohne:
            if len(ohne) == len(schnitte):
                zeilen.append(
                    "This project was saved by an older KVRouite (before "
                    "6.03). None of its %d cut(s) carries a record of the "
                    "GPX points it removed." % len(schnitte))
            else:
                zeilen.append(
                    "%d of the %d cuts in this project carry no record of "
                    "the GPX points they removed:" % (len(ohne), len(schnitte)))
                zeilen.append("\n".join("    %s - %s" % (self._sek_kurz(a),
                                                          self._sek_kurz(b))
                                        for (a, b) in ohne))
        if mit and not spur_passt:
            zeilen.append(
                "The GPX track no longer matches the %d recorded cut(s): its "
                "times have changed since they were saved, or the project "
                "carries no fingerprint of the track." % mit)
        zeilen.append(
            "While a GPX track is loaded, these cuts can be neither moved "
            "nor undone - the track could not be put back correctly. "
            "New cuts you set now are recorded and stay editable.")
        for z in zeilen:
            print("[CUT-REC] " + z.replace("\n", " "))
        QMessageBox.information(
            self, "Cuts in this project are fixed", "\n\n".join(zeilen))

    def _blenden_an_timeline(self):
        """Der Zeitleiste sagen, wie lang die Blende je Uebergang ist.

        Sie zeichnet damit die Ueberblendung, die ins behaltene Material
        hineinreicht. Zusammengefasste Bereiche, wie ueberall sonst auch:
        aneinander stossende Schnitte sind EIN Uebergang.
        """
        gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        try:
            bereiche = self.cut_manager.get_merged_cut_intervals()
            self.timeline.set_blenden_laengen(
                [(a, b, self._blende_fuer(a, b, gesamt))
                 for (a, b) in bereiche])
            self.timeline.set_merge_fades(
                {naht: laenge
                 for (naht, _zeit, laenge) in self._merge_fades_aktiv()})
        except Exception as e:
            print(f"[WARN] Blenden an die Zeitleiste: {e}")

    def _blende_am_rand(self, zeit_s) -> float:
        """Blendenlaenge des Schnitts, der an dieser Keep-Grenze liegt.

        Fuer die Overlay-Pruefung: wie viel Platz ein Overlay zur Grenze
        seines Keep-Segments halten muss, haengt daran, wie lang die Blende
        des dortigen Schnitts ist - und die ist seit 6.03 nicht mehr fuer
        alle gleich. Videoanfang und -ende liefern 0: dort gibt es keine
        Blende, die Platz braeuchte.
        """
        gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
        for (a, b) in self.cut_manager.get_merged_cut_intervals():
            if abs(b - zeit_s) < 0.001 or abs(a - zeit_s) < 0.001:
                return self._blende_fuer(a, b, gesamt)
        return 0.0

    def _make_fade_job(self, cstart, cend, fade):
        """
        Beschreibt die zu rendernde Blende fuer einen Schnitt.

        Die Blende liegt MITTIG auf dem Schnitt: bei 2 s Blende ueberlappen
        sich die beiden Seiten um 2 s, je zur Haelfte vor und hinter der
        Schnittkante. Abgehend ist also [cstart - fade/2 .. cstart + fade/2],
        ankommend [cend - fade/2 .. cend + fade/2]. Die jeweils innere Haelfte
        stammt aus dem weggeschnittenen Bereich, die aeussere aus dem
        behaltenen Material - so machen es Schnittprogramme ueblicherweise,
        und die Gesamtlaenge aendert sich dadurch nicht.

        Ein Fenster darf ueber eine Dateigrenze laufen. Es wird dann in
        Stuecke je Datei zerlegt - dieselbe Zerlegung, die der Export macht
        (ges_encoder_manager._Quellen.stuecke). Bis 6.11 fiel die Vorschau
        hier an jeder Dateigrenze stumm auf einen harten Schnitt zurueck,
        waehrend der Export die Blende rendert; an dieser Stelle zeigte sie
        also nicht das, was hinterher herauskommt.

        None, wenn keine Blende noetig ist oder ein Fenster ueber den Anfang
        oder das Ende des Videos hinausreicht - dann bleibt es beim harten
        Schnitt.
        """
        if fade <= 0 or not getattr(self, "playlist", None):
            return None
        durations = getattr(self, "video_durations", None) or []
        if len(durations) != len(self.playlist):
            return None
        gesamt = sum(durations)

        def stuecke(t, laenge):
            """[(Datei, Sekunde darin, Dauer)] fuer das Fenster [t, t+laenge].

            Ein Rest von Nanosekunden an einer Dateigrenze ergibt ein Stueck
            ohne ganzes Bild; fade_cache laesst es beim Rastern weg. Genau
            so ein Rest war der Ausloeser am 06.09.2026: Fensteranfang
            1953.117833333 gegen eine Grenze bei 1953.1178333333332 - das
            Fenster galt damit als "laeuft in die naechste Datei".
            """
            if t < -1e-6 or t + laenge > gesamt + 1e-6:
                return None
            teile = []
            start = 0.0
            for pfad, d in zip(self.playlist, durations):
                von = max(t, start)
                bis = min(t + laenge, start + d)
                if bis - von > 0:
                    teile.append((pfad, von - start, bis - von))
                start += d
            return teile or None

        halb = fade / 2.0
        a = stuecke(cstart - halb, fade)
        b = stuecke(cend - halb, fade)
        if a is None or b is None:
            print(f"[DEBUG] Blende {cstart:.2f}-{cend:.2f}: Fenster reicht ueber "
                  f"Anfang oder Ende des Videos hinaus, bleibt harter Schnitt")
            return None
        if len(a) > 1 or len(b) > 1:
            print(f"[DEBUG] Blende {cstart:.2f}-{cend:.2f}: Material liegt ueber "
                  f"einer Dateigrenze, wird dateiuebergreifend gerendert")

        # Bildrate als exakter BRUCH, gelesen aus der Quelldatei der
        # abgehenden Seite. Frueher stand hier (int(fps * 1000), 1000), also
        # der Rueckweg aus einer Kommazahl - aus 29,97002997 wurde damit
        # 29970/1000 statt 30000/1001. Der Schnipsel lief dann minimal zu
        # langsam, und weil die Bildrate im Schluessel des Zwischenspeichers
        # steckt, konnte derselbe Schnitt mehrfach gerendert werden.
        fps = framerate.lesen(a[0][0]) or (30000, 1001)
        return FadeJob(a, b, float(fade),
                       self.video_editor.preview_width(), fps)

    def _on_fades_progress(self, fertig, gesamt):
        if gesamt <= 0:
            return
        self.statusBar().showMessage(
            f"Rendering crossfades for the preview: {fertig}/{gesamt}", 0)
        if getattr(self, "_fade_dialog", None):
            self._fade_dialog.setzen(fertig, gesamt)

    def _on_fades_meldung(self, text):
        """Eine Zeile aus dem Renderer, woran er gerade arbeitet.

        Ins Fenster, wenn es steht, und in die Statuszeile. Das Fenster
        zeichnet sich dabei selbst neu (schritt() reicht die Ereignisse
        durch) - das Ziehen eines Standbilds blockiert gleich darauf fuer
        Sekunden, und ohne das stuende die Zeile erst hinterher da.
        """
        self.statusBar().showMessage(text, 0)
        dlg = getattr(self, "_fade_dialog", None)
        if dlg is not None:
            dlg.schritt(text)
        else:
            QApplication.processEvents()

    def _on_fades_abort(self):
        """Benutzer bricht das Vorrendern ab - offene Schnitte bleiben hart."""
        self._fade_renderer.cancel()
        self._close_fade_dialog()
        self.statusBar().clearMessage()

    def _close_fade_dialog(self):
        dlg = getattr(self, "_fade_dialog", None)
        self._fade_dialog = None
        if dlg is not None:
            try:
                dlg.close()
                dlg.deleteLater()
            except Exception:
                pass

    def _on_fades_ready(self):
        """Alle Blenden liegen vor - Timeline mit den fertigen Dateien neu setzen."""
        self.statusBar().clearMessage()
        self._close_fade_dialog()
        if not self._fade_jobs or not self.video_editor.supports_preview_cuts():
            return
        try:
            # Dieselbe Grundlage wie in _refresh_preview_timeline: die
            # ZUSAMMENGEFASSTEN Schnitte. Sonst wird hier unter den Schluesseln
            # der Einzelschnitte gesucht, waehrend die Auftraege unter denen
            # der zusammengefassten liegen - die fertige Blende wird dann nicht
            # gefunden und die Vorschau ohne sie neu gesetzt.
            cuts = self.cut_manager.get_merged_cut_intervals()
        except Exception:
            return
        total_dur = getattr(self, "real_total_duration", 0.0) or 0.0

        fertig = []
        gefunden = 0
        for (cstart, cend) in sorted(cuts, key=lambda x: x[0]):
            fade = self._blende_fuer(cstart, cend, total_dur)
            job = self._fade_jobs.get((cstart, cend))
            pfad = self._fade_renderer.ready_path(job) if job is not None else None
            if pfad:
                gefunden += 1
            fertig.append((cstart, cend, fade, pfad))
        for (naht, zeit, laenge) in self._merge_fades_aktiv():
            job = self._fade_jobs.get((zeit, zeit))
            pfad = self._fade_renderer.ready_path(job) if job is not None else None
            if pfad:
                gefunden += 1
                fertig.append((zeit, zeit, laenge, pfad))

        print(f"[DEBUG] Blenden fertig: {gefunden} von {len(self._fade_jobs)}")
        self.video_editor.set_preview_cuts(fertig)
        self._overlays_an_vorschau()
        QTimer.singleShot(0, self._maybe_ask_index)
        
        
    ## on_safe_click
    def on_render_clicked(self):
        # 1) Sicherheitsabfrage. Im Encode-Mode zeigt sie zugleich die
        # Encoder-Einstellungen und die drei Schalter der Tonspur
        # (views/export_bestaetigung) - was dort umgeschaltet wird, steht
        # danach in den Einstellungen und wird unten gelesen.
        if self._edit_mode == "encode":
            # Fuer den Zeithinweis zaehlt, was im Ergebnis landet: die
            # Gesamtlaenge ohne die Schnitte.
            gesamt = float(getattr(self, "real_total_duration", 0.0) or 0.0)
            try:
                gesamt -= sum(max(0.0, float(e) - float(s))
                              for (s, e) in self.cut_manager.get_cut_intervals())
            except Exception:
                pass
            anzahl, sekunden = self._sprechstellen_summe()
            frage = ExportBestaetigung(
                self, gesamt_sekunden=max(0.0, gesamt),
                dateien=len(self.playlist),
                sprechstellen=(anzahl, sekunden) if anzahl else None)
            ergebnis = frage.exec()
            # Die drei Schalter koennen dort umgestellt worden sein.
            self._sprechstellen_bedienung_nachziehen()
            if ergebnis != QDialog.Accepted:
                return
        else:
            msg = QMessageBox(self)
            msg.setWindowTitle("Are you sure?")
            msg.setText("We are now creating the final video, changes are no longer possible! Sure?")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            r = msg.exec()
            if r == QMessageBox.No:
                return

        if not self.playlist:
            QMessageBox.warning(self, "Error", "No videos in playlist!")
            return
            
        # -------------------------------------------------
        # NEUE LOGIK: Wenn Edit-Mode == "encode" => JSON schreiben
        if self._edit_mode == "encode":
            
            # 1) Daten aus QSettings lesen (Encoder Setup)
            s = QSettings("KVRouite","KVRouite")
            # Die Blendenlaenge steht nicht mehr hier: sie kann je
            # Schnitt abweichen und wird unten Schnitt fuer Schnitt
            # ueber _blende_fuer() bestimmt.
            hw_encode   = s.value("encoder/hw", "none", type=str)
            container   = s.value("encoder/container", "x265", type=str)
            crf_val     = s.value("encoder/crf", 25, type=int)
            # Als BRUCH weitergeben ("30000/1001"), nicht als gerundete
            # Zahl - sonst ist die Genauigkeit sofort wieder dahin.
            # Beide Encoder-Wege verstehen die Schreibweise: ffmpeg als
            # "-r 30000/1001", GES als Zaehler und Nenner.
            fps_val     = framerate.als_text(
                *framerate.parsen(s.value("encoder/fps", "30", type=str)))
            preset_val  = s.value("encoder/preset", "fast", type=str)
            width_val   = s.value("encoder/res_w", 1280, type=int)
            # Seite "Audio" im Encoder Setup (ab 7.0): Tonspur an/aus und
            # ihre Bitrate. Als Zahl abgelegt, siehe core/encoder_presets.
            # Tonspur und Daempfer sind reines GStreamer und gehen auch in
            # Lite. Nur "Remove voices" braucht das Voice-Zusatzpaket
            # (gepackt) bzw. requirements-voice.txt (ungepackt); ohne es
            # bleibt der Schalter wirkungslos, was immer in den
            # Einstellungen steht.
            voice_da    = stimme.verfuegbar()[0]
            audio_an    = bool(s.value("encoder/audio", 1, type=int))
            audio_kbps  = s.value("encoder/audio_kbps", 128, type=int)
            traffic_an  = bool(s.value("encoder/traffic", 0, type=int))
            traffic_db  = s.value("encoder/traffic_db", 12, type=int)
            traffic_hz  = s.value("encoder/traffic_fill_hz", 1000, type=int)
            voice_an    = voice_da and bool(s.value("encoder/voice", 0, type=int))
            voice_model = s.value("encoder/voice_model", "mdx", type=str)

            # 2) Cuts => skip_instructions
            #   Format [start_s, end_s, xfade]
            cuts = self.cut_manager.get_cut_intervals()  # Liste (start_s, end_s)
            skip_array = []
            total_dur = self.real_total_duration
            sorted_cuts = sorted(cuts, key=lambda x: x[0])
            
            for (cstart, cend) in sorted_cuts:
                if abs(cstart - 0.0) < 0.1:
                    skip_array.append([cstart, cend, -2])  # Startcut
                elif abs(cend - total_dur) < 0.1:
                    skip_array.append([cstart, cend, -1])  # Endcut
                else:
                    # Der dritte Wert ist die Blendendauer DIESES Schnitts.
                    # 0 bedeutet harte Kante: der Encoder baut dann weder
                    # A-/B-Segment noch Crossfade, die Schnittkante und die
                    # Gesamtlaenge bleiben unveraendert.
                    # Eingestellte Laenge, harte Kante oder Vorgabe -
                    # dieselbe Entscheidung wie in der Vorschau, damit beide
                    # nicht auseinanderlaufen koennen.
                    skip_array.append(
                        [cstart, cend,
                         self._blende_fuer(cstart, cend, total_dur)])
        
            # Merge-Fades an den Naehten: [[rohzeit, laenge], ...]. Dieselbe
            # Liste wie in der Vorschau (_merge_fades_aktiv), damit beide
            # nicht auseinanderlaufen koennen. Im Copy-Mode ist sie leer.
            merge_fades = [[zeit, laenge]
                           for (_naht, zeit, laenge) in self._merge_fades_aktiv()]

            # Debug-Ausgabe, damit du siehst, was wirklich passiert:
            print("DEBUG skip_array:", skip_array)
            print("DEBUG merge_fades:", merge_fades)
            
            print("DEBUG: Chronologisch sortierte skip_array:", skip_array)



            # 3) Overlays => overlay_instructions
            #   Jedes Overlay = dict mit "start","end","fade_in","fade_out","image","scale","x","y"
            all_ovls = self._overlay_manager.get_all_overlays()
            overlay_list = []
            for ovl in all_ovls:
                overlay_list.append({
                    "start":    ovl["start"],
                    "end":      ovl["end"],
                    "fade_in":  ovl.get("fade_in", 0),
                    "fade_out": ovl.get("fade_out", 0),
                    "image":    ovl.get("image",""),
                    "scale":    ovl.get("scale",1.0),
                    "x":        ovl.get("x","0"),
                    "y":        ovl.get("y","0"),
                })

            # 4) Ziel-Dateinamen (können Sie frei anpassen)
            merged_out = "merged.mp4"
            final_out  = "final_out.mp4"

            # 5) JSON-Dict bauen
            export_data = {
                "videos": self.playlist,
                "skip_instructions": skip_array,
                "merge_fades": merge_fades,
                "overlay_instructions": overlay_list,
                "merged_output": merged_out,
                "final_output": final_out,
                "hardware_encode": hw_encode,
                # "encoder" könnte z.B. "libx264"/"libx265" heißen:
                "encoder": f"lib{container}",  
                "crf": crf_val,
                "fps": fps_val,
                "width": width_val,
                "preset": preset_val,
                # Tonspur: ohne "audio" rendert ges_encoder_manager wie bis
                # 6.14 ohne Ton.
                "audio": audio_an,
                "audio_kbps": audio_kbps,
                # Verkehr daempfen (core/verkehr): Schalter und Daempfer.
                "traffic": traffic_an,
                "traffic_db": traffic_db,
                # Tiefpass auf dem Fuellstueck in Hz, 0 = ungefiltert.
                "traffic_fill_hz": traffic_hz,
                # Stimmen entfernen (core/stimme): Schalter und Modell.
                "voice": voice_an,
                "voice_model": voice_model,
                # Sprechstellen je Datei (Sekunden der Datei): gibt es
                # welche, trennt der Voice Remover nur dort.
                "voice_regions": self._sprechstellen_export(),
                # 360: derselbe Abschnitt wie in der Projektdatei. Ist er an,
                # rendert ges_encoder_manager das projizierte 16:9-Bild statt
                # des verzerrten 2:1-Equirects.
                "view360": self._blick360_export_cfg()
            }

            
            #temp_dir = tempfile.gettempdir()
            # 6) In unser KVRouite-Temp speichern
            
            temp_dir = MY_GLOBAL_TMP_DIR
            json_path = os.path.join(temp_dir, "vg_encoder_job.json")
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)

            #dlg = EncoderDialog(parent=self)
            #dlg.run_encoding(json_path)
            #dlg.exec()
            #self.setWindowTitle("Encoding in progress – please wait…")
            
            dlg = EncoderDialog(parent=self)
            self._encoder_dialog = dlg      # fuer closeEvent(): laeuft ein Export?
            dlg.show()  # ⬅️ Fenster sofort zeigen!
            QApplication.processEvents()  # ⬅️ wichtig, damit GUI reagiert

            dlg.run_encoding(json_path)  # ⬅️ d
            
            
            return
        
            

        total_dur = self.real_total_duration
        sum_cuts = self.cut_manager.get_total_cuts()
        final_duration_s = total_dur - sum_cuts
        if final_duration_s < 0:
            final_duration_s = 0

        out_file, _ = QFileDialog.getSaveFileName(
            self,
            "Select output file",
            "output_final.mp4",
            "Video Files (*.mp4)"
        )
        
        if not out_file:
            return
        if not out_file.lower().endswith('.mp4'):
            out_file += '.mp4'
            # Optional: Benutzer informieren
            QMessageBox.information(
                self, 
                "File Extension Added!",
                f"Added '.mp4' extension to filename:\n{os.path.basename(out_file)}"
            )

        keep_intervals = self._compute_keep_intervals(self.cut_manager._cut_intervals, total_dur)
        if not keep_intervals:
            QMessageBox.warning(self, "Error", "All time ranges are cut! Nothing to export.")
            return

       
        tmp_dir = MY_GLOBAL_TMP_DIR  # denselben Ordner nutzen
        

        # 2) Statt direkt ffmpeg aufzurufen => wir bauen eine Liste an Commands
        segment_commands = []
        segment_files = []
        seg_index = 0

        for (global_start, global_end) in keep_intervals:
            partials = self._resolve_partial_intervals(global_start, global_end)
            for (vid_idx, local_st, local_en) in partials:
                source_path = self.playlist[vid_idx]
                seg_len = local_en - local_st
                if seg_len <= 0.01:
                    continue
                out_segment = os.path.join(tmp_dir, f"segment_{seg_index:03d}.mp4")
                segment_files.append(out_segment)

                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{local_st:.3f}",
                    "-to", f"{local_en:.3f}",
                    "-i", source_path,
                    "-c", "copy",
                    out_segment
                ]
                segment_commands.append(cmd)
                seg_index += 1

        # 3) Concat-File
        concat_file = os.path.join(tmp_dir, "concat_list.txt")
        with open(concat_file, "w") as f:
            for segpath in segment_files:
                f.write(f"file '{segpath}'\n")

        final_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            out_file
        ]

        # 4) Nun unser asynchroner Dialog
        dlg = _SafeExportDialog(self)
        # concat_file und segment_files werden mitgegeben, damit der Dialog die
        # Liste NACH dem Schneiden noch einmal schreiben kann - erst dann
        # existieren die Segmente und ihre echte Laenge ist messbar.
        dlg.set_commands(segment_commands, final_cmd, out_file,
                         concat_file=concat_file, segment_files=segment_files)
        dlg.start_export()  # startet direkt den ersten ffmpeg-Aufruf
        dlg.exec()

        # Wenn du hierher kommst, ist der Dialog geschlossen => entweder fertig oder abgebrochen
        # Ggf. könntest du ein "if dlg.result() == QDialog.Accepted" => print("OK!") etc.
        if dlg.result() == QDialog.Accepted:
            print("Export was successful!")
        else:
            print("Export canceled or error.")

        
   
        

    def _resolve_partial_intervals(self, global_start, global_end):
        results = []
        if global_end <= global_start:
            return results
        if len(self.video_durations) == 0:
            return results

        boundaries = []
        offset = 0.0
        for dur in self.video_durations:
            offset += dur
            boundaries.append(offset)

        current_s = global_start
        end_s = global_end

        idx = 0
        prev_offset = 0.0
        for i, b in enumerate(boundaries):
            if current_s < b:
                idx = i
                prev_offset = boundaries[i - 1] if i > 0 else 0.0
                break

        while current_s < end_s and idx < len(boundaries):
            video_upper = boundaries[idx]
            local_st = current_s - prev_offset
            segment_end_global = min(end_s, video_upper)
            local_en = segment_end_global - prev_offset

            if local_en > local_st:
                results.append((idx, local_st, local_en))

            current_s = segment_end_global
            idx += 1
            if idx < len(boundaries):
                prev_offset = boundaries[idx - 1]

        return results

    def get_final_time_for_global(self, global_s: float, cut_intervals=None) -> float:
        """
        Konvertiert 'global_s' (Rohvideo-Zeit) => 'final_s' (geschnittenes Video).
        Liegen wir exakt auf dem Start eines Cuts, springen wir an den Endpunkt
        des vorherigen Keep-Segments.

        cut_intervals: normalerweise None => die aktuellen Schnitte. Beim
        Ersetzen eines End-Schnitts muss der alte End-Schnitt hier aber schon
        ausgeblendet sein, sonst laege der neue Startpunkt "im Cut" und wuerde
        auf das Ende des davorliegenden Keep-Segments abgebildet.
        """
        if cut_intervals is None:
            cut_intervals = self.cut_manager._cut_intervals
        total_dur = self.real_total_duration
        if not cut_intervals:
            return min(global_s, total_dur)

        keep_list = self._compute_keep_intervals(cut_intervals, total_dur)
        final_time = 0.0
        EPS = 1e-9

        for (kstart, kend) in keep_list:
            seg_len = (kend - kstart)
            if global_s < (kstart - EPS):
                break
            elif abs(global_s - kstart) <= EPS:
                # exact Start => final bleibt am Ende des letzten
                return final_time
            elif kstart <= global_s < (kend - EPS):
                final_time += (global_s - kstart)
                return final_time
            else:
                final_time += seg_len

        return final_time
        
        
    def get_global_time_for_final(self, final_s: float) -> float:
        """
        Konvertiert 'final_s' (geschnittenes Video) => 'global_s' (Rohvideo-Zeit).
        Liegt final_s exakt am Keep-Segmentende, springen wir ins nächste Segment.
        """
        cut_intervals = self.cut_manager._cut_intervals
        total_dur = self.real_total_duration
        if not cut_intervals:
            return min(final_s, total_dur)

        keep_list = self._compute_keep_intervals(cut_intervals, total_dur)
        remaining = final_s
        # Eine Mikrosekunde: feiner sind GPX-Zeiten nicht (datetime). Der
        # Nahtpunkt eines Video-Cuts liegt genau auf dem Segmentende, kommt
        # aber ueber datetime mit bis zu 0.5 us Abweichung zurueck. Mit 1 ns
        # Toleranz galt er je nach Richtung als "kurz davor" und landete nach
        # der ms-Rundung auf dem Schnittbeginn - "inside a cut segment".
        # Nur der Sprung Zeile -> Video rechnet hier, der Export nicht.
        EPS = 1e-6

        for (seg_start, seg_end) in keep_list:
            seg_len = (seg_end - seg_start)

            if remaining < seg_len - EPS:
                return seg_start + remaining
            elif abs(remaining - seg_len) <= EPS:
                # exakt Segmentende => Skip in den Anfang des nächsten Keep
                remaining = 0.0
            else:
                remaining -= seg_len

        return total_dur    

    def on_set_video_gpx_sync_clicked(self):
        """
        Define synchronization match between selected GPX and video time
        """
        global_s = self.video_editor.get_current_position_s()
        print(f"[DEBUG] on_set_video_gpx_sync_clicked => get_current_position_s()={global_s:.3f}")
        
        # 2) => final_s, falls Cuts 
        final_s = self.get_final_time_for_global(global_s)

        row = self.gpx_widget.gpx_list.table.currentRow()
        gpx_time = self._gpx_data[row]["time"] - self._gpx_data[0]["time"]
        new_shift=  final_s - gpx_time.total_seconds()

        reply = QMessageBox.question(
                self,
                "Video-GPX sync point",
                f"Define GPX at {gpx_time} synced with {final_s:.1f} seconds in video?\n"
                f"GPX-video shift will be {new_shift:.1f} seconds (undo possible).",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        if reply == QMessageBox.Yes:
            self.register_gpx_undo_snapshot(
                self.gpx_widget.gpx_list.schritt_text("Set video-GPX sync", row))
            set_gpx_video_shift(new_shift)
            #recalc_gpx_data(self._gpx_data) #to refresh list
            self.gpx_widget.gpx_list.set_gpx_data(self._gpx_data)
            self.video_control.activate_controls()
            #self.enableVideoGpxSync()
            if hasattr(self, "action_auto_sync_video"):
                if not self.action_auto_sync_video.isChecked():
                    self.action_auto_sync_video.setChecked(True)
                self._on_auto_sync_video_toggled(True)
                if hasattr(self, "video_control"):
                    self.video_control._update_autocut_icon()

            if hasattr(self, "action_new_pts_video_time"):
                if not self.action_new_pts_video_time.isChecked():
                    self.action_new_pts_video_time.setChecked(True)
                self._on_sync_point_video_time_toggled(True)
            
            if(get_gpx_video_shift() < 0): # color negative points in grey
                route_geojson = self._build_route_geojson_from_gpx(self._gpx_data)
                self.map_widget.loadRoute(route_geojson, do_fit=False)
            if self._edit_mode != "off":
                self.video_control.set_editing_mode(True,True) #to refresh the button state
            self._update_gpx_overview()
            self.chart.set_gpx_data(self._gpx_data)
            self.chart.update()
            if getattr(self, "mini_chart_widget", None):
                self.mini_chart_widget.set_gpx_data(self._gpx_data)
                self.mini_chart_widget.update()
                
                
    def _highlight_index_everywhere(self, idx: int):
        # Map
        self.map_widget.show_blue(idx, do_center=True)
        # Chart
        self.chart.highlight_gpx_index(idx)
        # GpxList
        self.gpx_widget.gpx_list.select_row_in_pause(idx)
        # MiniChart
        if self.mini_chart_widget:
            self.mini_chart_widget.set_current_index(idx)    
                    
            
    def on_sync_clicked(self):
        """
        Sync-Button aus VideoControlWidget: 
        Wir nutzen die *final* Time (falls Cuts) und 
        zeigen in der GPX-Liste + Map (blau) den passenden Punkt.
        """
        # 1) Aktuelle Videoposition => global
        """
        local_time_s = self.video_editor.get_current_position_s()
        if local_time_s < 0:
            local_time_s = 0.0
        video_idx = self.video_editor.get_current_index()
        offset = sum(self.video_durations[:video_idx])
        global_s = offset + local_time_s
        """
        global_s = self.video_editor.get_current_position_s()
        print(f"[DEBUG] on_sync_clicked => get_current_position_s()={global_s:.3f}")

        # 2) => final_s, falls Cuts
        final_s = self.get_final_time_for_global(global_s)

        # 3) => best_idx in GPX
        best_idx = self.gpx_widget.get_closest_index_for_time(final_s)

        # 4) GPX-Liste => Pause => also "select_row_in_pause"
        self.gpx_widget.gpx_list.select_row_in_pause(best_idx)

        # 5) Map => blau => "show_blue"
        #self.map_widget.show_blue(best_idx)
        self.map_widget.show_blue(best_idx, do_center=True)


        # 6) Falls du dein Chart mitziehen möchtest:
        self.chart.highlight_gpx_index(best_idx)
                
        self._gpx_slots[self._active_gpx_slot]["sync_marker"] = best_idx
        self.chart.update() 
        print(f"[DEBUG] Slot {self._active_gpx_slot}: saved sync_marker idx={best_idx}")
        
        
    def on_map_sync_any(self, idx=None):
        """
        Is called by map_widget._on_sync_noarg_from_js,
        when the sync button in map_page.html is clicked.

        idx: der Punkt, wenn der Aufrufer ihn kennt (Rechtsklick auf [- / -]
        in der GPX-Leiste). Sonst wie bisher der blaue Punkt der Karte, der
        dann aber von einem frueheren Klick stammen kann.

        1) Index => map_widget._blue_idx or fallback => gpx_list.currentRow()
        2) final_s = gpx_data[idx]["rel_s"]
        3) global_s = get_global_time_for_final(final_s)
        4) => on_time_hms_set_clicked => Video
        """
        print("[DEBUG] on_map_sync_any() aufgerufen (Map-Sync)")

        # 1) Welcher Punkt in der Karte? (blau_idx)
        idx_map = idx if idx is not None else self.map_widget._blue_idx
        if idx_map is None or idx_map < 0:
            # fallback => nimm Zeile aus gpx_list
            idx_map = self.gpx_widget.gpx_list.table.currentRow()

        # Prüfung
        row_count = self.gpx_widget.gpx_list.table.rowCount()
        if not (0 <= idx_map < row_count):
            print("[DEBUG] on_map_sync_any => invalid index => Abbruch.")
            return

        # 2) final_s
        point = self._gpx_data[idx_map]
        final_s = (point.get("time", 0.0) - self._gpx_data[0].get("time", 0.0)).total_seconds() + get_gpx_video_shift()

        # 3) global_s => Falls Cuts => global_s = get_global_time_for_final(final_s)
        global_s = self.get_global_time_for_final(final_s)
        if(global_s < 0): #selected gpx point with negative time, going to 0
            global_s = 0.0

        # => h,m,s
        hh = int(global_s // 3600)
        mm = int((global_s % 3600) // 60)
        s_float = (global_s % 60)      # z.B. 13.456
        ss = int(s_float)             # 13
        ms = int(round((s_float - ss)*1000))  # 456
        
        # 4) => Video-Position
        print(f"[DEBUG] on_map_sync_any => idx={idx_map}, final_s={final_s:.2f}, global_s={global_s:.2f}")
        self.on_time_hms_set_clicked(hh, mm, ss, ms)
        self.chart.update()  
        
        
        if self.cut_manager.markB_time_s >= 0 and self._autoSyncVideoEnabled and self.real_total_duration - global_s < 1:
            reply = QMessageBox.question(
                self,
                "Last Frame?",
                "You are near the end of the video. Do you want to select the last frame?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                # User confirmed selecting the last frame
                self.end_manager.go_to_end()


    def check_and_handle_video_end(self):
        """
        Robuste Endcut-Erkennung die direkt mit den Cut-Intervallen arbeitet
        """
        if not self.video_editor.is_playing:
            return

        try:
            current_global_s = self.video_editor.get_current_global_time()
            total_duration = self.real_total_duration
            cut_intervals = getattr(self.cut_manager, "_cut_intervals", [])
            
            # Berechne die tatsächliche Endposition
            final_end_position = total_duration
            if cut_intervals:
                keep_intervals = self._compute_keep_intervals(cut_intervals, total_duration)
                if keep_intervals:
                    final_end_position = keep_intervals[-1][1]

            # Prüfe ob wir am Ende sind (mit verschiedenen Toleranzen)
            time_to_end = final_end_position - current_global_s
            
            # Debug-Ausgabe bei Bedarf aktivieren:
            # if time_to_end < 1.0:
            #     print(f"[ENDOFTIME] current={current_global_s:.3f}, final_end={final_end_position:.3f}, time_to_end={time_to_end:.3f}")

            # Wenn wir sehr nah am Ende sind (50ms Toleranz)
            if time_to_end <= 0.05:
                print(f"[ENDOFTIME] Ende erreicht: {current_global_s:.3f} von {final_end_position:.3f}")
                
                # Sofort Video stoppen
                self._handle_video_end_state()
                
                # Prüfe ob ein Endcut vorhanden ist
                has_endcut = abs(final_end_position - total_duration) > 0.1
                
                if has_endcut:
                    print(f"[ENDOFTIME] Endcut erkannt: {final_end_position:.3f} (Gesamt: {total_duration:.3f})")
                    
                    # Zeige Popup wenn aktiviert
                    if self.action_show_endcut_warning.isChecked():
                        self._show_endcut_popup(final_end_position)
                    
                    # Ein Sprung genuegt - siehe on_goto_video_end_clicked().
                    QTimer.singleShot(10, lambda: self.video_editor.seek_global(final_end_position))
                    
                else:
                    # Kein Endcut - einfach am Ende bleiben
                    QTimer.singleShot(10, lambda: self.video_editor.seek_global(final_end_position))

        except Exception as e:
            print(f"[ERROR] Fehler in check_and_handle_video_end: {e}")

    def _show_endcut_popup(self, end_position):
        """Zeigt das Endcut-Popup mit spezifischen Informationen"""
        try:
            total_duration = self.real_total_duration
            cut_duration = total_duration - end_position
            
            msg = QMessageBox(self)
            msg.setWindowTitle("Endcut Reached")
            msg.setIcon(QMessageBox.Information)
            msg.setText(
                f"Endcut detected!\n\n"
                f"Video continues for {cut_duration:.1f}s after GPX track ends.\n"
                f"Jumped to end of GPX track at {end_position:.1f}s."
            )
            
            # Timer um das Popup automatisch zu schließen
            QTimer.singleShot(3000, msg.accept)
            msg.exec()
            
        except Exception as e:
            print(f"[ERROR] Fehler beim Anzeigen des Endcut-Popups: {e}")

    def _compute_keep_intervals(self, cut_intervals, total_duration):
        """Berechnet die zu behaltenden Intervalle basierend auf Schnitten"""
        if not cut_intervals:
            return [(0.0, total_duration)]

        sorted_cuts = sorted(cut_intervals, key=lambda x: x[0])
        merged = []
        current_start, current_end = sorted_cuts[0]
        for i in range(1, len(sorted_cuts)):
            (st, en) = sorted_cuts[i]
            if st <= current_end:
                if en > current_end:
                    current_end = en
            else:
                merged.append((current_start, current_end))
                current_start, current_end = st, en
        merged.append((current_start, current_end))

        keep_list = []
        pos = 0.0
        for (cst, cen) in merged:
            if cst > pos:
                keep_list.append((pos, cst))
            pos = cen
        if pos < total_duration:
            keep_list.append((pos, total_duration))

        return keep_list

    
    
    def _handle_video_end_state(self, mark_as_end: bool = True):
        """Setzt alle Player-Zustände korrekt für Video-Ende.
        mark_as_end=False nutzen, wenn das Ende nur "angesteuert" wurde (z. B. Goto End),
        damit nach Step-Back/Play nicht an den Anfang gesprungen wird.
        """
        try:
            # Sofortiger Stop/Pause
            self.video_editor.set_paused(True)

            # UI aktualisieren
            self.video_control.update_play_pause_icon(False)
            self.gpx_widget.set_video_playing(False)
            self.map_widget.set_video_playing(False)

            # Gelben Marker entfernen
            lw = self.gpx_widget.gpx_list
            if hasattr(lw, '_last_video_row') and lw._last_video_row is not None:
                lw._mark_row_bg_except_markcol(lw._last_video_row, Qt.white)
                lw._last_video_row = None

            # Nur beim echten Abspiel-Ende auf "am Ende" setzen
            self._video_at_end = bool(mark_as_end)

        except Exception as e:
            print(f"[ERROR] Fehler in _handle_video_end_state: {e}")    
                
    
    def _show_endcut_popup(self, end_position: float):
        """
        Zeigt ein höheres Popup-Fenster mit mehr Informationen.
        """
        popup = QDialog(self.video_editor)
        popup.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        popup.setStyleSheet("""
            QDialog {
                background-color: rgba(0, 0, 0, 180);
                border: 3px solid orange;
                border-radius: 10px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        
        layout = QVBoxLayout(popup)
        
        # Mehrzeiliger Text mit verschiedenen Schriftgrößen
        label1 = QLabel("🎬 Endcut Reached")
        label1.setAlignment(Qt.AlignCenter)
        label1.setStyleSheet("color: white; font-size: 16px; padding: 5px;")
        
        label2 = QLabel(f"New last frame: {end_position:.1f}s")
        label2.setAlignment(Qt.AlignCenter)
        label2.setStyleSheet("color: white; font-size: 14px; padding: 5px;")
        
        label3 = QLabel("(Auto-jumped to actual end)")
        label3.setAlignment(Qt.AlignCenter)
        label3.setStyleSheet("color: lightgray; font-size: 12px; padding: 5px;")
        
        label4 = QLabel("Don´t work with VideoSpeed greater than 2x")
        label4.setAlignment(Qt.AlignCenter)
        label4.setStyleSheet("color: white; font-size: 14px; padding: 8px;")
        
        
        layout.addWidget(label1)
        layout.addWidget(label2)
        layout.addWidget(label3)
        layout.addWidget(label4)
        
        
        # HÖHERES FENSTER
        popup.resize(300, 140)  # Breite: 300px, Höhe: 140px
        
        video_rect = self.video_editor.rect()
        popup_x = video_rect.center().x() - popup.width() // 2
        popup_y = video_rect.center().y() - popup.height() // 2
        
        popup.move(self.video_editor.mapToGlobal(QPoint(popup_x, popup_y)))
        popup.show()
        
        QTimer.singleShot(2500, popup.close)
        
        return popup
    
    def _fade_popout_out_step(self, popup, timer):
        """Ein Schritt der Fade-Out Animation"""
        current_opacity = popup.windowOpacity()
        if current_opacity > 0.1:
            popup.setWindowOpacity(current_opacity - 0.1)
        else:
            timer.stop()
            popup.close()
    
    def _save_gpx_to_file(self, gpx_points, out_file: str):
        """
        Schreibt gpx_points als valides GPX 1.1 in die Datei `out_file`.
        gpx_points: list of dicts with lat, lon, ele, time, rel_s, ...
    
        Zeitformat => "YYYY-MM-DDTHH:MM:SS.xxxZ"
        Beispiel: "2024-07-20T06:50:42.000Z"
        """
       

        if not gpx_points:
            return

        start_time = gpx_points[0].get("time", None)
        end_time   = gpx_points[-1].get("time", None)
        if not start_time:
            start_time = datetime.datetime.now()
        if not end_time:
            end_time = start_time

        # Bsp: 2024-07-20T06:50:42.000Z
        def _format_dt(dt):
            # dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ") => hat 6 Mikrosekunden
            # Wir kürzen auf 3 Stellen => .%f => .xxx
            s = dt.strftime("%Y-%m-%dT%H:%M:%S.%f")  # z.B. 2024-07-20T06:50:42.123456
            # => wir wollen nur die ersten 3 Nachkommastellen
            return s[:-3] + "Z"  # => 2024-07-20T06:50:42.123Z

        start_str = _format_dt(start_time)
        end_str   = _format_dt(end_time)

        track_name = "Exported GPX"
        track_desc = "Cut to final video length"

        with open(out_file, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write(f'<gpx version="1.1" creator="KVRouite v{APP_VERSION}" ')
            f.write('xmlns="http://www.topografix.com/GPX/1/1" ')
            f.write('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ')
            f.write('xsi:schemaLocation="http://www.topografix.com/GPX/1/1 ')
            f.write('http://www.topografix.com/GPX/1/1/gpx.xsd">\n')

            # Metadata
            f.write('  <metadata>\n')
            f.write(f'    <time>{start_str}</time>\n')
            f.write('  </metadata>\n')

            f.write('  <trk>\n')
            f.write(f'    <name>{track_name}</name>\n')
            f.write(f'    <desc>{track_desc}</desc>\n')
            f.write('    <trkseg>\n')
            for pt in gpx_points:
                lat = pt.get("lat", 0.0)
                lon = pt.get("lon", 0.0)
                ele = pt.get("ele", 0.0)
                dt = pt.get("time", None)
                if dt is None:
                    dt = datetime.datetime.now()
                time_str = _format_dt(dt)
    
                f.write(f'      <trkpt lat="{lat:.8f}" lon="{lon:.8f}">\n')
                f.write(f'        <ele>{ele:.2f}</ele>\n')
                f.write(f'        <time>{time_str}</time>\n')
                f.write('      </trkpt>\n')
            f.write('    </trkseg>\n')
            f.write('  </trk>\n')
            f.write('</gpx>\n')
    
        print(f"[DEBUG] _save_gpx_to_file => wrote {len(gpx_points)} points to {out_file}")
        
        
    def _remove_interval_with_tol(self, cuts, interval, tol=0.05):
        """
        Entfernt ein Intervall (start, end) aus 'cuts' mit Toleranz.
        Gibt True zurück, wenn etwas entfernt wurde.
        """
        if not interval or not cuts:
            return False
        s, e = interval
        for i, (cs, ce) in enumerate(list(cuts)):  # Kopie, falls während Iteration geändert wird
            if abs(cs - s) <= tol and abs(ce - e) <= tol:
                cuts.pop(i)
                return True
        return False


    ###############################################################################        
    
    def on_chPercent_clicked(self):
        """
        Called when the user clicks the 'ch%' button.
        - If no valid range is selected (or only 1 point in that range),
        it changes the slope for a single point (row) relative to row-1.
        - If a valid range [markB..markE] with >=2 points is selected,
        it applies one consistent slope across that entire range,
        and shifts subsequent points accordingly.
        All user-facing texts are in English.
        """
       
        gpx_data = self.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return
    
        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return

        # --- Check if we have a valid markB..markE range ---
        b_idx = self.gpx_widget.gpx_list._markB_idx
        e_idx = self.gpx_widget.gpx_list._markE_idx
    
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
            row = self.gpx_widget.gpx_list.table.currentRow()
            if row < 1:
                QMessageBox.warning(self, "Invalid Selection",
                    "Please select a point with row >= 1.\n"
                    "Cannot compute slope for the very first point (row=0).")
                return
            if row >= n:
                return
    
            # => Undo
            old_data = copy.deepcopy(gpx_data)
            self.gpx_widget.gpx_list._history_stack.append(old_data)
    
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
            self.gpx_widget.set_gpx_data(gpx_data)
            self._gpx_data = gpx_data
            self._update_gpx_overview()
    
            self.chart.set_gpx_data(gpx_data)
            if self.mini_chart_widget:
                self.mini_chart_widget.set_gpx_data(gpx_data)
    
            # Map
            #route_geojson = self._build_route_geojson_from_gpx(gpx_data)
            #self.map_widget.loadRoute(route_geojson, do_fit=False)

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
            old_data = copy.deepcopy(gpx_data)
            self.gpx_widget.gpx_list._history_stack.append(old_data)
    
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
            self.gpx_widget.set_gpx_data(gpx_data)
            self._gpx_data = gpx_data
            self._update_gpx_overview()
    
            self.chart.set_gpx_data(gpx_data)
            if self.mini_chart_widget:
                self.mini_chart_widget.set_gpx_data(gpx_data)
    
            #route_geojson = self._build_route_geojson_from_gpx(gpx_data)
            #self.map_widget.loadRoute(route_geojson, do_fit=False)

            QMessageBox.information(
                self, "Done",
                f"Average slope in {b_idx}..{e_idx} changed from {old_slope:.2f}% to {new_slope:.2f}%.\n"
                f"Subsequent points have been shifted by {shift_dz:+.2f} m in elevation."
            )
    
    
        
    
    def add_or_update_point_on_map(self, stable_id: str, lat: float, lon: float, 
                                color: str="#000000", size: int=4):
        """
        Ruft in map_page.html => addOrUpdatePoint(...) auf.
        """
        js_code = (f"addOrUpdatePoint('{stable_id}', {lat}, {lon}, "
                f"'{color}', {size});")
        self.map_widget.view.page().runJavaScript(js_code)

    def remove_point_on_map(self, stable_id: str):
        """
        Ruft in map_page.html => removePoint(...) auf.
        """
        

        js_code = f"removePoint('{stable_id}');"
        self.map_widget.view.page().runJavaScript(js_code)

    
    def _on_new_project_triggered(self):
        """
        Vollständiger Reset für 'New Project'.
        Setzt Video, GPX, Timeline, Overlays, Marker, Slots, Sync/Prompts,
        Edit-Mode, Zeitmodus (global) und UI-Zustände zurück.
        """
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "New Project",
            "Are you sure you want to start a new project?\nAll unsaved changes will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # Der Titel traegt den Namen des Projekts - ohne Projekt gehoert er weg.
        self._projekt_datei = None
        self._titel_setzen()

        # --- 1) Video hart stoppen & leeren ---
        try:
            self.video_editor.stop_and_clear()
        except Exception as e:
            print(f"[WARN] NewProject: player cleanup: {e}")

        # Zeitmodus/Callback zurück auf "global"/None
        try:
            self._time_mode = "global"
            self.video_editor.set_time_mode("global")      # VideoEditorWidget API
            self.video_editor.set_final_time_callback(None)
        except Exception:
            pass

        # --- 2) Interne Video-State-Container leeren ---
        try:
            self.playlist.clear()
        except Exception:
            pass
        try:
            self.video_durations.clear()
        except Exception:
            pass
        # Sprechstellen und Tonspur (Zeitleiste, Audio Zoom) leeren.
        try:
            self._sprechstellen = {}
            self._sprechstellen_anzeigen()
        except Exception as e:
            print(f"[WARN] NewProject: voices cleanup: {e}")

        self.global_keyframes = []
        self.video_editor.playlist = []
        self.video_editor.multi_durations = []
        self.video_editor.boundaries = []
        self.video_editor.is_playing = False
        self.video_editor._current_index = 0
        self.video_editor.set_total_length(0.0)
        self.video_editor.set_cut_time(0.0)
        self.video_editor.current_time_label.setText("")

        # --- 3) Timeline & Cuts vollständig zurücksetzen ---
        try:
            self.cut_manager._cut_intervals.clear()
            self.cut_manager.prune_hard_cuts()
            self.cut_manager.set_merge_fades([])
            self.timeline.set_merge_fades({})
            self.cut_manager.markB_time_s = -1.0
            self.cut_manager.markE_time_s = -1.0

            self.timeline.clear_all_cuts()
            self.timeline.clear_overlay_intervals()
            self.timeline.set_total_duration(0.0)
            self._thumbs.verwerfen()
            self.timeline.set_vorschaubilder([])
            self.timeline.set_boundaries([])
        except Exception as e:
            print(f"[WARN] NewProject: timeline/cuts reset: {e}")

        # --- 4) Overlays sauber löschen (über Manager-API) ---
        try:
            self._overlay_manager.clear_overlays()  # bevorzugt API verwenden
        except Exception:
            try:
                self._overlay_manager._overlays.clear()
                self.timeline.clear_overlay_intervals()
            except Exception:
                pass

        # --- 5) GPX-Daten, Marker, UI, Sync-Shift ---
        try:
            # GPX Array + Widgets
            self._gpx_data.clear()
            self.gpx_widget.set_gpx_data([])
            self.chart.set_gpx_data([])
            if getattr(self, "mini_chart_widget", None):
                self.mini_chart_widget.set_gpx_data([])

            # Tabellen-Selektion & Marker im List-Widget löschen
            try:
                gl = self.gpx_widget.gpx_list
                if hasattr(gl, "_markB_idx"): gl._markB_idx = None
                if hasattr(gl, "_markE_idx"): gl._markE_idx = None
                if hasattr(gl, "table"):
                    try:
                        gl.table.clearSelection()
                    except Exception:
                        pass
            except Exception as e:
                print(f"[WARN] NewProject: clear GPX markers: {e}")

            # Map leeren
            try:
                self.map_widget.loadRoute(
                    {"type": "FeatureCollection", "features": []}, do_fit=True
                )
                # Optional: Directions/Profile-Buttons verstecken
                try:
                    self.map_widget.view.page().runJavaScript("setDirectionsEnabled(false);")
                except Exception:
                    pass
            except Exception:
                pass

            # absolut alle Sync-Zustände deaktivieren
            from core.gpx_parser import set_gpx_video_shift
            set_gpx_video_shift(None)
            self.enableVideoGpxSync(False)
            self._sync_prompt_answer = None
            self._last_gpx_load_mode = None
        except Exception as e:
            print(f"[WARN] NewProject: gpx reset: {e}")

        # --- 6) GPX-Slots DEFINITIV auf Werkseinstellung ---
        try:
            for s in (1, 2):
                self._gpx_slots[s]["gpx_data"] = []
                self._gpx_slots[s]["gpx_video_shift"] = None
                self._gpx_slots[s]["markB"] = None
                self._gpx_slots[s]["markE"] = None
                self._gpx_slots[s]["bookmarks"] = []
                # Werkseinstellung: Slot1 False, Slot2 True
                self._gpx_slots[s]["sync_enabled"] = (s == 2)
            self._active_gpx_slot = 1
            self._apply_slot_to_ui()
        except Exception as e:
            print(f"[WARN] NewProject: slots reset: {e}")

        # --- 7) Edit-Mode & UI-Toggles neutralisieren ---
        try:
            if getattr(self, "_edit_mode", None) != "off":
                self._set_edit_mode("off")
            self.video_control.activate_controls(False)
            if hasattr(self, "action_auto_sync_video"):
                self.action_auto_sync_video.setChecked(False)
                try:
                    self._on_auto_sync_video_toggled(False)
                except Exception:
                    pass

            if hasattr(self, "action_new_pts_video_time"):
                self.action_new_pts_video_time.setChecked(False)
                try:
                    self._on_sync_point_video_time_toggled(False)
                except Exception:
                    pass
            
            self.update_timeline_marker()
        except Exception as e:
            print(f"[WARN] NewProject: edit/toggles: {e}")

        # --- 8) Undo-Stack & interne Flags ---
        try:
            self._undo_stack.clear()
        except Exception:
            pass
        self.gpx_control._glaettung = None
        self.first_video_frame_shown = False
        self.real_total_duration = 0.0
        self.playlist_counter = 0

        # --- 9) Menüs & Views aktualisieren ---
        try:
            self.playlist_menu.clear()
        except Exception:
            pass
        try:
            self.timeline.update()
            self.video_editor.update()
        except Exception:
            pass

    
        
    def _go_to_gpx_index(self, idx: int):
        """
        Highlights the GPX index 'idx' in the map, the gpx list, the chart, 
        and optionally the mini-chart or the video timeline.
        """
        # 1) Table (GPXList) -> Pause-Selection
        self.gpx_widget.gpx_list.select_row_in_pause(idx)
    
        # 2) Map -> show blue + center
        self.map_widget.show_blue(idx, do_center=True)

        # 3) Chart
        self.chart.highlight_gpx_index(idx)
    
        # 4) MiniChart
        if self.mini_chart_widget:
            self.mini_chart_widget.set_current_index(idx)

        # 5) (Optional) => Video 
        #    Falls du direkt zum passenden Zeitpunkt springen willst:
        # global_s = gpx_data[idx]["rel_s"]   # oder wie auch immer du es nennst
        # => self.on_time_hms_set_clicked(....) 
        # or do nothing if you prefer just highlighting
        
        
    def _haversine_m(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        from math import radians, sin, cos, sqrt, atan2
        R = 6371000.0  # Erdradius in m
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2.0)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2.0)**2
        c = 2.0 * atan2(sqrt(a), sqrt(1.0 - a))
        return R * c

    # ⬇️⬇️⬇️ NEU: Rechtsklick-Logik – im anderen Slot nächsten Punkt finden und springen
    def jump_to_nearest_point_in_other_slot(self, max_distance_m: float = 40.0):
        """
        Wird vom GPXControlWidget bei Rechtsklick auf den Slot-Button aufgerufen.
        - Nimmt den selektierten Punkt (Lat/Lon) im AKTIVEN Slot,
        - sucht im ANDEREN Slot den nächstgelegenen Punkt,
        - wenn <= max_distance_m: Slot wechseln + dort selektieren & zoomen,
        - sonst Hinweis und NICHT umschalten.
        """
        # 0) Beide Slots müssen Daten haben
        if not self._gpx_slots[1]["gpx_data"] or not self._gpx_slots[2]["gpx_data"]:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No data in both slots",
                                    "This action requires GPX data in Slot 1 and Slot 2.")
            return

        src_slot = self._active_gpx_slot
        dst_slot = 2 if src_slot == 1 else 1
        src_data = self._gpx_slots[src_slot]["gpx_data"]
        dst_data = self._gpx_slots[dst_slot]["gpx_data"]

        # 1) Welcher Punkt ist im aktiven Slot selektiert?
        row = self.gpx_widget.gpx_list.table.currentRow()
        if row < 0 or row >= len(src_data):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No selection",
                                    f"Please select a GPX point in Slot {src_slot} first.")
            return

        try:
            src_lat = float(src_data[row]["lat"])
            src_lon = float(src_data[row]["lon"])
        except Exception:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid point", "Selected GPX point has no valid lat/lon.")
            return

        # 2) Suche im Ziel-Slot den nächstgelegenen Punkt
        best_idx = -1
        best_dist = float("inf")
        for i, pt in enumerate(dst_data):
            try:
                d = self._haversine_m(src_lat, src_lon, float(pt["lat"]), float(pt["lon"]))
            except Exception:
                continue
            if d < best_dist:
                best_dist = d
                best_idx = i

        # 3) Schwellwert prüfen
        if best_idx < 0 or best_dist > max_distance_m:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Out of range",
                (f"No nearby point found in Slot {dst_slot}.\n\n"
                 f"Nearest distance: {best_dist:.1f} m (limit: {max_distance_m:.0f} m)\n"
                 "I won't switch the slot.")
            )
            return

        # 4) Slot wechseln und Zielpunkt anzeigen
        self.switch_gpx_slot(dst_slot)  # stellt UI/Daten/Sync des Slots her
        self._go_to_gpx_index(best_idx) # selektiert/zoomt (Liste, Map, Chart)    
        from PySide6.QtCore import QTimer
        def _refocus():
            # Punkt erneut als "selected" setzen (blau) UND dann hart ranzoomen
            self.map_widget.set_selected_point(best_idx)
            self.map_widget.zoom_to_index(best_idx, 18)
            #self.on_map_sync_any()

        QTimer.singleShot(200, _refocus)
        
    def _gpx_zeile_fuer_marke(self, name):
        """Welche Zeile bekommt markB/markE aus der GPX-Leiste? Oder None.

        Bis 6.12 war es stur die gewaehlte Tabellenzeile. Laeuft das Video,
        wandert aber nur der gelbe Balken (highlight_video_time), die Auswahl
        bleibt stehen, wo zuletzt geklickt wurde - und markB landete auf
        einer Zeile, die mit dem Bild nichts zu tun hat, oder nirgends, weil
        gar nichts gewaehlt war. Jetzt: steht der gelbe Balken woanders als
        die Auswahl, fragt die App, ob der Punkt unter dem Video gemeint ist.
        Ja: die Zeile wird wie ein Klick gewaehlt (blau auf der Karte,
        Tabelle und Chart ziehen nach) und bekommt die Marke. Nein: nichts
        passiert - die alte Auswahl wird NICHT still markiert. Nur mit
        AutoCutVideo+GPX aus; mit an setzt das Video die Marken selbst.
        """
        lw = self.gpx_widget.gpx_list
        gewaehlt = lw.table.currentRow()
        gelb = lw._last_video_row
        if (not self._autoSyncVideoEnabled and gelb is not None
                and 0 <= gelb < lw.table.rowCount() and gelb != gewaehlt):
            item = lw.table.item(gelb, 0)
            zeit = item.text() if item is not None else "?"
            antwort = QMessageBox.question(
                self, "Set %s" % name,
                "The video is at row %d (%s), but that row is not selected.\n\n"
                "Set %s on row %d?\n\n'No' leaves the marks as they are."
                % (gelb + 1, zeit, name, gelb + 1),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if antwort != QMessageBox.Yes:
                return None
            # Wie ein Klick auf die Zeile: blau auf der Karte, Zeile gewaehlt,
            # Chart nachgezogen. Beim laufenden, synchronisierten Video
            # laesst select_row_in_pause die Auswahl in Ruhe - dann bleibt
            # nur die rote Marke, die ohnehin gesetzt wird.
            self.on_user_selected_index(gelb)
            return gelb
        if gewaehlt < 0:
            self.statusBar().showMessage(
                "%s: select a GPX row or a point on the map first." % name, 4000)
            return None
        return gewaehlt

    def on_markB_clicked_gpx(self):

        """
        Wird aufgerufen, wenn im GPXControlWidget der Button 'MarkB' geklickt wird.
        => current_row ohne +1
        """
        current_row = self._gpx_zeile_fuer_marke("markB")
        if current_row is None:
            return

        # Ohne +1
        self.gpx_widget.gpx_list.set_markB_row(current_row)
        self.map_widget.set_markB_point(current_row)
    
   
    def on_deselect_clicked(self):
        
        """
        Wird aufgerufen, wenn der Deselect-Button gedrückt wird 
        (VideoControlWidget oder GPXControlWidget).
        => Wir entfernen alle roten Markierungen in der GPX-Liste.
        """
        self.gpx_widget.gpx_list.clear_marked_range()
        self.map_widget.clear_marked_range()        
        
    def check_gpx_errors(self, gpx_data):
        """
        Checks for:
        1) Time errors (points with time[i] == time[i-1])
        2) Way errors (points with lat/lon identical to next point)
        If any errors are found, shows an English warning message:
        - Only time errors
        - Only way errors
        - Both time & way errors
        Otherwise, no message.
        """
       

        if not gpx_data or len(gpx_data) < 2:
            return  # zu wenige Punkte -> auch keine Warnung

        # 1) Time Errors zählen
        time_err_count = 0
        for i in range(1, len(gpx_data)):
            if gpx_data[i]["time"] == gpx_data[i-1]["time"]:
                time_err_count += 1

        # 2) Way Errors zählen
        way_err_count = 0
        for i in range(len(gpx_data) - 1):
            lat1 = gpx_data[i]["lat"]
            lon1 = gpx_data[i]["lon"]
            lat2 = gpx_data[i+1]["lat"]
            lon2 = gpx_data[i+1]["lon"]
            # Vergleiche Koordinaten - fast identisch?
            if abs(lat1 - lat2) < 1e-12 and abs(lon1 - lon2) < 1e-12:
                way_err_count += 1
    
        # Nichts gefunden => keine Meldung
        if time_err_count == 0 and way_err_count == 0:
            return
    
        # Mindestens eines vorhanden => Warnmeldung bauen:
        if time_err_count > 0 and way_err_count > 0:
            msg = (
                f"Warning:\n"
                f"We found {time_err_count} time errors (0s step) and {way_err_count} way errors (duplicate coordinates).\n"
                "Please fix them via the more-menu \"...\" -> Time Errors / Way Errors!"
            )
        elif time_err_count > 0:
            msg = (
                f"Warning:\n"
                f"We found {time_err_count} time errors (0s step).\n"
                "Please fix them via the more-menu \"...\" -> Time Errors!"
            )
        else:  # way_err_count > 0
            msg = (
                f"Warning:\n"
                f"We found {way_err_count} way errors (duplicate coordinates).\n"
                "Please fix them via the more-menu \"...\" -> (Way Errors)!"
            )
    
        QMessageBox.warning(self, "GPX Errors Detected", msg)
        

    def ordered_insert_new_point(self,lat: float, lon: float, video_time: float) -> int:
        print(f"[DEBUG] ordered_insert_new_point => video_time={video_time}")
        gpx_data = self._gpx_data
        if gpx_data is None or len(gpx_data) == 0:
            video_ts = datetime.now()
            set_gpx_video_shift(video_time)  # Set initial shift
        else:
            video_ts = gpx_data[0].get("time",0.0) + timedelta(seconds = video_time - get_gpx_video_shift()) 

        idx = -1
        for i in range(0, len(gpx_data)):
            if (gpx_data[i].get("time") > video_ts):
                break
            else:
                idx = i

        ele = 0
        if idx >= 0:
            base_pt = gpx_data[idx]
            ele = base_pt.get("ele", 0.0)

        new_pt = {
            "lat": lat,
            "lon": lon,
            "ele": ele,
            "time": video_ts,
            "delta_m": 0.0,
            "speed_kmh": 0.0,
            "gradient": 0.0
        }

        insert_pos = idx + 1
        if insert_pos > len(gpx_data):
            insert_pos = len(gpx_data)
        elif insert_pos == 0: #inserted in the begin, so shift between video and gpx gets smaller
            set_gpx_video_shift(video_time)

        gpx_data.insert(insert_pos, new_pt)
        
        return insert_pos  # Index des neuen Punktes in gpx_data
        
    def on_global_undo(self):
        if self._undo_stack:
            self._undo_schritte(1)
        else:
            QMessageBox.warning(self,"Undo ignored","Undo stack is empty.")

    def _undo_ablegen(self, fn, name):
        """Einen Undo-Schritt auf den Stapel legen - mit Namen und Uhrzeit,
        damit Edit > Undo history ihn zeigen kann. Jede Stelle, die etwas auf
        den Stapel legt, geht hier durch."""
        fn.undo_name = name
        # 'datetime' ist hier die Klasse (from datetime import datetime, Zeile 120).
        fn.undo_zeit = datetime.now()
        self._undo_stack.append(fn)

    def _undo_schritte(self, anzahl):
        """'anzahl' Schritte vom Stapel nehmen und ausfuehren, neuester zuerst."""
        for _ in range(anzahl):
            if not self._undo_stack:
                break
            undo_fn = self._undo_stack.pop()
            undo_fn()  # Die gespeicherte Undo-Funktion ausführen
        self._update_gpx_overview()
        # Strg+Z ist eine eigene Aktion: der Zustand danach ist einer, den
        # wir selbst hergestellt haben. Ohne das Nachziehen waeren
        # anschliessend alle Schnitte gesperrt, weil der Fingerabdruck noch
        # vom Zustand davor stammt.
        self.cut_manager.fingerabdruck_merken(self._gpx_data)

    def _show_undo_history(self):
        """Edit > Undo history: die Schritte, die Strg+Z zuruecknimmt, mit Namen.

        Der Stapel kennt nur Zustaende, keine Aktionen - ein Schritt aus der
        Mitte laesst sich deshalb nicht einzeln herausnehmen. Was geht: bis zu
        einem Schritt zurueck, also ihn und alles Neuere. Genau das bietet die
        Liste, und sie zeigt vorher, wie weit das reicht.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Undo history")
        dlg.setMinimumSize(440, 380)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            "Newest first. Ctrl+Z undoes the top entry.\n"
            "Select an entry and press 'Undo to here': that step and every "
            "step above it are undone."))

        liste = QListWidget()
        for fn in reversed(self._undo_stack):
            zeit = getattr(fn, "undo_zeit", None)
            name = getattr(fn, "undo_name", "Edit")
            wann = zeit.strftime("%H:%M:%S") if zeit else "--:--:--"
            liste.addItem(f"{wann}   {name}")
        if not self._undo_stack:
            liste.addItem("(nothing to undo)")
            liste.setEnabled(False)
        v.addWidget(liste)

        knoepfe = QDialogButtonBox()
        bis_hier = knoepfe.addButton("Undo to here", QDialogButtonBox.AcceptRole)
        knoepfe.addButton(QDialogButtonBox.Close)
        bis_hier.setEnabled(False)
        liste.currentRowChanged.connect(
            lambda zeile: bis_hier.setEnabled(bool(self._undo_stack) and zeile >= 0))

        def zurueck():
            zeile = liste.currentRow()
            if zeile < 0 or not self._undo_stack:
                return
            schritte = zeile + 1
            if schritte > 1:
                antwort = QMessageBox.question(
                    dlg, "Undo to here",
                    f"This also undoes the {schritte - 1} later step(s) "
                    f"above it.\nContinue?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if antwort != QMessageBox.Yes:
                    return
            self._undo_schritte(schritte)
            dlg.accept()

        knoepfe.accepted.connect(zurueck)
        knoepfe.rejected.connect(dlg.reject)
        v.addWidget(knoepfe)
        dlg.exec()

    # ------------------------------------------------------------------
    # Lesezeichen ("Bookmarks") auf GPX-Punkte - je Slot, ueber Koordinaten.
    # Suche und Vorgaben: core/lesezeichen.py. Hier nur Menue, Dialog, Sprung.
    # ------------------------------------------------------------------
    def _lesezeichen_liste(self):
        """Die Lesezeichen des aktiven Slots (die Liste selbst, nicht Kopie)."""
        store = self._get_active_slot_store()
        if not isinstance(store.get("bookmarks"), list):
            store["bookmarks"] = []
        return store["bookmarks"]

    def _lesezeichen_anlegen(self, zeile: int):
        """Lesezeichen auf die Tabellenzeile `zeile` setzen, Name erfragen."""
        from core import lesezeichen as lz
        daten = self.gpx_widget.gpx_list._gpx_data or []
        if not (0 <= zeile < len(daten)):
            self.statusBar().showMessage("Bookmark: select a GPX row first.", 4000)
            return
        try:
            lat = float(daten[zeile]["lat"])
            lon = float(daten[zeile]["lon"])
        except (KeyError, TypeError, ValueError):
            QMessageBox.warning(self, "Add bookmark",
                                "This GPX point has no valid lat/lon.")
            return
        name, ok = QInputDialog.getText(
            self, "Add bookmark",
            "Name for this point (row %d, %.6f / %.6f):" % (zeile + 1, lat, lon),
            QLineEdit.Normal, lz.vorgabe_name(zeile))
        if not ok:
            return
        name = name.strip() or lz.vorgabe_name(zeile)
        liste = self._lesezeichen_liste()
        liste.append(lz.eintrag(name, lat, lon))
        self.statusBar().showMessage(
            "Bookmark %d '%s' set on row %d (Slot %d)."
            % (len(liste), name, zeile + 1, self._active_gpx_slot), 4000)

    def _lesezeichen_fuer_auswahl(self):
        """Menue Bookmarks > Add / Ctrl+B: die gewaehlte Tabellenzeile."""
        self._lesezeichen_anlegen(self.gpx_widget.gpx_list.table.currentRow())

    def _lesezeichen_anspringen(self, eintrag):
        """Zum Punkt des Lesezeichens - wie ein Klick auf seine Zeile.

        Der Sprung geht ueber die Tabellenauswahl, damit genau dieselbe Kette
        laeuft wie beim Klick: Zeile gelb, Karte, Chart, bei Bedarf Video.
        Vorher die Auswahl leeren, sonst kommt bei derselben Zeile kein
        Signal. Ist der Punkt weggeschnitten, landet der Sprung auf dem
        Nachbarn innerhalb der Toleranz und die Statuszeile sagt den Abstand.
        """
        from PySide6.QtWidgets import QAbstractItemView
        from core import lesezeichen as lz
        daten = self.gpx_widget.gpx_list._gpx_data or []
        treffer = lz.finde_index(daten, eintrag["lat"], eintrag["lon"])
        if treffer is None:
            self.statusBar().showMessage(
                "Bookmark '%s': point not found in this track (deleted?)."
                % eintrag.get("name", ""), 6000)
            return
        idx, abstand = treffer
        tabelle = self.gpx_widget.gpx_list.table
        tabelle.clearSelection()
        tabelle.selectRow(idx)
        item = tabelle.item(idx, 0)
        if item is not None:
            tabelle.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        zeit = item.text() if item is not None else "?"
        if abstand > 0.0:
            self.statusBar().showMessage(
                "Bookmark '%s': exact point is gone, nearest is row %d (%s), %.1f m away."
                % (eintrag.get("name", ""), idx + 1, zeit, abstand), 6000)
        else:
            self.statusBar().showMessage(
                "Bookmark '%s': row %d (%s)." % (eintrag.get("name", ""), idx + 1, zeit), 4000)

    def _lesezeichen_sortiert(self):
        """[(eintrag, heutiger index oder None), ...] in Spurreihenfolge.

        Menue, Dialog und Ctrl+1..9 nehmen alle diese Reihenfolge, damit die
        Nummer im Menue und die Taste dasselbe Lesezeichen meinen.
        """
        from core import lesezeichen as lz
        daten = self.gpx_widget.gpx_list._gpx_data or []
        return lz.sortiert(daten, self._lesezeichen_liste())

    def _lesezeichen_nummer_anspringen(self, nummer: int):
        """Ctrl+1..9 - Nummer in Spurreihenfolge, siehe _lesezeichen_sortiert."""
        sortiert = self._lesezeichen_sortiert()
        if 1 <= nummer <= len(sortiert):
            self._lesezeichen_anspringen(sortiert[nummer - 1][0])
        else:
            self.statusBar().showMessage(
                "No bookmark %d in Slot %d." % (nummer, self._active_gpx_slot), 3000)

    def _lesezeichen_menue_fuellen(self, menue, zeile=None):
        """Menue aufbauen: Anlegen, Verwalten, dann ein Eintrag je Lesezeichen.

        `zeile` kommt vom Rechtsklick in die Tabelle: dann bietet der erste
        Eintrag genau diese Zeile an. Im Hauptmenue gilt die gewaehlte Zeile.
        Die Nummern 1..9 stehen als Ctrl+n rechts im Eintrag; das ist reiner
        Text, die Tasten bedienen die QShortcuts des Fensters.
        """
        menue.clear()
        if zeile is not None and zeile >= 0:
            a = menue.addAction("Add bookmark for row %d..." % (zeile + 1))
            a.triggered.connect(lambda _=False, z=zeile: self._lesezeichen_anlegen(z))
        else:
            menue.addAction(self.action_add_bookmark)
        menue.addAction(self.action_manage_bookmarks)
        sortiert = self._lesezeichen_sortiert()
        if not sortiert:
            return
        menue.addSeparator()
        for n, (eintrag, idx) in enumerate(sortiert, start=1):
            wo = ("row %d" % (idx + 1)) if idx is not None else "not in track"
            text = "%d  %s  (%s)" % (n, eintrag.get("name", ""), wo)
            if n <= 9:
                text += "\tCtrl+%d" % n
            a = menue.addAction(text)
            a.triggered.connect(lambda _=False, e=eintrag: self._lesezeichen_anspringen(e))

    def _lesezeichen_kontextmenue(self, zeile: int, pos):
        """Rechtsklick in die GPX-Tabelle."""
        menue = QMenu(self)
        self._lesezeichen_menue_fuellen(menue, zeile)
        menue.exec(pos)

    def _lesezeichen_dialog(self):
        """Bookmarks...: Liste mit Go to, Rename, Delete - nach dem Muster
        von Edit > Undo history."""
        liste = self._lesezeichen_liste()
        dlg = QDialog(self)
        dlg.setWindowTitle("Bookmarks - Slot %d" % self._active_gpx_slot)
        dlg.setMinimumSize(460, 360)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            "Bookmarks remember a GPX point by its coordinates, so they\n"
            "survive cuts and time edits. Listed in track order; Ctrl+1..9\n"
            "jump to the first nine in this order."))

        ansicht = QListWidget()
        # Die Zeilen der Ansicht in Spurreihenfolge; jede zeigt auf den
        # Eintrag in `liste`, damit Rename und Delete den richtigen treffen.
        sortiert = []

        def neu_zeichnen():
            sortiert[:] = self._lesezeichen_sortiert()
            ansicht.clear()
            for n, (e, idx) in enumerate(sortiert, start=1):
                wo = ("row %d" % (idx + 1)) if idx is not None else "not in track"
                ansicht.addItem("%d   %s   %s   (%.6f / %.6f)"
                                % (n, e.get("name", ""), wo, e["lat"], e["lon"]))
            if not liste:
                ansicht.addItem("(no bookmarks in this slot)")
            ansicht.setEnabled(bool(liste))

        neu_zeichnen()
        v.addWidget(ansicht)

        knoepfe = QDialogButtonBox()
        gehe = knoepfe.addButton("Go to", QDialogButtonBox.ActionRole)
        umbenennen = knoepfe.addButton("Rename", QDialogButtonBox.ActionRole)
        loeschen = knoepfe.addButton("Delete", QDialogButtonBox.ActionRole)
        knoepfe.addButton(QDialogButtonBox.Close)

        def gewaehlt():
            """Der gewaehlte Eintrag (das Objekt aus `liste`) oder None."""
            z = ansicht.currentRow()
            return sortiert[z][0] if (liste and 0 <= z < len(sortiert)) else None

        def knoepfe_anpassen():
            da = gewaehlt() is not None
            for k in (gehe, umbenennen, loeschen):
                k.setEnabled(da)

        ansicht.currentRowChanged.connect(lambda _z: knoepfe_anpassen())
        knoepfe_anpassen()

        def gehe_zu():
            e = gewaehlt()
            if e is not None:
                self._lesezeichen_anspringen(e)

        def umbenennen_jetzt():
            e = gewaehlt()
            if e is None:
                return
            z = ansicht.currentRow()
            name, ok = QInputDialog.getText(dlg, "Rename bookmark", "Name:",
                                            QLineEdit.Normal, e.get("name", ""))
            if ok and name.strip():
                e["name"] = name.strip()
                neu_zeichnen()
                ansicht.setCurrentRow(z)

        def loeschen_jetzt():
            e = gewaehlt()
            if e is None:
                return
            z = ansicht.currentRow()
            liste[:] = [x for x in liste if x is not e]
            neu_zeichnen()
            if liste:
                ansicht.setCurrentRow(min(z, len(liste) - 1))
            knoepfe_anpassen()

        gehe.clicked.connect(gehe_zu)
        umbenennen.clicked.connect(umbenennen_jetzt)
        loeschen.clicked.connect(loeschen_jetzt)
        ansicht.itemDoubleClicked.connect(lambda _i: gehe_zu())
        knoepfe.rejected.connect(dlg.reject)
        v.addWidget(knoepfe)
        dlg.exec()

    def register_gpx_undo_snapshot(self, name="GPX edit"):
        # Waehrend eines Umzugs legt der Umzug selbst EINEN Schnappschuss an.
        # Die beiden Teilschritte duerfen keine eigenen dazulegen, sonst
        # braeuchte Strg+Z drei Anlaeufe fuer eine Aktion.
        if getattr(self, "_verschiebe_schritt", False):
            return

        gpx_snapshot = copy.deepcopy(self.gpx_widget.gpx_list._gpx_data)
        curr_gpx_video_shift = get_gpx_video_shift() if is_gpx_video_shift_set() else None

        def undo():
            set_gpx_video_shift(curr_gpx_video_shift)
            if(not is_gpx_video_shift_set()):
                self.enableVideoGpxSync(False)
            self.gpx_widget.set_gpx_data(gpx_snapshot)
            self._gpx_data = gpx_snapshot
            self._update_gpx_overview()
            self.chart.set_gpx_data(gpx_snapshot)
            if self.mini_chart_widget:
                self.mini_chart_widget.set_gpx_data(gpx_snapshot)
            route_geojson = self._build_route_geojson_from_gpx(gpx_snapshot)
            self.map_widget.loadRoute(route_geojson, do_fit=False)

        self._undo_ablegen(undo, name)

    def register_video_undo_snapshot(self, appendToLast: bool = False, name="Video cut"):
        # Waehrend eines Umzugs legt der Umzug selbst EINEN Schnappschuss an.
        # Die beiden Teilschritte duerfen keine eigenen dazulegen, sonst
        # braeuchte Strg+Z drei Anlaeufe fuer eine Aktion.
        if getattr(self, "_verschiebe_schritt", False):
            return

        snapshot = copy.deepcopy(self.cut_manager._cut_intervals)
        # Die Markierungen 'harte Kante' gehoeren zum selben Zustand wie die
        # Schnitte selbst und muessen mit zurueckgeholt werden.
        hard_snapshot = set(self.cut_manager._hard_cuts)
        # Die eingestellten Blendenlaengen gehoeren zum selben Zustand wie die
        # Markierungen "harte Kante" und muessen mit zurueckgeholt werden.
        blenden_snapshot = dict(self.cut_manager._blenden)
        # Die Merge-Fades an den Naehten gehoeren zum selben Videostand.
        merge_snapshot = dict(self.cut_manager._merge_fades)
        # Ebenso, was die Schnitte aus der GPX-Spur genommen haben. Ohne das
        # haette ein Schnitt nach Strg+Z entweder keine Aufzeichnung mehr oder
        # die eines spaeter an derselben Stelle gesetzten.
        punkte_snapshot = copy.deepcopy(self.cut_manager._cut_points)

        def undo():
            self.cut_manager._cut_intervals = copy.deepcopy(snapshot)
            self.cut_manager._cut_points = copy.deepcopy(punkte_snapshot)
            self.timeline.clear_all_cuts()
            for (start, end) in snapshot:
                self.timeline.add_cut_interval(start, end)
            self.cut_manager._hard_cuts = set(hard_snapshot)
            self.cut_manager._blenden = dict(blenden_snapshot)
            self.cut_manager._merge_fades = dict(merge_snapshot)
            self.cut_manager.prune_hard_cuts()
            self.cut_manager._sync_timeline_hard_cuts()

            self.cut_manager.video_editor.set_cut_intervals(snapshot)
            self._refresh_preview_timeline()
            self.timeline.update()

            # 🆕: Letzten Cut-Endpunkt ermitteln
            if snapshot:
                last_end = snapshot[-1][1]
                self.cut_manager.video_editor.set_cut_time(last_end)
            else:
                self.cut_manager.video_editor.set_cut_time(0.0)

        if appendToLast and self._undo_stack:
            # Combine with the last undo
            last_undo = self._undo_stack.pop()

            def combined_undo():
                last_undo()
                undo()
                print("[DEBUG] Combined with video undo snapshot.")

            self._undo_ablegen(combined_undo, name)
        else:
            self._undo_ablegen(undo, name)

    def save_project(self):
        """
        Speichert das aktuelle Projekt in eine JSON-Datei.
        """
        filename, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "KVRouite Project (*.KVRouiteproj)")
        if not filename:
            return
        if not filename.endswith(".KVRouiteproj"):
            filename += ".KVRouiteproj"
        project_data = {
            "playlist": self.playlist,
            "video_durations": self.video_durations,
            # global_keyframes wird bewusst NICHT gespeichert.
            #
            # Der Index hat genau einen Abnehmer: den k-Schrittmodus, und der
            # zeigt, wo Copy-Mode schneiden wuerde. Copy-Mode setzt ffmpeg und
            # ffprobe auf dem System voraus - wo die Keyframes gebraucht
            # werden, ist also immer auch das Werkzeug da, sie zu erzeugen.
            # Beim Laden werden sie direkt aus den Videos gelesen (Millisekunden).
            #
            # Mitgespeichert waren sie ausserdem die Ursache falscher Daten:
            # die Liste wurde nur bei "New Project" geleert und wanderte so aus
            # einem Projekt ins naechste - gemessen an 1min.KVRouiteproj: 4948
            # Keyframes bis Sekunde 4227 fuer ein Projekt von 121 Sekunden.
            "gpx_data": self.gpx_widget.gpx_list._gpx_data,
            "cut_intervals": self.cut_manager._cut_intervals,
            "hard_cuts": self.cut_manager.get_hard_cuts(),
            # Blendenlaengen je Schnitt. Was hier fehlt, folgt der Vorgabe aus
            # dem Encoder Setup - genau wie in einer frischen Sitzung.
            "cut_fades": self.cut_manager.get_blenden(),
            # Merge-Fades je Naht der Videoliste: [[naht, sekunden|null]].
            # Fehlt der Schluessel (Projekt von vor 6.14), gibt es keine.
            "merge_fades": self.cut_manager.get_merge_fades(),
            # Was die Schnitte aus der GPX-Spur genommen haben. Ohne das war
            # "Undo Cut" nach jedem Laden grau: die Aufzeichnungen standen nur
            # im Speicher, ein geladenes Projekt begann mit einem leeren
            # _cut_points, und die erste Sperre in ruecknahme_moeglich() griff
            # damit fuer jeden Schnitt. Gemessen an maptest.KVRouiteproj:
            # 200 Byte je Punkt, drei Schnitte von je einer Minute bei 1 Hz
            # sind rund 36 kB auf eine Datei von 4,4 MB.
            "cut_points": self.cut_manager.get_cut_points(),
            # Der Zustand der Spur nach der letzten eigenen Aktion. Er MUSS
            # mitgespeichert werden: beim Laden neu gerechnet wuerde er immer
            # passen und damit jede Aufzeichnung ungeprueft freigeben - auch
            # nach einem chT oder Close Gaps zwischen Schnitt und Speichern.
            "gpx_fingerabdruck": self.cut_manager.get_gpx_abdruck(),
            # Der letzte Smooth als Zusammenfassung (Parameter, Zeit, Bereich,
            # Hoehenmeter), damit ein zweiter Durchlauf auch nach dem Laden
            # gewarnt wird. Die Hoehen selbst stehen nicht drin.
            "gpx_smooth": self.gpx_control.glaettung_als_dict(),
            "gpx_markers": {
                "markB_idx": self.gpx_widget.gpx_list._markB_idx,
                "markE_idx": self.gpx_widget.gpx_list._markE_idx
            },
            # Lesezeichen je Slot, als Koordinaten - siehe core/lesezeichen.py.
            "gpx_bookmarks": {
                str(s): list(self._gpx_slots[s].get("bookmarks") or [])
                for s in (1, 2)
            },
            "overlays": self._overlay_manager.get_all_overlays(),
            "edit_mode": self._edit_mode,
            # AutoCutVideo+GPX. Bisher wurde der Zustand nicht gespeichert,
            # sondern beim Laden daraus abgeleitet, ob ein Video/GPX-Versatz
            # in der Datei stand. Das traf zwei Faelle nicht: eingeschaltet
            # ohne gesetzten Versatz, und ausgeschaltet mit gesetztem Versatz.
            "auto_sync": bool(self._autoSyncVideoEnabled),
            "view360": self._blick360_export_cfg(),
            # Sprechstellen des Voice Removers, je Datei in Sekunden der
            # Datei - siehe _sprechstellen. Aeltere Projekte haben den
            # Schluessel nicht; dann gibt es keine.
            "voice_regions": self._sprechstellen_export(),
        }

        if is_gpx_video_shift_set():
            project_data["gpx_video_shift"]= get_gpx_video_shift() 
    
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(project_data, f, indent=2, default=str)
            QMessageBox.information(self, "Project Saved", f"Project saved to:\n{filename}")
            self.save_recent_file(filename)
            self._titel_setzen(filename)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project:\n{e}")

        
    
    def load_project(self):
        """Lädt eine Projektdatei - zeigt beide Projektformate gleichzeitig an"""
        file_path, selected_filter = QFileDialog.getOpenFileName(
            self,
            "Load Project File",
            "",
            "Project Files (*.kvrouiteproj *.vgsyncproj);;KVRouite Project (*.kvrouiteproj);;VGSync Project (*.vgsyncproj);;All Files (*.*)"
        )
    
        if not file_path:
            return

        # Automatische Erkennung anhand der Dateiendung
        file_ext = file_path.lower()
    
        try:
            if file_ext.endswith('.kvrouiteproj') or file_ext.endswith('.vgsyncproj'):
                # Deine existierende Projekt-Lade-Logik hier aufrufen
                # (die Logik, die du bereits in load_project hattest)
                
                #self._load_project_file(file_path)
                self.process_open_project(file_path)
                self.save_recent_file(file_path)
            else:
                QMessageBox.warning(
                    self, 
                    "Unsupported Format", 
                    f"File format not supported: {file_path}\n"
                    "Please select a .kvrouiteproj or .vgsyncproj file."
                )
                return
                
            self.save_recent_file(file_path)
        
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Error Loading Project", 
                f"Failed to load project file:\n{str(e)}"
            )
    
    def _titel_setzen(self, projekt: str = None):
        """Fenstertitel aufbauen - mit dem Namen des geladenen Projekts.

        Ohne Projekt steht dort wie bisher nur Name und Fassung. Ist eines
        geladen, kommt sein Dateiname davor: das ist die Stelle, an der man
        bei mehreren offenen Fenstern zuerst hinsieht.
        """
        if projekt is not None:
            self._projekt_datei = projekt
        grund = f"KVRouite v{APP_VERSION}"
        if self._projekt_datei:
            name = os.path.basename(self._projekt_datei)
            self.setWindowTitle(f"{name} - {grund}")
        else:
            self.setWindowTitle(grund)

    def process_open_project(self, filename: str):
        # Das Laden dauert bei grossen Quelldateien zehn Sekunden und mehr -
        # ohne Rueckmeldung sieht die App dabei aus, als waere sie abgestuerzt.
        # Deshalb ein Fenster, das sagt, woran gerade gearbeitet wird.
        ladefenster = PreviewPrepareDialog(0, self, titel="Loading project…")
        ladefenster.label_info.setText(
            "Opening the project and preparing the preview. "
            "Large source files can take a moment.")
        ladefenster.btn_cancel.hide()
        self._loading_project = True
        ladefenster.show()
        ladefenster.raise_()
        QApplication.processEvents()
        try:
            ladefenster.schritt("Reading project file…")
            with open(filename, "r", encoding="utf-8") as f:
                project_data = json.load(f)

            
                
                
            # 1. Playlist und Videolängen
            self.playlist = project_data.get("playlist", [])
            self.video_durations = project_data.get("video_durations", [])
            # Keyframes aus der Projektdatei uebernehmen, aber nur die, die
            # ueberhaupt in dieses Projekt passen.
            #
            # Die Zeiten sind Positionen auf der GLOBALEN Zeitachse. Aeltere
            # Projektdateien enthalten Zeiten von Videos, die beim Speichern
            # laengst nicht mehr in der Playlist standen - gemessen an
            # 1min.KVRouiteproj: 4948 Keyframes bis Sekunde 4227 fuer ein
            # Projekt von 121 Sekunden. Alles jenseits der Gesamtdauer zeigt
            # auf eine Zeitachse, die es nicht mehr gibt.
            # Keyframes immer frisch aus den Videos lesen, nie aus der
            # Projektdatei. keyframe_times_from_index holt die Tabelle direkt
            # aus dem MP4-Container - gemessen 0,002 s fuer zwei Dateien, laut
            # Messung im Indexer 0,006 s bei 11,9 GB.
            #
            # Gibt eine Datei den Schnellweg nicht her (kein MP4/MOV,
            # B-Frames, fragmentiert - siehe core/mp4_keyframes.py), bleibt die
            # Liste leer. Das ist richtig so: gebraucht wird sie nur im
            # Copy-Mode, und dort bietet die Anwendung das Indizieren ohnehin
            # an (_maybe_ask_index).
            self.global_keyframes = []
            dauern = project_data.get("video_durations", []) or []
            versatz, gesammelt = 0.0, []
            for nr, pfad in enumerate(self.playlist):
                zeiten = None
                try:
                    if os.path.exists(pfad):
                        zeiten = keyframe_times_from_index(pfad)
                except Exception:
                    zeiten = None
                if not zeiten:
                    gesammelt = []
                    print("[INFO] Keyframe-Index nicht direkt lesbar fuer %s - "
                          "er wird bei Bedarf im Copy-Mode erzeugt."
                          % os.path.basename(pfad))
                    break
                gesammelt.extend(t + versatz for t in zeiten)
                versatz += dauern[nr] if nr < len(dauern) else 0.0
            if gesammelt:
                self.global_keyframes = sorted(set(gesammelt))
                print("[DEBUG] %d Keyframes aus den Videos gelesen."
                      % len(self.global_keyframes))

            self.video_durations = project_data.get("video_durations", [])
            self.rebuild_timeline()

            ladefenster.schritt("Loading GPX data…")
            # 2. GPX-Daten laden + reparieren (datetime aus String machen)
            gpx_data = project_data.get("gpx_data", [])
            for pt in gpx_data:
                if "time" in pt and isinstance(pt["time"], str):
                    try:
                        pt["time"] = datetime.fromisoformat(pt["time"])
                    except Exception:
                        pass  # Falls Zeit kaputt, bleibt String

            self._gpx_data = gpx_data
            self.gpx_widget.gpx_list._gpx_data = gpx_data

            ladefenster.schritt("Loading cuts…")
            # 3. Cuts laden
            self.cut_manager._cut_intervals = project_data.get("cut_intervals", [])
            # Aeltere Projektdateien kennen "hard_cuts" nicht -> alle
            # Schnitte behalten ihre Blende, wie bisher.
            self.cut_manager.set_hard_cuts(project_data.get("hard_cuts", []))
            self.cut_manager.set_blenden(project_data.get("cut_fades", []))
            self.cut_manager.set_merge_fades(project_data.get("merge_fades", []))
            self.cut_manager.prune_merge_fades(len(self.playlist))
            # Aufzeichnungen der Schnitte. Fehlt der Schluessel (Projekt von
            # vor 6.03), bleibt es beim leeren Stand und die Schnitte sind
            # gesperrt wie bisher.
            anzahl_aufz = self.cut_manager.set_cut_points(
                project_data.get("cut_points", []))
            # Der Fingerabdruck kommt AUS DER DATEI und wird nicht neu
            # gerechnet - siehe set_gpx_abdruck(). Neu gerechnet passte er
            # immer und gaebe jede Aufzeichnung ungeprueft frei.
            hat_abdruck = self.cut_manager.set_gpx_abdruck(
                project_data.get("gpx_fingerabdruck"))
            self.gpx_control.glaettung_aus_dict(project_data.get("gpx_smooth"))
            # Lesezeichen je Slot; Unbrauchbares wird uebergangen.
            from core import lesezeichen as _lz
            gespeichert = project_data.get("gpx_bookmarks") or {}
            for s in (1, 2):
                self._gpx_slots[s]["bookmarks"] = _lz.aus_projekt(gespeichert.get(str(s)))
            passt = (hat_abdruck
                     and self.cut_manager.zeiten_unveraendert(self._gpx_data))
            print(f"[CUT-REC] {anzahl_aufz} Aufzeichnung(en) aus dem Projekt "
                  f"geladen, Abdruck in der Datei: "
                  f"{'ja' if hat_abdruck else 'nein'}, "
                  f"passt zur Spur: {'ja' if passt else 'nein'}")
            if self.video_durations:
                total_duration = sum(self.video_durations)
                self.timeline.set_total_duration(total_duration)
                self._thumbs.verwerfen()
                self.thumbs_anstossen()
                QTimer.singleShot(0, self.thumbs_grundstock)

                boundaries = []
                accum = 0.0
                for d in self.video_durations:
                    accum += d
                    boundaries.append(accum)
                self.timeline.set_boundaries(boundaries)
            

            # 4. GPX Markierungen B/E: nur lesen. Gesetzt werden sie unten,
            # nach Tabelle und Karte, und zwar sichtbar. Bisher standen hier
            # nur die Indizes im Widget - Zeilen, Buttons und Karte wussten
            # nichts davon, aber Smooth, chT oder Cut arbeiteten auf dem
            # unsichtbaren Bereich.
            gpx_markers = project_data.get("gpx_markers", {}) or {}

            # GPX/Video shift (s)
            set_gpx_video_shift(project_data.get("gpx_video_shift", None))
            # AutoCutVideo+GPX wird hier NICHT mehr eingeschaltet - das
            # passiert weiter unten, direkt hinter dem Edit-Mode. Warum,
            # steht dort.

            ladefenster.schritt("Loading overlays…")
            # 5. Overlays laden
            overlays = project_data.get("overlays", [])
            self._overlay_manager.clear_overlays()
            for ovl in overlays:
                self._overlay_manager.add_overlay(ovl)

            ladefenster.schritt("Opening the videos…")
            # 6. VideoEditor neu setzen
            self.video_editor.set_playlist(
                self.playlist,
                lambda nr, ges, pfad: ladefenster.schritt(
                    f"Opening video {nr} of {ges}: {os.path.basename(pfad)}"))
            self.video_control.activate_controls(True)
            if self.video_durations:
                self.video_editor.set_multi_durations(self.video_durations)

            self.video_editor.set_cut_intervals(self.cut_manager._cut_intervals)

            # 6b. 360-Blickwinkel. Vor dem Aufbau der Vorschau, damit sie
            # gleich richtig gerechnet wird - das Einschalten aendert das
            # Zielformat und baut die Timeline ohnehin neu auf.
            self._blick360_laden(project_data)
            self._sprechstellen_laden(project_data)

            self._refresh_preview_timeline()

            if self.video_durations:
                total_duration = sum(self.video_durations)
                self.video_editor.set_total_length(total_duration)

            if self.cut_manager._cut_intervals:
                cut_duration = self._calculate_cut_total_duration()
                self.video_editor.set_cut_time(cut_duration)
            else:
                self.video_editor.set_cut_time(0.0)
                
                
            mode = project_data.get("edit_mode", "off")
            try:
                current = getattr(self, "_edit_mode", "off")
                # WICHTIG: Für jedes geladene Projekt die Frage erzwingen,
                # indem wir bei Zielmode copy/encode vorher auf OFF togglen,
                # falls wir aktuell nicht OFF sind.
                if mode in ("copy", "encode") and current != "off":
                    self._set_edit_mode("off")   # kurzer Toggle, keine Indexierung hier

                self._set_edit_mode(mode)        # jetzt OFF -> copy/encode => Frage erscheint
            except Exception as _e:
                print(f"[WARN] Could not restore edit_mode '{mode}': {_e}")    

            # AutoCutVideo+GPX wiederherstellen - erst JETZT, hinter dem
            # Edit-Mode.
            #
            # Zwei Gruende, warum der Schalter bisher nach jedem Laden aus
            # war. Erstens wurde er gar nicht gespeichert, sondern daraus
            # abgeleitet, ob ein Video/GPX-Versatz in der Datei stand.
            # Zweitens lief das Einschalten oben, VOR dieser Stelle - und
            # enableVideoGpxSync() prueft self._edit_mode, der bis hierher
            # noch auf dem Stand von vor dem Laden steht. Beim Programmstart
            # ist das "off", und damit machte
            #     self._on_auto_sync_video_toggled(
            #         enable and self._edit_mode != "off")
            # aus dem gewuenschten True ein False. Wer ein Projekt in eine
            # bereits laufende Sitzung im Encode-Mode lud, sah es deshalb
            # gelegentlich funktionieren - beim Start nie.
            #
            # Aeltere Projektdateien kennen "auto_sync" nicht. Fuer die gilt
            # weiter die alte Ableitung: ein gespeicherter Versatz heisst an.
            auto_sync = bool(project_data.get("auto_sync",
                                              is_gpx_video_shift_set()))
            if auto_sync and self._edit_mode != "off":
                self.enableVideoGpxSync(True)
            print(f"[DEBUG] AutoCutVideo+GPX aus dem Projekt: "
                  f"{'an' if self._autoSyncVideoEnabled else 'aus'} "
                  f"(gespeichert {auto_sync}, edit_mode {self._edit_mode})")

            ladefenster.schritt("Building the display…")
            # 7. GPX Widgets neu aufbauen
            self.gpx_widget.set_gpx_data(gpx_data)
            self.chart.set_gpx_data(gpx_data)
            if self.mini_chart_widget:
                self.mini_chart_widget.set_gpx_data(gpx_data)

            route_geojson = self._build_route_geojson_from_gpx(gpx_data)
            self.map_widget.loadRoute(route_geojson, do_fit=True)

            # Gespeicherte Marken B/E wiederherstellen - ueber denselben Weg
            # wie beim Setzen: Zeilen rot, Buttons rot, Punkte in der Karte
            # rot. Die Karte baut ihre Punkte um 100 ms verzoegert neu auf
            # und faerbt B..E dabei selbst wieder rot (loadRoute in
            # map_page.html), deshalb kommt das Rot dort auch an.
            gl = self.gpx_widget.gpx_list
            gl.clear_marked_range()
            n_pkt = len(gpx_data)
            b_gesp = gpx_markers.get("markB_idx")
            e_gesp = gpx_markers.get("markE_idx")
            if isinstance(b_gesp, int) and 0 <= b_gesp < n_pkt:
                gl.set_markB_row(b_gesp)
            if isinstance(e_gesp, int) and 0 <= e_gesp < n_pkt:
                gl.set_markE_row(e_gesp)
            # Und hinfahren: Liste auf B gescrollt, Chart auf B, die Karte
            # zoomt beim Aufbau der Route selbst auf B..E (loadRoute in
            # map_page.html). Sonst sieht man zwar rote Buttons, muss den
            # Bereich aber in 17.000 Zeilen suchen.
            if gl._markB_idx is not None:
                b_zeile = gl._markB_idx
                gl.select_row_in_pause(b_zeile)
                self.chart.highlight_gpx_index(b_zeile)
                if self.mini_chart_widget:
                    self.mini_chart_widget.set_current_index(b_zeile)

                # Das Scrollen greift hier noch nicht: das Ladefenster ist
                # modal, die Tabelle hat ihre Groesse noch nicht, und danach
                # kommen noch die Fragen (Bildrate, Index) mit eigenen
                # Ereignisschleifen. Deshalb erst NACH den Fragen, in
                # _fragen_nach_dem_laden() - siehe _liste_auf_zeile_nach_laden().
                self._liste_zeile_nach_laden = b_zeile

            self._update_gpx_overview()

            # 8. Timeline neu aufbauen
            self.timeline.clear_all_cuts()
            for start_s, end_s in self.cut_manager._cut_intervals:
                self.timeline.add_cut_interval(start_s, end_s)
            self.cut_manager._sync_timeline_hard_cuts()

            self.timeline.update()
            self._rebuild_playlist_menu()
            self._titel_setzen(filename)

            #QMessageBox.information(self, "Project Loaded", f"Project loaded from:\n{filename}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load project:\n{e}")
        finally:
            # In JEDEM Fall schliessen - ein stehengebliebenes modales
            # Fenster waere schlimmer als gar keins.
            self._loading_project = False
            try:
                ladefenster.close()
                ladefenster.deleteLater()
            except Exception:
                pass

            # Die Vorschau JETZT aufbauen, nachdem die Fahne gefallen ist.
            #
            # Verlassen kann man sich dabei nicht auf die Aufrufe, die
            # _set_edit_mode einreiht: das Ladefenster ruft in schritt()
            # QApplication.processEvents() auf (views/dialogs.py), und dabei
            # werden sie noch WAEHREND des Ladens abgearbeitet - also zu einem
            # Zeitpunkt, an dem _refresh_preview_timeline noch aussteigt.
            # Ohne diese Zeile blieben Schnitte und Blenden danach ganz aus.
            QTimer.singleShot(0, self._refresh_preview_timeline)
            QTimer.singleShot(0, self._fragen_nach_dem_laden)
            # Passen die gespeicherten Blenden noch? Geaendert wird dabei
            # nichts - beim Laden hat der Nutzer nichts getan, was er
            # zuruecknehmen koennte.
            QTimer.singleShot(0, self._blenden_lage_melden)
            # Lassen sich die Schnitte noch verschieben und zuruecknehmen?
            # Das soll der Nutzer gleich erfahren, nicht erst beim Versuch.
            QTimer.singleShot(0, self._alte_schnitte_melden)

            
    def _rebuild_playlist_menu(self):
        self.playlist_menu.clear()

        # Reorder… immer oben wieder einfügen (Action lebt, weil Parent=self)
        self.playlist_menu.addAction(self._playlist_reorder_action)
        self.playlist_menu.addSeparator()

        self.playlist_counter = 1
        for filepath in self.playlist:
            label_text = f"{self.playlist_counter}: {os.path.basename(filepath)}"
            action = self.playlist_menu.addAction(label_text)
            action.triggered.connect(lambda checked, f=filepath, a=action: self.confirm_remove(f, a))
            self.playlist_counter += 1
     
        
    def _calculate_cut_total_duration(self):
        """
        Berechnet die Gesamtdauer nach Anwendung aller Cuts.
        """
        if not self.video_durations:
            return 0.0
        original_total = sum(self.video_durations)
        # get_total_cuts() fasst ueberlappende Schnitte zusammen. Wuerde man
        # hier stur jedes Intervall abziehen, kaeme bei zwei ueberlappenden
        # End-Schnitten 0.0 heraus - und on_save_gpx_clicked() wuerde dann
        # jeden GPX-Punkt verwerfen ("no meaningful GPX remains").
        cut_total = original_total - self.cut_manager.get_total_cuts()
        return max(0.0, cut_total)

    def save_recent_file(self, path: str):
        s = QSettings("KVRouite", "KVRouite")
        file_history = s.value("file_history", [], type=list)

        if path in file_history:
            file_history.remove(path)  # Move it to the top
        file_history.insert(0, path)

        file_history = file_history[:10]  # Keep only the last 5

        s.setValue("file_history", file_history)

    def load_last_gpx_paths(self) -> list[str]:
        s = QSettings("KVRouite", "KVRouite")
        return s.value("file_history", [], type=list)

    def remove_recent_file(self, path: str):
        """Einen Eintrag aus "Open Recent" nehmen und das Menue neu aufbauen.

        Gerufen, wenn die Datei nicht mehr da ist. Bis 6.13 blieb der Eintrag
        stehen: die Fehlermeldung kam bei jedem Klick wieder, und der tote
        Eintrag verdraengte einen brauchbaren aus der Liste von zehn.
        """
        s = QSettings("KVRouite", "KVRouite")
        file_history = s.value("file_history", [], type=list)
        if path in file_history:
            file_history = [p for p in file_history if p != path]
            s.setValue("file_history", file_history)
        self.update_recent_files_menu()

    def update_recent_files_menu(self):
        self.recent_menu.clear()

        recent_files = self.load_last_gpx_paths()
        if not recent_files:
            no_recents_action = QAction("No Recent Files", self)
            no_recents_action.setEnabled(False)
            self.recent_menu.addAction(no_recents_action)
            return

        for path in recent_files:
            action = QAction(path, self)
            action.triggered.connect(lambda checked, p=path: self.open_recent(p))
            self.recent_menu.addAction(action)

    def open_recent(self, path: str):
        if not os.path.exists(path):
            QMessageBox.critical(
                self, "Error",
                f"File does not exist:\n{path}\n\n"
                "It has been removed from Open Recent.")
            self.remove_recent_file(path)
            return
        if(path.endswith(".gpx")):
            self.process_open_gpx(path)
        elif(path.endswith(".fit")): 
            self.process_open_fit(path)  # default mode="new" passt hier
        elif(path.endswith(".mp4") or path.endswith(".MP4")):
            self.process_open_mp4([path])
        elif(path.endswith(".KVRouiteproj")):
            self.process_open_project(path)
        else:
            QMessageBox.critical(self, "Error", f"Unsupported file type:\n{path}")
            return
    
    
    def on_save_gpx_clicked(self):
        from datetime import timedelta

        # --- 0) GPX vorhanden? ---
        gpx_data = getattr(self.gpx_widget.gpx_list, "_gpx_data", [])
        if not gpx_data:
            QMessageBox.warning(self, "No GPX", "No GPX data available!")
            return

        # --- 1) Hinweis/Bestätigung ---
        reply = QMessageBox.question(
            self,
            "Save GPX",
            "Have you smoothed the GPX data?\n\n"
            "It is highly recommended to smooth your GPX before saving.\n"
            "Do you want to continue saving?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        # --- 2) Datei wählen ---
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save GPX File", "export.gpx", "GPX Files (*.gpx)"
        )
        if not out_path:
            return

        # Gibt der User nur "Test" ein, wuerde ohne Endung gespeichert.
        # Gleiches Verhalten wie beim Video-Export und beim Projekt-Speichern.
        if not out_path.lower().endswith('.gpx'):
            out_path += '.gpx'
            QMessageBox.information(
                self,
                "File Extension Added!",
                f"Added '.gpx' extension to filename:\n{os.path.basename(out_path)}"
            )

        # --- 2b) Sonderfall: GPX ohne Video ---
        # Ist kein Video geladen, gibt es keine Videolänge/keinen Video-Sync, auf
        # den die GPX gekürzt werden müsste. Die Truncation-Logik unten würde in
        # diesem Fall auf die Videolänge 0 kürzen und faelschlich
        # "no meaningful GPX remains" melden. Deshalb speichern wir hier die GPX
        # unveraendert und sind fertig. Mit geladenem Video bleibt alles wie bisher.
        if not getattr(self, "playlist", None):
            self._save_gpx_to_file(gpx_data, out_path)


            QMessageBox.information(
                self, "Done",
                f"No video loaded – GPX saved unchanged (no cut to video length) as '{out_path}'."
            )
            return

        # --- 3) Nullpunkt (Video-Start) bestimmen ---
        try:
            shift = get_gpx_video_shift()
        except Exception:
            shift = 0.0

        first_gpx_video_time = gpx_data[0]["time"] - timedelta(seconds=shift)

        # --- 4) ersten nicht-grauen Index finden ---
        first_positive_index = 0
        for i, pt in enumerate(gpx_data):
            rel_s = (pt["time"] - first_gpx_video_time).total_seconds()
            if rel_s >= 0.0:
                first_positive_index = i
                break

        if first_positive_index >= len(gpx_data):
            QMessageBox.warning(self, "Truncation", "No GPX points with positive time found!")
            return

        # --- 5) START exakt auf t=0 setzen (bei vorne-Sync) + grauen Vorlauf entfernen ---
        # Falls der erste nicht-graue Punkt bereits > 0 liegt, interpolieren wir exakt t=0 zwischen dem letzten grauen (A) und dem ersten >=0 (B)
        t_first_rel = (gpx_data[first_positive_index]["time"] - first_gpx_video_time).total_seconds()
        if first_positive_index > 0 and t_first_rel > 0.0:
            A = gpx_data[first_positive_index - 1]  # letzter Punkt <0
            B = gpx_data[first_positive_index]      # erster Punkt >=0
            tA = (A["time"] - first_gpx_video_time).total_seconds()
            tB = t_first_rel
            if tB > tA:
                f = (0.0 - tA) / (tB - tA)
                start_pt = {
                    "lat": A["lat"] + f * (B["lat"] - A["lat"]),
                    "lon": A["lon"] + f * (B["lon"] - A["lon"]),
                    "ele": A.get("ele", 0.0) + f * (B.get("ele", 0.0) - A.get("ele", 0.0)),
                    "time": first_gpx_video_time,  # exakt t=0
                    "delta_m": 0.0,
                    "speed_kmh": 0.0,
                    "gradient": 0.0,
                }
                truncated = [start_pt] + gpx_data[first_positive_index + 1:]
            else:
                truncated = gpx_data[first_positive_index:]
        else:
            truncated = gpx_data[first_positive_index:]

        if len(truncated) < 2:
            QMessageBox.warning(self, "Truncation", "After shortening to positive time, no meaningful GPX remains!")
            return

        # --- 6) finale Videolänge (Exportlänge) holen ---
        # Bevorzugt deine interne Berechnung (wie in der Infozeile). Fallback: Summe video_durations - Cuts.
        try:
            final_duration_s = float(self._calculate_cut_total_duration())
        except Exception:
            # Fallback robust
            vd = getattr(self, "video_durations", None)
            if isinstance(vd, (list, tuple)):
                total_len = float(sum(vd))
            elif isinstance(vd, dict):
                total_len = float(sum(vd.values()))
            elif vd is not None:
                total_len = float(vd)
            else:
                total_len = float(getattr(self, "real_total_duration", 0.0))

            cm = getattr(self, "cut_manager", None)
            try:
                cuts = float(cm.get_total_cuts()) if cm else 0.0
            except Exception:
                cuts = 0.0

            final_duration_s = max(0.0, total_len - cuts)

        # --- 7) ENDE millisekundengenau auf final_duration_s klemmen ---
        last_valid_index = -1
        for i, pt in enumerate(truncated):
            rel_s = (pt["time"] - first_gpx_video_time).total_seconds()
            if rel_s <= final_duration_s:
                last_valid_index = i
            else:
                break

        if last_valid_index < 0:
            QMessageBox.warning(self, "Truncation", "After shortening to the video length, no meaningful GPX remains!")
            return

        final_truncated = truncated[:last_valid_index + 1]

        # Interpolation des letzten Punkts, wenn Exportende zwischen zwei Punkten liegt
        if last_valid_index < len(truncated) - 1:
            A = final_truncated[-1]
            B = truncated[last_valid_index + 1]
            tA = (A["time"] - first_gpx_video_time).total_seconds()
            tB = (B["time"] - first_gpx_video_time).total_seconds()

            if tB > final_duration_s and (tB - tA) > 0.0:
                f = (final_duration_s - tA) / (tB - tA)
                adjusted_pt = {
                    "lat": A["lat"] + f * (B["lat"] - A["lat"]),
                    "lon": A["lon"] + f * (B["lon"] - A["lon"]),
                    "ele": A.get("ele", 0.0) + f * (B.get("ele", 0.0) - A.get("ele", 0.0)),
                    "time": first_gpx_video_time + timedelta(seconds=final_duration_s),
                    "delta_m": 0.0,
                    "speed_kmh": 0.0,
                    "gradient": 0.0,
                }
                final_truncated[-1] = adjusted_pt

        if len(final_truncated) < 2:
            QMessageBox.warning(self, "Truncation", "After shortening to the video length, no meaningful GPX remains!")
            return

        # --- 8) Speichern (NUR die gekürzte & interpolierte Liste) ---
        self._save_gpx_to_file(final_truncated, out_path)

        # --- 9) Fertigmeldung ---
        QMessageBox.information(self, "Done", f"GPX saved as '{out_path}'.")

                
    def _on_show_temp_dir(self):
        """
        Zeigt das aktuelle Temp-Verzeichnis an.
        """
        from PySide6.QtCore import QSettings
        import config

        s = QSettings("KVRouite", "KVRouite")
        path_stored = s.value("tempSegmentsDir", "", str)
        if path_stored and os.path.isdir(path_stored):
            msg = f"Currently stored Temp Directory:\n{path_stored}"
        else:
            msg = f"No temp dir stored. Default:\n{config.get_temp_segments_container()}"
        QMessageBox.information(self, "Temp Directory", msg)


    def _on_set_temp_dir(self):
        """
        Temp-Verzeichnis neu wählen.
        """
        from PySide6.QtCore import QSettings
    
        folder = QFileDialog.getExistingDirectory(self, "Select Temp Directory")
        if not folder:
            return
    
        s = QSettings("KVRouite", "KVRouite")
        s.setValue("tempSegmentsDir", folder)
        s.sync()
    
        QMessageBox.information(
            self,
            "Temp Directory Set",
            f"Temp Directory set to:\n{folder}\n\n"
            "Please restart the application for the changes to take effect."
        )


    def _on_clear_temp_dir(self):
        """
        Entfernt das Temp-Verzeichnis aus QSettings.
        """
        from PySide6.QtCore import QSettings
    
        s = QSettings("KVRouite", "KVRouite")
        s.remove("tempSegmentsDir")
        s.sync()

        QMessageBox.information(
            self,
            "Temp Directory Reset",
            "The Temp Directory setting has been cleared.\n"
            "Default will be used on next start.\n\n"
            "Please restart the application for the changes to take effect."
        )
        
    def _check_gpx_step_intervals(self, gpx_data: list[dict]) -> bool:
        

        if len(gpx_data) < 3:
            return False

        deltas = [
            (gpx_data[i]["time"] - gpx_data[i - 1]["time"]).total_seconds()
            for i in range(1, len(gpx_data))
            if isinstance(gpx_data[i]["time"], datetime) and isinstance(gpx_data[i - 1]["time"], datetime)
        ]

        if len(deltas) < 3:
            return False

        mean = statistics.mean(deltas)
        stdev = statistics.stdev(deltas)

        # Nur wenn der Mittelwert signifikant von 1.0 abweicht (> ±0.05)
        if mean < 0.95:
            ret = QMessageBox.question(
                self,
                "Resample to 1s?",
                f"The GPX data does not use 1s steps (mean: {mean:.2f}s).\n"
                "Would you like to resample it to 1s intervals?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            return ret == QMessageBox.Yes

        return False
    
        
    
    
    def _resample_to_1s(self, gpx_data: list[dict]) -> list[dict]:
        

        if not gpx_data or len(gpx_data) < 2:
            return gpx_data

        # Schritt 1: Alle Punkte in Sekunden ab Start
        base_time = gpx_data[0]["time"]
        for pt in gpx_data:
            pt["abs_s"] = (pt["time"] - base_time).total_seconds()

        new_data = []
        target_s = 0
        total_s = int((gpx_data[-1]["time"] - gpx_data[0]["time"]).total_seconds())

        i = 0
        while target_s <= total_s and i < len(gpx_data) - 1:
            while i < len(gpx_data) - 2 and gpx_data[i + 1]["abs_s"] < target_s:
                i += 1

            pt1 = gpx_data[i]
            pt2 = gpx_data[i + 1]
            s1 = pt1["abs_s"]
            s2 = pt2["abs_s"]

            if s2 == s1:
                ratio = 0
            else:
                ratio = (target_s - s1) / (s2 - s1)

            # Interpolation entlang der Strecke
            lat = pt1["lat"] + ratio * (pt2["lat"] - pt1["lat"])
            lon = pt1["lon"] + ratio * (pt2["lon"] - pt1["lon"])
            ele = pt1.get("ele", 0.0) + ratio * (pt2.get("ele", 0.0) - pt1.get("ele", 0.0))

            new_pt = {
                "lat": lat,
                "lon": lon,
                "ele": ele,
                "time": base_time + timedelta(seconds=target_s),
                "delta_m": 0.0,
                "speed_kmh": 0.0,
                "gradient": 0.0
            }
            new_data.append(new_pt)
            target_s += 1

        recalc_gpx_data(new_data)
        return new_data

    def _update_set_gpx2video_enabled(self):
        """
        Aktiviert/Deaktiviert die 'SetGPX2VideoTime'-Funktion je nach Modus.
        Nur aktiv, wenn EditMode != "off" und AutoCutVideo+GPX deaktiviert ist.
        """
        if self.gpx_control and hasattr(self.gpx_control, "_action_set_gpx2video"):
            is_edit_mode = self._edit_mode != "off"
            autocut = self.action_auto_sync_video.isChecked()
            self.gpx_control._action_set_gpx2video.setEnabled(is_edit_mode and not autocut)



    

    # Neue kombinierte Methode GPX/FIT:

    def load_track_file(self):
        """Lädt entweder eine GPX oder FIT Datei - automatisch erkannt an der Endung"""
        # Dialog für new/append (gleiche Logik wie vorher)
        if self._gpx_data:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Load Track File")
            msg_box.setText("A track is already loaded.\n"
                            "Do you want to start a new track or append the new file?")
            new_btn = msg_box.addButton("New", QMessageBox.AcceptRole)
            append_btn = msg_box.addButton("Append", QMessageBox.YesRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.RejectRole)

            msg_box.exec()
            clicked = msg_box.clickedButton()
            if clicked == cancel_btn:
                return
            elif clicked == new_btn:
                mode = "new"
                self._sync_prompt_answer = None
            else:
                mode = "append"
        else:
            mode = "new"

        # Kombiniertes Dateiauswahlfenster für beide Formate
        file_path, selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select Track File (GPX or FIT)",
            "",
            "Track Files (*.gpx *.fit);;GPX Files (*.gpx);;FIT Files (*.fit);;All Files (*.*)"
        )
    
        if not file_path:
            return
    
        # Automatische Erkennung anhand der Dateiendung
        file_ext = file_path.lower()
    
        try:
            if file_ext.endswith('.gpx'):
                self.process_open_gpx(file_path, mode)
            elif file_ext.endswith('.fit'):
                self.process_open_fit(file_path, mode)
            else:
                QMessageBox.warning(
                    self, 
                    "Unsupported Format", 
                    f"File format not supported: {file_path}\n"
                    "Please select a .gpx or .fit file."
                )
                return
            
            self.save_recent_file(file_path)
        
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Error Loading File", 
                f"Failed to load track file:\n{str(e)}"
            )
    

    
    
    
    
    def process_open_fit(self, file_path, mode="new"):
        """Verarbeitet die FIT-Datei und konvertiert sie zu GPX-Daten"""
        self.map_widget.view.page().runJavaScript("showLoading('Loading FIT...');")
        QApplication.processEvents()
    
        try:
            # FIT-Datei parsen
            fit_data = self.parse_fit(file_path)
            
            if not fit_data:
                QMessageBox.warning(self, "Load FIT", "File is empty or invalid.")
                self.map_widget.view.page().runJavaScript("hideLoading();")
                return
    
            # In GPX-Daten konvertieren
            gpx_data = self.convert_fit_to_gpx(fit_data)
            
            if not gpx_data:
                QMessageBox.warning(self, "Load FIT", "No valid track data found in FIT file.")
                self.map_widget.view.page().runJavaScript("hideLoading();")
                return
    
            # Prüfen ob Resample nötig ist
            if self._check_gpx_step_intervals(gpx_data):
                gpx_data = self._resample_to_1s(gpx_data)
    
            # Wie bei GPX weiterverarbeiten
            if mode == "new":
                self._gpx_slots[1]["gpx_data"] = gpx_data
                self._gpx_slots[1]["gpx_video_shift"] = None
                self._gpx_slots[1]["markB"] = None
                self._gpx_slots[1]["markE"] = None
                self._gpx_slots[1]["bookmarks"] = []

                if self._active_gpx_slot == 1:
                    self._apply_slot_to_ui()    
                if self._active_gpx_slot == 2:
                    self.switch_gpx_slot(1)
                    try:
                        btn = self.gpx_control.slot_button
                        btn.blockSignals(True)
                        btn.setChecked(False)
                        btn.setText("Slot 1")
                        btn.setStyleSheet(self.gpx_control._slot1_style)
                        btn.blockSignals(False)
                    except Exception as e:
                        print(f"[DEBUG] Slot1-AutoActivate UI update skipped: {e}")
                        
                        
            elif mode == "append":
                if not self._gpx_data:
                        # --- Append ausschließlich in Slot 1 ---
                    base = self._gpx_slots[1]["gpx_data"] or []
                    merged = (base + gpx_data) if base else list(gpx_data)
                    self._gpx_slots[1]["gpx_data"] = merged
                    if self._active_gpx_slot == 1:
                        self._apply_slot_to_ui()
                    returnself._set_gpx_data(gpx_data)
                else:
                    old_data = self._gpx_data
                    old_snapshot = copy.deepcopy(old_data)
                    self.gpx_widget.gpx_list._history_stack.append(old_snapshot)
    
                    from datetime import timedelta
                    old_end_time = old_data[-1]["time"]
                    gap_start = old_end_time + timedelta(seconds=1)
                    shift_dt = gap_start - gpx_data[0]["time"]
    
                    for pt in gpx_data:
                        pt["time"] = pt["time"] + shift_dt
    
                    merged_data = old_data + gpx_data
                    recalc_gpx_data(merged_data)
                    self._set_gpx_data(merged_data)
                    QMessageBox.information(self, "Load FIT", "FIT data appended successfully.")
    
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load FIT file:\n{str(e)}")
        finally:
            self.map_widget.view.page().runJavaScript("hideLoading();")
    
        self.proposeVideoGpxSync()
    
    def parse_fit(self, file_path):
        """Parst die FIT-Datei und extrahiert Track-Daten"""
        fitfile = fitparse.FitFile(file_path)
        
        records = []
        for record in fitfile.get_messages('record'):
            point = {}
            
            # Koordinaten
            lat = record.get_value('position_lat')
            lon = record.get_value('position_long')
            
            if lat is not None and lon is not None:
                # FIT-Koordinaten sind in semicircles, konvertiere zu Grad
                point['lat'] = lat * (180 / 2**31)
                point['lon'] = lon * (180 / 2**31)
            else:
                continue  # Punkt ohne Koordinaten überspringen
                
            # Höhe
            altitude = record.get_value('altitude')
            point['ele'] = altitude if altitude is not None else 0.0
            
            # Zeit
            timestamp = record.get_value('timestamp')
            point['time'] = timestamp if timestamp else datetime.now()
            
            records.append(point)
        
        return records
    
    def convert_fit_to_gpx(self, fit_data):
        """Konvertiert FIT-Daten in GPX-Format mit allen benötigten Feldern"""
        if not fit_data:
            return []
        
        gpx_data = []
        for i, point in enumerate(fit_data):
            gpx_point = {
                "lat": point["lat"],
                "lon": point["lon"], 
                "ele": point["ele"],
                "time": point["time"],
                "delta_m": 0.0,  # Wird später berechnet
                "speed_kmh": 0.0,  # Wird später berechnet
                "gradient": 0.0,   # Wird später berechnet
            }
            gpx_data.append(gpx_point)
        
        # Metriken berechnen
        if len(gpx_data) > 1:
            recalc_gpx_data(gpx_data)
        
        return gpx_data
    
    def _on_extract_gopro_gps(self):
        """
        Wird aufgerufen, wenn 'Extract GoPro-GPS' im Menü geklickt wird.
        """
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
            QHBoxLayout, QPushButton, QMessageBox
        )
        from PySide6.QtCore import Qt
        import os

        # Prüfe nur SLOT 2 (Extractor-Slot) – Slot 1 bleibt unberührt
        slot2_has_gpx = False
        try:
            slot2_has_gpx = bool(self._gpx_slots[2]["gpx_data"])
        except Exception:
            slot2_has_gpx = False

        keep_append = False 
        
        if slot2_has_gpx:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Slot 2 already contains GPX")
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setText(
                "Slot 2 (GoPro Extractor) already contains GPX data.\n\n"
                "What do you want to do?"
            )

            overwrite_btn = msg_box.addButton("Overwrite Slot 2", QMessageBox.YesRole)
            append_btn    = msg_box.addButton("Keep & Append", QMessageBox.NoRole)
            cancel_btn    = msg_box.addButton("Cancel", QMessageBox.RejectRole)

            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == cancel_btn:
                return

            if clicked == overwrite_btn:
                # Nur Slot 2 leeren (KEIN globales _clear_gpx_data!)
                self._gpx_slots[2]["gpx_data"] = []
                self._gpx_slots[2]["markB"] = None
                self._gpx_slots[2]["markE"] = None
                self._gpx_slots[2]["gpx_video_shift"] = None
                self._gpx_slots[2]["bookmarks"] = []

                # Falls aktuell Slot 2 aktiv ist, UI entsprechend leeren
                if getattr(self, "_active_gpx_slot", 1) == 2:
                    self.gpx_widget.set_gpx_data([])
                    self.chart.set_gpx_data([])
                    if self.mini_chart_widget:
                        self.mini_chart_widget.set_gpx_data([])
                    self.map_widget.loadRoute({"type": "FeatureCollection", "features": []}, do_fit=True)
                    from core.gpx_parser import set_gpx_video_shift
                    set_gpx_video_shift(None)
                    self._update_gpx_overview()
            else:
                
                keep_append = True

        # jetzt erst prüfen, ob Videos geladen sind
        if not self.playlist:
            QMessageBox.warning(
                self,
                "No Videos Loaded",
                "Please load video files first before extracting GPS data."
            )
            return

        # Warnhinweis
        reply = QMessageBox.warning(
            self,
            "Experimental Feature",
            "EXPERIMENTAL - All video files must be loaded\n\n"
            "Only works with GoPro files containing GPS data.\n"
            "Each video will be processed sequentially.\n"
            "Extracted GPX tracks will be automatically appended.\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # === Inline-Auswahldialog (KEINE neue Klasse/Datei) ===
        selection_dlg = QDialog(self)
        selection_dlg.setWindowTitle("GoPro Extraction Selection")
        selection_dlg.setModal(True)
        selection_dlg.resize(520, 460)

        vbox = QVBoxLayout(selection_dlg)
        vbox.addWidget(QLabel("Detected GoPro videos:"))

        lw = QListWidget(selection_dlg)
        for p in self.playlist:
            it = QListWidgetItem(os.path.basename(p))
            it.setCheckState(Qt.Checked)
            lw.addItem(it)
        vbox.addWidget(lw)

        hbox = QHBoxLayout()
        btn_first = QPushButton("Only First Video", selection_dlg)
        btn_sel = QPushButton("Selected", selection_dlg)
        btn_all = QPushButton("All", selection_dlg)
        btn_cancel = QPushButton("Cancel", selection_dlg)
        hbox.addWidget(btn_all)
        hbox.addWidget(btn_sel)
        hbox.addWidget(btn_first)
        hbox.addWidget(btn_cancel)
        vbox.addLayout(hbox)

        # Ergebniscontainer
        chosen_files = []

        def _choose_all():
            nonlocal chosen_files
            chosen_files = list(self.playlist)
            selection_dlg.accept()

        def _choose_first():
            nonlocal chosen_files
            chosen_files = [self.playlist[0]]
            selection_dlg.accept()

        def _choose_selected():
            nonlocal chosen_files
            checked = []
            for i in range(lw.count()):
                it = lw.item(i)
                if it.checkState() == Qt.Checked:
                    checked.append(it.text())
            if not checked:
                QMessageBox.warning(selection_dlg, "No Selection", "Please select at least one file or use 'All' / 'Only First'.")
                return
            # Basenames -> Full paths
            base_set = set(checked)
            chosen_files = [p for p in self.playlist if os.path.basename(p) in base_set]
            selection_dlg.accept()

        btn_all.clicked.connect(_choose_all)
        btn_first.clicked.connect(_choose_first)
        btn_sel.clicked.connect(_choose_selected)
        btn_cancel.clicked.connect(selection_dlg.reject)

        if selection_dlg.exec() != QDialog.Accepted:
            print("[DEBUG] Extraction cancelled by user in selection dialog")
            return

        if not chosen_files:
            QMessageBox.information(self, "Nothing selected", "No video selected for extraction.")
            return

        print(f"[DEBUG] Extracting {len(chosen_files)} videos")

        # Starte den Extraktionsprozess - benutze DEINEN existierenden Dialog
        dlg = GoProExtractorDialog(chosen_files, self, keep_append=keep_append)
        dlg.show()
        QApplication.processEvents()
        dlg.start_extraction()

    

    
    def _import_gopro_gpx(self, gpx_path, is_first_video=True):
        """
        Vereinfachte Import-Funktion - erwartet bereits korrekt zusammengeführte GPX
        """
        if not os.path.exists(gpx_path):
            print(f"GPX file not found: {gpx_path}")
            return
    
        try:
            # Parse die GPX-Datei
            new_data = parse_gpx(gpx_path)
            
            if not new_data:
                print("No valid GPX data found in extracted file")
                return

            # --- Slot 2 füllen (keine globale UI-Löschung/Überschreibung) ---
            # --- Slot 2 vorbereiten & Daten speichern ---
            self._gpx_slots[2]["gpx_data"] = new_data
            self._gpx_slots[2]["markB"] = None
            self._gpx_slots[2]["markE"] = None
            self._gpx_slots[2]["bookmarks"] = []
            self._gpx_slots[2]["gpx_video_shift"] = 0
            self._gpx_slots[2]["sync_enabled"] = True

            # --- Direkt Slot 2 aktivieren, bevor UI geladen wird ---
            self._active_gpx_slot = 2
            self._apply_slot_to_ui()  # zeigt Map + GPX sofort an

            # --- Button-Status visuell anpassen ---
            try:
                btn = self.gpx_control.slot_button
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.setText("Slot 2")
                btn.setStyleSheet(self.gpx_control._slot2_style)
                btn.blockSignals(False)
                self.gpx_control.apply_slot_button_style(2)
            except Exception as e:
                print(f"[DEBUG] Slot2 button update skipped: {e}")

            # --- Sync-Zustand & Edit-Mode aktivieren ---
            if self.playlist_counter > 0:
                from core.gpx_parser import set_gpx_video_shift
                set_gpx_video_shift(0)
                self.enableVideoGpxSync(True)
                self._gpx_slots[2]["sync_enabled"] = True
                if self._edit_mode != "off":
                    self.video_control.set_editing_mode(True, True)
                print("✓ Automatic video-GPX synchronization activated for GoPro data")

            # --- Integration abschließen ---
            QTimer.singleShot(200, self._complete_gpx_integration)

            QTimer.singleShot(200, self._complete_gpx_integration)
            
        except Exception as e:
            print(f"❌ Error importing combined GPX: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(
                self,
                "GPX Import Error", 
                f"Failed to import combined GPX:\n{str(e)}"
            )
            
    
    def _complete_gpx_integration(self):
        """
        Vollständige Integration der GPX-Daten für Video-Synchronisation.
        Wird nach dem GoPro-Extraktionsprozess aufgerufen.
        """
        if not self._gpx_data or not self.playlist:
            return
        
        # 1. Stelle sicher, dass alle UI-Komponenten aktualisiert sind
        self._update_gpx_overview()
        self.chart.set_gpx_data(self._gpx_data)
        if self.mini_chart_widget:
            self.mini_chart_widget.set_gpx_data(self._gpx_data)
        
        # 2. Lade die Route in die Map
        route_geojson = self._build_route_geojson_from_gpx(self._gpx_data)
        self.map_widget.loadRoute(route_geojson, do_fit=True)
        
        # 3. Aktiviere die Auto-Sync-Funktionalität falls möglich
        if is_gpx_video_shift_set():
            self.enableVideoGpxSync(True)
            
            # 4. Setze den aktuellen Video-Zeitpunkt auf den Start
            if self.video_editor.get_current_position_s() == 0:
                # Springe zum ersten Frame, um die Synchronisation zu testen
                self.video_editor.show_first_frame_at_index(0)
                
                # Markiere den ersten GPX-Punkt
                if len(self._gpx_data) > 0:
                    self.gpx_widget.gpx_list.select_row_in_pause(0)
                    self.map_widget.show_blue(0, do_center=True)
                    self.chart.highlight_gpx_index(0)    
                    
    def _load_player_settings(self):
        """
        Lädt die Player-Einstellungen aus QSettings.
        """
        s = QSettings("KVRouite", "KVRouite")
        
        # Standardwerte: True (beide Optionen aktiv)
        #show_endcut = s.value("player/show_endcut", True, type=bool)
        show_endcut_warning = s.value("player/show_endcut_warning", True, type=bool)
        
        # Setze die Menü-Zustände
        #self.action_show_endcut.setChecked(show_endcut)
        self.action_show_endcut_warning.setChecked(show_endcut_warning)
        
        print(f"[DEBUG] Player settings loaded: warning={show_endcut_warning}")

    def _save_player_settings(self):
        """
        Speichert die Player-Einstellungen in QSettings.
        """
        s = QSettings("KVRouite", "KVRouite")
        
        
        s.setValue("player/show_endcut_warning", self.action_show_endcut_warning.isChecked())
        
        s.sync()
        print(f"[DEBUG] Player settings saved: warning={self.action_show_endcut_warning.isChecked()}")

    

    def _on_show_endcut_warning_toggled(self, checked: bool):
        """
        Wird aufgerufen, wenn "Show Endcut Warning" an/aus geschaltet wird.
        """
        print(f"[DEBUG] Show Endcut Warning: {checked}")
        self._save_player_settings()                


    def _on_open_tutorials(self):
        """
        Öffnet den KVRouite YouTube-Kanal im Standard-Browser nach Bestätigung durch den Benutzer.
        """
        youtube_url = "https://www.youtube.com/@KVRouite"
        
        # Überprüfe, ob die URL gültig ist
        url = QUrl(youtube_url)
        if not url.isValid():
            QMessageBox.critical(
                self,
                "Invalid URL",
                f"The YouTube URL is invalid:\n{youtube_url}"
            )
            return

        # Bestätigungs-Popup anzeigen
        reply = QMessageBox.question(
            self,
            "Open YouTube Tutorials",
            "Do you want to open the KVRouite YouTube channel ?\n\n"
            "This will open in your default web browser.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No  # Standard-Button: No
        )
        
        if reply == QMessageBox.Yes:
            # YouTube-Kanal im Browser öffnen
            QDesktopServices.openUrl(url)
            
    def _on_toggle_360_from_menu(self, checked: bool = None):
        # Editor schaltet um; Menü-Check danach mit tatsächlichem Zustand
        # synchronisieren. Ohne `checked` wird umgeschaltet - das ist der Weg
        # über Taste V und über den Menüeintrag.
        self.video_editor.toggle_360_mode(checked)
        an = bool(getattr(self.video_editor, "_is_360_mode", False))
        self.action_toggle_360.setChecked(an)
        if an:
            # Beim Einschalten den gespeicherten Blickwinkel des laufenden
            # Videos wiederherstellen.
            self._blick360_an_player()

    # ------------------------------------------------------------------
    # 360: Blickwinkel je Video
    # ------------------------------------------------------------------
    # `self.view360_views` liegt parallel zu `self.playlist` - ein Eintrag je
    # Video, wie `self.video_durations`. Gespeichert wird in Radiant, weil das
    # Backend so rechnet.

    def _blick360_liste(self):
        """Die Liste auf die Länge der Playlist bringen und zurückgeben."""
        if not hasattr(self, "view360_views") or self.view360_views is None:
            self.view360_views = []
        fehlend = len(self.playlist) - len(self.view360_views)
        if fehlend > 0:
            self.view360_views += [view360.Blickwinkel()
                                   for _ in range(fehlend)]
        elif fehlend < 0:
            del self.view360_views[len(self.playlist):]
        return self.view360_views

    def _blick360_an_player(self):
        """Alle Blickwinkel an das Backend geben.

        Nicht nur den des laufenden Videos: die Vorschau ist EINE Timeline mit
        allen Clips, und jeder Clip traegt den Blickwinkel seiner Quelldatei.
        """
        liste = self._blick360_liste()
        self.video_editor.set_blick360_liste([b.werte() for b in liste])

    def _on_blick360_geaendert(self, index, yaw, pitch, fov):
        """Der Editor meldet einen neuen Blickwinkel - merken."""
        liste = self._blick360_liste()
        if 0 <= index < len(liste):
            liste[index].setzen(yaw, pitch, fov)

    def _on_blick360_auf_alle(self):
        """Den Blickwinkel des laufenden Videos auf alle übertragen.

        Material aus derselben Kamera hat praktisch immer dieselbe Ausrichtung
        - ohne das müsste man ihn für jede Datei neu einstellen.
        """
        liste = self._blick360_liste()
        if not liste:
            return
        yaw, pitch, fov = self.video_editor.blick360()
        for blick in liste:
            blick.setzen(yaw, pitch, fov)
        self._blick360_an_player()
        QMessageBox.information(
            self, "360°",
            f"View applied to all {len(liste)} video(s):\n"
            f"yaw {math.degrees(yaw):+.1f}°, pitch {math.degrees(pitch):+.1f}°, "
            f"field of view {math.degrees(fov):.0f}°")

    def _blick360_export_cfg(self):
        """Der Abschnitt "view360" für Projektdatei und Export."""
        return {
            "enabled": bool(getattr(self.video_editor, "_is_360_mode", False)),
            "views": [b.als_dict() for b in self._blick360_liste()],
        }


    def keyPressEvent(self, event):
        """Nur V. Alles andere an Tasten liegt woanders.

        Geschwindigkeit (+, -, 1 bis 9), 360-Blickwinkel und Zoom haengen an
        QShortcut mit Qt.ApplicationShortcut in video_editor_widget.py. Die
        greifen unabhaengig davon, welches Widget den Fokus hat, und decken
        zusaetzlich den Ziffernblock und die =-Variante mancher Layouts ab.

        Bis 6.03 stand weiter oben im Fenster eine zweite Methode desselben
        Namens. In Python gewinnt die spaeter definierte - die erste war
        unerreichbar. Sie behandelte + und - noch einmal auf eigene Weise und
        wurde samt ihrem Zustand entfernt (vlc_speeds, speed_index,
        current_rate), den sonst niemand benutzt hat.
        """
        if event.key() == Qt.Key_V:
            # trigger() schaltet den Menuehaken um und ruft dabei
            # _on_toggle_360_from_menu mit dem neuen Zustand auf.
            self.action_toggle_360.trigger()
        else:
            super().keyPressEvent(event)
            
    def _show_shortcuts_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Shortcuts")
        dlg.setMinimumSize(560, 500)

        v = QVBoxLayout(dlg)

        head = QLabel("<b>Keyboard Shortcuts</b>")
        v.addWidget(head)

        txt = QTextEdit()
        txt.setReadOnly(True)

        # Kopfzeile und Linien aus der Farbtafel: fest #f3f3f3 stand im
        # dunklen Betrieb helle Schrift auf hellem Grund - der Tabellenkopf
        # war unsichtbar (gesehen am 08.09.2026).
        from core import theme
        f = theme.farben()
        help_html = """
        <style>
          /* Die Liste wird von links nach rechts abgearbeitet, die erste
             vorhandene Schrift gewinnt: Windows nimmt Segoe UI und Consolas,
             macOS Helvetica Neue und Menlo, Linux DejaVu. Der Name mit
             Leerzeichen gehoert in Anfuehrungszeichen. */
          body { font-family: "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 12.5px; }
          code { font-family: Consolas, Menlo, "DejaVu Sans Mono", monospace; }
          table { border-collapse: collapse; width: 100%%; }
          th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid %(gitter)s; vertical-align: top; }
          th { background: %(kopf)s; color: %(text)s; }
        </style>""" % {"gitter": f["gitter"], "kopf": f["kopfzeile"], "text": f["text"]} + """
        <table>
          <tr><th>Action</th><th>Shortcut</th><th>Notes</th></tr>

          <tr><td>Undo</td><td><code>Ctrl+Z</code></td>
              <td>Revert the last action.</td></tr>
              
          <tr><td>Increase / Decrease speed</td>
              <td><code>+</code> / <code>-</code></td>
              <td>Adjusts Video-playback rate in 0.10× steps.</td></tr>    

          <tr><td>Toggle 360° mode</td><td><code>V</code></td>
              <td>Activate the 360° view (Pan/Tilt/Zoom are only active in 360° mode.)</td></tr>

          
          <tr><td>Set exact speed</td>
              <td><code>1</code>…<code>9</code></td>
              <td><code>1</code>=1.0×, <code>2</code>=2.0×, …, <code>9</code>=9.0×.</td></tr>

          <tr><td>Zoom</td>
              <td><code>Ctrl + +</code> / <code>Ctrl + -</code></td>
              <td>Only available in 360° mode.</td></tr>

          <tr><td>Pan / Tilt</td>
              <td><code>Ctrl + Arrow Keys</code></td>
              <td>Left/Right/Up/Down; only available in 360° mode.</td></tr>
          <tr><td>Reset View</td>
              <td><code>Ctrl + 0</code></td>
              <td>Reset the View; only available in 360° mode.</td></tr>

          <tr><td>Add bookmark</td><td><code>Ctrl + B</code></td>
              <td>Bookmark the selected GPX row (menu Bookmarks, or right-click on the map or in the table).</td></tr>
          <tr><td>Go to bookmark</td>
              <td><code>Ctrl + 1</code>…<code>Ctrl + 9</code></td>
              <td>Jump to bookmark 1…9 of the active GPX slot.</td></tr>
        </table>
        """
        txt.setHtml(help_html)
        v.addWidget(txt)

        btns = QDialogButtonBox(QDialogButtonBox.Ok, parent=dlg)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)

        dlg.exec()
        
        
    def _ask_new_append(self, title: str, text: str, default: str = "append") -> str:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        new_btn    = box.addButton("New", QMessageBox.AcceptRole)
        append_btn = box.addButton("Append", QMessageBox.AcceptRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        # Default-Fokus
        if default.lower() == "append":
            box.setDefaultButton(append_btn)
        else:
            box.setDefaultButton(new_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is new_btn:    return "new"
        if clicked is append_btn: return "append"
        return "cancel"

    # --- Handler: Videos gedroppt ---
    def _on_videos_dropped(self, paths: list[str]):
        if not paths:
            return

        # already videos loaded?
        has_videos = getattr(self, "playlist_counter", 0) > 0

        if not has_videos:
            # kein Dialog, einfach "New"
            self._clear_video_playlist()   # nur Videos leeren (s.u.)
            try:
                self.process_open_mp4(paths)  
                self._maybe_prompt_edit_mode_after_first_load() 
                try:
                    if paths:
                        self.save_recent_file(paths[0])
                        self.update_recent_files_menu()
                except Exception:
                    pass
            except Exception as e:
                print(f"[Drop Videos] Error (first import): {e}")
            return

        # Es gibt schon Videos => fragen
        choice = self._ask_new_append("Import Videos", "Import dropped videos?", "append")
        if choice == "cancel":
            return

        try:
            if choice == "new":
                self._clear_video_playlist()
                self.process_open_mp4(paths)
                try:
                    if paths:
                        self.save_recent_file(paths[0])
                        self.update_recent_files_menu()
                except Exception:
                    pass
                
            else:  # "append"
                self.process_open_mp4(paths)
                try:
                    if paths:
                        self.save_recent_file(paths[0])
                        self.update_recent_files_menu()
                except Exception:
                    pass
        except Exception as e:
            print(f"[Drop Videos] Error: {e}")


    def _clear_video_playlist(self):
        # interne Zustände zurücksetzen
        self.playlist = []
        self.playlist_counter = 0
        self.video_durations = []
        self._sprechstellen = {}
        self._sprechstellen_anzeigen()
        self.view360_views = []
        self._360_aus_projekt = False
        # Keyframes sind Positionen auf der globalen Zeitachse. Ohne Playlist
        # gibt es diese Achse nicht mehr.
        self.global_keyframes = []
        try:
            self.video_editor.set_playlist([])   # Playlist leeren
        except Exception:
            pass

        # UI aktualisieren
        try:
            self.video_control.activate_controls(False)
        except Exception:
            pass

        try:
            self.rebuild_timeline()              # setzt Total-Dauer/Boundaries auf 0
        except Exception:
            pass

        # Menü neu aufbauen/aufräumen
        if hasattr(self, "_rebuild_playlist_menu"):
            self._rebuild_playlist_menu()
        elif hasattr(self, "playlist_menu"):
            self.playlist_menu.clear()


    # --- Handler: GPX/FIT gedroppt (Map oder Liste) ---
    def _on_tracks_dropped(self, paths: list[str]):
        if not paths:
            return

        # Max. 1 Datei zulassen
        p0 = paths[0]
        if len(paths) > 1:
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, "Multiple files",
                    "Please load only one GPX/FIT file via drag & drop.\n"
                    "Only the first one is imported."
                )
            except Exception:
                pass  # not critical for headless/test runs

        pl = p0.lower()
        is_gpx = pl.endswith(".gpx")
        is_fit = pl.endswith(".fit")
        if not (is_gpx or is_fit):
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Unsupported", f"Not a GPX/FIT file:\n{p0}")
            except Exception:
                pass
            return

        # Wenn noch keine GPX/FIT geladen ist: immer New (ohne Dialog)
        has_tracks = bool(getattr(self, "_gpx_data", None))
        if not has_tracks:
            choice = "new"
        else:
            # Es sind bereits Tracks vorhanden → nachfragen
            choice = self._ask_new_append("Import Tracks", "Import dropped GPX/FIT?", "append")
            if choice == "cancel":
                return

        try:
            if is_gpx:
                self.process_open_gpx(p0, mode=choice)   # deine Loader unterstützen 'mode'
                try:
                    self.save_recent_file(p0)
                    self.update_recent_files_menu()
                except Exception:
                    pass
            else:
                self.process_open_fit(p0, mode=choice)
                try:
                    self.save_recent_file(p0)
                    self.update_recent_files_menu()
                except Exception:
                    pass
        except Exception as e:
            print(f"[Drop Track] Error on {p0}: {e}")
            
            
    # mainwindow.py
    def _maybe_prompt_edit_mode_after_first_load(self):
        # Nur fragen, wenn aktuell OFF ist (wie beim normalen Load)
        if getattr(self, "_edit_mode", "off") != "off":
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QPushButton

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit video")
        vbox = QVBoxLayout(dlg)
        vbox.addWidget(QLabel("Select video edition mode"))

        btns = QDialogButtonBox()
        # "Copy" nur anbieten, wenn ffmpeg und ffprobe vorhanden sind.
        if copy_mode_moeglich():
            b_copy = QPushButton("Copy")
            btns.addButton(b_copy, QDialogButtonBox.YesRole)
            b_copy.clicked.connect(lambda: dlg.done(1))
        b_enc  = QPushButton("Encode"); btns.addButton(b_enc,   QDialogButtonBox.ActionRole); b_enc.clicked.connect(lambda: dlg.done(2))
        b_no   = QPushButton("No Edit");btns.addButton(b_no,    QDialogButtonBox.RejectRole); b_no.clicked.connect(lambda: dlg.reject())
        vbox.addWidget(btns)

        res = dlg.exec()
        if res == 1:
            self._set_edit_mode("copy")    # zeigt anschließend eure Index-Dialog-Logik an
        elif res == 2:
            self._set_edit_mode("encode")  # dito

        # wie im normalen Flow
        try:
            self.proposeVideoGpxSync()
        except Exception:
            pass
        QTimer.singleShot(120, self._auto_enable_360_if_needed)

        
        
    # NEU: kleine Hilfsfunktion neben deinem Helper platzieren
    def _auto_enable_360_if_needed(self):
        """360 selbst einschalten, wenn das Material danach aussieht.

        Erkennungsmerkmal ist das Seitenverhältnis 2:1. Ein geladenes Projekt
        hat den Vorrang: wer 360 dort bewusst ausgeschaltet hat, soll es nicht
        beim nächsten Öffnen wieder anhaben.
        """
        if getattr(self, "_360_aus_projekt", False):
            return
        try:
            w, h = self.video_editor.get_video_size()
            if view360.ist_equirect(w, h) and not self.video_editor.is_360_mode():
                self._on_toggle_360_from_menu(True)  # schaltet Menü+Player sauber um
        except Exception as e:
            print(f"[DEBUG] _auto_enable_360_if_needed: {e}")

    def _blick360_laden(self, project_data):
        """360-Zustand aus einer Projektdatei übernehmen.

        Ältere Projekte haben den Abschnitt nicht - dann bleibt alles beim
        Alten und die Automatik entscheidet wie bisher.
        """
        daten = project_data.get("view360")
        if not isinstance(daten, dict):
            self._360_aus_projekt = False
            return
        self._360_aus_projekt = True
        self.view360_views = [view360.Blickwinkel.aus_dict(d)
                              for d in (daten.get("views") or [])]
        self._blick360_liste()          # auf die Länge der Playlist bringen
        an = bool(daten.get("enabled"))
        if an and not self.video_editor.supports_360():
            self._360_aus_projekt = False
            print("[WARN] Das Projekt hat 360 an, das Backend kann es nicht - "
                  "bitte unter Config -> Video Backend auf GES stellen.")
            return
        self._on_toggle_360_from_menu(an)

    
    def _on_raise_track_above_sea(self, delta_m: float):
        """
        Raises the entire GPX track by 'delta_m' meters (including greyed points).
        Recomputes derived values and refreshes all views.
        """
        if not self._gpx_data or delta_m <= 0:
            return

        
        try:
            self.register_gpx_undo_snapshot("Raise track above sea")
        except Exception:
            pass

        # 1) Elevation aller Punkte erhöhen (auch graue)
        for pt in self._gpx_data:
            if pt.get("ele") is not None:
                pt["ele"] = float(pt["ele"]) + float(delta_m)

        # 2) Abgeleitete Werte neu berechnen
        try:
            from core.gpx_parser import recalc_gpx_data
            recalc_gpx_data(self._gpx_data)
        except Exception:
            pass

        # 3) Alle Views updaten
        try:
            self.gpx_widget.set_gpx_data(self._gpx_data)
        except Exception:
            pass
        try:
            self._update_gpx_overview()
        except Exception:
            pass
        try:
            self.chart.set_gpx_data(self._gpx_data)
        except Exception:
            pass
        try:
            # Map neu zeichnen 
            new_geojson = self._build_route_geojson_from_gpx(self._gpx_data)
            self.map_widget.loadRoute(new_geojson, do_fit=False)
        except Exception:
            pass
        
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Track lifted",
                                    f"Raised entire track by {delta_m:.2f} m.")
                                    
        except Exception:
            pass

    def _validate_overlays_after_xfade_change(self) -> bool:
        """
        Prüft alle bestehenden Overlays gegen das aktuell in QSettings gesetzte encoder/xfade.
        Gibt True zurück, wenn alles ok; bei Verstößen Warnhinweis (englisch) und False.
        """
        
        

        # 1) Aktuelles xfade aus dem Setup
        s = QSettings("KVRouite", "KVRouite")
        try:
            xfade = float(s.value("encoder/xfade", 2, type=int))
        except Exception:
            xfade = 2.0
        if xfade < 0:
            xfade = 0.0

        total = float(getattr(self, "real_total_duration", 0.0))
        if total <= 0.0:
            return True  # kein Video => nichts zu prüfen

        # 2) Cuts/Keep-Segmente holen (deine bestehende Logik)
        cuts = list(self.cut_manager.get_cut_intervals())
        keep_list = self._compute_keep_intervals(cuts, total)

        # 3) Alle Overlays prüfen
        violations = []
        for ovl in self._overlay_manager.get_all_overlays():
            start_s = float(ovl.get("start", 0.0))
            end_s   = float(ovl.get("end",   0.0))
            if end_s <= start_s:
                continue

            # passendes Keep-Segment finden, das den gesamten Bereich enthält
            containing = None
            for (ks, ke) in keep_list:
                if start_s >= ks and end_s <= ke:
                    containing = (ks, ke)
                    break

            if containing is None:
                violations.append(
                    f"[{start_s:.2f}s … {end_s:.2f}s] crosses a cut/video boundary"
                )
                continue

            ks, ke = containing
            # Der Rand haengt am jeweiligen Schnitt, nicht mehr am globalen
            # Wert: seit 6.03 kann jeder Schnitt seine eigene Blendenlaenge
            # haben. Videoanfang und -ende liefern 0.
            allowed_start_min = ks + self._blende_am_rand(ks)
            allowed_end_max   = ke - self._blende_am_rand(ke)

            if start_s < allowed_start_min or end_s > allowed_end_max:
                max_len_here = max(0.0, allowed_end_max - max(start_s, allowed_start_min))
                violations.append(
                    (f"[{start_s:.2f}s … {end_s:.2f}s] violates crossfade margins "
                     f"(allowed window: {allowed_start_min:.2f}s … {allowed_end_max:.2f}s; "
                     f"max length here: {max_len_here:.2f}s)")
                )

        if violations:
            msg = ("Some existing overlays no longer fit the new crossfade setting.\n" 
                    "You´re Video will not be longer in sync, remove the Overlays!\n\n" +
                   "\n".join(violations[:8]) +
                   ("\n… (more)" if len(violations) > 8 else ""))
            QMessageBox.warning(self, "Overlays invalid with new xfade!", msg)
            return False

        return True

    def _check_updates_interactive(self):
        """
        Wird nur vom Menüpunkt 'Check for Updates' aufgerufen.
        Markiert den Lauf als 'manuell', damit wir ggf. einen Dialog zeigen.
        """
        self._update_check_is_manual = True
        self._kickoff_update_check()

    def _kickoff_update_check(self):
        # Repo aus Settings (Default wurde im __init__ gesetzt)
        s = QSettings("KVRouite","KVRouite")
        repo = s.value("updates/repo", "ridewithoutstomach/KVRouite", type=str)

        url = f"https://api.github.com/repos/{repo}/releases?per_page=10"
        req = QNetworkRequest(QUrl(url))

        # GitHub erwartet einen User-Agent
        try:
            from config import APP_VERSION
            ua = f"KVRouite/{APP_VERSION}"
        except Exception:
            ua = "KVRouite"
        req.setRawHeader(b"User-Agent", ua.encode("utf-8"))
        req.setRawHeader(b"Accept", b"application/vnd.github+json")

        # Kein HTTP/2: Qt 6.11 liest nach dem GOAWAY von GitHub noch einmal auf dem
        # bereits geschlossenen Socket und meldet "QIODevice::read (QSslSocket): device not open".
        req.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, False)

        self._update_nam = getattr(self, "_update_nam", QNetworkAccessManager(self))
        reply = self._update_nam.get(req)
        reply.finished.connect(lambda r=reply, reponame=repo: self._on_update_reply(r, reponame))


    def _on_update_reply(self, reply, repo: str):
        # Fehler robust prüfen (nicht truthy/falsy, sondern explizit)
        err = reply.error()
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        reason = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
        body_bytes = bytes(reply.readAll())
        body_text = body_bytes.decode("utf-8", errors="replace")

        if err != QNetworkReply.NetworkError.NoError:
            print(f"[updates] network error: {err} {reply.errorString()}  http={status_code} {reason}")
            reply.deleteLater()
            return

        if status_code and int(status_code) >= 400:
            print(f"[updates] HTTP error: {status_code} {reason}  body[:200]={body_text[:200]!r}")
            reply.deleteLater()
            return

        # JSON parsen
        import json
        try:
            data = json.loads(body_text)
        except Exception as e:
            print(f"[updates] JSON parse error: {e}  body[:200]={body_text[:200]!r}")
            reply.deleteLater()
            return

        # tag_name aus Releases
        tags = []
        for rel in data:
            tag = str(rel.get("tag_name") or rel.get("name") or "").strip()
            if tag:
                tags.append(tag)

        reply.deleteLater()

        if not tags:
            # Fallback: /tags
            url = f"https://api.github.com/repos/{repo}/tags?per_page=10"
            req = QNetworkRequest(QUrl(url))
            req.setRawHeader(b"User-Agent", b"KVRouite")
            req.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, False)  # s. _kickoff_update_check
            r2 = self._update_nam.get(req)
            r2.finished.connect(lambda r=r2, reponame=repo: self._on_tags_reply(r, reponame))
            return

        self._evaluate_tags_and_notify(tags, repo)

    def _on_tags_reply(self, reply, repo: str):
        err = reply.error()
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        reason = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
        body_text = bytes(reply.readAll()).decode("utf-8", errors="replace")

        if err != QNetworkReply.NetworkError.NoError:
            print(f"[updates] tag fetch error: {err} {reply.errorString()}  http={status_code} {reason}")
            reply.deleteLater()
            return

        if status_code and int(status_code) >= 400:
            print(f"[updates] tag HTTP error: {status_code} {reason}  body[:200]={body_text[:200]!r}")
            reply.deleteLater()
            return

        import json
        try:
            arr = json.loads(body_text)
        except Exception as e:
            print(f"[updates] tags JSON parse error: {e}  body[:200]={body_text[:200]!r}")
            reply.deleteLater()
            return

        tags = []
        for t in arr:
            tag = str(t.get("name") or "").strip()
            if tag:
                tags.append(tag)

        reply.deleteLater()
        self._evaluate_tags_and_notify(tags, repo)
        
    def _evaluate_tags_and_notify(self, tags: list[str], repo: str):
        """
        Zeigt Updates nur für *stabile* Tags (genau vX.Y[.Z...]).
        Pre-/Beta-/RC-Tags werden ignoriert.
        Falls User selbst eine *_pre/-beta/-rc* Version hat, wird ein stabiles Release
        mit gleichem oder höherem Core (z. B. 4.27 statt 4.27_pre) angeboten.
        """
        import re
        if not tags:
            print("[updates] no tags found")
            return

        # 1) Nur stabile Tags behalten: vX.Y[.Z...] ohne weiteren Suffix
        stable_tags = []
        for t in tags:
            t = (t or "").strip()
            if re.fullmatch(r"[vV]?\d+(?:\.\d+)*", t):
                stable_tags.append(t)

        if not stable_tags:
            print("[updates] only pre-release tags found; no stable updates to show")
            return

        def to_tuple(ver: str):
            """ 'v4.27' -> (4,27); '4.27.1' -> (4,27,1) """
            v = ver.strip()
            if v.lower().startswith("v"):
                v = v[1:]
            nums = tuple(int(x) for x in v.split(".") if x.isdigit())
            return nums

        # 2) Neueste stabile Version bestimmen
        try:
            newest_stable = sorted(stable_tags, key=to_tuple, reverse=True)[0]
        except Exception:
            newest_stable = stable_tags[0]

        newest_core = to_tuple(newest_stable)

        # 3) Aktuelle APP_VERSION normalisieren (Core + erkennen, ob "pre")
        try:
            from config import APP_VERSION
            current_raw = f"{APP_VERSION}".strip()
        except Exception:
            current_raw = "0.0"

        # Core extrahieren (nur Ziffern und Punkte am Anfang)
        m = re.match(r"^[vV]?(\d+(?:\.\d+)*)", current_raw)
        current_core_str = m.group(1) if m else "0.0"
        current_core = to_tuple(current_core_str)

        # Ist die aktuelle Version selbst ein Pre/Beta/RC?
        is_current_prerelease = not re.fullmatch(r"[vV]?\d+(?:\.\d+)*", current_raw)

        # 4) Vergleichslogik:
        # - Wenn aktueller Core kleiner als neuester stabiler Core -> Update anbieten (auf newest_stable)
        # - Wenn aktueller Core == neuester stabiler Core,
        #   aber aktuelle Build ist *pre/beta/rc* -> "Stable available" auf newest_stable anbieten
        # - Sonst: nichts anzeigen
        if current_core < newest_core:
            self._notify_new_version(current_raw, newest_stable, repo)
        elif current_core == newest_core and is_current_prerelease:
            self._notify_new_version(current_raw, newest_stable, repo)
        
        else:
            print(f"[updates] up-to-date (stable). current={current_raw}, latest_stable={newest_stable}")
            # Nur wenn der User manuell geprüft hat, auch ein Fenster zeigen:
            if getattr(self, "_updates_manual", False):
                try:
                    from PySide6.QtWidgets import QMessageBox
                    # Anzeige: führendes "v"/"V" ausblenden
                    disp_current = re.sub(r'^[vV]', '', str(current_raw or ""))
                    disp_latest  = re.sub(r'^[vV]', '', str(newest_stable or ""))
                    html = (
                        "<html><head><style>"
                        "td{font-family:Consolas,Menlo,'DejaVu Sans Mono',monospace;font-size:10pt}"
                        "td.label{white-space:nowrap}"
                        "td.val{text-align:right;padding-left:12px;min-width:4em}"
                        "</style></head><body>"
                        "<table>"
                        f"<tr><td class='label'>Current version:</td><td class='val'>{disp_current}</td></tr>"
                        f"<tr><td class='label'>Latest stable:</td><td class='val'>{disp_latest}</td></tr>"
                        "</table>"
                        "</body></html>"
                    )

                    QMessageBox.information(self, "You are up to date", html)
                    
                    

                finally:
                    # Flag zurücksetzen, damit Auto-Check still bleibt
                    self._updates_manual = False
            return
    
    
    

    

    def _notify_new_version(self, current: str, newest_stable: str, repo: str):
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QUrl, QTimer
        from PySide6.QtGui import QDesktopServices

        releases_url = f"https://github.com/{repo}/releases"

        def _show():
            # Anzeige: führendes "v"/"V" ausblenden
            disp_current = re.sub(r'^[vV]', '', str(current or ""))
            disp_latest  = re.sub(r'^[vV]', '', str(newest_stable or ""))

            html = (
                "<html><head><style>"
                "td{font-family:Consolas,Menlo,'DejaVu Sans Mono',monospace;font-size:10pt}"
                "td.label{white-space:nowrap}"
                "td.val{text-align:right;padding-left:12px;min-width:4em}"
                "</style></head><body>"
                "<div>A newer <i>stable</i> version is available on GitHub.</div><br/>"
                "<table>"
                f"<tr><td class='label'>Current:</td><td class='val'>{disp_current}</td></tr>"
                f"<tr><td class='label'>Latest (stable):</td><td class='val'>{disp_latest}</td></tr>"
                "</table><br/>"
                "<div>Open the releases page now?</div>"
                "</body></html>"
            )

            answer = QMessageBox.information(
                self,
                "New Version Available",
                html,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            if answer == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(releases_url))

        # Sicherstellen, dass der Dialog erst nach dem Paint-Cycle kommt
        QTimer.singleShot(0, _show)


    ##################
    def _on_open_reorder_playlist_dialog(self):
        """
        Reorder-Dialog mit Up/Down Buttons pro Eintrag (kein Drag&Drop).
        - Fortlaufende Nummer vor dem Dateinamen
        - Warnung bei vorhandenen Cuts/Overlays
        - KEIN Undo-Eintrag
        """
        if not getattr(self, "playlist", None):
            QMessageBox.information(self, "Reorder", "No videos loaded.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Reorder Playlist")
        vbox = QVBoxLayout(dlg)

        lw = QListWidget(dlg)
        lw.setAlternatingRowColors(True)
        lw.setDragDropMode(QListWidget.NoDragDrop)
        vbox.addWidget(lw)

        # ---------------- Hilfsfunktionen ----------------

        def rebuild_row_numbers_and_buttons_state():
            count = lw.count()
            for i in range(count):
                it = lw.item(i)
                row_widget = lw.itemWidget(it)
                if not row_widget:
                    continue
                num_label = row_widget.findChild(QLabel, "num_label")
                if num_label is not None:
                    num_label.setText(f"{i+1}.")
                btn_up = row_widget.findChild(QToolButton, "btn_up")
                btn_dn = row_widget.findChild(QToolButton, "btn_dn")
                if btn_up is not None:
                    btn_up.setEnabled(i > 0)
                if btn_dn is not None:
                    btn_dn.setEnabled(i < count - 1)
        
        def move_item(old_row: int, new_row: int):
            """
            Stabil: keine Item-Objekte verschieben (take/insert),
            sondern nur die Inhalte (UserRole + Dateiname im Zeilen-Widget) tauschen.
            """
            count = lw.count()
            if new_row < 0 or new_row >= count or new_row == old_row:
                return

            it_a = lw.item(old_row)
            it_b = lw.item(new_row)
            if it_a is None or it_b is None:
                return

            # Pfade (Schlüssel) tauschen
            path_a = it_a.data(Qt.UserRole)
            path_b = it_b.data(Qt.UserRole)
            it_a.setData(Qt.UserRole, path_b)
            it_b.setData(Qt.UserRole, path_a)

            # Sichtbarer Name im Row-Widget tauschen
            wa = lw.itemWidget(it_a)
            wb = lw.itemWidget(it_b)
            if wa is not None:
                lbl_a = wa.findChild(QLabel, "name_label")
                if lbl_a is not None:
                    lbl_a.setText(os.path.basename(path_b))
            if wb is not None:
                lbl_b = wb.findChild(QLabel, "name_label")
                if lbl_b is not None:
                    lbl_b.setText(os.path.basename(path_a))

            # Nummern & Button-Enable-States neu setzen
            rebuild_row_numbers_and_buttons_state()

        
        

        def make_row_widget(it: QListWidgetItem, path: str) -> QWidget:
            w = QWidget(lw)
            h = QHBoxLayout(w)
            h.setContentsMargins(6, 2, 6, 2)
            h.setSpacing(8)

            # Nummer
            lbl_num = QLabel(w)
            lbl_num.setObjectName("num_label")
            lbl_num.setMinimumWidth(26)
            h.addWidget(lbl_num)

            # Dateiname
            name = os.path.basename(path)
            lbl_name = QLabel(name, w)
            lbl_name.setObjectName("name_label")
            lbl_name.setTextInteractionFlags(Qt.TextSelectableByMouse)
            h.addWidget(lbl_name, 1)

            # Up / Down
            btn_up = QToolButton(w)
            btn_up.setObjectName("btn_up")
            btn_up.setIcon(self.style().standardIcon(QStyle.SP_ArrowUp))
            btn_up.setToolTip("Move up")
            h.addWidget(btn_up)

            btn_dn = QToolButton(w)
            btn_dn.setObjectName("btn_dn")
            btn_dn.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
            btn_dn.setToolTip("Move down")
            h.addWidget(btn_dn)

            def on_up():
                row = lw.row(it)
                move_item(row, row - 1)

            def on_dn():
                row = lw.row(it)
                move_item(row, row + 1)

            btn_up.clicked.connect(on_up)
            btn_dn.clicked.connect(on_dn)

            return w

        # -------- Liste befüllen (mit UserRole=Pfad) --------
        for path in self.playlist:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, path)
            it.setSizeHint(QSize(0, 28))
            lw.addItem(it)
            lw.setItemWidget(it, make_row_widget(it, path))

        # Initiale Nummerierung / Button-States
        rebuild_row_numbers_and_buttons_state()

        # OK/Cancel Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        vbox.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        # Dialog starten
        if dlg.exec() != QDialog.Accepted:
            return

        # neue Reihenfolge einsammeln
        new_order = []
        for i in range(lw.count()):
            it = lw.item(i)
            new_order.append(it.data(Qt.UserRole))

        if new_order == self.playlist:
            return

        # Warnung, falls Edits vorhanden
        has_cuts = bool(getattr(self.cut_manager, "_cut_intervals", []))

        try:
            has_ovl = bool(self._overlay_manager.get_all_overlays())
        except Exception:
            has_ovl = False

        # NEU: „vorne grau“ prüfen – exakt wie deine GPX-Liste das färbt:
        # rel_s < 0  => Zeile grau; rel_s steckt in _gpx_times
        has_front_grey = False
        try:
            gpx_times = getattr(self.gpx_widget.gpx_list, "_gpx_times", [])
            if gpx_times:
                has_front_grey = any((t is not None and t < 0.0) for t in gpx_times)
        except Exception:
            has_front_grey = False
            
        has_front_grey = False
        try:
            gpx_data = getattr(self.gpx_widget.gpx_list, "_gpx_data", [])
            if gpx_data:
                try:
                    shift = get_gpx_video_shift()   # gleicher Helper wie im Export
                except Exception:
                    shift = 0.0
                # „vorne grau“ <=> Shift ist negativ
                if shift < 0.0:
                    has_front_grey = True
        except Exception:
            has_front_grey = False    

        
        if has_cuts or has_ovl or has_front_grey:    
            parts = []
            if has_cuts:
                parts.append("cuts")
            if has_ovl:
                parts.append("overlays")
            if has_front_grey:
                parts.append("a front sync (pre-video grey section)")

            detail = " and ".join(parts) if parts else "edits"
            reply = QMessageBox.question(
                self,
                "Warning",
                (
                    f"You already have {detail}.\n"
                    "Reordering can misalign your edits or invalidate the current sync.\n\n"
                    "Proceed anyway?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # Anwenden – KEIN Undo
        self.playlist = new_order[:]                  # 1) Reihenfolge setzen
        self.video_editor.set_playlist(self.playlist) # 2) Playlist neu
        self.rebuild_timeline()                       # 3) Timeline neu berechnen
        self._rebuild_playlist_menu()                 # 4) Menü neu aufbauen

        try:
            if self.playlist:
                self.video_editor.show_first_frame_at_index(0)
        except Exception:
            pass

        try:
            self.statusBar().showMessage("Order changed. Timeline rebuilt.", 3000)
        except Exception:
            pass

    
    def _on_goto_next_edit_requested(self):
        """
        Rechtsklick auf Goto-End:
        springt zum nächsten Edit-Event nach aktueller globaler Zeit.
        Priorität: Cut-Start -> Cut-Ende -> Merge-Point -> End.
        Danach Wrap hart auf 0.000 s.
        """
        try:
            # from PySide6.QtCore import QTimer  # falls noch nicht importiert
            eps = 1e-4
            wrap_window = 0.8  # Toleranz: "praktisch am Ende" (in Sekunden)

            # 1) aktuelle globale Zeit
            current = float(self.video_editor.get_current_global_time())

            # 2) Gesamtdauer (Timeline-Ende)
            total = 0.0
            try:
                if getattr(self, "video_durations", None):
                    total = float(sum(float(d) for d in self.video_durations))
                elif hasattr(self, "real_total_duration"):
                    total = float(self.real_total_duration)
            except Exception:
                total = float(getattr(self, "real_total_duration", 0.0))

            # 3) Wenn wir (praktisch) am Ende stehen -> Wrap direkt zu 0.0 s
            if total > 0.0 and (total - current) <= wrap_window:
                self._handle_video_end_state(mark_as_end=False)
                for delay in (10, 100, 250):
                    QTimer.singleShot(delay, lambda t=0.0: self.video_editor.seek_global(t))
                try:
                    self.statusBar().showMessage("Wrapped to 0.000s", 2000)
                except Exception:
                    pass
                return

            # Helper: Events ab einer Schwelle sammeln, inkl. 'end'
            def collect_events(threshold):
                evts = []  # (kind, time)

                # Cuts
                cuts = []
                try:
                    cuts = self.cut_manager.get_cut_intervals()
                except Exception:
                    cuts = getattr(self.cut_manager, "_cut_intervals", [])
                for (st, en) in sorted(cuts, key=lambda x: (x[0], x[1])):
                    if st is not None and st > threshold + eps:
                        evts.append(("cut_start", float(st)))
                    if en is not None and en > threshold + eps:
                        evts.append(("cut_end", float(en)))

                # Merge-Points (Videogrenzen) – letzte Grenze (== total) EXPLIZIT ausschließen!
                if getattr(self, "video_durations", None):
                    acc = 0.0
                    for d in self.video_durations:
                        acc += float(d)
                        # nur "innere" Grenzen zulassen (strict < total - eps)
                        if acc < (total - eps) and acc > threshold + eps:
                            evts.append(("merge", acc))

                # Ende der Timeline als eigenes Event
                if total > threshold + eps:
                    evts.append(("end", total))

                return evts

            # 4) Events nach current einsammeln
            events = collect_events(current)

            # 5) Wenn gar kein Event kommt -> Sicherheitshalber Wrap zu 0.0 s
            if not events:
                self._handle_video_end_state(mark_as_end=False)
                for delay in (10, 100, 250):
                    QTimer.singleShot(delay, lambda t=0.0: self.video_editor.seek_global(t))
                try:
                    self.statusBar().showMessage("Wrapped to 0.000s", 2000)
                except Exception:
                    pass
                return

            # 6) Nächstes Event wählen (Zeit, dann Priorität)
            #    Priorität: cut_start (0) < cut_end (1) < merge (2) < end (3)
            prio = {"cut_start": 0, "cut_end": 1, "merge": 2, "end": 3}
            events.sort(key=lambda kv: (kv[1], prio.get(kv[0], 99)))
            next_kind, next_t = events[0]

            # 7) Springen (robust, wie bei Goto-End)
            self._handle_video_end_state(mark_as_end=False)
            for delay in (10, 100, 250):
                QTimer.singleShot(delay, lambda t=next_t: self.video_editor.seek_global(t))

            try:
                label = next_kind.replace('_', ' ')
                self.statusBar().showMessage(f"Jumped to next {label} @ {next_t:.3f}s", 2000)
            except Exception:
                pass

        except Exception as e:
            print(f"[ERROR] _on_goto_next_edit_requested: {e}")

    def _on_goto_prev_edit_requested(self):
        """
        Rechtsklick auf Goto Start: das Gegenstueck zu
        _on_goto_next_edit_requested, rueckwaerts.

        Springt zum vorigen Ereignis VOR der aktuellen Zeit: Schnittanfang,
        Schnittende oder Naht zweier Dateien. Kommt nichts mehr, geht es auf
        0,000 s; steht man schon (praktisch) am Anfang, springt es ans Ende -
        so, wie der Vorwaertssprung vom Ende auf den Anfang zurueckfaellt.

        Die Toleranz nach hinten ist grosszuegiger als vorwaerts: nach einem
        Sprung liegt die Wiedergabe oft ein Bild HINTER dem Ziel, und ein
        weiterer Rechtsklick soll dann die Kante davor treffen, nicht dieselbe
        noch einmal.
        """
        try:
            toleranz = 0.1
            wrap_window = 0.8

            current = float(self.video_editor.get_current_global_time())
            total = 0.0
            try:
                if getattr(self, "video_durations", None):
                    total = float(sum(float(d) for d in self.video_durations))
                elif hasattr(self, "real_total_duration"):
                    total = float(self.real_total_duration)
            except Exception:
                total = float(getattr(self, "real_total_duration", 0.0))

            def springen(ziel, text):
                self._handle_video_end_state(mark_as_end=False)
                for delay in (10, 100, 250):
                    QTimer.singleShot(delay, lambda t=ziel: self.video_editor.seek_global(t))
                try:
                    self.statusBar().showMessage(text, 2000)
                except Exception:
                    pass

            # Praktisch am Anfang: ans Ende, wie vorwaerts vom Ende an den Anfang.
            if current <= wrap_window:
                if total > 0.0:
                    springen(total, f"Wrapped to end @ {total:.3f}s")
                return

            events = []
            try:
                cuts = self.cut_manager.get_cut_intervals()
            except Exception:
                cuts = getattr(self.cut_manager, "_cut_intervals", [])
            for (st, en) in cuts:
                if st is not None and float(st) < current - toleranz:
                    events.append(("cut start", float(st)))
                if en is not None and float(en) < current - toleranz:
                    events.append(("cut end", float(en)))
            if getattr(self, "video_durations", None):
                acc = 0.0
                for d in self.video_durations:
                    acc += float(d)
                    if acc < total - 1e-4 and acc < current - toleranz:
                        events.append(("file join", acc))

            if not events:
                springen(0.0, "Jumped to start @ 0.000s")
                return

            # Das spaeteste Ereignis vor der aktuellen Zeit; bei gleicher Zeit
            # dieselbe Reihenfolge wie vorwaerts: Schnittanfang vor Schnittende
            # vor Naht.
            prio = {"cut start": 0, "cut end": 1, "file join": 2}
            events.sort(key=lambda kv: (-kv[1], prio.get(kv[0], 99)))
            art, ziel = events[0]
            springen(ziel, f"Jumped to previous {art} @ {ziel:.3f}s")

        except Exception as e:
            print(f"[ERROR] _on_goto_prev_edit_requested: {e}")
