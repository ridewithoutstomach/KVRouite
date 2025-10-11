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

# widgets/mini_chart_widget.py

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont

class MiniChartWidget(QWidget):
    """
    Zeigt eine Mini-Chart von maximal 30 GPX-Punkten.
    Hat einen festen Marker bei ca. 70% (x=0.7 * width).
    'darunter' läuft die Kurve, damit immer der aktuelle GPX-Punkt 
    an dieser Marker-Linie auftaucht. 

    Unten am Marker wird der "Slope" (Steigung) des aktuellen Punkts 
    als Text dargestellt.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)

        # Ggf. Hintergrund wie Timeline => #333333
        self.setStyleSheet("background-color: #444444 ;")

        # Interne Daten
        self._gpx_data = []
        self._max_points = 30   # Standard: 30 Gpx-Punkte anzeigen
        self._marker_ratio_x = 0.7  # 70% vom Widget
        self._current_index = 0     # Welcher Punkt ist 'aktuell'?

    def set_max_points(self, num: int):
        """Erlaubt es dir, die max. Anzahl von GPX-Punkten (30) zu ändern."""
        self._max_points = max(1, num)
        self.update()

    def set_gpx_data(self, data: list):
        """
        data: Liste von Dicts, z.B. [{'lat':..., 'lon':..., 'ele':..., 
                                     'speed_kmh':..., 'gradient':..., ...}, ...]
        Wir schneiden uns max. _max_points 'vor' dem aktuellen Index heraus 
        und ein paar 'danach', damit die Kurve "scrollt".
        """
        self._gpx_data = data or []
        self.update()

    def set_current_index(self, idx: int):
        """Setzt den Index des 'aktuellen' GPX-Punkts."""
        if idx < 0:
            idx = 0
        if idx >= len(self._gpx_data):
            idx = len(self._gpx_data) - 1
        self._current_index = idx
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._gpx_data:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        painter.fillRect(self.rect(), QColor("#333333"))
        
        rect_ = self.rect()
        w = rect_.width()
        h = rect_.height()

        # 1) Berechne, welche GPX-Punkte wir anzeigen (Fenster um current_index).
        N = len(self._gpx_data)
        if N < 1:
            return

        c_idx = self._current_index
        half_window = self._max_points // 2
        start_i = c_idx - half_window
        end_i   = c_idx + half_window
        if self._max_points % 2 == 0:
            end_i -= 1

        if start_i < 0:
            start_i = 0
        if end_i >= N:
            end_i = N - 1

        # Extrahiere Teilbereich
        relevant_points = self._gpx_data[start_i : end_i+1]
        count_window = len(relevant_points)
        if count_window < 2:
            return

        # Index des c_idx in relevant_points:
        local_idx = c_idx - start_i

        # x-Positionen definieren wir in [0..1], 
        # so dass local_idx => x = self._marker_ratio_x
        step = 1.0 / max(1, (count_window - 1))
        offset_in_data = local_idx * step
        shift_x = self._marker_ratio_x - offset_in_data

        # WICHTIG: Wir verwenden die Höhendaten (ele) für eine natürliche Darstellung
        # statt der Steigung (gradient)
        elevations = [p.get("ele", 0.0) for p in relevant_points]
        
        if not elevations:
            return
            
        min_ele = min(elevations)
        max_ele = max(elevations)
        
        # Vermeide Division durch Null
        if abs(max_ele - min_ele) < 0.1:
            max_ele = min_ele + 10.0  # 10 Meter Puffer bei flachen Strecken

        pts_screen = []
        for i, p in enumerate(relevant_points):
            x_data = i*step + shift_x
            ele = p.get("ele", 0.0)
            
            # Y-Berechnung basierend auf Höhe
            # Höhere Punkte weiter oben, niedrigere weiter unten
            frac = (ele - min_ele) / (max_ele - min_ele)
            y_pix = h - 10 - (frac * (h - 20))  # 10px Rand oben und unten
            
            x_pix = x_data * w
            pts_screen.append((x_pix, y_pix))

        # Zeichne die Höhenlinie
        pen_line = QPen(QColor("#00cccc"), 2)
        painter.setPen(pen_line)
        for i in range(len(pts_screen)-1):
            (x1, y1) = pts_screen[i]
            (x2, y2) = pts_screen[i+1]
            painter.drawLine(x1, y1, x2, y2)

        # Zeichne Punkte
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#cccccc"))
        for (xx, yy) in pts_screen:
            painter.drawEllipse(int(xx)-1, int(yy)-1, 4, 4)

        # Zeichne Marker-Linie
        x_marker = int(self._marker_ratio_x * w)
        pen_marker = QPen(QColor("white"), 2)
        painter.setPen(pen_marker)
        painter.drawLine(x_marker, 0, x_marker, h)

        # Zeichne aktuellen Punkt und Steigungswert
        if 0 <= local_idx < len(pts_screen):
            xP, yP = pts_screen[local_idx]
            painter.setBrush(QColor("#ffff00"))
            painter.drawEllipse(int(xP)-3, int(yP)-3, 6, 6)

            # Steigung und Höhe als Text anzeigen
            slope_val = relevant_points[local_idx].get("gradient", 0.0)
            ele_val = relevant_points[local_idx].get("ele", 0.0)
            
            # Kombinierte Anzeige: Steigung und Höhe
            #info_str = f"{slope_val:.1f}% / {ele_val:.0f}m"
            info_str = f"{slope_val:.1f}%"
            
            
            painter.setPen(QColor("#ffffff"))
            font_ = QFont()
            font_.setPointSize(10)
            painter.setFont(font_)

            text_w = painter.fontMetrics().horizontalAdvance(info_str)
            
            # Dynamische Positionierung basierend auf der Y-Position des aktuellen Punkts
            # Wenn der Punkt in der oberen Hälfte ist, zeige Text unten, sonst oben
            if yP < h / 2:
                # Punkt oben -> Text unten anzeigen
                text_y = h - 5
            else:
                # Punkt unten -> Text oben anzeigen
                text_y = 15
                
            painter.drawText(x_marker - text_w//2, text_y, info_str)