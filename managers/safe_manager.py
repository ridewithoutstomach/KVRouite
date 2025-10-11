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

# managers/safe_manager.py

import subprocess
import re
import os
import tempfile

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QProgressBar, QLabel, QMessageBox
)
from PySide6.QtCore import Qt, QProcess, QTimer

class SafeManager(QDialog):
    def __init__(self, cmd_list, total_duration_s: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Safe Manager – ffmpeg in QProcess")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        self.label_status = QLabel("Starte ...", self)
        layout.addWidget(self.label_status)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        row_btn = QHBoxLayout()
        self.btn_cancel = QPushButton("Abbrechen", self)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        row_btn.addStretch()
        row_btn.addWidget(self.btn_cancel)
        layout.addLayout(row_btn)

        self.setLayout(layout)

        self.cmd_list = cmd_list
        self.total_duration_s = total_duration_s
        self.ffmpeg_process = None

    def start_saving(self):
        if not self.cmd_list or len(self.cmd_list) < 2:
            QMessageBox.critical(self, "Fehler", "Ungültiges ffmpeg-Kommando!")
            self.close()
            return
        self._start_ffmpeg()

    def _start_ffmpeg(self):
        self.label_status.setText("Starte ffmpeg ...")
        self.progress_bar.setValue(0)

        self.ffmpeg_process = QProcess(self)
        self.ffmpeg_process.setProgram(self.cmd_list[0])
        self.ffmpeg_process.setArguments(self.cmd_list[1:])

        self.ffmpeg_process.readyReadStandardError.connect(self._on_read_stderr)
        self.ffmpeg_process.finished.connect(self._on_process_finished)
        self.ffmpeg_process.start()
        if not self.ffmpeg_process.waitForStarted(3000):
            QMessageBox.critical(self, "Fehler", "Konnte ffmpeg nicht starten!")
            self.close()

    def _on_read_stderr(self):
        if not self.ffmpeg_process:
            return
        data = self.ffmpeg_process.readAllStandardError().data().decode("utf-8", errors="replace")
        lines = data.split("\n")
        for line in lines:
            line = line.strip()
            if "time=" in line:
                m = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if m:
                    cur_time_str = m.group(1)
                    cur_s = self._hms_to_seconds(cur_time_str)
                    pct = 0
                    if self.total_duration_s > 0:
                        pct = (cur_s / self.total_duration_s) * 100
                        if pct > 100:
                            pct = 100
                    self.progress_bar.setValue(int(pct))
                    hms_total = self._seconds_to_hms(self.total_duration_s)
                    self.label_status.setText(f"Verarbeite: {cur_time_str} / {hms_total}")

    def _on_process_finished(self, exit_code, exit_status):
        if exit_code == 0:
            self.progress_bar.setValue(100)
            self.label_status.setText("Fertig!")
        else:
            self.label_status.setText(f"Fehler oder abgebrochen (exit={exit_code}).")
        QTimer.singleShot(1000, self.close)

    def _on_cancel_clicked(self):
        if self.ffmpeg_process and self.ffmpeg_process.state() == QProcess.Running:
            self.ffmpeg_process.kill()
            self.ffmpeg_process.waitForFinished()
        self.close()

    def _hms_to_seconds(self, hms_str: str) -> float:
        try:
            hh, mm, ss = hms_str.split(":")
            sec = float(ss)
            return int(hh)*3600 + int(mm)*60 + sec
        except:
            return 0.0

    def _seconds_to_hms(self, total_seconds: float) -> str:
        s = int(round(total_seconds))
        h = s // 3600
        s %= 3600
        m = s // 60
        s %= 60
        return f"{h:02d}:{m:02d}:{s:02d}"
