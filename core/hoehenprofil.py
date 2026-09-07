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
Hoehenprofil zwischen zwei verlaesslichen Punkten aus Stuetzpunkten aufbauen.

Das Problem: In einer halboffenen Galerie oder auf einem Viadukt zeichnet
auch ein barometrischer Radcomputer Unsinn auf (Wahoo am Stilfserjoch,
06.09.2026: 8 m bergab, wo die Strasse steigt). Ein Gelaendemodell hilft
dort nicht, es misst das Dach oder den Hang unter der Bruecke. Was bleibt:
die Hoehe an den Enden stimmt, die Strecke stimmt (nach "Directions"), und
der Fahrer sieht im Video, wo es wie steil ist.

Hier steht nur die Rechnung, ohne Qt: aus Stuetzpunkten (Strecke, Hoehe)
wird die Hoehe an jedem Punkt der Spur. Zwischen den Stuetzpunkten gerade,
an jedem inneren Stuetzpunkt wird der Knick durch eine Parabel ersetzt -
die Ausrundung, mit der Strassen gebaut werden. Ihre Laenge waehlt der
Nutzer: lang fuer weiche Uebergaenge, kurz fuer scharfe Wechsel.
"""

import math


def strecke_2d(g, b, e):
    """Kumulierte Strecke in Metern ab Punkt b, fuer die Punkte b..e.

    Nur aus Lage (Haversine), NICHT aus delta_m der Spur: das ist 3D und
    traegt genau die falschen Hoehen mit, die hier ersetzt werden sollen.
    """
    R = 6371000.0
    s = [0.0]
    for i in range(b + 1, e + 1):
        la1, lo1 = math.radians(g[i - 1]["lat"]), math.radians(g[i - 1]["lon"])
        la2, lo2 = math.radians(g[i]["lat"]), math.radians(g[i]["lon"])
        x = (math.sin((la2 - la1) / 2) ** 2
             + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
        s.append(s[-1] + 2 * R * math.atan2(math.sqrt(x), math.sqrt(1 - x)))
    return s


def steigungen(stuetzen):
    """Steigung in Prozent je Abschnitt zwischen den Stuetzpunkten.

    Ein Stuetzpunkt ist (s, h) oder (s, h, ausrundung_m)."""
    out = []
    for a, b in zip(stuetzen, stuetzen[1:]):
        d = b[0] - a[0]
        out.append((b[1] - a[1]) / d * 100.0 if d > 0 else 0.0)
    return out


def _ausrundungen(stuetzen, laenge):
    """Ausrundungslaenge je Stuetzpunkt: an den Enden 0, innen die eigene
    Laenge des Punkts (drittes Element), sonst die Vorgabe 'laenge'; begrenzt
    auf den kuerzeren Nachbarabschnitt. So reicht jede Ausrundung hoechstens
    bis zur Mitte eines Abschnitts, zwei Ausrundungen ueberlappen sich nie.
    Je Punkt einstellbar, damit ein Wechsel von 9 auf 12 % schnell kommen
    kann und der naechste langsam."""
    n = len(stuetzen)
    out = [0.0] * n
    for k in range(1, n - 1):
        links = stuetzen[k][0] - stuetzen[k - 1][0]
        rechts = stuetzen[k + 1][0] - stuetzen[k][0]
        wunsch = stuetzen[k][2] if len(stuetzen[k]) > 2 else laenge
        out[k] = max(0.0, min(wunsch, links, rechts))
    return out


def hoehe_bei(s, stuetzen, ausrundung=0.0, _l=None):
    """Hoehe an Strecke s. Zwischen Stuetzpunkten gerade; im Bereich einer
    Ausrundung die Parabel, die beide Geraden beruehrt."""
    n = len(stuetzen)
    if n == 0:
        return 0.0
    if n == 1 or s <= stuetzen[0][0]:
        return stuetzen[0][1]
    if s >= stuetzen[-1][0]:
        return stuetzen[-1][1]
    if _l is None:
        _l = _ausrundungen(stuetzen, ausrundung)
    st = steigungen(stuetzen)
    # Abschnitt i: stuetzen[i] .. stuetzen[i+1]
    i = 0
    while i < n - 2 and s > stuetzen[i + 1][0]:
        i += 1
    s0, h0 = stuetzen[i][0], stuetzen[i][1]
    s1, h1 = stuetzen[i + 1][0], stuetzen[i + 1][1]
    g0 = st[i] / 100.0
    # Ausrundung am Anfang des Abschnitts (Scheitel i)?
    if i > 0 and s - s0 < _l[i] / 2:
        return _parabel(s - s0, h0, st[i - 1] / 100.0, g0, _l[i])
    # Ausrundung am Ende des Abschnitts (Scheitel i+1)?
    if i + 1 < n - 1 and s1 - s < _l[i + 1] / 2:
        return _parabel(s - s1, h1, g0, st[i + 1] / 100.0, _l[i + 1])
    return h0 + g0 * (s - s0)


def _parabel(x, h_scheitel, g1, g2, laenge):
    """Ausrundung der Laenge 'laenge', mittig auf dem Scheitel: x ist der
    Abstand zum Scheitel (negativ davor). Trifft an beiden Enden Hoehe und
    Steigung der Geraden."""
    return h_scheitel + g1 * x + (g2 - g1) / (2.0 * laenge) * (x + laenge / 2.0) ** 2


def profil(strecke, stuetzen, ausrundung=0.0):
    """Hoehe fuer jede Stelle in 'strecke' (aufsteigend, ab 0)."""
    l = _ausrundungen(stuetzen, ausrundung)
    return [hoehe_bei(s, stuetzen, ausrundung, l) for s in strecke]
