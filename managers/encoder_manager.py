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

# core/gpx_parser.py

#
# managers/encoder_manager.py
#


import os
import sys
import json
import subprocess
import tempfile
import shutil
import contextlib
import builtins, contextlib, sys

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPlainTextEdit,
    QPushButton, QFileDialog, QApplication,
    QMessageBox
)
class _StringStream:
    def __init__(self, callback):
        # callback ist z. B. self._on_new_text
        self._cb = callback

    def write(self, s):
        if not s:
            return
        # direkt in dein Output-Fenster streamen
        self._cb(s)

    def flush(self):
        pass


# --- NEU: print() nur innerhalb eines Blocks wieder aktivieren ---
def _std_print(*args, **kwargs):
    """Das print des Exportfensters: schreibt nach sys.stdout, das waehrend
    des Exports ins Textfeld umgeleitet ist.

    AUF MODULEBENE, nicht in __enter__ verschachtelt: numba prueft beim Import
    (numba/core/typing/templates.py, register_global) fuer jedes eingebaute
    Objekt, ob getattr(sys.modules[obj.__module__], obj.__name__) noch dasselbe
    Objekt ist. Fuer builtins.print landet es dann hier - und eine
    verschachtelte Funktion gibt es unter ihrem Namen im Modul nicht. So
    brach am 10.09.2026 der Voice Remover (librosa importiert numba) mit
    "module 'managers.encoder_manager' has no attribute '_std_print'" ab.
    """
    sep   = kwargs.get("sep", " ")
    end   = kwargs.get("end", "\n")
    file  = kwargs.get("file", sys.stdout)
    flush = kwargs.get("flush", False)
    file.write(sep.join(map(str, args)) + end)
    if flush:
        try: file.flush()
        except Exception: pass


class _EnablePrintTemporarily(contextlib.AbstractContextManager):
    def __enter__(self):
        self._old_print = builtins.print
        builtins.print = _std_print
        return self
    def __exit__(self, exc_type, exc, tb):
        builtins.print = self._old_print
        return False

from config import MY_GLOBAL_TMP_DIR

##### hier xfade6_2.py rein kopieren!

#!/usr/bin/env python3


#############################################################################
# Aktuelle funktionierende Versiion mit xfade overlay und crf für nvenc!
# Neue Logik der copy cuts integriert!
############################################################################

#

# Aktuell wird nur das erste overlay richtug gesetzt der cut und das zweite overlay wird garnicht erst abgearbeitet
# das Endvideo sollte 1min20s sein und der Kreisel ist am Schild ausgeschnitten
# aktuelle Video-Länge: 2:12s

# Video startet bei dem Parkplatz beim ersten weissen balken
# erstes Overlay am baum
# Kreisel bei Schild geschnitten
# zweites overlay: beim baustellenschild
# Ende: Schild Barrabco

#################

# nutze hierzu die config6.json

import os
import sys
import re
import json
import subprocess
import tempfile
import shutil
from PySide6.QtCore import QSettings

"""
Was von dieser Datei uebrig ist.

Bis 5.01 stand hier der komplette ffmpeg-Render-Weg: Vorschnitt, Keyframe-
Suche, copy_cut, crossfade_2, concat, Overlay-Encode und die VAAPI/NVENC-
Parameter, zusammengehalten von xfade_main(). Seit 6.0 rendert der Encode-Mode
ueber GES (managers/ges_encoder_manager.ges_xfade_main), und der ffmpeg-Weg
wurde nie mehr aufgerufen. Er ist am 30.08.2026 entfernt worden, rund 1200
Zeilen.

Geblieben sind zwei Dinge, die es weiterhin gibt:

  EncoderDialog                Der Export-Dialog. Er sammelt die Einstellungen,
                               schreibt die JSON-Konfiguration und uebergibt sie
                               an ges_xfade_main(). Das Format der Konfiguration
                               ist dort beschrieben.
  measure_real_duration_fast   Misst die tatsaechliche Inhaltsdauer eines mit
                               "-c copy" geschnittenen Segments. Nur der
                               Copy-Mode braucht das, und nur der braucht hier
                               noch ffprobe.

ffmpeg wird ab 6.0 NICHT mehr mitgeliefert. Beide Messfunktionen laufen ueber
ffprobe aus dem PATH des Anwenders und werden nur erreicht, wenn der Copy-Mode
zur Verfuegung steht - der ist gesperrt, solange ffmpeg und ffprobe fehlen.
"""

    


    
    
