#!/usr/bin/env python3
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
"""Die Modelle des Voice Removers holen - EINMAL, auf dem Bau-Rechner.

    python tools/modelle_holen.py

Legt voice_models/ im Projektverzeichnis an und laedt dorthin, was
core/stimme.MODELLE nennt: die MDX-Datei aus dem Modell-Release von UVR
(GitHub) und htdemucs von Meta, dazu die drei Metadaten-Dateien, die
audio-separator zum Laden braucht. Zusammen rund 144 MB. Was schon da ist,
wird nicht noch einmal geholt.

Der Packer (build_with_pyinstaller.py, build_macos.py) nimmt den Ordner mit
in die App; die App selbst laedt nichts nach. Der Ordner steht in
.gitignore - ins Repository gehoeren die Dateien nicht.

Das Holen erledigt audio-separator selbst (download_model_files), damit
Quelle und Dateinamen genau die sind, die es spaeter beim Laden erwartet.
"""

import os
import sys

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASIS)

from core import stimme  # noqa: E402


def main():
    ordner = os.path.join(BASIS, "voice_models")
    os.makedirs(ordner, exist_ok=True)
    try:
        from audio_separator.separator import Separator
    except ImportError as exc:
        print("FEHLT: audio-separator ist nicht installiert "
              "(pip install -r requirements.txt):", exc)
        return 2

    sep = Separator(model_file_dir=ordner)
    for _kennung, (datei, name) in stimme.MODELLE.items():
        print(f"== {name} ({datei})")
        # download_model_and_data holt Modell UND Metadaten (mdx_model_data,
        # vr_model_data, download_checks), ueberspringt, was da ist - bei
        # Demucs auch die .th-Datei hinter der .yaml.
        sep.download_model_and_data(datei)

    fehlt = []
    for datei in stimme.MODELL_METADATEN:
        if not os.path.isfile(os.path.join(ordner, datei)):
            fehlt.append(datei)
    ok, grund = stimme.verfuegbar()
    if fehlt or not ok:
        print("FEHLER:", grund or ("Metadaten fehlen: " + ", ".join(fehlt)))
        return 1

    gesamt = sum(os.path.getsize(os.path.join(ordner, f))
                 for f in os.listdir(ordner))
    print(f"\nvoice_models/: {len(os.listdir(ordner))} Dateien, "
          f"{gesamt / 1e6:.0f} MB")
    for f in sorted(os.listdir(ordner)):
        print(f"   {f:<32} {os.path.getsize(os.path.join(ordner, f)) / 1e6:7.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
