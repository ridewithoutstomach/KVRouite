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
Geschwindigkeitsspitze an einer Schnittnaht glaetten.

Das Problem: Faellt die Kamera aus und der Ausfall wird aus dem Video
geschnitten, nimmt der Schnitt auch die GPX-Punkte dieser Zeit heraus und
rueckt alles dahinter nach vorn. Die Strecke, die in der Zeit gefahren wurde,
bleibt aber - als ein Segment von 100 m in einer Sekunde. Gesehen am
06.09.2026 im Projekt Stelvio: 105 m in 1,0 s, 381 km/h, bei 10,5 km/h
ringsum. Kinomap und ICTrainer rechnen das Tempo aus der GPX-Datei selbst,
ein reines Anzeige-Pflaster in der App hilft dort nicht.

Was NICHT geht: die Punkte ringsum auf ein gemeinsames Tempo plattziehen
("Set AverageSpeed"). Ein Fahrer ist auf 5 % schneller als auf 9 %; ein
konstantes Tempo ueber wechselnde Steigung faellt auf.

Was geht, und was diese Datei tut: Der Naht die fehlende Fahrzeit geben
(Sprungdistanz durch Umfeldtempo, bei Stelvio 35 s) und dieselbe Zeit aus
dem Umfeld wieder hereinholen, indem dort jeder Schritt um denselben Faktor
verkuerzt wird. Alle Geschwindigkeiten im Bereich werden damit um diesen
Faktor hoeher, in ihrem echten Verhaeltnis: die flachere Minute bleibt die
schnellere. Positionen, Hoehen und damit die Steigung je Punkt bleiben
unangetastet. Hinter dem Bereich aendert sich keine Zeit, das Video bleibt
synchron.

Um den FAKTOR, nicht auf einen gemeinsamen Schritt - das ist der Unterschied
zu chT auf einem Bereich. Der beim Videoschnitt interpolierte Nahtpunkt hat
einen kuerzeren Schritt als seine Nachbarn (bei Stelvio 0,513 s fuer
1,54 m). Bekommt er denselben Schritt wie alle, faellt sein Tempo von 10,8
auf 6,3 km/h - so gesehen am 06.09.2026 nach dem chT-Rezept. Mit dem Faktor
wird aus 0,513 s eben 0,45 s, und sein Tempo steigt wie das aller anderen.

Der Bereich: je Seite mit 60 Punkten beginnen und in 30er-Schritten
wachsen, solange der Faktor ueber der Grenze liegt (Vorgabe 15 %) und die
Steigung der dazukommenden Punkte nahe der Steigung an der Naht bleibt
(Vorgabe 2 Prozentpunkte). Vor einer weiteren Spitze, dem Spuranfang und
dem Spurende endet der Bereich; die Seiten duerfen ungleich lang sein.
Gemessen an Stelvio: die Naht bei 2276 (lange Luecke, gleichmaessig 9 %)
bekommt einen langen Bereich, die bei 1764 (kurze Luecke, Steigung von 1 %
auf 15 % wechselnd) einen kurzen - dieselbe Wahl, die von Hand getroffen
wurde. Nachzurechnen mit check_naht.py im Scratchpad vom 06.09.2026.

