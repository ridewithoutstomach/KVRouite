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

# core/gpx_parser.py

#
# managers/encoder_manager.py
#
# Kopiere unten deinen xfade6_2.py-Code GENAU rein, inkl. 
# aller Funktionen. Wir behalten also crossfade, overlays usw. 
# UNVERÄNDERT. Erst nach der Markierung "### Ende xfade6_2.py"
# kommt der neue Code.

#  Aktuelle VErsion: Der Endcut passt nicht!


import os
import sys
import json
import subprocess
import tempfile
import shutil
import contextlib

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPlainTextEdit,
    QPushButton, QFileDialog, QApplication,
    QMessageBox
)

# Hilfsklasse, um print(...) in ein Callback zu leiten:
class _StringStream:
    """Alle print()-Ausgaben in write(text)->callback(text)."""
    def __init__(self, callback):
        self._callback = callback
    def write(self, text):
        self._callback(text)
    def flush(self):
        pass


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
===========================================================
 Universal-Skript für ffmpeg-Encodierung, 
 Crossfades (skip_instructions) und Overlays (overlay_instructions),
 mit deaktivierten B-Frames (closed-GOP), Keyframe-Zähler,
 optionaler GPU-Nutzung und CPU->GPU-Preset-Mapping
===========================================================

JSON-Konfiguration (Beispiel):

{
  "videos": [
    "C:/Pfad/clip1.mp4",
    "C:/Pfad/clip2.mp4"
  ],

  "skip_instructions": [
    [10, 20, 2],
    [55, 65, 3]
  ],
  
  "overlay_instructions": [
    {
      "start": 2,
      "end": 7,
      "fade_in": 1.0,
      "fade_out": 1.0,
      "image": "C:/Logos/logo.png",
      "scale": 0.5,
      "x": 100,
      "y": 50
    },
    {
      "start": 30,
      "end": 35,
      "fade_in": 0,
      "fade_out": 0,
      "image": "C:/Logos/watermark.gif",
      "scale": 1.0,
      "x": "(W-w)/2",    // zentriert in X-Richtung
      "y": "H-h-10"      // 10 px vom unteren Rand
    }
  ],

  "merged_output": "merged.mp4",
  "final_output":  "final_out.mp4",

  "encoder": "libx265",
  "hardware_encode": "nvidia_hevc",
  "crf": 25,
  "fps": 30,
  "width": 1280,
  "preset": "fast"
}


ERLÄUTERUNG DER FELDER
----------------------

1) **"videos"** (Pflicht)  
   Liste der Quellvideos, die wir in Schritt (1) per ffmpeg concat 
   zu einer großen "merged.mp4" (bzw. 'merged_output') machen.

2) **"skip_instructions"** (optional)  
   Array von [start, end, overlap].  
   - start, end => Die Zeitbereiche (in Sekunden) sollen "geskippt" werden.  
   - overlap => Anzahl Sekunden, die wir crossfaden (Crossfade).  
   => Wir schneiden an Keyframes und erstellen pro Skip 
      zwei Overlap-Segmente + xfade => "type":"skip".

3) **"overlay_instructions"** (optional)  
   Array von Objekten:
   {
     "start": <Sekunde>,  // Ab wann Overlay erscheint
     "end":   <Sekunde>,  // Bis wann Overlay sichtbar
     "fade_in":  <Dauer>, // Zeit (in Sek.) ab start => Overlay "erscheint" (enable=..)
     "fade_out": <Dauer>, // Zeit (in Sek.) vor end => Overlay "verschwindet" (enable=..)
     "image":    "C:/..", // Pfad zum PNG/GIF (wenn GIF => loop)
     "scale":    0.5,     // Skalierungsfaktor => 0.5 => halbe Größe
     "x": 100,            // Position X (int oder ffmpeg-Ausdruck, z.B. "(W-w)/2")
     "y": 50              // Position Y 
   }
   => Segmente in [start..end] werden re-encoded, 
      wir legen das Overlay-Bild (PNG/GIF) 
      per ffmpeg overlay=...  
   => "fade_in"/"fade_out" steuert, wann im 
      Segment das Overlay "enable=between(...)" 
      aktiv ist.  
   => x,y = 0 => links/oben, 
      z.B. x="(W-w)/2" => zentriert, 
      y="H-h-10" => unten 10 px Abstand.

4) **"merged_output"** (Pflicht)  
   Zwischen-Datei, in die wir "videos" 
   zusammenkopieren => bframes=0 (closed-gop).

5) **"final_output"** (Pflicht)  
   Ziel-Datei nach allen Crossfades/Overlays, 
   am Ende per "-c copy" zusammengefasst.

6) **"encoder"** (optional, default: "libx265")  
   - "libx264", "libx265" => CPU  
   - wir nutzen bframes=0, closed-gop

