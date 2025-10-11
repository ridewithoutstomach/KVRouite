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

import csv
import json
import os

def merge_keyframes_incremental(csv_file, json_file, label=None, offset=0.0, do_sort=True):
    """
    Liest Keyframes aus 'csv_file' (welches KEINEN Header hat, sondern direkt:
       1,0.000000,I
       1,1.001000,I
       ...
    also Reihenfolge: [key_frame, pts_time, pict_type]

    Lädt vorhandene Keyframes aus 'json_file' (falls existiert), merged beide
    und speichert das Ergebnis wieder in 'json_file'.
    """

    print(f"[DEBUG] merge_keyframes_incremental => csv_file: {csv_file}, json_file: {json_file}, label={label}, offset={offset}")

    # 1) Prüfen, ob CSV existiert
    if not os.path.isfile(csv_file):
        print(f"[WARN] CSV '{csv_file}' existiert nicht. Abbruch.")
        return

    # 2) CSV einmal öffnen, um Zeilen zu zählen (optional, nur für Debug)
    with open(csv_file, 'r', encoding='utf-8') as f:
        all_lines = f.read().splitlines()
    print(f"[DEBUG] CSV '{csv_file}' => enthält {len(all_lines)} Gesamtzeilen (ohne Header).")

    # 3) Jetzt nochmal öffnen für DictReader, mit festen fieldnames
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, fieldnames=["key_frame", "pts_time", "pict_type"])
        csv_keyframes = []
        for row in reader:
            # row = {"key_frame": "1", "pts_time": "0.000000", "pict_type": "I"}
            try:
                # KEYFRAME (Spalte 1)
                kf_str = row["key_frame"].strip()

                # PTS_TIME (Spalte 2)
                pts_str = row["pts_time"].strip()
                pts_val = float(pts_str)

                # PICT_TYPE (Spalte 3)
                pict_type = row["pict_type"].strip()

            except (KeyError, AttributeError, ValueError) as e:
                print(f"[WARN] Zeile ungültig: {row} => {e}")
                continue

            # Dictionary erstellen
            entry = {
                "pts_time":    f"{pts_val:.6f}",   # z.B. "0.000000"
                "pict_type":   pict_type,          # z.B. "I"
                "key_frame":   kf_str,            # z.B. "1"
                "global_time": f"{pts_val + offset:.6f}"
            }
            if label:
                entry["video"] = label

            csv_keyframes.append(entry)

    print(f"[DEBUG] CSV '{csv_file}' => {len(csv_keyframes)} gültige Keyframes eingelesen.")

    # 4) Existierendes JSON laden
    existing_data = []
    if os.path.isfile(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                if not isinstance(existing_data, list):
                    print(f"[WARN] '{json_file}' enthielt kein Array. Überschreibe es.")
                    existing_data = []
        except Exception as e:
            print(f"[WARN] Konnte '{json_file}' nicht laden ({e}). Starte mit leerer Liste.")
            existing_data = []

    print(f"[DEBUG] Im JSON '{json_file}' lagen bereits {len(existing_data)} Keyframes.")

    # 5) Merge (Liste zusammenfügen)
    merged_data = existing_data + csv_keyframes

    # 6) Sortieren
    if do_sort:
        def safe_float(val):
            try:
                return float(val)
            except:
                return 0.0
        merged_data.sort(key=lambda x: safe_float(x.get("global_time", "0.0")))

    # 7) Speichern
    try:
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Konnte '{json_file}' nicht schreiben: {e}")
        return

    print(f"[DEBUG] Merge fertig. Neu enthalten: {len(merged_data)} Keyframes in '{json_file}'.")
