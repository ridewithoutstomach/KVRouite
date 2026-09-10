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
from core import theme

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
    
    markClearClicked         = Signal()

    syncClicked              = Signal()
    set_beginClicked         = Signal()  
    overlayClicked        = Signal()
    setSyncClicked           = Signal()
    gotoNextEditRequested   = Signal()
    #: Rechtsklick auf Goto Start: zur vorigen Schnittkante oder Naht.
    gotoPrevEditRequested   = Signal()
    #: Seite A (Audio, ab 7.0): B-E als Sprechstelle anlegen, Suchlauf,
    #: Empfindlichkeit 1-5, und der Wechsel der Seite ("video"/"audio").
    voiceClicked            = Signal()
    findVoicesClicked       = Signal()
    sensitivityChanged      = Signal(int)
    seiteGewechselt         = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5,5,5,5)
        layout.setSpacing(5)

        # Zwei Seiten in derselben Leiste (ab 7.0): V wie bisher (Schnitt,
        # Sync, Overlay), A fuer die Sprechstellen des Voice Removers. Der
        # Platz ist knapp - die App soll sich klein ziehen lassen -, darum
        # wechseln die Knoepfe statt sich anzureihen. Transport, [-, -] und
        # x stehen auf beiden Seiten. Den Knopf gibt es nur im Encode-Mode
        # mit Voice-Zusatz (voice_seite_anbieten).
        self._seite = "video"
        self._edit = False
        self._cut = False
        self._ovl = False
        self._audio_da = False
        self.seite_button = QPushButton()
        self.seite_button.setToolTip(
            "Switch the buttons: film = video (cut, sync, overlay), "
            "speaker = audio (mark the stretches with voices)")
        self.seite_button.setFixedWidth(30)
        self.seite_button.setIconSize(QSize(20, 20))
        self.seite_button.clicked.connect(self._seite_umschalten)
        layout.addWidget(self.seite_button)
        self.seite_button.hide()

        self.play_pause_button = QPushButton()
        self._laeuft = False
        self.play_pause_button.setIcon(
            theme.standardsymbol(self, QStyle.SP_MediaPlay)
        )
        self.play_pause_button.clicked.connect(self.play_pause_clicked.emit)
        layout.addWidget(self.play_pause_button)
        
        icon_size = self.style().pixelMetric(QStyle.PM_ToolBarIconSize)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(theme.icon("icon/go_to_start_icon_padded.png"))
        self.stop_button.setIconSize(QSize(icon_size, icon_size))
        play_size = self.play_pause_button.sizeHint()
        self.stop_button.setMaximumSize(play_size)    
        
        self.stop_button.setToolTip(
            "Goto Start (second 0)\n"
            "Right-click: jump back to the previous cut edge or file join")
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_button)
        # Gegenstueck zum Rechtsklick auf Goto End (seit 6.14): rueckwaerts
        # von Kante zu Kante.
        self.stop_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.stop_button.customContextMenuRequested.connect(
            lambda _pos: self.gotoPrevEditRequested.emit())

        self.goto_end = QPushButton()
        self.goto_end.setIcon(theme.icon("icon/go_to_end.png"))
        self.goto_end.setIconSize(QSize(icon_size, icon_size))
        self.goto_end.setMaximumSize(play_size)    
        
        self.goto_end.setToolTip(
            "Goto End (last frame)\n"
            "Right-click: jump to the next cut edge or file join")
        self.goto_end.clicked.connect(self.goto_video_end_clicked.emit)
        layout.addWidget(self.goto_end)
        
        self.goto_end.setContextMenuPolicy(Qt.CustomContextMenu)
        self.goto_end.customContextMenuRequested.connect(lambda _pos: self.gotoNextEditRequested.emit())
        
        
        # Ohne "k": den Keyframe-Schritt gibt es nur im Copy-Mode, und beim
        # Start steht der Bearbeitungsmodus auf "off". _set_edit_mode()
        # setzt die Liste danach passend (siehe set_step_values).
        self._step_values = ["s", "m", "f", "c"]
        self._step_index = 0
        self.step_button = QPushButton(self._step_values[self._step_index])
        self.step_button.setToolTip(
            "Choose the Step-Value\n"
            "s = seconds, m = minutes, f = single frame\n"
            "c = cut edges"
        )
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
        self.backward_button.setIcon(theme.standardsymbol(self, QStyle.SP_MediaSeekBackward))
        self.backward_button.clicked.connect(self.backward_clicked.emit)
        layout.addWidget(self.backward_button)

        self.forward_button = QPushButton()
        self.forward_button.setToolTip("Step forwards: Step x Multiplier")
        self.forward_button.setIcon(theme.standardsymbol(self, QStyle.SP_MediaSeekForward))
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
        
        
                
        self.cut_begin_button = QPushButton()
        self.cut_begin_button.setIcon(theme.icon("icon/cut_begin.png")) 
        self.cut_begin_button.setIconSize(QSize(20, 20))
        self.cut_begin_button.setToolTip("Cut the Begin of the Video and the GPX")
        self.cut_begin_button.clicked.connect(self.set_beginClicked.emit)
        layout.addWidget(self.cut_begin_button)
        
        
        self.cut_end_button = QPushButton()
        self.cut_end_button.setIcon(theme.icon("icon/cut_end.png")) 
        self.cut_end_button.setIconSize(QSize(20, 20))
        self.cut_end_button.setToolTip("Cut the End of the Video and the GPX")
        
        self.cut_end_button.clicked.connect(self.goToEndClicked.emit)
        layout.addWidget(self.cut_end_button)

        self.set_sync_button = QPushButton()
        self.set_sync_button.setIcon(theme.icon("icon/vg_sync_ring.png")) 
        self.set_sync_button.setIconSize(QSize(20, 20))
        self.set_sync_button.setToolTip("Set current video frame synchronized with selected GPX Point")
        self.set_sync_button.clicked.connect(self.setSyncClicked.emit)
        self.update_set_sync_highlight()
        layout.addWidget(self.set_sync_button)

        self.sync_button = QPushButton("GSync")
        self.sync_button.setToolTip("Select the corresponding GPX-Point")
        self.sync_button.setFixedWidth(50)
        self.sync_button.clicked.connect(self.syncClicked.emit)
        layout.addWidget(self.sync_button)
        
        
        self.ovl_button = QPushButton("Ovl")
        self.ovl_button.setToolTip("Some Overlay or future function")
        self.ovl_button.setFixedWidth(40)
        self.ovl_button.clicked.connect(self._on_ovl_clicked)
        layout.addWidget(self.ovl_button)
        self.ovl_button.hide()   # Standard: ausgeblendet

        # Seite A: Voice (B-E als Sprechstelle, wie Ovl ein Overlay anlegt),
        # Find (Suchlauf ueber alle Videos), Sens (Empfindlichkeit 1-5).
        self.voice_button = QPushButton("Voice")
        self.voice_button.setToolTip(
            "Mark the area between [- and -] as a stretch with voices.\n"
            "The voice remover then works only in the marked stretches\n"
            "(right-click a stretch in the timeline to change or remove it).")
        self.voice_button.setFixedWidth(46)
        self.voice_button.clicked.connect(self.voiceClicked.emit)
        layout.addWidget(self.voice_button)
        self.voice_button.hide()

        self.find_button = QPushButton("Detect")
        self.find_button.setToolTip(
            "Detect the voices in all loaded videos and mark them at once.\n"
            "Replaces the marked stretches. Detection is never complete -\n"
            "check the result in the timeline or the Audio Zoom.")
        self.find_button.setFixedWidth(50)
        self.find_button.clicked.connect(self.findVoicesClicked.emit)
        layout.addWidget(self.find_button)
        self.find_button.hide()

        self._empfindlichkeit = 3
        self.sens_button = QPushButton("Sens 3")
        self.sens_button.setToolTip(
            "Sensitivity of Detect: 1 = only clear speech, 7 = everything "
            "that might be")
        self.sens_button.setFixedWidth(56)
        self.sens_button.clicked.connect(self._sens_menue)
        layout.addWidget(self.sens_button)
        self.sens_button.hide()

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
        
        # Diese beiden sind farbig (rot/gruen) - theme.icon() laesst sie in
        # Ruhe, sie stehen hier nur der Einheitlichkeit halber.
        self.icon_autocut_on = theme.icon("icon/vg_icon_on2.png")
        self.icon_autocut_off = theme.icon("icon/vg_icon_off.png")
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
        self.goto_end.setEnabled(enabled)
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
    
    def set_editing_mode(self, edit: bool, cut: bool):
        """
        Schaltet Buttons wie MarkB, MarkE, Clear, Cut, etc. an oder aus.
        """
        self._edit = bool(edit)
        self._cut = bool(cut)
        self._seite_anwenden()
        self._update_autocut_icon()

    def show_ovl_button(self, show: bool):
        """
        Zeigt oder versteckt den Ovl-Button.
        """
        self._ovl = bool(show)
        self._seite_anwenden()

    # ---- Seite V / A -------------------------------------------------
    def voice_seite_anbieten(self, an: bool):
        """Den Seitenknopf zeigen (Encode-Mode mit Voice-Zusatz). Ohne ihn
        steht die Leiste auf Seite V."""
        self._audio_da = bool(an)
        if not self._audio_da and self._seite != "video":
            self._seite = "video"
            self.seiteGewechselt.emit(self._seite)
        self._seite_anwenden()

    def seite(self) -> str:
        return self._seite

    def _seite_umschalten(self):
        self._seite = "audio" if self._seite == "video" else "video"
        self._seite_anwenden()
        self.seiteGewechselt.emit(self._seite)

    def _seite_anwenden(self):
        """Sichtbarkeit aller Knoepfe aus Bearbeitungsmodus und Seite. Eine
        Stelle dafuer, damit ein Seitenwechsel nichts vergisst, was
        set_editing_mode oder show_ovl_button zuvor gesetzt haben."""
        edit, cut, ovl = self._edit, self._cut, self._ovl
        audio = self._seite == "audio" and self._audio_da and edit
        self.seite_button.setVisible(edit and self._audio_da)
        self.seite_button.setIcon(self._seiten_symbol("audio" if audio else "video"))
        # Auf beiden Seiten
        self.markB_button.setVisible(edit)
        self.markE_button.setVisible(edit)
        self.clear_button.setVisible(edit)
        # Seite V
        self.time_btn.setVisible(not audio)
        self.cut_button.setVisible(edit and not audio)
        self.cut_end_button.setVisible(cut and not audio)
        self.cut_begin_button.setVisible(cut and not audio)
        self.set_sync_button.setVisible(not audio)
        self.sync_button.setVisible(not audio)
        self.ovl_button.setVisible(ovl and not audio)
        self.autocut_button.setVisible(edit and not audio and is_gpx_video_shift_set())
        # Seite A
        self.voice_button.setVisible(audio)
        self.find_button.setVisible(audio)
        self.sens_button.setVisible(audio)
        if audio:
            self.markB_button.setToolTip("Mark the Begin of the stretch with voices")
            self.markE_button.setToolTip("Mark the End of the stretch with voices")
        else:
            self.markB_button.setToolTip("Mark the Begin of the Cut")
            self.markE_button.setToolTip("Mark the End of the Cut")

    def _seiten_symbol(self, art: str) -> QIcon:
        """Das Symbol des Seitenknopfs, gezeichnet statt geladen: ein
        Filmstreifen fuer V, ein Lautsprecher fuer A - in der Textfarbe der
        Farbgebung, deshalb ohne eigene Dateien fuer hell und dunkel."""
        from PySide6.QtGui import QPixmap, QPainter, QPen, QBrush, QPolygonF, QPainterPath
        from PySide6.QtCore import QPointF, QRectF, Qt as _Qt
        farbe = self.palette().buttonText().color()
        bild = QPixmap(20, 20)
        bild.fill(_Qt.transparent)
        p = QPainter(bild)
        p.setRenderHint(QPainter.Antialiasing, True)
        if art == "audio":
            # Lautsprecher: Kasten, Trichter, zwei Schallboegen.
            p.setPen(_Qt.NoPen)
            p.setBrush(QBrush(farbe))
            p.drawRect(QRectF(2, 7, 4, 6))
            p.drawPolygon(QPolygonF([QPointF(6, 7), QPointF(11, 3), QPointF(11, 17), QPointF(6, 13)]))
            p.setBrush(_Qt.NoBrush)
            p.setPen(QPen(farbe, 1.6))
            for r in (3.0, 6.0):
                pfad = QPainterPath()
                pfad.arcMoveTo(QRectF(11 - r, 10 - r, 2 * r, 2 * r), 45)
                pfad.arcTo(QRectF(11 - r, 10 - r, 2 * r, 2 * r), 45, -90)
                p.drawPath(pfad)
        else:
            # Filmstreifen: Rahmen, Perforation oben und unten, ein Bild.
            p.setPen(QPen(farbe, 1.4))
            p.setBrush(_Qt.NoBrush)
            p.drawRoundedRect(QRectF(2, 3, 16, 14), 1.5, 1.5)
            p.setPen(_Qt.NoPen)
            p.setBrush(QBrush(farbe))
            for x in (4, 8, 12, 15):
                p.drawRect(QRectF(x, 4.5, 2, 1.8))
                p.drawRect(QRectF(x, 13.7, 2, 1.8))
            p.drawRect(QRectF(5, 8, 10, 4))
        p.end()
        return QIcon(bild)

    def set_sensitivity(self, wert: int):
        self._empfindlichkeit = max(1, min(7, int(wert)))
        self.sens_button.setText("Sens %d" % self._empfindlichkeit)

    def sensitivity(self) -> int:
        return self._empfindlichkeit

    def _sens_menue(self):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QActionGroup
        menue = QMenu(self)
        gruppe = QActionGroup(menue)
        namen = {1: "1 - only clear speech", 2: "2", 3: "3 - default",
                 4: "4", 5: "5", 6: "6 - voices in the wind",
                 7: "7 - everything that might be"}
        for stufe in range(1, 8):
            a = menue.addAction(namen[stufe])
            a.setCheckable(True)
            a.setChecked(stufe == self._empfindlichkeit)
            a.setData(stufe)
            gruppe.addAction(a)
        gewaehlt = menue.exec(self.sens_button.mapToGlobal(
            self.sens_button.rect().bottomLeft()))
        if gewaehlt is not None and gewaehlt.data() != self._empfindlichkeit:
            self.set_sensitivity(gewaehlt.data())
            self.sensitivityChanged.emit(self._empfindlichkeit)


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
        # Der Zustand wird gemerkt, damit nach einem Wechsel der Farbgebung
        # wieder das richtige Zeichen gesetzt werden kann.
        self._laeuft = bool(is_playing)
        self.play_pause_button.setIcon(theme.standardsymbol(
            self, QStyle.SP_MediaPause if self._laeuft else QStyle.SP_MediaPlay))

    def set_step_values(self, values):
        """Legt fest, welche Schrittweiten der Knopf durchschaltet.

        Der Keyframe-Schritt "k" hat nur im Copy-Mode einen Sinn: dort landet
        ein Schnitt am naechsten Keyframe, und "k" zeigt, wo das waere. Im
        Encode-Mode liegt jeder Schnitt genau auf dem gewaehlten Bild, und der
        Keyframe-Index wird dort gar nicht erst gebaut. Statt "k" anzubieten
        und dann eine Fehlermeldung zu zeigen, wird er ausgeblendet.

        Die aktuelle Auswahl bleibt erhalten, wenn es sie noch gibt; sonst
        faellt sie auf den ersten Eintrag zurueck und der Wechsel wird gemeldet.
        """
        werte = [v for v in values if v]
        if not werte or werte == self._step_values:
            return
        vorher = self._step_values[self._step_index] if self._step_values else None
        self._step_values = werte
        if vorher in werte:
            self._step_index = werte.index(vorher)
            geaendert = False
        else:
            self._step_index = 0
            geaendert = True
        self.step_button.setText(self._step_values[self._step_index])
        self.step_button.setToolTip(
            "Choose the Step-Value\n"
            + ", ".join({
                "s": "s = seconds", "m": "m = minutes",
                "k": "k = keyframes", "f": "f = single frame",
                "c": "c = cut edges",
            }.get(v, v) for v in self._step_values))
        if geaendert:
            self.step_value_changed.emit(self._step_values[self._step_index])

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
        
    def theme_aktualisieren(self):
        """Symbole neu holen, wenn die Farbgebung gewechselt hat.

        Die einfarbigen Zeichnungen werden von core/theme.icon() umgekehrt -
        das Ergebnis haengt an der Farbgebung und muss nach dem Umschalten
        neu gesetzt werden.
        """
        self.stop_button.setIcon(theme.icon("icon/go_to_start_icon_padded.png"))
        self.goto_end.setIcon(theme.icon("icon/go_to_end.png"))
        self.cut_begin_button.setIcon(theme.icon("icon/cut_begin.png"))
        self.cut_end_button.setIcon(theme.icon("icon/cut_end.png"))
        self.set_sync_button.setIcon(theme.icon("icon/vg_sync_ring.png"))
        self.play_pause_button.setIcon(theme.standardsymbol(
            self, QStyle.SP_MediaPause if self._laeuft else QStyle.SP_MediaPlay))
        self.backward_button.setIcon(
            theme.standardsymbol(self, QStyle.SP_MediaSeekBackward))
        self.forward_button.setIcon(
            theme.standardsymbol(self, QStyle.SP_MediaSeekForward))
        self.icon_autocut_on = theme.icon("icon/vg_icon_on2.png")
        self.icon_autocut_off = theme.icon("icon/vg_icon_off.png")
        self._update_autocut_icon()
        self._seite_anwenden()      # Seitensymbol in der neuen Textfarbe

    def _find_mainwindow(self):
        p = self.parent()
        while p:
            if p.__class__.__name__ == "MainWindow":
                return p
            p = p.parent()
        return None        
    
    