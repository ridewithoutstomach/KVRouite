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
    QDialog, QVBoxLayout, QLabel, QCheckBox, QDialogButtonBox
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

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
            "Some codecs (e.g., x265) may be patent-encumbered in certain jurisdictions.<br> "
            "It is the user's responsibility to ensure compliance with all applicable laws and regulations,<br> "
            "and to obtain any necessary patent licenses.<br><br>"
        
            "By clicking OK or using this software, you confirm that you have read and accept<br> "
            "these terms, including the GPLv3 License.<br><br>"
            
            "<b>Third-Party Libraries:</b><br>"
            "This application includes and distributes open-source libraries:<br>"
            "<ul>"
            "<li><b>FFmpeg (GPL build)</b> – <a href='https://ffmpeg.org'>ffmpeg.org</a></li>"
            "<li><b>mpv (GPL build)</b> – <a href='https://mpv.io'>mpv.io</a></li>"
            "</ul>"
            "Full license texts for these libraries are located in the <br>"
            "<code>_internal/ffmpeg</code> and <code>_internal/mpv</code> folders.<br>"
            "Corresponding source code for FFmpeg and mpv, as used in this distribution, is available at<br> "
            "<a href='http://KVRouite.casa-eller.de'>http://KVRouite.casa-eller.de</a>.<br><br>"
            
            
            "</p>"
)


        self.label_info = QLabel()
        self.label_info.setTextFormat(Qt.RichText)
        self.label_info.setOpenExternalLinks(False)  # Wir handeln das selbst
        self.label_info.setTextInteractionFlags(Qt.TextBrowserInteraction | Qt.LinksAccessibleByMouse)
        self.label_info.setText(disclaimer_html)
        layout.addWidget(self.label_info)

        # (2) Signal abfangen ⇒ Linkklick
        self.label_info.linkActivated.connect(self._on_link_clicked)

        # (3) CheckBox
        self.chkConfirm = QCheckBox("I confirm I have read and accept these terms.", self)
        layout.addWidget(self.chkConfirm)

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

    def _on_link_clicked(self, url: str):
        """
        Wird aufgerufen, wenn der User auf den HTML-Link klickt.
        Öffnet die URL im Standardbrowser.
        """
        QDesktopServices.openUrl(QUrl(url))