# Wie weit vom Dateiende zurueck gemessen wird.
MEASURE_WINDOW_S = 5.0

# Wieviel die Messung hoechstens unter dem Containerwert liegen darf, bevor sie
# als unbrauchbar gilt. Der abzuziehende Ueberhang ist hoechstens eine GOP -
# bei GoPro-Material rund eine Sekunde, dokumentiert gemessen 0,901 s. Alles
# darunter ist keine Korrektur mehr, sondern ein Messfehler.
MEASURE_MAX_CORRECTION_S = 1.5


def measure_real_duration(path):
    """
    Liefert die TATSAECHLICHE Inhaltsdauer einer Datei (Frames x Framedauer).

    Warum nicht die Container-Angabe?
    Wird eine Datei mit "-ss" auf eine Position geschnitten, die kein Keyframe
    ist, schleppt sie die Vorlauf-Pakete ab dem letzten Keyframe mit. Container
    und nb_frames zaehlen diese mit, obwohl sie beim Abspielen uebersprungen
    werden. Gemessen an GX010089.MP4, Schnitt bei 2018.884 s:

        tatsaechlich dekodierbar : 2853 Frames = 95.195 s
        format=duration          : 96.096 s   (0.901 s zu viel)
        stream=nb_frames         : 2880       (27 Frames zu viel)

    Der Concat-Demuxer glaubt der Container-Angabe und setzt die naechste Datei
    dadurch fast eine Sekunde zu spaet an. Beim anschliessenden Neukodieren
    wird die Luecke mit einem stehenden Bild gefuellt -> sichtbarer Ruckler an
    der Nahtstelle zwischen zwei Videos.

    Gemessen wird ueber den Zeitstempel des LETZTEN Frames plus eine
    Framedauer. Alle Frames zu zaehlen ("-count_frames") liefert dasselbe
    Ergebnis, dauert bei einer 4K-Datei dieses Umfangs aber ueber anderthalb
    Minuten statt gut drei Sekunden.

    Gibt None zurueck, wenn die Messung nicht moeglich ist; der Aufrufer
    verhaelt sich dann wie bisher.
    """
    try:
        # 1) Bildrate und Container-Dauer aus dem Header - kostet nichts
        head = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate", "-show_entries",
             "format=duration", "-of", "json", path],
            capture_output=True, text=True, check=True)
        info = json.loads(head.stdout)
        st = (info.get("streams") or [{}])[0]
        num, _, den = (st.get("avg_frame_rate") or "0/0").partition("/")
        num, den = float(num or 0), float(den or 0)
        container_dur = float((info.get("format") or {}).get("duration") or 0)
        if num <= 0 or den <= 0 or container_dur <= 0:
            return None
        frame_dur = den / num

        # 2) nur die letzten Sekunden lesen und den letzten Zeitstempel nehmen
        #
        # Dem Intervall wird ausdruecklich ein ENDE mitgegeben. "START%" allein
        # heisst nicht zuverlaessig "bis zum Dateiende"; beobachtet wurde, dass
        # ffprobe dann je nach Lage gar nichts oder nur den ERSTEN Frame des
        # Intervalls liefert.
        start = max(0.0, container_dur - MEASURE_WINDOW_S)
        fenster = container_dur - start + 1.0
        tail = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-read_intervals", f"{start:.3f}%+{fenster:.3f}",
             "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True)
        last = None
        for line in tail.stdout.splitlines():
            line = line.strip().rstrip(",")
            if line:
                try:
                    last = float(line)
                except ValueError:
                    pass
        if last is None:
            return None
        gemessen = last + frame_dur

        # 3) Plausibilitaet. Diese Messung soll einen kleinen Ueberhang
        #    abziehen - bei einer geseekten Trim-Datei hoechstens eine GOP,
        #    gemessen 0,901 s. Kommt deutlich weniger heraus als der Container
        #    sagt, war die Messung unvollstaendig und der Wert ist Muell.
        #
        #    Genau das ist am 28.08.2026 passiert: statt 60,000 s kam 55,033 s
        #    heraus - der Intervallanfang plus ein Bild. Dieser Wert landete in
        #    der Concat-Liste, ffmpeg schnitt die Datei beim Zusammenfuegen auf
        #    diese Laenge zurueck (147 verworfene Bilder), und das fertige Video
        #    war knapp 5 Sekunden zu kurz.
        #
        #    Lieber den Containerwert nehmen: dann verhaelt sich der Export wie
        #    vor dieser Funktion - im schlimmsten Fall ein Ruckler an einer
        #    Naht, aber niemals ein zu kurzes Video.
        if gemessen < container_dur - MEASURE_MAX_CORRECTION_S:
            print(f"[WARN] measure_real_duration({os.path.basename(path)}): "
                  f"{gemessen:.3f}s gemessen, Container sagt {container_dur:.3f}s "
                  f"- unplausibel, benutze den Containerwert.")
            return None
        return gemessen
    except Exception as e:
        print(f"[WARN] measure_real_duration({path}) failed: {e}")
        return None


