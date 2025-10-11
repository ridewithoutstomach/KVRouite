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


# core/hardware_detect.py
import subprocess

_cached_encoders = None  # Global Cache
_cached_already_printed_debug = False

def detect_available_hw_encoders(ffmpeg_path="ffmpeg"):
    """
    Ruft ffmpeg -encoders auf, um GPU-Encoder herauszufinden.
    Gibt ein set(...) zurück, z.B. {"CPU","nvidia_h264","nvidia_hevc","amd_h264","amd_hevc",...}
    
    "CPU" steht hier für den reinen Software-Encode (vormals "none").
    """
    import subprocess
    global _cached_encoders
    global _cached_already_printed_debug

    if _cached_encoders is not None:
        return _cached_encoders

    encoders_found = set()
    encoders_found.add("CPU")  # CPU = reine Software

    try:
        cmd = [ffmpeg_path, "-hide_banner", "-encoders"]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, encoding="utf-8")
    except Exception as e:
        print("[WARN] detect_available_hw_encoders failed:", e)
        print("[DEBUG] => No GPU encoders => returning {'CPU'}")
        _cached_encoders = {"CPU"}
        return _cached_encoders

    if "h264_nvenc" in output:
        encoders_found.add("nvidia_h264")
    if "hevc_nvenc" in output:
        encoders_found.add("nvidia_hevc")

    if "h264_amf" in output:
        encoders_found.add("amd_h264")
    if "hevc_amf" in output:
        encoders_found.add("amd_hevc")

    if "h264_qsv" in output:
        encoders_found.add("intel_h264")
    if "hevc_qsv" in output:
        encoders_found.add("intel_hevc")

    print("[DEBUG] => GPU encoders found:", encoders_found)
    _cached_encoders = encoders_found
    return _cached_encoders
