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
    QHBoxLayout, QMessageBox, QTextEdit, QApplication, QComboBox, QFrame
    
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
            QMessageBox.critical(self, "Error", f"Could not start ffprobe:\n{cmd}")
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
        self._concat_file = None
        self._segment_files = []
        self._cancel_requested = False

    def set_commands(self, commands_list: list, concat_cmd: list, out_file: str,
                     concat_file: str = None, segment_files: list = None):
        self._commands = commands_list
        self._concat_cmd = concat_cmd
        self._out_file = out_file
        # Fuer die Laengenmessung vor dem Zusammenfuegen (siehe _write_concat_list).
        self._concat_file = concat_file
        self._segment_files = segment_files or []

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
        self._write_concat_list()
        if self._cancel_requested:
            return
        self._append_text("All segments done! Now concatenating…")
        self._process.setProgram(self._concat_cmd[0])
        self._process.setArguments(self._concat_cmd[1:])
        self._process.finished.disconnect(self._on_process_finished)
        self._process.finished.connect(self._on_concat_finished)
        self._process.start()

    def _write_concat_list(self):
        """
        Schreibt die Concat-Liste neu und haengt an jede Datei ihre TATSAECHLICHE
        Inhaltsdauer.

        Ohne diese Angabe nimmt der Concat-Demuxer die Container-Dauer des
        Segments. Die ist bei einem "-c copy"-Schnitt zu gross, weil ffmpeg beim
        Keyframe VOR der Schnittstelle beginnt und der Vorlauf mitzaehlt
        (gemessen: 96.096 s statt 95.195 s). Die naechste Datei wird dadurch um
        diese Differenz zu spaet angesetzt - im fertigen Video steht das Bild an
        der Naht 934 ms still. Genau der Ruckler beim Zusammenfuegen.

        Die Bilder selbst sind in beiden Faellen identisch, es geht
        ausschliesslich um die Zeitstempel.
        """
        if not self._concat_file or not self._segment_files:
            return
        from managers.encoder_manager import measure_real_duration_fast

        total = len(self._segment_files)
        self._append_text(f"Checking length of {total} segment(s)…")
        lines = []
        for i, seg in enumerate(self._segment_files, 1):
            if self._cancel_requested:
                return
            name = os.path.basename(seg)
            lines.append(f"file '{seg}'")
            real_dur = measure_real_duration_fast(seg)
            if real_dur:
                lines.append(f"duration {real_dur:.6f}")
                self._append_text(f"[{i}/{total}] {name}: {real_dur:.3f}s")
            else:
                self._append_text(f"[{i}/{total}] {name}: length not measurable, "
                                  f"using container value")
            QApplication.processEvents()
        try:
            with open(self._concat_file, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as err:
            # Die Liste vom Aufrufer steht noch - dann eben ohne Dauerangaben.
            self._append_text(f"Could not update concat list: {err}")

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


class PreviewPrepareDialog(QDialog):
    """
    Zeigt beim Laden eines Projekts, dass die Vorschau noch vorbereitet wird.

    Die Blenden werden vorgerendert (core/fade_cache.py). Bei grossen
    Quelldateien dauert das mehrere Sekunden. Ohne Fenster sieht der Benutzer
    in dieser Zeit harte Schnitte, haelt sie fuer einen Fehler - oder haelt die
    App fuer abgestuerzt. Deshalb wird hier blockierend angezeigt, was laeuft.
    """

    abgebrochen = Signal()

    def __init__(self, gesamt: int = 0, parent=None, titel: str = "Preparing preview…"):
        super().__init__(parent)
        self.setWindowTitle(titel)
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.label_info = QLabel(
            "Rendering the crossfades for the preview. "
            "This happens once per cut; afterwards it is reused.", self)
        self.label_info.setWordWrap(True)
        layout.addWidget(self.label_info)

        self.progress_bar = QProgressBar(self)
        if gesamt > 0:
            self.progress_bar.setRange(0, gesamt)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%v / %m")
        else:
            # Unbekannte Dauer: laufender Balken statt falscher Prozentzahl.
            self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.label_step = QLabel("", self)
        layout.addWidget(self.label_step)

        row = QHBoxLayout()
        row.addStretch()
        self.btn_cancel = QPushButton("Skip", self)
        self.btn_cancel.setToolTip(
            "Stop rendering. Cuts without a finished crossfade are shown as "
            "hard cuts until you change something.")
        self.btn_cancel.clicked.connect(self._on_cancel)
        row.addWidget(self.btn_cancel)
        layout.addLayout(row)

        if gesamt > 0:
            self.setzen(0, gesamt)

    def schritt(self, text: str):
        """Zeigt an, woran gerade gearbeitet wird."""
        self.label_step.setText(text)
        QApplication.processEvents()

    def setzen(self, fertig: int, gesamt: int):
        gesamt = max(1, gesamt)
        self.progress_bar.setRange(0, gesamt)
        self.progress_bar.setValue(min(fertig, gesamt))
        self.label_step.setText(f"Crossfade {min(fertig + 1, gesamt)} of {gesamt}")

    def _on_cancel(self):
        self.btn_cancel.setEnabled(False)
        self.label_step.setText("Stopping…")
        self.abgebrochen.emit()

    def closeEvent(self, event):
        # Das Fenster schliesst sich selbst, wenn alles fertig ist. Klickt der
        # Benutzer vorher auf X, zaehlt das wie "Skip".
        if self.btn_cancel.isEnabled():
            self.abgebrochen.emit()
        super().closeEvent(event)


class OutputFrameRateDialog(QDialog):
    """Zeigt nach dem Laden, mit welcher Bildrate exportiert wird.

    Die Rate wird aus der ersten Videodatei gelesen und vorgeschlagen - so
    machen es Schnittprogramme auch ("Projektrate aus dem ersten Clip").
    Stimmt die Ausgabe mit der Quelle ueberein,
    muss nichts umgerechnet werden: jedes Ausgabebild ist genau ein Quellbild,
    und Video und GPX-Spur bleiben auf die Millisekunde beieinander.

    Nur die Bildrate. Aufloesung, Container, Hardware, CRF, Preset, Bitrate und
    X-Fade bleiben unangetastet - das sind die Einstellungen des Anwenders.

    Das Fenster kommt bei jedem Laden. Damit man die eine Meldung, auf die es
    ankommt, nicht im gewohnten Bild uebersieht, sieht es bei unterschiedlichen
    Bildraten deutlich anders aus: roter Rahmen, grosse Ueberschrift, anderer
    Fenstertitel. Ein Hinweis im Kleingedruckten wuerde genau dann untergehen,
    wenn er gebraucht wird.
    """

    def __init__(self, quelle_text, auswahl_texte, aktuell_index,
                 warnung=None, warnung_details=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Frame rate mismatch" if warnung
                            else "Output frame rate")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        if warnung:
            kasten = QFrame()
            kasten.setFrameShape(QFrame.StyledPanel)
            kasten.setStyleSheet(
                "QFrame { border: 2px solid #c62828; border-radius: 6px;"
                " background: #fdecea; }"
                " QLabel { border: none; background: transparent; }")
            innen = QVBoxLayout(kasten)

            titel = QLabel("⚠  " + warnung)
            schrift = titel.font()
            schrift.setPointSize(max(12, schrift.pointSize() + 4))
            schrift.setBold(True)
            titel.setFont(schrift)
            titel.setStyleSheet("color: #b71c1c;")
            titel.setWordWrap(True)
            innen.addWidget(titel)

            if warnung_details:
                text = QLabel(warnung_details)
                text.setWordWrap(True)
                text.setStyleSheet("color: #7f1d1d;")
                innen.addWidget(text)

            layout.addWidget(kasten)

        kopf = QLabel(f"Your source material runs at <b>{quelle_text} fps</b>.")
        kopf.setTextFormat(Qt.RichText)
        layout.addWidget(kopf)

        info = QLabel(
            "The export is set to the same rate. That way every exported frame "
            "is exactly one source frame, and the video stays in step with the "
            "GPX track.\n\n"
            "You can pick a different rate - the video is then converted, which "
            "costs a little accuracy.")
        info.setWordWrap(True)
        layout.addWidget(info)

        zeile = QHBoxLayout()
        zeile.addWidget(QLabel("Output frame rate:"))
        self.combo = QComboBox()
        for text in auswahl_texte:
            self.combo.addItem(text)
        if 0 <= aktuell_index < len(auswahl_texte):
            self.combo.setCurrentIndex(aktuell_index)
        zeile.addWidget(self.combo)
        zeile.addStretch(1)
        layout.addLayout(zeile)

        fuss = QLabel("You can change this later under Config → Encoder Setup.")
        from core import theme
        fuss.setStyleSheet("color: %s;" % theme.farben()["text_grau"])
        layout.addWidget(fuss)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        knoepfe.addWidget(self.btn_ok)
        layout.addLayout(knoepfe)

    def gewaehlt(self):
        return self.combo.currentIndex()
