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
die Tonspur in den Export bringt, und ihre Bitrate. Dazu die Gruppe
"Traffic": vorbeifahrende Fahrzeuge daempfen (core/verkehr), mit dem
Daempfer in dB als Regler. Die Seite ist als eigenes Widget angelegt, damit
spaetere Werkzeuge fuer den Ton - eine Lautstaerke, eine Trennung von
Stimme und Umgebung - hier dazukommen, ohne den Dialog umzubauen: jedes
bekommt seine Gruppe auf dieser Seite und seine Schluessel in
core/encoder_presets.FELDER.

Die Werte gehen denselben Weg wie die der Videoseite: werte() liefert sie in
der Schreibweise von "encoder/", setzen() nimmt sie so entgegen. Gespeichert
und in Presets abgelegt werden sie vom Dialog.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QGroupBox, QCheckBox, QSpinBox, QLabel,
    QComboBox
)

from core import stimme
from core import verkehr

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

        # (B) Verkehr daempfen - core/verkehr
        verkehr_gruppe = QGroupBox("Traffic", self)
        vform = QFormLayout(verkehr_gruppe)
        self.traffic_check = QCheckBox("Damp passing vehicles", verkehr_gruppe)
        self.traffic_check.setToolTip(
            "Scans the sound track of every source file once (cached) for "
            "passing cars and motorbikes: stretches that rise clearly above "
            "the ride noise. Each one is pulled down by up to the damper "
            "value and filled with nearby ride noise, so the vehicle recedes "
            "while wind and tyres stay. Encode-Mode with audio only.")
        vform.addRow(self.traffic_check)
        self.traffic_spin = QSpinBox(verkehr_gruppe)
        self.traffic_spin.setRange(verkehr.DAEMPFER_MIN_DB, verkehr.DAEMPFER_MAX_DB)
        self.traffic_spin.setSingleStep(1)
        self.traffic_spin.setValue(verkehr.DAEMPFER_VORGABE_DB)
        self.traffic_spin.setToolTip(
            "How far a vehicle is pulled down at most. 6 dB: half as loud, "
            "12 dB: a quarter, 18 dB: an eighth. The deeper, the more the "
            "filled-in ride noise carries.")
        vform.addRow("Damper (dB):", self.traffic_spin)
        aussen.addWidget(verkehr_gruppe)

        # (C) Stimmen entfernen - core/stimme
        stimme_gruppe = QGroupBox("Voices", self)
        sform = QFormLayout(stimme_gruppe)
        self.voice_check = QCheckBox("Remove voices", stimme_gruppe)
        self.voice_check.setToolTip(
            "Runs a separation model over the sound track of every source "
            "file once (cached) and keeps everything but the voices. No "
            "marking needed: the model listens to the whole track. On the "
            "CPU this takes roughly as long as the audio lasts. "
            "Encode-Mode with audio only.")
        sform.addRow(self.voice_check)
        self.voice_combo = QComboBox(stimme_gruppe)
        for kennung, (_datei, name) in stimme.MODELLE.items():
            self.voice_combo.addItem(name, userData=kennung)
        self.voice_combo.setToolTip(
            "MDX-Net: the UVR model, removes the voice directly. Demucs v4: "
            "Meta's model, separates the voice and KVRouite subtracts it; "
            "measured to leave the ride noise more intact. Both are shipped "
            "with KVRouite.")
        sform.addRow("Model:", self.voice_combo)
        # Ohne Bibliothek oder Modelle bleibt die Gruppe grau und sagt warum -
        # sichtbar in der Gruppe, nicht nur im Tooltip: ein ausgegrauter
        # Schalter ohne Grund war am 10.09.2026 das Erste, was aufgefallen ist.
        self._voice_ok, grund = stimme.verfuegbar()
        if not self._voice_ok:
            self.voice_check.setToolTip("Voice removal is not available: " + grund)
            hinweis_voice = QLabel("Not available: " + grund, stimme_gruppe)
            hinweis_voice.setWordWrap(True)
            hinweis_voice.setStyleSheet("color: gray;")
            sform.addRow(hinweis_voice)
        aussen.addWidget(stimme_gruppe)

        # Platz fuer die naechsten Werkzeuge - siehe Modulkopf.
        hinweis = QLabel(
            "Further audio tools (volume) will appear on this page.", self)
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet("color: gray;")
        aussen.addWidget(hinweis)
        aussen.addStretch(1)

        self.audio_check.toggled.connect(self._audio_umgeschaltet)
        self.traffic_check.toggled.connect(self.traffic_spin.setEnabled)
        self.voice_check.toggled.connect(self.voice_combo.setEnabled)
        self._audio_umgeschaltet(self.audio_check.isChecked())

    def _audio_umgeschaltet(self, an):
        """Ohne Tonspur gibt es nichts zu daempfen und nichts zu entfernen -
        die Gruppen folgen dem Schalter, ihre Werte bleiben erhalten."""
        self.kbps_spin.setEnabled(an)
        self.traffic_check.setEnabled(an)
        self.traffic_spin.setEnabled(an and self.traffic_check.isChecked())
        voice = an and self._voice_ok
        self.voice_check.setEnabled(voice)
        self.voice_combo.setEnabled(voice and self.voice_check.isChecked())

    # ---------------------------
    # Werte in der Schreibweise von "encoder/"
    # ---------------------------
    def werte(self) -> dict:
        return {
            "audio": 1 if self.audio_check.isChecked() else 0,
            "audio_kbps": self.kbps_spin.value(),
            "traffic": 1 if self.traffic_check.isChecked() else 0,
            "traffic_db": self.traffic_spin.value(),
            "voice": 1 if self.voice_check.isChecked() else 0,
            "voice_model": self.voice_combo.currentData() or stimme.VORGABE,
        }

    @staticmethod
    def _zahl(werte, schluessel, vorgabe):
        try:
            return int(werte.get(schluessel, vorgabe))
        except (TypeError, ValueError):
            return vorgabe

    def setzen(self, werte: dict):
        an = bool(self._zahl(werte, "audio", 1))
        self.audio_check.setChecked(an)
        kbps = self._zahl(werte, "audio_kbps", KBPS_VORGABE)
        self.kbps_spin.setValue(max(KBPS_MIN, min(KBPS_MAX, kbps)))
        verkehr_an = bool(self._zahl(werte, "traffic", 0))
        self.traffic_check.setChecked(verkehr_an)
        db = self._zahl(werte, "traffic_db", verkehr.DAEMPFER_VORGABE_DB)
        self.traffic_spin.setValue(
            max(verkehr.DAEMPFER_MIN_DB, min(verkehr.DAEMPFER_MAX_DB, db)))
        self.voice_check.setChecked(bool(self._zahl(werte, "voice", 0)))
        index = self.voice_combo.findData(str(werte.get("voice_model", stimme.VORGABE)))
        self.voice_combo.setCurrentIndex(max(0, index))
        self._audio_umgeschaltet(an)