7) **"hardware_encode"** (optional, default: "none")  
   - "none" => CPU  
   - "nvidia_h264", "nvidia_hevc" => GPU (NVENC)  
   - "amd_h264", "amd_hevc", "intel_h264", "intel_hevc"  
   => Wir mappen auf h264_nvenc / hevc_nvenc, 
      h264_amf / hevc_amf, etc.  
   => CRF => interpretiert als QP

8) **"crf"** (optional, default: 12)  
   - CPU => "CRF"  
   - GPU => "QP" => globale Konstante QP

9) **"preset"** (optional)  
   CPU: "ultrafast", "superfast", "veryfast", "faster", 
        "fast", "medium", "slow", "slower", "veryslow"  
   GPU (Nvidia): "fast", "hp", "hq", "llhq", usw. 
   => Wir mappen von CPU-Voreinstellungen 
      auf GPU-spezifische Presets

10) **"fps"** (optional, default: 30)  
    => wir resampeln das Video auf diese Rate

11) **"width"** (optional)  
    => Falls angegeben => ffmpeg scale=width:-2 
       => hält Seitenverhältnis. 
    => z.B. 1280 => 1280 x (height?)

BFRAMES=0 / CLOSED-GOP
-----------------------
Wir erzwingen minimal-bf / closed-gop, 
um Non-Monotonic-DTS beim finalen "-c copy" 
zu vermeiden.

KEYFRAME-ZÄHLER
---------------
Das Script zeigt beim Scannen "Indexing Keyframes: N", 
damit man bei größeren Videos eine Fortschrittsanzeige hat.

OVERLAYS & CROSSFADE: KEINE ÜBERSCHNEIDUNG
------------------------------------------
Bitte beachte: "skip_instructions" und 
"overlay_instructions" dürfen sich NICHT 
zeitlich überlappen, weil wir nur einen 
segmentbasierten Re-Encode pro Bereich machen. 
Das Script geht timeline-basiert vor, 
zählt erst den skip-Bereich, 
dann den overlay-Bereich.

FERTIG
------
=> Das Ergebnis liegt in "final_output".

"""

"""
KURZ-ERKLÄRUNG: x, y, W, H, w, h BEI OVERLAY

- 'x' und 'y' sind die Pixel-Koordinaten der linken oberen Ecke
  des Overlays im Hauptvideo (Video-Breite= W, Video-Höhe= H).

- 'w', 'h' bezeichnen die Breite/Höhe des Overlays (nach scale=...).

- Typische Positionierungen:

  - Oben links:      x=0,       y=0
  - Unten rechts:    x="W-w",   y="H-h"
  - Zentriert:       x="(W-w)/2",  y="(H-h)/2"
  
- Mit Randabstand z. B. rechts/unten 20px:
  x="W - w - 20",  y="H - h - 20"
  Das bedeutet Weite des Videos minud Weite des Overlays minus 10 pixel!

