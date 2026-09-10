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

# views/audio_setup_seite.py
"""
Die Seite "Audio" im Encoder Setup (ab 7.0).

Bis 6.14 gab der Encode-Mode keinen Ton aus. Hier steht der Schalter, der
die Tonspur in den Export bringt, und ihre Bitrate. Die Seite ist als
eigenes Widget angelegt, damit spaetere Werkzeuge fuer den Ton - eine
Lautstaerke, ein Filter gegen Verkehrslaerm, eine Trennung von Musik und
Umgebung - hier dazukommen, ohne den Dialog umzubauen: jedes bekommt seine
Gruppe auf dieser Seite und seine Schluessel in core/encoder_presets.FELDER.

Die Werte gehen denselben Weg wie die der Videoseite: werte() liefert sie in
der Schreibweise von "encoder/", setzen() nimmt sie so entgegen. Gespeichert
und in Presets abgelegt werden sie vom Dialog.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QCheckBox, QSpinBox, QLabel
)

#: Grenzen der AAC-Bitrate in kbit/s. voaacenc nimmt bis 320 an; darunter
#: wird bei 48 kHz Stereo hoerbar gespart.
KBPS_MIN = 32
KBPS_MAX = 320
KBPS_VORGABE = 128


class AudioSeite(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        aussen = QVBoxLayout(self)

        # (A) Tonspur im Export
        gruppe = QGroupBox("Export", self)
        form = QFormLayout(gruppe)

        self.audio_check = QCheckBox("Audio track in the exported video", gruppe)
        self.audio_check.setToolTip(
            "Encode-Mode only. The sound of the source files goes into the "
            "output as AAC; crossfades fade the sound of both sides like the "
            "picture. Off: the video is exported without a sound track, as "
            "before 7.0. Copy-Mode always keeps the original sound.")
        form.addRow(self.audio_check)

        self.kbps_spin = QSpinBox(gruppe)
        self.kbps_spin.setRange(KBPS_MIN, KBPS_MAX)
        self.kbps_spin.setSingleStep(16)
        self.kbps_spin.setValue(KBPS_VORGABE)
        self.kbps_spin.setToolTip(
            "Bitrate of the AAC sound track. 128 kbit/s is the usual value "
            "for stereo; 192 or more for music.")
        form.addRow("Bitrate (kbit/s):", self.kbps_spin)
        aussen.addWidget(gruppe)

        # Platz fuer die naechsten Werkzeuge - siehe Modulkopf.
        hinweis = QLabel(
            "Further audio tools (volume, noise reduction) will appear on "
            "this page.", self)
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet("color: gray;")
        aussen.addWidget(hinweis)
        aussen.addStretch(1)

        self.audio_check.toggled.connect(self.kbps_spin.setEnabled)

    # ---------------------------
    # Werte in der Schreibweise von "encoder/"
    # ---------------------------
    def werte(self) -> dict:
        return {
            "audio": 1 if self.audio_check.isChecked() else 0,
            "audio_kbps": self.kbps_spin.value(),
        }

    def setzen(self, werte: dict):
        an = bool(int(werte.get("audio", 1)))
        self.audio_check.setChecked(an)
        self.kbps_spin.setEnabled(an)
        try:
            kbps = int(werte.get("audio_kbps", KBPS_VORGABE))
        except (TypeError, ValueError):
            kbps = KBPS_VORGABE
        self.kbps_spin.setValue(max(KBPS_MIN, min(KBPS_MAX, kbps)))
