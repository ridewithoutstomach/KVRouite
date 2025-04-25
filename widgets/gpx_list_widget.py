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

import math
from datetime import datetime, timedelta
import platform
import re

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QStyledItemDelegate, QStyle,
    QAbstractScrollArea
)
from PySide6.QtGui import QColor



class MarkColumnDelegate(QStyledItemDelegate):
    """
    Delegate für Spalte 8 ("Mark"):
    Ignoriert den Selektions-State, damit Spalte 8 nicht blau übermalt wird.
    """
    def paint(self, painter, option, index):
        # Wenn Spalte 8 selektiert wäre, entfernen wir den Selektionszustand,
        # damit der Hintergrund (z.B. rot) sichtbar bleibt.
        if index.column() == 8 and (option.state & QStyle.State_Selected):
            option.state &= ~QStyle.State_Selected
        super().paint(painter, option, index)



class GPXListWidget(QWidget):
    # Signal, wenn der Nutzer im Pause-Modus in der Tabelle auf eine Zeile klickt
    rowClickedInPause = Signal(int)
    markBSet = Signal(int)          # Signal: B=Index
    markESet = Signal(int)          # Signal: E=Index
    markRangeCleared = Signal()     # Signal: Deselect

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        self._markB_idx = None
        self._markE_idx = None
        
        self.table = QTableWidget(self)
        layout.addWidget(self.table)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Time(GPX)", "Lat", "Lon", "Step (s)",
            "m", "km/h", "Height", "%Slope", "Mark"
        ])
        header = self.table.horizontalHeader()
        
        
        if platform.system().startswith("Windows"):
            header.setSectionResizeMode(QHeaderView.Stretch)
        elif platform.system().startswith("Darwin"):        
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
        else:
            # Für Linux/sonstige OS ggf. was anderes
            header.setSectionResizeMode(QHeaderView.ResizeToContents)
        
       
        
        font = self.table.font()
        font.setPointSize(9)  # or 8
        self.table.setFont(font)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        
        self.table.verticalHeader().setDefaultSectionSize(24)
       
        self.table.setItemDelegateForColumn(8, MarkColumnDelegate(self.table))

        # B) StyleSheet: Selektierte Zeile blau (auch wenn kein Fokus).
        self.table.setStyleSheet("""
            QTableView::item:selected {
                background-color: #3874f2;  /* Blau */
                color: white;               /* Weißer Text */
            }
            /* optional: bei NoFocus bleibt es sichtbar */
            QTableView {
                selection-background-color: #3874f2;
            }
        """)
        self.table.setFocusPolicy(Qt.StrongFocus)
       
        # Intern
        self._gpx_data = []            # interner Speicher der GPX-Punkte
        self._history_stack = []
        
        self._markB_idx = None
        self._markE_idx = None
        
        self._marked_rows = set()
        
        
        self._gpx_times = []
        self._last_video_row = None
        self._video_is_playing = False

        # Wenn die Auswahl (Selektion) geändert wird
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        
        #time edit functionality 
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.itemChanged.connect(self._on_item_changed) 
        self._original_value = None
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        
    # ---------------------------------------------------
    # markB markE und Deselect
    # ---------------------------------------------------
   
    def set_markB_row(self, new_b: int):
        if not (0 <= new_b < self.table.rowCount()):
            return

        old_b = self._markB_idx
        old_e = self._markE_idx
        
        if old_e is not None:
            # => E existiert schon => Zeitvergleich
            t_e = self._get_time_of_row(old_e)
            t_b_new = self._get_time_of_row(new_b)
            if t_e and t_b_new:
                if t_b_new > t_e:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self.table,
                        "Invalid Range",
                        "MarkB cannot be set to a time later than MarkE!"
                    )
                    return


        # FALL A) Gar kein B, kein E => B alleine
        if old_b is None and old_e is None:
            self.clear_marked_range()
            self._markB_idx = new_b
            self._color_mark_cell(new_b, QColor("red"))
            print(f"[DEBUG] set_markB_row => B={new_b} (no E yet)")
            self.markBSet.emit(new_b)
            return

        # FALL B) B=None, E!=None => (theoretisch seltener) => "erstes B"
        # => male range
        if old_b is None and old_e is not None:
            self._markB_idx = new_b
            b_ = min(new_b, old_e)
            e_ = max(new_b, old_e)
            self._mark_range(b_, e_)
            print(f"[DEBUG] set_markB_row => E={old_e}, B={new_b}, range=[{b_}..{e_}]")
            self.markBSet.emit(new_b)
            return

        # FALL C) B war schon gesetzt => SHIFT
        if old_b is not None:
            # (C1) E=None => B -> B
            if old_e is None:
                # => wir ersetzen den alten B
                self._color_mark_cell(old_b, QColor("white"))
                self._markB_idx = new_b
                self._color_mark_cell(new_b, QColor("red"))
                print(f"[DEBUG] set_markB_row => replaced old B={old_b} => new B={new_b} (E=None)")
                self.markBSet.emit(new_b)
                return

            # (C2) E existiert => SHIFT range
            b_old = min(old_b, old_e)
            e_old = max(old_b, old_e)
            self._unmark_range(b_old, e_old)

            self._markB_idx = new_b
            b_new = min(new_b, old_e)
            e_new = max(new_b, old_e)
            self._mark_range(b_new, e_new)
            print(f"[DEBUG] set_markB_row => shift range old=[{b_old}..{e_old}], new=[{b_new}..{e_new}]")
            self.markBSet.emit(new_b)
            return

    
    
   
    def set_markE_row(self, new_e: int):
        """
        Setzt den MarkE-Index auf new_e. 
        Falls MarkB noch nicht gesetzt wurde, haben wir nur E allein.
        Falls B schon gesetzt ist => färbe den Bereich B..E rot.
        Falls E schon existiert => SHIFT.
        """
        if not (0 <= new_e < self.table.rowCount()):
            return

        old_b = self._markB_idx
        old_e = self._markE_idx
        
        if old_b is not None:
            # => B existiert schon => Zeitvergleich
            t_b = self._get_time_of_row(old_b)
            t_e_new = self._get_time_of_row(new_e)
            if t_b and t_e_new:
                if t_e_new < t_b:
                    # => MarkE liegt vor MarkB => Verboten
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self.table,  # parent widget
                        "Invalid Range",
                        "MarkE cannot be set to a time earlier than MarkB!"
                    )
                    return  # Abbruch
        

        # ============== FALL A) Noch gar kein E, kein B => E alleine ==============
        if old_e is None and old_b is None:
            # E "erstmalig" ohne B
            self.clear_marked_range()  # Sicherheit: alles weg
            self._markE_idx = new_e
            self._color_mark_cell(new_e, QColor("red"))  # E allein = rote Zelle
            print(f"[DEBUG] set_markE_row => E={new_e} (only E set, no B yet)")
            self.markESet.emit(new_e)
            return

        # ============== FALL B) E war noch None, aber B ist schon da => range ==============
        if old_e is None and old_b is not None:
            # => wir haben B, aber noch keinen E => nun E = new_e => male B..E
            self._markE_idx = new_e
    
            b_ = min(old_b, new_e)
            e_ = max(old_b, new_e)
            self._mark_range(b_, e_)
            print(f"[DEBUG] set_markE_row => B={old_b}, E={new_e}, range=[{b_}..{e_}]")
            self.markESet.emit(new_e)
            return

        # ============== FALL C) E war schon gesetzt => SHIFT ==============
        # Wir hatten old_e != None
        if old_e is not None:
            # (C1) Falls B=None aber E!=None => wir ersetzen den alten E
            if old_b is None:
                # => wir hatten E allein, jetzt kommt "neuer" E => 
                # => Farbe in alter E-Zelle zurücksetzen
                self._color_mark_cell(old_e, QColor("white"))
                # => neue E
                self._markE_idx = new_e
                self._color_mark_cell(new_e, QColor("red"))
                self.markESet.emit(new_e)
                print(f"[DEBUG] set_markE_row => replaced old E={old_e} with new E={new_e}, B=None")
                return
    
            # (C2) B und E existieren => SHIFT
            b_old = min(old_b, old_e)
            e_old = max(old_b, old_e)
            # altes Intervall ENT-marken
            self._unmark_range(b_old, e_old)
    
            # E => new_e
            self._markE_idx = new_e
    
            b_new = min(old_b, new_e)
            e_new = max(old_b, new_e)
            self._mark_range(b_new, e_new)
            print(f"[DEBUG] set_markE_row => old=[{b_old}..{e_old}], new=[{b_new}..{e_new}]")
            self.markESet.emit(new_e)
            return
    
    
    
    # ---------------------------------------------------------
    # Deselect
    # ---------------------------------------------------------
    def clear_marked_range(self):
        """
        Entfernt jegliche Markierung von B..E
        """
        if self._markB_idx is None and self._markE_idx is None:
            return
        if self._markB_idx is not None and self._markE_idx is not None:
            b = min(self._markB_idx, self._markE_idx)
            e = max(self._markB_idx, self._markE_idx)
            self._unmark_range(b, e)
        elif self._markB_idx is not None:
            # Falls nur B existiert
            self._color_mark_cell(self._markB_idx, QColor("white"))
        
        self._markB_idx = None
        self._markE_idx = None
        print("[DEBUG] clear_marked_range => done")
        self.markRangeCleared.emit()

    # ---------------------------------------------------------
    # Helper-Funktionen
    # ---------------------------------------------------------
    def _mark_range(self, row_start: int, row_end: int):
        """
        Färbt Zeilen row_start..row_end (Spalte 8) rot
        """
        for r in range(row_start, row_end+1):
            self._color_mark_cell(r, QColor("red"))

    def _unmark_range(self, row_start: int, row_end: int):
        """
        Färbt Zeilen row_start..row_end (Spalte 8) wieder weiß
        """
        for r in range(row_start, row_end+1):
            self._color_mark_cell(r, QColor("white"))
        
    
    
    def _color_mark_cell(self, row: int, color: QColor):
        col_mark = 8
        item = self.table.item(row, col_mark)
        if not item:
            item = QTableWidgetItem("")
            self.table.setItem(row, col_mark, item)
        item.setBackground(color)
        
    def _mark_row_bg_except_markcol(self, row: int, color):
        """
        Färbt Spalten 0..7 von `row` in `color`,
        ohne Spalte 8 (Mark) zu verändern.
        """
        col_count = self.table.columnCount()  # meist 9
        for col in range(col_count):
            if col == 8:
                continue  # Spalte 8 bleibt, wie sie ist (rot/weiß)
            item = self.table.item(row, col)
            if not item:
                item = QTableWidgetItem("")
                self.table.setItem(row, col, item)
            item.setBackground(color)
    
        

    # ---------------------------------------------------
    # 1) Play/Pause
    # ---------------------------------------------------
    def set_video_playing(self, playing: bool):
        """
        Wird vom MainWindow aufgerufen, wenn wir auf Play oder Pause wechseln.
        """
        if playing:
            # Beim Umschalten auf Play -> vorhandene manuelle Auswahl entfernen
            self.table.blockSignals(True)
            self.table.clearSelection()
            self.table.blockSignals(False)
        self._video_is_playing = playing

    # ---------------------------------------------------
    # 2) Live-Aktualisierung (Video läuft)
    # ---------------------------------------------------
    def highlight_video_time(self, current_s: float, is_playing: bool):
        """
        Wird periodisch aufgerufen, wenn das Video läuft (oder 
        wenn man per Zeit-Set gehen will),
        damit die "beste" Zeile (in Spalten 0..7) gelb wird,
        ohne Spalte 8 (Mark) zu überschreiben.
        """
        self._video_is_playing = is_playing

        # Alte gelbe Zeile (Spalten 0..7) ggf. weiß
        if self._last_video_row is not None:
            self._mark_row_bg_except_markcol(self._last_video_row, Qt.white)

        if not self._gpx_times:
            return

        # Index mit minimaler Zeitdifferenz
        best_idx = self.get_closest_index_for_time(current_s)

        # Neue Markierung (Spalten 0..7 = gelb)
        self._mark_row_bg_except_markcol(best_idx, Qt.yellow)
        self._last_video_row = best_idx

        # Scroll-Logik
        
        item = self.table.item(best_idx, 0)
        if not item:
            return

        viewport_rect = self.table.viewport().rect()
        if is_playing:
            row_scroll = min(best_idx + 2, self.table.rowCount() - 1)
            item2 = self.table.item(row_scroll, 0)
            if item2:
                item2_rect = self.table.visualItemRect(item2)
                if not viewport_rect.contains(item2_rect):
                    self.table.scrollToItem(item2, QAbstractItemView.PositionAtBottom)
        else:
            item_rect = self.table.visualItemRect(item)
            if not viewport_rect.contains(item_rect):
                self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    # ---------------------------------------------------
    # 3) Manuelles Klicken im Pause-Modus
    # ---------------------------------------------------
    def _on_table_selection_changed(self):
        """
        Wird aufgerufen, wenn der Nutzer eine Zeile in der Tabelle anklickt
        (im Pause-Modus). Wir wollen verhindern, dass ein bereits
        rot markierter Bereich in Spalte 8 (B..E) zurückgesetzt wird.

        - Falls _video_is_playing => Abbruch
        - Alte gelbe Zeile (0..7) ggf. auf weiß => ABER Spalte 8 bleibt rot falls B..E
        - Neue Zeile (0..7) wird gelb
        - Signal rowClickedInPause(new_idx) => damit MainWindow synchron agieren kann
        """
        if self._video_is_playing:
            return

        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return

        new_idx = selected[0].row()

        # 1) Alte Zeile 0..7 -> zurück auf weiß (nur, wenn sie nicht in B..E liegt)
        if self._last_video_row is not None and self._last_video_row != new_idx:
            # Prüfen, ob _last_video_row in B..E
            if self._markB_idx is not None and self._markE_idx is not None:
                b = min(self._markB_idx, self._markE_idx)
                e = max(self._markB_idx, self._markE_idx)
                if b <= self._last_video_row <= e:
                    # => NICHT Spalte 8 ändern, NICHT 0..7 "komplett" weißfärben?
                    # Wir wollen aber evtl. 0..7 trotzdem auf weiß, 
                    # damit nicht 2 Zeilen gelb sind.
                    # => Wir nehmen die Hilfsmethode => except Mark:
                    self._mark_row_bg_except_markcol(self._last_video_row, Qt.white)
                else:
                    # alter Punkt außerhalb B..E => normal auf weiß
                    self._mark_row_bg_except_markcol(self._last_video_row, Qt.white)
            else:
                # kein B..E => normal
                self._mark_row_bg_except_markcol(self._last_video_row, Qt.white)

        # 2) Neue Zeile 0..7 => gelb
        self._mark_row_bg_except_markcol(new_idx, Qt.yellow)
        self._last_video_row = new_idx

        # 3) Jetzt erst das Signal -> MainWindow
        self.rowClickedInPause.emit(new_idx)

    def _on_item_changed(self, item):
        if self._updating_table or item.column() != 0 or self._original_value is None or self._original_value == item.text():
            return

        row = item.row()
        column = item.column()
        value = item.text()
        # Update your internal GPX data
        print(f"[DEBUG] Item at row {row}, column {column} changed to {value}")

        self._original_value = None

        match column:
            case 0: 
                 # Parse relative time and update GPX datetime
                base_dt = self._gpx_data[0].get("time")
                if base_dt is None:
                    return  # Can't apply relative update

                try:
                    rel_s = self._parse_hhmmss_milli(value)
                    new_dt = base_dt + timedelta(seconds=rel_s)
                    next_dt = self._get_time_of_row(row + 1)

                    if next_dt and new_dt >= next_dt:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(
                            self.table,  # parent widget
                            "Invalid Range",
                            "New time must be earlier than the next time"
                        )
                        self.set_gpx_data(self._gpx_data) # Reset to original value
                        return
                    prev_dt = self._get_time_of_row(row -1)

                    if prev_dt and new_dt <= prev_dt:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.warning(
                            self.table,  # parent widget
                            "Invalid Range",
                            "New time must be later than the previous time"
                        )
                        self.set_gpx_data(self._gpx_data) # Reset to original value
                        return
                    
                    self._gpx_data[row]["time"] = new_dt
                except Exception as e:
                    print(f"Invalid time format in row {row}: {value} ({e})")

        from core.gpx_parser import recalc_gpx_data
        recalc_gpx_data(self._gpx_data)
        self.set_gpx_data(self._gpx_data)

    def _on_item_double_clicked(self, item):
        if item.column() == 0:
            self._original_value = item.text()

    def select_row_in_pause(self, row_idx: int):
        if self._video_is_playing:
            return
        if not (0 <= row_idx < self.table.rowCount()):
            return

        self.table.blockSignals(True)

        # Falls es eine alte gelbe Zeile gibt
        if self._last_video_row is not None and self._last_video_row != row_idx:
            # => 0..7 auf weiß
            self._mark_row_bg_except_markcol(self._last_video_row, Qt.white)

        # Neue Zeile 0..7 => gelb
        self._mark_row_bg_except_markcol(row_idx, Qt.yellow)
        self._last_video_row = row_idx

        # Offiziell selektieren
        self.table.setCurrentCell(row_idx, 0)
        self.table.selectRow(row_idx)

        self.table.blockSignals(False)
 

    def delete_selected_range(self, shift: bool = True):
        """
        Löscht [markB..markE], 
        setzt Zeitlücke = 1s,
        ruft recalc_gpx_data,
        und updatet Table => set_gpx_data.
        Danach entfernen wir die betroffenen Punkte auch aus der Karte,
        indem wir 'remove_point_on_map(stable_id)' aufrufen (NEU).
        """
        if self._markB_idx is None:
            print("[DEBUG] Nichts markiert, Abbruch.")
            return
    
        b = self._markB_idx
        e = self._markE_idx
        if e is None:
            e = b
        if b > e:
            b, e = e, b
    
        # Grenzen checken
        if b < 0 or b >= len(self._gpx_data):
            print("[DEBUG] B ausserhalb => Abbruch.")
            return
        if e < 0:
            e = 0
        if e >= len(self._gpx_data):
            e = len(self._gpx_data) - 1
    
        print(f"[DEBUG] DELETE => b={b}, e={e}")
        
        # 1) Undo-Snapshot
        import copy
        old_data = copy.deepcopy(self._gpx_data)
        self._history_stack.append(old_data)
    
        # (NEU) 1b) Wir merken uns die stable_ids der zu löschenden Punkte:
        to_remove_ids = []
        for i in range(b, e+1):
            if "stable_id" in self._gpx_data[i]:
                to_remove_ids.append(self._gpx_data[i]["stable_id"])
    
        # 2) Entfernen
        del self._gpx_data[b:e+1]
    
        # 3) Zeitlücke = 1 Sek
        if shift and b > 0 and b < len(self._gpx_data):
            time_before = self._gpx_data[b-1]["time"]
            time_after  = self._gpx_data[b]["time"]
            old_gap = (time_after - time_before).total_seconds()
            shift = old_gap - 1.0
            if shift > 0:
                from datetime import timedelta
                for i in range(b, len(self._gpx_data)):
                    self._gpx_data[i]["time"] = self._gpx_data[i]["time"] - timedelta(seconds=shift)
            print(f"[DEBUG] SHIFT={shift:.3f}s, old_gap={old_gap:.3f}s")

        # 4) Neu berechnen
        from core.gpx_parser import recalc_gpx_data
        recalc_gpx_data(self._gpx_data)
    
        # 5) Tabelle updaten
        self.set_gpx_data(self._gpx_data)
    
        # 6) Markierung entfernen
        self.clear_marked_range()
        print("[DEBUG] delete_selected_range => fertig.")
    
        # (NEU) 7) Map partial update => remove
        mw = self._get_mainwindow()  # (NEU) => MainWindow holen
        if mw is not None:
            for sid in to_remove_ids:
                if sid:
                    mw.remove_point_on_map(sid)  # ruft JS 'removePoint' auf
    
        
   
    
    

    def undo_delete(self):
        """
        Stellt den letzten Zustand wieder her,
        ruft recalc und set_gpx_data.
        """
        if not self._history_stack:
            print("[DEBUG] Undo: Nichts mehr im Stack.")
            return

        import copy
        old_data = self._history_stack.pop()
        self._gpx_data = old_data

        # recalc (zur Sicherheit, 
        #  falls wir den alten Zustand modifiziert hatten)
        from core.gpx_parser import recalc_gpx_data
        recalc_gpx_data(self._gpx_data)

        self.set_gpx_data(self._gpx_data)
        self.clear_marked_range()
        print("[DEBUG] undo_delete => fertig.")

        
        
    
    


    # ---------------------------------------------------
    # 4) GPX-Daten
    # ---------------------------------------------------
    def set_gpx_data(self, data):
        self._updating_table = True
        self._gpx_data = data
        
        n = len(data)
        self.table.setRowCount(n)
        self._gpx_times = [0.0]*n
        self._last_video_row = None

        if n == 0:
            return

        base_dt = data[0].get("time", None)
        base_ts = base_dt.timestamp() if base_dt else None
        prev_dt = None

        for row_idx, pt in enumerate(data):
            dt = pt.get("time", None)
            if dt and base_ts is not None:
                rel_s = dt.timestamp() - base_ts
                if rel_s < 0:
                    rel_s = 0.0
            else:
                rel_s = 0.0

            self._gpx_times[row_idx] = rel_s

            time_str = self._format_hhmmss_milli(rel_s)
            self._set_cell(row_idx, 0, time_str)

            lat_val = pt.get("lat", 0.0)
            lon_val = pt.get("lon", 0.0)
            self._set_cell(row_idx, 1, f"{lat_val:.6f}")
            self._set_cell(row_idx, 2, f"{lon_val:.6f}")

            if row_idx == 0 or not dt or not prev_dt:
                step_s = 0.0
            else:
                diff_s = (dt - prev_dt).total_seconds()
                step_s = diff_s if diff_s > 0 else 0.0
            self._set_cell(row_idx, 3, f"{step_s:.3f}")
            prev_dt = dt

            dist_val = pt.get("delta_m", 0.0)
            self._set_cell(row_idx, 4, f"{dist_val:.2f}")
            spd_val = pt.get("speed_kmh", 0.0)
            self._set_cell(row_idx, 5, f"{spd_val:.2f}")
            ele_val = pt.get("ele", 0.0)
            self._set_cell(row_idx, 6, f"{ele_val:.2f}")
            grd_val = pt.get("gradient", 0.0)
            self._set_cell(row_idx, 7, f"{grd_val:.1f}")
            self._set_cell(row_idx, 8, "")

        self._updating_table = False

    # ---------------------------------------------------
    # 5) get_closest_index_for_time
    # ---------------------------------------------------
    def get_closest_index_for_time(self, current_s: float) -> int:
        """
        Sucht in self._gpx_times den Index mit minimaler Differenz zu current_s.
        """
        if not self._gpx_times:
            return 0
        best_idx = 0
        best_diff = abs(self._gpx_times[0] - current_s)
        for i, val in enumerate(self._gpx_times):
            diff = abs(val - current_s)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

    # ---------------------------------------------------
    # 6) Hilfsfunktionen (Zeilen-Markierung, Format, usw.)
    # ---------------------------------------------------
    def _mark_row_bg(self, row_index, color):
        for col in range(self.table.columnCount()):
            it = self.table.item(row_index, col)
            if it:
                it.setBackground(color)

    def _format_hhmmss_milli(self, secs: float) -> str:
        ms_total = int(round(secs * 1000))
        hh = ms_total // 3600000
        rest = ms_total % 3600000
        mm = rest // 60000
        rest = rest % 60000
        ss = rest // 1000
        ms = rest % 1000
        return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"

    def _parse_hhmmss_milli(self, time_str: str) -> float:
         # Match hh:mm:ss[.mmm] — milliseconds optional
        match = re.match(r"^(\d+):(\d+):(\d+)(?:\.(\d{1,3}))?$", time_str.strip())
        if not match:
            raise ValueError("Time format must be hh:mm:ss or hh:mm:ss.mmm")

        h, m, s, ms = match.groups()
        h = int(h)
        m = int(m)
        s = int(s)
        ms = int(ms) if ms else 0

        return h * 3600 + m * 60 + s + ms / 1000.0

    def _set_cell(self, row, col, text):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsEditable if col==0 else item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, col, item)

    def _get_mainwindow(self):
        """
        Durchwandert die Eltern-Widgets, bis das MainWindow gefunden wird.
        Voraussetzung: GPXListWidget wird im MainWindow verschachtelt.
        """
        w = self.parentWidget()
        while w is not None:
            # Prüfen auf Typ oder ob es z. B. mainwindow-Attribut besitzt
            if hasattr(w, "remove_point_on_map") and hasattr(w, "add_or_update_point_on_map"):
                # => wir gehen davon aus, dass das unser MainWindow ist
                return w
            w = w.parentWidget()
        return None
        
    def _get_time_of_row(self, row_idx: int):
        """
        Gibt das Python-datetime-Objekt zurück, das zu row_idx gehört.
        Falls row_idx ungültig ist, None.
        """
        if not self._gpx_data or row_idx < 0 or row_idx >= len(self._gpx_data):
            return None
        return self._gpx_data[row_idx].get("time", None)    