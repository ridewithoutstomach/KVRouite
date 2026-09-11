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

# views/disclaimer_dialog.py

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox, QScrollArea
)
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

# Was die Anwendung an Verbindungen aufbaut - Wortlaut fuer den erzwungenen
# Disclaimer und fuer "Help -> Privacy". Bewusst nur eine Stelle: sonst
# beschreiben die beiden Texte irgendwann verschiedene Programme.
#
# Der Inhalt ist gemessen, nicht angenommen (30.08.2026): vollstaendige
# Aufzaehlung aller ausgehenden Adressen in core/, managers/, views/, widgets/
# und map_page.html. Wer ihn aendert, misst vorher nach.
NETWORK_HTML = (
    "<b>Network use and data</b><br><br>"
    "KVRouite does not collect usage statistics. No information about you, "
    "your videos<br>or your routes is sent to the author of this program."
    "<br><br>"
    "Connections to other services are made only in these situations:"
    "<ul>"
    "<li><b>Map display.</b> While the map is shown, map tiles are loaded "
    "from OpenStreetMap (<code>tile.openstreetmap.org</code>). After you load "
    "a GPX file the map centres on your track, so the tile server can infer "
    "the area you are working in.</li>"
    "<li><b>Update check.</b> A few seconds after start, KVRouite asks "
    "<code>api.github.com</code> whether a newer release exists. Only the "
    "program version is sent. You can switch this off under "
    "<i>Help &rarr; Auto Check for Updates</i>.</li>"
    "<li><b>Optional map services.</b> Satellite imagery (MapTiler, Mapbox) "
    "and route calculation and elevation lookup (Mapbox) are contacted "
    "<b>only when you use them</b>, and only after you have entered your own "
    "API key. Route calculation and elevation lookup transmit the coordinates "
    "of the section of your track concerned. Your keys are stored on your "
    "computer and are sent only to the service they belong to.</li>"
    "</ul>"
    "Everything else - playing, cutting, rendering, and reading and writing "
    "GPX files -<br>happens entirely on your computer. No other connections "
    "are made.<br><br>"
    "See <a href='https://kvrouite.com/privacy.html'>kvrouite.com/privacy.html</a>."
)


