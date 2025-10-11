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

# managers/cut_manager.py
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QObject, QTimer, Signal

class VideoCutManager(QObject):
    cutsChanged = Signal(float)

    def __init__(self, video_editor, timeline, parent=None):
        super().__init__(parent)
        self.video_editor = video_editor
        self.timeline = timeline
        self.markB_time_s = -1.0
        self.markE_time_s = -1.0
        self._cut_intervals = []
        self._skip_timer = QTimer(self)
        self._skip_timer.timeout.connect(self._check_cut_skip)
        self._skip_timer.start(200)

        self.video_durations = []
        self._last_skip_target = None
        self._orig_marker_func = None
        
        
    def stop_skip_timer(self):
        """Stoppt den 200ms-Timer, sodass _check_cut_skip nicht mehr aufgerufen wird."""
        if self._skip_timer.isActive():
            self._skip_timer.stop()

    def start_skip_timer(self):
        """Startet den Timer wieder, damit _check_cut_skip erneut aktiv wird."""
        if not self._skip_timer.isActive():
            self._skip_timer.start(200)
            

    def set_video_durations(self, durations_list):
        self.video_durations = durations_list

    def on_markB_clicked(self):
        current_global_s = self._get_current_global_time()
        if self.markE_time_s >= 0 and current_global_s >= self.markE_time_s:
            QMessageBox.warning(
                None,
                "Invalid MarkB",
                f"You cannot set MarkB ({current_global_s:.2f}s) behind MarkE ({self.markE_time_s:.2f}s)!"
            )
            return  # Abbrechen, gar nicht setzen
            
        self.markB_time_s = current_global_s
        self.timeline.set_markB_time(current_global_s)

    def on_markE_clicked(self):
        current_global_s = self._get_current_global_time()
        if self.markB_time_s >= 0 and current_global_s <= self.markB_time_s:
            QMessageBox.warning(
                None,
                "Invalid MarkE",
                f"You cannot set MarkE ({current_global_s:.2f}s) in front of MarkB ({self.markB_time_s:.2f}s)!"
            )
            return
        video_total = sum(self.video_durations)
        if video_total - current_global_s < 1 : #impossible to select last frame on mpv, so we clamp manually
            current_global_s = video_total
        self.markE_time_s = current_global_s
        self.timeline.set_markE_time(current_global_s)

    def on_cut_clicked(self):
        if self.markB_time_s < 0 or self.markE_time_s < 0:
            return
        start_s = min(self.markB_time_s, self.markE_time_s)
        end_s   = max(self.markB_time_s, self.markE_time_s)
        video_total = sum(self.video_durations)
        start_s = max(0.0, start_s)
        end_s   = min(end_s, video_total)
        if (end_s - start_s) < 0.01:
            print("[DEBUG] Cut-Bereich zu klein, Abbruch. Start:", start_s, "Ende:", end_s)
            return
        print(f"[DEBUG] CUT hinzugefügt: ({start_s:.3f}, {end_s:.3f})")
        self._cut_intervals.append((start_s, end_s))
        self.timeline.add_cut_interval(start_s, end_s)
        self.markB_time_s = -1
        self.markE_time_s = -1
        self.timeline.set_markB_time(-1)
        self.timeline.set_markE_time(-1)
        self._emit_cuts_changed()
        self.video_editor.set_cut_intervals(self._cut_intervals)

    def on_undo_clicked(self):
        if not self._cut_intervals:
            return
        self._cut_intervals.pop()
        self.timeline.remove_last_cut_interval()
        self._emit_cuts_changed()
        self.video_editor.set_cut_intervals(self._cut_intervals)

    def on_markClear_clicked(self):
        if self.markB_time_s >= 0 or self.markE_time_s >= 0:
            self.markB_time_s = -1.0
            self.markE_time_s = -1.0
            self.timeline.set_markB_time(-1)
            self.timeline.set_markE_time(-1)

    def get_total_cuts(self) -> float:
        total_cut = 0.0
        for (start_s, end_s) in self._cut_intervals:
            total_cut += (end_s - start_s)
        print(f"[DEBUG] get_total_cuts => {total_cut:.3f}")
        return total_cut

    def get_cut_intervals(self):
        return self._cut_intervals
    
   
    def _check_cut_skip(self):
        # 1) Prüfen, ob mpv überhaupt ein File abspielt
        if not self._has_active_file():
            return  # => Kein Skip, da kein aktives Video

        current_global_s = self._get_current_global_time()
        skip_target = self._find_skip_target(current_global_s)
        
        if skip_target is not None:
            if self._is_repeated_skip_target(skip_target):
                return
        
            was_playing = self.video_editor.is_playing
            self._set_global_time_s(skip_target)
            self._last_skip_target = skip_target

            # NUR wenn wir wirklich vorher gespielt haben, wieder abspielen
            if was_playing:
                self._play_after_skip()
        else:
            self._last_skip_target = None


    def _has_active_file(self) -> bool:
        """Prüft, ob mpv noch eine gültige Datei (playlist/current_index) geladen hat."""
        # 1) Hat der VideoEditor eine Playlist?
        if not self.video_editor.playlist:
            return False

        # 2) current_index darf nicht außerhalb liegen
        idx = self.video_editor.get_current_index()
        if idx < 0 or idx >= len(self.video_editor.playlist):
            return False

        # 3) mpv-Filename (sofern mpv.py das unterstützt)
        fname = self.video_editor._player.filename
        if not fname:
            return False

        return True
    
    

    def _find_skip_target(self, current_s: float):
        """
        Falls current_s in einem cut-Intervall liegt (start_s <= current_s < end_s),
        soll direkt ans Ende (end_s) gesprungen werden.
        """
        for (start_s, end_s) in self._cut_intervals:
            if start_s <= current_s < end_s:
                return end_s
        return None

    def _is_repeated_skip_target(self, skip_target: float) -> bool:
        """
        Verhindert doppeltes Springen an dieselbe Stelle in schneller Folge.
        """
        if self._last_skip_target is None:
            return False
        return abs(skip_target - self._last_skip_target) < 0.001
    
    
    def _get_current_global_time(self) -> float:
        return self.video_editor.get_current_position_s()
    
    def _set_global_time_s(self, new_global_s: float):
        """
        Springt in die Timeline => new_global_s, 
        macht sofort Pause, so dass 1 Frame sichtbar ist.
        """
        was_playing = self.video_editor.is_playing  # Merke, ob das Video vorher lief
        # 1) mpv-Seeking
        self.video_editor._jump_to_global_time(new_global_s)
        if not was_playing:
            # 2) Pause => Freeze
            self.video_editor._player.pause = True
            self.video_editor.is_playing = False
        else:
            self._play_after_skip()    
            
        # 3) Timeline-Update blocken
        self._block_timeline_marker()
    
    

    def _play_after_skip(self):
        """
        Wird nach dem Setzen der neuen Zeit aufgerufen, 
        um (leicht verzögert) weiterzuspielen.
        """
        #return
        
        def _ensure_playing():
            """Prüft, ob das Video läuft, und startet es falls nötig."""
            if not self.video_editor.is_playing:
                self.video_editor._player.pause = False
                self.video_editor.is_playing = True


        from PySide6.QtCore import QTimer
        #QTimer.singleShot(50, self._really_force_play)
        # 1) Normale Verzögerung für Sprünge innerhalb desselben Videos
        QTimer.singleShot(50, _ensure_playing)

        # 2) Falls ein Video-Wechsel stattfand, nochmals nachprüfen
        QTimer.singleShot(500, _ensure_playing)

    def _really_force_play(self):
        """
        Analog zum alten Code: Startet MPV-Wiedergabe wirklich neu
        (statt 'media_list_player.play()').
        """
        self.video_editor._player.pause = False
        self.video_editor.is_playing = True

    def _block_timeline_marker(self):
        if self._orig_marker_func is not None:
            return
        self._orig_marker_func = self.timeline.set_marker_position

        def dummy_marker_position(pos: float):
            pass

        self.timeline.set_marker_position = dummy_marker_position

        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._restore_timeline_marker)

    def _restore_timeline_marker(self):
        if self._orig_marker_func is not None:
            self.timeline.set_marker_position = self._orig_marker_func
            self._orig_marker_func = None

    def _emit_cuts_changed(self):
        total_cut = self.get_total_cuts()
        self.cutsChanged.emit(total_cut)
    
    def is_in_cut_segment(self, time_s: float) -> bool:
        """
        Returns True, wenn 'time_s' innerhalb eines vorhandenen 
        Schnittbereichs (start_s <= time_s < end_s) liegt.
        """
        for (start_s, end_s) in self._cut_intervals:
            if start_s <= time_s < end_s:
                return True
        return False
