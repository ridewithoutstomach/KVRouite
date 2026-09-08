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
Lesezeichen ("Bookmarks") auf GPX-Punkte - wiederfinden ueber Koordinaten.

Beim Synchronisieren einer Spur muss man denselben GPX-Punkt oft mehrmals
ansehen. Sein Index taugt nicht zum Merken: vor einem Schnitt ist er Zeile
1304, danach 1296. Seine Zeit auch nicht: chT, "Cut GPX to video" und "Fix
speed spike" verschieben sie. Was keine Bearbeitung anfasst, sind Lat und
Lon des Punkts - nur Loeschen nimmt ihn weg. Deshalb merkt sich ein
Lesezeichen genau das, plus einen Namen.

Diese Datei kennt kein Qt. Sie sucht den Punkt und liefert Vorgaben; Menue,
Dialog und Projektdatei liegen in views/mainwindow.py.
"""

import math

#: Bis zu diesem Abstand gilt ein anderer Punkt noch als "derselbe", wenn
#: der gemerkte Punkt selbst nicht mehr in der Spur ist (weggeschnitten).
#: Bei 1 Hz und Radtempo liegen die Punkte 3 bis 10 m auseinander; 5 m
#: findet also hoechstens den direkten Nachbarn, nie einen zwei Kurven weiter.
TOLERANZ_M = 5.0

_ERDRADIUS_M = 6371000.0


def eintrag(name, lat, lon):
    """Ein Lesezeichen, so wie es im Slot und in der Projektdatei liegt."""
    return {"name": str(name), "lat": float(lat), "lon": float(lon)}


def vorgabe_name(zeile):
    """Vorschlag fuer den Namen: die Tabellenzeile, wie sie links steht (ab 1).

    Bewusst ohne Zeit - die aendert sich mit jeder Bearbeitung, und ein
    veralteter Wert im Menue wuerde nur in die Irre fuehren.
    """
    return "Row %d" % (int(zeile) + 1)


def abstand_m(lat1, lon1, lat2, lon2):
    """Abstand zweier Punkte in Metern, Plattkarte (equirectangular).

    Reicht hier voellig: gesucht wird im Bereich weniger Meter, da ist der
    Fehler gegenueber Haversine unter einem Millimeter.
    """
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2.0))
    y = math.radians(lat2 - lat1)
    return math.sqrt(x * x + y * y) * _ERDRADIUS_M


def finde_index(gpx_data, lat, lon, toleranz_m=TOLERANZ_M):
    """Den Punkt mit diesen Koordinaten in der Spur suchen.

    Rueckgabe (index, abstand_m) oder None.

    Zuerst exakt: die Werte kommen aus derselben Spur, und auch der Weg ueber
    die Projektdatei (json) laesst einen float unveraendert. Trifft nichts,
    der naechstgelegene Punkt - aber nur innerhalb der Toleranz. Ein
    Lesezeichen, dessen Punkt weggeschnitten wurde, landet so auf dem
    Nachbarn und meldet den Abstand; liegt nichts in der Naehe, kommt None,
    und der Aufrufer sagt das, statt irgendwohin zu springen.
    """
    if not gpx_data:
        return None
    lat = float(lat)
    lon = float(lon)
    bester, bester_abstand = None, None
    for i, pt in enumerate(gpx_data):
        try:
            p_lat = float(pt["lat"])
            p_lon = float(pt["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if p_lat == lat and p_lon == lon:
            return i, 0.0
        # Grobfilter, bevor gerechnet wird: 0.001 Grad sind rund 110 m.
        if abs(p_lat - lat) > 0.001 or abs(p_lon - lon) > 0.001:
            continue
        d = abstand_m(lat, lon, p_lat, p_lon)
        if bester_abstand is None or d < bester_abstand:
            bester, bester_abstand = i, d
    if bester is not None and bester_abstand <= toleranz_m:
        return bester, bester_abstand
    return None


def sortiert(gpx_data, liste, toleranz_m=TOLERANZ_M):
    """Die Lesezeichen in Spurreihenfolge: [(eintrag, index oder None), ...].

    Gespeichert wird nur Lat/Lon, keine Zeit und keine Zeilennummer - beides
    aendert sich mit jeder Bearbeitung. Die Reihenfolge steckt trotzdem in
    der Spur: jedes Lesezeichen wird auf seinen HEUTIGEN Index aufgeloest,
    und danach wird sortiert. Ein spaeter gesetztes Lesezeichen auf einen
    frueheren Punkt steht damit vorn, und nach einem Schnitt stimmt die
    Reihenfolge weiterhin. Lesezeichen ohne Punkt in der Spur kommen ans
    Ende, in der Reihenfolge ihres Anlegens. Die Nummern 1..9 folgen dieser
    Sortierung, sie sind also keine festen Kennungen.
    """
    aufgeloest = []
    for stelle, e in enumerate(liste or []):
        treffer = finde_index(gpx_data, e["lat"], e["lon"], toleranz_m)
        idx = treffer[0] if treffer is not None else None
        aufgeloest.append((idx if idx is not None else float("inf"), stelle, e, idx))
    aufgeloest.sort(key=lambda t: (t[0], t[1]))
    return [(e, idx) for _k, _s, e, idx in aufgeloest]


def aus_projekt(roh):
    """Lesezeichen aus der Projektdatei lesen; Unbrauchbares wird uebergangen."""
    sauber = []
    for e in roh or []:
        try:
            sauber.append(eintrag(e.get("name", ""), e["lat"], e["lon"]))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return sauber
