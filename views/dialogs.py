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

# views/dialogs.py

import os
import shutil

from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QPushButton, QProgressBar, \
    QHBoxLayout, QMessageBox, QTextEdit
    
from PySide6.QtCore import QTimer, QProcess, Signal, Qt
from PySide6.QtCore import QEvent


from config import TMP_KEYFRAME_DIR
from config import MY_GLOBAL_TMP_DIR            

class _IndexingDialog(QDialog):
    indexing_extracted = Signal(str, str)  # (video_path, temp_dir)

    def __init__(self, video_path, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.process = None
        self._outfile = None
        self._line_count = 0
        
        
        base_name = os.path.splitext(os.path.basename(self.video_path))[0]
        self.output_csv = os.path.join(TMP_KEYFRAME_DIR, f"keyframes_{base_name}_ffprobe.csv")

        self.setWindowTitle("Indexing Keyframes")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        info_text = f"Indexing {base_name} -> {self.output_csv}"
        self.label_info = QLabel(info_text, self)
        layout.addWidget(self.label_info)

        more_info_text = "Please wait patiently. Large files can take 5–10 minutes!"
        self.label_more_info = QLabel(more_info_text, self)
        layout.addWidget(self.label_more_info)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.label_linecount = QLabel("Read Keyframe:", self)
        layout.addWidget(self.label_linecount)

        self._bounce_timer = QTimer(self)
        self._bounce_timer.timeout.connect(self._on_bounce_timer)
        self._bounce_timer.start(80)
        self._bounce_value = 0

        row_btn = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self.on_cancel)
        row_btn.addStretch()
        row_btn.addWidget(self.btn_cancel)
        layout.addLayout(row_btn)

    def _on_bounce_timer(self):
        self._bounce_value += 2
        if self._bounce_value > 100:
            self._bounce_value = 0
        self.progress_bar.setValue(self._bounce_value)

    def start_indexing(self):
        self.run_ffprobe_direct()

    def run_ffprobe_direct(self):
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-skip_frame", "nokey",
            "-show_entries", "frame=pts_time,pict_type,key_frame",
            "-of", "csv=p=0",
            self.video_path
        ]
        print("[DEBUG] ffprobe cmd:", cmd)

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_stdout)
        self.process.finished.connect(self._on_process_finished)

        os.makedirs(os.path.dirname(self.output_csv), exist_ok=True)
        self._outfile = open(self.output_csv, "w", encoding="utf-8")

        self.process.setProgram(cmd[0])
        self.process.setArguments(cmd[1:])
        self.process.start()

        if not self.process.waitForStarted(-1):
            QMessageBox.critical(self, "Fehler", f"Konnte ffprobe nicht starten:\n{cmd}")
            self.reject()

    def _on_process_stdout(self):
        if not self.process:
            return
        data = self.process.readAllStandardOutput().data().decode("utf-8", "replace")
        if data:
            lines = data.split("\n")
            for line in lines:
                line = line.strip()
                if line:
                    self._line_count += 1
                    self._outfile.write(line + "\n")
            self._outfile.flush()
            self.label_linecount.setText(f"Read Keyframe: {self._line_count}")

    def _on_process_finished(self, exit_code, exit_status):
        self._bounce_timer.stop()
        self.progress_bar.setValue(100)

        if self._outfile:
            self._outfile.close()
            self._outfile = None

        if exit_code != 0:
            QMessageBox.warning(self, "Indexing Error", "Extract step failed.")
            self.reject()
            return

        print("[DEBUG] ffprobe fertig => CSV:", self.output_csv)
        self.indexing_extracted.emit(self.video_path, os.path.dirname(self.output_csv))
        self.accept()

    def on_cancel(self):
        if self.process and self.process.state() == QProcess.Running:
            self.process.kill()
        self._bounce_timer.stop()
        if self._outfile:
            self._outfile.close()
            self._outfile = None
        self.reject()


