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
"""Die Lizenztexte der Voice-Remover-Pakete aus der venv einsammeln.

    python tools/lizenzen_sammeln.py            # schreibt nach third-party-licenses/voice/
    python tools/lizenzen_sammeln.py --pruefen  # nur nachsehen, nichts schreiben

Der Voice Remover (core/stimme) bringt rund fuenfzig Python-Pakete mit, die
alle einen Copyright-Hinweis und ihren Lizenztext im Paket verlangen (MIT,
BSD, Apache, ISC, MPL, LGPL). Die Texte liegen in der venv in den
dist-info-Ordnern; dieses Werkzeug kopiert je Paket den Text nach
third-party-licenses/voice/LICENSE.<paket> und schreibt daneben
INVENTAR.txt mit Version und Lizenzkennung, wie das Paket sie selbst
angibt. Der Packer liefert third-party-licenses/ komplett mit aus.

PAKETE ist die Liste dessen, was PyInstaller fuer den Voice Remover
tatsaechlich einpackt (abgelesen am 10.09.2026 aus dem Analysis-Protokoll
eines Probebaus), nicht das, was pip installiert hat - die Differenz sind
Werkzeuge wie pip, setuptools oder Cython, die im Build nichts tun.

Fehlt ein Paket in der venv oder liegt ihm kein Lizenztext bei, wird das
gemeldet und der Rueckgabewert ist 1: dann fehlt ein Text, den wir liefern
muessten.
"""

import importlib.metadata
import os
import sys

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIEL = os.path.join(BASIS, "third-party-licenses", "voice")

#: Verteilungsname (pip) je Paket im Build.
PAKETE = (
    "audio-separator", "torch", "torchvision", "onnxruntime", "onnx-weekly",
    "onnx2torch-py313", "numpy", "scipy", "scikit-learn", "librosa",
    "numba", "llvmlite", "soundfile", "soxr", "resampy", "samplerate",
    "audioread", "pydub", "julius", "einops", "rotary-embedding-torch",
    "beartype", "ml_collections", "ml_dtypes", "sympy", "mpmath",
    "networkx", "Jinja2", "MarkupSafe", "filelock", "fsspec",
    "typing_extensions", "tqdm", "requests", "urllib3", "certifi", "idna",
    "charset-normalizer", "PyYAML", "lazy_loader", "decorator", "joblib",
    "pooch", "platformdirs", "threadpoolctl", "protobuf", "flatbuffers",
    "cloudpickle", "msgpack", "absl-py", "colorama", "six", "pycparser",
    "cffi", "narwhals", "packaging", "setuptools", "audioop-lts", "Cython",
)

#: Pakete, die nur in manchen venvs liegen: audioop-lts nur ab Python 3.13
#: (requirements.txt), Cython nur, wenn etwas es hereingezogen hat. Fehlen
#: sie, ist das kein Fehler - sie sind dann auch nicht im Build.
OPTIONAL = {"audioop-lts", "Cython"}

#: Binaerbibliotheken, die in einem Wheel stecken, aber ihren Lizenztext
#: NICHT im dist-info fuehren: (Name fuer die Ausgabedatei, Paket, Pfad
#: relativ zu site-packages). libsndfile ist LGPL-2.1 - Text ist Pflicht,
#: und die DLL liegt austauschbar als eigene Datei im Build.
BINAERE = (
    ("libsndfile", "soundfile", os.path.join("_soundfile_data", "COPYING")),
    # onnxruntime fuehrt seine Texte im Paketordner, nicht im dist-info.
    ("onnxruntime", "onnxruntime", os.path.join("onnxruntime", "LICENSE")),
    ("onnxruntime-third-party", "onnxruntime",
     os.path.join("onnxruntime", "ThirdPartyNotices.txt")),
)

#: Pakete, deren Wheel gar keinen Lizenztext enthaelt. Sie erklaeren ihre
#: Lizenz nur in den Metadaten; der Text kommt dann aus dem Standardtext im
#: Ordner darueber, mit Urheber und Version davor.
STANDARD = {
    "flatbuffers": "LICENSE.Apache-2.0",
    "Cython": "LICENSE.Apache-2.0",
}

LIZENZ_NAMEN = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst",
                "COPYING", "COPYING.txt", "LICENCE", "LICENCE.txt")


def _metadatum(dist, schluessel):
    wert = dist.metadata.get(schluessel)
    return wert.strip() if wert else ""


