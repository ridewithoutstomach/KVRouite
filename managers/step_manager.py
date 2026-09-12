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

Der Stepper hinter den Vor-/Zurueck-Knoepfen. Modi:

- 's' Sekunden
- 'm' Minuten
- 'f' Einzelbild
- 'k' Keyframes
- 'c' Schnittkanten
- 'KF' 360-Blickmarken (View-Keyframes), nur bei aktivem 360

GRUNDSATZ: gezaehlt wird im FERTIGEN Video, nicht im Rohmaterial.

Ein Schnitt kommt im Ergebnis nicht vor. Steht man also auf dem letzten Bild
vor einem Schnitt und drueckt "+1 s", dann liegt das Ziel eine Sekunde weiter
im fertigen Video - im Rohmaterial also hinter dem Schnitt plus einer Sekunde.
Frueher wurde stattdessen im Rohmaterial gerechnet: 1 s weiter landete mitten
im geloeschten Bereich, und eine "Freeze"-Mechanik hat den Player dann an die
Schnittkante gesetzt. Dadurch blieb man an jedem Schnitt haengen, der laenger
war als die Schrittweite, und kam nie weiter. Diese Mechanik gibt es nicht mehr.

Was die Modi damit tun:

  s / m  Schrittweite x Multiplier weiter, im fertigen Video gemessen.
         Schnitte werden ueberflogen, als gaebe es sie nicht.

  f      genau ein Bild weiter, im fertigen Video. Steht man auf dem letzten
         Bild vor einem Schnitt, fuehrt EIN Druck auf das erste Bild dahinter.
         Solange kein Schnitt im Weg ist, macht das der Player selbst,
         das ist bildgenau. Der Multiplier bleibt hier ohne Wirkung, wie bisher.

  k      zum naechsten Keyframe, DER IM FERTIGEN VIDEO NOCH EXISTIERT.
         Keyframes, die in einem Schnitt liegen, werden uebersprungen.

  c      die Schnittkanten selbst: je Schnitt das letzte Bild davor und das
         erste danach, dazu Anfang und Ende des fertigen Videos. Nur im
         Encode-Mode, siehe _require_encode_mode(). Der Multiplier bleibt ohne
         Wirkung, es geht immer eine Kante weiter.

  KF     zur naechsten 360-Blickmarke (core/blickverlauf), wie 'k', nur mit
         der Liste aus dem Blickverlauf des Fensters. Marken in einem
         Schnitt werden wie Keyframes uebersprungen.

ZUM SPRINGEN: ein bildgenauer Sprung zeigt das ERSTE Bild AB der Zielzeit
(so nachgemessen). Wer das letzte Bild VOR einem Zeitpunkt
sehen will, muss deshalb eine ganze Bilddauer abziehen - eine Millisekunde
reicht nicht, die liegt noch im selben Bild. Siehe _edge_seek_target().
"""


class StepManager(object):

    # Steht hier oben, damit unten keine mehrzeiligen Texte im Code haengen.
    _C_MODE_HINT = """Stepping along the cut edges works in Encode-Mode only.

Encode-Mode places a keyframe exactly on every cut, so the two frames you see
here are the ones the result will show.

