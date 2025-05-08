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

# managers/end_manager.py

import os
import tempfile
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QMessageBox
from PySide6.QtGui import QPixmap

class EndManager(QObject):
    def __init__(self, video_editor, timeline, cut_manager, mainwindow, parent=None):
        super().__init__(parent)
        self.video_editor = video_editor
        self.timeline = timeline
        self.cut_manager = cut_manager           # <-- NEU
        self.mainwindow = mainwindow            # <-- NEU
        #print("[DEBUG] EndManager wurde erstellt.")

    def go_to_end(self):
        """
        Wird aufgerufen, wenn man den >>| -Button anklickt.
        Bisher hat man hier ans letzte Frame gesprungen. 
        Neu: Wir prüfen, ob MarkB gesetzt ist. 
             Falls nein => Warnung.
             Falls ja => MarkE = komplettes Video-Ende,
                         und wenn AutoSyncVideo=ON => 
                         markiere auch in GPX-Liste von B..Ende.
        """
        print("[DEBUG] go_to_end() wurde aufgerufen")

        if not self.video_editor.multi_durations:
            print("[DEBUG] keine Videos geladen (multi_durations ist leer)")
            return

        # 1) Haben wir überhaupt MarkB?
        if self.cut_manager.markB_time_s < 0:
            QMessageBox.warning(
                None,
                "MarkB not set",
                "Please set MarkB first, before cutting the End of the video."
            )
            return

        # 2) Komplettes Ende des Videos errechnen
        total_duration = sum(self.video_editor.multi_durations)
        print(f"[DEBUG] Gesamtdauer: {total_duration:.2f} s")
        if total_duration <= 0:
            print("[DEBUG] Video hat keine positive Gesamtdauer.")
            return

        # 3) MarkE = Video-Ende setzen
        self.cut_manager.markE_time_s = total_duration
        self.timeline.set_markE_time(total_duration)
        print(f"[DEBUG] MarkE automatisch gesetzt auf {total_duration:.3f}s")

        # 4) Falls AutoSyncVideo ON => im GPX von B..Ende rot markieren
        if self.mainwindow._autoSyncVideoEnabled:
            print("[DEBUG] AutoSyncVideo ist an => auch in GPX den Bereich bis zum Schluss markieren.")
            gpx_list = self.mainwindow.gpx_widget.gpx_list
            if gpx_list._markB_idx is None or gpx_list._markB_idx < 0:
                print("[DEBUG] Im GPX ist allerdings kein MarkB gesetzt => wir lassen es so.")
            else:
                row_count = gpx_list.table.rowCount()
                if row_count > 0:
                    e_idx = row_count - 1
                    gpx_list.set_markE_row(e_idx)
                    print(f"[DEBUG] GPX => E = letzte Zeile (Index={e_idx})")

        # 5) Optional: Du kannst hier noch eine Info-Box anzeigen,
        #    damit der User weiß, er braucht jetzt nur noch "cut" zu drücken.
        reply = QMessageBox.question(
            None,
            "Cut Now?",
            "The End of the video is now marked (B..E).\n"
            "Do you want to cut this section now?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            print("[DEBUG] User confirmed => führe Schnitt aus.")
            self.mainwindow.on_cut_clicked_video()
        else:
            print("[DEBUG] User hat abgelehnt => kein Schnitt.")
        
    def _set_global_time_s(self, new_global_s: float):
        """
        Versetzt den Player (media_list_player) an die globale Zeit new_global_s,
        pausiert dann sofort. So bleiben wir garantiert am letzten Frame stehen.
        """
        durations = self.video_editor.multi_durations
        if not durations:
            return

        boundaries = []
        offset = 0.0
        for dur in durations:
            offset += dur
            boundaries.append(offset)

        total_all = boundaries[-1]
        if new_global_s < 0:
            new_global_s = 0
        if new_global_s > total_all:
            new_global_s = total_all

        new_idx = 0
        offset_prev = 0.0
        if abs(new_global_s - total_all) < 0.0001:
            new_idx = len(boundaries) - 1
            if new_idx > 0:
                offset_prev = boundaries[new_idx - 1]
        else:
            for i, bnd in enumerate(boundaries):
                if new_global_s <= bnd:
                    new_idx = i
                    break
                offset_prev = bnd

        local_s = new_global_s - offset_prev
        if local_s < 0:
            local_s = 0

        self.video_editor.media_list_player.stop()
        self.video_editor.is_playing = False
        self.video_editor._current_index = new_idx
        self.video_editor.media_list_player.play_item_at_index(new_idx)

        def after_switch():
            self.video_editor.media_player.set_time(int(local_s * 1000))
            self.video_editor.media_player.set_pause(True)
            self.video_editor.is_playing = False

        QTimer.singleShot(50, after_switch)

    def _take_snapshot(self, out_file: str):
        w = self.video_editor.video_frame.width()
        h = self.video_editor.video_frame.height()
        self.video_editor.media_player.video_take_snapshot(0, out_file, w, h)

    def _show_snapshot_dialog(self, path_to_image: str):
        dlg = QDialog()
        dlg.setWindowTitle("Schnappschuss – letztes Frame")

        vbox = QVBoxLayout(dlg)
        lbl = QLabel()
        pix = QPixmap(path_to_image)
        lbl.setPixmap(pix)
        vbox.addWidget(lbl)

        btn = QPushButton("OK")
        btn.clicked.connect(dlg.close)
        vbox.addWidget(btn)

        dlg.exec()
