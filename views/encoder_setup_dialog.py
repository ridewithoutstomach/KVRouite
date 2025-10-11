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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with KVRouite.  If not, see <https://www.gnu.org/licenses/>.
#

import subprocess
import json

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDialogButtonBox,
    QLabel, QComboBox, QSpinBox, QPushButton, QMessageBox,
    QProgressDialog
)
from PySide6.QtCore import QSettings, Qt


# Hilfsfunktion: kurzer Test, ob ein FFmpeg-Encoder läuft
def can_encode_with(ffmpeg_enc_name, ffmpeg_path="ffmpeg", test_duration=0.5):
    """
    Versucht, ein kurzes Testvideo (test_duration Sek.) mit ffmpeg_enc_name zu encoden.
    Gibt True zurück, wenn ffmpeg normal beendet wird, sonst False.
    """
    try:
        cmd = [
            ffmpeg_path, "-hide_banner", "-y",
            "-f", "lavfi",
            "-i", "color=black:r=24:size=320x240",
            "-t", str(test_duration),
            "-c:v", ffmpeg_enc_name,
            "-an",
            "test_enc.mp4"
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except:
        return False


class EncoderSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Encoder Setup")

        self.settings = QSettings("KVRouite", "KVRouite")
        
        # Hier speichern wir das "fertig getestete" Set an HW-Encodern,
        # das wir via QSettings eingelesen haben (bzw. neu ermitteln).
        self._cached_detected_hw = None

        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        main_layout.addLayout(form_layout)

        # (A) Resolution
        self.resolution_combo = QComboBox()
        self.resolution_options = [
            ((640, 360),  "640x360 (SD)"),
            ((854, 480),  "854x480 (nHD)"),
            ((1280, 720), "1280x720 (HD)"),
            ((1920,1080), "1920x1080 (Full HD)"),
            ((2560,1440), "2560x1440 (QHD 2K)"),
            ((3840,2160), "3840x2160 (4K UHD)")
        ]
        for wh, label in self.resolution_options:
            self.resolution_combo.addItem(label, userData=wh)
        form_layout.addRow("Resolution:", self.resolution_combo)

        # (B) Container: x264 / x265
        self.container_combo = QComboBox()
        self.container_combo.addItem("x264")
        self.container_combo.addItem("x265")
        form_layout.addRow("Container:", self.container_combo)

        # (C) Hardware
        self.hw_combo = QComboBox()
        form_layout.addRow("Hardware:", self.hw_combo)

        # (D) CRF
        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(12, 50)
        form_layout.addRow("CRF (Quality):", self.crf_spin)

        # (E) Preset
        self.preset_combo = QComboBox()
        cpu_presets = ["ultrafast", "superfast", "veryfast", "faster",
                       "fast", "medium", "slow", "slower", "veryslow"]
        for p in cpu_presets:
            self.preset_combo.addItem(p)
        form_layout.addRow("Preset:", self.preset_combo)

        # (H) Bitrate (Mbit/s)
        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(1, 200)
        form_layout.addRow("Bitrate (Mbit/s):", self.bitrate_spin)

        # (F) FPS
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        form_layout.addRow("FPS:", self.fps_spin)

        # (G) Xfade
        self.xfade_spin = QSpinBox()
        self.xfade_spin.setRange(0, 30)
        form_layout.addRow("X-Fade (s):", self.xfade_spin)

        # Buttons (OK/Cancel + "Detect HW")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        main_layout.addWidget(btns, alignment=Qt.AlignRight)

        self.btn_detect_hw = QPushButton("Detect HW", self)
        main_layout.addWidget(self.btn_detect_hw, alignment=Qt.AlignLeft)

        # Connect-Signale (grundsätzlich)
        btns.accepted.connect(self.on_ok_clicked)
        btns.rejected.connect(self.reject)
        self.btn_detect_hw.clicked.connect(self.on_detect_hw_clicked)
        self.container_combo.currentIndexChanged.connect(self.update_hw_options)

        # Erst aus QSettings laden
        self.load_from_settings()
        # Dann HW-Combo aktualisieren
        self.update_hw_options()

        # ----- WICHTIG: Signale, die Widgets im Dialog live ändern, erst ganz am Ende verbinden.
        # Dadurch verhindern wir, dass Slots feuern bevor Widgets existieren.
        self.resolution_combo.currentIndexChanged.connect(self.on_resolution_changed)


    # ---------------------------
    # Neue / geordnete Hilfsfunktionen
    # ---------------------------
    def _default_bitrate_for(self, res_wh: tuple[int, int]) -> int:
        """Gibt die Default-Bitrate (Mbit/s) für eine Auflösung zurück."""
        mapping = {
            (640, 360): 2,
            (854, 480): 5,
            (1280, 720): 10,
            (1920, 1080): 20,
            (2560, 1440): 35,
            (3840, 2160): 50,
        }
        return mapping.get(res_wh, 20)

    def on_resolution_changed(self, _idx: int):
        """
        Slot: wird aufgerufen, wenn der User die Resolution im Dialog ändert.
        Setzt die Bitrate auf den Default-Wert für die gewählte Resolution.
        """
        # fallback: falls in einer geänderten Version die Spinbox anders heißt,
        # versuchen wir alternative Attribute (robust gegen Versions-Unterschiede)
        spin = getattr(self, "bitrate_spin", None) or getattr(self, "bitrate_mbps_spin", None)
        if spin is None:
            # Defensive: Spin nicht gefunden -> nichts tun (kein Crash)
            print("[WARN] Bitrate spinbox not found; skip auto-update.")
            return

        w, h = self.resolution_combo.currentData()
        default_bitrate = self._default_bitrate_for((w, h))

        # Blockiere Signale temporär, damit kein weiteres Feedback ausgelöst wird.
        spin.blockSignals(True)
        spin.setValue(default_bitrate)
        spin.blockSignals(False)


    # ---------------------------
    # load / save
    # ---------------------------
    def load_from_settings(self):
        """Liest QSettings und setzt die GUI-Felder."""

        # 1) Auflösung
        wdef = self.settings.value("encoder/res_w", 1920, type=int)
        hdef = self.settings.value("encoder/res_h", 1080, type=int)
        stored_res = (wdef, hdef)
        found_idx = 0
        for i, (wh, label) in enumerate(self.resolution_options):
            if wh == stored_res:
                found_idx = i
                break
        # setCurrentIndex hier: Signal NOT connected yet (wir verbinden es erst am Ende)
        self.resolution_combo.setCurrentIndex(found_idx)

        # 2) Container
        container_val = self.settings.value("encoder/container", "x265", type=str)
        idx_c = self.container_combo.findText(container_val)
        if idx_c < 0:
            idx_c = 0
        self.container_combo.setCurrentIndex(idx_c)

        # 3) CRF
        crf_val = self.settings.value("encoder/crf", 20, type=int)
        self.crf_spin.setValue(crf_val)

        # 4) Preset
        preset_val = self.settings.value("encoder/preset", "fast", type=str)
        idx_p = self.preset_combo.findText(preset_val)
        if idx_p < 0:
            idx_p = 0
        self.preset_combo.setCurrentIndex(idx_p)

        # 5) FPS
        fps_val = self.settings.value("encoder/fps", 30, type=int)
        self.fps_spin.setValue(fps_val)

        # 6) Xfade
        xfade_val = self.settings.value("encoder/xfade", 2, type=int)
        self.xfade_spin.setValue(xfade_val)
        
        # 7) Bitrate (Standardwerte nach Auflösung)
        bitrate_val = self.settings.value("encoder/bitrate_mbps", None)
        if bitrate_val is None:
            bitrate_val = self._default_bitrate_for(stored_res)
        self.bitrate_spin.setValue(int(bitrate_val))
        

        # 8) Detected HW laden (wenn vorhanden)
        hw_json = self.settings.value("encoder/detected_hw_list", "")
        if hw_json:
            try:
                # JSON -> Python set
                arr = json.loads(hw_json)
                self._cached_detected_hw = set(arr)
            except:
                self._cached_detected_hw = None


    # ---------------------------
    # Hardware detection / UI update
    # ---------------------------
    def update_hw_options(self):
        """
        Befüllt das hw_combo je nach Container (x264/x265) und:
        - Falls self._cached_detected_hw nicht None -> nur die Encoders daraus
        - CPU immer, falls nicht schon enthalten
        """
        container = self.container_combo.currentText()  # "x264" / "x265"

        if self._cached_detected_hw is not None:
            # Schon gemessen -> nur diese
            all_hw_encoders = self._cached_detected_hw
        else:
            # Noch nicht gemessen -> wir nehmen die "theoretisch" vorhandenen
            # => z.B. ffmpeg -encoders
            # Du hast in "core/hardware_detect" die Funktion detect_available_hw_encoders().
            from core.hardware_detect import detect_available_hw_encoders
            all_hw_encoders = detect_available_hw_encoders()  # => z.B. {"CPU","nvidia_h264","amd_h264",...}

        # CPU sollte immer drin sein, falls nicht => hinzufügen
        if "CPU" not in all_hw_encoders:
            # man weiß nie, ob detect_available_hw_encoders "CPU" zurückgibt
            all_hw_encoders = set(all_hw_encoders)
            all_hw_encoders.add("CPU")

        # Filtern je Container
        if container == "x264":
            allowed = {"CPU", "nvidia_h264", "amd_h264", "intel_h264"}
        else:
            allowed = {"CPU", "nvidia_hevc", "amd_hevc", "intel_hevc"}

        final_hw = all_hw_encoders.intersection(allowed)
        if not final_hw:
            final_hw = {"CPU"}

        self.hw_combo.clear()
        sorted_list = sorted(list(final_hw))
        for hw in sorted_list:
            self.hw_combo.addItem(hw)

        # Gucken, ob wir in QSettings einen vorhandenen Wert haben
        stored_hw = self.settings.value("encoder/hw", "CPU", type=str)
        # Falls "none" -> mappe auf "CPU"
        if stored_hw == "none":
            stored_hw = "CPU"

        idx_hw = self.hw_combo.findText(stored_hw)
        if idx_hw < 0:
            idx_hw = 0
        self.hw_combo.setCurrentIndex(idx_hw)


    def on_detect_hw_clicked(self):
        """
        Zeigt ein "Bitte warten..."-Fenster,
        testet die wichtigsten GPU-Encoder per can_encode_with(),
        speichert das Ergebnis in self._cached_detected_hw + QSettings,
        dann update_hw_options().
        """
        # 1) Warte-Dialog
        progress = QProgressDialog("Detecting hardware, please wait...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle("Please wait...")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        # 2) Test-liste: wir ignorieren libx264 / libx265
        possible_hw_encs = {
            "nvidia_h264": "h264_nvenc",
            "nvidia_hevc": "hevc_nvenc",
            "amd_h264":    "h264_amf",
            "amd_hevc":    "hevc_amf",
            "intel_h264":  "h264_qsv",
            "intel_hevc":  "hevc_qsv",
        }

        working = {"CPU"}  # CPU immer
        for label, ffenc in possible_hw_encs.items():
            # Falls der user das Dialog-Fenster schließt o.ä., brechen wir ab
            if progress.wasCanceled():
                break
            if can_encode_with(ffenc, test_duration=0.5):
                working.add(label)

        # 3) Schließen wir den Warte-Dialog
        progress.close()

        # 4) Speichern in self._cached_detected_hw
        self._cached_detected_hw = working

        # 5) Auch in QSettings => "encoder/detected_hw_list"
        arr_list = list(working)
        hw_json = json.dumps(arr_list)
        self.settings.setValue("encoder/detected_hw_list", hw_json)

        # 6) Info für den User
        QMessageBox.information(self, "Detect HW", f"Found working encoders:\n{', '.join(sorted(working))}")

        # 7) Combo aktualisieren
        self.update_hw_options()


    def on_ok_clicked(self):
        """Speichert die Werte in QSettings und schließt."""
        # resolution
        w,h = self.resolution_combo.currentData()
        self.settings.setValue("encoder/res_w", w)
        self.settings.setValue("encoder/res_h", h)

        # container
        container = self.container_combo.currentText()
        self.settings.setValue("encoder/container", container)

        # hardware => CPU => none
        hw_ui = self.hw_combo.currentText()
        hw_stored = "none" if (hw_ui == "CPU") else hw_ui
        self.settings.setValue("encoder/hw", hw_stored)

        # crf
        self.settings.setValue("encoder/crf", self.crf_spin.value())

        # preset
        preset = self.preset_combo.currentText()
        self.settings.setValue("encoder/preset", preset)

        # fps
        self.settings.setValue("encoder/fps", self.fps_spin.value())

        xfade_val = self.xfade_spin.value()
        if xfade_val < 1:
            QMessageBox.warning(self, "Invalid X-Fade", "The X-Fade must be >= 1 second.")
            return
        self.settings.setValue("encoder/xfade", xfade_val)
        self.settings.setValue("encoder/bitrate_mbps", self.bitrate_spin.value())

        self.accept()
