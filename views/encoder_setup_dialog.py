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
    QProgressDialog, QHBoxLayout, QInputDialog, QTabWidget, QWidget
)
from PySide6.QtCore import QSettings, Qt

from core import framerate
from core import encoder_presets
from views.audio_setup_seite import AudioSeite


# Hilfsfunktion: kurzer Test, ob ein FFmpeg-Encoder läuft

class EncoderSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Encoder Setup")

        self.settings = QSettings("KVRouite", "KVRouite")

        # Hier speichern wir das "fertig getestete" Set an HW-Encodern,
        # das wir via QSettings eingelesen haben (bzw. neu ermitteln).
        self._cached_detected_hw = None
        # Hardware, die update_hw_options() vorwaehlen soll, waehrend ein
        # gespeicherter Satz in die Felder kommt; sonst None.
        self._hw_gewuenscht = None

        main_layout = QVBoxLayout(self)

        # (0) Gespeicherte Saetze (core/encoder_presets). Die Auswahl fuellt
        # die Felder darunter; wirksam wird das erst mit OK, wie jede andere
        # Aenderung in diesem Fenster auch. "Save…" legt die Felder, wie sie
        # gerade stehen, unter einem Namen ab.
        preset_zeile = QHBoxLayout()
        preset_zeile.addWidget(QLabel("Preset:", self))
        self.vorlage_combo = QComboBox(self)
        self.vorlage_combo.setMinimumWidth(180)
        self.vorlage_combo.setToolTip(
            "Saved encoder settings. Choosing one fills in the fields "
            "below; OK makes them the active settings.")
        preset_zeile.addWidget(self.vorlage_combo, 1)
        self.btn_vorlage_speichern = QPushButton("Save…", self)
        self.btn_vorlage_speichern.setToolTip(
            "Store the fields below under a name.")
        preset_zeile.addWidget(self.btn_vorlage_speichern)
        self.btn_vorlage_loeschen = QPushButton("Delete", self)
        self.btn_vorlage_loeschen.setToolTip("Remove the chosen preset.")
        preset_zeile.addWidget(self.btn_vorlage_loeschen)
        main_layout.addLayout(preset_zeile)

        # Zwei Seiten (ab 7.0): "Video" mit den Feldern, die es seit jeher
        # gibt, und "Audio" (views/audio_setup_seite.py) fuer die Tonspur und
        # kommende Werkzeuge fuer den Ton. Preset-Zeile und Knoepfe gelten
        # fuer beide Seiten zusammen; ein Preset umfasst alle Felder.
        self.seiten = QTabWidget(self)
        main_layout.addWidget(self.seiten)

        video_seite = QWidget(self.seiten)
        form_layout = QFormLayout(video_seite)
        self.seiten.addTab(video_seite, "Video")

        self.audio_seite = AudioSeite(self.seiten)
        self.seiten.addTab(self.audio_seite, "Audio")

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

        # (F) FPS - Auswahl statt freier Eingabe.
        # Eine Bildrate ist ein Bruch: NTSC-Material laeuft mit 30000/1001,
        # nicht mit 29,97. In ein Zahlenfeld liesse sich das gar nicht
        # eintragen, und frei gewaehlte Raten haetten hier ohnehin keinen
        # Nutzen. Welche Werte angeboten werden, haengt an der Bildrate des
        # geladenen Materials (siehe core/framerate.auswahl); der Bruch steckt
        # als userData hinter dem angezeigten Text.
        self.fps_combo = QComboBox()
        form_layout.addRow("FPS:", self.fps_combo)

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

        # Die Liste der Saetze, mit dem vorgewaehlt, der den Feldern genau
        # entspricht. Erst jetzt verbinden: das Fuellen der Liste darf die
        # Felder nicht ueberschreiben.
        self._vorlagen_fuellen(encoder_presets.passender_name(self._felder_lesen()))
        self.vorlage_combo.currentIndexChanged.connect(self._on_vorlage_gewaehlt)
        self.btn_vorlage_speichern.clicked.connect(self._on_vorlage_speichern)
        self.btn_vorlage_loeschen.clicked.connect(self._on_vorlage_loeschen)

    # ---------------------------
    # Gespeicherte Saetze
    # ---------------------------
    def _vorlagen_fuellen(self, gewaehlt=None):
        """Liste neu aufbauen; erster Eintrag ist "keiner"."""
        self.vorlage_combo.blockSignals(True)
        try:
            self.vorlage_combo.clear()
            self.vorlage_combo.addItem("(none)", userData=None)
            for name in encoder_presets.namen():
                self.vorlage_combo.addItem(name, userData=name)
            index = self.vorlage_combo.findData(gewaehlt) if gewaehlt else 0
            self.vorlage_combo.setCurrentIndex(max(0, index))
        finally:
            self.vorlage_combo.blockSignals(False)
        self.btn_vorlage_loeschen.setEnabled(
            self.vorlage_combo.currentData() is not None)

    def _felder_lesen(self) -> dict:
        """Die Felder, wie sie gerade stehen - in der Schreibweise von "encoder/"."""
        w, h = self.resolution_combo.currentData()
        hw_ui = self.hw_combo.currentText()
        wert = self.fps_combo.currentData()
        werte = {
            "res_w": int(w),
            "res_h": int(h),
            "container": self.container_combo.currentText(),
            "hw": "none" if hw_ui == "CPU" else hw_ui,
            "crf": self.crf_spin.value(),
            "preset": self.preset_combo.currentText(),
            "fps": framerate.als_text(*wert) if wert else
                   self.settings.value("encoder/fps", "30", type=str),
            "xfade": self.xfade_spin.value(),
            "bitrate_mbps": self.bitrate_spin.value(),
        }
        werte.update(self.audio_seite.werte())
        return werte

    def _felder_setzen(self, werte: dict):
        """Alle Felder aus einem Satz fuellen.

        Die Reihenfolge ist nicht beliebig: die Aufloesung setzt ueber
        on_resolution_changed() die Bitrate auf ihren Vorgabewert, deshalb
        kommt die Bitrate danach. Der Container bestimmt, welche Hardware
        zur Wahl steht, deshalb kommt die Hardware ueber update_hw_options()
        nach dem Container - mit dem gewuenschten Wert statt dem aus den
        Einstellungen.
        """
        ziel = (int(werte.get("res_w", 1920)), int(werte.get("res_h", 1080)))
        for i, (wh, _label) in enumerate(self.resolution_options):
            if wh == ziel:
                self.resolution_combo.setCurrentIndex(i)
                break

        idx_c = self.container_combo.findText(str(werte.get("container", "x265")))
        self.container_combo.setCurrentIndex(max(0, idx_c))
        self._hw_gewuenscht = str(werte.get("hw", "none"))
        self.update_hw_options()
        self._hw_gewuenscht = None

        self.crf_spin.setValue(int(werte.get("crf", 20)))
        idx_p = self.preset_combo.findText(str(werte.get("preset", "fast")))
        self.preset_combo.setCurrentIndex(max(0, idx_p))

        gewuenscht = framerate.parsen(str(werte.get("fps", "30")))
        for i, wert in enumerate(self._fps_werte):
            if framerate.gleich(wert, gewuenscht):
                self.fps_combo.setCurrentIndex(i)
                break
        else:
            # Eine Rate, die zum geladenen Material nicht angeboten wird -
            # dazunehmen, damit der Satz vollstaendig ankommt.
            if gewuenscht:
                self._fps_werte.append(gewuenscht)
                self.fps_combo.addItem(framerate.anzeige(*gewuenscht),
                                       userData=gewuenscht)
                self.fps_combo.setCurrentIndex(self.fps_combo.count() - 1)

        self.xfade_spin.setValue(int(werte.get("xfade", 2)))
        self.bitrate_spin.setValue(int(werte.get("bitrate_mbps", 20)))
        self.audio_seite.setzen(werte)

    def _on_vorlage_gewaehlt(self, _index):
        name = self.vorlage_combo.currentData()
        self.btn_vorlage_loeschen.setEnabled(name is not None)
        if name is None:
            return
        werte = encoder_presets.laden(name)
        if werte is None:
            self._vorlagen_fuellen()
            return
        self._felder_setzen(werte)

    def _on_vorlage_speichern(self):
        vorschlag = self.vorlage_combo.currentData() or ""
        name, ok = QInputDialog.getText(
            self, "Save preset", "Name for these encoder settings:",
            text=vorschlag)
        if not ok:
            return
        name = encoder_presets.name_saeubern(name)
        if not name:
            QMessageBox.warning(self, "Save preset", "A preset needs a name.")
            return
        if name in encoder_presets.namen():
            antwort = QMessageBox.question(
                self, "Replace preset?",
                f"A preset named \"{name}\" exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if antwort != QMessageBox.Yes:
                return
        encoder_presets.speichern(name, self._felder_lesen())
        print(f"[ENCODER] Preset \"{name}\" gespeichert")
        self._vorlagen_fuellen(name)

    def _on_vorlage_loeschen(self):
        name = self.vorlage_combo.currentData()
        if name is None:
            return
        antwort = QMessageBox.question(
            self, "Delete preset?", f"Delete the preset \"{name}\"?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if antwort != QMessageBox.Yes:
            return
        encoder_presets.loeschen(name)
        print(f"[ENCODER] Preset \"{name}\" geloescht")
        # Die Felder bleiben, wie sie sind - nur der Name ist weg.
        self._vorlagen_fuellen()


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
        # "encoder/fps_source" schreibt das Hauptfenster beim Laden eines
        # Projekts: die Bildrate der ersten Videodatei. Daran haengt, welche
        # Werte ueberhaupt sinnvoll sind - NTSC-Raten nur bei NTSC-Material.
        quelle = framerate.parsen(
            self.settings.value("encoder/fps_source", "", type=str), None)
        aktuell = framerate.parsen(
            self.settings.value("encoder/fps", "30", type=str))
        self._fps_werte = framerate.auswahl(quelle, zusaetzlich=aktuell)
        self.fps_combo.clear()
        for wert in self._fps_werte:
            text = framerate.anzeige(*wert)
            if quelle and framerate.gleich(wert, quelle):
                text += "   (source)"
            self.fps_combo.addItem(text, userData=wert)
        for i, wert in enumerate(self._fps_werte):
            if framerate.gleich(wert, aktuell):
                self.fps_combo.setCurrentIndex(i)
                break

        # 6) Xfade
        xfade_val = self.settings.value("encoder/xfade", 2, type=int)
        self.xfade_spin.setValue(xfade_val)
        
        # 7) Bitrate (Standardwerte nach Auflösung)
        bitrate_val = self.settings.value("encoder/bitrate_mbps", None)
        if bitrate_val is None:
            bitrate_val = self._default_bitrate_for(stored_res)
        self.bitrate_spin.setValue(int(bitrate_val))

        # 7b) Seite "Audio" - als Zahlen abgelegt, siehe core/encoder_presets
        self.audio_seite.setzen({
            "audio": self.settings.value("encoder/audio", 1, type=int),
            "audio_kbps": self.settings.value("encoder/audio_kbps", 128, type=int),
            "traffic": self.settings.value("encoder/traffic", 0, type=int),
            "traffic_db": self.settings.value("encoder/traffic_db", 12, type=int),
        })

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
            # Was theoretisch da ist. GStreamer legt die Hersteller-Elemente
            # erst an, wenn beim Start eine passende Karte gefunden wurde -
            # der Beweis bleibt aber der Knopf "Detect HW", der wirklich
            # kodiert.
            from core.hardware_detect import list_hw_encoders_gst
            all_hw_encoders = list_hw_encoders_gst()

        # CPU sollte immer drin sein, falls nicht => hinzufügen
        if "CPU" not in all_hw_encoders:
            # man weiß nie, ob detect_available_hw_encoders "CPU" zurückgibt
            all_hw_encoders = set(all_hw_encoders)
            all_hw_encoders.add("CPU")

        # Filtern je Container
        if container == "x264":
            allowed = {"CPU", "nvidia_h264", "amd_h264", "intel_h264", "vaapi_h264"}
        else:
            allowed = {"CPU", "nvidia_hevc", "amd_hevc", "intel_hevc", "vaapi_hevc"}

        final_hw = all_hw_encoders.intersection(allowed)
        if not final_hw:
            final_hw = {"CPU"}

        self.hw_combo.clear()
        sorted_list = sorted(list(final_hw))
        for hw in sorted_list:
            self.hw_combo.addItem(hw)

        # Gucken, ob wir in QSettings einen vorhandenen Wert haben - oder
        # ob gerade ein gespeicherter Satz geladen wird (_felder_setzen).
        stored_hw = getattr(self, "_hw_gewuenscht", None)
        if stored_hw is None:
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
        testet die wichtigsten GPU-Encoder ueber GStreamer,
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
            "vaapi_h264":  "h264_vaapi",
            "vaapi_hevc":  "hevc_vaapi",
        }

        # Getestet wird wirklich, und zwar auf dem Weg des Exports: jeder
        # Encoder gibt ein halbe Sekunde in eine echte MP4-Datei aus, durch
        # dieselben Funktionen, die auch der Export benutzt. Nur so kann das
        # Setup nichts anbieten, was der Export nachher nicht kann.
        # Gemessen auf einem NVIDIA-Rechner am 03.09.2026: 1,10 s fuer alle
        # acht Kandidaten. Der frueher benutzte ffmpeg-Testlauf brauchte 6,90 s.
        from core.hardware_detect import detect_hw_encoders_gst

        working, protokoll = detect_hw_encoders_gst()
        for name, ok, grund in protokoll:
            print(f"[DETECT HW] {'ok  ' if ok else 'nein'} {name}"
                  + (f" - {grund}" if grund else ""))

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

        # fps - als Bruch ablegen ("30000/1001"), nicht als gerundete Zahl.
        wert = self.fps_combo.currentData()
        if wert:
            self.settings.setValue("encoder/fps", framerate.als_text(*wert))

        xfade_val = self.xfade_spin.value()
        if xfade_val < 1:
            QMessageBox.warning(self, "Invalid X-Fade", "The X-Fade must be >= 1 second.")
            return
        self.settings.setValue("encoder/xfade", xfade_val)
        self.settings.setValue("encoder/bitrate_mbps", self.bitrate_spin.value())

        # Seite "Audio"
        for schluessel, wert in self.audio_seite.werte().items():
            self.settings.setValue(f"encoder/{schluessel}", wert)

        self.accept()
