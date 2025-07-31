# -*- coding: utf-8 -*-
#
# This file is part of VGSync.
#
# Copyright (C) 2025 by Bernd Eller
#
# VGSync is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# VGSync is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with VGSync. If not, see <https://www.gnu.org/licenses/>.
#

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPoint, Signal, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QWheelEvent, QPolygonF
)
                           


class ChartWidget(QWidget):
    markerClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._gpx_data = []
        self._speed_cap = 70.0

        # Ausschnitt/Zoom
        self._zoom_factor = 1.0
        self._min_zoom = 1.0
        self._max_zoom = 50.0
        self._horizontal_offset = 0.0

        self._marker_index = 0

        # Dragging
        self._dragging_scroll = False
        self._drag_start_x = 0.0
        self._offset_start = 0.0

        # Chart-Layouts
        self._chart_height_top = 0.6
        self._chart_height_bottom = 0.3
        self._scroll_speed_px = 40

        # Neuer Schwellenwert (z.B. 1 km/h)
        self._zero_speed_threshold = 1.0
        
        
         # ---------------------------
        # **NEU**: Schwellenwert für Stops
        self._stop_threshold = 1.0   # z.B. Default 1 Sekunde

        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        
    def set_stop_threshold(self, value: float):
        self._stop_threshold = value
        self.update()  # Damit das Diagramm neu gezeichnet wird    
        

    # -----------------------------------------------------
    # Getter/Setter für die neue Zero-Speed-Einstellung
    # -----------------------------------------------------
    def set_zero_speed_threshold(self, threshold: float):
        """
        Legt den Geschwindigkeits-Schwellenwert fest.
        Werte darunter werden im Diagramm rot markiert.
        """
        self._zero_speed_threshold = threshold
        self.update()

    def zero_speed_threshold(self) -> float:
        return self._zero_speed_threshold

    # -----------------------------------------------------
    # Andere bekannte Setter
    # -----------------------------------------------------
    def set_speed_cap(self, new_limit: float):
        """Setzt das max. Speed-Limit und refresht."""
        self._speed_cap = new_limit
        self.update()

    def set_gpx_data(self, data):
        self._gpx_data = data if data else []
        self._marker_index = 0
        self._zoom_factor = 1.0
        self._horizontal_offset = 0.0
        self.update()

    def highlight_gpx_index(self, index: int):
        """Springt im Chart zum GPX-Punkt `index`."""
        if not self._gpx_data:
            return
        if index < 0:
            index = 0
        if index >= len(self._gpx_data):
            index = len(self._gpx_data) - 1
        self._marker_index = index
        self._keep_marker_visible()
        self.update()

    def _keep_marker_visible(self):
        """
        Verhindert, dass der Marker aus dem sichtbaren Bereich rutscht.
        Schiebt ggf. self._horizontal_offset so, dass der Marker x-Koordinate
        in ~80% des sichtbaren Bereichs bleibt.
        """
        count = len(self._gpx_data)
        if count <= 0:
            return

        w = self.width()
        chart_width = w * self._zoom_factor

        if count > 1:
            ratio = self._marker_index / (count - 1)
        else:
            ratio = 0.0

        marker_x = ratio * chart_width

        if marker_x < self._horizontal_offset:
            self._horizontal_offset = marker_x
        elif marker_x > self._horizontal_offset + (0.8 * w):
            self._horizontal_offset = marker_x - (0.8 * w)

        if self._horizontal_offset < 0:
            self._horizontal_offset = 0
        max_offset = chart_width - w
        if max_offset < 0:
            max_offset = 0
        if self._horizontal_offset > max_offset:
            self._horizontal_offset = max_offset

    # -----------------------------------------------------
    # Mouse/Scroll/Zoom
    # -----------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx = self._index_for_x(event.pos().x())
            self._marker_index = idx
            self.update()
            self.markerClicked.emit(idx)
            event.accept()
        elif event.button() == Qt.RightButton:
            self._dragging_scroll = True
            self._drag_start_x = event.pos().x()
            self._offset_start = self._horizontal_offset
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_scroll:
            delta_x = event.pos().x() - self._drag_start_x
            new_offset = self._offset_start - delta_x
            if new_offset < 0:
                new_offset = 0
            self._horizontal_offset = new_offset
            self.update()
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton and self._dragging_scroll:
            self._dragging_scroll = False
            event.accept()
        else:
            event.ignore()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        mods = event.modifiers()
        if (mods & Qt.ShiftModifier):
            # horizontal scroll
            if delta > 0:
                self._horizontal_offset = max(0, self._horizontal_offset - self._scroll_speed_px)
            else:
                self._horizontal_offset += self._scroll_speed_px
            self.update()
            event.accept()
            return

        if (mods & Qt.ControlModifier):
            # zoom
            factor = 1.1 if delta > 0 else (1.0 / 1.1)
            new_zoom = self._zoom_factor * factor
            if new_zoom < self._min_zoom:
                new_zoom = self._min_zoom
            if new_zoom > self._max_zoom:
                new_zoom = self._max_zoom

            old_zoom = self._zoom_factor
            self._zoom_factor = new_zoom
            self._center_marker(0.3)
            self.update()
            event.accept()
            return

        super().wheelEvent(event)

    def _center_marker(self, widget_ratio: float):
        count = len(self._gpx_data)
        if count < 2:
            return
        w = self.width()
        chart_width = w * self._zoom_factor
        ratio = self._marker_index / (count - 1)
        marker_x_abs = ratio * chart_width
        desired_x_in_widget = widget_ratio * w
        self._horizontal_offset = marker_x_abs - desired_x_in_widget
        if self._horizontal_offset < 0:
            self._horizontal_offset = 0

    # -----------------------------------------------------
    # Painting
    # -----------------------------------------------------
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
    
        rect_ = self.rect()
        w = rect_.width()
        h = rect_.height()
        painter.fillRect(rect_, QColor("#222222"))

        # ------------------------------------------------------
        # LEGENDE (oben links)
        # ------------------------------------------------------
        legend_x = 10
        legend_y = 20

        # SPEED
        painter.setPen(QPen(Qt.white, 1))
        painter.drawText(legend_x, legend_y, "Speed:")

        fm = painter.fontMetrics()
        speed_text_width = fm.horizontalAdvance("Speed:")
        line_start_x = legend_x + speed_text_width + 5
        line_start_y = legend_y - 5
        line_end_x = line_start_x + 30
        line_end_y = line_start_y

        # Speed-Legendenlinie (cyan, 3px)
        painter.setPen(QPen(QColor("cyan"), 3))
        painter.drawLine(line_start_x, line_start_y, line_end_x, line_end_y)

        # HEIGHT
        next_block_x = line_end_x + 20
        painter.setPen(QPen(Qt.white, 1))
        painter.drawText(next_block_x, legend_y, "Height:")
    
        height_text_width = fm.horizontalAdvance("Height:")
        height_line_start_x = next_block_x + height_text_width + 5
        height_line_start_y = legend_y - 5
        height_line_end_x = height_line_start_x + 30
        height_line_end_y = height_line_start_y
    
        # Height-Legendenlinie (yellow, 3px)
        painter.setPen(QPen(QColor("yellow"), 3))
        painter.drawLine(
            height_line_start_x,
            height_line_start_y,
            height_line_end_x,
            height_line_end_y
        )
    
        # ------------------------------------------------------
        # GPX-Daten prüfen
        # ------------------------------------------------------
        count = len(self._gpx_data)
        if count < 2:
            painter.setPen(QColor("white"))
            painter.drawText(10, 60, "No GPX data for chart.")
            return

        chart_width = w * self._zoom_factor
    
        # ------------------------------------------------------
        # ELE / SPEED ermitteln und skalieren
        # ------------------------------------------------------
        ele_vals = [pt.get("ele", 0.0) for pt in self._gpx_data]
    
        speed_vals = []
        for pt in self._gpx_data:
            raw_spd = pt.get("speed_kmh", 0.0)
            capped_spd = min(raw_spd, self._speed_cap)
            speed_vals.append(capped_spd)
    
        min_ele, max_ele = min(ele_vals), max(ele_vals)
        min_spd, max_spd = min(speed_vals), max(speed_vals)
    
        if abs(max_ele - min_ele) < 0.1:
            max_ele += 0.1
            min_ele -= 0.1
        if abs(max_spd - min_spd) < 0.1:
            max_spd += 0.1
            min_spd -= 0.1
    
        top_height = int(self._chart_height_top * h)
        bottom_height = int(self._chart_height_bottom * h)
    
        def x_for_index(i: int) -> float:
            ratio = i / (count - 1)
            return ratio * chart_width - self._horizontal_offset
    
        def y_for_ele(e: float) -> float:
            frac = (e - min_ele) / (max_ele - min_ele)
            return top_height - (frac * (top_height - 20))
    
        def y_for_speed(s: float) -> float:
            frac = (s - min_spd) / (max_spd - min_spd)
            speed_range = bottom_height - 20
            y0 = top_height + 10
            return y0 + (bottom_height - 20) - (frac * speed_range)
    
        # Pfade für Elevation/Speed
        path_ele = []
        path_spd = []
        for i in range(count):
            x_ = x_for_index(i)
            path_ele.append((x_, y_for_ele(ele_vals[i])))
            path_spd.append((x_, y_for_speed(speed_vals[i])))
    
        # ------------------------------------------------------
        # Linien zeichnen (Elevation = gelb, Speed = cyan)
        # ------------------------------------------------------
        def draw_polyline(painter, pts, color, thickness=2):
            painter.setPen(QPen(color, thickness))
            for idx in range(len(pts) - 1):
                x1, y1 = pts[idx]
                x2, y2 = pts[idx + 1]
                if (x1 < -50 and x2 < -50):
                    continue
                if (x1 > w + 50 and x2 > w + 50):
                    continue
                painter.drawLine(x1, y1, x2, y2)
    
        # 1) Elevation-Linie (gelb, 2px)
        draw_polyline(painter, path_ele, QColor(255, 255, 0), thickness=2)
    
        # 2) Speed-Linie (cyan, 1px)
        draw_polyline(painter, path_spd, QColor(0, 255, 255), thickness=1)
    
        # ------------------------------------------------------
        # Null-Linie (0 km/h) dünn weiß
        # ------------------------------------------------------
        painter.setPen(QPen(QColor("white"), 1))
        zero_speed_y = y_for_speed(0.0)
        painter.drawLine(0, zero_speed_y, w, zero_speed_y)
    
        # ------------------------------------------------------
        # Bereich für Geschwindigkeiten < zero_speed_threshold rot markieren
        # ------------------------------------------------------
        zst = self._zero_speed_threshold  # z.B. 1 km/h
        y_axis_speed = y_for_speed(0)     # x-Achse für Speed
    
        # Wir nutzen ein "Füll-Polygon" für jede zusammenhängende Unterschreitung.
        painter.setBrush(QColor(255, 0, 0, 100))  # halbtransparentes Rot
        painter.setPen(Qt.NoPen)
    
        sub_threshold_polygon = []
        in_segment = False
    
        for i in range(count):
            if i == 0:
                continue  # Ersten Punkt überspringen
            x_, y_ = path_spd[i]
            spd_ = speed_vals[i]
    
            # Unterhalb Schwelle?
            if spd_ < zst:
                # Segment anfangen, falls wir noch nicht "drin" sind
                if not in_segment:
                    sub_threshold_polygon.append((x_, y_axis_speed))
                    in_segment = True
                sub_threshold_polygon.append((x_, y_))
            else:
                # Falls wir gerade ein "rotes" Segment hatten, jetzt schließen
                if in_segment:
                    sub_threshold_polygon.append((x_, y_axis_speed))
                    # Zeichnen der Polygonfläche
                    poly = QPolygonF()
                    for (px, py) in sub_threshold_polygon:
                        poly.append(QPointF(px, py))
                    painter.drawPolygon(poly)
                    sub_threshold_polygon.clear()
                    in_segment = False
    
        # Falls Segment bis zum letzten Punkt offen
        if in_segment and len(sub_threshold_polygon) > 0:
            sub_threshold_polygon.append((path_spd[-1][0], y_axis_speed))
            poly = QPolygonF()
            for (px, py) in sub_threshold_polygon:
                poly.append(QPointF(px, py))
            painter.drawPolygon(poly)
    
        # ------------------------------------------------------
        # Rote Marker an der x-Achse für alle Punkte < zst
        # ------------------------------------------------------
        painter.setPen(QPen(QColor(255, 0, 0), 4))
        for i in range(count):
            if i == 0:
                continue
            x_, y_ = path_spd[i]
            spd_ = speed_vals[i]
            if spd_ < zst:
                # Kleiner senkrechter Strich nach unten (5px)
                painter.drawLine(x_, y_axis_speed, x_, y_axis_speed + 15)
    
        # ------------------------------------------------------
        # **NEU**: Blaue Marker für "Stops"
        # wenn Zeitdifferenz > self._stop_threshold
        # ------------------------------------------------------
        painter.setPen(QPen(QColor(255, 165, 0), 4))  # Blau, Dicke=2
        for i in range(1, count):
            # Zeitdifferenz zwischen Punkt i-1 und i:
            dt = (self._gpx_data[i]["time"] - self._gpx_data[i-1]["time"]).total_seconds() if self._gpx_data[i]["time"] else 0
            if dt > self._stop_threshold:
                # x_-Koordinate des Punktes i (bereits in path_spd gespeichert)
                x_ = path_spd[i][0]
                # Hier zeichnen wir einen Strich nach oben (15px) vom zero_speed_y:
                painter.drawLine(x_, zero_speed_y, x_, zero_speed_y + 15)
    
        # ------------------------------------------------------
        # Kreise auf den Datenpunkten (Elevation = gelb, Speed = cyan)
        # ------------------------------------------------------
        painter.setPen(Qt.NoPen)
    
        # Elevation-Kreise
        painter.setBrush(QBrush(QColor(255, 255, 0)))
        ele_radius = 1
        for (xx, yy) in path_ele:
            if -10 < xx < w + 10:
                painter.drawEllipse(QPointF(xx, yy), ele_radius, ele_radius)
    
        # Speed-Kreise
        painter.setBrush(QBrush(QColor(0, 255, 255)))
        speed_radius = 0.7
        for (xx, yy) in path_spd:
            if -10 < xx < w + 10:
                painter.drawEllipse(QPointF(xx, yy), speed_radius, speed_radius)
    
        # ------------------------------------------------------
        # Marker-Linie und Info-Texte
        # ------------------------------------------------------
        m_x = x_for_index(self._marker_index)
        if -50 < m_x < w + 50:
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(m_x, 0, m_x, h)
            pt_ = self._gpx_data[self._marker_index]
    
            ele_val = pt_['ele']
            spd_val = speed_vals[self._marker_index]  # gecappter Wert
            grad_val = pt_.get("gradient", 0.0)
    
            line1 = f"{ele_val:.1f}".replace(".", ",") + "m"
            line2 = f"{spd_val:.1f}".replace(".", ",") + "km/h"
            line3 = f"{grad_val:.1f}".replace(".", ",") + "%"
    
            y_start = 40
            y_step = 15
    
            painter.setPen(QPen(QColor("white"), 1))
            painter.drawText(m_x + 5, y_start, line1)
            painter.drawText(m_x + 5, y_start + y_step, line2)
            painter.drawText(m_x + 5, y_start + 2 * y_step, line3)
    
                
     

    # -----------------------------------------------------
    # Hilfsfunktion: x->Index
    # -----------------------------------------------------
    def _index_for_x(self, x_screen: float) -> int:
        count = len(self._gpx_data)
        if count < 2:
            return 0
        w = self.width()
        chart_width = w * self._zoom_factor
        abs_x = x_screen + self._horizontal_offset
        ratio = abs_x / chart_width
        ratio = max(0, min(ratio, 1))
        idx_ = int(round(ratio * (count - 1)))
        return max(0, min(idx_, count - 1))
