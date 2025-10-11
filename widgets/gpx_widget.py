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

# widgets/gpx_widget.py

from PySide6.QtWidgets import QWidget, QVBoxLayout
from .gpx_list_widget import GPXListWidget

class GPXWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.gpx_list = GPXListWidget(self)
        layout.addWidget(self.gpx_list)

    def set_gpx_data(self, data):
        self.gpx_list.set_gpx_data(data)

    def highlight_video_time(self, current_s: float, is_playing: bool):
        self.gpx_list.highlight_video_time(current_s, is_playing)

    def get_closest_index_for_time(self, current_s: float) -> int:
        return self.gpx_list.get_closest_index_for_time(current_s)
        
    def set_video_playing(self, playing: bool):
        """ Delegiert an die Methode der gpx_list. """
        self.gpx_list.set_video_playing(playing)    

    def set_flag(self, index: int, color: str, size: int, label_text: str):
        """
        Weist JavaScript an, ein Flag an Punkt 'index' zu setzen,
        z.B. mit bestimmter Farbe und Label (B/E).
        """
        js_code = (
            f"setFlag({index}, '{color}', {size}, '{label_text}')"
        )
        self.view.page().runJavaScript(js_code)
        
    def remove_all_flags(self):
        """
        Weist JavaScript an, alle Flag-Icons zu entfernen.
        """
        js_code = "removeAllFlags();"
        self.view.page().runJavaScript(js_code)    