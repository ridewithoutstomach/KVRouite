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

from PySide6.QtWidgets import QWidget

from PySide6.QtCore import Qt, QPoint, Signal, QPointF, QRect
from datetime import timedelta
import math
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QWheelEvent, QPolygonF, QFont,
    QImage
)
                           

ELE_EPS = 0.05
class ChartWidget(QWidget):
    markerClicked = Signal(int)
    raiseTrackRequested = Signal(float)

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

        # Die fertige Zeichnung ohne Marker, plus der Schluessel, unter dem
        # sie gilt. Siehe paintEvent() und _hintergrund_schluessel().
        self._hintergrund = None
        self._hintergrund_gueltig = None

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
        
        # ausgrauen
        self._sync_idx_start = None
        self._sync_idx_end   = None
        
        self._usl_indices = []        # alle Indizes mit ele < 0
        self._usl_idx_cursor = -1     # Cursor fürs Durchklicken
        self._usl_badge_rect = None   # Klickfläche des Warn-Badges
        
         # ---------------------------
        # **NEU**: Schwellenwert für Stops
        self._stop_threshold = 1.0   # z.B. Default 1 Sekunde

        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        
        self._usl_badge_rect = None   # clickable area of the badge
        self._usl_idx_cursor = -1     # cycling cursor for USL points
        
        
    def _prevideo_cut_idx(self) -> int:
        """
        Index-Grenze für das Vorlauf-Grau bei negativem Video-Shift.
        Alles < return-Wert gilt als 'grau' (ausgeschlossen).
        """
        try:
            from core.gpx_parser import get_gpx_video_shift
            shift = get_gpx_video_shift()
        except Exception:
            shift = 0
        if not (self._gpx_data and shift is not None and shift < 0 and self._gpx_data[0].get("time")):
            return 0
        from datetime import timedelta
        positive_time = self._gpx_data[0]["time"] + timedelta(seconds=abs(shift))
        cut_idx = 0
        for i, pt in enumerate(self._gpx_data):
            ti = pt.get("time")
            if ti and ti >= positive_time:
                cut_idx = i
                break
            else:
                cut_idx = i + 1
        return max(0, min(cut_idx, len(self._gpx_data)))
    
    def _effective_usl_indices(self):
        """
        Liefert die Liste aller 'unter Meer' Indizes, ABER
        ausgeschlossen werden:
          - B..E (self._sync_idx_start.._end), falls gesetzt
          - Vorlaufbereich 0..pre_cut_idx-1 bei negativem Shift
        """
        base = [i for i, pt in enumerate(self._gpx_data)
                if (pt.get("ele") is not None and pt["ele"] < -ELE_EPS)]
        if not base:
            return []
        # Vorlauf (pre-video) grau ausschließen
        cut0 = self._prevideo_cut_idx()
        base = [i for i in base if i >= cut0]

        # Markierter B..E-Bereich ausschließen (falls gesetzt)
        if getattr(self, "_sync_idx_start", None) is not None and getattr(self, "_sync_idx_end", None) is not None:
            i0 = int(min(self._sync_idx_start, self._sync_idx_end))
            i1 = int(max(self._sync_idx_start, self._sync_idx_end))
            base = [i for i in base if not (i0 <= i <= i1)]

        return base

    
        
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
        # Die gemerkte Zeichnung verwerfen - ausdruecklich, nicht ueber den
        # Schluessel. Der kennt von den Daten nur Objektkennung und Laenge
        # der Liste, und die meisten Bearbeitungen (Fix speed spike, chT,
        # Glaetten) aendern die Werte IN derselben Liste: gleiche Kennung,
        # gleiche Laenge, altes Bild. Gesehen am 09.09.2026: nach Fix speed
        # spike standen die Spitzen im Chart, bis man einmal gescrollt hat.
        self._hintergrund = None
        self._hintergrund_gueltig = None
        self._marker_index = 0
        self._zoom_factor = 1.0
        self._horizontal_offset = 0.0
        self._usl_indices = [i for i, pt in enumerate(self._gpx_data) if pt.get("ele", 0.0) < 0.0]
        self._usl_idx_cursor = -1
        self._usl_badge_rect = None
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
            hoechst = self._max_zoom_aktuell()
            if new_zoom > hoechst:
                new_zoom = hoechst

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
    def _kurven_zeichnen(self, painter):
        """Alles ausser dem Marker: Legende, Kurven, Markierungen, Ueberlagerungen.

        Zeile fuer Zeile die bisherige Zeichnung. Sie haengt NICHT vom Marker ab
        und wird deshalb nur noch gebraucht, wenn sich Daten, Groesse, Zoom,
        Versatz, Schwellen oder der Sync-Bereich aendern - siehe paintEvent().
        """
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
    
        # Achsen an das SICHTBARE Fenster anpassen, sobald gezoomt ist (ab
        # 6.14). Bis dahin galt immer Minimum bis Maximum der ganzen Strecke:
        # bei 0 bis 2757 m auf 340 Pixel sind das 8 m je Pixel, und eine Stufe
        # von 0,2 m im Hoehenprofil war bei jedem Zoom unsichtbar - der Zoom
        # wirkte nur waagerecht. Bei Zoom 1 bleibt die Uebersicht ueber die
        # ganze Strecke, wie bisher.
        #
        # Hoehe: Minimum bis Maximum der sichtbaren Punkte, 10 % Rand, aber
        # mindestens 2 m Spanne, damit eine flache Stelle nicht zu Rauschen
        # aufgeblasen wird. 2 m und nicht 5: bei voller Zoomstufe liegen nur
        # noch rund 25 Punkte im Bild, und eine 0,2-m-Stufe soll dann ein
        # Zehntel der Hoehe einnehmen, nicht ein Fuenfundzwanzigstel.
        # Geschwindigkeit: unten bleibt 0, sonst wanderte die 0-km/h-Linie
        # aus dem Bild; nur oben folgt sie dem Fenster.
        i0, i1 = self._sichtbare_indizes(w)
        gezoomt = self._zoom_factor > 1.0 + 1e-9
        if gezoomt:
            ele_fenster = ele_vals[i0:i1 + 1]
            spd_fenster = speed_vals[i0:i1 + 1]
        else:
            ele_fenster, spd_fenster = ele_vals, speed_vals
        min_ele, max_ele = min(ele_fenster), max(ele_fenster)
        max_spd = max(spd_fenster)
        min_spd = 0.0 if gezoomt else min(speed_vals)

        if gezoomt:
            spanne = max(max_ele - min_ele, 2.0)
            mitte = (max_ele + min_ele) / 2.0
            min_ele = mitte - spanne * 0.6
            max_ele = mitte + spanne * 0.6
            max_spd = max(max_spd * 1.1, min_spd + 5.0)

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

        # Die Punkte selbst, sobald sie weit genug auseinander liegen - wie
        # im Mini-Chart. Dann sieht man jeden aufgezeichneten Punkt einzeln
        # und erkennt, wo eine Stufe sitzt. Bei enger Lage waere das nur ein
        # dicker Strich.
        je_punkt_px = chart_width / max(1, count - 1)
        if je_punkt_px >= 4.0:
            self._punkte_zeichnen(painter, path_ele, QColor(255, 255, 0), 2.0, w)
            self._punkte_zeichnen(painter, path_spd, QColor(0, 255, 255), 1.5, w)

        # Skalenwerte am rechten Rand: oberer und unterer Wert des sichtbaren
        # Fensters. Ohne die weiss man bei angepasster Achse nicht, ob eine
        # Stufe 20 cm oder 20 m ist.
        self._skala_zeichnen(painter, w, top_height,
                             min_ele, max_ele, min_spd, max_spd)

        # --- NEU: 0-Meter-Linie im Höhenbereich --------------------------------
        # Fälle:
        #  - min_ele <= 0 <= max_ele  -> Linie exakt bei 0 m (deutlich, gestrichelt)
        #  - min_ele > 0              -> dezente Linie am unteren Rand des Höhenplots
        #  - max_ele < 0              -> dezente Linie am oberen Rand des Höhenplots
        
        
        # --- 0-Meter-Linie im Höhenbereich (robust) -------------------------------
        eps = 1e-6
        has_only_above = (min_ele > 0.0 + eps)
        has_only_below = (max_ele < 0.0 - eps)

        if not (has_only_above or has_only_below):
            # 0 liegt im Bereich -> echte 0-m-Position
            zero_y = y_for_ele(0.0)
            pen = QPen(QColor(255, 80, 80), 1, Qt.DashLine)  # gut sichtbar
        elif has_only_above:
            # alles über 0 -> Linie dezent am unteren Rand des Höhenplots
            zero_y = int(top_height) - 1
            pen = QPen(QColor(140, 140, 140), 1, Qt.DashLine)
        else:
            # alles unter 0 -> Linie dezent am oberen Rand des Höhenplots
            zero_y = 20  # Plot beginnt ab ~20px
            pen = QPen(QColor(140, 140, 140), 1, Qt.DashLine)

        painter.setPen(pen)
        painter.drawLine(0, zero_y, w, zero_y)

        # Label "0 m" nahe der Linie
        try:
            lab_font = QFont(self.font().family(), max(4, int(h * 0.025)))
            painter.setFont(lab_font)
        except Exception:
            pass
        painter.drawText(4, int(zero_y) - 2, "0 m")
        # -------------------------------------------------------------------------

        # ------------------------------------------------------------------------

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
        
        painter.setPen(QPen(QColor(255, 215, 0), 3))  # Time Gaps: GELB (Gold)
        #painter.setPen(QPen(QColor(0, 153, 255), 3))  # Time Gaps: BLAU
        #painter.setPen(QPen(QColor(0, 255, 255), 4))  # Cyan
        #painter.setPen(QPen(QColor(173, 255, 47), 4)) # Lime
        #painter.setPen(QPen(QColor(255, 105, 180), 4))# Pink
        #painter.setPen(QPen(QColor(148, 0, 211), 4))  # Violett
        
        #painter.setPen(QPen(QColor(255, 255, 255), 4))# Weiß
        
        for i in range(1, count):
            # Zeitdifferenz zwischen Punkt i-1 und i:
            dt = (self._gpx_data[i]["time"] - self._gpx_data[i-1]["time"]).total_seconds() if self._gpx_data[i]["time"] else 0
            if dt > self._stop_threshold:
                # x_-Koordinate des Punktes i (bereits in path_spd gespeichert)
                x_ = path_spd[i][0]
                # Hier zeichnen wir einen Strich nach oben (15px) vom zero_speed_y:
                painter.drawLine(x_, zero_speed_y, x_, zero_speed_y + 15)
        
        # === Sync-Overlay (aus der GPX-Liste) ==============================
        if (self._sync_idx_start is not None and
            self._sync_idx_end   is not None and
            self._gpx_data and
            path_spd and len(path_spd) == len(self._gpx_data)):

            i0 = int(max(0, min(self._sync_idx_start, len(self._gpx_data) - 1)))
            i1 = int(max(0, min(self._sync_idx_end,   len(self._gpx_data) - 1)))
            if i0 > i1:
                i0, i1 = i1, i0

            # x-Koordinaten direkt aus path_spd (kein x_for_index nötig)
            x0 = path_spd[i0][0]
            x1 = path_spd[i1][0]

            left  = max(0, min(w, min(x0, x1)))
            right = max(0, min(w, max(x0, x1)))

            if right - left > 1:
                painter.save()
                try:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(0, 0, 0, 110))  # halbtransparentes Grau
                    painter.drawRect(left, 0, right - left, h)
                finally:
                    painter.restore()
        # ===================================================================

        
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
        
        # --- Label links an der Speed-Basislinie: "0 km/h" ---
        try:
            lab_font = QFont(self.font().family(), max(8, int(h * 0.025)))
            painter.setFont(lab_font)
        except Exception:
            pass
        # y-Position der 0-km/h-Linie: nutze die gleiche Skalierung wie für die Speed-Kurve
        y0_spd = int(y_for_speed(0.0))
        # Falls 0 außerhalb des sichtbaren Speed-Bereichs liegen sollte, am unteren Rand einklemmen:
        y0_spd = max(top_height, min(h - 1, y0_spd))
        painter.setPen(QColor(180, 180, 180))
        painter.drawText(6, y0_spd - 2, "0 km/h")
        
        try:
            from core.gpx_parser import get_gpx_video_shift
            shift = get_gpx_video_shift()
        except Exception:
            shift = 0

        if shift is not None and shift < 0 and self._gpx_data and self._gpx_data[0].get("time"):
            positive_time = self._gpx_data[0]["time"] + timedelta(seconds=abs(shift))

            # Finde den ersten Index, dessen Zeit >= positive_time ist
            cut_idx = 0
            for i, pt in enumerate(self._gpx_data):
                ti = pt.get("time")
                if ti and ti >= positive_time:
                    cut_idx = i
                    break
                else:
                    cut_idx = i + 1  # falls alle < positive_time

            if cut_idx > 0:
                # x-Position des letzten "grauen" Punktes
                x_right = path_spd[min(cut_idx - 1, len(path_spd)-1)][0]
                # sichtbare Breite begrenzen (Scroll/Zoom beachten)
                fill_to = x_right
                if fill_to > 0:
                    if fill_to > w:
                        fill_to = w
                    # halbtransparent grau über den gesamten Chart-Bereich
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(128, 128, 128, 90))
                    painter.drawRect(0, 0, fill_to, h)
        # --------------------------------------------------------------------------
        
        # ------------------------------------------------------
        # Marker-Linie und Info-Texte
        # ------------------------------------------------------
        m_x = x_for_index(self._marker_index)
        # ... dein bestehender Marker-Zeichencode ...

        # === NEU: Warn-Badge "unter 0 m" einblenden, wenn min_ele < 0 ===
        usl_list = self._effective_usl_indices()
        
        if usl_list:  # nur wenn es (gefilterte) USL-Punkte gibt
            # Text & Style
            badge_text = "⚠ under sea level ⚠ (0m)"
            try:
                lab_font = QFont(self.font().family(), max(8, int(h * 0.025)))
                painter.setFont(lab_font)
            except Exception:
                pass
            fm = painter.fontMetrics()

            # Position: links oben UNTER der Legende (3 Zeilen * Schrift-Höhe)
            margin = 8
            legend_lines = 3  # "Speed:", "Height:", + Werteblock
            y_top = margin + legend_lines * fm.height() + 6
            x_left = margin

            pad_x = 8
            pad_y = 4
            tw = fm.horizontalAdvance(badge_text)
            th = fm.height()
            rect_w = tw + 2 * pad_x
            rect_h = th + 2 * pad_y
            
            self._usl_badge_rect = QRect(x_left, y_top, rect_w, rect_h)
            
            # Kapsel (halbtransparent), rote Kontur, gut lesbarer Text
            painter.setBrush(QColor(60, 20, 20, 200))
            painter.setPen(QPen(QColor(255, 80, 80), 1))
            painter.drawRoundedRect(x_left, y_top, rect_w, rect_h, 6, 6)

            painter.setPen(QColor(255, 160, 160))
            painter.drawText(x_left + pad_x, y_top + pad_y + fm.ascent(), badge_text)

        
        
        
    def _marker_zeichnen(self, painter):
        """Nur die weisse Linie und die drei Werte daneben.

        Das ist der einzige Teil, der sich beim Abspielen aendert. Er rechnet
        seine paar Werte selbst aus, statt sie aus der grossen Zeichnung zu
        uebernehmen - fuer EINEN Punkt ist das nichts.
        """
        count = len(self._gpx_data)
        if count < 2:
            return
        w = self.width()
        h = self.height()
        idx = max(0, min(self._marker_index, count - 1))

        chart_width = w * self._zoom_factor
        m_x = (idx / (count - 1)) * chart_width - self._horizontal_offset
        if not (-50 < m_x < w + 50):
            return

        painter.setRenderHint(QPainter.Antialiasing)
        # Duenner und halbdurchsichtig: mit 2 px reinweiss stand die Marke wie
        # ein Balken im Bild, besonders am linken Rand, wo sie bei Position 0
        # sitzt. Sie bleibt ueber der gelben und der cyanen Kurve sichtbar,
        # verdeckt sie aber nicht mehr.
        painter.setPen(QPen(QColor(255, 255, 255, 170), 1))
        painter.drawLine(m_x, 0, m_x, h)

        pt_ = self._gpx_data[idx]
        ele_val = pt_["ele"]
        spd_val = min(pt_.get("speed_kmh", 0.0), self._speed_cap)
        grad_val = pt_.get("gradient", 0.0)

        e_show = ele_val if abs(ele_val) >= ELE_EPS else 0.0
        line1 = f"{e_show:.1f}".replace(".", ",") + "m"
        line2 = f"{spd_val:.1f}".replace(".", ",") + "km/h"
        line3 = f"{grad_val:.1f}".replace(".", ",") + "%"

        y_start = 40
        y_step = 15

        painter.setPen(QPen(QColor("white"), 1))
        painter.drawText(m_x + 5, y_start, line1)
        painter.drawText(m_x + 5, y_start + y_step, line2)
        painter.drawText(m_x + 5, y_start + 2 * y_step, line3)

    def _sichtbare_indizes(self, w):
        """(erster, letzter) Index der Punkte im sichtbaren Ausschnitt."""
        count = len(self._gpx_data)
        if count < 2:
            return 0, max(0, count - 1)
        chart_width = max(1.0, w * self._zoom_factor)
        r0 = self._horizontal_offset / chart_width
        r1 = (self._horizontal_offset + w) / chart_width
        i0 = int(math.floor(max(0.0, r0) * (count - 1)))
        i1 = int(math.ceil(min(1.0, r1) * (count - 1)))
        i0 = max(0, min(i0, count - 1))
        i1 = max(i0 + 1, min(i1, count - 1)) if count > 1 else i0
        return i0, i1

    #: Pixel je Punkt bei voller Zoomstufe. 8 waren zu wenig: eine 0,2-m-Stufe
    #: war damit ein Zacken von 8 Pixeln Breite, nicht mehr zu erkennen als
    #: bei Zoom 50 - gesehen am 09.09.2026. Mit 40 liegen rund 25 Punkte im
    #: Bild, jede Stufe hat Platz, und die Hoehenskala umfasst dann nur noch
    #: wenige Meter.
    PIXEL_JE_PUNKT_MAX = 40.0

    def _max_zoom_aktuell(self):
        """Zoomgrenze nach Punktzahl statt fest 50.

        Fest 50 reichte fuer kurze Strecken, bei einer 10-Stunden-Aufzeichnung
        ergab es nur gut ein Pixel je Punkt. Nie unter 50, damit sich kurze
        Strecken nicht schlechter zoomen lassen als bisher.
        """
        count = len(self._gpx_data)
        w = max(1, self.width())
        return max(self._max_zoom, count * self.PIXEL_JE_PUNKT_MAX / w)

    def _punkte_zeichnen(self, painter, pts, farbe, radius, w):
        painter.save()
        try:
            painter.setPen(Qt.NoPen)
            painter.setBrush(farbe)
            for (x_, y_) in pts:
                if -5 <= x_ <= w + 5:
                    painter.drawEllipse(QPointF(x_, y_), radius, radius)
        finally:
            painter.restore()

    def _skala_zeichnen(self, painter, w, top_height, min_ele, max_ele,
                        min_spd, max_spd):
        painter.save()
        try:
            painter.setPen(QPen(QColor(200, 200, 200), 1))
            painter.setFont(QFont(self.font().family(), 8))
            fm = painter.fontMetrics()
            nachkomma = 1 if (max_ele - min_ele) < 20.0 else 0
            oben = f"{max_ele:.{nachkomma}f} m"
            unten = f"{min_ele:.{nachkomma}f} m"
            painter.drawText(w - 4 - fm.horizontalAdvance(oben), 20 + fm.ascent(), oben)
            painter.drawText(w - 4 - fm.horizontalAdvance(unten), top_height - 4, unten)
            spd = f"{max_spd:.0f} km/h"
            painter.drawText(w - 4 - fm.horizontalAdvance(spd),
                             top_height + 10 + fm.ascent(), spd)
        finally:
            painter.restore()

    def _hintergrund_schluessel(self):
        """Woran haengt die gemerkte Zeichnung? Aendert sich davon etwas, neu."""
        try:
            from core.gpx_parser import get_gpx_video_shift
            versatz = get_gpx_video_shift()
        except Exception:
            versatz = None
        return (self.width(), self.height(), self.devicePixelRatioF(),
                id(self._gpx_data), len(self._gpx_data),
                self._zoom_factor, self._horizontal_offset,
                self._speed_cap, self._zero_speed_threshold,
                self._stop_threshold,
                self._sync_idx_start, self._sync_idx_end,
                versatz)

    def paintEvent(self, event):
        """Gemerkte Zeichnung aufs Widget kopieren, Marker darueber.

        Frueher wurde hier ALLES neu gezeichnet - Werte sammeln, Minima und
        Maxima bilden, zwei Punktlisten aufbauen und je Punkt eine eigene
        Linie ziehen. Bei einer 5-Stunden-Aufzeichnung mit 17000 Punkten
        waren das rund 35000 Zeichenbefehle, und das fuenfmal je Sekunde,
        weil update_timeline_marker() den Marker im 200-ms-Takt weiterschiebt.
        Gemessen am 31.08.2026: 25 ms je Neuzeichnung bei 17329 Punkten,
        42 ms bei 28800. Ein Videobild dauert bei 30 fps 33 ms - deshalb hat
        das Video bei langen Strecken gestockt, und zwar nur nach dem Sync,
        weil der Chart erst dann mitlaeuft.

        Beim Abspielen aendert sich an den Kurven aber gar nichts. Sie werden
        deshalb einmal in ein Bild gezeichnet und gemerkt; je Takt wird nur
        noch dieses Bild kopiert und der Marker darueber gemalt. Gemessen:
        0,06 ms statt 25 ms.
        """
        super().paintEvent(event)

        schluessel = self._hintergrund_schluessel()
        if self._hintergrund is None or self._hintergrund_gueltig != schluessel:
            dpr = self.devicePixelRatioF()
            breite = max(1, int(self.width() * dpr))
            hoehe = max(1, int(self.height() * dpr))
            bild = QImage(breite, hoehe, QImage.Format_ARGB32_Premultiplied)
            bild.setDevicePixelRatio(dpr)
            bild.fill(Qt.transparent)
            maler = QPainter(bild)
            try:
                self._kurven_zeichnen(maler)
            finally:
                maler.end()
            self._hintergrund = bild
            self._hintergrund_gueltig = schluessel

        painter = QPainter(self)
        painter.drawImage(0, 0, self._hintergrund)
        self._marker_zeichnen(painter)

    
                
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 1) Klick auf den USL-Badge => Dialog
            if self._usl_badge_rect and self._usl_badge_rect.contains(event.pos()):
                usl = self._effective_usl_indices()
                if not usl:
                    event.accept()
                    return
                # tiefster Punkt suchen
                min_idx = min(usl, key=lambda i: (self._gpx_data[i].get("ele", 0.0)))
                min_ele = self._gpx_data[min_idx].get("ele", 0.0)

                # Dialog (englisch)
                from PySide6.QtWidgets import QMessageBox
                msg = QMessageBox(self)
                msg.setWindowTitle("Under sea level")
                msg.setText(f"Deepest point: {min_ele:.2f} m\nWhat would you like to do?")
                show_btn = msg.addButton("Show", QMessageBox.AcceptRole)
                move_btn = msg.addButton("Raise track above sea level", QMessageBox.ActionRole)
                cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)
                msg.exec()

                btn = msg.clickedButton()
                if btn is show_btn:
                    # marker + notify world
                    self.highlight_gpx_index(min_idx)
                    self.markerClicked.emit(min_idx)
                elif btn is move_btn:
                    # delta = -min_ele + buffer (aktuell 0)
                    buffer_m = 0.0
                    delta = max(0.0, -min_ele + buffer_m)
                    if delta > 0:
                        self.raiseTrackRequested.emit(delta)
                event.accept()
                return

            # 2) normaler Left-Click ins Chart -> Marker dahin
            idx = self._index_for_x(event.pos().x())
            self._marker_index = idx
            self.update()
            self.markerClicked.emit(idx)
            event.accept()

        elif event.button() == Qt.RightButton:
            # 1) Rechtsklick auf Badge -> USL zyklisch durchgehen
            if self._usl_badge_rect and self._usl_badge_rect.contains(event.pos()):
                usl = self._effective_usl_indices()
                if usl:
                    self._usl_idx_cursor = (self._usl_idx_cursor + 1) % len(usl)
                    idx = usl[self._usl_idx_cursor]
                    self.highlight_gpx_index(idx)
                    self.markerClicked.emit(idx)
                event.accept()
                return
            # 2) sonst: Scroll-Drag wie gehabt
            self._dragging_scroll = True
            self._drag_start_x = event.pos().x()
            self._offset_start = self._horizontal_offset
            event.accept()
        else:
            super().mousePressEvent(event)

 

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
        
    def set_sync_range(self, idx_start: int, idx_end: int):
        if idx_start is None or idx_end is None:
            self._sync_idx_start = None
            self._sync_idx_end = None
        else:
            if idx_start > idx_end:
                idx_start, idx_end = idx_end, idx_start
            self._sync_idx_start = max(0, idx_start)
            self._sync_idx_end   = max(0, idx_end)
        self.update()

    def clear_sync_range(self):
        self._sync_idx_start = None
        self._sync_idx_end   = None
        self.update()
    