def measure_real_duration_fast(path):
    """
    Wie measure_real_duration(), aber ueber die PAKETE statt ueber dekodierte
    Frames - deshalb ohne Dekodierung und rund 35x schneller (0,16 s statt
    5,6 s bei einer 4K-Datei).

    Ein mit "-c copy" geschnittener Abschnitt beginnt immer beim Keyframe VOR
    der gewuenschten Position. Die Pakete dieses Vorlaufs bekommen negative
    Zeitstempel und werden im MP4 per Edit-List ausgeblendet - sichtbarer
    Inhalt sind genau die Pakete ab Zeitstempel 0. Deren Anzahl mal Framedauer
    ist die tatsaechliche Inhaltsdauer.

    Gemessen an segment_000.mp4 (Schnitt bei 2018.884 s):
        Pakete gesamt : 2880   (davon 27 Vorlauf)
        sichtbar      : 2853 = 95.195100 s
    - identisch zum Wert aus measure_real_duration().

    Faellt auf measure_real_duration() zurueck, wenn die Pakete keine
    brauchbaren Zeitstempel liefern (z. B. variable Framerate).
    """
    try:
        head = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate", "-of", "json", path],
            capture_output=True, text=True, check=True)
        st = (json.loads(head.stdout).get("streams") or [{}])[0]
        num, _, den = (st.get("avg_frame_rate") or "0/0").partition("/")
        num, den = float(num or 0), float(den or 0)
        if num <= 0 or den <= 0:
            return measure_real_duration(path)
        frame_dur = den / num

        pk = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
            capture_output=True, text=True, check=True)
        visible = 0
        for line in pk.stdout.splitlines():
            line = line.strip().rstrip(",")
            if not line or line == "N/A":
                continue
            try:
                if float(line) >= -1e-9:
                    visible += 1
            except ValueError:
                pass
        if visible <= 0:
            return measure_real_duration(path)
        return visible * frame_dur
    except Exception as e:
        print(f"[WARN] measure_real_duration_fast({path}) failed: {e}")
        return measure_real_duration(path)


        

    
###############################################################################
# 2) GPU-PRESET MAP
###############################################################################

gpu_map_nvidia = {
    "ultrafast": "fast",
    "superfast": "fast",
    "veryfast":  "fast",
    "faster":    "medium",
    "fast":      "hp",
    "medium":    "default",
    "slow":      "hq",
    "slower":    "hq",
    "veryslow":  "llhq"
}
gpu_map_amd = {
    "ultrafast": "speed",
    "superfast": "speed",
    "veryfast":  "speed",
    "faster":    "balanced",
    "fast":      "balanced",
    "medium":    "balanced",
    "slow":      "quality",
    "slower":    "quality",
    "veryslow":  "quality"
}
gpu_map_intel = {
    "ultrafast": "veryfast",
    "superfast": "veryfast",
    "veryfast":  "veryfast",
    "faster":    "fast",
    "fast":      "fast",
    "medium":    "medium",
    "slow":      "slow",
    "slower":    "slower",
    "veryslow":  "slower"
}

