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

# managers/import_export_manager.py
import subprocess
import os
import sys
import json
from PySide6.QtWidgets import QMessageBox

class ImportExportManager:
    """
    Dient dazu, Videos zu importieren (ffprobe-Aufrufe, Keyframes-Index),
    und am Ende exportieren (Concat-Skripte, etc.).
    """
    def __init__(self, mainwindow):
        self.mw = mainwindow  # Referenz auf dein MainWindow oder ein 'context'
        
    def start_indexing_process(self, video_path):
        dlg = _IndexingDialog(video_path, parent=self)
        dlg.indexing_extracted.connect(self.on_extract_finished)
        dlg.start_indexing()
        dlg.exec()  

    def on_extract_finished(self, video_path, temp_dir):
        print("[DEBUG] on_extract_finished => rufe run_merge an ...")
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        csv_file = os.path.join(temp_dir, f"keyframes_{base_name}_ffprobe.csv")
        self.run_merge(video_path, csv_file, temp_dir)
        
    def run_merge(self, video_path, csv_file, temp_dir):
        print("[DEBUG] run_merge => optionaler code hier ...")
        offset_value = self._get_offset_for_filepath(video_path)
        
        
        
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

            self.global_keyframes.extend(new_kfs)
            self.global_keyframes = sorted(set(self.global_keyframes))
            print("[DEBUG] %d Keyframes global geladen (gesamt)." % len(self.global_keyframes))

        except Exception as e:
            print("[DEBUG] Fehler beim Laden der JSON:", e)
    
    