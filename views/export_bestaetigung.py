# -*- coding: utf-8 -*-
#
# This file is part of KVRouite.
#
# Copyright (C) 2026 by Bernd Eller
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

# views/export_bestaetigung.py
"""
Das Fenster vor dem Export im Encode-Mode (ab 7.0).

Bis 7.0 fragte der Export nur "Are you sure?". Seit die Seite Audio den
Verkehrsdaempfer und den Voice Remover hat, entscheidet ein Haken dort ueber
Minuten Rechenzeit, und man sah beim Klick auf Export nicht, was eingestellt
ist. Hier steht es auf einen Blick: die Encoder-Einstellungen, wie sie das
Setup gespeichert hat, und die drei Schalter der Tonspur zum direkten
Umschalten - Audio, Verkehr, Stimmen. Was hier umgeschaltet wird, wird in
die Einstellungen geschrieben, genau wie ein OK im Encoder Setup; die Seite
Audio zeigt danach dasselbe. Der Knopf "Encoder Setup..." oeffnet das
volle Setup, danach wird die Uebersicht neu gelesen.

Der Zeithinweis beim Voice Remover ist grob: auf der CPU dauert das Trennen
etwa so lang wie der Ton, dazu das Auslesen jeder Datei.
"""

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QGroupBox, QLabel, QCheckBox,
    QPushButton, QDialogButtonBox, QHBoxLayout
)

from core import encoder_presets
from core import framerate
from core import stimme


