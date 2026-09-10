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

# core/verkehr.py
"""
Vorbeifahrende Fahrzeuge in der Tonspur finden und daempfen (ab 7.0).

WAS ES TUT
----------
Ein Auto oder Motorrad, das an der Kamera vorbeifaehrt, ist im Pegel ein
Berg: ueber Sekunden steigt der Ton deutlich ueber das Grundgeraeusch aus
Wind und Reifen, haelt kurz und faellt wieder ab. Der SUCHER faehrt die
Tonspur einer Datei einmal ab, misst den Pegel je 100 ms und meldet jeden
solchen Berg. Die BEHANDLUNG an jeder Fundstelle folgt dem Verfahren von
Kinotomo Audio (benilerouge.org, MIT - nur das Verfahren, kein Code): das
Original wird Richtung Grundgeraeusch gezogen, hoechstens um den DAEMPFER
(Regler im Encoder Setup, Seite Audio), und die naechste ruhige Strecke der
gleichen Datei wird als Fahrgeraeusch darueber gelegt, mit dem Gegenstueck
der Daempfung als Pegel. So bleibt das Fahrgeraeusch gleich laut, waehrend
das Fahrzeug in die Ferne rueckt. Rampen von RAMPE_S an jeder Kante.

Der Sucher braucht kein Modell und kein numpy: GStreamers "level"-Element
liefert den Pegel, der Rest ist reines Python. Gemessen am 10.09.2026 an
einer GoPro-Aufnahme vom Stilfserjoch (7,5 min, 2,5 GB, 20 Fundstellen):
dieselben 20 Fundstellen auf die Zehntelsekunde wie die numpy-Sonde, 35 s
fuer das Abfahren der Datei (die Zeit geht in das Lesen der Videodaten von
der Platte, das Bild wird nicht dekodiert), 0,1 s fuer die Auswertung.

WER RUFT AUF
------------
managers/ges_encoder_manager.ges_xfade_main - vor dem Bau der Timeline, je
Quelldatei einmal, mit Zwischenspeicher: analyse(). Beim Bau der Timeline
liefern daempfung() und fuellstuecke() die Kurven und Fuellclips je
Fundstelle.

ZWISCHENSPEICHER
----------------
Das Abfahren einer Datei kostet Sekunden bis Minuten (die Platte, s.o.).
Das Ergebnis liegt deshalb als JSON unter config.TEMP_SEGMENTS_CONTAINER/
verkehr/, benannt nach Pfad, Groesse und Aenderungszeit der Datei; der
Behaelter wird nie geloescht. Der Daempfer steckt NICHT im Zwischenspeicher:
er wird erst beim Bau der Timeline angewendet, damit der Regler keinen
neuen Suchlauf ausloest.
"""

import hashlib
import json
import os

import config

#: Laenge eines Messrahmens in Sekunden. Alle Zeiten der Fundstellen sind
#: Vielfache davon.
RAHMEN_S = 0.1

#: Fenster fuer das Grundgeraeusch (gleitend, mittig) und welches Perzentil
#: der Pegel darin als "Grund" gilt. 20: ein Fuenftel der Zeit ist leiser.
GRUND_FENSTER_S = 60.0
GRUND_PERZENTIL = 20

#: Ein Berg beginnt, wenn der Pegel um AN_DB ueber den Grund steigt, und
#: endet, wenn er wieder unter AUS_DB faellt (Hysterese).
AN_DB = 6.0
AUS_DB = 3.0

#: Kuerzere Berge werden verworfen; Luecken kuerzer als LUECKE_S verbinden
#: zwei Berge zu einem.
MIN_S = 1.0
LUECKE_S = 0.6

#: Uebergang an jeder Kante, und Glaettung der Daempfungskurve.
RAMPE_S = 0.5

#: Eine ruhige Fuellstrecke ist hoechstens so lang; laengere Fundstellen
#: werden mit Wiederholungen gefuellt, mit RAMPE_S Ueberlappung. Kuerzer als
#: FUELLUNG_MIN_S wird nicht gefuellt, nur gedaempft.
FUELLUNG_MAX_S = 8.0
FUELLUNG_MIN_S = 1.0

#: Vorgabe und Grenzen des Daempfers (Regler), in dB.
DAEMPFER_VORGABE_DB = 12
DAEMPFER_MIN_DB = 3
DAEMPFER_MAX_DB = 24

