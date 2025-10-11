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


"""
step_manager.py

Erweiterter StepManager für verschiedene Step-Modi:

- 's' (Sekunden-Schritte)
- 'm' (Minuten-Schritte)
- 'k' (Keyframe-Schritte)
- 'f' (Frame-Schritte) NEU

Mit Folgendem Verhalten:
1) s/m-Modus:
   - Bei Schritt ins Cut-Interval -> "Freeze" knapp vor/hinter dem Cut.
   - Beim nächsten Schritt -> Überspringe den Cut.

2) k-Modus:
   - Falls das Keyframe im Cut-Bereich liegt -> direkt drüber springen
     (also ohne Freeze).

3) f-Modus (Frame-Step):
   - Springt um ca. 1 Frame (bzw. step_multiplier Frames).
   - Vor jedem Step wird überprüft, ob wir ins Cut-Interval geraten würden;
     wenn ja, wird wie bei s/m ein Freeze gemacht.
   - ACHTUNG: Da MPV bei Rückwärts-Frame-Step eventuell keine exakte
     Einzelframe-Auflösung unterstützt (und VFR-Videos variieren können),
     ist dies nur ein Approx. Man nimmt (1 / fps).
"""

from PySide6.QtCore import QTimer

class StepManager(object):
    def __init__(self, video_editor):
        """
        :param video_editor: Referenz auf das VideoEditorWidget (enthaelt multi_durations, MPV player usw.)

        Mögliche step_mode:
        - 's' => Sekunden
        - 'm' => Minuten
        - 'k' => Keyframes
        - 'f' => Einzelbild (Frame) - NEU
        """
        self.video_editor = video_editor
        self.mainwindow = None
        self.cut_manager = None

        self.step_mode = "s"   # 's', 'm', 'k', 'f'
        self.step_multiplier = 1.0

        # Freeze-Logik fuer s/m/f
        self._freeze_mode = False
        self._frozen_cut_interval = None

        # Fuer Keyframe-Schritte
        self._last_skip_target = None

    def set_mainwindow(self, mw):
        """
        Damit wir z.B. auf mw.global_keyframes zugreifen können
        (fuer K-Mode).
        """
        self.mainwindow = mw

    def set_cut_manager(self, cm):
        """
        Uebergibt den VideoCutManager, damit wir auf dessen get_cut_intervals() zugreifen koennen.
        """
        self.cut_manager = cm

    def set_step_mode(self, new_mode):
        self.step_mode = new_mode
        print(f"[DEBUG] StepManager: step_mode set to '{self.step_mode}'")

    def set_step_multiplier(self, multiplier):
        self.step_multiplier = multiplier
        print(f"[DEBUG] StepManager: step_multiplier = {self.step_multiplier}")

    # ------------------------------------------------------------------------
    # Oeffentliche Step-Funktionen (werden per Buttons aufgerufen)
    # ------------------------------------------------------------------------
    def step_forward(self):
        # Falls das Video laeuft -> Pausieren
        if self.video_editor.is_playing:
            self.video_editor._player.pause = True
            self.video_editor.is_playing = False

        # (1) Freeze-Modus schon aktiv?
        if self._freeze_mode:
            self._handle_freeze_forward()
            return

        # (2) Normaler Step, je nach Mode
        if self.step_mode == 'k':
            self._step_keyframe_forward()
        elif self.step_mode in ('s', 'm'):
            self._step_time_forward()
        elif self.step_mode == 'f':  # *** F-Mode START ***
            self._step_frame_forward() 
        else:
            print(f"[DEBUG] step_mode='{self.step_mode}'? Unbekannter Modus.")

    def step_backward(self):
        # Falls das Video laeuft -> Pausieren
        if self.video_editor.is_playing:
            self.video_editor._player.pause = True
            self.video_editor.is_playing = False

        # (1) Freeze aktiv?
        if self._freeze_mode:
            self._handle_freeze_backward()
            return

        # (2) Normaler Step
        if self.step_mode == 'k':
            self._step_keyframe_backward()
        elif self.step_mode in ('s', 'm'):
            self._step_time_backward()
        elif self.step_mode == 'f':  # *** F-Mode START ***
            self._step_frame_backward()
        else:
            print(f"[DEBUG] step_mode='{self.step_mode}'? Unbekannter Modus.")

    # ------------------------------------------------------------------------
    # Freeze-Logik entkoppelt, damit wir keinen Code-Duplikat haben.
    # ------------------------------------------------------------------------
    def _handle_freeze_forward(self):
        """
        Falls wir schon eingefroren sind und nochmal step_forward rufen,
        überspringen wir direkt das Cut-Ende.
        """
        self._freeze_mode = False
        if self._frozen_cut_interval:
            start_s, end_s = self._frozen_cut_interval
            self._frozen_cut_interval = None
            jump_s = end_s + 0.001
            print(f"[DEBUG] War eingefroren - Ueberspringe Cut => gehe zu {jump_s:.3f}")
            self.video_editor._jump_to_global_time(jump_s)
        else:
            print("[DEBUG] War eingefroren, aber _frozen_cut_interval=None => normal step forward")

    def _handle_freeze_backward(self):
        """
        Falls wir schon eingefroren sind und nochmal step_backward rufen,
        überspringen wir direkt das Cut-Start.
        """
        self._freeze_mode = False
        if self._frozen_cut_interval:
            start_s, end_s = self._frozen_cut_interval
            self._frozen_cut_interval = None
            jump_s = max(start_s - 0.001, 0.0)
            print(f"[DEBUG] War eingefroren - Ueberspringe Cut rueckwaerts => gehe zu {jump_s:.3f}")
            self.video_editor._jump_to_global_time(jump_s)
        else:
            print("[DEBUG] War eingefroren, aber _frozen_cut_interval=None => normal step backward")

    # ------------------------------------------------------------------------
    # s-/m-Modus => Zeit-Schritte + Freeze-Logik
    # ------------------------------------------------------------------------
    def _step_time_forward(self):
        cur_s = self._get_current_global_time()
        delta_s = self._compute_time_step_s()
        new_s = cur_s + delta_s

        # Check, ob new_s im Cut => freeze
        if self._check_and_freeze_if_stepping_into_cut(cur_s, new_s, forward=True):
            return

        print(f"[DEBUG] (time-forward): {cur_s:.3f} => {new_s:.3f} (dt={delta_s:.3f})")
        self.video_editor._jump_to_global_time(new_s)

    def _step_time_backward(self):
        cur_s = self._get_current_global_time()
        delta_s = self._compute_time_step_s()
        new_s = cur_s - delta_s
        if new_s < 0.0:
            new_s = 0.0

        if self._check_and_freeze_if_stepping_into_cut(cur_s, new_s, forward=False):
            return

        print(f"[DEBUG] (time-backward): {cur_s:.3f} => {new_s:.3f} (dt={delta_s:.3f})")
        self.video_editor._jump_to_global_time(new_s)

    def _compute_time_step_s(self):
        if self.step_mode == 'm':
            return 60.0 * self.step_multiplier
        elif self.step_mode == 's':
            return 1.0 * self.step_multiplier
        else:
            # Falls man hier landet (k/f) => normal 1.0
            return 1.0

    # ------------------------------------------------------------------------
    # *** F-Mode START *** => Frame-Step + Freeze
    # ------------------------------------------------------------------------
    def _step_frame_forward(self):
        """
        Einzelbild vorwärts, mit Freeze-Check.
        Wir approximieren die nächste Zeit als current + (step_multiplier / fps).
        """
        cur_s = self._get_current_global_time()
        fps = self._get_current_fps()
        # step_multiplier = '2x' => 2 Frames?
        frame_delta = (1.0 * self.step_multiplier) / fps  
        next_s = cur_s + frame_delta

        # Freeze-Check
        if self._check_and_freeze_if_stepping_into_cut(cur_s, next_s, forward=True):
            return

        print(f"[DEBUG] (frame-forward): {cur_s:.3f} => ~{next_s:.3f} (+{frame_delta:.5f}s)")
        self.video_editor.frame_step_forward()

    def _step_frame_backward(self):
        """
        Einzelbild rückwärts, mit Freeze-Check.
        Achtung: MPV kann rückwärts-frame-step nur eingeschränkt.
        """
        cur_s = self._get_current_global_time()
        fps = self._get_current_fps()
        frame_delta = (1.0 * self.step_multiplier) / fps
        next_s = cur_s - frame_delta
        if next_s < 0.0:
            next_s = 0.0

        if self._check_and_freeze_if_stepping_into_cut(cur_s, next_s, forward=False):
            return

        print(f"[DEBUG] (frame-backward): {cur_s:.3f} => ~{next_s:.3f} (-{frame_delta:.5f}s)")
        self.video_editor.frame_step_backward()

    def _get_current_fps(self):
        """
        Lese das aktuelle FPS aus MPV (falls verfügbar).
        Fallback = 25.0 bei unbekannter Framerate.
        """
        try:
            fps = self.video_editor._player.video_params["fps"]
            if fps and fps > 0:
                return float(fps)
        except:
            pass
        return 25.0

    # ------------------------------------------------------------------------
    # k-Modus => Keyframe-Schritte (ohne Freeze, direkter Skip)
    # ------------------------------------------------------------------------
    def _step_keyframe_forward(self):
        kfs = self._get_kfs_list()
        if not kfs:
            print("[DEBUG] (k-forward): Keine Keyframes vorhanden.")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "No Keyframes Loaded",
                "No keyframes loaded! Please index your videos or switch off 'k' mode.")
            return

        cur_s = self._get_current_global_time()
        mul = max(1.0, self.step_multiplier)
        n = int(mul)

        EPS = 0.005
        idx = None
        for i, t in enumerate(kfs):
            if t > (cur_s + EPS):
                idx = i
                break
        if idx is None:
            print("[DEBUG] (k-forward): bereits am letzten Keyframe.")
            return

        idx_n = idx + (n - 1)
        if idx_n >= len(kfs):
            idx_n = len(kfs) - 1

        target_s = kfs[idx_n]
        skip_s = self._maybe_skip_cut(target_s, forward=True)
        if skip_s is not None:
            print(f"[DEBUG] (k-forward): Keyframe {target_s:.3f} im Cut => springe {skip_s:.3f}")
            self.video_editor._jump_to_global_time(skip_s)
            return

        print(f"[DEBUG] (k-forward): current={cur_s:.3f} => {target_s:.3f} (idx={idx_n})")
        self.video_editor._jump_to_global_time(target_s)

    def _step_keyframe_backward(self):
        kfs = self._get_kfs_list()
        if not kfs:
            print("[DEBUG] (k-backward): Keine Keyframes vorhanden.")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "No Keyframes Loaded",
                "No keyframes loaded! Please index your videos or switch off 'k' mode.")
            return

        cur_s = self._get_current_global_time()
        mul = max(1.0, self.step_multiplier)
        n = int(mul)

        EPS = 0.005
        idx = None
        # Rueckwaerts => den naechsten Keyframe UNTERHALB cur_s
        for i in reversed(range(len(kfs))):
            if kfs[i] < (cur_s - EPS):
                idx = i
                break
        if idx is None:
            print("[DEBUG] (k-backward): Vor erstem Keyframe.")
            return

        idx_n = idx - (n - 1)
        if idx_n < 0:
            idx_n = 0

        target_s = kfs[idx_n]
        skip_s = self._maybe_skip_cut(target_s, forward=False)
        if skip_s is not None:
            print(f"[DEBUG] (k-backward): Keyframe {target_s:.3f} im Cut => springe {skip_s:.3f}")
            self.video_editor._jump_to_global_time(skip_s)
            return

        print(f"[DEBUG] (k-backward): current={cur_s:.3f} => {target_s:.3f} (idx={idx_n})")
        self.video_editor._jump_to_global_time(target_s)

    # ------------------------------------------------------------------------
    # Gemeinsame Hilfsfunktionen
    # ------------------------------------------------------------------------
    def _maybe_skip_cut(self, target_s: float, forward: bool) -> float | None:
        """
        Prueft, ob target_s in einem geschnittenen Bereich liegt.
        Falls ja => "Cut-Ende+0.001" (forward) oder "Cut-Start-0.001" (backward).
        Sonst None => normal.
        """
        if not self.cut_manager:
            return None

        for (start_s, end_s) in self.cut_manager.get_cut_intervals():
            if start_s <= target_s < end_s:
                if forward:
                    return min(end_s + 0.001, self._get_total_duration())
                else:
                    return max(start_s - 0.001, 0.0)
        return None

    def _check_and_freeze_if_stepping_into_cut(self, cur_s, next_s, forward: bool) -> bool:
        """
        Falls wir in einen geschnittenen Bereich gelangen, freeze knapp davor.
        Nächster Step => actual skip.
        """
        if not self.cut_manager:
            return False

        for (start_s, end_s) in self.cut_manager.get_cut_intervals():
            # check if [cur_s, next_s] => in den Cut-Bereich läuft
            # forward => next_s > cur_s
            # backward => next_s < cur_s
            if forward:
                # wir wollen von cur_s nach next_s
                if (start_s <= next_s < end_s):
                    freeze_s = max(start_s - 0.001, 0.0)
                    print(f"[DEBUG] Step => freeze @ {freeze_s:.3f}")
                    self._frozen_cut_interval = (start_s, end_s)
                    self._freeze_mode = True
                    self.video_editor._jump_to_global_time(freeze_s)
                    return True
            else:
                if (start_s < next_s <= end_s):
                    freeze_s = min(end_s + 0.001, self._get_total_duration())
                    print(f"[DEBUG] Step => freeze @ {freeze_s:.3f}")
                    self._frozen_cut_interval = (start_s, end_s)
                    self._freeze_mode = True
                    self.video_editor._jump_to_global_time(freeze_s)
                    return True

        return False

    def _get_current_global_time(self) -> float:
        """
        Index => local => global
        """
        idx = self.video_editor._current_index
        local_s = self.video_editor.get_current_position_s()
        total_before = sum(self.video_editor.multi_durations[:idx])
        return total_before + local_s

    def _get_total_duration(self) -> float:
        return sum(self.video_editor.multi_durations)

    def _get_kfs_list(self):
        """
        Aus dem MainWindow => global_keyframes
        """
        if not self.mainwindow:
            return []
        return self.mainwindow.global_keyframes or []
