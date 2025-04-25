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
#test
import platform
import mpv
import math

from PySide6.QtWidgets import (
    QWidget, QGridLayout, QFrame, QLabel, QVBoxLayout
)
from PySide6.QtCore import Qt, QTimer, Signal

class VideoEditorWidget(QWidget):
    """
    Ein mpv-basierter Video-Player, der die alten Methoden (show_first_frame_at_index,
    set_playback_rate, etc.) bereitstellt, damit dein restlicher Code weiter funktioniert.
    Er kann mehrere Videos in die mpv-Playlist laden und nacheinander abspielen.
    
    Ob du 'end-file' auswertest, liegt bei dir. Siehe _on_mpv_event(...).
    """

    play_ended = Signal()  # z.B. wenn das letzte Video fertig ist

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cut_intervals = []
    
        self._time_mode = "global"  # default
        self._final_time_callback = None   # optional
        
        # Haupt-Layout
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Ein Frame als Video-Anzeige
        self.video_frame = QFrame(self)
        self.video_frame.setStyleSheet("background:black;")
        layout.addWidget(self.video_frame, 0, 0)
        layout.setRowStretch(0, 1)
        layout.setColumnStretch(0, 1)

        # Oben Rechts: Speed-Label
        self.speed_label = QLabel("", self)
        self.speed_label.setStyleSheet("color:white; background-color:rgba(0,0,0,120); padding:2px;")
        self.speed_label.hide()
        layout.addWidget(self.speed_label, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight)

        # Oben Rechts: Aktuelle Zeit
        self.current_time_widget = QWidget(self)
        vbox_time = QVBoxLayout(self.current_time_widget)
        vbox_time.setContentsMargins(0,20,0,0)
        vbox_time.setSpacing(0)
        vbox_time.setAlignment(Qt.AlignTop | Qt.AlignRight)

        self.current_time_label = QLabel("", self.current_time_widget)
        self.current_time_label.setTextFormat(Qt.RichText)
        self.current_time_label.setStyleSheet(
            "background-color:rgba(0,0,0,120); color: yellow; font-size:16px;"
            "padding:2px;"
        )
        vbox_time.addWidget(self.current_time_label)
        layout.addWidget(self.current_time_widget, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight)

        # Extra: Edit-Status
        self.edit_status_widget = QWidget(self)
        self.edit_status_widget.setMaximumWidth(65)

        vbox_edit = QVBoxLayout(self.edit_status_widget)
        vbox_edit.setContentsMargins(0, 50, 0, 0)
        vbox_edit.setSpacing(0)

        self.edit_status_label = QLabel("", self.edit_status_widget)
        self.acut_status_label = QLabel("", self.edit_status_widget)
        vbox_edit.addWidget(self.edit_status_label)
        vbox_edit.addWidget(self.acut_status_label)
        layout.addWidget(self.edit_status_widget, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight)

        # Unten Links: total_length + cut_time
        self.right_time_widget = QWidget(self)
        vbox_right_time = QVBoxLayout(self.right_time_widget)
        vbox_right_time.setContentsMargins(0,0,0,0)
        vbox_right_time.setSpacing(0)
        vbox_right_time.setAlignment(Qt.AlignRight)

        self.total_length_label = QLabel("", self.right_time_widget)
        self.total_length_label.setStyleSheet("color:white; padding-left:5px;")
        vbox_right_time.addWidget(self.total_length_label)

        self.cut_time_label = QLabel("", self.right_time_widget)
        self.cut_time_label.setStyleSheet("color:red; padding-left:5px;")
        vbox_right_time.addWidget(self.cut_time_label)
        self.cut_time_label.hide()

        layout.addWidget(self.right_time_widget, 0, 0, alignment=Qt.AlignBottom | Qt.AlignLeft)

        # MPV Setup
        self._player = mpv.MPV(
            wid=str(int(self.video_frame.winId())),
            log_handler=self._mpv_log_handler,
            hr_seek="yes",
            hr_seek_framedrop="yes",
            loglevel='info',
        )
        # Fenstereinstellungen, damit wir (fast) nie Schwarz flackern
        self._player["force-window"] = "immediate"
        self._player["keep-open"] = "yes"

        # Start = paused
        self._player.pause = True
        self._player.volume = 50

        self.is_playing = False
        self.playlist = []
        self._current_index = 0
        self.multi_durations = []
        self.boundaries = []

        # Falls du end-file auswerten willst:
        # (Wenn du python-mpv >= 0.5.2 hast, geht so:)
        self._player.observe_property('playlist-pos', self._on_playlist_pos_changed)
        # oder mit self._player.register_event_callback(...) + Auswertung event.event_id ?

        # Du kannst z. B. die Zeitanzeige in einer Timer-Schleife updaten
        self._time_timer = QTimer(self)
        self._time_timer.timeout.connect(self._update_time_label)
        self._time_timer.start(200)  # alle 200ms

    # -----------------------------------------
    # ALTE METHODEN (Schnittstellen), die dein restlicher Code aufruft
    # -----------------------------------------
    
    def set_cut_intervals(self, intervals):
        """
        Speichert eine Liste von (start_s, end_s)-Schnittbereichen.
        Beispiel: [(0.0, 12.5), (80.0, 85.2)]
        """
        if not intervals:
            self._cut_intervals = []
        else:
            self._cut_intervals = intervals
    
    def _get_cut_end_if_zero(self) -> float:
        """
        Falls in self._cut_intervals ein Bereich [0..end] existiert,
        gib end zurück. Sonst 0.0.
        Wir suchen das größte 'end', bei dem start quasi 0 ist.
        """
        max_cut_end = 0.0
        for (start_s, end_s) in self._cut_intervals:
            # Prüfen, ob der Schnitt (start_s..end_s) wirklich
            # am absoluten Anfang ansetzt (z.B. <= 0.001)
            if abs(start_s) < 0.001:
                if end_s > max_cut_end:
                    max_cut_end = end_s
        return max_cut_end    
            
            
    def set_time_mode(self, mode: str):
        self._time_mode = mode    
        
    def set_final_time_callback(self, func):
        """func soll sein: func(global_s) -> final_s"""
        self._final_time_callback = func    
        

    def show_first_frame_at_index(self, index: int):
        """
        Gehe zum playlist-Index 'index', pausiere + seek an den Anfang => 1. Frame
        """
        if not self.playlist or index < 0 or index >= len(self.playlist):
            return  # Ungültig => Abbruch

        self.is_playing = False
    
        # => mpv springt zu Clip 'index'
        self._player.command("playlist-play-index", str(index))
    
        def do_seek():
            # 1) Prüfen, ob mpv noch ein Video hat + Position >=0
            if self._player.playlist_count == 0:
                return
            if self._player.playlist_pos is None or self._player.playlist_pos < 0:
                return

            # 2) Seek an 0s
            try:
                self._player.command("seek", "0", "absolute", "exact")
                self._player.pause = True
                self.is_playing = False
            except SystemError as e:
                # -12 bedeutet oft, dass mpv in Idle ist oder “keine Datei mehr hat”
                print(f"[WARN] show_first_frame: mpv refused to seek => {e}")

        QTimer.singleShot(80, do_seek)

    def set_playback_rate(self, rate: float):
        self._player.speed = rate
        self._show_speed_label(f"Speed: {rate:.2f}x")

    def _show_speed_label(self, txt: str):
        self.speed_label.setText(txt)
        self.speed_label.show()
        QTimer.singleShot(2000, self.speed_label.hide)

    def set_total_length(self, total_s: float):
        # z. B. Summe aller Videos
        txt = self.format_seconds_simple(total_s)
        self.total_length_label.setText(txt)

    def set_old_time(self, old_s: float):
        """
        Falls dein Code hierhin ruft (historische Funktion).
        Man kann z. B. `old_s` = summe aller Video-Längen *vor* dem Cut?
        """
        txt = self.format_seconds_simple(old_s)
        self.total_length_label.setText(txt)

    def set_cut_time(self, cut_s: float):
        if cut_s > 0:
            self.cut_time_label.setText(self.format_seconds_simple(cut_s))
            self.cut_time_label.show()
        else:
            self.cut_time_label.setText("")
            self.cut_time_label.hide()

    def format_seconds_simple(self, secs: float) -> str:
        """z. B. 74.2 => '00:01:14' (ohne ms)"""
        s_rounded = round(secs)
        hh = s_rounded // 3600
        mm = (s_rounded % 3600) // 60
        ss = s_rounded % 60
        return f"<span style='font-size:14px;'>{hh:02d}:{mm:02d}:{ss:02d}</span>"

    def format_seconds_html(self, secs: float) -> str:
        """z. B. 12.345 => '00:00:12.<ms=345>' in HTML-Font-Styles."""
        
        base = int(math.floor(secs))
        fraction = secs - base
        ms = int(round(fraction * 1000))
        if ms == 1000:
            base += 1
            ms = 0
        hh = base // 3600
        mm = (base % 3600) // 60
        ss = base % 60

        return (
            f"<span style='font-size:16px;'>"
            f"{hh:02d}:{mm:02d}:{ss:02d}"
            "</span>"
            f".<span style='font-size:10px;'>{ms:03d}</span>"
        )

    def set_current_time(self, secs: float):
        """
        Wird evtl. aufgerufen, wenn Timeline den Schieberegler setzt und wir
        nur das UI-Label anpassen wollen. (Oder optional -> self._player.seek())
        """
        # => wir machen hier NUR Label:
        text_html = self.format_seconds_html(secs)
        self.current_time_label.setTextFormat(Qt.RichText)
        self.current_time_label.setText(text_html)

    def play_pause(self):
        if self.is_playing:
            self._player.pause = True
            self.is_playing = False
        else:
            self._player.pause = False
            self.is_playing = True



    def get_current_position_s(self) -> float:
        """
        Gibt die *globale* Zeit (in Sekunden) über alle Clips zurück.
        Ruft intern get_current_global_time() auf.
        """
        return self.get_current_global_time()

    def get_current_index(self) -> int:
        """Ablösung für dein altes self._current_index => mpv.playlist_pos."""
        pos = self._player.playlist_pos
        if pos is None or pos < 0:
            return -1
        return pos

    def set_time(self, new_s: float):
        """
        Globaler Sprung in der gesamten Playlist:
        Rechnet new_s => clipIndex + local_s und ruft 'playlist-play-index' + 'seek' auf.
        """
        self._jump_to_global_time(new_s)

    def frame_step_forward(self):
        self._player.command("frame-step")

    def frame_step_backward(self):
        self._player.command("frame-step", -1)

    # -----------------------------------------
    # Playlist-Funktionen
    # -----------------------------------------
    def set_multi_durations(self, durations_list):
        """z.B. [60.0, 90.0] => 2 Videos => sum=150 => boundaries=[60,150]."""
        self.multi_durations = durations_list or []
        self.boundaries = []
        accum = 0.0
        for d in self.multi_durations:
            accum += d
            self.boundaries.append(accum)

    def set_playlist(self, video_list):
        """Erzeugt mpv-Playlist per 'append-play'."""
        self._player.command("playlist-clear")
        if not video_list:
            self.playlist = []
            return
        # Erstes normal load
        self._player.command("loadfile", video_list[0])
        # Rest => append
        for path in video_list[1:]:
            self._player.command("loadfile", path, "append-play")

        # Start paused
        self._player.pause = True
        self.is_playing = False

        self.playlist = video_list

    def _jump_to_global_time(self, wanted_s: float):
        """
        'wanted_s' ist die globale Zeit über alle Clips.
        Wir ermitteln clipIndex + local_s.
        Nur wenn der clipIndex sich tatsächlich ändert, machen wir
        playlist-play-index + 80ms Delay. Sonst: direkt seek.
        """
        if not self.boundaries:
            return

        total = self.boundaries[-1]
        if wanted_s < 0:
            wanted_s = 0.0
        elif wanted_s > total:
            wanted_s = total

        # ClipIndex suchen
        clip_idx = 0
        offset_prev = 0.0
        for i, bound_val in enumerate(self.boundaries):
            if wanted_s < bound_val:
                clip_idx = i
                break
            offset_prev = bound_val
    
        local_s = wanted_s - offset_prev
        if local_s < 0:
            local_s = 0

        # Aktueller mpv-Playlist-Index:
        current_idx = self._player.playlist_pos

        if current_idx == clip_idx:
            # 1) GLEICHER CLIP => kein Delay, kein playlist-play-index
            try:
                self._player.command("seek", f"{local_s}", "absolute", "exact")
                self._player.pause = True
                self.is_playing = False
            except SystemError as e:
                print(f"[WARN] _jump_to_global_time: mpv refused to seek => {e}")
        else:
            # 2) CLIP WECHSEL => playlist-play-index + kleiner Delay
            self._player.command("playlist-play-index", str(clip_idx))

            def do_seek():
                if self._player.playlist_count == 0:
                    return
                if self._player.playlist_pos is None or self._player.playlist_pos < 0:
                    return
                try:
                    self._player.command("seek", f"{local_s}", "absolute", "exact")
                    self._player.pause = True
                    self.is_playing = False
                except SystemError as e:
                    print(f"[WARN] _jump_to_global_time: mpv refused to seek => {e}")

            QTimer.singleShot(80, do_seek)


    

    # -----------------------------------------
    # mpv Event-Handling
    # -----------------------------------------

    def _on_playlist_pos_changed(self, name, value):
        """
        mpv ruft diese Callback auf, sobald 'playlist-pos' wechselt.
        Falls wir am Ende sind, pos=None. Dann => play_ended-Signal?
        """
        if value is None or value < 0:
            # => wir sind evtl. am Ende der Playlist
            self.play_ended.emit()

    # optionales Log
    def _mpv_log_handler(self, level, component, message):
        print(f"[MPV] {level} {component}: {message}", end="")
    
    def _update_time_label(self):
        if not self.playlist or self._player.playlist_count == 0:
            self.current_time_label.hide()
            return
        else:
            self.current_time_label.show()
            
        

        # 1) globale Sekunde
        global_s = self.get_current_global_time()

        # 2) falls "global" => zeige global_s
        #    falls "final"  => rufe callback auf
        if self._time_mode == "final" and self._final_time_callback:
            show_s = self._final_time_callback(global_s)
        else:
            show_s = global_s

        text_html = self.format_seconds_html(show_s)
        self.current_time_label.setText(text_html)

    def stop(self):
        """
        Wenn am Anfang ein Schnitt [0..X] existiert, springen wir an X,
        ansonsten an 0s des ersten Videos.
        """
        if not self.playlist:
            return
    
        # (1) Prüfe, ob wir [0..cutX] haben
        cut0_end = self._get_cut_end_if_zero()

        if cut0_end > 0.001:
            # => wir haben einen Schnitt am Anfang => an cut0_end springen
            self._jump_to_global_time(cut0_end)
        
            # Danach Pause + is_playing = False
            self._player.pause = True
            self.is_playing = False

        else:
            # => kein Schnitt am Anfang => normaler Sprung an Clip=0, 0s
            self._player.command("playlist-play-index", "0")

            def do_seek_zero():
                if self._player.playlist_count == 0:
                    return
                if self._player.playlist_pos is None or self._player.playlist_pos < 0:
                    return
            
                try:
                    self._player.command("seek", "0", "absolute", "exact")
                    self._player.pause = True
                    self.is_playing = False
                except SystemError as e:
                    print(f"[WARN] stop(): mpv refused to seek => {e}")
        
            QTimer.singleShot(50, do_seek_zero)

        
        
    def get_current_global_time(self) -> float:
        """
        Gibt die 'globale' Zeit (in Sekunden) über alle Clips zurück.
        Beispiel: wenn wir im 2. Clip sind, der erste Clip war 60s lang 
        und im 2. Clip sind wir gerade bei Sekunde 10 => Rückgabe = 70.
        """
        clipIndex = self._player.playlist_pos  # python-mpv property
        local_s   = self._player.time_pos or 0.0
        if clipIndex is None or clipIndex < 0:
            return 0.0

        # offset_prev = boundaries[clipIndex - 1] (0.0 wenn clipIndex==0)
        if clipIndex == 0:
            offset_prev = 0.0
        else:
            offset_prev = self.boundaries[clipIndex - 1]
    
        return offset_prev + local_s   

    def is_video_loaded(self) -> bool:
        return self._player.playlist_count > 0