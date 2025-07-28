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

# widgets/video_control_widget.py

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QStyle, QDialog, QVBoxLayout, QFrame
)
from PySide6.QtCore import Signal, Qt, QRegularExpression, QSize
from PySide6.QtGui import QRegularExpressionValidator, QCursor, QIcon

from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize

from core.gpx_parser import is_gpx_video_shift_set

class VideoControlWidget(QWidget):
    play_pause_clicked       = Signal()
    stop_clicked             = Signal()
    goto_video_end_clicked   = Signal()
    step_value_changed       = Signal(str)
    multiplier_value_changed = Signal(str)
    backward_clicked         = Signal()
    forward_clicked          = Signal()
    goToEndClicked           = Signal()
    timeHMSSetClicked        = Signal(int, int, int)
    markBClicked             = Signal()
    markEClicked             = Signal()
    cutClicked               = Signal()
    #undoClicked              = Signal()
    markClearClicked         = Signal()
#safeClicked              = Signal()
    syncClicked              = Signal()
    set_beginClicked         = Signal()  
    overlayClicked        = Signal()
    setSyncClicked           = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5,5,5,5)
        layout.setSpacing(5)

        self.play_pause_button = QPushButton()
        self.play_pause_button.setIcon(
            self.style().standardIcon(QStyle.SP_MediaPlay)
        )
        self.play_pause_button.clicked.connect(self.play_pause_clicked.emit)
        layout.addWidget(self.play_pause_button)
        """
        self.stop_button = QPushButton()
        self.stop_button.setIcon(
            self.style().standardIcon(QStyle.SP_MediaStop)
        )
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_button)
        """
        icon_size = self.style().pixelMetric(QStyle.PM_ToolBarIconSize)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(QIcon("icon/go_to_start_icon_padded.png"))
        self.stop_button.setIconSize(QSize(icon_size, icon_size))
        play_size = self.play_pause_button.sizeHint()
        self.stop_button.setMaximumSize(play_size)    
        
        self.stop_button.setToolTip("Goto Start (Second 0)")
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_button)

        self.goto_end = QPushButton()
        self.goto_end.setIcon(QIcon("icon/go_to_end.png"))
        self.goto_end.setIconSize(QSize(icon_size, icon_size))
        self.goto_end.setMaximumSize(play_size)    
        
        self.goto_end.setToolTip("Goto End (last frame)")
        self.goto_end.clicked.connect(self.goto_video_end_clicked.emit)
        layout.addWidget(self.goto_end)
        
        self._step_values = ["s", "m", "k", "f"]  # <-- "f" ergänzt
        self._step_index = 0
        self.step_button = QPushButton(self._step_values[self._step_index])
        self.step_button.setToolTip("Choose the Step-Value")
        self.step_button.setFixedSize(40, 24)
        self.step_button.clicked.connect(self.on_step_button_clicked)
        layout.addWidget(self.step_button)

        self._multiplier_values = ["1x", "2x", "4x", "8x", "15x", "30x"]
        self._multiplier_index = 0
        self.multiplier_button = QPushButton(self._multiplier_values[self._multiplier_index])
        self.multiplier_button.setToolTip("Choose the Multiplier of the Stepper")
        self.multiplier_button.setFixedSize(40, 24)
        self.multiplier_button.clicked.connect(self.on_multiplier_button_clicked)
        layout.addWidget(self.multiplier_button)

        self.backward_button = QPushButton()
        self.backward_button.setToolTip("Step backwards: Step x Multiplier")
        self.backward_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekBackward))
        self.backward_button.clicked.connect(self.backward_clicked.emit)
        layout.addWidget(self.backward_button)

        self.forward_button = QPushButton()
        self.forward_button.setToolTip("Step forwards: Step x Multiplier")
        self.forward_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSeekForward))
        self.forward_button.clicked.connect(self.forward_clicked.emit)
        layout.addWidget(self.forward_button)

        self.hour_edit = QLineEdit("00")
        self.hour_edit.setVisible(False)
        self.hour_edit.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-9]{2}$")))
        layout.addWidget(self.hour_edit)

        self.min_edit = QLineEdit("00")
        self.min_edit.setVisible(False)
        self.min_edit.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-5]\\d$")))
        layout.addWidget(self.min_edit)

        self.sec_edit = QLineEdit("00")
        self.sec_edit.setVisible(False)
        self.sec_edit.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-5]\\d$")))
        layout.addWidget(self.sec_edit)

        self.time_btn = QPushButton("SetTime")
        self.time_btn.setToolTip("Jump to video time")

        self.time_btn.setFixedWidth(60)
        self.time_btn.clicked.connect(self._on_time_btn_clicked)
        layout.addWidget(self.time_btn)
        
        self._current_h = 0
        self._current_m = 0
        self._current_s = 0
        
        
       
        

        self.markB_button = QPushButton("[-")
        self.markB_button.setToolTip("Mark the Begin of the Cut")
        self.markB_button.setFixedWidth(40)
        self.markB_button.clicked.connect(self._on_markB_clicked)
        layout.addWidget(self.markB_button)

        self.markE_button = QPushButton("-]") 
        self.markE_button.setToolTip("Mark the End of the Cut")
        self.markE_button.setFixedWidth(40)
        self.markE_button.clicked.connect(self._on_markE_clicked)
        layout.addWidget(self.markE_button)
        
        self.clear_button = QPushButton("x")
        self.clear_button.setToolTip("Deselect the marked Area")
        self.clear_button.setFixedWidth(30)
        self.clear_button.clicked.connect(self.markClearClicked.emit)
        layout.addWidget(self.clear_button)

        self.cut_button = QPushButton("cut")
        self.cut_button.setToolTip("Cut the marked Area \nChoose AutoCutVideo+GPX in the config to cut the GPX-Area too")
        self.cut_button.setFixedWidth(40)
        self.cut_button.clicked.connect(self.cutClicked.emit)
        layout.addWidget(self.cut_button)
        
        
                
        self.set_begin_button = QPushButton()
        self.set_begin_button.setIcon(QIcon("icon/cut_begin.png")) 
        self.set_begin_button.setIconSize(QSize(20, 20))
        self.set_begin_button.setToolTip("Cut the Begin of the Video and/or the GPX")
        self.set_begin_button.clicked.connect(self.set_beginClicked.emit)
        layout.addWidget(self.set_begin_button)
        
        
        self.go_to_end_button = QPushButton()
        self.go_to_end_button.setIcon(QIcon("icon/cut_end.png")) 
        self.go_to_end_button.setIconSize(QSize(20, 20))
        self.go_to_end_button.setToolTip("Cut the End of the Video and the GPX")
        
        self.go_to_end_button.clicked.connect(self.goToEndClicked.emit)
        layout.addWidget(self.go_to_end_button)

        self.set_sync_button = QPushButton()
        self.set_sync_button.setIcon(QIcon("icon/video_gpx_sync.png")) 
        self.set_sync_button.setIconSize(QSize(25, 25))
        self.set_sync_button.setToolTip("Set current video frame synchronized with selected GPX Point")
        self.set_sync_button.clicked.connect(self.setSyncClicked.emit)
        self.update_set_sync_highlight()
        layout.addWidget(self.set_sync_button)

        self.sync_button = QPushButton("GSync")
        self.sync_button.setToolTip("Select the corresponding GPX-Point")
        self.sync_button.setFixedWidth(45)
        self.sync_button.clicked.connect(self.syncClicked.emit)
        layout.addWidget(self.sync_button)
        
        
        self.ovl_button = QPushButton("Ovl")
        self.ovl_button.setToolTip("Some Overlay or future function")
        self.ovl_button.setFixedWidth(40)
        self.ovl_button.clicked.connect(self._on_ovl_clicked)
        layout.addWidget(self.ovl_button)
        self.ovl_button.hide()   # Standard: ausgeblendet
        
        separator = QFrame(self)
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        # | AutoCut Video+GPX Button
        self.autocut_button = QPushButton()
        self.autocut_button.setToolTip("Toggle AutoCut for Video and GPX")
        self.autocut_button.setFixedSize(36, 36)
        self.autocut_button.clicked.connect(self._on_autocut_toggle_clicked)
        layout.addWidget(self.autocut_button)

        # Icons laden
        
        self.icon_autocut_on = QIcon("icon/vg_icon_on2.png")
        self.icon_autocut_off = QIcon("icon/vg_icon_off.png")
        # Default setzen
        self._update_autocut_icon()
        self.autocut_button.setVisible(False)  # nur bei Copy- oder Encode-Mode

        layout.addStretch()
        self.activate_controls(False)  # desactivate all buttons initially
        
        
    def _on_autocut_toggle_clicked(self):
        mw = self._find_mainwindow()
        if not mw:
            return
        action = getattr(mw, "action_auto_sync_video", None)
        if action:
            action.setChecked(not action.isChecked())
            self._update_autocut_icon()
            mw._on_auto_sync_video_toggled(action.isChecked())

    def _update_autocut_icon(self):
        mw = self._find_mainwindow()
        if not mw or not hasattr(mw, "action_auto_sync_video"):
            return
        is_on = mw.action_auto_sync_video.isChecked()
        if hasattr(self, "autocut_button"):
            self.autocut_button.setIcon(self.icon_autocut_on if is_on else self.icon_autocut_off)
    
    def activate_controls(self, enabled: bool = True):
        self.play_pause_button.setEnabled(enabled)
        self.stop_button.setEnabled(enabled)
        self.step_button.setEnabled(enabled)
        self.multiplier_button.setEnabled(enabled)
        self.backward_button.setEnabled(enabled)
        self.forward_button.setEnabled(enabled)
        self.time_btn.setEnabled(enabled)
        
        self.sync_button.setEnabled(enabled and is_gpx_video_shift_set())
        self.set_sync_button.setEnabled(enabled)
        self.update_set_sync_highlight()

    def update_set_sync_highlight(self):
        color= "none" if  is_gpx_video_shift_set() else "#ff0000"  # Red or none
        self.set_sync_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};     /* Red */
            }}
            QPushButton:hover {{
                background-color: #005fa3;
            }}
        """)
    
    def set_editing_mode(self, enabled: bool):
        """
        Schaltet Buttons wie MarkB, MarkE, Clear, Cut, etc. an oder aus.
        """
        self.markB_button.setVisible(enabled)
        self.markE_button.setVisible(enabled)
        self.clear_button.setVisible(enabled)
        self.cut_button.setVisible(enabled)
        
        self.go_to_end_button.setVisible(enabled and is_gpx_video_shift_set())
        self.set_begin_button.setVisible(enabled and is_gpx_video_shift_set())
        self.autocut_button.setVisible(enabled and is_gpx_video_shift_set())
        self._update_autocut_icon()
        
    def show_ovl_button(self, show: bool):
        """
        Zeigt oder versteckt den Ovl-Button.
        """
        if show:
            self.ovl_button.show()
        else:
            self.ovl_button.hide()    


    def _on_markB_clicked(self):
        # 1) erst Sync-Funktion aufrufen:
        #self.syncClicked.emit()
        # 2) danach das 'eigentliche' MarkB-Signal:
        self.markBClicked.emit()

    def _on_markE_clicked(self):
        # 1) erst Sync-Funktion aufrufen:
        #self.syncClicked.emit()
        # 2) danach das 'eigentliche' MarkE-Signal:
        self.markEClicked.emit()    

    def update_play_pause_icon(self, is_playing):
        if is_playing:
            self.play_pause_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaPause)
            )
        else:
            self.play_pause_button.setIcon(
                self.style().standardIcon(QStyle.SP_MediaPlay)
            )

    def on_step_button_clicked(self):
        self._step_index = (self._step_index + 1) % len(self._step_values)
        new_value = self._step_values[self._step_index]
        self.step_button.setText(new_value)
        self.step_value_changed.emit(new_value)

    def on_multiplier_button_clicked(self):
        self._multiplier_index = (self._multiplier_index + 1) % len(self._multiplier_values)
        new_value = self._multiplier_values[self._multiplier_index]
        self.multiplier_button.setText(new_value)
        self.multiplier_value_changed.emit(new_value)
    
    def set_hms_time(self, hh: int, mm: int, ss: int):
        self._current_h = hh
        self._current_m = mm
        self._current_s = ss    
        
    def _on_time_btn_clicked(self):
        """
        Beim Klick auf "SetTime"-Button ein Popup öffnen,
        das mit (self._current_h, _current_m, _current_s) vorbelegt ist.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Set Time")

        vbox = QVBoxLayout(dlg)
        row = QHBoxLayout()

        # Vorbelegung mit unseren internen h,m,s
        hh_str = f"{self._current_h:02d}"
        mm_str = f"{self._current_m:02d}"
        ss_str = f"{self._current_s:02d}"

        popup_h = QLineEdit(hh_str, dlg)
        popup_h.setFixedWidth(25)
        popup_h.setMaxLength(2)
        popup_h.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-9]{2}$")))

        popup_m = QLineEdit(mm_str, dlg)
        popup_m.setFixedWidth(25)
        popup_m.setMaxLength(2)
        popup_m.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-5]\\d$")))

        popup_s = QLineEdit(ss_str, dlg)
        popup_s.setFixedWidth(25)
        popup_s.setMaxLength(2)
        popup_s.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-5]\\d$")))

        row.addWidget(popup_h)
        row.addWidget(QLabel(":", dlg))
        row.addWidget(popup_m)
        row.addWidget(QLabel(":", dlg))
        row.addWidget(popup_s)

        row_box = QHBoxLayout()
        row_box.addStretch()
        row_box.addLayout(row)
        row_box.addStretch()
        vbox.addLayout(row_box)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_set = QPushButton("Set", dlg)
        btn_set.clicked.connect(
            lambda: self._popup_accepted(dlg, popup_h, popup_m, popup_s)
        )
        btn_box.addWidget(btn_set)
        btn_box.addStretch()
        vbox.addLayout(btn_box)

        dlg.setModal(True)
        dlg.move(QCursor.pos())
        dlg.exec()    
    

    def _show_time_popup_at_cursor(self, hh_str: str, mm_str: str, ss_str: str):


        dlg = QDialog(self)
        dlg.setWindowTitle("Set time")

        vbox = QVBoxLayout(dlg)
        row = QHBoxLayout()
        popup_h = QLineEdit(hh_str, dlg)
        popup_h.setFixedWidth(25)
        popup_h.setMaxLength(2)
        popup_h.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-9]{2}$"), popup_h))

        popup_m = QLineEdit(mm_str, dlg)
        popup_m.setFixedWidth(25)
        popup_m.setMaxLength(2)
        popup_m.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-5]\\d$"), popup_m))

        popup_s = QLineEdit(ss_str, dlg)
        popup_s.setFixedWidth(25)
        popup_s.setMaxLength(2)
        popup_s.setValidator(QRegularExpressionValidator(QRegularExpression("^[0-5]\\d$"), popup_s))

        row.addWidget(popup_h)
        row.addWidget(QLabel(":", dlg))
        row.addWidget(popup_m)
        row.addWidget(QLabel(":", dlg))
        row.addWidget(popup_s)

        row_box = QHBoxLayout()
        row_box.addStretch()
        row_box.addLayout(row)
        row_box.addStretch()
        vbox.addLayout(row_box)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_set = QPushButton("Set", dlg)
        btn_set.clicked.connect(
            lambda: self._popup_accepted(dlg, popup_h, popup_m, popup_s)
        )
        btn_box.addWidget(btn_set)
        btn_box.addStretch()
        vbox.addLayout(btn_box)

        dlg.setModal(True)
        dlg.move(QCursor.pos())
        dlg.exec()

    def _popup_accepted(self, dlg, edit_h, edit_m, edit_s):
        txtH = edit_h.text().strip()
        txtM = edit_m.text().strip()
        txtS = edit_s.text().strip()

        hh = int(txtH) if txtH.isdigit() else 0
        mm = int(txtM) if txtM.isdigit() else 0
        ss = int(txtS) if txtS.isdigit() else 0

        # Speichere es erneut (oder schicke ein Signal)
        self._current_h = hh
        self._current_m = mm
        self._current_s = ss

        # => Optional: Signal, wenn du das im MainWindow weiterverarbeiten willst
        self.timeHMSSetClicked.emit(hh, mm, ss)

        dlg.close()
        
    def _on_ovl_clicked(self):
        """
        Wird aufgerufen, wenn der Ovl-Button geklickt wird.
        Hier könntest du z.B. ein Signal feuern oder direkt eine Aktion machen.
        """

        self.overlayClicked.emit()
        
    def _find_mainwindow(self):
        p = self.parent()
        while p:
            if p.__class__.__name__ == "MainWindow":
                return p
            p = p.parent()
        return None        
    
    