#: Aendert sich an Sucher oder Ablageformat etwas, zaehlt das hoch - alte
#: Eintraege im Zwischenspeicher werden dann nicht mehr gelesen.
VERSION = 1


class Abgebrochen(Exception):
    """Der Anwender hat waehrend des Suchlaufs abgebrochen."""


# ---------------------------------------------------------------------------
# Sucher
# ---------------------------------------------------------------------------

def pegel_messen(pfad, fortschritt=None, abbruch=None):
    """Pegel in dB je RAHMEN_S, ueber die ganze Datei.

    playbin mit ausgeschaltetem Bild (flags=AUDIO): nur die Tonspur wird
    dekodiert, "level" liefert je Rahmen den RMS-Wert in dB. fortschritt(p)
    wird mit 0..100 gerufen, abbruch() alle paar Rahmen gefragt.
    """
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst, GLib
    if not Gst.is_initialized():
        Gst.init(None)

    senke = Gst.parse_bin_from_description(
        "audioconvert ! audio/x-raw,channels=1 ! level name=pegel "
        f"interval={int(RAHMEN_S * Gst.SECOND)} post-messages=true "
        "! fakesink sync=false", True)
    play = Gst.ElementFactory.make("playbin", None)
    if play is None:
        raise RuntimeError("playbin is not available")
    play.set_property("uri", GLib.filename_to_uri(os.path.abspath(pfad), None))
    play.set_property("flags", 0x02)            # AUDIO - kein Bild dekodieren
    play.set_property("audio-sink", senke)
    if play.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("audio scan pipeline did not start")

    bus = play.get_bus()
    pegel = []
    dauer_ns = 0
    gemeldet = -1
    try:
        while True:
            msg = bus.timed_pop_filtered(
                200 * Gst.MSECOND,
                Gst.MessageType.ELEMENT | Gst.MessageType.ERROR
                | Gst.MessageType.EOS)
            if msg is None:
                if abbruch is not None and abbruch():
                    raise Abgebrochen()
                continue
            if msg.type == Gst.MessageType.ELEMENT:
                s = msg.get_structure()
                if s is not None and s.get_name() == "level":
                    rms = s.get_value("rms")
                    pegel.append(float(rms[0]) if rms else -100.0)
                    if fortschritt is not None:
                        if dauer_ns <= 0:
                            ok, dauer_ns = play.query_duration(Gst.Format.TIME)
                            if not ok:
                                dauer_ns = 0
                        if dauer_ns > 0:
                            prozent = min(100, int(s.get_value("endtime")
                                                   * 100 / dauer_ns))
                            # Nur vorwaerts melden: am Dateiende kam am
                            # 10.09.2026 nach "100%" noch ein "0%".
                            if prozent > gemeldet:
                                gemeldet = prozent
                                fortschritt(prozent)
                    if abbruch is not None and len(pegel) % 50 == 0 and abbruch():
                        raise Abgebrochen()
                continue
            if msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                raise RuntimeError(f"audio scan failed: {err.message}")
            break   # EOS
    finally:
        play.set_state(Gst.State.NULL)
    return pegel


def _perzentil(werte, p):
    w = sorted(werte)
    if not w:
        return -100.0
    k = (len(w) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(w) - 1)
    return w[f] + (w[c] - w[f]) * (k - f)


def grundgeraeusch(pegel):
    """Der laufende Grund je Rahmen: GRUND_PERZENTIL im mittigen Fenster."""
    halb = int(GRUND_FENSTER_S / RAHMEN_S / 2)
    n = len(pegel)
    return [_perzentil(pegel[max(0, i - halb):min(n, i + halb + 1)],
                       GRUND_PERZENTIL) for i in range(n)]


def _ruhige_strecke(ruhig, von, bis, bedarf):
    """Anfang (Rahmen) der naechsten ruhigen Strecke von 'bedarf' Rahmen vor
    oder hinter [von, bis), oder None."""
    n = len(ruhig)
    beste = None
    lauf = 0
    k = von - 1
    while k >= 0:
        lauf = lauf + 1 if ruhig[k] else 0
        if lauf >= bedarf:
            beste = (k, von - k)
            break
        k -= 1
    lauf = 0
    k = bis
    while k < n:
        lauf = lauf + 1 if ruhig[k] else 0
        if lauf >= bedarf:
            anfang = k - bedarf + 1
            if beste is None or (anfang - bis) < beste[1]:
                beste = (anfang, anfang - bis)
            break
        k += 1
    return None if beste is None else beste[0]