# VAAPI kennt kein -preset, sondern -quality als Ganzzahl:
# hoeherer Wert = schneller (siehe "ffmpeg -h encoder=h264_vaapi").
# Wir spiegeln damit dieselbe Skala wie bei den anderen Encodern.
gpu_map_vaapi = {
    "ultrafast": "7",
    "superfast": "7",
    "veryfast":  "6",
    "faster":    "5",
    "fast":      "4",
    "medium":    "4",
    "slow":      "3",
    "slower":    "2",
    "veryslow":  "1"
}

    


###############################################################################
# 5b) VAAPI-Hilfen (Linux: Intel-iGPU und AMD)
###############################################################################

_cached_vaapi_device = "unset"


# VAAPI-Encoder nehmen keine Software-Frames entgegen: die Filterkette
# muss auf format=nv12,hwupload enden.
VAAPI_FILTER_SUFFIX = "format=nv12,hwupload"


    

###############################################################################
# 8) KEYFRAMES => live counter
###############################################################################

import re


# Toleranz fuer die Keyframe-Suche: 1 ms. Zwei Bilder liegen mindestens 16 ms
# auseinander, ein Keyframe kann also nie versehentlich der falsche sein.
# Noetig, weil die Schnittzeiten durch die Umrechnung auf die Zeitachse nach
# dem Vorschnitt minimal danebenliegen koennen: 18.1 - 3.1 ergibt in Python
# 15.000000000000002, der erzwungene Keyframe steht aber bei 15.000000 - ohne
# Toleranz wird er uebersehen und der Schnitt springt eine GOP zu weit.
KF_EPS = 0.001


    


    
    


if __name__ == "__main__":
    main()


### Ende xfade6_2.py


#-----------------------------------------------------------------
# Neuer Code: 
#  - Wir definieren xfade_main(cfg_json) als Ersatz für main().
#  - Wir leiten print() ins QPlainTextEdit (EncoderDialog).
#  - Vorher machen wir ein Dateiauswahl-Fenster, damit der User 
#    den final_output festlegen kann, wenn du das möchtest.
#-----------------------------------------------------------------

