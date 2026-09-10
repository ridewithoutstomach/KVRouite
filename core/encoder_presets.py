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

# core/encoder_presets.py
"""
Gespeicherte Encoder-Einstellungen unter einem Namen (ab 6.14).

Bis 6.13 gab es genau EINEN Satz Encoder-Einstellungen: was im Encoder Setup
mit OK bestaetigt wurde, ueberschrieb den vorigen Stand. Wer zwischen "2K,
35 Mbit, HEVC auf der Karte" und "Full HD, x264 auf der CPU" wechseln
wollte, musste jedes Mal alle Felder von Hand setzen. Hier liegt eine
Bibliothek solcher Saetze; das Encoder Setup laedt einen davon in seine
Felder oder legt die Felder unter einem Namen ab.

Abgelegt wird in denselben QSettings wie alles andere, in der Gruppe
"encoder_presets/<Name>", mit genau den Schluesseln, die auch unter
"encoder/" stehen (FELDER). "fps_source" gehoert NICHT dazu: das ist die
Bildrate des geladenen Materials, keine Einstellung.

Ein Name ist ein QSettings-Gruppenname. Schraegstriche wuerden darin als
Untergruppe gelesen und werden deshalb ersetzt.
"""

from PySide6.QtCore import QSettings

GRUPPE = "encoder_presets"

#: Schluessel unter "encoder/", die einen Satz ausmachen, mit Vorgabewert.
FELDER = (
    ("res_w", 1920),
    ("res_h", 1080),
    ("container", "x265"),
    ("hw", "none"),
    ("crf", 20),
    ("preset", "fast"),
    ("fps", "30"),
    ("xfade", 2),
    ("bitrate_mbps", 20),
    # Seite "Audio" (ab 7.0): Tonspur an (1) oder aus (0), als Zahl statt
    # bool - QSettings liefert aus Registry und .ini Text zurueck, und
    # _lesen() bringt nur Zahlen und Text sicher auf ihren Typ. Dazu die
    # AAC-Bitrate in kbit/s.
    ("audio", 1),
    ("audio_kbps", 128),
    # Verkehr daempfen (core/verkehr): an/aus und der Daempfer in dB.
    ("traffic", 0),
    ("traffic_db", 12),
    # Tiefpass auf dem Fuellstueck in Hz, 0 = ungefiltert (verkehr.FUELL_*).
    ("traffic_fill_hz", 1000),
    # Stimmen entfernen (core/stimme): an/aus und das Modell ("mdx", "demucs").
    ("voice", 0),
    ("voice_model", "mdx"),
)


def _einstellungen():
    return QSettings("KVRouite", "KVRouite")


def name_saeubern(name) -> str:
    name = (name or "").strip().replace("/", "-").replace("\\", "-")
    return name


def namen() -> list:
    """Alle gespeicherten Namen, alphabetisch ohne Beachtung der Schreibung."""
    s = _einstellungen()
    s.beginGroup(GRUPPE)
    try:
        return sorted(s.childGroups(), key=str.casefold)
    finally:
        s.endGroup()


def _lesen(s, praefix) -> dict:
    werte = {}
    for schluessel, vorgabe in FELDER:
        wert = s.value(f"{praefix}/{schluessel}", vorgabe)
        # QSettings liefert aus der Registry und aus .ini-Dateien Text;
        # Zahlen kommen ueber den Typ der Vorgabe zurueck.
        if isinstance(vorgabe, int) and not isinstance(wert, bool):
            try:
                wert = int(wert)
            except (TypeError, ValueError):
                wert = vorgabe
        elif isinstance(vorgabe, str):
            wert = str(wert)
        werte[schluessel] = wert
    return werte


def aus_einstellungen() -> dict:
    """Der Satz, der gerade unter "encoder/" steht."""
    return _lesen(_einstellungen(), "encoder")


def laden(name) -> dict:
    """Ein gespeicherter Satz, oder None wenn es ihn nicht gibt."""
    name = name_saeubern(name)
    if not name or name not in namen():
        return None
    return _lesen(_einstellungen(), f"{GRUPPE}/{name}")


def speichern(name, werte) -> str:
    """Einen Satz unter einem Namen ablegen; ein vorhandener wird ersetzt.

    Rueckgabe: der gesaeuberte Name, unter dem er liegt.
    """
    name = name_saeubern(name)
    if not name:
        raise ValueError("A preset needs a name")
    s = _einstellungen()
    for schluessel, vorgabe in FELDER:
        s.setValue(f"{GRUPPE}/{name}/{schluessel}", werte.get(schluessel, vorgabe))
    s.sync()
    return name


def loeschen(name) -> bool:
    name = name_saeubern(name)
    if not name or name not in namen():
        return False
    s = _einstellungen()
    s.remove(f"{GRUPPE}/{name}")
    s.sync()
    return True


def gleich(a, b) -> bool:
    """Zwei Saetze gleich? Verglichen ueber die FELDER, als Text."""
    if a is None or b is None:
        return False
    return all(str(a.get(k, v)) == str(b.get(k, v)) for k, v in FELDER)


def passender_name(werte):
    """Der Name eines gespeicherten Satzes, der genau diesen Werten entspricht."""
    for name in namen():
        if gleich(laden(name), werte):
            return name
    return None