Ohne Qt, damit sich alles ohne Oberflaeche nachrechnen laesst. Die Zeiten
sind datetime-Objekte, wie ueberall in gpx_data.
"""

import copy
import math
import statistics
from datetime import timedelta

from core.gpx_parser import recalc_gpx_data

#: Punkte je Seite fuer das Umfeldtempo und als Startbereich.
UMFELD = 60
#: Um so viele Punkte waechst eine Seite je Runde.
WACHSTUM = 30
#: Mehr Punkte je Seite gibt es nicht - fuenf Minuten bei 1 s Abstand.
HOECHSTENS = 300
#: Der Bereich waechst, solange das Tempo im Bereich um mehr als das steigt.
FAKTOR_GRENZE = 1.15
#: Dazukommende Punkte muessen in der Steigung so nah an der Naht liegen.
STEIGUNG_TOLERANZ = 2.0
#: Kuerzere Segmente gelten nicht als Spitze - GPS-Zittern ist kuerzer.
MIN_SPRUNG_M = 20.0
#: Eine Spitze ist mindestens so viel schneller als ihr Umfeld.
SPITZE_FAKTOR = 3.0
#: Langsamer gilt als Stillstand und zaehlt nicht zum Umfeldtempo.
STILLSTAND_KMH = 0.5


class NahtFehler(Exception):
    """Der Vorschlag laesst sich an dieser Stelle nicht bilden."""


class Vorschlag:
    """Das Ergebnis von vorschlagen(): alles, was Dialog und anwenden() brauchen.

    idx        Index des Punkts, der den Sprung traegt (sein Segment zum
               Vorgaenger ist die Naht)
    dm         Laenge dieses Segments in m
    dt_alt     seine bisherige Zeit in s
    v_spitze   sein bisheriges Tempo in km/h
    v_umfeld   Median des Tempos ringsum in km/h
    naht_s     Zeit, die das Segment bekommt (dm durch v_umfeld)
    davor      Punkte vor der Naht, deren Schritte verkuerzt werden
    danach     Punkte dahinter
    b_idx      erster Punkt des Bereichs (idx - 1 - davor); seine Zeit bleibt
    e_idx      letzter Punkt (idx + danach); seine Zeit bleibt
    schritt    was aus einem 1-s-Schritt im Bereich wird, in s (1 / faktor)
    faktor     alte Zeit des Bereichs durch neue - um so viel schneller;
               jeder Schritt im Bereich wird durch diesen Faktor geteilt
    steigung   Steigung des Startbereichs in Prozent, Naht ausgenommen
    max_davor  wie weit jede Seite hoechstens reichen darf (Spuranfang,
    max_danach Spurende, naechste Spitze, HOECHSTENS)
    halt_davor warum das Wachsen dieser Seite endete (fuer den Dialog)
    halt_danach
    """

    def __init__(self):
        self.idx = 0
        self.dm = 0.0
        self.dt_alt = 0.0
        self.v_spitze = 0.0
        self.v_umfeld = 0.0
        self.naht_s = 0.0
        self.davor = 0
        self.danach = 0
        self.b_idx = 0
        self.e_idx = 0
        self.schritt = 0.0
        self.faktor = 1.0
        self.steigung = 0.0
        self.max_davor = 0
        self.max_danach = 0
        self.halt_davor = ""
        self.halt_danach = ""


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def _hav(a, b):
    R = 6371000.0
    la1, lo1 = math.radians(a["lat"]), math.radians(a["lon"])
    la2, lo2 = math.radians(b["lat"]), math.radians(b["lon"])
    x = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _dt(g, i):
    """Zeit des Segments i-1 -> i in Sekunden, 0 wenn eine Zeit fehlt."""
    a, b = g[i - 1].get("time"), g[i].get("time")
    if a is None or b is None:
        return 0.0
    return (b - a).total_seconds()


def _segment_m(g, i):
    """Laenge des Segments i-1 -> i, wie recalc_gpx_data sie rechnet (3D)."""
    d = g[i].get("delta_m")
    if d is not None and i > 0:
        return float(d)
    d2 = _hav(g[i - 1], g[i])
    dh = float(g[i].get("ele", 0.0)) - float(g[i - 1].get("ele", 0.0))
    return math.sqrt(d2 * d2 + dh * dh)


def _steigung(g, i0, i1, ohne=None):
    """Steigung in Prozent ueber die Segmente i0+1 .. i1, 'ohne' ausgelassen.

    Hoehendifferenz durch horizontale Strecke, wie je Punkt in
    recalc_gpx_data - nur ueber viele Punkte, damit das Barometerzittern
    einzelner Sekunden nicht zaehlt.
    """
    d2 = dh = 0.0
    for i in range(i0 + 1, i1 + 1):
        if i == ohne:
            continue
        d2 += _hav(g[i - 1], g[i])
        dh += float(g[i].get("ele", 0.0)) - float(g[i - 1].get("ele", 0.0))
    return (dh / d2 * 100.0) if d2 > 0 else 0.0


def umfeldtempo(g, idx, spitzen=()):
    """Median des Tempos je UMFELD Punkte vor und hinter idx, in km/h.

    Median statt Mittelwert: eine zweite Spitze in der Naehe oder ein
    einzelner Ausreisser darf das Umfeld nicht mitziehen. Stillstand zaehlt
    nicht - wer an der Naht angehalten hat, ist deswegen nicht langsamer
    gefahren.
    """
    werte = []
    for i in range(max(1, idx - UMFELD), min(len(g), idx + UMFELD + 1)):
        if i == idx or i in spitzen:
            continue
        v = float(g[i].get("speed_kmh", 0.0) or 0.0)
        if v > STILLSTAND_KMH:
            werte.append(v)
    return statistics.median(werte) if werte else 0.0


def spitzen_finden(g):
    """Indizes aller Punkte, deren Segment eine Spitze traegt.

    Spitze heisst: laenger als MIN_SPRUNG_M und mindestens SPITZE_FAKTOR mal
    so schnell wie das Umfeld. Bei Stelvio: [1763, 2275] - die beiden
    Kameraausfaelle, sonst nichts.
    """
    raus = []
    for i in range(1, len(g)):
        if _segment_m(g, i) < MIN_SPRUNG_M:
            continue
        v = float(g[i].get("speed_kmh", 0.0) or 0.0)
        um = umfeldtempo(g, i)
        if um > 0 and v >= SPITZE_FAKTOR * um:
            raus.append(i)
    return raus


# ---------------------------------------------------------------------------
# Vorschlag
# ---------------------------------------------------------------------------
def _grenzen(g, idx, spitzen):
    """Wie viele Punkte jede Seite hoechstens umfassen darf.

    Vor der Naht: bis zum Spuranfang oder bis hinter die vorige Spitze -
    deren Segment darf nicht im Bereich liegen, sonst wird es mit verkuerzt.
    Dahinter entsprechend bis vor die naechste Spitze oder zum Spurende.
    """
    n = len(g)
    vorige = [s for s in spitzen if s < idx]
    naechste = [s for s in spitzen if s > idx]
    max_davor = idx - 1 - (max(vorige) if vorige else 0)
    max_danach = (min(naechste) - 1 if naechste else n - 1) - idx
    return (max(0, min(HOECHSTENS, max_davor)),
            max(0, min(HOECHSTENS, max_danach)))


def _rechnen(g, v, davor, danach):
    """schritt und faktor fuer diese Bereichsgroessen in v eintragen."""
    v.davor, v.danach = davor, danach
    v.b_idx = v.idx - 1 - davor
    v.e_idx = v.idx + danach
    alt = ((g[v.idx - 1]["time"] - g[v.b_idx]["time"]).total_seconds()
           + (g[v.e_idx]["time"] - g[v.idx]["time"]).total_seconds())
    neu = alt - (v.naht_s - v.dt_alt)
    if neu <= 0.0 or davor + danach <= 0:
        raise NahtFehler(
            "The range is too short: it holds %.1f s, but the seam needs "
            "%.1f s more than it has." % (alt, v.naht_s - v.dt_alt))
    v.faktor = alt / neu
    v.schritt = 1.0 / v.faktor
    return v


def vorschlagen(g, idx, davor=None, danach=None, faktor_grenze=FAKTOR_GRENZE):
    """Den Vorschlag fuer die Spitze am Punkt idx bilden.

    davor/danach: feste Bereichsgroessen (Punkte je Seite), etwa aus dem
    Dialog. None heisst: selbst waehlen, siehe Kopf der Datei.
    """
    n = len(g)
    if not 1 <= idx < n:
        raise NahtFehler("Point %d does not exist." % idx)
    for i in (idx - 1, idx):
        if g[i].get("time") is None:
            raise NahtFehler("Point %d has no time." % i)

    spitzen = set(spitzen_finden(g))
    v = Vorschlag()
    v.idx = idx
    v.dm = _segment_m(g, idx)
    v.dt_alt = _dt(g, idx)
    v.v_spitze = float(g[idx].get("speed_kmh", 0.0) or 0.0)
    v.v_umfeld = umfeldtempo(g, idx, spitzen)
    if v.v_umfeld <= 0.0:
        raise NahtFehler("No speed around this point - the surroundings "
                         "stand still, so there is nothing to take the time "
                         "from.")
    v.naht_s = v.dm / (v.v_umfeld / 3.6)
    v.max_davor, v.max_danach = _grenzen(g, idx, spitzen)
    if v.max_davor < 1 or v.max_danach < 1:
        raise NahtFehler("There is no room next to this point: the track "
                         "starts or ends here, or another spike is directly "
                         "adjacent.")

    start_davor = min(UMFELD, v.max_davor)
    start_danach = min(UMFELD, v.max_danach)
    v.steigung = _steigung(g, idx - 1 - start_davor, idx + start_danach, ohne=idx)

    if davor is not None or danach is not None:
        d1 = min(v.max_davor, max(1, int(davor if davor is not None else start_davor)))
        d2 = min(v.max_danach, max(1, int(danach if danach is not None else start_danach)))
        v.halt_davor = v.halt_danach = "set by hand"
        return _rechnen(g, v, d1, d2)

    # Selbst waehlen: wachsen, solange der Faktor zu hoch ist und die
    # Steigung mitspielt.
    d1, d2 = start_davor, start_danach
    halt1 = halt2 = ""

    def _passt(i0, i1):
        return abs(_steigung(g, i0, i1) - v.steigung) <= STEIGUNG_TOLERANZ

    while True:
        try:
            _rechnen(g, v, d1, d2)
            if v.faktor <= faktor_grenze:
                break
        except NahtFehler:
            pass    # noch zu kurz fuer die fehlende Zeit - weiter wachsen
        gewachsen = False
        if not halt1:
            neu1 = min(d1 + WACHSTUM, v.max_davor)
            if neu1 <= d1:
                halt1 = ("track start" if v.max_davor < HOECHSTENS
                         and idx - 1 - v.max_davor == 0 else
                         "next spike" if v.max_davor < HOECHSTENS else
                         "limit of %d points" % HOECHSTENS)
            elif not _passt(idx - 1 - neu1, idx - 1 - d1):
                halt1 = "gradient changes (%.1f %%)" % _steigung(
                    g, idx - 1 - neu1, idx - 1 - d1)
            else:
                d1 = neu1
                gewachsen = True
        if not halt2:
            neu2 = min(d2 + WACHSTUM, v.max_danach)
            if neu2 <= d2:
                halt2 = ("track end" if v.max_danach < HOECHSTENS
                         and idx + v.max_danach == n - 1 else
                         "next spike" if v.max_danach < HOECHSTENS else
                         "limit of %d points" % HOECHSTENS)
            elif not _passt(idx + d2, idx + neu2):
                halt2 = "gradient changes (%.1f %%)" % _steigung(
                    g, idx + d2, idx + neu2)
            else:
                d2 = neu2
                gewachsen = True
        if not gewachsen:
            break

    v.halt_davor = halt1 or "factor within limit"
    v.halt_danach = halt2 or "factor within limit"
    return _rechnen(g, v, d1, d2)       # wirft, wenn es auch so nicht reicht


# ---------------------------------------------------------------------------
# Anwenden und Vorschau
# ---------------------------------------------------------------------------
def anwenden(g, v):
    """Die Zeiten nach dem Vorschlag setzen - nur die Zeiten, in place.

    Jeder Schritt im Bereich wird durch den Faktor geteilt, seine alte
    Laenge bleibt also im Verhaeltnis erhalten. Die Punkte b_idx und e_idx
    behalten ihre Zeit. Davor wird vorwaerts aufgebaut, dahinter rueckwaerts
    vom Ende her. Damit steht e_idx unveraendert da, und kein Punkt hinter
    dem Bereich bewegt sich - nicht einmal um Mikrosekunden. Die Naht
    bekommt, was zwischen beiden Seiten uebrig bleibt: naht_s.

    Rueckgabe: die Zeit, die die Naht wirklich bekommen hat, in s.
    """
    alte_schritte = {i: _dt(g, i) for i in range(v.b_idx + 1, v.e_idx + 1)}
    skala = 1.0 / v.faktor
    t = g[v.b_idx]["time"]
    for i in range(v.b_idx + 1, v.idx):         # b+1 .. idx-1, vorwaerts
        t = t + timedelta(seconds=alte_schritte[i] * skala)
        g[i]["time"] = t
    t = g[v.e_idx]["time"]
    for i in range(v.e_idx, v.idx, -1):         # e-1 .. idx, rueckwaerts
        t = t - timedelta(seconds=alte_schritte[i] * skala)
        g[i - 1]["time"] = t
    return _dt(g, v.idx)


def vorschau(g, v):
    """Eine Kopie der Spur mit angewandtem Vorschlag, neu durchgerechnet."""
    kopie = copy.deepcopy(g)
    anwenden(kopie, v)
    recalc_gpx_data(kopie)
    return kopie


def zeilen(g_alt, g_neu, v, breite=60, nah=10):
    """Vergleich vorher/nachher fuer den Dialog.

    Rueckgabe: Liste von (bezeichnung, steigung, v_alt, v_neu). Von der Naht
    aus nach aussen: erst die `nah` naechsten Punkte je Seite als eigene
    Zeile, dann je `breite` Punkte eine; dazu die Naht selbst und das
    hoechste Tempo im Bereich. Tempo als Mittelwert der Punkte, Steigung
    ueber die Strecke - wie in den Rechnungen vom 06.09.2026.

    Warum die Nahzeile: am 08.09.2026 stand in der Tabelle "60..1 before
    19.3 km/h", die Naht bekam 15.0 km/h - das sah nach zu langsam aus.
    Erst die Tabelle zeigte, dass die Punkte direkt vor und hinter der Naht
    selbst mit 15 km/h fahren; das Mittel ueber 60 Punkte hatte schnellere
    Abschnitte weiter weg mit drin. Die Nahzeile zeigt das, ohne dass man
    in die Tabelle muss.
    """
    def mittel(g, i0, i1):
        w = [float(g[i].get("speed_kmh", 0.0) or 0.0)
             for i in range(i0 + 1, i1 + 1) if i != v.idx]
        return (sum(w) / len(w)) if w else 0.0

    raus = []
    # davor: Bloecke rueckwaerts sammeln, dann in Leserichtung ausgeben.
    # Der erste (nahste) Block ist `nah` breit, die weiteren `breite`.
    bloecke = []
    ende = v.idx - 1
    schritt_breite = nah
    while ende > v.b_idx:
        anfang = max(v.b_idx, ende - schritt_breite)
        bloecke.append((anfang, ende))
        ende = anfang
        schritt_breite = breite
    for (i0, i1) in reversed(bloecke):
        raus.append(("%d..%d before" % (v.idx - 1 - i0, v.idx - i1),
                     _steigung(g_alt, i0, i1), mittel(g_alt, i0, i1),
                     mittel(g_neu, i0, i1)))
    raus.append(("seam", _steigung(g_alt, v.idx - 1, v.idx),
                 float(g_alt[v.idx].get("speed_kmh", 0.0) or 0.0),
                 float(g_neu[v.idx].get("speed_kmh", 0.0) or 0.0)))
    anfang = v.idx
    schritt_breite = nah
    while anfang < v.e_idx:
        ende = min(v.e_idx, anfang + schritt_breite)
        raus.append(("%d..%d after" % (anfang - v.idx + 1, ende - v.idx),
                     _steigung(g_alt, anfang, ende), mittel(g_alt, anfang, ende),
                     mittel(g_neu, anfang, ende)))
        anfang = ende
        schritt_breite = breite
    bereich = [i for i in range(v.b_idx + 1, v.e_idx + 1) if i != v.idx]
    raus.append(("max in range", 0.0,
                 max(float(g_alt[i].get("speed_kmh", 0.0) or 0.0) for i in bereich),
                 max(float(g_neu[i].get("speed_kmh", 0.0) or 0.0) for i in bereich)))
    return raus


def verlauf(g_alt, g_neu, v):
    """Tempo je Punkt im Bereich, fuer das Diagramm im Dialog.

    Rueckgabe: Liste von (abstand, v_alt, v_neu); abstand ist der Punkt
    relativ zur Naht - negativ davor, 0 die Naht, positiv dahinter. Die
    Naht selbst ist mit drin (v_alt ist dort die Spitze, im Diagramm wird
    sie abgeschnitten und beschriftet).
    """
    raus = []
    for i in range(v.b_idx + 1, v.e_idx + 1):
        raus.append((i - v.idx,
                     float(g_alt[i].get("speed_kmh", 0.0) or 0.0),
                     float(g_neu[i].get("speed_kmh", 0.0) or 0.0)))
    return raus


def versatz_dahinter(g_alt, g_neu, v):
    """Zeitversatz des ersten Punkts hinter dem Bereich - muss 0 sein."""
    if v.e_idx + 1 >= len(g_alt):
        return 0.0
    return (g_neu[v.e_idx + 1]["time"] - g_alt[v.e_idx + 1]["time"]).total_seconds()