class DisclaimerDialog(QDialog):
    """
    Zeigt einen Haftungsausschluss (Disclaimer) mit anklickbarem Link.
    Der User muss ein Häkchen setzen, dann wird OK aktiv.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Disclaimer – Important Notice")

        layout = QVBoxLayout(self)

        # (1) HTML-Text mit Link
        # Achtung: openExternalLinks=True alleine kann buggy sein,
        # deshalb setzen wir openExternalLinks=False und fangen linkActivated ab.
        
        disclaimer_html = (
            "<p><b>IMPORTANT NOTICE (GPLv3 Disclaimer):</b><br><br>"
            "This software is provided under the terms of the "
            "<a href='https://www.gnu.org/licenses/gpl-3.0.en.html'>GNU General Public License v3 (GPLv3)</a>. "
            "You may redistribute it and/or modify it under these terms.<br><br>"
    
            "<b>No Warranty:</b><br>"
            "THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW.<br> "
            "EXCEPT WHEN OTHERWISE STATED IN WRITING, THE COPYRIGHT HOLDERS AND/OR OTHER PARTIES<br> "
            "PROVIDE THE PROGRAM “AS IS” WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESSED OR IMPLIED,<br> "
            "INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS<br> "
            "FOR A PARTICULAR PURPOSE. THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM<br> "
            "IS WITH YOU. SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF ALL NECESSARY<br> "
            "SERVICING, REPAIR OR CORRECTION.<br><br>"
            
            "<b>Patent Encumbrance Notice:</b><br>"
            "Some codecs (e.g., x264, x265, AAC, MP3, AC-3, DTS) may be patent-encumbered<br> "
            "in certain jurisdictions.<br> "
            "It is the user's responsibility to ensure compliance with all applicable laws and regulations,<br> "
            "and to obtain any necessary patent licenses.<br><br>"
        
            "By clicking OK or using this software, you confirm that you have read and accept<br> "
            "these terms, including the GPLv3 License.<br><br>"
            
            "<b>Third-Party Libraries:</b><br>"
            "This application includes and distributes open-source libraries:<br>"
            "<ul>"
            "<li><b>Qt 6.11.2 with PySide6 and shiboken6</b> – LGPL-3.0-only – "
            "<a href='https://pyside.org'>pyside.org</a></li>"
            "<li><b>OpenLayers 7.3.0</b> \u2013 BSD-2-Clause \u2013 "
            "<a href='https://openlayers.org'>openlayers.org</a></li>"
            "<li><b>CPython %d.%d</b> (PSF), <b>OpenSSL 3</b> (Apache-2.0), "
            % (sys.version_info.major, sys.version_info.minor) +
            "<b>Pillow</b> (MIT-CMU), <b>fitparse</b> (MIT)</li>"
            "<li><b>GStreamer 1.28.6, incl. GStreamer Editing Services (GES) "
            "and PyGObject</b> – LGPL-2.1-or-later; the bundled x264 and x265 "
            "encoder plugins are GPL-2.0-or-later – "
            "<a href='https://gstreamer.freedesktop.org'>gstreamer.freedesktop.org</a></li>"
            "<li><b>Voice remover</b> (since 7.0) – "
            "<a href='https://github.com/nomadkaraoke/python-audio-separator'>python-audio-separator</a> "
            "(MIT) with PyTorch (BSD-3-Clause), ONNX Runtime (MIT), NumPy, SciPy, "
            "scikit-learn, librosa, numba, torchvision and further packages "
            "(BSD, MIT, ISC, Apache-2.0, MPL-2.0); libsndfile and libsoxr among "
            "them are LGPL-2.1-or-later and replaceable shared libraries. "
            "Separation models: MDX-Net trained by the "
            "<a href='https://github.com/Anjok07/ultimatevocalremovergui'>Ultimate "
            "Vocal Remover (UVR)</a> team (Anjok07, aufr33; MIT) and Demucs v4 by "
            "Meta (MIT); architecture code from Meta, tsurumeso, kuielab and "
            "ZFTurbo (all MIT). Speech detection uses Silero VAD (Silero Team, "
            "MIT). Not shipped: diffq-fixed (CC BY-NC 4.0), replaced by a GPL "
            "stand-in. List and texts in "
            "<code>_internal/third-party-licenses/voice</code></li>"
            "<li><b>Traffic damper</b> (since 7.0) – KVRouite's own code; the "
            "method follows Kinotomo Audio by Alain Côté "
            "(benilerouge.org, MIT), no code taken, named as a courtesy</li>"
            "</ul>"
            "The GStreamer bundle also contains the FFmpeg 7.1 shared libraries "
            "(LGPL build)<br>used by its gst-libav plugin – see "
            "<code>COMPONENTS.txt</code>.<br><br>"
            "GStreamer is what plays, cuts and renders video in KVRouite, so it is "
            "always loaded.<br>"
            "On Linux, GStreamer is not distributed with KVRouite at all – it is "
            "installed<br>from your distribution's own packages.<br><br>"
            "Copy mode additionally calls the <b>ffmpeg</b> and <b>ffprobe</b> "
            "programs. Those are <b>not</b><br>part of this distribution – "
            "KVRouite uses whatever is installed on your system,<br>"
            "and copy mode stays disabled without them.<br><br>"
            "The Qt libraries are ordinary DLL files in "
            "<code>_internal/PySide6</code> – you may<br>replace them with a "
            "compatible build of your own, as the LGPL provides for.<br><br>"
            "Full license texts are located in <code>_internal/gstreamer</code>, "
            "<code>_internal/qt</code><br>and "
            "<code>_internal/third-party-licenses</code>.<br>"
            "The GStreamer binaries are the GStreamer Project's own, passed on<br>"
            "unchanged; their source is published by that project at "
            "<a href='https://gstreamer.freedesktop.org/src/'>gstreamer.freedesktop.org/src</a><br>"
            "in the same version - see <code>_internal/gstreamer/CORRESPONDING-SOURCE.txt</code>.<br>"
            "KVRouite compiles none of these binaries. If one of those links "
            "ever stops<br>working, write to "
            "<a href='mailto:bernd@kvrouite.com'>bernd@kvrouite.com</a> and you "
            "will be pointed at a<br>working source for the version you "
            "received.<br><br>"
            
            
            "</p>"
            "<p>" + NETWORK_HTML + "</p>"
)


        self.label_info = QLabel()
        self.label_info.setTextFormat(Qt.RichText)
        self.label_info.setOpenExternalLinks(False)  # Wir handeln das selbst
        self.label_info.setTextInteractionFlags(Qt.TextBrowserInteraction | Qt.LinksAccessibleByMouse)
        self.label_info.setText(disclaimer_html)
        self.label_info.setWordWrap(True)

        bereich = QScrollArea(self)
        bereich.setWidget(self.label_info)
        bereich.setWidgetResizable(True)
        bereich.setMinimumSize(700, 520)
        layout.addWidget(bereich)

        # (2) Signal abfangen ⇒ Linkklick
        self.label_info.linkActivated.connect(self._on_link_clicked)

        # (3) CheckBox - erst anklickbar, wenn der Text bis unten gerollt
        # wurde (Berns Wunsch vom 10.09.2026, wie bei anderen Programmen
        # ueblich). Passt der Text ohne Rollen ins Fenster, ist er sofort
        # frei. Beides entscheidet der Rollbalken: rangeChanged kommt, sobald
        # die Hoehe des Textes bekannt ist, valueChanged beim Rollen.
        self.chkConfirm = QCheckBox("I confirm I have read and accept these terms.", self)
        self.chkConfirm.setEnabled(False)
        self.chkConfirm.setToolTip("Scroll to the end of the text first.")
        layout.addWidget(self.chkConfirm)
        self._rollbalken = bereich.verticalScrollBar()
        self._rollbalken.valueChanged.connect(self._gelesen_pruefen)
        self._rollbalken.rangeChanged.connect(self._gelesen_pruefen)

        # (4) ButtonBox => OK / Cancel
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        layout.addWidget(btn_box)

        self.btn_ok = btn_box.button(QDialogButtonBox.Ok)
        self.btn_ok.setEnabled(False)

        self.chkConfirm.stateChanged.connect(self.on_checkbox_changed)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

    def on_checkbox_changed(self, state):
        self.btn_ok.setEnabled(self.chkConfirm.isChecked())

    def _gelesen_pruefen(self, *_args):
        """Unten angekommen (oder nichts zu rollen)? Dann den Haken freigeben.
        Einmal frei bleibt frei - wer zurueckrollt, muss nicht noch einmal."""
        if self.chkConfirm.isEnabled():
            return
        if self._rollbalken.value() >= self._rollbalken.maximum():
            self.chkConfirm.setEnabled(True)
            self.chkConfirm.setToolTip("")

    def _on_link_clicked(self, url: str):
        """
        Wird aufgerufen, wenn der User auf den HTML-Link klickt.
        Öffnet die URL im Standardbrowser.
        """
        QDesktopServices.openUrl(QUrl(url))
