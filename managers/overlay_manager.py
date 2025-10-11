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


# Al Overlays are saved in "all_ovls = self._overlay_manager.get_all_overlays()"

#

from PySide6.QtCore import QObject, Signal, QSettings
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QComboBox, QDoubleSpinBox, QPushButton,
    QSpinBox, QLineEdit, QFileDialog, QHBoxLayout, QDialogButtonBox
)
import os
import copy

class OverlayManager(QObject):
    """
    Verwaltet Overlays und malt sie in die Timeline (blau). 
    Bietet die Public-Methode:
      ask_user_for_overlay(marker_s, parent)
    Darin kann der User ein 'overlay 1..3' (aus QSettings) wählen 
    ODER ein neues Overlay (Bild+Scale+Corner+dx+dy+Duration+FadeIn/Out) anlegen,
    das sofort in die Timeline gemalt wird.
    """

    overlaysChanged = Signal()

    def __init__(self, timeline, parent=None):
        super().__init__(parent)
        self.timeline = timeline
        self._overlays = []
        self._history_stack = []

    def add_overlay(self, ovl_dict):
        """
        ovl_dict z.B.:
        {
          "start":  30,
          "end":    50,
          "fade_in":2,
          "fade_out":1,
          "image":  "C:/temp/logo.png",
          "scale":  1.0,
          "x":      "(W-w)/2",
          "y":      "(H-h)-10"
        }
        => Speichern + timeline.add_overlay_interval(...)
        """
        start_s = ovl_dict.get("start", 0.0)
        end_s   = ovl_dict.get("end", 0.0)
        if end_s <= start_s:
            print("[WARN] add_overlay => end <= start => ignoring.")
            return
        
        self._history_stack.append(copy.deepcopy(self._overlays))    
        self._overlays.append(ovl_dict)
        # => Timeline in Blau markieren
        self.timeline.add_overlay_interval(start_s, end_s)
        self.overlaysChanged.emit()
        print("[OverlayManager] => Overlay ADDED:", ovl_dict)

    def remove_last_overlay(self):
        if self._overlays:
            self._overlays.pop()
            self.timeline.remove_last_overlay_interval()
            self.overlaysChanged.emit()

    def clear_overlays(self):
        self._overlays.clear()
        self.timeline.clear_overlay_intervals()
        self.overlaysChanged.emit()
        
        
    def undo_overlay(self):
        if not self._history_stack:
            return
        old_state = self._history_stack.pop()
        self._overlays = old_state
        self.timeline.clear_overlay_intervals()
        for ovl in self._overlays:
            self.timeline.add_overlay_interval(ovl["start"], ovl["end"])
        self.overlaysChanged.emit()   

    def get_all_overlays(self):
        return self._overlays

    # -------------------------------------------------------------------------
    # Public-Methode: ask_user_for_overlay(marker_s, parent)
    # Öffnet InsertOverlayDialog => user:
    #   A) Wählt "overlay 1..3" => Duration + fadeIn/Out => OK
    #   B) Klickt "Add New" => FullOverlayDialog => eingeben (Bild, corner, dx,dy, scale, Dauer, fadeIn/Out)
    #      => wir rufen add_overlay(...) direkt => und schließen InsertOverlayDialog
    # -------------------------------------------------------------------------
    def ask_user_for_overlay(self, marker_s: float, parent=None):
        dlg = self.InsertOverlayDialog(marker_s, self, parent)
        if dlg.exec() == QDialog.Accepted:
            # => falls user exist overlay 1..3 gewählt
            chosen_id = dlg.chosen_overlay_id
            duration_s= dlg.duration_s
            fade_in_s = dlg.fade_in_s
            fade_out_s= dlg.fade_out_s
            if not chosen_id:
                print("[OverlayManager] => user had no selection.")
                return
            # => start/end
            start_s = marker_s
            end_s   = marker_s + duration_s

            # => QSettings auslesen
            s = QSettings("KVRouite", "KVRouite")
            image_val  = s.value(f"overlay/{chosen_id}/image", "", str)
            scale_val  = s.value(f"overlay/{chosen_id}/scale", 1.0, float)
            x_expr     = s.value(f"overlay/{chosen_id}/mapped_x", "0", str)
            y_expr     = s.value(f"overlay/{chosen_id}/mapped_y", "0", str)

            ovl_dict = {
                "start":    start_s,
                "end":      end_s,
                "fade_in":  fade_in_s,
                "fade_out": fade_out_s,
                "image":    image_val,
                "scale":    scale_val,
                "x":        x_expr,
                "y":        y_expr
            }
            self.add_overlay(ovl_dict)
        else:
            print("[OverlayManager] => user canceled InsertOverlayDialog")


    # =========================================================================
    # 1) InsertOverlayDialog
    #    => Zeigt Combobox mit overlay 1..3 + Button "Add New"
    #    => Evtl. (Dauer, fadeIn/Out) => OK
    # =========================================================================
    class InsertOverlayDialog(QDialog):
        def __init__(self, marker_s, overlay_manager, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Insert Overlay")

            self._manager = overlay_manager
            self.marker_s = marker_s

            self.chosen_overlay_id = None
            self.duration_s = 5.0
            self.fade_in_s  = 1.0
            self.fade_out_s = 1.0

            layout = QVBoxLayout(self)

            lbl_info = QLabel(
                "Pick an existing Overlay from QSettings (1..3)\n"
                "Or click 'Add New' to define everything (image, dx, corner, + duration etc.)."
            )
            layout.addWidget(lbl_info)

            # => Combo overlay i
            self.combo = QComboBox()
            s = QSettings("KVRouite", "KVRouite")
            count_found = 0
            for i in [1,2,3]:
                image_path = s.value(f"overlay/{i}/image","",str).strip()
                if image_path:
                    self.combo.addItem(f"overlay {i}")
                    count_found += 1
            layout.addWidget(self.combo)

            # => Button "Add New"
            btn_new = QPushButton("Add New")
            btn_new.clicked.connect(self._on_add_new_clicked)
            layout.addWidget(btn_new)

            # => Duration
            lbl_dur = QLabel("Duration (s):")
            layout.addWidget(lbl_dur)

            self.spin_dur = QDoubleSpinBox()
            self.spin_dur.setRange(0.1,30.0)
            self.spin_dur.setValue(15.0)
            self.spin_dur.setDecimals(2)
            layout.addWidget(self.spin_dur)

            # => fade in/out
            fade_h = QHBoxLayout()
            lbl_in = QLabel("Fade In(s):")
            self.spin_in = QDoubleSpinBox()
            self.spin_in.setRange(0.0,5.0)
            self.spin_in.setValue(1.0)
            self.spin_in.setDecimals(2)
            fade_h.addWidget(lbl_in)
            fade_h.addWidget(self.spin_in)

            lbl_out= QLabel("Fade Out(s):")
            self.spin_out = QDoubleSpinBox()
            self.spin_out.setRange(0.0,5.0)
            self.spin_out.setValue(1.0)
            self.spin_out.setDecimals(2)
            fade_h.addWidget(lbl_out)
            fade_h.addWidget(self.spin_out)

            layout.addLayout(fade_h)

            # => Ok / Cancel
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
            layout.addWidget(btn_box)
            btn_box.accepted.connect(self._on_ok_clicked)
            btn_box.rejected.connect(self.reject)
            
        


        def _on_add_new_clicked(self):
            """
            Öffnet FullOverlayDialog => prompt user => 
            wenn ok => dort sofort add_overlay(...) 
            => wir schließen uns hier.
            """
            dlg = OverlayManager.FullOverlayDialog(self.marker_s, self._manager, parent=self)
            if dlg.exec() == QDialog.Accepted:
                # => Overlay ist bereits angelegt + Timeline gemalt
                self.reject()  
                return
            # => user abgebrochen => bleibe hier => user kann weiter die combo (1..3) nutzen

        def _on_ok_clicked(self):
            # => user wählt overlay i
            idx = self.combo.currentIndex()
            if idx < 0:
                self.reject()
                return

            text_ = self.combo.itemText(idx).lower().strip()
            if text_.startswith("overlay"):
                arr = text_.split()
                if len(arr)>=2:
                    self.chosen_overlay_id = arr[1]
                else:
                    self.chosen_overlay_id = "1"
            else:
                self.chosen_overlay_id = "1"

            self.duration_s = self.spin_dur.value()
            self.fade_in_s  = self.spin_in.value()
            self.fade_out_s = self.spin_out.value()

            self.accept()
            
    
        

    # =========================================================================
    # 2) FullOverlayDialog
    #    => EIGENER Dialog: (Bild, scale, corner, dx, dy, + Duration, fade_in, fade_out)
    #    => Auf OK: timeline-> add_overlay => Schließen
    # =========================================================================
    class FullOverlayDialog(QDialog):
        def __init__(self, marker_s, overlay_manager, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Add new Overlay (Full)")

            self.marker_s = marker_s
            self._manager = overlay_manager

            layout = QVBoxLayout(self)

            lbl_info = QLabel(
                "Define your new Overlay:\n"
                "Image, scale, corner, dx/dy,\n"
                "plus Duration, FadeIn, FadeOut."
            )
            layout.addWidget(lbl_info)

            # (A) Bild
            row_img = QHBoxLayout()
            lbl_img = QLabel("Image path:")
            row_img.addWidget(lbl_img)
            self.line_img = QLineEdit()
            row_img.addWidget(self.line_img)

            def on_browse(checked=None):
                f, _ = QFileDialog.getOpenFileName(self, "Select overlay image")
                if f:
                    self.line_img.setText(f)

            btn_browse = QPushButton("...")
            btn_browse.clicked.connect(on_browse)
            row_img.addWidget(btn_browse)
            layout.addLayout(row_img)

            # (B) Scale
            row_scale = QHBoxLayout()
            lbl_scale = QLabel("Scale:")
            row_scale.addWidget(lbl_scale)
            self.spin_scale = QDoubleSpinBox()
            self.spin_scale.setRange(0.0,10.0)
            self.spin_scale.setValue(1.0)
            self.spin_scale.setDecimals(3)
            row_scale.addWidget(self.spin_scale)
            layout.addLayout(row_scale)

            # (C) corner
            row_corner = QHBoxLayout()
            lbl_corner= QLabel("Corner:")
            row_corner.addWidget(lbl_corner)
            self.combo_corner= QComboBox()
            self.combo_corner.addItems([
                "top-left","top-right","bottom-left","bottom-right","center"
            ])
            row_corner.addWidget(self.combo_corner)
            layout.addLayout(row_corner)

            # (D) dx, dy
            row_offset = QHBoxLayout()
            lbl_dx = QLabel("dx:")
            self.spin_dx = QSpinBox()
            self.spin_dx.setRange(0,9999)
            self.spin_dx.setValue(10)
            row_offset.addWidget(lbl_dx)
            row_offset.addWidget(self.spin_dx)

            lbl_dy = QLabel("dy:")
            self.spin_dy = QSpinBox()
            self.spin_dy.setRange(0,9999)
            self.spin_dy.setValue(10)
            row_offset.addWidget(lbl_dy)
            row_offset.addWidget(self.spin_dy)
            layout.addLayout(row_offset)

            # (E) Duration, fade_in/out
            row_dur = QHBoxLayout()
            lbl_d = QLabel("Duration (s):")
            self.spin_dur = QDoubleSpinBox()
            self.spin_dur.setRange(0.1,99999.0)
            self.spin_dur.setValue(5.0)
            self.spin_dur.setDecimals(2)

            row_dur.addWidget(lbl_d)
            row_dur.addWidget(self.spin_dur)
            layout.addLayout(row_dur)

            row_fade = QHBoxLayout()
            lbl_in = QLabel("FadeIn(s):")
            self.spin_in = QDoubleSpinBox()
            self.spin_in.setRange(0.0,9999.0)
            self.spin_in.setValue(1.0)
            self.spin_in.setDecimals(2)
            row_fade.addWidget(lbl_in)
            row_fade.addWidget(self.spin_in)

            lbl_out= QLabel("FadeOut(s):")
            self.spin_out = QDoubleSpinBox()
            self.spin_out.setRange(0.0,9999.0)
            self.spin_out.setValue(1.0)
            self.spin_out.setDecimals(2)
            row_fade.addWidget(lbl_out)
            row_fade.addWidget(self.spin_out)
            layout.addLayout(row_fade)

            # (F) OK/Cancel
            btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            layout.addWidget(btn_box)
            btn_box.accepted.connect(self._on_ok)
            btn_box.rejected.connect(self.reject)

        def _on_ok(self):
            """
            Liest alle Felder, baut ein Overlay-Dict,
            ruft overlay_manager.add_overlay => timeline blau,
            dann accept()
            """
            image_val = self.line_img.text().strip()
            scale_val = self.spin_scale.value()
            corner_val= self.combo_corner.currentText()
            dx_val    = self.spin_dx.value()
            dy_val    = self.spin_dy.value()

            dur_val   = self.spin_dur.value()
            fade_in   = self.spin_in.value()
            fade_out  = self.spin_out.value()

            start_s   = self.marker_s
            end_s     = start_s + dur_val

            # => mapped_x,y
            if corner_val == "top-left":
                x_expr = f"{dx_val}"
                y_expr = f"{dy_val}"
            elif corner_val == "top-right":
                x_expr = f"(W-w)-{dx_val}"
                y_expr = f"{dy_val}"
            elif corner_val == "bottom-left":
                x_expr = f"{dx_val}"
                y_expr = f"(H-h)-{dy_val}"
            elif corner_val == "bottom-right":
                x_expr = f"(W-w)-{dx_val}"
                y_expr = f"(H-h)-{dy_val}"
            else:
                # center
                x_expr = f"((W-w)/2)-{dx_val}"
                y_expr = f"((H-h)/2)-{dy_val}"

            ovl_dict = {
                "start":    start_s,
                "end":      end_s,
                "fade_in":  fade_in,
                "fade_out": fade_out,
                "image":    image_val,
                "scale":    scale_val,
                "x":        x_expr,
                "y":        y_expr
            }
            self._manager.add_overlay(ovl_dict)

            self.accept()
    def remove_overlay_interval(self, start_s, end_s):
        if not self._overlays:
            return
        import copy
        # Falls du Undo möchtest:
        self._history_stack.append(copy.deepcopy(self._overlays))

        found_i = -1
        for i, ovl in enumerate(self._overlays):
            # ovl hat "start", "end"
            if abs(ovl["start"] - start_s) < 0.001 and abs(ovl["end"] - end_s) < 0.001:
                found_i = i
                break
        if found_i >= 0:
            self._overlays.pop(found_i)
            self.timeline.clear_overlay_intervals()
            for ovl in self._overlays:
                self.timeline.add_overlay_interval(ovl["start"], ovl["end"])
            self.overlaysChanged.emit()
            print(f"[OverlayManager] removed overlay {start_s:.2f}..{end_s:.2f}")