def ereignisse_finden(pegel):
    """Die Berge im Pegel. Je Fund ein dict:

        von, bis     Sekunden in der Datei (Vielfache von RAHMEN_S)
        ueber        Liste: Pegel ueber Grund je Rahmen, dB
        fuellung     Sekunde, an der die ruhige Fuellstrecke beginnt, oder None
        fuellung_s   Laenge der Fuellstrecke in Sekunden
    """
    grund = grundgeraeusch(pegel)
    ueber = [p - g for p, g in zip(pegel, grund)]
    n = len(ueber)
    ruhig = [u <= AUS_DB for u in ueber]

    roh = []
    i = 0
    while i < n:
        if ueber[i] > AN_DB:
            j = i
            while j < n and ueber[j] > AUS_DB:
                j += 1
            if roh and (i - roh[-1][1]) * RAHMEN_S < LUECKE_S:
                roh[-1][1] = j
            else:
                roh.append([i, j])
            i = j
        else:
            i += 1

    funde = []
    for s, e in roh:
        if (e - s) * RAHMEN_S < MIN_S:
            continue
        bedarf = min(e - s, int(FUELLUNG_MAX_S / RAHMEN_S))
        q = None
        while bedarf * RAHMEN_S >= FUELLUNG_MIN_S:
            q = _ruhige_strecke(ruhig, s, e, bedarf)
            if q is not None:
                break
            bedarf //= 2
        funde.append({
            "von": round(s * RAHMEN_S, 3),
            "bis": round(e * RAHMEN_S, 3),
            "ueber": [round(u, 1) for u in ueber[s:e]],
            "fuellung": None if q is None else round(q * RAHMEN_S, 3),
            "fuellung_s": 0.0 if q is None else round(bedarf * RAHMEN_S, 3),
        })
    return funde


# ---------------------------------------------------------------------------
# Zwischenspeicher
# ---------------------------------------------------------------------------

def _cache_datei(pfad):
    try:
        st = os.stat(pfad)
        kennung = f"{os.path.abspath(pfad)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        kennung = os.path.abspath(pfad)
    kennung += (f"|v{VERSION}|{RAHMEN_S}|{GRUND_FENSTER_S}|{GRUND_PERZENTIL}"
                f"|{AN_DB}|{AUS_DB}|{MIN_S}|{LUECKE_S}|{FUELLUNG_MAX_S}")
    name = hashlib.sha1(kennung.encode("utf-8")).hexdigest()[:20]
    return os.path.join(config.TEMP_SEGMENTS_CONTAINER, "verkehr", name + ".json")


def analyse(pfad, log=None, fortschritt=None, abbruch=None):
    """Fundstellen einer Datei, aus dem Zwischenspeicher oder frisch.

    Rueckgabe: {"dauer": Sekunden, "ereignisse": [siehe ereignisse_finden]}
    """
    log = log or (lambda text: None)
    datei = _cache_datei(pfad)
    try:
        with open(datei, "r", encoding="utf-8") as f:
            daten = json.load(f)
        if daten.get("version") == VERSION and "ereignisse" in daten:
            log(f"[TRAFFIC] {os.path.basename(pfad)}: "
                f"{len(daten['ereignisse'])} spot(s) from cache")
            return daten
    except (OSError, ValueError):
        pass

    log(f"[TRAFFIC] {os.path.basename(pfad)}: scanning the audio track...")
    pegel = pegel_messen(pfad, fortschritt, abbruch)
    daten = {
        "version": VERSION,
        "dauer": round(len(pegel) * RAHMEN_S, 3),
        "ereignisse": ereignisse_finden(pegel),
    }
    log(f"[TRAFFIC] {os.path.basename(pfad)}: {len(daten['ereignisse'])} "
        f"spot(s) in {daten['dauer']:.1f}s")
    try:
        os.makedirs(os.path.dirname(datei), exist_ok=True)
        with open(datei, "w", encoding="utf-8") as f:
            json.dump(daten, f)
    except OSError as exc:
        log(f"[TRAFFIC] cache not written: {exc}")
    return daten