class _SafeExportDialog(QDialog):
    export_finished = Signal(str)
    export_canceled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exporting Video – This may take a while…")
        self.setModal(True)
        self.setMinimumWidth(500)

        
        layout = QVBoxLayout(self)
        self.label_info = QLabel("Please wait while segments are being cut…")
        layout.addWidget(self.label_info)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.text_log = QTextEdit(self)
        self.text_log.setReadOnly(True)
        layout.addWidget(self.text_log)

        row_btn = QHBoxLayout()
        row_btn.addStretch()
        self.btn_cancel = QPushButton("Cancel", self)
        self.btn_cancel.clicked.connect(self._on_cancel)
        row_btn.addWidget(self.btn_cancel)
        layout.addLayout(row_btn)

        
        self._bounce_timer = QTimer(self)
        self._bounce_timer.timeout.connect(self._on_bounce)
        self._bounce_value = 0
        self._bounce_timer.start(100)

        self._process = QProcess(self)
        self._process.finished.connect(self._on_process_finished)
        self._process.readyReadStandardError.connect(self._on_read_stderr)
        self._process.readyReadStandardOutput.connect(self._on_read_stdout)
        self._commands = []
        self._current_index = 0
        self._concat_cmd = None
        self._out_file = None
        self._cancel_requested = False

    def set_commands(self, commands_list: list, concat_cmd: list, out_file: str):
        self._commands = commands_list
        self._concat_cmd = concat_cmd
        self._out_file = out_file

    def start_export(self):
        if not self._commands:
            self._start_concat()
            return
        self._run_next_command()

    def _run_next_command(self):
        if self._cancel_requested:
            return
        if self._current_index >= len(self._commands):
            self._start_concat()
            return
        cmd = self._commands[self._current_index]
        self._append_text(f"Cut Segment #{self._current_index+1}: {cmd}")
        self._process.setProgram(cmd[0])
        self._process.setArguments(cmd[1:])
        self._process.start()

    def _on_process_finished(self, exit_code, exit_status):
        if self._cancel_requested:
            return
        if exit_code != 0:
            self._append_text("Error while processing segment!")
            
            QMessageBox.critical(self, "Error", "A segment failed.")
            self.reject()
            return
        self._append_text(f"Segment #{self._current_index+1} done!\n")
        self._current_index += 1
        self._run_next_command()

    def _start_concat(self):
        if self._cancel_requested:
            return
        if not self._concat_cmd:
            self._finish_up()
            return
        self._append_text("All segments done! Now concatenating…")
        self._process.setProgram(self._concat_cmd[0])
        self._process.setArguments(self._concat_cmd[1:])
        self._process.finished.disconnect(self._on_process_finished)
        self._process.finished.connect(self._on_concat_finished)
        self._process.start()

    def _on_concat_finished(self, exit_code, exit_status):
        if exit_code != 0:
            self._append_text("Concat failed.")
            QMessageBox.critical(self, "Error", "Concat step failed.")
            self.reject()
            return
        self._finish_up()

    def _finish_up(self):
        self._append_text("Export finished successfully!")
        QMessageBox.information(self, "Done", "Video exported successfully!")
        self._clear_segments()
        self.accept()

    def _clear_segments(self):
        
        e = "done"
        if os.path.exists(MY_GLOBAL_TMP_DIR):
            try:
                shutil.rmtree(MY_GLOBAL_TMP_DIR)
                print("[DEBUF] Temp deleted", e)
            except Exception as err:
                print("[WARN]", err)
                e = err
        os.makedirs(MY_GLOBAL_TMP_DIR, exist_ok=True)

    def _append_text(self, txt):
        self.text_log.append(txt)

    def _on_read_stderr(self):
        data = self._process.readAllStandardError().data().decode("utf-8", "replace")
        if data:
            self._append_text(data.strip())

    def _on_read_stdout(self):
        data = self._process.readAllStandardOutput().data().decode("utf-8", "replace")
        if data:
            self._append_text(data.strip())

    def _on_bounce(self):
        self._bounce_value = (self._bounce_value + 2) % 100
        self.progress_bar.setValue(self._bounce_value)

    def _on_cancel(self):
        self._append_text("User canceled export.")
        self._cancel_requested = True
        if self._process.state() == 2:
        #if self._process.state() == self._process.Running:
            self._process.kill()
            
        self.export_canceled.emit()
        self.reject()

class DetachDialog(QDialog):
    requestPlus = Signal()
    requestMinus = Signal()
    requestReattach = Signal()

    def keyPressEvent(self, event):
        key = event.key()
        txt = event.text()
        if key == Qt.Key_Plus or txt == '+':
            self.requestPlus.emit()
            event.accept()
        elif key == Qt.Key_Minus or txt == '-':
            self.requestMinus.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                self.requestReattach.emit()

    def closeEvent(self, event):
        self.requestReattach.emit()
        super().closeEvent(event)


