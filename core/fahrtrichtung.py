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
360-Blick folgt der Fahrtrichtung (Stufe 3 des 360-Editor-Plans).

Aus der GPX-Spur ist zu jedem Punkt bekannt, wohin gefahren wird: der Kurs
(Peilung zum naechsten Punkt, 0 = Nord, im Uhrzeigersinn). Daraus dreht
die App die Kamera von selbst nach vorn - in jeder Kurve, ohne Marken.

Der Zusammenhang mit dem Blickwinkel des Shaders (core/view360.py,
positives yaw schaut nach rechts): zeigt die Bildmitte des Equirect-Videos
auf eine feste Himmelsrichtung H0, dann schaut yaw = kurs - H0 nach vorn.
H0 kennt niemand, deshalb die Kalibrierung: an EINER Stelle dreht der
Nutzer den Blick von Hand nach vorn, und die App merkt sich

    offset = yaw_hand - kurs(t)          (= -H0)

fuer dieses Video. Danach gilt yaw(t) = kurs(t) + offset.

Zeigt die Bildmitte NICHT auf eine feste Richtung, sondern dreht sie mit
der Kamera mit (Export ohne Richtungssperre, der Normalfall), dann ist
"vorn" schon vorn, und das Folgen dreht den Blick weg. Dann schaltet man
es ab.

Was hier steht, ist reine Rechnung ohne Qt und ohne GStreamer:

  kurse()       Kurs je GPX-Punkt in Radiant, mit Umgang fuer Punkte ohne
                Bewegung (doppelte Zeitstempel, Stillstand) und mit
                kreisfoermiger Glaettung - ein gewoehnliches gleitendes
                Mittel springt am Nordpunkt.
  folgemarken() die dichte Liste von Blickmarken, die Vorschau und Export
                dann wie handgesetzte Marken abspielen (core/blickverlauf).
                Vorschau und Export brauchen so kein GPX.
"""

import math

from core.blickverlauf import Blickmarke, WEICH

#: Unter diesem Abstand zum naechsten Punkt gilt "keine Bewegung" - ein Kurs
#: aus GPS-Rauschen im Stand ist Unsinn. 1 m ist gut ein Zehntel dessen, was
#: ein Rad je Sekunde zuruecklegt, und mehr als das Rauschen im Stand.
MINDEST_WEG_M = 1.0

#: Vorgaben, die im Dialog "360 Setup" einstellbar sind.
#:
#: Die Glaettung ist in SEKUNDEN, nicht in Punkten: die GPX aus der
#: 360-Kamera vom 12.09.2026 hat 10 Punkte je Sekunde (2199 von 2445
#: Punkten teilen den Zeitstempel mit dem Vorgaenger), eine GoPro- oder
#: Radcomputer-GPX einen.
#: "5 Punkte" waeren dort 0,5 s und hier 5 s. fenster_punkte() rechnet um.
GLAETTUNG_VORGABE_S = 2.0      # je Seite
VORAUSSCHAU_VORGABE_S = 2.0    # der Fahrer schaut dahin, wo er gleich ist
SCHRITT_S = 0.2                # Abstand der erzeugten Marken


def punkte_je_sekunde(gpx_data):
    """Mittlere Punktdichte der Spur; 1.0, wenn sie sich nicht bestimmen laesst."""
    zeiten = [p.get("time") for p in gpx_data if p.get("time")]
    if len(zeiten) < 2:
        return 1.0
    dauer = (zeiten[-1] - zeiten[0]).total_seconds()
    if dauer <= 0:
        return 1.0
    return max(0.1, (len(zeiten) - 1) / dauer)


def fenster_punkte(gpx_data, sekunden):
    """Glaettung in Sekunden -> Punkte je Seite fuer kurse()."""
    return max(0, int(round(float(sekunden) * punkte_je_sekunde(gpx_data))))


def peilung(lat1, lon1, lat2, lon2):
    """Kurs von Punkt 1 nach Punkt 2 in Radiant, 0 = Nord, im Uhrzeigersinn."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.atan2(x, y) % (2.0 * math.pi)


def _abstand_m(a, b):
    """Grob, aber fuer "hat er sich bewegt?" voellig ausreichend."""
    dlat = math.radians(b["lat"] - a["lat"]) * 6371000.0
    dlon = (math.radians(b["lon"] - a["lon"]) * 6371000.0
            * math.cos(math.radians(a["lat"])))
    return math.hypot(dlat, dlon)


def kurse(gpx_data, glaettung=0):
    """
    Kurs je Punkt in Radiant (0 = Nord), Liste so lang wie gpx_data.

    Je Punkt die Peilung zum naechsten Punkt, der mindestens MINDEST_WEG_M
    entfernt ist - so fallen doppelte Zeitstempel und Stillstand heraus.
    Gibt es keinen solchen Punkt mehr (Ende), bleibt der letzte Kurs.
    Danach kreisfoermig geglaettet ueber +-glaettung PUNKTE (aus Sekunden
    mit fenster_punkte() umrechnen).
    """
    n = len(gpx_data)
    if n == 0:
        return []
    roh = [None] * n
    letzter = None
    j = 0
    for i in range(n):
        if j <= i:
            j = i + 1
        while j < n and _abstand_m(gpx_data[i], gpx_data[j]) < MINDEST_WEG_M:
            j += 1
        if j < n:
            letzter = peilung(gpx_data[i]["lat"], gpx_data[i]["lon"],
                              gpx_data[j]["lat"], gpx_data[j]["lon"])
        roh[i] = letzter
    # Punkte ganz am Anfang ohne Bewegung: den ersten echten Kurs uebernehmen.
    erster = next((k for k in roh if k is not None), 0.0)
    roh = [erster if k is None else k for k in roh]

    g = max(0, int(glaettung))
    if g == 0 or n == 1:
        return roh
    # Kreisfoermiges Mittel: atan2(Summe sin, Summe cos) ueber das Fenster.
    sinus = [math.sin(k) for k in roh]
    cosinus = [math.cos(k) for k in roh]
    aus = []
    for i in range(n):
        a, b = max(0, i - g), min(n, i + g + 1)
        s, c = sum(sinus[a:b]), sum(cosinus[a:b])
        aus.append(math.atan2(s, c) % (2.0 * math.pi) if (s or c) else roh[i])
    return aus


def offset_bestimmen(yaw_hand, kurs):
    """Kalibrierung: der Versatz zwischen Handblick und Kurs, in -pi..pi."""
    return (yaw_hand - kurs + math.pi) % (2.0 * math.pi) - math.pi


def folgemarken(von_s, bis_s, offset, kurs_bei, blick_bei,
                schritt=SCHRITT_S):
    """
    Dichte Blickmarken fuer eine Datei im Rohbereich [von_s, bis_s).

    kurs_bei(t_roh)  -> Kurs in Radiant an der Rohzeit (Vorausschau schon
                        eingerechnet), oder None, wenn dort keiner ist
                        (Stelle liegt in einem Schnitt, kein GPX).
    blick_bei(t_roh) -> Blickwinkel, aus dem Neigung und Bildwinkel kommen
                        (Handmarken oder Grundblick). Yaw kommt vom Kurs.

    Bereiche ohne Kurs bekommen keine Marken; dort haelt die Wiedergabe den
    Blick der letzten Marke davor (siehe blickverlauf.Kurve).
    """
    marken = []
    t = von_s
    while t < bis_s:
        kurs = kurs_bei(t)
        if kurs is not None:
            b = blick_bei(t)
            marken.append(Blickmarke(t, kurs + offset, b.pitch, b.fov, WEICH))
        t += schritt
    return marken
