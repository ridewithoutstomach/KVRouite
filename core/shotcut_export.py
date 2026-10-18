# -*- coding: utf-8 -*-
#
# This file is part of KVRouite.
#
# Copyright (C) 2026 by Bernd Eller
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
Export of the KVRouite timeline into a Shotcut project (.mlt).

Enables non-destructive further editing in the Shotcut video editor:
  - All source clips are referenced directly (preserving head and tail handles).
  - Cuts with crossfades appear as native Shotcut transition blocks (luma dissolve + audio mix) on Track V1.
  - Hard cuts (without crossfades) are positioned consecutively without gaps.
  - Multi-chapter recordings (e.g. GoPro continuous chapter files) are resolved across file boundaries.
  - Image overlays can optionally be placed on an overlay track (V2).
"""

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List, Tuple, Dict, Any, Optional

from PySide6.QtCore import QProcess


def can_open_in_shotcut() -> bool:
    """Return True if the shotcut executable is found on PATH."""
    return shutil.which("shotcut") is not None


def open_in_shotcut(mlt_path: str) -> bool:
    """Launch Shotcut with the specified .mlt project file."""
    if not can_open_in_shotcut():
        return False
    abs_path = os.path.abspath(mlt_path)
    try:
        # Use QProcess.startDetached to avoid holding the parent process
        ok = QProcess.startDetached("shotcut", [abs_path])
        if ok:
            return True
    except Exception:
        pass

    try:
        subprocess.Popen(["shotcut", abs_path], close_fds=True)
        return True
    except Exception:
        return False


def _keep_segmente(skip_list: List[List[float]], gesamt: float) -> List[List[float]]:
    """Bereiche, die bleiben, nachdem Anfangs- und End-Trim entfernt sind."""
    trims = sorted((s, e) for s, e, modus in skip_list if modus in (-2, -1) and e > s)
    keeps = []
    lauf = 0.0
    for s, e in trims:
        if s > lauf:
            keeps.append([lauf, s])
        lauf = max(lauf, e)
    if lauf < gesamt:
        keeps.append([lauf, gesamt])
    return keeps


def _stuecke_berechnen(skip_list: List[List[float]], gesamt_s: float) -> List[List[float]]:
    """Die Teilstuecke der Timeline aus der Schnittliste: [von, bis, blende_davor, blende_danach]."""
    keeps = _keep_segmente(skip_list, gesamt_s)

    kanten = []
    for s, e, v in skip_list:
        if v in (-2, -1):
            continue
        kanten.append((float(s), float(e), max(0.0, float(v))))
    kanten.sort()

    stuecke = []
    for k_von, k_bis in keeps:
        grenzen = [k_von]
        for s, e, _v in kanten:
            if k_von <= s and e <= k_bis:
                grenzen += [s, e]
        grenzen.append(k_bis)
        for i in range(0, len(grenzen) - 1, 2):
            von, bis = grenzen[i], grenzen[i + 1]
            if bis - von <= 0:
                continue
            blende_davor = 0.0
            blende_danach = 0.0
            for s, e, v in kanten:
                if v <= 0:
                    continue
                if abs(e - von) < 1e-6:
                    blende_davor = v
                if abs(s - bis) < 1e-6:
                    blende_danach = v
            stuecke.append([von, bis, blende_davor, blende_danach])
    return stuecke


def _rohbereich(von: float, bis: float, bl_davor: float, bl_danach: float):
    """Gibt (roh_von, roh_bis, bl_davor, bl_danach, halb_davor, halb_danach) zurueck."""
    halb_davor = bl_davor / 2.0
    halb_danach = bl_danach / 2.0
    if halb_davor + halb_danach >= (bis - von):
        halb_davor = halb_danach = 0.0
        bl_davor = bl_danach = 0.0
    return (von - halb_davor, bis + halb_danach, bl_davor, bl_danach, halb_davor, halb_danach)


def _resolve_partials(global_start: float, global_end: float, video_durations: List[float]) -> List[Tuple[int, float, float]]:
    """Zerlegt ein globales Zeitintervall in (video_index, local_start, local_end)."""
    results = []
    if global_end <= global_start or not video_durations:
        return results

    boundaries = []
    off = 0.0
    for d in video_durations:
        off += d
        boundaries.append(off)

    curr = global_start
    idx = 0
    prev_off = 0.0
    for i, b in enumerate(boundaries):
        if curr < b:
            idx = i
            prev_off = boundaries[i - 1] if i > 0 else 0.0
            break

    while curr < global_end and idx < len(boundaries):
        b_end = boundaries[idx]
        l_st = max(0.0, curr - prev_off)
        seg_end = min(global_end, b_end)
        l_en = max(l_st, seg_end - prev_off)
        if l_en > l_st:
            results.append((idx, l_st, l_en))
        curr = seg_end
        idx += 1
        if idx < len(boundaries):
            prev_off = boundaries[idx - 1]

    return results


def export_to_shotcut(
    videos: List[str],
    video_durations: List[float],
    skip_list: List[List[float]],
    out_mlt_path: str,
    width: int = 1920,
    height: int = 1080,
    fps_num: int = 30,
    fps_den: int = 1,
    title: str = "KVRouite Shotcut Project",
    overlays: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Export the timeline to an MLT XML project file readable by Shotcut.

    :param videos: List of absolute file paths to input videos.
    :param video_durations: List of durations in seconds for each video.
    :param skip_list: List of [start_s, end_s, xfade_s] cut definitions.
    :param out_mlt_path: Target path for the .mlt file.
    :param width: Target video frame width.
    :param height: Target video frame height.
    :param fps_num: Frame rate numerator.
    :param fps_den: Frame rate denominator.
    :param title: Project title.
    :param overlays: Optional list of overlay dictionaries.
    :return: The generated XML string.
    """
    total_dur = sum(video_durations)
    if total_dur <= 0.0:
        raise ValueError("Total video duration must be greater than zero.")

    def sec_to_frame(s: float) -> int:
        return int(round(float(s) * fps_num / float(fps_den)))

    stuecke = _stuecke_berechnen(skip_list, total_dur)

    root = ET.Element("mlt", {
        "LC_NUMERIC": "C",
        "version": "7.24.0",
        "title": title
    })

    # MLT Profile
    ET.SubElement(root, "profile", {
        "description": f"{width}x{height} {fps_num}/{fps_den}fps",
        "width": str(int(width)),
        "height": str(int(height)),
        "progressive": "1",
        "sample_aspect_num": "1",
        "sample_aspect_den": "1",
        "display_aspect_num": "16",
        "display_aspect_den": "9",
        "frame_rate_num": str(int(fps_num)),
        "frame_rate_den": str(int(fps_den)),
        "colorspace": "709"
    })

    # Video Producers
    for idx, (path, dur) in enumerate(zip(videos, video_durations)):
        abs_p = os.path.abspath(path)
        p_frames = max(1, sec_to_frame(dur))
        p = ET.SubElement(root, "producer", {
            "id": f"producer{idx}",
            "in": "0",
            "out": str(p_frames - 1)
        })
        ET.SubElement(p, "property", {"name": "length"}).text = str(p_frames)
        ET.SubElement(p, "property", {"name": "eof"}).text = "pause"
        ET.SubElement(p, "property", {"name": "resource"}).text = abs_p
        ET.SubElement(p, "property", {"name": "mlt_service"}).text = "avformat"
        ET.SubElement(p, "property", {"name": "seekable"}).text = "1"
        ET.SubElement(p, "property", {"name": "audio_index"}).text = "0"
        ET.SubElement(p, "property", {"name": "video_index"}).text = "0"

    # Main Bin playlist (for Shotcut playlist panel)
    main_bin = ET.SubElement(root, "playlist", {"id": "main_bin"})
    ET.SubElement(main_bin, "property", {"name": "xml_retain"}).text = "1"
    for idx, dur in enumerate(video_durations):
        p_frames = max(1, sec_to_frame(dur))
        ET.SubElement(main_bin, "entry", {
            "producer": f"producer{idx}",
            "in": "0",
            "out": str(p_frames - 1)
        })

    # Build pieces and transitions
    playlist_entries = []
    trans_counter = 0

    for i, stueck in enumerate(stuecke):
        von, bis, bl_davor, bl_danach = stueck
        _roh_von, _roh_bis, bl_davor, bl_danach, _halb_davor, _halb_danach = _rohbereich(*stueck)

        # 1) Transition before this piece
        if i > 0 and bl_davor > 0:
            trans_dur = bl_davor
            trans_frames = max(1, sec_to_frame(trans_dur))

            prev_bis = stuecke[i - 1][1]
            out_partials = _resolve_partials(prev_bis - trans_dur / 2.0, prev_bis + trans_dur / 2.0, video_durations)
            in_partials = _resolve_partials(von - trans_dur / 2.0, von + trans_dur / 2.0, video_durations)

            p_out_idx, p_out_st, _p_out_en = out_partials[-1] if out_partials else (0, 0, trans_dur)
            p_in_idx, p_in_st, _p_in_en = in_partials[0] if in_partials else (0, 0, trans_dur)

            f_out_in = sec_to_frame(p_out_st)
            f_out_out = f_out_in + trans_frames - 1
            f_in_in = sec_to_frame(p_in_st)
            f_in_out = f_in_in + trans_frames - 1

            t_id = f"tractor_trans_{trans_counter}"
            trans_counter += 1

            tr = ET.Element("tractor", {
                "id": t_id,
                "in": "0",
                "out": str(trans_frames - 1)
            })
            ET.SubElement(tr, "property", {"name": "shotcut:transition"}).text = "lumaMix"
            ET.SubElement(tr, "track", {
                "producer": f"producer{p_out_idx}",
                "in": str(f_out_in),
                "out": str(f_out_out)
            })
            ET.SubElement(tr, "track", {
                "producer": f"producer{p_in_idx}",
                "in": str(f_in_in),
                "out": str(f_in_out)
            })

            tr_v = ET.SubElement(tr, "transition", {
                "id": f"transition_{t_id}_v",
                "out": str(trans_frames - 1)
            })
            ET.SubElement(tr_v, "property", {"name": "a_track"}).text = "0"
            ET.SubElement(tr_v, "property", {"name": "b_track"}).text = "1"
            ET.SubElement(tr_v, "property", {"name": "mlt_service"}).text = "luma"
            ET.SubElement(tr_v, "property", {"name": "alpha_over"}).text = "1"

            tr_a = ET.SubElement(tr, "transition", {
                "id": f"transition_{t_id}_a",
                "out": str(trans_frames - 1)
            })
            ET.SubElement(tr_a, "property", {"name": "a_track"}).text = "0"
            ET.SubElement(tr_a, "property", {"name": "b_track"}).text = "1"
            ET.SubElement(tr_a, "property", {"name": "mlt_service"}).text = "mix"
            ET.SubElement(tr_a, "property", {"name": "combine"}).text = "1"

            playlist_entries.append(("tractor", tr, t_id, trans_frames))

        # 2) Solo section of this piece
        solo_start_s = von + (bl_davor / 2.0 if bl_davor > 0 else 0.0)
        solo_end_s = bis - (bl_danach / 2.0 if bl_danach > 0 else 0.0)
        if solo_end_s > solo_start_s:
            for p_idx, p_st, p_en in _resolve_partials(solo_start_s, solo_end_s, video_durations):
                in_f = sec_to_frame(p_st)
                out_f = max(in_f, sec_to_frame(p_en) - 1)
                playlist_entries.append(("entry", f"producer{p_idx}", in_f, out_f))

    # Append all transition tractors to the root before the playlist
    for item in playlist_entries:
        if item[0] == "tractor":
            root.append(item[1])

    # Track V1 Playlist
    pl0 = ET.SubElement(root, "playlist", {"id": "playlist0"})
    ET.SubElement(pl0, "property", {"name": "shotcut:video"}).text = "1"
    ET.SubElement(pl0, "property", {"name": "shotcut:name"}).text = "V1"

    total_timeline_frames = 0
    for item in playlist_entries:
        if item[0] == "tractor":
            _typ, _tr_elem, t_id, frames = item
            ET.SubElement(pl0, "entry", {
                "producer": t_id,
                "in": "0",
                "out": str(frames - 1)
            })
            total_timeline_frames += frames
        else:
            _typ, p_id, in_f, out_f = item
            ET.SubElement(pl0, "entry", {
                "producer": p_id,
                "in": str(in_f),
                "out": str(out_f)
            })
            total_timeline_frames += (out_f - in_f + 1)

    # Optional Track V2 for Overlays
    has_overlays = bool(overlays)
    if has_overlays:
        # Sort overlays by start time
        valid_ovls = [ov for ov in overlays if ov.get("image") and os.path.isfile(ov.get("image"))]
        valid_ovls.sort(key=lambda x: float(x.get("start", 0.0)))
        if valid_ovls:
            pl1 = ET.SubElement(root, "playlist", {"id": "playlist1"})
            ET.SubElement(pl1, "property", {"name": "shotcut:video"}).text = "1"
            ET.SubElement(pl1, "property", {"name": "shotcut:name"}).text = "V2 (Overlays)"
            current_cursor_f = 0
            for o_idx, ov in enumerate(valid_ovls):
                o_img = os.path.abspath(ov["image"])
                o_start_f = max(0, sec_to_frame(float(ov.get("start", 0.0))))
                o_end_f = max(o_start_f + 1, sec_to_frame(float(ov.get("end", 0.0))))
                o_len_f = o_end_f - o_start_f

                o_prod_id = f"producer_ovl_{o_idx}"
                o_prod = ET.SubElement(root, "producer", {
                    "id": o_prod_id,
                    "in": "0",
                    "out": str(o_len_f - 1)
                })
                ET.SubElement(o_prod, "property", {"name": "length"}).text = str(o_len_f)
                ET.SubElement(o_prod, "property", {"name": "eof"}).text = "pause"
                ET.SubElement(o_prod, "property", {"name": "resource"}).text = o_img
                ET.SubElement(o_prod, "property", {"name": "mlt_service"}).text = "qimage"
                ET.SubElement(o_prod, "property", {"name": "mlt_image_format"}).text = "rgba"
                ET.SubElement(o_prod, "property", {"name": "aspect_ratio"}).text = "1"

                fade_in_s = float(ov.get("fade_in", 0.0) or 0.0)
                fade_out_s = float(ov.get("fade_out", 0.0) or 0.0)

                if fade_in_s > 0.0:
                    fin_frames = max(1, sec_to_frame(fade_in_s))
                    f_in = ET.SubElement(o_prod, "filter", {"id": f"filter_ovl_{o_idx}_fadein"})
                    ET.SubElement(f_in, "property", {"name": "start"}).text = "1"
                    ET.SubElement(f_in, "property", {"name": "level"}).text = "1"
                    ET.SubElement(f_in, "property", {"name": "mlt_service"}).text = "brightness"
                    ET.SubElement(f_in, "property", {"name": "shotcut:filter"}).text = "fadeInBrightness"
                    ET.SubElement(f_in, "property", {"name": "alpha"}).text = f"00:00:00.000=0;{fade_in_s:.3f}=1"
                    ET.SubElement(f_in, "property", {"name": "shotcut:animIn"}).text = str(fin_frames)

                if fade_out_s > 0.0:
                    fout_frames = max(1, sec_to_frame(fade_out_s))
                    dur_s = float(ov.get("end", 0.0)) - float(ov.get("start", 0.0))
                    fout_start_s = max(0.0, dur_s - fade_out_s)
                    f_out = ET.SubElement(o_prod, "filter", {"id": f"filter_ovl_{o_idx}_fadeout"})
                    ET.SubElement(f_out, "property", {"name": "start"}).text = "1"
                    ET.SubElement(f_out, "property", {"name": "level"}).text = "1"
                    ET.SubElement(f_out, "property", {"name": "mlt_service"}).text = "brightness"
                    ET.SubElement(f_out, "property", {"name": "shotcut:filter"}).text = "fadeOutBrightness"
                    ET.SubElement(f_out, "property", {"name": "alpha"}).text = f"{fout_start_s:.3f}=1;{dur_s:.3f}=0"
                    ET.SubElement(f_out, "property", {"name": "shotcut:animOut"}).text = str(fout_frames)

                if o_start_f > current_cursor_f:
                    blank_len = o_start_f - current_cursor_f
                    ET.SubElement(pl1, "blank", {"length": str(blank_len)})
                    current_cursor_f += blank_len

                ET.SubElement(pl1, "entry", {
                    "producer": o_prod_id,
                    "in": "0",
                    "out": str(o_len_f - 1)
                })
                current_cursor_f += o_len_f
        else:
            has_overlays = False

    # Black Background producer & playlist
    black_p = ET.SubElement(root, "producer", {
        "id": "black",
        "in": "0",
        "out": str(max(100, total_timeline_frames + 100))
    })
    ET.SubElement(black_p, "property", {"name": "length"}).text = str(max(100, total_timeline_frames + 200))
    ET.SubElement(black_p, "property", {"name": "eof"}).text = "pause"
    ET.SubElement(black_p, "property", {"name": "resource"}).text = "black"
    ET.SubElement(black_p, "property", {"name": "aspect_ratio"}).text = "1"
    ET.SubElement(black_p, "property", {"name": "mlt_service"}).text = "colour"

    bg_pl = ET.SubElement(root, "playlist", {"id": "background"})
    ET.SubElement(bg_pl, "entry", {
        "producer": "black",
        "in": "0",
        "out": str(max(0, total_timeline_frames - 1))
    })

    # Main Tractor
    main_tractor = ET.SubElement(root, "tractor", {
        "id": "tractor0",
        "title": title,
        "in": "0",
        "out": str(max(0, total_timeline_frames - 1))
    })
    ET.SubElement(main_tractor, "property", {"name": "shotcut"}).text = "1"
    ET.SubElement(main_tractor, "property", {"name": "shotcut:project"}).text = "1"
    ET.SubElement(main_tractor, "property", {"name": "shotcut:scaleFactor"}).text = "1.0"
    ET.SubElement(main_tractor, "property", {"name": "shotcut:trackHeight"}).text = "50"

    ET.SubElement(main_tractor, "track", {"producer": "background"})
    ET.SubElement(main_tractor, "track", {"producer": "playlist0"})
    if has_overlays:
        ET.SubElement(main_tractor, "track", {"producer": "playlist1"})

    # Transitions between background and V1
    t_bg_a = ET.SubElement(main_tractor, "transition", {"id": "transition_bg_a"})
    ET.SubElement(t_bg_a, "property", {"name": "a_track"}).text = "0"
    ET.SubElement(t_bg_a, "property", {"name": "b_track"}).text = "1"
    ET.SubElement(t_bg_a, "property", {"name": "mlt_service"}).text = "mix"
    ET.SubElement(t_bg_a, "property", {"name": "always_active"}).text = "1"
    ET.SubElement(t_bg_a, "property", {"name": "combine"}).text = "1"

    if has_overlays:
        t_v2_v = ET.SubElement(main_tractor, "transition", {"id": "transition_v2_v"})
        ET.SubElement(t_v2_v, "property", {"name": "a_track"}).text = "1"
        ET.SubElement(t_v2_v, "property", {"name": "b_track"}).text = "2"
        ET.SubElement(t_v2_v, "property", {"name": "mlt_service"}).text = "qtblend"
        ET.SubElement(t_v2_v, "property", {"name": "always_active"}).text = "1"

    t_bg_v = ET.SubElement(main_tractor, "transition", {"id": "transition_bg_v"})
    ET.SubElement(t_bg_v, "property", {"name": "a_track"}).text = "0"
    ET.SubElement(t_bg_v, "property", {"name": "b_track"}).text = "1"
    ET.SubElement(t_bg_v, "property", {"name": "mlt_service"}).text = "qtblend"
    ET.SubElement(t_bg_v, "property", {"name": "always_active"}).text = "1"

    raw_xml = ET.tostring(root, encoding="utf-8")
    dom = minidom.parseString(raw_xml)
    pretty_xml = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    # Ensure parent directory exists
    parent_dir = os.path.dirname(os.path.abspath(out_mlt_path))
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    with open(out_mlt_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    return pretty_xml
