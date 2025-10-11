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

#!/usr/bin/env python3
# tools/extract_keyframes.py

import argparse
import subprocess
import csv
import os
import sys

def extract_keyframes(ffprobe_path, input_file):
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time,pict_type,key_frame",
        "-of", "csv=p=0",
        input_file
    ]
    try:
        completed_process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    except FileNotFoundError:
        print(f"Fehler: ffprobe wurde unter '{ffprobe_path}' nicht gefunden.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Fehler bei der ffprobe-Ausführung:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)

    lines = completed_process.stdout.strip().split('\n')
    keyframes = []
    for line in lines:
        parts = line.split(',')
        if len(parts) == 3:
            d = {
                "pts_time": parts[0],
                "pict_type": parts[1],
                "key_frame": parts[2]
            }
            keyframes.append(d)
    return keyframes

def save_keyframes_to_csv(keyframes, output_file):
    with open(output_file, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["pts_time", "pict_type", "key_frame"])
        writer.writeheader()
        for kf in keyframes:
            writer.writerow(kf)

def main():
    parser = argparse.ArgumentParser(description="Extrahiert Keyframes aus einem MP4-Video.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Fehler: Eingabedatei '{args.input}' nicht gefunden.")
        sys.exit(1)

    keyframes = extract_keyframes(args.ffprobe, args.input)
    if not keyframes:
        print("Keine Keyframes gefunden oder Fehler bei ffprobe.")
        sys.exit(1)

    save_keyframes_to_csv(keyframes, args.output)
    print(f"Keyframes erfolgreich in '{args.output}' gespeichert.")

if __name__ == "__main__":
    main()