class EncoderDialog(QDialog):
    """
    Dieses QFenster zeigt den gesamten ffmpeg-Output,
    den dein xfade6_2.py generiert (also Keyframe-Indexing, etc.),
    live an. 
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("XFade Encoding - This may take a while")
        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.close)
        layout.addWidget(self.btn_close)

        self.setLayout(layout)
        self.resize(800, 600)

        # Laeuft gerade ein Export? Dann fragt closeEvent() nach, und der
        # Encoder bekommt den Abbruchwunsch ueber _abbruch_pruefen().
        self._laeuft = False
        self._abbruch_gewuenscht = False

    def laeuft(self) -> bool:
        return self._laeuft

    def _abbruch_pruefen(self) -> bool:
        """Vom Encoder alle 200 ms gerufen. Pumpt die Ereignisse, damit der
        Dialog und sein Close-Knopf waehrend des Renderns reagieren - bisher
        kam die Oberflaeche nur bei jeder Prozentzeile zum Zug."""
        QApplication.processEvents()
        return self._abbruch_gewuenscht

    def closeEvent(self, event):
        if self._laeuft:
            if not self._abbruch_gewuenscht:
                antwort = QMessageBox.question(
                    self, "Stop the export?",
                    "The export is still running.\n\nStop it? The output file "
                    "is incomplete and will be deleted.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if antwort == QMessageBox.Yes:
                    self._abbruch_gewuenscht = True
                    self.btn_close.setEnabled(False)
                    self._on_new_text("[GES] Stopping the export...\n")
            # Das Fenster bleibt, bis der Encoder wirklich steht; run_encoding()
            # schliesst es dann.
            event.ignore()
            return
        super().closeEvent(event)

    def run_encoding(self, json_path: str, ziel: str = None):
        """
        1) Wir lesen json_path => c
        2) Zeigen ein QFileDialog, damit User final_out wählt (optional).
        3) Überschreiben c["final_output"].
        4) Leiten print(...) in self._on_new_text
        5) Rufen xfade_main(cfg_path) oder xfade_main_direct(c) auf

        ziel: steht er, gibt es keine Dateiauswahl und keine Meldung "Done"
        - der Hoerausschnitt einer Stelle (mainwindow._stelle_anhoeren)
        rendert so still in eine Datei, und dieser Dialog schliesst sich
        danach selbst. Rueckgabe True, wenn die Datei geschrieben wurde.
        """
        # 1) JSON lesen
        with open(json_path, "r", encoding="utf-8") as f:
            c = json.load(f)

        # 2) Dateiauswahl => final_out
        if ziel:
            chosen_out = ziel
        else:
            default_out = c.get("final_output", "final.mp4")
            chosen_out, _ = QFileDialog.getSaveFileName(
                self,
                "Select final output",
                default_out,
                "Video Files (*.mp4)"
            )
            if not chosen_out:
                self._on_new_text("[CANCELED] No output file selected.\n")
                return False

            if not chosen_out.lower().endswith('.mp4'):
                chosen_out += '.mp4'
                QMessageBox.information(
                    self,
                    "File Extension Added!",
                    f"Added '.mp4' extension to:\n{os.path.basename(chosen_out)}"
                )

        # => final_out überschreiben
        c["final_output"] = chosen_out

        # 3) c in eine temp-Datei schreiben, damit wir "xfade_main(...)" 
        #    ohne sys.argv aufrufen können:
        temp_cfg = os.path.join(tempfile.gettempdir(), "xfade_temp.json")
        with open(temp_cfg, "w", encoding="utf-8") as f2:
            json.dump(c, f2, indent=2)

        # 4) print-Umleitung => self._on_new_text
        stream = _StringStream(self._on_new_text)
        
        with _EnablePrintTemporarily(), contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            try:
                # 5) xfade_main(temp_cfg) => ruft dein "main()" auf, 
                #    nur ohne sys.argv.
                #
                # Der Encode-Mode rendert ueber GES. ffmpeg wird in KVRouite
                # nur noch fuer den Copy-Mode gebraucht, und der hat seinen
                # eigenen Weg in mainwindow.on_render_clicked().
                from managers.ges_encoder_manager import ges_xfade_main, GesRenderAbgebrochen
                self._laeuft = True
                self._abbruch_gewuenscht = False
                try:
                    ges_xfade_main(temp_cfg, abbruch=self._abbruch_pruefen)
                except GesRenderAbgebrochen:
                    self._laeuft = False
                    if not ziel:
                        QMessageBox.information(
                            self, "Export stopped",
                            "The export was stopped. The incomplete output file was deleted.")
                    self.close()
                    return False
                finally:
                    self._laeuft = False
                    self.btn_close.setEnabled(True)

                if ziel:
                    # Hoerausschnitt: still fertig, der Aufrufer spielt ab.
                    self.close()
                    return os.path.isfile(chosen_out)

                QMessageBox.information(
                     self,
                    "Done",
                    "Video exported successfully!"
                )
                
                for file in os.listdir(MY_GLOBAL_TMP_DIR):
                    full_path = os.path.join(MY_GLOBAL_TMP_DIR, file)
                    if file.endswith(".mp4"):
                        try:
                            os.remove(full_path)
                            print(f"[INFO] Deleted temp file: {full_path}")
                        except Exception as e:
                            print(f"[WARN] Could not delete temp file {full_path}: {e}")

                
                try:
                    shutil.rmtree(MY_GLOBAL_TMP_DIR)
                    #print("[INFO] TEMP-Ordner gelöscht:", MY_GLOBAL_TMP_DIR)
                    os.makedirs(MY_GLOBAL_TMP_DIR, exist_ok=True)
                except Exception as e:
                    #print("[WARN] TEMP konnte nicht gelöscht werden:", e)
                    os.makedirs(MY_GLOBAL_TMP_DIR, exist_ok=True)

            except Exception as e:
                print(f"[ERROR] {e}")
        

    def _on_new_text(self, text: str):
        """Callback pro print-Ausgabe => wir hängen ans Textfeld an."""
        self.text_edit.moveCursor(QTextCursor.End)
        self.text_edit.insertPlainText(text)
        self.text_edit.moveCursor(QTextCursor.End)
        QApplication.processEvents()
