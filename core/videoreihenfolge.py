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
Reihenfolge mehrerer Videos beim Import: nach Aufnahmezeit, GoPro-Kapitel
in ihrer Nummernfolge.

Der Dateidialog liefert die Dateien in Klickreihenfolge, und nach Namen
sortiert stehen GoPro-Kapitel falsch: GX010037, GX010038, GX010039,
GX010042, GX020039 ... - Kapitel 2 von 0039 kaeme nach Kapitel 1 von 0042.

Gemessen am 07.09.2026 an den sieben Stelvio-Dateien:
- Die Aufnahmezeit steht im Container ("mvhd", wie ffprobe creation_time)
  und ist in 1 ms gelesen. Alle Kapitel EINER Aufnahme tragen dieselbe
  Zeit (GX010039/020039/030039: 06:34:59), Kapitel 2 von 0042 sogar 2 s
  VOR Kapitel 1. Die Zeit ordnet also Aufnahmen, nicht Kapitel.
- Die Aenderungszeit der Datei ist die Kopierzeit, unbrauchbar. Die
  Erstellzeit passte zur Aufnahme - nur als Ersatz, wenn der Container
  nichts sagt, denn sie ueberlebt nicht jedes Kopieren.

Schluessel je Datei: (Zeit der Aufnahme = fruehste Zeit ihrer Kapitel,
Dateinummer, Kapitelnummer, Name). GoPro-Namen: GX/GH/GP + zwei Stellen
Kapitel + vier Stellen Nummer, oder GOPR + Nummer (Kapitel 1, Rest GPcc).
"""

import os
import re
from datetime import datetime, timezone

_GOPRO = re.compile(r"^(?:G[XHP])(\d{2})(\d{4})$", re.I)
_GOPRO_ERSTES = re.compile(r"^GOPR(\d{4})$", re.I)


def gopro_nummer(pfad):
    """(Dateinummer, Kapitel) aus einem GoPro-Namen, sonst None."""
    stamm = os.path.splitext(os.path.basename(pfad))[0]
    m = _GOPRO.match(stamm)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = _GOPRO_ERSTES.match(stamm)
    if m:
        return int(m.group(1)), 1
    return None


def aufnahmezeit(pfad):
    """Zeit als UTC-datetime: aus dem Container, sonst Erstellzeit der Datei,
    sonst None. (quelle, zeit) fuer die Konsole."""
    try:
        from core.mp4_keyframes import creation_time_from_container
        t = creation_time_from_container(pfad)
        if t is not None:
            return "container", t
    except Exception:
        pass
    try:
        st = os.stat(pfad)
        roh = getattr(st, "st_birthtime", None) or st.st_ctime
        return "datei", datetime.fromtimestamp(roh, tz=timezone.utc)
    except OSError:
        return "keine", None


def sortieren(pfade, zeit=aufnahmezeit):
    """Die Pfade in Aufnahmereihenfolge. 'zeit' ist austauschbar (Test)."""
    eintraege = []
    for p in pfade:
        quelle, t = zeit(p)
        eintraege.append((p, quelle, t, gopro_nummer(p)))
    # Aufnahmezeit je GoPro-Nummer: die frueheste ihrer Kapitel
    gruppe = {}
    for p, _, t, g in eintraege:
        if g is not None and t is not None:
            nr = g[0]
            gruppe[nr] = min(gruppe[nr], t) if nr in gruppe else t
    fern = datetime.max.replace(tzinfo=timezone.utc)

    def schluessel(e):
        p, _, t, g = e
        if g is not None:
            nr, kapitel = g
            return (gruppe.get(nr, t if t is not None else fern), nr, kapitel, os.path.basename(p).lower())
        return (t if t is not None else fern, 0, 0, os.path.basename(p).lower())

    eintraege.sort(key=schluessel)
    return [e[0] for e in eintraege]


def erklaeren(pfade, zeit=aufnahmezeit):
    """Zeilen fuer die Konsole: Name, Zeit und Quelle in der gewaehlten Folge."""
    zeilen = []
    for p in sortieren(pfade, zeit):
        quelle, t = zeit(p)
        wann = t.strftime("%Y-%m-%d %H:%M:%S") if t else "-"
        zeilen.append(f"{os.path.basename(p)}  {wann} ({quelle})")
    return zeilen