# ---------------------------------------------------------------------------
# Behandlung: Kurven fuer die Timeline
# ---------------------------------------------------------------------------

def daempfung(ereignis, daempfer_db):
    """Lautstaerkekurve des Originals an dieser Fundstelle.

    Rueckgabe: [(Sekunde in der Datei, Faktor)], stueckweise linear, Faktor
    1.0 ausserhalb. Je Rahmen wird der Pegel auf Grund + AUS_DB gezogen,
    hoechstens um daempfer_db; danach ein gleitender Mittelwert ueber
    RAMPE_S, der zugleich die Rampen an den Kanten ergibt.
    """
    ueber = ereignis["ueber"]
    if not ueber or daempfer_db <= 0:
        return []
    rand = max(1, int(round(RAMPE_S / RAHMEN_S)))
    db = [0.0] * rand
    for u in ueber:
        db.append(max(-float(daempfer_db), min(0.0, AUS_DB - u)))
    db += [0.0] * rand
    # gleitender Mittelwert ueber 'rand' Rahmen, mittig - so lang wie die
    # Rampe; die Nullen davor und dahinter ergeben die Rampen an den Kanten.
    halb = rand // 2
    n = len(db)
    kurve = []
    t0 = ereignis["von"] - rand * RAHMEN_S
    for i in range(n):
        a, b = max(0, i - halb), min(n, i + halb + 1)
        mittel = sum(db[a:b]) / (b - a)
        kurve.append((t0 + (i + 0.5) * RAHMEN_S, 10 ** (mittel / 20.0)))
    return kurve


def fuellstuecke(ereignis):
    """Die Fuellclips einer Fundstelle: [(inpoint_s, versatz_s, dauer_s)].

    inpoint_s: Sekunde in der Datei, an der das Stueck der ruhigen Strecke
    beginnt; versatz_s: wo es relativ zum Anfang der Fundstelle liegt;
    dauer_s: seine Laenge. Ist die ruhige Strecke kuerzer als die Fundstelle,
    wird sie wiederholt, jedes Stueck um RAMPE_S ueberlappend, damit die
    Naehte ueberblendet werden koennen (siehe fuellkurve).
    """
    q = ereignis.get("fuellung")
    stueck = float(ereignis.get("fuellung_s") or 0.0)
    if q is None or stueck <= 0:
        return []
    laenge = ereignis["bis"] - ereignis["von"]
    # Die Fuellung reicht um RAMPE_S ueber beide Kanten hinaus: dort ist die
    # Daempfungskurve schon unterwegs (daempfung() glaettet ueber die Kante),
    # und das Gegenstueck (1 - Faktor) braucht Material, um hoerbar zu sein.
    anfang = -RAMPE_S
    ende = laenge + RAMPE_S
    stuecke = []
    lage = anfang
    while lage < ende:
        dauer = min(stueck, ende - lage)
        if dauer <= 0:
            break
        stuecke.append((float(q), lage, dauer))
        if lage + dauer >= ende:
            break
        lage += stueck - RAMPE_S
    return stuecke


def fuellkurve(stuecke, index):
    """Naht-Ueberblendung eines Fuellstuecks: [(versatz_s, Faktor)].

    Das erste Stueck beginnt voll, das letzte endet voll; dazwischen faehrt
    jedes ueber RAMPE_S ein und aus, wo es das Nachbarstueck ueberlappt.
    """
    _q, lage, dauer = stuecke[index]
    kurve = []
    if index > 0:
        kurve += [(lage, 0.0), (lage + min(RAMPE_S, dauer), 1.0)]
    else:
        kurve.append((lage, 1.0))
    if index < len(stuecke) - 1:
        kurve += [(lage + dauer - min(RAMPE_S, dauer), 1.0), (lage + dauer, 0.0)]
    else:
        kurve.append((lage + dauer, 1.0))
    return kurve


def gegenstueck(kurve):
    """1 - Faktor: der Pegel der Fuellung, damit Original + Fuellung zusammen
    das Fahrgeraeusch auf gleicher Hoehe halten."""
    return [(t, max(0.0, 1.0 - v)) for t, v in kurve]