class ExportBestaetigung(QDialog):
    """Rueckgabe wie QDialog.exec(): Accepted heisst Export starten."""

    def __init__(self, parent=None, gesamt_sekunden=0.0, dateien=1):
        super().__init__(parent)
        self.setWindowTitle("Export - Encode-Mode")
        self.settings = QSettings("KVRouite", "KVRouite")
        self._gesamt = float(gesamt_sekunden or 0.0)
        self._dateien = max(1, int(dateien or 1))

        aussen = QVBoxLayout(self)
        hinweis = QLabel("The final video is created now; changes are no "
                         "longer possible afterwards. These are the settings "
                         "it will be encoded with:", self)
        hinweis.setWordWrap(True)
        aussen.addWidget(hinweis)

        # (A) Video - nur Anzeige
        self.video_gruppe = QGroupBox("Video", self)
        self.video_grid = QGridLayout(self.video_gruppe)
        self._video_labels = {}
        for zeile, (schluessel, name) in enumerate((
                ("res", "Resolution"), ("container", "Container"),
                ("hw", "Hardware"), ("crf", "CRF"), ("preset", "Preset"),
                ("bitrate_mbps", "Bitrate"), ("fps", "FPS"), ("xfade", "X-Fade"))):
            self.video_grid.addWidget(QLabel(name + ":", self.video_gruppe), zeile, 0)
            wert = QLabel("", self.video_gruppe)
            wert.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.video_grid.addWidget(wert, zeile, 1)
            self._video_labels[schluessel] = wert
        self.video_grid.setColumnStretch(1, 1)
        aussen.addWidget(self.video_gruppe)

        # (B) Audio - die drei Schalter
        audio_gruppe = QGroupBox("Audio", self)
        agrid = QGridLayout(audio_gruppe)
        self.audio_check = QCheckBox("Audio track", audio_gruppe)
        self.audio_info = QLabel("", audio_gruppe)
        self.traffic_check = QCheckBox("Damp passing vehicles", audio_gruppe)
        self.traffic_info = QLabel("", audio_gruppe)
        self.voice_check = QCheckBox("Remove voices", audio_gruppe)
        self.voice_info = QLabel("", audio_gruppe)
        for zeile, (check, info) in enumerate((
                (self.audio_check, self.audio_info),
                (self.traffic_check, self.traffic_info),
                (self.voice_check, self.voice_info))):
            info.setStyleSheet("color: gray;")
            info.setWordWrap(True)
            agrid.addWidget(check, zeile, 0)
            agrid.addWidget(info, zeile, 1)
        agrid.setColumnStretch(1, 1)
        aussen.addWidget(audio_gruppe)

        self._voice_ok, self._voice_grund = stimme.verfuegbar()

        # Knoepfe
        zeile = QHBoxLayout()
        self.btn_setup = QPushButton("Encoder Setup...", self)
        zeile.addWidget(self.btn_setup)
        zeile.addStretch(1)
        knoepfe = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        knoepfe.button(QDialogButtonBox.Ok).setText("Export")
        zeile.addWidget(knoepfe)
        aussen.addLayout(zeile)

        knoepfe.accepted.connect(self._on_export)
        knoepfe.rejected.connect(self.reject)
        self.btn_setup.clicked.connect(self._on_setup)
        self.audio_check.toggled.connect(self._schalter_nachziehen)
        self.traffic_check.toggled.connect(self._schalter_nachziehen)
        self.voice_check.toggled.connect(self._schalter_nachziehen)

        self.lesen()

    # ---------------------------
    def lesen(self):
        """Alles aus den Einstellungen in die Anzeige."""
        w = encoder_presets.aus_einstellungen()
        hw = str(w.get("hw", "none"))
        anzeige = {
            "res": f"{w.get('res_w')}x{w.get('res_h')}",
            "container": str(w.get("container", "")),
            "hw": "CPU" if hw in ("none", "", "CPU") else hw,
            "crf": str(w.get("crf", "")),
            "preset": str(w.get("preset", "")),
            "bitrate_mbps": f"{w.get('bitrate_mbps')} Mbit/s",
            # Die Rate liegt als Bruch in den Einstellungen ("30000/1001");
            # angezeigt wird sie wie im Encoder Setup ("29.97").
            "fps": framerate.anzeige(*framerate.parsen(str(w.get("fps", "30")))),
            "xfade": f"{w.get('xfade')} s",
        }
        for schluessel, label in self._video_labels.items():
            label.setText(anzeige.get(schluessel, ""))

        for check in (self.audio_check, self.traffic_check, self.voice_check):
            check.blockSignals(True)
        self.audio_check.setChecked(bool(int(w.get("audio", 1))))
        self.traffic_check.setChecked(bool(int(w.get("traffic", 0))))
        self.voice_check.setChecked(bool(int(w.get("voice", 0))) and self._voice_ok)
        for check in (self.audio_check, self.traffic_check, self.voice_check):
            check.blockSignals(False)
        self._modell = str(w.get("voice_model", stimme.VORGABE))
        self._kbps = w.get("audio_kbps", 128)
        self._daempfer = w.get("traffic_db", 12)
        self._schalter_nachziehen()

    def _schalter_nachziehen(self, *_a):
        audio = self.audio_check.isChecked()
        self.traffic_check.setEnabled(audio)
        self.voice_check.setEnabled(audio and self._voice_ok)
        self.audio_info.setText(f"AAC {self._kbps} kbit/s" if audio
                                else "no sound track, as before 7.0")
        minuten = self._gesamt / 60.0
        if not audio:
            self.traffic_info.setText("")
            self.voice_info.setText("")
            return
        if self.traffic_check.isChecked():
            self.traffic_info.setText(
                f"damper {self._daempfer} dB - scans each source file once "
                f"(reads the whole file, cached afterwards)")
        else:
            self.traffic_info.setText("off")
        if not self._voice_ok:
            self.voice_info.setText("not available: " + self._voice_grund)
        elif self.voice_check.isChecked():
            name = stimme.MODELLE.get(self._modell, (None, self._modell))[1]
            self.voice_info.setText(
                f"{name} - separates each source file once; on the CPU this "
                f"takes roughly as long as the audio lasts, here about "
                f"{minuten:.0f} min (cached afterwards)")
        else:
            self.voice_info.setText("off")

    def _on_setup(self):
        # Import hier, nicht am Modulkopf: encoder_setup_dialog wird vom
        # Hauptfenster geladen, und ein Kreis beim Import waere die Folge.
        from views.encoder_setup_dialog import EncoderSetupDialog
        dlg = EncoderSetupDialog(self)
        dlg.exec()
        self.lesen()

    def _on_export(self):
        """Die drei Schalter in die Einstellungen - wie ein OK im Setup."""
        self.settings.setValue("encoder/audio", 1 if self.audio_check.isChecked() else 0)
        self.settings.setValue("encoder/traffic", 1 if self.traffic_check.isChecked() else 0)
        self.settings.setValue("encoder/voice", 1 if self.voice_check.isChecked() else 0)
        self.accept()