Copy-Mode cuts at the nearest keyframe instead - use step mode 'k' there to see
where the cut will really land."""

    def __init__(self, video_editor):
        """
        :param video_editor: das VideoEditorWidget (Player, multi_durations)
        """
        self.video_editor = video_editor
        self.mainwindow = None
        self.cut_manager = None

        self.step_mode = "s"   # 's', 'm', 'k', 'f', 'c'
        self.step_multiplier = 1.0

    def set_mainwindow(self, mw):
        """Fuer global_keyframes, _compute_keep_intervals und _edit_mode."""
        self.mainwindow = mw

    def set_cut_manager(self, cm):
        """Uebergibt den VideoCutManager (liefert die Schnitte)."""
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
        if self.video_editor.is_playing:
            self.video_editor.set_paused(True)

        if self.step_mode in ('s', 'm'):
            self._step_time(+1)
        elif self.step_mode == 'f':
            self._step_frame_forward()
        elif self.step_mode == 'k':
            self._step_keyframe(+1)
        elif self.step_mode == 'c':
            self._step_cut(+1)
        elif self.step_mode == 'KF':
            self._step_blickmarke(+1)
        else:
            print(f"[DEBUG] step_mode='{self.step_mode}'? Unbekannter Modus.")

    def step_backward(self):
        if self.video_editor.is_playing:
            self.video_editor.set_paused(True)

        if self.step_mode in ('s', 'm'):
            self._step_time(-1)
        elif self.step_mode == 'f':
            self._step_frame_backward()
        elif self.step_mode == 'k':
            self._step_keyframe(-1)
        elif self.step_mode == 'c':
            self._step_cut(-1)
        elif self.step_mode == 'KF':
            self._step_blickmarke(-1)
        else:
            print(f"[DEBUG] step_mode='{self.step_mode}'? Unbekannter Modus.")

    # ------------------------------------------------------------------------
    # KF => 360-Blickmarken
    # ------------------------------------------------------------------------
    def _step_blickmarke(self, direction: int):
        """Zur naechsten / vorigen Blickmarke, mit Multiplier wie bei 'k'."""
        verlauf = getattr(self.mainwindow, "_blickverlauf", None) \
            if self.mainwindow else None
        raw = verlauf.zeiten() if verlauf is not None else []
        if not raw:
            print("[DEBUG] (KF): Keine 360-Blickmarken vorhanden.")
            self.video_editor.hinweis_zeigen("No 360° keyframes set (button KF)")
            return
        kfs = self._surviving_keyframes(raw)
        if not kfs:
            print("[DEBUG] (KF): Alle Blickmarken liegen in geschnittenen Bereichen.")
            return
        cur_s = self._get_current_global_time()
        n = max(1, int(max(1.0, self.step_multiplier)))
        EPS = 0.005
        if direction > 0:
            idx = next((i for i, t in enumerate(kfs) if t > cur_s + EPS), None)
            if idx is None:
                print("[DEBUG] (KF-forward): bereits an der letzten Blickmarke.")
                return
            idx = min(idx + (n - 1), len(kfs) - 1)
        else:
            idx = next((i for i in reversed(range(len(kfs)))
                        if kfs[i] < cur_s - EPS), None)
            if idx is None:
                print("[DEBUG] (KF-backward): vor der ersten Blickmarke.")
                return
            idx = max(idx - (n - 1), 0)
        target = kfs[idx]
        print(f"[DEBUG] (KF {'+' if direction > 0 else '-'}): "
              f"{cur_s:.3f} => {target:.3f} (Marke {idx + 1} von {len(kfs)})")
        self.video_editor.seek_global(target)
        self.video_editor.hinweis_zeigen(
            f"Keyframe {idx + 1} of {len(kfs)}: {target:.2f}s")

    # ------------------------------------------------------------------------
    # s / m => Zeitschritte, im fertigen Video gemessen
    # ------------------------------------------------------------------------
    def _step_time(self, direction: int):
        delta = self._compute_time_step_s() * direction
        cur_s = self._get_current_global_time()
        keeps = self._get_keep_intervals()
        if not keeps:
            target = max(cur_s + delta, 0.0)
            print(f"[DEBUG] (time): keine Schnitte => {cur_s:.3f} => {target:.3f}")
            self.video_editor.seek_global(target)
            return

        cur_final = self._final_from_source(cur_s)
        new_final = self._clamp_final(cur_final + delta, keeps)
        target = self._source_from_final(new_final, keeps)
        arrow = "+" if direction > 0 else "-"
        print(f"[DEBUG] (time {arrow}): roh {cur_s:.3f} => {target:.3f} | "
              f"fertig {cur_final:.3f} => {new_final:.3f} (dt={delta:+.3f})")
        self.video_editor.seek_global(target)

    def _compute_time_step_s(self):
        if self.step_mode == 'm':
            return 60.0 * self.step_multiplier
        return 1.0 * self.step_multiplier

    # ------------------------------------------------------------------------
    # f => Einzelbild, im fertigen Video
    # ------------------------------------------------------------------------
    def _step_frame_forward(self):
        cur_s = self._get_current_global_time()
        keeps = self._get_keep_intervals()
        d = 1.0 / self._get_current_fps()
        idx = self._keep_index_for(cur_s, keeps, d)

        if idx is None:
            print(f"[DEBUG] (frame-forward): {cur_s:.3f} liegt in keinem "
                  f"Keep-Bereich => normaler Bildschritt")
            self.video_editor.frame_step_forward()
            return

        ke = keeps[idx][1]
        if cur_s + d < ke - 0.25 * d:
            # Das naechste Bild bleibt erhalten: der Player macht das bildgenau.
            print(f"[DEBUG] (frame-forward): {cur_s:.3f} + 1 Bild")
            self.video_editor.frame_step_forward()
            return

        if idx + 1 >= len(keeps):
            print("[DEBUG] (frame-forward): letztes Bild des Videos erreicht.")
            return

        target = self._edge_seek_target("in", keeps[idx + 1][0])
        print(f"[DEBUG] (frame-forward): {cur_s:.3f} => {target:.3f} "
              f"(ueber den Schnitt {ke:.3f}..{keeps[idx + 1][0]:.3f})")
        self.video_editor.seek_global(target)

    def _step_frame_backward(self):
        cur_s = self._get_current_global_time()
        keeps = self._get_keep_intervals()
        d = 1.0 / self._get_current_fps()
        idx = self._keep_index_for(cur_s, keeps, d)

        if idx is None:
            print(f"[DEBUG] (frame-backward): {cur_s:.3f} liegt in keinem "
                  f"Keep-Bereich => normaler Bildschritt")
            self.video_editor.frame_step_backward()
            return

        ks = keeps[idx][0]
        if cur_s - d > ks - 0.25 * d:
            print(f"[DEBUG] (frame-backward): {cur_s:.3f} - 1 Bild")
            self.video_editor.frame_step_backward()
            return

        if idx == 0:
            print("[DEBUG] (frame-backward): erstes Bild des Videos erreicht.")
            return

        target = self._edge_seek_target("out", keeps[idx - 1][1])
        print(f"[DEBUG] (frame-backward): {cur_s:.3f} => {target:.3f} "
              f"(ueber den Schnitt {keeps[idx - 1][1]:.3f}..{ks:.3f})")
        self.video_editor.seek_global(target)

    # ------------------------------------------------------------------------
    # k => Keyframes, die im fertigen Video noch vorkommen
    # ------------------------------------------------------------------------
    def _step_keyframe(self, direction: int):
        raw = self._get_kfs_list()
        if not raw:
            print("[DEBUG] (k): Keine Keyframes vorhanden.")
            from PySide6.QtWidgets import QMessageBox
            # Indiziert wird nur noch im Copy-Mode: der Keyframe-Index hat
            # keinen anderen Abnehmer als diesen Schrittmodus, und der zeigt,
            # wo Copy-Mode schneiden wuerde. Im Encode-Mode liegt jeder Schnitt
            # ohnehin genau auf dem Bild, das man gewaehlt hat.
            QMessageBox.warning(
                None, "No Keyframes Loaded",
                "No keyframes are indexed.\n\n"
                "Keyframe stepping shows where Copy mode would cut, so the "
                "index is only built in Copy mode.\n\n"
                "In Encode mode every cut lands exactly on the frame you "
                "picked - use step mode '1' or 'c' there.")
            return

        kfs = self._surviving_keyframes(raw)
        if not kfs:
            print("[DEBUG] (k): Alle Keyframes liegen in geschnittenen Bereichen.")
            return

        cur_s = self._get_current_global_time()
        n = max(1, int(max(1.0, self.step_multiplier)))
        EPS = 0.005

        if direction > 0:
            idx = next((i for i, t in enumerate(kfs) if t > cur_s + EPS), None)
            if idx is None:
                print("[DEBUG] (k-forward): bereits am letzten Keyframe.")
                return
            idx = min(idx + (n - 1), len(kfs) - 1)
        else:
            idx = next((i for i in reversed(range(len(kfs)))
                        if kfs[i] < cur_s - EPS), None)
            if idx is None:
                print("[DEBUG] (k-backward): vor dem ersten Keyframe.")
                return
            idx = max(idx - (n - 1), 0)

        target = kfs[idx]
        arrow = "+" if direction > 0 else "-"
        print(f"[DEBUG] (k {arrow}): {cur_s:.3f} => {target:.3f} "
              f"(idx={idx} von {len(kfs)})")
        self.video_editor.seek_global(target)

    def _surviving_keyframes(self, raw):
        """
        Keyframes ohne die, die in einem geschnittenen Bereich liegen.

        Ein Keyframe genau auf dem Anfang eines Schnitts faellt weg (das ist das
        erste geloeschte Bild), einer genau auf dem Ende bleibt (das ist das
        erste Bild, das wieder vorkommt).
        """
        keeps = self._get_keep_intervals()
        if not keeps:
            return list(raw)
        out = []
        i = 0
        for t in raw:
            while i < len(keeps) and t >= keeps[i][1]:
                i += 1
            if i >= len(keeps):
                break
            if t >= keeps[i][0]:
                out.append(t)
        return out

    # ------------------------------------------------------------------------
    # c => Schnittkanten
    # ------------------------------------------------------------------------
    def _step_cut(self, direction: int):
        if not self._require_encode_mode():
            return

        edges = self._get_cut_edges()
        if not edges:
            print("[DEBUG] (c): keine Schnittkanten vorhanden.")
            return

        cur_s = self._get_current_global_time()
        tol = self._edge_tolerance()
        order = edges if direction > 0 else list(reversed(edges))
        arrow = "+" if direction > 0 else "-"
        for kind, t in order:
            hit = (t > cur_s + tol) if direction > 0 else (t < cur_s - tol)
            if hit:
                target = self._edge_seek_target(kind, t)
                print(f"[DEBUG] (c {arrow}): {cur_s:.3f} => {target:.3f} "
                      f"({kind} @ {t:.3f})")
                self.video_editor.seek_global(target)
                return

        print("[DEBUG] (c): letzte Schnittkante in dieser Richtung erreicht.")

    def _get_cut_edges(self):
        """
        Die Schnittkanten als aufsteigende Liste (art, zeit_global_s).

        Gerechnet wird ueber die Keep-Bereiche, nicht ueber die Schnitte selbst:

          Anfang eines Keep-Bereichs ("in")  = erstes Bild nach einem Schnitt
                                               bzw. Anfang des Videos
          Ende eines Keep-Bereichs   ("out") = letztes Bild vor einem Schnitt
                                               bzw. Ende des Videos

        Ein Schnitt am Anfang (0..x) hat links keine Kante, einer am Ende rechts
        keine - das faellt so von selbst heraus.
        """
        keeps = self._get_keep_intervals()
        if not keeps:
            return []
        edges = []
        for ks, ke in keeps:
            edges.append(("in", ks))
            edges.append(("out", ke))
        edges.sort(key=lambda e: e[1])
        return edges

    def _edge_tolerance(self) -> float:
        """
        Abstand, ab dem eine Kante als "andere Kante" gilt.

        Nach dem Anfahren einer "out"-Kante steht der Player rund ein Bild vor
        der Kante. Ohne diese Toleranz wuerde derselbe Punkt beim naechsten
        Druck noch einmal angefahren.
        """
        return max(1.5 / self._get_current_fps(), 0.005)

    def _require_encode_mode(self) -> bool:
        """
        Der c-Modus ergibt nur im Encode-Mode einen Sinn: dort wird an jeder
        Schnittkante ein Keyframe erzwungen, der Schnitt landet also genau auf
        der Markierung. Der Copy-Mode schneidet am naechsten Keyframe.
        """
        mode = getattr(self.mainwindow, "_edit_mode", "off") if self.mainwindow else "off"
        if mode == "encode":
            return True
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "Cut mode needs Encode-Mode", self._C_MODE_HINT)
        return False

    # ------------------------------------------------------------------------
    # Umrechnung Rohzeit <-> Zeit im fertigen Video
    # ------------------------------------------------------------------------
    def _get_keep_intervals(self):
        """
        Die Bereiche, die im fertigen Video uebrig bleiben.

        Kommt aus MainWindow._compute_keep_intervals(), damit ueberlappende
        Schnitte genauso zusammengefasst werden wie ueberall sonst.
        """
        total = self._get_total_duration()
        if total <= 0.0:
            return []
        cuts = self.cut_manager.get_cut_intervals() if self.cut_manager else []
        if self.mainwindow and hasattr(self.mainwindow, "_compute_keep_intervals"):
            keeps = self.mainwindow._compute_keep_intervals(cuts, total)
        else:
            keeps = [(0.0, total)]
        return [(float(a), float(b)) for (a, b) in keeps if b > a]

    def _final_from_source(self, t: float) -> float:
        """Rohzeit => Zeit im fertigen Video."""
        acc = 0.0
        for ks, ke in self._get_keep_intervals():
            if t < ks:
                return acc
            if t < ke:
                return acc + (t - ks)
            acc += (ke - ks)
        return acc

    def _source_from_final(self, f: float, keeps=None) -> float:
        """Zeit im fertigen Video => Rohzeit."""
        if keeps is None:
            keeps = self._get_keep_intervals()
        if not keeps:
            return max(f, 0.0)
        if f <= 0.0:
            return keeps[0][0]
        acc = 0.0
        for ks, ke in keeps:
            seg = ke - ks
            if f < acc + seg:
                return ks + (f - acc)
            acc += seg
        return keeps[-1][1]

    def _clamp_final(self, f: float, keeps) -> float:
        """Begrenzt eine Zeit im fertigen Video auf das erste/letzte Bild."""
        total_final = sum(ke - ks for ks, ke in keeps)
        last = max(0.0, total_final - 1.0 / self._get_current_fps())
        return min(max(f, 0.0), last)

    def _keep_index_for(self, t: float, keeps, d: float):
        """Nummer des Keep-Bereichs, in dem t liegt - oder None."""
        tol = 0.25 * d
        for i, (ks, ke) in enumerate(keeps):
            if (ks - tol) <= t < (ke + tol):
                return i
        return None

    def _edge_seek_target(self, kind: str, t: float) -> float:
        """
        Rechnet eine Kante in die Zeit um, auf die wir springen.

        Nachgemessen an einem bildgenauen Sprung: gezeigt wird das ERSTE Bild AB
        der Zielzeit, nicht das davor. Also:

          "in"  (erstes Bild ab der Kante)   -> die Kante selbst, minus 0,1 ms,
                damit ein Bild genau auf der Kante sicher getroffen wird.
          "out" (letztes Bild vor der Kante) -> eine ganze Bilddauer frueher.

        Eine Millisekunde reicht bei "out" NICHT: Schnittkanten liegen auf einer
        Bildgrenze (MarkB/MarkE kommen aus der Player-Position), man landet dann
        auf dem ersten geloeschten Bild - also im geschnittenen Bereich, den man
        gerade nicht sehen soll. Eine ganze Bilddauer trifft dagegen sicher das
        letzte Bild davor.
        """
        eps = 1e-4
        if kind == "in":
            return max(t - eps, 0.0)
        return max(t - (1.0 / self._get_current_fps()) - eps, 0.0)

    # ------------------------------------------------------------------------
    # Player-Auskuenfte
    # ------------------------------------------------------------------------
    def _get_current_fps(self) -> float:
        """
        Bildrate, in der die VORSCHAU rechnet. Fallback 25.0, wenn der Player
        keine liefert - siehe GesPlayerBackend.preview_fps().

        Nicht die Quellrate. Der Stepper zaehlt in Bildern, die man sieht, und
        die Vorschau ist nach oben gedeckelt. Beide Groessen muessen dieselbe
        sein: mit dieser Bilddauer wird hier entschieden, ob das naechste Bild
        noch im Keep-Bereich liegt (_step_frame_forward/-backward) und wie weit
        vor eine Kante gesprungen wird (_edge_seek_target). Rechnete der Player
        in Vorschaubildern und diese Datei in Quellbildern, faende der Stepper
        an den Schnittkanten die falsche Stelle.

        Bei Material bis 30 fps sind beide Raten gleich.
        """
        fps = self.video_editor.get_preview_fps()
        if fps and float(fps) > 0:
            return float(fps)
        return 25.0

    def _get_current_global_time(self) -> float:
        """
        Aktuelle globale Zeit - dieselbe Quelle, mit der auch
        VideoCutManager rechnet.
        """
        return float(self.video_editor.get_current_position_s())

    def _get_total_duration(self) -> float:
        return sum(self.video_editor.multi_durations)

    def _get_kfs_list(self):
        """Die indizierten Keyframes aus dem MainWindow."""
        if not self.mainwindow:
            return []
        return self.mainwindow.global_keyframes or []