So kannst du das Overlay per ffmpeg-Ausdruck 'W'/'H'/'w'/'h'
genau platzieren (auch 'main_w'/'main_h'/'overlay_w'/'overlay_h' möglich).
"""
###############################################################################
# 1) QSETTINGS => TEMP
###############################################################################

def get_or_create_encoder_temp_dir():
    s = QSettings("VGSync","VGSync")
    key = "encoderTempDir"
    current= s.value(key,"",type=str)
    if not current:
        default_path= os.path.join(tempfile.gettempdir(),"my_vgsync_encoder")
        s.setValue(key,default_path)
        current = default_path
    os.makedirs(current,exist_ok=True)
    return current

def clear_encoder_temp_dir():
    tdir = get_or_create_encoder_temp_dir()
    try:
        shutil.rmtree(tdir)
    except:
        pass
    os.makedirs(tdir,exist_ok=True)
    return tdir
    
def compute_keep_segments(skip_instructions, total_duration):
    """
    Gibt die Segmente zurück, die **behalten** werden sollen,
    also zwischen -2 (Anfangs-Trim) und -1 (End-Trim)
    Nur Bereiche außerhalb dieser Skips werden behalten.
    """
    trim_ranges = [ (s, e) for s, e, mode in skip_instructions if mode in (-2, -1) and e > s ]
    trim_ranges.sort()

    keep_segments = []
    current = 0.0

    for s, e in trim_ranges:
        if s > current:
            keep_segments.append([current, s])
        current = max(current, e)

    if current < total_duration:
        keep_segments.append([current, total_duration])

    return keep_segments

    
def remap_time(t, timeline_map):
    """
    Mappt eine Zeit aus Original-Zeitleiste auf neue Timeline (nach Pre-Trim)
    Gibt None zurück, wenn die Zeit nicht im behaltenen Bereich liegt
    """
    for i, entry in enumerate(timeline_map):
        src_start = entry["src_start"]
        src_end = entry["src_end"]
        dst_start = entry["dst_start"]
        if src_start <= t < src_end:
            return dst_start + (t - src_start)
        if i == len(timeline_map) - 1 and abs(t - src_end) < 1e-6:
            return dst_start + (src_end - src_start)
    return None


def pre_trim_input_videos(videos, keep_segments, temp_dir):
    """
    Schneidet alle relevanten Keep-Segmente aus allen Videos heraus,
    wobei die Zeitachsen über die gesamte Videoliste laufen.
    Gibt: Liste Trim-Dateien, Mapping-Table mit src_start/src_end/dst_start
    """
    result_files = []
    timeline_map = []
    dst_time = 0.0
    counter = 1

    # Ermittele Gesamtlänge der Videos
    durations = []
    for v in videos:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", v]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        durations.append(float(out.stdout.strip()))

    video_ranges = []  # Liste: (video_index, start_time_in_video, abs_time_start)
    current_abs = 0.0
    for i, dur in enumerate(durations):
        video_ranges.append((i, 0.0, current_abs))
        current_abs += dur

    for seg_start, seg_end in keep_segments:
        for i, (vidx, local_start, abs_start) in enumerate(video_ranges):
            abs_end = abs_start + durations[vidx]
            if seg_end <= abs_start:
                continue
            if seg_start >= abs_end:
                continue

            # Schnittbereich im aktuellen Video (teilweise oder ganz)
            cut_start = max(seg_start, abs_start)
            cut_end = min(seg_end, abs_end)

            ss_local = cut_start - abs_start
            duration = cut_end - cut_start

            if duration <= 0:
                continue

            outname = os.path.join(temp_dir, f"trim_{counter:03d}_{int(cut_start)}_{int(cut_end)}.mp4")
            cmd = [
                "ffmpeg", "-hide_banner", "-y",
                "-ss", f"{ss_local:.3f}",
                "-i", videos[vidx],
                "-t", f"{duration:.3f}",
                "-map", "0:v:0", "-c", "copy",
                outname
            ]
            print("PRE-TRIM:", " ".join(cmd))
            #subprocess.run(cmd, check=True)
            run_command_gui(cmd, log_func=print)  # oder deine GUI-Logfunktion

            result_files.append(outname)
            timeline_map.append({
                "src_start": cut_start,
                "src_end": cut_end,
                "dst_start": dst_time
            })
            dst_time += duration
            counter += 1

    return result_files, timeline_map
    
    
def run_command_gui(cmd, log_func=print):
    """
    Führt einen externen Befehl aus und streamt stdout + stderr live in die GUI (z. B. QTextEdit).
    """
    log_func(f"[CMD] {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Hier kommt auch das ffmpeg-Encoding rein!
        bufsize=1,
        universal_newlines=True,
    )

    for line in process.stdout:
        if line:
            log_func(line.rstrip())

    process.wait()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)
        
def remap_instructions(skip_instructions, overlay_instructions, timeline_map):
    """
    Remapt skip_instructions und overlay_instructions auf die neue Zeitachse nach Pre-Trim.
    - Nur Skips mit value >= 0.1 (also keine -1/-2) werden berücksichtigt
    - Der dritte Wert wird als xfade_duration übernommen
    """
    new_skips = []
    for s, e, val in skip_instructions:
        if val in (-1, -2):  # Pre-Trim Skips -> wurden bereits geschnitten
            continue
        rs = remap_time(s, timeline_map)
        re = remap_time(e, timeline_map)
        if rs is not None and re is not None and re > rs:
            new_skips.append([rs, re, val])  # val ist hier xfade_dur

    new_overlays = []
    for ov in overlay_instructions:
        rs = remap_time(ov["start"], timeline_map)
        re = remap_time(ov["end"], timeline_map)
        if rs is not None and re is not None and re > rs:
            new_overlays.append({
                "start": rs,
                "end":   re,
                "fade_in": ov.get("fade_in", 1.0),
                "fade_out": ov.get("fade_out", 1.0),
                "image": ov["image"],
                "scale": ov.get("scale", 1.0),
                "x": ov.get("x", 0),
                "y": ov.get("y", 0)
            })

    return new_skips, new_overlays

    
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

def map_preset_for_gpu(user_preset, hw_encode):
    if not user_preset:
        return None
    up= user_preset.lower()
    hw_lc= (hw_encode or "").lower()
    if hw_lc.startswith("nvidia_"):
        return gpu_map_nvidia.get(up,"default")
    elif hw_lc.startswith("amd_"):
        return gpu_map_amd.get(up,"balanced")
    elif hw_lc.startswith("intel_"):
        return gpu_map_intel.get(up,"medium")
    return user_preset
    
    
def get_kf_le_with_margin(kf_list, time, margin):
    """
    Sucht in kf_list das Keyframe, das <= (time - margin) liegt.
    Liegt (time - margin) < 0, dann wird 0 genommen.
    Gibt das 'größte' Keyframe zurück, das immer noch <= diesem Wert ist.
    """
    target = time - margin
    if target < 0:
        target = 0
    best = kf_list[0]
    for k in kf_list:
        if k <= target:
            best = k
        else:
            break
    return best
    

###############################################################################
# 3) DETERMINE ENCODER
###############################################################################

def determine_encoder(cpu_encoder="libx265", hw_encode=None):
    """
    => (encoderName, mode) => e.g. ("libx264","cpu"), ("hevc_nvenc","gpu")
    """
    if not hw_encode or hw_encode.lower()=="none":
        return cpu_encoder,"cpu"
    hw_map={
        "nvidia_h264":"h264_nvenc",
        "nvidia_hevc":"hevc_nvenc",
        "amd_h264":"h264_amf",
        "amd_hevc":"hevc_amf",
        "intel_h264":"h264_qsv",
        "intel_hevc":"hevc_qsv"
    }
    val= hw_map.get(hw_encode.lower(),"")
    if not val:
        print(f"[WARN] unknown hw_encode={hw_encode}, fallback CPU {cpu_encoder}")
        return cpu_encoder,"cpu"
    return val,"gpu"

###############################################################################
# 4) BFRAMES=0 => CLOSED-GOP
###############################################################################

def get_cpu_closedgop_params(enc_name="libx265"):
    if enc_name=="libx264":
        return ["-x264-params","bframes=0:scenecut=0","-g","15","-keyint_min","15"]
    else:
        return ["-x265-params","bframes=0:no-open-gop=1:scenecut=0","-g","15","-keyint_min","15"]

def get_gpu_closedgop_params(hw_encode):
    return ["-bf","0","-g","15"]

###############################################################################
# 5) CPU CRF vs GPU pseudo-CRF
###############################################################################

def clamp_crf(crf_val):
    if crf_val<0: crf_val=0
    if crf_val>51: crf_val=51
    return crf_val

###############################################################################
# 6) SCALE-FILTER
###############################################################################

def build_scale_filter(width):
    if width is None:
        return None
    return f"scale={width}:-2"

###############################################################################
# 7) ENCODE_CLOSEDGOP => CPU CRF / GPU VBR_HQ + -cq
###############################################################################

def encode_closedgop(
    concat_file,
    outname,
    encoder="libx265",
    hw_encode=None,
    fps=None,
    crf=None,       # read from config; no default 12
    width=None,
    preset=None
):
    enc_name, mode = determine_encoder(encoder, hw_encode)
    real_preset = preset
    if mode=="gpu":
        real_preset= map_preset_for_gpu(preset, hw_encode)

    filter_str= build_scale_filter(width)

    cmd=[
        "ffmpeg","-hide_banner","-y",
        "-f","concat","-safe","0",
        "-i", concat_file,
        "-an"
    ]

    # if user didn't specify => fallback?
    if crf is None:
        crf=23  # or 25 ?

    if mode=="cpu":
        # => real CRF
        p_extra= get_cpu_closedgop_params(enc_name)
        cmd+= ["-c:v", enc_name, "-crf", str(crf)]
        if real_preset:
            cmd+= ["-preset", real_preset]
        cmd+= p_extra
        print(f"[DEBUG] CPU => CRF={crf}")

    else:
        # => GPU => pseudo CRF => vbr_hq + -cq
        # clamp 0..51
        qv= clamp_crf(crf)
        p_extra= get_gpu_closedgop_params(hw_encode)
        cmd+=["-c:v", enc_name,
              "-rc:v","vbr_hq",
              "-cq", str(qv)]
        if real_preset:
            cmd+= ["-preset", real_preset]
        cmd+= p_extra
        print(f"[DEBUG] GPU => vbr_hq + -cq={qv}")

    if fps:
        cmd+= ["-r", str(fps)]
    if filter_str:
        cmd+= ["-vf", filter_str]

    cmd+= [outname]
    print("ENCODE_CLOSEDGOP:", " ".join(cmd))
    #subprocess.run(cmd, check=True)
    run_command_gui(cmd, log_func=print)  # oder deine GUI-Logfunktion
    

###############################################################################
# 8) KEYFRAMES => live counter
###############################################################################

import re

def get_keyframes(src):
    print(f"\nIndexing Keyframes in [may take a while - stay tuned ] {src} ...")
    pattern= re.compile(r'"best_effort_timestamp_time"\s*:\s*"')
    cmd=[
        "ffprobe","-hide_banner",
        "-select_streams","v:0",
        "-skip_frame","nokey",
        "-show_frames",
        "-show_entries","frame=best_effort_timestamp_time",
        "-print_format","json",
        "-i", src
    ]
    p= subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    lines=[]
    count=0
    while True:
        line= p.stdout.readline()
        if not line: break
        lines.append(line)
        if pattern.search(line):
            count+=1
            m = re.search(r'"best_effort_timestamp_time"\s*:\s*"([^"]+)"', line)
            t_str = m.group(1) if m else "?"
            #print(f"\rKeyframes gefunden: {count} => Zeit: {t_str}", end='', flush=True)
    p.wait()
    print()
    data= json.loads("".join(lines))
    frames_data= data.get("frames",[])
    times=[]
    for fr in frames_data:
        t= float(fr.get("best_effort_timestamp_time","0"))
        times.append(t)
    times.sort()
    print(f"Total Keyframes found: {len(times)}\n")
    
    #for i, t in enumerate(times, start=1):
    #    print(f" - Keyframe {i} bei {t:.3f}s")
    return times        
def get_kf_le(kf_list,t):
    if not kf_list:
        return 0.0
    best=kf_list[0]
    for k in kf_list:
        if k<=t:
            best=k
        else:
            break
    return best

def get_kf_ge(kf_list,t):
    if not kf_list:
        return t
    for k in kf_list:
        if k>=t:
            return k
    return kf_list[-1]

###############################################################################
# 9) COPY_CUT / CROSSFADE
###############################################################################

def copy_cut(src,start,end,outfile):
    dur= end-start
    if dur<=0:
        raise ValueError("invalid cut dur => start={start},end={end}")
    cmd=[
        "ffmpeg","-hide_banner","-y",
        "-ss",f"{start:.3f}",
        "-i",src,
        "-t",f"{dur:.3f}",
        "-map","0:v:0",
        "-c","copy",
        outfile
    ]
    print("COPY_CUT:", " ".join(cmd))
    subprocess.run(cmd,check=True)

def crossfade_2(
    inA,inB,outname,
    encoder="libx265",
    hw_encode=None,
    crf=23,
    fps=None,width=None,preset=None,
    overlap=2
):
    enc_name, mode= determine_encoder(encoder,hw_encode)
    real_preset= preset
    if mode=="gpu":
        real_preset= map_preset_for_gpu(preset,hw_encode)

    filter_complex=[]
    if width:
        filter_complex.append(f"[0:v]scale={width}:-2,format=yuv420p[v0]")
        filter_complex.append(f"[1:v]scale={width}:-2,format=yuv420p[v1]")
    else:
        filter_complex.append("[0:v]format=yuv420p[v0]")
        filter_complex.append("[1:v]format=yuv420p[v1]")
    filter_complex.append(f"[v0][v1]xfade=transition=fade:duration={overlap}:offset=0[vout]")
    flt=";".join(filter_complex)

    cmd=[
        "ffmpeg","-hide_banner","-y",
        "-i",inA,
        "-i",inB,
        "-filter_complex",flt,
        "-map","[vout]"
    ]

    if mode=="cpu":
        # CPU => -crf
        p_extra= get_cpu_closedgop_params(enc_name)
        cmd+= ["-c:v", enc_name, "-crf", str(crf)]
        if real_preset:
            cmd+= ["-preset", real_preset]
        cmd+= p_extra
        print(f"[DEBUG] CROSSFADE => CPU => CRF={crf}")
    else:
        # GPU => pseudo CRF => vbr_hq -cq crf
        qv= clamp_crf(crf)
        p_extra= get_gpu_closedgop_params(hw_encode)
        cmd+= ["-c:v", enc_name, "-rc","vbr_hq", "-cq", str(qv)]
        if real_preset:
            cmd+= ["-preset", real_preset]
        cmd+= p_extra
        print(f"[DEBUG] CROSSFADE => GPU => -cq={qv}")

    if fps:
        cmd+=["-r",str(fps)]
    cmd+=["-pix_fmt","yuv420p","-an", outname]
    print("CROSSFADE_2:", " ".join(cmd))
    subprocess.run(cmd,check=True)

###############################################################################
# 10) FINAL CONCAT
###############################################################################

def final_concat_copy(parts,outfile):
    tmp_list= os.path.splitext(outfile)[0]+"_concat.txt"
    with open(tmp_list,"w",encoding="utf-8") as f:
        for p in parts:
            abspath= os.path.abspath(p)
            f.write(f"file '{abspath}'\n")

    cmd=[
        "ffmpeg","-hide_banner","-y",
        "-f","concat","-safe","0",
        "-i", tmp_list,
        "-map","0:v:0",
        "-c","copy",
        outfile
    ]
    print("FINAL CONCAT COPY:", " ".join(cmd))
    subprocess.run(cmd,check=True)
    os.remove(tmp_list)

###############################################################################
# 11) ALPHA FADE OVERLAY
###############################################################################

def _build_overlay_input_args(img):
    ext= os.path.splitext(img.lower())[1]
    if ext in (".png",".jpg",".jpeg",".bmp"):
        return ["-loop","1","-f","image2","-i", img]
    elif ext==".gif":
        return ["-stream_loop","-1","-i", img]
    else:
        return ["-i", img]

def overlay_segment_encode(
    in_segment,out_segment,
    overlay_image,
    fade_in=1.0,fade_out=1.0,
    seg_duration=None,scale=1.0,x=0,y=0,
    encoder="libx265",hw_encode=None,crf=23,
    fps=None,preset=None,width=None
):
    # => real alpha fade => RGBA => fade in/out => scale => overlay
    # => same idea as we had:
    #   fade_in => 0..fade_in => alpha=0..1
    #   fade_out => (dur-fade_out)..dur => alpha=1..0
    if seg_duration is None:
        cmd_dur=[
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=noprint_wrappers=1:nokey=1",
            in_segment
        ]
        rr=subprocess.run(cmd_dur,capture_output=True,text=True,check=True)
        seg_duration= float(rr.stdout.strip())

    fade_out_start= seg_duration - fade_out
    if fade_out_start<0:
        fade_out_start=0

    filter_complex=[]
    chain=[]
    chain.append("format=rgba")
    if fade_in>0:
        chain.append(f"fade=t=in:st=0:d={fade_in:.3f}:alpha=1")
    if fade_out>0:
        chain.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}:alpha=1")
    chain.append(f"scale=iw*{scale}:ih*{scale}:force_original_aspect_ratio=decrease")

    chain_str=",".join(chain)
    filter_complex.append(f"[1:v]{chain_str}[ov1]")

    base_in="[vbase]"
    if width:
        filter_complex.append(f"[0:v]scale={width}:-2,format=yuv420p[vbase]")
    else:
        filter_complex.append("[0:v]format=yuv420p[vbase]")
    x_str= str(x)
    y_str= str(y)
    overlay_str= f"{base_in}[ov1]overlay=x={x_str}:y={y_str}:format=auto[vout]"
    filter_complex.append(overlay_str)

    fc_str= ";".join(filter_complex)

    overlay_input_args= _build_overlay_input_args(overlay_image)
    cmd=[
        "ffmpeg","-hide_banner","-y",
        "-i", in_segment
    ]+ overlay_input_args + [
        "-filter_complex", fc_str,
        "-map","[vout]",
        "-t", f"{seg_duration:.3f}"
    ]

    enc_name, mode= determine_encoder(encoder, hw_encode)
    real_preset= preset
    if mode=="gpu":
        real_preset= map_preset_for_gpu(preset,hw_encode)

    if mode=="cpu":
        p_extra= get_cpu_closedgop_params(enc_name)
        cmd+= ["-c:v", enc_name, "-crf", str(crf)]
        if real_preset:
            cmd+= ["-preset", real_preset]
        cmd+= p_extra
        print(f"[DEBUG] overlay => CPU => CRF={crf}")
    else:
        # GPU => pseudo CRF => vbr_hq -cq
        qv= clamp_crf(crf)
        p_extra= get_gpu_closedgop_params(hw_encode)
        cmd+= ["-c:v", enc_name, "-rc","vbr_hq","-cq", str(qv)]
        if real_preset:
            cmd+= ["-preset", real_preset]
        cmd+= p_extra
        print(f"[DEBUG] overlay => GPU => -cq={qv}")

    if fps:
        cmd+=["-r",str(fps)]
    cmd+=["-pix_fmt","yuv420p","-an", out_segment]

    print("OVERLAY_SEGMENT_ENCODE:", " ".join(cmd))
    subprocess.run(cmd,check=True)

###############################################################################
# 12) Build skip/overlay events
###############################################################################
def build_segments_with_skip_and_overlay(
    merged_file, kf_list, total_duration,
    skip_instructions, overlay_instructions,
    encoder="libx265", hw_encode=None, crf=23, fps=None, width=None, preset=None
):
    """
    Erzeugt Segmente (normal/skip/overlay) streng aufsteigend entlang der Timeline,
    damit es keine Überschneidungen oder rückwärtslaufende Schnitte gibt.
    """

    # 1) Events aus JSON sammeln
    events = []
    for triple in skip_instructions:
        s, e, o = triple
        ev = {"type": "skip", "start": float(s), "end": float(e), "overlap": float(o)}
        events.append(ev)

    for ov in overlay_instructions:
        ev = {
            "type":     "overlay",
            "start":    float(ov["start"]),
            "end":      float(ov["end"]),
            "fade_in":  float(ov.get("fade_in", 1.0)),
            "fade_out": float(ov.get("fade_out", 1.0)),
            "image":    ov["image"],
            "scale":    float(ov.get("scale", 1.0)),
            "x":        ov.get("x", 0),
            "y":        ov.get("y", 0)
        }
        events.append(ev)

    # Sortieren nach Startzeit
    events.sort(key=lambda x: x["start"])

    temp_dir = get_or_create_encoder_temp_dir()
    segments = []
    out_count = 1
    current_pos = 0.0

    # Debug-Liste
    debug_logs = []

    # ============= Schleife durch alle Events =============
    for ev in events:
        t1 = ev["start"]
        t2 = ev["end"]
        if t2 <= t1:
            # Ungültig, überspringen
            continue

        # 1) Normal-Part: [current_pos..t1]
        if t1 > current_pos:
            seg_start = get_kf_le(kf_list, current_pos)
            seg_end   = get_kf_le(kf_list, t1)
            if seg_end > seg_start:
                part_out = os.path.join(
                    temp_dir, f"part_{out_count:02d}_{int(seg_start)}_{int(seg_end)}.mp4"
                )
                copy_cut(merged_file, seg_start, seg_end, part_out)
                segments.append(part_out)
                debug_logs.append(
                    f"[NORMAL] JSON-Bereich: {current_pos:.2f}..{t1:.2f} "
                    f"=> Keyframes: {seg_start:.2f}..{seg_end:.2f}"
                )
                out_count += 1
            normal_end = seg_end
        else:
            # Falls t1 <= current_pos, sind wir schon "drüber"
            normal_end = current_pos

        # 2) Schauen, ob wir SKIP oder OVERLAY haben
        if ev["type"] == "skip":
            overlap = ev["overlap"]
            #if t2 > total_duration:
            #    t2 = total_duration
            #if t1 >= total_duration:
            #    debug_logs.append(f"[SKIP] JSON-Bereich {t1:.2f}..{t2:.2f} liegt komplett hinter Video-Ende => skip!")
            #    continue
                
            # Wir "skippen" [t1..t2], aber crossfaden über overlap
            # => Segment A = [normal_end..(t1+overlap)]
            # => Segment B = [t2..(t2+overlap)]
            A_start = normal_end
            A_end   = get_kf_le(kf_list, t1 + overlap)
            if A_end < A_start:
                A_end = A_start

            skipA = os.path.join(temp_dir, f"skipA_{out_count:02d}.mp4")
            copy_cut(merged_file, A_start, A_end, skipA)

            #B_start = get_kf_ge(kf_list, t2)
            B_start = get_kf_ge(kf_list, min(t2, total_duration))
            B_end   = get_kf_le(kf_list, t2 + overlap)
            
            if B_end > total_duration:
                B_end = total_duration
            if B_start >= B_end:
                # kein (gültiges) B-Segment => kein Crossfade möglich
                debug_logs.append(
                    f"[SKIP] B-Segment entfällt (Start={B_start:.2f} >= End={B_end:.2f}). Nur A-Segment wird benutzt."
                )
                segments.append(skipA)
                current_pos = max(current_pos, t2 + overlap)
                out_count += 1
                continue
            
            #if B_end < B_start:
            #    B_end = B_start

            skipB = os.path.join(temp_dir, f"skipB_{out_count:02d}.mp4")
            copy_cut(merged_file, B_start, B_end, skipB)

            # Crossfade beider Segmente:
            xf_out = os.path.join(temp_dir, f"skipX_{out_count:02d}_{int(t1)}_{int(t2)}.mp4")
            crossfade_2(
                inA=skipA, inB=skipB, outname=xf_out,
                encoder=encoder, hw_encode=hw_encode, crf=crf,
                fps=fps, width=width, preset=preset,
                overlap=overlap
            )
            segments.append(xf_out)

            debug_logs.append(
                f"[SKIP] JSON-Bereich: {t1:.2f}..{t2:.2f}, overlap={overlap:.1f} "
                f"=> A=({A_start:.2f}..{A_end:.2f}), B=({B_start:.2f}..{B_end:.2f})"
            )
            out_count += 1

            # Jetzt ist current_pos = (t2 + overlap)
            current_pos = max(current_pos, (t2 + overlap))

        elif ev["type"] == "overlay":
            fade_in  = ev["fade_in"]
            fade_out = ev["fade_out"]
            ov_img   = ev["image"]
            sc       = ev["scale"]
            xx       = ev["x"]
            yy       = ev["y"]

            # Re-encode [t1..t2] => auf Keyframes gerundet
            ov_start = get_kf_le(kf_list, t1)
            ov_end   = get_kf_le(kf_list, t2)
            if ov_end < ov_start:
                ov_end = ov_start

            in_cut = os.path.join(temp_dir, f"ov_in_{out_count:02d}_{int(t1)}.mp4")
            copy_cut(merged_file, ov_start, ov_end, in_cut)

            out_cut = os.path.join(temp_dir, f"ov_out_{out_count:02d}_{int(t1)}_{int(t2)}.mp4")
            seg_dur = ov_end - ov_start
            overlay_segment_encode(
                in_segment=in_cut, out_segment=out_cut,
                overlay_image=ov_img, fade_in=fade_in, fade_out=fade_out,
                seg_duration=seg_dur, scale=sc, x=xx, y=yy,
                encoder=encoder, hw_encode=hw_encode, crf=crf,
                fps=fps, preset=preset, width=None
            )
            segments.append(out_cut)

            debug_logs.append(
                f"[OVERLAY] JSON-Bereich: {t1:.2f}..{t2:.2f} => "
                f"Keyframes: {ov_start:.2f}..{ov_end:.2f}"
            )
            out_count += 1

            # current_pos anheben
            current_pos = max(current_pos, t2)

    # 3) Letztes Segment (falls was übrig)
    if current_pos < total_duration:
        seg_start = get_kf_le(kf_list, current_pos)
        seg_end   = get_kf_le(kf_list, total_duration)
        if seg_end > seg_start:
            final_out = os.path.join(
                temp_dir, f"final_{out_count:02d}_{int(seg_start)}_{int(seg_end)}.mp4"
            )
            copy_cut(merged_file, seg_start, seg_end, final_out)
            segments.append(final_out)
            debug_logs.append(
                f"[END] JSON-Bereich: {current_pos:.2f}..{total_duration:.2f} => "
                f"{seg_start:.2f}..{seg_end:.2f}"
            )

    # ============= Debug-Ausgabe =============
    print("\n============== DEBUG SCHNITT-LISTE ==============")
    for line in debug_logs:
        print(line)
    print("=================================================\n")

    return segments
    
    


###############################################################################
# MAIN
###############################################################################
def xfade_main(cfg_path):
    
    #if len(sys.argv) < 2:
    #    print("Usage: python script.py config.json")
    #    sys.exit(1)

    #with open(sys.argv[1], "r", encoding="utf-8") as f:
    #    cfg = json.load(f)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
        
    videos = cfg["videos"]
    skip_list = cfg.get("skip_instructions", [])
    overlay_list = cfg.get("overlay_instructions", [])
    merged_out = cfg["merged_output"]
    final_out = cfg["final_output"]
    hw_encode = cfg.get("hardware_encode", "none")
    encoder = cfg.get("encoder", "libx265")
    crf = cfg.get("crf", 23)
    fps = cfg.get("fps", 30)
    width = cfg.get("width", None)
    preset = cfg.get("preset", None)

    temp_dir = tempfile.mkdtemp()
    print("[INFO] TempDir:", temp_dir)

    total_duration = 0.0
    for v in videos:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", v]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        total_duration += float(out.stdout.strip())

    keep_segments = compute_keep_segments(skip_list, total_duration)
    print("[INFO] Keep segments:", keep_segments)

    trimmed_parts, timeline_map = pre_trim_input_videos(videos, keep_segments, temp_dir)
    print("[INFO] Timeline map:", timeline_map)

    concat_txt = os.path.join(temp_dir, "concat_input.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for path in trimmed_parts:
            f.write(f"file '{os.path.abspath(path)}'\n")

    merged_path = os.path.join(temp_dir, merged_out)
    encode_closedgop(
        concat_file=concat_txt,
        outname=merged_path,
        encoder=encoder,
        hw_encode=hw_encode,
        fps=fps,
        crf=crf,
        width=width,
        preset=preset
    )

    cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", merged_path]
    rr = subprocess.run(cmd_dur, capture_output=True, text=True, check=True)
    new_duration = float(rr.stdout.strip())
    print("[INFO] Merged duration:", new_duration)

    kf = get_keyframes(merged_path)
    remapped_skips, remapped_overlays = remap_instructions(skip_list, overlay_list, timeline_map)

    parts = build_segments_with_skip_and_overlay(
        merged_file=merged_path,
        kf_list=kf,
        total_duration=new_duration,
        skip_instructions=remapped_skips,
        overlay_instructions=remapped_overlays,
        encoder=encoder,
        hw_encode=hw_encode,
        crf=crf,
        fps=fps,
        width=width,
        preset=preset
    )

    final_concat_copy(parts, final_out)
    print("\n== DONE == Final video:", final_out)

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


    def run_encoding(self, json_path: str):
        """
        1) Wir lesen json_path => c 
        2) Zeigen ein QFileDialog, damit User final_out wählt (optional).
        3) Überschreiben c["final_output"].
        4) Leiten print(...) in self._on_new_text
        5) Rufen xfade_main(cfg_path) oder xfade_main_direct(c) auf
        """
        # 1) JSON lesen
        with open(json_path, "r", encoding="utf-8") as f:
            c = json.load(f)

        # 2) Dateiauswahl => final_out
        default_out = c.get("final_output", "final.mp4")
        chosen_out, _ = QFileDialog.getSaveFileName(
            self,
            "Select final output",
            default_out,
            "Video Files (*.mp4 *.mov *.mkv *.avi)"
        )
        if not chosen_out:
            self._on_new_text("[ABBRUCH] Keine Ausgabedatei gewählt.\n")
            return
        # => final_out überschreiben
        c["final_output"] = chosen_out

        # 3) c in eine temp-Datei schreiben, damit wir "xfade_main(...)" 
        #    ohne sys.argv aufrufen können:
        temp_cfg = os.path.join(tempfile.gettempdir(), "xfade_temp.json")
        with open(temp_cfg, "w", encoding="utf-8") as f2:
            json.dump(c, f2, indent=2)

        # 4) print-Umleitung => self._on_new_text
        stream = _StringStream(self._on_new_text)
        with contextlib.redirect_stdout(stream):
            try:
                # 5) xfade_main(temp_cfg) => ruft dein "main()" auf, 
                #    nur ohne sys.argv.
                xfade_main(temp_cfg)
                QMessageBox.information(
                     self,
                    "Done",
                    "Video exported successfully!"
                )

            except Exception as e:
                print(f"[ERROR] {e}")
        

    def _on_new_text(self, text: str):
        """Callback pro print-Ausgabe => wir hängen ans Textfeld an."""
        self.text_edit.moveCursor(QTextCursor.End)
        self.text_edit.insertPlainText(text)
        self.text_edit.moveCursor(QTextCursor.End)
        QApplication.processEvents()
