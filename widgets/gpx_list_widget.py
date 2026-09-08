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

import bisect
import math
from datetime import datetime, timedelta
import platform
import re

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QAbstractItemView, QStyledItemDelegate, QStyle,
    QAbstractScrollArea
)    
from PySide6.QtGui import QColor, QBrush

from core.gpx_parser import get_gpx_video_shift, is_gpx_video_shift_set, set_gpx_video_shift


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
    
    # Signal als Klassenattribut
    tracksDropped = Signal(list)  # list[str]
    
    # Signal, wenn der Nutzer im Pause-Modus in der Tabelle auf eine Zeile klickt
    rowClickedInPause = Signal(int)
    rowSelected = Signal(int) 
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

        # B) Selektierte Zeile bleibt farbig, auch ohne Fokus. Die Farbe
        # kommt aus core/theme.py - hell ist es dasselbe Blau wie bisher.
        self.table.setStyleSheet(self._tabellen_stil())
        self.table.setFocusPolicy(Qt.StrongFocus)

        # Ende des Tabellenaufbaus

       
        # Intern
        self._gpx_data = []            # interner Speicher der GPX-Punkte
        self._history_stack = []
        
        self._markB_idx = None
        self._markE_idx = None
        # Die Luecke des letzten Schnitts: (Punkt davor, Punkt danach,
        # Punktzahl der Spur danach). Rechtsklick auf [- / -] markiert sie.
        self._luecke = None

        self._marked_rows = set()
        # Schriftfarben, die der gelbe Balken ueberdeckt - je Zeile gemerkt,
        # damit sie danach wieder gelten.
        self._schrift_vorher = {}
        
        
        self._gpx_times = []
        # Sind die Zeiten aufsteigend? Nur dann darf binaer gesucht werden -
        # siehe get_closest_index_for_time().
        self._gpx_times_sortiert = True
        self._last_video_row = None
        self._video_is_playing = False
        # Bulk update guards and previous state holders
        self._updating_table = False
        self._prev_resize_modes = None
        self._prev_sorting_enabled = None

        # Wenn die Auswahl (Selektion) geändert wird
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        
        #time edit functionality 
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.itemChanged.connect(self._on_item_changed) 
        self._original_value = None
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        
        # --- Drag&Drop: GPX/FIT ---
        self.setAcceptDrops(True)  # auf dem ganzen Widget (Tabelle füllt es ohnehin)
        self._dnd_overlay = QLabel("Drop 1x GPX / FIT to import…", self)
        self._dnd_overlay.setStyleSheet(
            "background: rgba(0,0,0,0.55); color: white; border: 2px dashed #ddd;"
            "border-radius: 12px; font-size: 18px; padding: 16px;"
        )
        self._dnd_overlay.setAlignment(Qt.AlignCenter)
        self._dnd_overlay.hide()
        self._dnd_overlay.setGeometry(self.rect())
        self._dnd_overlay.show()  # leer -> Hinweis sichtbar
    #    -------------------------------------------------
    # markB markE und Deselect
    # ---------------------------------------------------
   
    # ------------------------------------------------------------------
    # Farben
    # ------------------------------------------------------------------
    def _tabellen_stil(self) -> str:
        """Die ausgewaehlte Zeile bleibt farbig, auch ohne Fokus.

        Im dunklen Betrieb kommen Gitterlinien und Kopfzeilen dazu: ihre Farbe
        leitet Qt sonst aus Palettenrollen ab, die die dunkle Tafel nicht
        setzt - die Linien verschwanden dann und die Tabelle stand als
        schwarzer Block da. Im hellen Betrieb bleibt es bei dem einen Satz von
        frueher, damit dort nichts anders aussieht als bisher.
        """
        from core import theme
        f = theme.farben()
        stil = ("QTableView::item:selected { background-color: %s; color: %s; }"
                "QTableView { selection-background-color: %s; }"
                % (f["akzent"], f["akzent_text"], f["akzent"]))
        if theme.ist_dunkel():
            stil += (
                "QTableView { gridline-color: %(gitter)s; }"
                "QHeaderView::section { background-color: %(kopf)s; color: %(text)s;"
                " border: 0px; border-right: 1px solid %(gitter)s;"
                " border-bottom: 1px solid %(gitter)s; padding: 2px 4px; }"
                "QTableCornerButton::section { background-color: %(kopf)s;"
                " border: 0px; border-right: 1px solid %(gitter)s;"
                " border-bottom: 1px solid %(gitter)s; }"
                % {"gitter": f["gitter"], "kopf": f["kopfzeile"], "text": f["text"]})
        return stil

    def theme_aktualisieren(self):
        """Wird von core/theme.anwenden() gerufen, wenn umgeschaltet wurde."""
        from core import theme
        self.table.setStyleSheet(self._tabellen_stil())

        # Schon gefaerbte Zeilen nachziehen: die zurueckgenommene Schrift der
        # Punkte vor dem Sync-Punkt haengt an der Farbgebung. Erkannt wird sie
        # daran, dass sie einer der beiden Tafelwerte ist - andere Faerbungen
        # (rote Marken, gelbe Zeile) bleiben unberuehrt.
        gedimmt = {theme.DUNKEL["text_gedimmt"].lower(),
                   theme.HELL["text_gedimmt"].lower(),
                   "#808080"}
        neu = self.gedimmte_schrift()
        for zeile in range(self.table.rowCount()):
            for spalte in range(self.table.columnCount()):
                if spalte == 8:
                    continue
                item = self.table.item(zeile, spalte)
                if item is None:
                    continue
                if item.foreground().color().name().lower() in gedimmt:
                    item.setForeground(neu)

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

    def luecke_merken(self, b):
        """Nach einem Schnitt: b ist der erste Punkt HINTER der Luecke in der
        neuen Spur, b-1 der letzte davor. Rechtsklick auf [- / -] markiert die
        beiden wieder, etwa fuer chT oder die Nahtglaettung ueber die Luecke.
        Ruft der Schnitt in der GPX-Leiste wie der Video-Cut mit V&G On auf.
        Am Anfang oder Ende der Spur gibt es keine Luecke."""
        n = len(self._gpx_data)
        self._luecke = (b - 1, b, n) if 0 < b < n else None

    def schritt_text(self, name, b_idx=None, e_idx=None):
        """Name eines Undo-Schritts fuer Edit > Undo history: mit Zeile(n)
        und der GPX-Zeit aus der Tabelle, damit man sieht, WO er war.
        Ohne Zeilen bleibt es beim Namen (ganze Spur)."""
        def zeit(i):
            try:
                return self._format_hhmmss_milli(self._gpx_times[i])
            except Exception:
                return "?"
        if b_idx is None and e_idx is None:
            return name
        if b_idx is None or e_idx is None or b_idx == e_idx:
            i = b_idx if b_idx is not None else e_idx
            return f"{name} row {i} ({zeit(i)})"
        b, e = sorted((b_idx, e_idx))
        return f"{name} rows {b}..{e} ({zeit(b)} - {zeit(e)})"

    def restore_markB(self):
        """Markiert den Punkt vor der Luecke des letzten Schnitts als MarkB.
        Rueckgabe: die Zeile, wenn sie markiert wurde, sonst None."""
        return self._luecke_markieren(0, self.set_markB_row)

    def restore_markE(self):
        """Markiert den Punkt nach der Luecke des letzten Schnitts als MarkE.
        Rueckgabe: die Zeile, wenn sie markiert wurde, sonst None."""
        return self._luecke_markieren(1, self.set_markE_row)

    def _luecke_markieren(self, seite, setzen):
        # Nur solange die Spur noch so viele Punkte hat wie nach dem Schnitt:
        # chT, chEle, Smooth aendern die Zaehlung nicht, ein weiterer Schnitt,
        # Undo oder eine andere Spur schon - dann zeigt der Index irgendwohin.
        if self._luecke is None or self._luecke[2] != self.table.rowCount():
            return None
        idx = self._luecke[seite]
        setzen(idx)
        # set_markB/E_row lehnt ab, wenn die Zeitreihenfolge nicht passt -
        # dann steht die Marke nicht auf idx, und es gibt nichts anzufahren.
        jetzt = self._markB_idx if seite == 0 else self._markE_idx
        return idx if jetzt == idx else None

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

        Die Schriftfarbe wird mitgesetzt, und zwar aus der Helligkeit des
        Hintergrunds gerechnet: auf dem gelben Balken der aktuellen Zeile stand
        im Dunkelmodus sonst die helle Palettenschrift - gelb auf gelb.
        """
        farbe = QColor(color)
        # Helligkeit nach ITU-R BT.601, wie sie auch Qt fuer Kontraste nimmt.
        helligkeit = (farbe.red() * 299 + farbe.green() * 587
                      + farbe.blue() * 114) / 1000.0
        schrift = QColor("#000000") if helligkeit > 140 else QColor("#ffffff")

        # Traegt die Zeile den Balken schon, ist die echte Schrift bereits
        # gemerkt - dann NICHT noch einmal merken, sonst stuende dort die
        # Balkenschrift vom ersten Mal. Genau das passierte beim Klick in die
        # Tabelle: _on_table_selection_changed malt die Zeile gelb, meldet
        # sie dem MainWindow, und das ruft select_row_in_pause auf derselben
        # Zeile - zweiter Anstrich, gemerkt wurde Schwarz. Beim Wechsel auf
        # die naechste Zeile kam das Schwarz zurueck: im dunklen Betrieb
        # schwarze Schrift auf dunklem Grund (gemessen am 08.09.2026).
        schon_gemerkt = row in self._schrift_vorher
        gemerkt = []
        col_count = self.table.columnCount()  # meist 9
        for col in range(col_count):
            if col == 8:
                continue  # Spalte 8 bleibt, wie sie ist (rot/weiß)
            item = self.table.item(row, col)
            if not item:
                item = QTableWidgetItem("")
                self.table.setItem(row, col, item)
            # Die bisherige Schrift merken: Punkte vor dem Sync-Punkt stehen
            # zurueckgenommen da, und das soll nach dem Balken wieder gelten.
            # Ueber data(ForegroundRole), nicht ueber foreground(): letzteres
            # liefert fuer ein Feld OHNE eigene Farbe einen schwarzen Pinsel,
            # und den wuerden wir danach faelschlich zurueckschreiben.
            if not schon_gemerkt:
                gemerkt.append((col, item.data(Qt.ForegroundRole)))
            item.setBackground(farbe)
            item.setForeground(schrift)
        if not schon_gemerkt:
            self._schrift_vorher[row] = gemerkt

    def _zeile_klar(self, row: int):
        """Die Faerbung des Balkens zuruecknehmen.

        Frueher wurde hier Qt.white gesetzt - richtig, solange die Tabelle
        weiss war. Im dunklen Betrieb blieb dadurch ein heller Streifen hinter
        dem Balken stehen. Jetzt wird der Hintergrund GELOESCHT (leerer
        QBrush), dann zeichnet die Tabelle wieder ihren eigenen, egal welcher
        das gerade ist.
        """
        if row is None or not (0 <= row < self.table.rowCount()):
            return
        gemerkt = dict(self._schrift_vorher.pop(row, []))
        for col in range(self.table.columnCount()):
            if col == 8:
                continue
            item = self.table.item(row, col)
            if item is None:
                continue
            # setBackground(QBrush()) bzw. setForeground(QBrush()) taugen hier
            # NICHT: ein leerer QBrush malt zwar keinen Hintergrund, traegt
            # als Farbe aber Schwarz - der Text wurde dadurch schwarz auf
            # dunklem Grund. Die Rolle muss ganz weg, dann steht das Feld
            # wieder da wie ein frisches.
            item.setData(Qt.BackgroundRole, None)
            vorher = gemerkt.get(col)
            if vorher is not None:
                item.setForeground(vorher)
            else:
                item.setData(Qt.ForegroundRole, None)
    
    def _set_row_foreground(self, row: int, color):
        col_count = self.table.columnCount()
        for col in range(col_count):
            if col != 8:
                item = self.table.item(row, col)
                item.setForeground(color)

    def gedimmte_schrift(self) -> QColor:
        """Farbe fuer Punkte vor dem Sync-Punkt.

        Frueher fest Qt.gray. Auf dunklem Grund war das nicht mehr zu lesen,
        deshalb kommt der Wert jetzt aus core/theme.py und wird dort je nach
        Farbgebung heller oder dunkler gewaehlt.
        """
        from core import theme
        return QColor(theme.farben()["text_gedimmt"])
        

    # ---------------------------------------------------
    # 1) Play/Pause
    # ---------------------------------------------------
    def set_video_playing(self, playing: bool):
        """
        Wird vom MainWindow aufgerufen, wenn wir auf Play oder Pause wechseln.
        """
        if playing and is_gpx_video_shift_set():
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
            self._zeile_klar(self._last_video_row)

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
        if self._video_is_playing and is_gpx_video_shift_set():
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
                    self._zeile_klar(self._last_video_row)
                else:
                    # alter Punkt außerhalb B..E => normal auf weiß
                    self._zeile_klar(self._last_video_row)
            else:
                # kein B..E => normal
                self._zeile_klar(self._last_video_row)

        # 2) Neue Zeile 0..7 => gelb
        self._mark_row_bg_except_markcol(new_idx, Qt.yellow)
        self._last_video_row = new_idx

        # 3) Jetzt erst das Signal -> MainWindow
        self.rowClickedInPause.emit(new_idx)
        self.rowSelected.emit(new_idx)

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
                base_dt = self._gpx_data[0].get("time") - timedelta(seconds=get_gpx_video_shift())
                if base_dt is None:
                    return  # Can't apply relative update

                try:
                    rel_s = self._parse_hhmmss_milli(value)
                    new_dt = base_dt + timedelta(seconds=rel_s) 
                    next_dt = self._get_time_of_row(row + 1)  
                    print(f"[DEBUG] Setting new time for row {row}: {new_dt} (base={base_dt}, rel_s={rel_s})")

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
                            f"New time must be later than the previous time"
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
        if self._video_is_playing and is_gpx_video_shift_set():
            return
        if not (0 <= row_idx < self.table.rowCount()):
            return

        self.table.blockSignals(True)

        # Falls es eine alte gelbe Zeile gibt
        if self._last_video_row is not None and self._last_video_row != row_idx:
            # => 0..7 auf weiß
            self._zeile_klar(self._last_video_row)

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
    
        if(not shift and b==0 and e < len(self._gpx_data)): #if delete first point -> gpx-video shift to update
            delta = (self._gpx_data[e+1].get("time") - self._gpx_data[0].get("time")).total_seconds()
            set_gpx_video_shift(get_gpx_video_shift() + delta)
            
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

        # 5b) Die Luecke merken: der Bereich ist weg, davor liegt b-1, danach
        # rueckt b nach.
        self.luecke_merken(b)

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
        self._begin_table_update()
        try:
            self._gpx_data = data

            n = len(data)
            self.table.clearContents()
            self.table.setRowCount(n)
            
            
            self._gpx_times = [0.0] * n
            self._gpx_times_sortiert = True
            self._last_video_row = None
    
            if n == 0:
                # Keine Spur mehr (Projekt geschlossen): die gemerkte Luecke
                # gehoerte zu ihr.
                self._luecke = None
                if hasattr(self, "_dnd_overlay"):
                    self._dnd_overlay.setText("Drag & Drop 1 GPX/FIT here")
                    self._dnd_overlay.show()
                return

            base_dt = data[0].get("time", None)
            prev_dt = None
            video_shift = get_gpx_video_shift()

            for row_idx, pt in enumerate(data):
                dt = pt.get("time", None)
                if dt and base_dt is not None:
                    # Faster than timestamp(): use timedelta-based difference
                    rel_s = (dt - base_dt).total_seconds() + video_shift
                else:
                    rel_s = 0.0

                if abs(rel_s) < 0.001:
                    rel_s = 0.0

                self._gpx_times[row_idx] = rel_s
                # Ein Punkt OHNE Zeitstempel bekommt oben 0.0. Steht so einer
                # mitten drin, sind die Zeiten nicht mehr aufsteigend, und die
                # binaere Suche waere falsch. Einmal hier mitgepruefen kostet
                # nichts - die Schleife laeuft ohnehin ueber alle Punkte.
                if row_idx > 0 and rel_s < self._gpx_times[row_idx - 1]:
                    self._gpx_times_sortiert = False

                # Column 0: time
                time_str = self._format_hhmmss_milli(rel_s)
                self._set_cell(row_idx, 0, time_str)

                # Columns 1-2: lat/lon
                lat_val = pt.get("lat", 0.0)
                lon_val = pt.get("lon", 0.0)
                self._set_cell(row_idx, 1, f"{lat_val:.6f}")
                self._set_cell(row_idx, 2, f"{lon_val:.6f}")

                # Column 3: step (s)
                if row_idx == 0 or not dt or not prev_dt:
                    step_s = 0.0
                else:
                    diff_s = (dt - prev_dt).total_seconds()
                    step_s = diff_s if diff_s > 0 else 0.0
                self._set_cell(row_idx, 3, f"{step_s:.3f}")
                prev_dt = dt

                # Columns 4-8: metrics
                dist_val = pt.get("delta_m", 0.0)
                self._set_cell(row_idx, 4, f"{dist_val:.2f}")
                spd_val = pt.get("speed_kmh", 0.0)
                self._set_cell(row_idx, 5, f"{spd_val:.2f}")
                ele_val = pt.get("ele", 0.0)
                self._set_cell(row_idx, 6, f"{ele_val:.2f}")
                grd_val = pt.get("gradient", 0.0)
                self._set_cell(row_idx, 7, f"{grd_val:.1f}")
                self._set_cell(row_idx, 8, "")
                if rel_s < 0:
                    self._set_row_foreground(row_idx, self.gedimmte_schrift())
        finally:
            # End of bulk update: restore widget state
            self._end_table_update()
            
            if hasattr(self, "_dnd_overlay"):
                self._dnd_overlay.hide()
    # ----------------------------
    # Drag&Drop (GPX/FIT)
    # ----------------------------
    def _extract_paths(self, mime):
        paths = []
        if mime and mime.hasUrls():
            for u in mime.urls():
                if u.isLocalFile():
                    paths.append(u.toLocalFile())
        elif mime and mime.hasText():
            for line in mime.text().splitlines():
                line = line.strip()
                if line:
                    paths.append(line)
        return paths

    def _is_track(self, path: str) -> bool:
        return path.lower().endswith((".gpx", ".fit"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._dnd_overlay.setGeometry(self.rect())

    def dragEnterEvent(self, e):
        ok = any(self._is_track(p) for p in self._extract_paths(e.mimeData()))
        if ok:
            self._dnd_overlay.show()
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._dnd_overlay.hide()
        e.accept()

    def dropEvent(self, e):
        self._dnd_overlay.hide()
        paths = [p for p in self._extract_paths(e.mimeData()) if self._is_track(p)]
        if paths:
            try:
                self.tracksDropped.emit(paths)
            except Exception:
                pass
            e.acceptProposedAction()
        else:
            e.ignore()        
            

    # ---------------------------------------------------
    # 5) get_closest_index_for_time
    # ---------------------------------------------------
    def get_closest_index_for_time(self, current_s: float) -> int:
        """
        Sucht in self._gpx_times den Index mit minimaler Differenz zu current_s.

        Sind die Zeiten aufsteigend - der Normalfall -, wird binaer gesucht.
        Beim Abspielen wird diese Suche zweimal je 200-ms-Takt gerufen, und
        linear kostet sie bei einer 5-Stunden-Aufzeichnung mit 17000 Punkten
        0,74 ms je Aufruf (gemessen am 31.08.2026); binaer sind es 0,0004 ms.
        Auf diesem Rechner faellt das nicht auf, auf einem langsameren schon.

        Sind sie NICHT aufsteigend - ein Punkt ohne Zeitstempel bekommt beim
        Aufbau 0.0 -, wird wie bisher linear gesucht. Das Ergebnis ist in
        beiden Faellen dasselbe.
        """
        zeiten = self._gpx_times
        if not zeiten:
            return 0

        if self._gpx_times_sortiert:
            i = bisect.bisect_left(zeiten, current_s)
            if i <= 0:
                return 0
            if i >= len(zeiten):
                return len(zeiten) - 1
            # bisect liefert die erste Stelle NICHT KLEINER als current_s.
            # Der naechstgelegene Punkt ist die davor oder diese.
            return i if (zeiten[i] - current_s) < (current_s - zeiten[i - 1]) else i - 1

        best_idx = 0
        best_diff = abs(zeiten[0] - current_s)
        for i, val in enumerate(zeiten):
            diff = abs(val - current_s)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

    # ---------------------------------------------------
    # 6) Hilfsfunktionen (Zeilen-Markierung, Format, usw.)
    # ---------------------------------------------------
    
    def _format_hhmmss_milli(self, secs: float) -> str:
        sign = '-' if secs < 0 else ''
        secs_abs = abs(secs)
        ms_total = int(round(secs_abs * 1000))
        hh = ms_total // 3600000
        rest = ms_total % 3600000
        mm = rest // 60000
        rest = rest % 60000
        ss = rest // 1000
        ms = rest % 1000
        return f"{sign}{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"

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
        """
        Efficient cell update: reuse an existing QTableWidgetItem when possible,
        only update its text. Only column 0 is editable.
        """
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            flags = item.flags()
            if col == 0:
                item.setFlags(flags | Qt.ItemIsEditable)
            else:
                item.setFlags(flags & ~Qt.ItemIsEditable)
            self.table.setItem(row, col, item)
        item.setText(text)

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

    # ---------------------------------------------------
    # Internal: freeze/unfreeze table for bulk updates
    # ---------------------------------------------------
    def _begin_table_update(self):
        if self._updating_table:
            return
        self._updating_table = True
        # Disable signals and repaints to speed up bulk filling
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        # Disable sorting because it can be very expensive during cell insert/update
        self._prev_sorting_enabled = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        # Temporarily fix header resize modes to avoid per-row recalculation
        # (especially when using ResizeToContents)
        header = self.table.horizontalHeader()
        self._prev_resize_modes = [header.sectionResizeMode(i) for i in range(self.table.columnCount())]
        for i in range(self.table.columnCount()):
            header.setSectionResizeMode(i, QHeaderView.Fixed)

    def _end_table_update(self):
        # Restore original header resize modes
        header = self.table.horizontalHeader()
        if self._prev_resize_modes is not None:
            for i, mode in enumerate(self._prev_resize_modes):
                header.setSectionResizeMode(i, mode)
        self._prev_resize_modes = None
        # Restore sorting and repaints
        if self._prev_sorting_enabled is not None:
            self.table.setSortingEnabled(self._prev_sorting_enabled)
        self._prev_sorting_enabled = None
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._updating_table = False
        
    def _get_time_of_row(self, row_idx: int):
        """
        Gibt das Python-datetime-Objekt zurück, das zu row_idx gehört.
        Falls row_idx ungültig ist, None.
        """
        if not self._gpx_data or row_idx < 0 or row_idx >= len(self._gpx_data):
            return None
        return self._gpx_data[row_idx].get("time", None)    
        
    # NEU ergänzen:
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_dnd_overlay") and self._dnd_overlay:
            self._dnd_overlay.setGeometry(self.rect())
    