def _lizenztexte(dist):
    """Alle Lizenzdateien der Verteilung: [(Name, Text)]."""
    texte = []
    for datei in dist.files or []:
        name = os.path.basename(str(datei))
        teile = str(datei).replace("\\", "/").split("/")
        if len(teile) < 2 or not teile[0].endswith(".dist-info"):
            continue
        ist_lizenz = (name.upper().startswith(LIZENZ_NAMEN)
                      or name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "AUTHORS"))
                      or "licenses" in teile)
        if not ist_lizenz or name.endswith((".py", ".pyc")):
            continue
        # locate() gibt den absoluten Pfad; dist.read_text() erwartet dagegen
        # einen Pfad RELATIV zum dist-info-Ordner und liefert fuer die
        # Eintraege aus dist.files nichts.
        try:
            with open(str(datei.locate()), "r", encoding="utf-8",
                      errors="replace") as f:
                inhalt = f.read()
        except OSError:
            inhalt = None
        if inhalt and inhalt.strip():
            texte.append((str(datei).replace("\\", "/"), inhalt))
    return texte


def main():
    nur_pruefen = "--pruefen" in sys.argv
    fehler = []
    zeilen = []
    for name in PAKETE:
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            if name in OPTIONAL:
                print(f"{name:<26} {'':<22} nicht installiert - nicht im Build")
                alt = os.path.join(ZIEL, "LICENSE." + name)
                if not nur_pruefen and os.path.isfile(alt):
                    os.remove(alt)      # kein veralteter Text fuer ein Paket, das fehlt
                continue
            fehler.append(f"{name}: nicht installiert")
            continue
        version = dist.version
        lizenz = (_metadatum(dist, "License-Expression")
                  or _metadatum(dist, "License") or "")
        if not lizenz or len(lizenz) > 120:
            klassen = [z for z in dist.metadata.get_all("Classifier") or []
                       if z.startswith("License ::")]
            lizenz = "; ".join(k.split("::")[-1].strip() for k in klassen) or lizenz[:120]
        texte = _lizenztexte(dist)
        if not texte and name in STANDARD:
            standard = os.path.join(os.path.dirname(ZIEL), STANDARD[name])
            try:
                with open(standard, "r", encoding="utf-8") as f:
                    urheber = _metadatum(dist, "Author") or name
                    texte = [(STANDARD[name],
                              f"Copyright: {urheber} (per package metadata)\n\n"
                              + f.read())]
            except OSError:
                pass
        if not texte and any(b[1] == name for b in BINAERE):
            pass            # kommt unten aus dem Paketordner
        elif not texte:
            fehler.append(f"{name} {version}: kein Lizenztext im Paket")
        zeilen.append(f"{name:<26} {version:<22} {lizenz}")
        print(f"{name:<26} {version:<22} {len(texte):2d} Text(e)  {lizenz}")
        if nur_pruefen or not texte:
            continue
        os.makedirs(ZIEL, exist_ok=True)
        ziel = os.path.join(ZIEL, "LICENSE." + name)
        with open(ziel, "w", encoding="utf-8") as f:
            f.write(f"{name} {version}\nLicense as declared by the package: {lizenz}\n")
            for pfad, inhalt in texte:
                f.write("\n" + "=" * 78 + "\n" + pfad + "\n" + "=" * 78 + "\n\n")
                f.write(inhalt.rstrip() + "\n")

    for name, paket, relativ in BINAERE:
        try:
            dist = importlib.metadata.distribution(paket)
            wurzel = str(dist.locate_file(""))
        except importlib.metadata.PackageNotFoundError:
            fehler.append(f"{name}: {paket} nicht installiert")
            continue
        quelle = os.path.join(wurzel, relativ)
        if not os.path.isfile(quelle):
            fehler.append(f"{name}: {quelle} fehlt")
            continue
        zeilen.append(f"{name:<26} {'(in ' + paket + ')':<22} see LICENSE.{name}")
        print(f"{name:<26} {'':<22}  1 Text     aus {paket}")
        if not nur_pruefen:
            os.makedirs(ZIEL, exist_ok=True)
            with open(quelle, "r", encoding="utf-8", errors="replace") as q, \
                    open(os.path.join(ZIEL, "LICENSE." + name), "w",
                         encoding="utf-8") as f:
                f.write(f"{name} - shipped inside the {paket} package as "
                        f"{relativ}\n\n")
                f.write(q.read().rstrip() + "\n")

    if not nur_pruefen and zeilen:
        with open(os.path.join(ZIEL, "INVENTAR.txt"), "w", encoding="utf-8") as f:
            f.write("KVRouite - Python packages of the voice remover, as shipped\n")
            f.write("=" * 78 + "\n\n")
            f.write("Collected by tools/lizenzen_sammeln.py from the build venv. The\n")
            f.write("license given is the one the package declares in its own metadata.\n")
            f.write("The full texts are the LICENSE.<package> files next to this one.\n\n")
            f.write(f"{'package':<26} {'version':<22} license\n")
            f.write("-" * 78 + "\n")
            f.write("\n".join(zeilen) + "\n")
        print(f"\n{len(zeilen)} Pakete nach {ZIEL}")
    for f in fehler:
        print("FEHLER:", f)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
