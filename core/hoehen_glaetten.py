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
Hoehen glaetten (Smooth): Steigung je Punkt mitteln und ihre Aenderung
deckeln, dann die Hoehen wieder aufbauen. Fuer einen Bereich B..E oder die
ganze Spur.

Bis 6.11 nahm Smooth immer die ganze Spur, sagte das nicht, und baute die
Hoehen ab Punkt 0 wieder auf - der Endpunkt wanderte, und jeder weitere
Durchlauf flachte die Spur weiter ab, ohne dass jemand es merkte. Jetzt:
- Bereich, wenn markiert; die Nachbarn ausserhalb gehen als Umfeld in die
  Mittelung ein, damit an den Raendern kein Knick entsteht.
- Der Endpunkt bleibt auf seiner Hoehe: was beim Wiederaufbau uebrig
  bleibt, wird gleichmaessig ueber die Strecke verteilt. Gilt auch fuer die
  ganze Spur - die Enden sind echte Daten.
- Der Stand nach dem Glaetten wird gemerkt (Stand), damit ein zweiter
  Durchlauf gewarnt werden kann und geaenderte Zeilen gefunden werden.

Ohne Qt, damit es sich ohne Fenster nachrechnen laesst.
"""

import math
from datetime import datetime


def _dist2d(g, i):
    """Strecke des Segments i-1 -> i in Metern, aus der Lage (2D)."""
    R = 6371000.0
    la1, lo1 = math.radians(g[i - 1]["lat"]), math.radians(g[i - 1]["lon"])
    la2, lo2 = math.radians(g[i]["lat"]), math.radians(g[i]["lon"])
    x = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def anstieg(g, b=0, e=None):
    """Summe der positiven Hoehenschritte ueber b+1..e (Hoehenmeter)."""
    if e is None:
        e = len(g) - 1
    summe = 0.0
    for i in range(b + 1, e + 1):
        d = float(g[i].get("ele", 0.0)) - float(g[i - 1].get("ele", 0.0))
        if d > 0:
            summe += d
    return summe


def glaetten(g, b, e, box, flatten):
    """Neue Hoehen fuer die Punkte b..e (Liste der Laenge e-b+1).

    box:     Steigung je Punkt wird ueber +-box Punkte gemittelt
    flatten: hoechste erlaubte Aenderung der Steigung von Punkt zu Punkt (%)
    Die Steigungen kommen aus dem Bereich plus 'box' Punkten Umfeld auf
    beiden Seiten. Hoehe von b und e bleiben.
    """
    n = len(g)
    if n < 2 or e <= b:
        return [float(g[i].get("ele", 0.0)) for i in range(b, e + 1)]
    box = max(0, int(box))
    lo = max(1, b - box)          # erstes Segment (i-1 -> i), das mitgemittelt wird
    hi = min(n - 1, e + box)

    dist = {i: _dist2d(g, i) for i in range(lo, hi + 1)}
    roh = {}
    for i in range(lo, hi + 1):
        d = dist[i]
        roh[i] = ((float(g[i]["ele"]) - float(g[i - 1]["ele"])) / d * 100.0) if d > 0.01 else 0.0

    # Box-Mittel fuer die Segmente b..e (Segment b nur als Anschluss)
    mittel = {}
    for i in range(max(lo, b), e + 1):
        a, z = max(lo, i - box), min(hi, i + box)
        mittel[i] = sum(roh[j] for j in range(a, z + 1)) / (z - a + 1)

    # Flatten: Aenderung von Segment zu Segment deckeln, Anschluss am
    # Segment vor b, damit der Rand nicht springt
    geglaettet = {}
    vorher = mittel.get(b, roh.get(b))
    for i in range(b + 1, e + 1):
        s = mittel[i]
        if vorher is not None and abs(s - vorher) > flatten:
            s = vorher + (flatten if s > vorher else -flatten)
        geglaettet[i] = s
        vorher = s

    # Wiederaufbau ab b, dann E festhalten: Rest ueber die Strecke verteilen
    h = [float(g[b].get("ele", 0.0))]
    strecke = [0.0]
    for i in range(b + 1, e + 1):
        h.append(h[-1] + dist[i] * geglaettet[i] / 100.0)
        strecke.append(strecke[-1] + dist[i])
    rest = float(g[e].get("ele", 0.0)) - h[-1]
    S = strecke[-1]
    if S > 0:
        h = [hk + rest * sk / S for hk, sk in zip(h, strecke)]
    h[-1] = float(g[e].get("ele", 0.0))
    return h


class Stand:
    """Was nach dem letzten Smooth festgehalten wird.

    'hoehen' ist die Hoehe jedes Punkts danach - nur im Speicher; in die
    Projektdatei geht nur die Zusammenfassung (als_dict), 17.000 Hoehen
    waeren dort 140 kB fuer wenig Nutzen.
    """

    def __init__(self, hoehen, box, flatten, b, e, anstieg_vorher, anstieg_nachher, zeit=None):
        self.hoehen = hoehen
        self.box = int(box)
        self.flatten = float(flatten)
        self.b, self.e = int(b), int(e)
        self.anstieg_vorher = float(anstieg_vorher)
        self.anstieg_nachher = float(anstieg_nachher)
        self.zeit = zeit or datetime.now()

    def als_dict(self):
        return {"box": self.box, "flatten": self.flatten, "b": self.b, "e": self.e,
                "anstieg_vorher": self.anstieg_vorher, "anstieg_nachher": self.anstieg_nachher,
                "zeit": self.zeit.isoformat(timespec="seconds")}

    @classmethod
    def aus_dict(cls, d):
        if not d:
            return None
        try:
            zeit = datetime.fromisoformat(d.get("zeit"))
        except Exception:
            zeit = None
        try:
            return cls(None, d["box"], d["flatten"], d["b"], d["e"],
                       d["anstieg_vorher"], d["anstieg_nachher"], zeit)
        except (KeyError, TypeError, ValueError):
            return None

    def wann(self):
        if self.zeit.date() == datetime.now().date():
            return self.zeit.strftime("%H:%M")
        return self.zeit.strftime("%Y-%m-%d %H:%M")


def geaenderte_zeilen(stand, g, toleranz=0.001):
    """Vergleich der Hoehen mit dem Stand nach dem letzten Smooth.

    Rueckgabe (art, erste, letzte):
      ("unbekannt", None, None)  kein Stand mit Hoehen, oder andere Punktzahl
      ("gleich", None, None)     keine Hoehe hat sich geaendert
      ("geaendert", a, z)        Zeilen a..z sind anders (erste und letzte)
    """
    if stand is None or stand.hoehen is None or len(stand.hoehen) != len(g):
        return ("unbekannt", None, None)
    anders = [i for i, (alt, p) in enumerate(zip(stand.hoehen, g))
              if abs(float(p.get("ele", 0.0)) - alt) > toleranz]
    if not anders:
        return ("gleich", None, None)
    return ("geaendert", anders[0], anders[-1])
