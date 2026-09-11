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
Original wird an der Fundstelle um den DAEMPFER abgesenkt (Regler im
Encoder Setup, Seite Audio; Kinotomo: "volume original", Vorgabe 30 %),
und die naechste ruhige Strecke der gleichen Datei wird als Fahrgeraeusch
darueber gelegt, mit dem FUELLPEGEL (Kinotomo: "volume added", Vorgabe
100 %). So bleibt das Fahrgeraeusch da, waehrend das Fahrzeug um den
Daempfer leiser wird. Rampen von RAMPE_S an jeder Kante.

Bis zum 10.09.2026 abends zog die Daempfung nur bis auf Grund + AUS_DB
herunter und die Fuellung kam nur mit dem Gegenstueck davon: bei einem
Fahrzeug 6 dB ueber Grund waren das 3 dB Daempfung und 30 % Fuellung, kaum
zu hoeren (Bernd: "das macht die App von Kinotomo ganz anders"). Kinotomo
senkt um den eingestellten Faktor ab, ohne Blick auf den Grund - so jetzt
auch hier.

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
import threading
import time

import config


#: Laenge eines Messrahmens in Sekunden. Alle Zeiten der Fundstellen sind
#: Vielfache davon.
RAHMEN_S = 0.1

#: Fenster fuer das Grundgeraeusch (gleitend, mittig) und welches Perzentil
#: der Pegel darin als "Grund" gilt. 20: ein Fuenftel der Zeit ist leiser.
GRUND_FENSTER_S = 60.0
GRUND_PERZENTIL = 20

#: Ein Berg beginnt, wenn der Pegel um AN dB ueber den Grund steigt, und
#: endet, wenn er wieder unter AUS dB faellt (Hysterese). Empfindlichkeit
#: 1-5 -> (AN, AUS). Bis zum 10.09.2026 abends fest 6/3 dB: damit fand der
#: Sucher in Kinotomos eigenem Demo-Video (Auto 2-4 dB ueber der Fahrt)
#: NICHTS, und bei Berns Autos nur den lauten Kern ohne An- und Wegfahren.
#: 3/1,5 dB trifft dort die Handmarkierung des Autors - das ist die Vorgabe.
#: Gemessen an Kinotomos Demo (Handmarkierung 10-19 s): 4/2 dB ergibt mit
#: LUECKE_S 10,0-19,4 s; 3/1,5 dB laeuft bis 23,6 s, weil der Pegel nach
#: dem Auto nur langsam auf den Grund zurueckfaellt.
SCHWELLEN = {
    1: (6.0, 3.0),
    2: (5.0, 2.5),
    3: (4.0, 2.0),
    4: (3.0, 1.5),
    5: (2.0, 1.0),
}
EMPFINDLICHKEIT_VORGABE = 3
AN_DB, AUS_DB = SCHWELLEN[EMPFINDLICHKEIT_VORGABE]

#: Kuerzere Berge werden verworfen; Luecken kuerzer als LUECKE_S verbinden
#: zwei Berge zu einem.
MIN_S = 1.0
#: 2 s (bis 10.09.2026 abends 0,6): in Kinotomos Demo fiel das Auto fuer
#: 1,1 s unter die Schwelle, zwei Stellen mit einer Sekunde volles Auto
#: dazwischen - hoerbares Pumpen. Der Autor markiert einen Block.
LUECKE_S = 2.5
#: Laenger ist kein vorbeifahrendes Fahrzeug, sondern Verkehr oder eine
#: lautere Strasse: solche Berge werden nicht behandelt. Berns Vehicel
#: (10.09.2026 spaet): ein "Berg" von 128 s, gefuellt mit einer 5-s-Schleife.
MAX_STELLE_S = 40.0
#: Vorlauf und Nachlauf je Stelle in Sekunden: die Schwelle springt erst
#: an, wenn das Fahrzeug schon zu hoeren ist, und faellt ab, bevor es weg
#: ist. Kinotomos Autor markiert von Hand grosszuegiger (Bernd, 10.09.2026
#: abends: "trifft das ankommende Auto nicht rechtzeitig", "ab Sekunde 19
#: wesentlich lauter").
VORLAUF_S = 1.5
NACHLAUF_S = 1.5
#: Ausklang: ein wegfahrendes Fahrzeug faellt unter das Grundgeraeusch und
#: ist trotzdem noch zu hoeren (Kinotomos Demo: der Roller von 19 bis 27 s,
#: der Pegel faellt dabei stetig von -18 auf -23 dB). Die Stelle bleibt
#: deshalb offen, solange der Pegel nach dem Kern weiter faellt - bis zu
#: AUSKLANG_MAX_S, mit AUSKLANG_TOLERANZ_DB Spielraum fuer kleine Buckel -
#: und nur, wenn er dabei wenigstens AUSKLANG_MIN_DB verliert.
AUSKLANG_MAX_S = 10.0
AUSKLANG_TOLERANZ_DB = 1.0
AUSKLANG_MIN_DB = 2.0
#: Verfolgt wird nur, solange der Pegel noch ueber dem Grund liegt: ein
#: Fahrzeug hoert man nur, solange es ueber dem Fahrgeraeusch liegt. Ohne
#: diese Bremse wuchsen am Stelvio (Wind, Reifen) die Stellen ineinander,
#: 98 % der Aufnahme "Fahrzeug" (10.09.2026 spaet).
AUSKLANG_GRUND_DB = 0.5

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
DAEMPFER_MAX_DB = 30

#: Pegel der Fuellung in Prozent (Kinotomo "volume added"). 100: die ruhige
#: Strecke in voller Hoehe, die Stelle bleibt etwa gleich laut, nur das
#: Fahrzeug ist weg. 0: keine Fuellung, die Stelle wird um den Daempfer
#: leiser - ein hoerbares Loch.
FUELL_ANTEIL_VORGABE = 100

#: Tiefpass auf dem Fuellstueck, in Hz; 0 heisst ungefiltert. Das Fuellstueck
#: ist eine Kopie der naechsten ruhigen Strecke - alles, was darin hoch und
#: dauernd ist (ein Quietschen der Halterung, ein Rad), laege an der
#: Fundstelle sonst DOPPELT: einmal im Original, einmal in der Fuellung.
#: Bernd, 10.09.2026: nach dem Daempfen war ein Quietschen deutlicher als
#: vorher. Reifen und Wind liegen tief; unter der Grenze bleibt das
#: Fahrgeraeusch, darueber faellt die zweite Kopie weg.
FUELL_TIEFPASS_VORGABE_HZ = 1000
FUELL_TIEFPASS_MIN_HZ = 300
FUELL_TIEFPASS_MAX_HZ = 4000

#: Aendert sich an Sucher oder Ablageformat etwas, zaehlt das hoch - alte
#: Eintraege im Zwischenspeicher werden dann nicht mehr gelesen.
VERSION = 5     # 2: Pegelverlauf und Sprachwerte im Eintrag (10.09.2026)
                # 5: bereichsweise, None wo nicht abgefahren (10.09.2026 spaet)
                # 4: nur Pegel und Sprachwerte, Berge je Empfindlichkeit
                #    beim Lesen (10.09.2026 abends)
                # 3: Sprachwerte mit Hochpass vor dem Detektor (10.09.2026)


class Abgebrochen(Exception):
    """Der Anwender hat waehrend des Suchlaufs abgebrochen."""


# ---------------------------------------------------------------------------
# Sucher
# ---------------------------------------------------------------------------

def _pegel_aus_wav(wav):
    """(pegel, daten) aus der 16-kHz-mono-WAV: der RMS-Pegel je RAHMEN_S in
    dBFS - dasselbe Mass wie GStreamers level-Element - und die rohen
    Abtastwerte als bytes. Ein Durchlauf in reinem Python, ohne numpy
    (Lite hat keins); 11 Minuten Ton brauchen etwa eine Sekunde."""
    import array
    import math
    import wave
    with wave.open(wav, "rb") as w:
        daten = w.readframes(w.getnframes())
    werte = array.array("h")
    werte.frombytes(daten)
    je = int(round(16000 * RAHMEN_S))
    pegel = []
    voll = 32768.0 * 32768.0
    for i in range(0, len(werte) - je + 1, je):
        stueck = werte[i:i + je]
        q = sum(v * v for v in stueck) / je
        pegel.append(10.0 * math.log10(q / voll) if q > 0 else -100.0)
    return pegel, daten


def pegel_messen(pfad, fortschritt=None, abbruch=None, proben=None,
                 von_s=None, bis_s=None):
    """Pegel in dB je RAHMEN_S, ueber die ganze Datei oder einen Bereich.

    Rueckgabe: (pegel, dauer_s, anfang_s) - pegel ab anfang_s (der Beginn
    des ersten Rahmens, ein Vielfaches von RAHMEN_S), dauer_s die Laenge
    der ganzen Datei.

    von_s/bis_s: nur diesen Bereich abfahren (Segment-Seek). Das Lesen der
    Videodaten von der Platte ist der teure Teil - bei Berns 4K-Dateien vom
    externen Laufwerk 4 Minuten je 11-Minuten-Datei (10.09.2026 spaet); wer
    nur zwei Minuten davon behaelt, soll nur die lesen.

    playbin mit ausgeschaltetem Bild (flags=AUDIO): nur die Tonspur wird
    dekodiert, "level" liefert je Rahmen den RMS-Wert in dB. fortschritt(p)
    wird mit 0..100 gerufen, abbruch() alle paar Rahmen gefragt.

    proben: eine Liste, in die die Abtastwerte der Tonspur als bytes
    (16 kHz, mono, S16LE) gesammelt werden - fuer den Sprachdetektor
    (core/sprache), der dieselbe Form braucht. So faehrt EIN Durchlauf die
    Datei ab, und das Lesen der Videodaten von der Platte, der teure Teil,
    passiert einmal. Der Pegel wird deshalb ebenfalls auf 16 kHz mono
    gemessen; fuer die Fundstellen des Daempfers zaehlt nur der Abstand zum
    Grund, und der bleibt.
    """
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst, GLib
    if not Gst.is_initialized():
        Gst.init(None)

    # Die Tonspur geht als WAV (16 kHz, mono, S16LE) in den Zwischenspeicher
    # und wird danach in EINEM Rutsch gelesen: Pegel je Rahmen und, wenn
    # verlangt, die Abtastwerte fuer den Sprachdetektor. Kein "level"-Element
    # mehr, keine 7000 Bus-Meldungen, kein appsink: jeder dieser Aufrufe
    # musste sich in der App den Interpreter mit der Oberflaeche teilen -
    # 57 s fuer 11 Minuten Ton statt 1 s (scan.log, 10.09.2026 nacht), am
    # Skript und im leeren Fenster nicht zu sehen.
    ordner = os.path.join(config.TEMP_SEGMENTS_CONTAINER, "verkehr")
    os.makedirs(ordner, exist_ok=True)
    wav = os.path.join(ordner, f"ton_{os.getpid()}_{threading.get_ident()}.wav")
    senke_text = (
        "audioconvert ! audioresample ! "
        "audio/x-raw,format=S16LE,channels=1,rate=16000,layout=interleaved "
        "! wavenc ! filesink sync=false location=\"%s\"" % wav.replace("\\", "/"))

    # Schneller Weg: den Demuxer direkt, NUR die Tonspur angeschlossen. Dann
    # liest qtdemux aus der Datei nur die Ton-Haeppchen und ueberspringt das
    # Bild - gemessen am 10.09.2026 nacht an einer 4-GB-GoPro-Datei: 1 s
    # statt 90 s, denn ueber playbin wird die ganze Datei gelesen, auch mit
    # flags=AUDIO. Geht der Aufbau schief (kein MP4/MOV, keine erste
    # Tonspur), bleibt der alte Weg ueber playbin.
    play = None
    ort = os.path.abspath(pfad).replace("\\", "/").replace('"', '\\"')
    if os.path.splitext(pfad)[1].lower() in (".mp4", ".mov", ".m4v", ".m4a"):
        try:
            play = Gst.parse_launch(
                f'filesrc location="{ort}" ! qtdemux name=d  d.audio_0 ! queue '
                f'! decodebin ! {senke_text}')
        except Exception:
            play = None
    weg = "qtdemux audio only"
    if play is None:
        weg = "playbin whole file"
        print(f"[AUDIO] {os.path.basename(pfad)}: reading the whole file (playbin)")
        senke = Gst.parse_bin_from_description(senke_text, True)
        play = Gst.ElementFactory.make("playbin", None)
        if play is None:
            raise RuntimeError("playbin is not available")
        play.set_property("uri", GLib.filename_to_uri(os.path.abspath(pfad), None))
        play.set_property("flags", 0x02)            # AUDIO - kein Bild dekodieren
        play.set_property("audio-sink", senke)
    # Erst PAUSED (Vorlauf), dann Laenge fragen und bei Bedarf in den
    # Bereich springen, dann PLAYING.
    if play.set_state(Gst.State.PAUSED) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("audio scan pipeline did not start")
    bus = play.get_bus()
    pegel = []
    dauer_ns = 0
    anfang_ns = 0
    spanne_ns = 0
    gemeldet = -1
    try:
        zustand = play.get_state(20 * Gst.SECOND)
        if zustand[0] == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("audio scan pipeline did not start")
        ok, dauer_ns = play.query_duration(Gst.Format.TIME)
        if not ok:
            dauer_ns = 0
        if von_s is not None or bis_s is not None:
            # Auf das Rahmenraster legen, damit die Rahmen der Bereiche
            # spaeter luecklos aneinanderpassen.
            anfang_ns = int(round(max(0.0, von_s or 0.0) / RAHMEN_S)) * int(RAHMEN_S * Gst.SECOND)
            ende_ns = -1 if bis_s is None else int(round(bis_s / RAHMEN_S)) * int(RAHMEN_S * Gst.SECOND)
            if dauer_ns > 0 and (ende_ns < 0 or ende_ns > dauer_ns):
                ende_ns = dauer_ns
            if not play.seek(1.0, Gst.Format.TIME,
                             Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                             Gst.SeekType.SET, anfang_ns,
                             Gst.SeekType.SET if ende_ns >= 0 else Gst.SeekType.NONE,
                             ende_ns if ende_ns >= 0 else 0):
                raise RuntimeError("audio scan: seek failed")
            spanne_ns = (ende_ns - anfang_ns) if ende_ns >= 0 else max(0, dauer_ns - anfang_ns)
        else:
            spanne_ns = dauer_ns
        if play.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("audio scan pipeline did not start")
        # Nur noch Fehler und Ende vom Bus; der Fortschritt kommt aus der
        # wachsenden WAV (32.000 Byte je Sekunde Ton).
        erwartet = spanne_ns / float(Gst.SECOND) * 32000.0
        while True:
            msg = bus.timed_pop_filtered(
                200 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if msg is None:
                if abbruch is not None and abbruch():
                    raise Abgebrochen()
                if fortschritt is not None and erwartet > 0:
                    try:
                        prozent = min(99, int(os.path.getsize(wav) * 100 / erwartet))
                    except OSError:
                        prozent = 0
                    if prozent > gemeldet:
                        gemeldet = prozent
                        fortschritt(prozent)
                continue
            if msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                raise RuntimeError(f"audio scan failed: {err.message}")
            break   # EOS
        play.set_state(Gst.State.NULL)
        pegel, daten = _pegel_aus_wav(wav)
        if proben is not None:
            proben.append(daten)
        if fortschritt is not None:
            fortschritt(100)
    finally:
        play.set_state(Gst.State.NULL)
        try:
            os.remove(wav)
        except OSError:
            pass
    return pegel, dauer_ns / float(Gst.SECOND), anfang_ns / float(Gst.SECOND)


def _perzentil(werte, p):
    w = sorted(werte)
    if not w:
        return -100.0
    k = (len(w) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(w) - 1)
    return w[f] + (w[c] - w[f]) * (k - f)


def grundgeraeusch(pegel):
    """Der laufende Grund je Rahmen: GRUND_PERZENTIL im mittigen Fenster.
    None, wo der Pegel nicht abgefahren ist (und ueberall, wo im Fenster
    kein einziger Wert liegt)."""
    halb = int(GRUND_FENSTER_S / RAHMEN_S / 2)
    n = len(pegel)
    aus = []
    for i in range(n):
        if pegel[i] is None:
            aus.append(None)
            continue
        werte = [p for p in pegel[max(0, i - halb):min(n, i + halb + 1)] if p is not None]
        aus.append(_perzentil(werte, GRUND_PERZENTIL) if werte else None)
    return aus


def _mittelwert(werte):
    """Mittel ohne None; None, wenn nichts da ist."""
    da = [w for w in werte if w is not None]
    return sum(da) / len(da) if da else None


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


#: Wie weit (Sekunden) vor und hinter einer Stelle nach freier Fuellung
#: gesucht wird.
FUELL_HORIZONT_S = 60.0


def _laeufe(frei, a, b):
    """Zusammenhaengende freie Laeufe in [a, b): [(anfang, laenge)]."""
    laeufe = []
    k = a
    while k < b:
        if frei[k]:
            j = k
            while j < b and frei[j]:
                j += 1
            laeufe.append((k, j - k))
            k = j
        else:
            k += 1
    return laeufe


def _fuellquelle(frei, s, e, bedarf):
    """(anfang, laenge) der Kopie fuer eine Stelle [s, e), oder (None, 0).

    Dahinter vor davor; erst ein Lauf in voller Laenge (der naechste an der
    Stelle), sonst der laengste freie Lauf auf beiden Seiten, mindestens
    FUELLUNG_MIN_S lang (wird dann wiederholt).
    """
    n = len(frei)
    horizont = int(round(FUELL_HORIZONT_S / RAHMEN_S))
    dahinter = _laeufe(frei, e, min(n, e + horizont))
    davor = _laeufe(frei, max(0, s - horizont), s)
    for anfang, laenge in dahinter:
        if laenge >= bedarf:
            return anfang, bedarf
    for anfang, laenge in reversed(davor):
        if laenge >= bedarf:
            return anfang + laenge - bedarf, bedarf
    mindest = int(round(FUELLUNG_MIN_S / RAHMEN_S))
    beste = None
    for seite in (dahinter, davor):
        for anfang, laenge in seite:
            if laenge >= mindest and (beste is None or laenge > beste[1]):
                beste = (anfang, laenge)
    return beste if beste else (None, 0)


def _anklang(pegel, ueber, s):
    """Anfang (Rahmen) einer Stelle, der Anfahrt folgend - das Gegenstueck
    zu _ausklang: rueckwaerts Sekunde fuer Sekunde, solange der Pegel zum
    Kern hin steigt (Toleranz AUSKLANG_TOLERANZ_DB, hoechstens
    AUSKLANG_MAX_S) und noch ueber dem Grund liegt (AUSKLANG_GRUND_DB); der
    Anfang ist die Sekunde des Minimums. Ohne echten Anstieg
    (AUSKLANG_MIN_DB) bleibt s. Bernd, 10.09.2026 spaet: "man hoert das
    Moped schon vorher, das wird nicht gedaempft"."""
    n = len(pegel)
    sek = int(round(1.0 / RAHMEN_S))
    if s - sek < 0:
        return s

    def mittel(werte, a):
        return _mittelwert(werte[a:min(n, a + sek)])

    start = mittel(pegel, s)
    if start is None:
        return s
    minimum, min_bei = start, s
    t = s
    grenze = max(0, s - int(round(AUSKLANG_MAX_S / RAHMEN_S)))
    while t - sek >= grenze:
        t -= sek
        u = mittel(ueber, t)
        if u is None or u < AUSKLANG_GRUND_DB:
            break
        m = mittel(pegel, t)
        if m is None or m > minimum + AUSKLANG_TOLERANZ_DB:
            break
        if m < minimum:
            minimum, min_bei = m, t
    if start - minimum < AUSKLANG_MIN_DB:
        return s
    return min_bei


def _ausklang(pegel, ueber, e):
    """Ende (Rahmen) einer Stelle, dem Abklingen folgend - siehe AUSKLANG_*.

    Der Pegel wird ueber eine Sekunde gemittelt und Sekunde fuer Sekunde
    verfolgt: solange er nicht mehr als AUSKLANG_TOLERANZ_DB ueber sein
    bisheriges Minimum steigt und noch ueber dem Grund liegt
    (AUSKLANG_GRUND_DB), laeuft die Stelle weiter; das Ende ist die Sekunde
    des Minimums. Ohne echten Abfall (AUSKLANG_MIN_DB) bleibt e.
    """
    n = len(pegel)
    sek = int(round(1.0 / RAHMEN_S))
    if e + sek > n:
        return e

    def mittel(werte, a):
        return _mittelwert(werte[a:min(n, a + sek)])

    start = mittel(pegel, max(0, e - sek))
    if start is None:
        return e
    minimum, min_bei = start, e
    t = e
    grenze = min(n - sek, e + int(round(AUSKLANG_MAX_S / RAHMEN_S)))
    while t + sek <= grenze:
        t += sek
        u = mittel(ueber, t)
        if u is None or u < AUSKLANG_GRUND_DB:
            break
        m = mittel(pegel, t)
        if m is None or m > minimum + AUSKLANG_TOLERANZ_DB:
            break
        if m < minimum:
            minimum, min_bei = m, t
    if start - minimum < AUSKLANG_MIN_DB:
        return e
    return min_bei


def ereignisse_finden(pegel, empfindlichkeit=EMPFINDLICHKEIT_VORGABE):
    """Die Berge im Pegel. Je Fund ein dict:

        von, bis     Sekunden in der Datei (Vielfache von RAHMEN_S)
        ueber        Liste: Pegel ueber Grund je Rahmen, dB
        fuellung     Sekunde, an der die ruhige Fuellstrecke beginnt, oder None
        fuellung_s   Laenge der Fuellstrecke in Sekunden

    empfindlichkeit 1-5 waehlt die Schwellen (SCHWELLEN).
    """
    an_db, aus_db = SCHWELLEN.get(int(empfindlichkeit), SCHWELLEN[EMPFINDLICHKEIT_VORGABE])
    grund = grundgeraeusch(pegel)
    # None, wo nicht abgefahren wurde: dort gibt es weder Berge noch Fuellung.
    ueber = [None if p is None or g is None else p - g for p, g in zip(pegel, grund)]
    n = len(ueber)
    ruhig = [u is not None and u <= aus_db for u in ueber]

    roh = []
    i = 0
    while i < n:
        if ueber[i] is not None and ueber[i] > an_db:
            j = i
            while j < n and ueber[j] is not None and ueber[j] > aus_db:
                j += 1
            if roh and (i - roh[-1][1]) * RAHMEN_S < LUECKE_S:
                roh[-1][1] = j
            else:
                roh.append([i, j])
            i = j
        else:
            i += 1

    # Kerne, die kein Fahrzeug mehr sind (MAX_STELLE_S), fallen weg.
    maxlen = int(round(MAX_STELLE_S / RAHMEN_S))
    alle_kerne = list(roh)
    kerne = [(s, e) for s, e in roh if e - s <= maxlen]

    # Ausklang, dann Vor- und Nachlauf; was sich dadurch beruehrt, wird
    # eins - solange das Ganze unter MAX_STELLE_S bleibt, sonst stossen die
    # Stellen nur aneinander.
    vor = int(round(VORLAUF_S / RAHMEN_S))
    nach = int(round(NACHLAUF_S / RAHMEN_S))
    breit = []
    luecke = int(round(LUECKE_S / RAHMEN_S))
    for s, e in kerne:
        s = _anklang(pegel, ueber, s)
        e = _ausklang(pegel, ueber, e)
        s, e = max(0, s - vor), min(n, e + nach)
        if breit and s - breit[-1][1] < luecke:
            if max(e, breit[-1][1]) - breit[-1][0] <= maxlen:
                breit[-1][1] = max(breit[-1][1], e)
                continue
            s = breit[-1][1]
            if e - s < vor:
                continue
        breit.append([s, e])
    roh = breit

    # Was als Fuellung taugt: kein Rahmen eines Kerns (auch der verworfenen
    # langen), und nichts deutlich ueber der Einschaltschwelle. Die
    # Vor- und Nachlaeufe selbst sind leise genug.
    frei = [u is not None and u <= an_db + 2.0 for u in ueber]
    for s0, e0 in alle_kerne:
        for k in range(s0, e0):
            frei[k] = False

    funde = []
    rand = int(round(RAMPE_S / RAHMEN_S))
    for s, e in roh:
        if (e - s) * RAHMEN_S < MIN_S:
            continue
        # Fuellung wie Kinotomo ("blend": eine Kopie des Tons neben der
        # Stelle, am Stueck, plus RAMPE_S an beiden Kanten) - nur die WAHL
        # der Kopie ist die eines Menschen, nicht die Vorgabe "davor":
        #   * die Kopie darf kein anderes Fahrzeug enthalten (Berns Vehicel,
        #     10.09.2026 spaet: die Kopie von 130 s frueher trug ein Moped,
        #     "als wuerde er nochmal vorbeifahren"), also nur Rahmen, die in
        #     keiner Stelle liegen und nicht ueber der Einschaltschwelle;
        #   * DAHINTER geht vor DAVOR: davor liegt die Anfahrt des Fahrzeugs
        #     und bei Bernd das Piepsen des Radars, dahinter ist die Strasse
        #     frei;
        #   * am Stueck, so lang wie noetig; reicht es nirgends, das laengste
        #     freie Stueck, wiederholt (fuellstuecke, eine Naht je Runde).
        bedarf = (e - s) + 2 * rand
        q, laenge = _fuellquelle(frei, s, e, bedarf)
        if q is not None:
            bedarf = laenge
        if q is None:
            # Weder davor noch dahinter genug Platz (Dateianfang und -ende
            # nah beieinander): der alte Weg, notfalls gestueckelt.
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
            "ueber": [0.0 if u is None else round(u, 1) for u in ueber[s:e]],
            "fuellung": None if q is None else round(q * RAHMEN_S, 3),
            "fuellung_s": 0.0 if q is None else round(bedarf * RAHMEN_S, 3),
            # Pegelangleich der Fuellung in dB: eine Kopie von weiter weg
            # (andere Strasse, anderer Wind) ist sonst lauter oder leiser
            # als die Umgebung der Stelle - Berns Vehicel: Kopie von 583 s,
            # 8 dB lauter als die ruhige Fahrt bei 430 s. Ziel ist der
            # Grund an der Stelle; begrenzt, damit nichts Absurdes entsteht.
            "fuellung_db": 0.0 if q is None else round(max(-20.0, min(6.0,
                (_mittelwert(grund[s:e]) or 0.0) - (_mittelwert(pegel[q:q + bedarf]) or 0.0))), 1),
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
    # Nur der Pegel liegt im Zwischenspeicher; die Berge werden beim Lesen
    # mit der gewaehlten Empfindlichkeit gerechnet (0,1 s), deshalb stehen
    # die Schwellen nicht im Schluessel.
    kennung += f"|v{VERSION}|{RAHMEN_S}"
    name = hashlib.sha1(kennung.encode("utf-8")).hexdigest()[:20]
    return os.path.join(config.TEMP_SEGMENTS_CONTAINER, "verkehr", name + ".json")


def aus_cache(pfad):
    """Nur der Zwischenspeicher, ohne Suchlauf - fuer die Tonspur der
    Zeitleiste, die zeigen soll, was da ist, ohne minutenlang zu rechnen.
    Rueckgabe wie analyse() oder None."""
    try:
        with open(_cache_datei(pfad), "r", encoding="utf-8") as f:
            daten = json.load(f)
        if daten.get("version") == VERSION and "pegel" in daten:
            return daten
    except (OSError, ValueError):
        pass
    return None


#: Rand um jeden gebrauchten Bereich, der mit abgefahren wird: das halbe
#: Fenster des Grundgeraeuschs plus der Suchweg fuer die Fuellung.
SCAN_RAND_S = GRUND_FENSTER_S / 2 + 60.0


def _bereiche_vereinen(bereiche):
    """[(von, bis)] sortiert und verschmolzen."""
    liste = sorted((float(a), float(b)) for a, b in bereiche if b > a)
    aus = []
    for a, b in liste:
        if aus and a <= aus[-1][1] + RAHMEN_S:
            aus[-1][1] = max(aus[-1][1], b)
        else:
            aus.append([a, b])
    return [(a, b) for a, b in aus]


def _bereiche_abziehen(gebraucht, vorhanden):
    """Was von 'gebraucht' nicht in 'vorhanden' liegt: [(von, bis)]."""
    rest = []
    for a, b in gebraucht:
        stuecke = [(a, b)]
        for va, vb in vorhanden:
            neu = []
            for sa, sb in stuecke:
                if vb <= sa or va >= sb:
                    neu.append((sa, sb))
                    continue
                if sa < va:
                    neu.append((sa, va))
                if vb < sb:
                    neu.append((vb, sb))
            stuecke = neu
        rest.extend(s for s in stuecke if s[1] - s[0] >= RAHMEN_S)
    return _bereiche_vereinen(rest)


def _cache_lesen(pfad):
    try:
        with open(_cache_datei(pfad), "r", encoding="utf-8") as f:
            daten = json.load(f)
        if daten.get("version") == VERSION and "pegel" in daten:
            return daten
    except (OSError, ValueError):
        pass
    return None


def fehlende_bereiche(pfad, bereiche=None, mit_sprache=False):
    """Welche Teile von 'bereiche' (None: die ganze Datei) noch nicht im
    Zwischenspeicher liegen: [(von, bis)]. Leer heisst: nichts zu tun.
    mit_sprache: die Sprachwerte werden auch gebraucht (Detect) - ein
    Eintrag ohne sie zaehlt dann als fehlend."""
    daten = _cache_lesen(pfad)
    if daten is None:
        return [(0.0, float("inf"))] if bereiche is None else _bereiche_vereinen(bereiche)
    if mit_sprache and daten.get("sprache") is None:
        # Nur der Pegel liegt da (Kurve); fuer Detect wird neu abgefahren.
        vorhanden = []
    else:
        vorhanden = [tuple(b) for b in daten.get("bereiche") or []]
    dauer = float(daten.get("dauer") or 0)
    gebraucht = [(0.0, dauer)] if bereiche is None else \
        [(max(0.0, a), min(dauer, b) if dauer > 0 else b) for a, b in _bereiche_vereinen(bereiche)]
    return _bereiche_abziehen(gebraucht, vorhanden)


def analyse(pfad, log=None, fortschritt=None, abbruch=None, name=None,
            empfindlichkeit=EMPFINDLICHKEIT_VORGABE, bereiche=None,
            mit_sprache=False):
    """Pegelverlauf (und auf Wunsch Sprachwerte) einer Datei, aus dem
    Zwischenspeicher oder frisch.

    bereiche: [(von_s, bis_s)] - nur diese Teile der Datei werden gebraucht
    (der Aufrufer gibt die behaltenen Bereiche, der Rand SCAN_RAND_S kommt
    hier dazu). None: die ganze Datei. Abgefahren wird nur, was im
    Zwischenspeicher noch fehlt; der Eintrag waechst mit jedem Schnitt.
    name: wie die Datei im Protokoll heissen soll - beim Voice Remover wird
    die WAV ohne Stimme abgefahren, genannt werden soll aber die Quelle.
    empfindlichkeit: 1-5, siehe SCHWELLEN - die Berge werden immer frisch
    aus dem gespeicherten Pegel gerechnet, ein Wechsel kostet keinen Scan.

    Rueckgabe: {"dauer": Sekunden, "ereignisse": [siehe ereignisse_finden],
    "pegel": [...], "sprache": [...] oder None, "bereiche": [[von, bis]]}.
    pegel und sprache decken die ganze Datei ab; wo nicht abgefahren
    wurde, steht None.
    """
    log = log or (lambda text: None)
    name = name or os.path.basename(pfad)
    from core import sprache
    # Sprachwerte nur, wenn sie verlangt sind (Detect) und der Detektor da
    # ist. Die Kurve der Zeitleiste braucht nur den Pegel (Bernd,
    # 10.09.2026 nacht: "wir malen doch erst mal nur die Kurve").
    mit_sprache = bool(mit_sprache) and sprache.verfuegbar()[0]

    gebraucht = None
    if bereiche is not None:
        gebraucht = _bereiche_vereinen(
            [(max(0.0, a - SCAN_RAND_S), b + SCAN_RAND_S) for a, b in bereiche])
    fehlt = fehlende_bereiche(pfad, gebraucht, mit_sprache)
    daten = _cache_lesen(pfad)
    if daten is not None and daten.get("sprache") is None and mit_sprache:
        daten = None            # bisher nur Pegel, jetzt mit Detektor neu

    if fehlt:
        for von, bis in fehlt:
            ganz = von <= 0.0 and bis == float("inf")
            log(f"[AUDIO] {name}: reading the audio track"
                + ("..." if ganz else f" {von:.0f}-{bis:.0f}s..."))
            proben = [] if mit_sprache else None
            pegel, dauer_s, anfang_s = pegel_messen(
                pfad, fortschritt, abbruch, proben,
                None if ganz else von, None if ganz else bis)
            rahmen = int(round(dauer_s / RAHMEN_S))
            if daten is None:
                daten = {"version": VERSION, "dauer": round(dauer_s, 3),
                         "pegel": [None] * rahmen,
                         "sprache": [None] * int(dauer_s / sprache.SCHRITT_S + 1) if mit_sprache else None,
                         "bereiche": []}
            k0 = int(round(anfang_s / RAHMEN_S))
            for k, p in enumerate(pegel):
                if k0 + k < len(daten["pegel"]):
                    daten["pegel"][k0 + k] = round(p, 1)
            if mit_sprache and daten.get("sprache") is not None:
                try:
                    werte = sprache.wahrscheinlichkeiten(proben)
                    j0 = int(round(anfang_s / sprache.SCHRITT_S))
                    for j, w in enumerate(werte):
                        if j0 + j < len(daten["sprache"]):
                            daten["sprache"][j0 + j] = round(w, 2)
                except Exception as exc:
                    log(f"[AUDIO] {name}: speech detector failed: {exc}")
            ende = anfang_s + len(pegel) * RAHMEN_S
            daten["bereiche"] = [list(b) for b in _bereiche_vereinen(
                [tuple(b) for b in daten["bereiche"]] + [(anfang_s, ende)])]
        try:
            datei = _cache_datei(pfad)
            os.makedirs(os.path.dirname(datei), exist_ok=True)
            with open(datei, "w", encoding="utf-8") as f:
                json.dump(daten, f)
        except OSError as exc:
            log(f"[AUDIO] cache not written: {exc}")
        gescannt = sum(b - a for a, b in daten["bereiche"])
        log(f"[AUDIO] {name}: {gescannt:.0f}s of {daten['dauer']:.0f}s read")

    # Kein Fahrzeugsucher mehr (10.09.2026 nacht): die Stellen setzt der
    # Nutzer. "ereignisse" bleibt als leere Liste fuer alte Aufrufer.
    daten["ereignisse"] = []
    return daten


# ---------------------------------------------------------------------------
# Behandlung: Kurven fuer die Timeline
# ---------------------------------------------------------------------------

#: Fuellung einer von Hand gesetzten Stelle (Kinotomo "blend"): die Kopie
#: von direkt davor, von direkt dahinter, oder keine ("none" = nur
#: absenken, Kinotomo "volume added" 0). Der Nutzer waehlt je Stelle und
#: hoert es vorher an - der Sucher entscheidet seit dem 10.09.2026 nacht
#: nichts mehr (Bernd: "das koennen wir nicht ermitteln, ich kann es
#: hoeren, du kannst nur messen").
FUELLUNGEN = ("before", "after", "none")
FUELLUNG_VORGABE = "before"


def stelle_von_hand(von_s, bis_s, fuellung=FUELLUNG_VORGABE, dauer_s=None):
    """Eine vom Nutzer gesetzte Fahrzeugstelle als Ereignis, wie es
    daempfung() und fuellstuecke() brauchen.

    von_s/bis_s in Sekunden der Datei. fuellung: siehe FUELLUNGEN. Die
    Kopie ist so lang wie die Stelle plus RAMPE_S an beiden Kanten und
    liegt am Stueck direkt davor bzw. dahinter; fehlt davor der Platz
    (Stelle am Dateianfang), rueckt sie an den Anfang und ragt in die Stelle
    hinein, wo die Fuellung ohnehin ausblendet - dahinter entsprechend am
    Dateiende, wenn dauer_s bekannt ist. Kein Pegelangleich: die Kopie
    kommt aus derselben Umgebung.
    """
    von = round(max(0.0, float(von_s)) / RAHMEN_S) * RAHMEN_S
    bis = round(float(bis_s) / RAHMEN_S) * RAHMEN_S
    if bis <= von:
        bis = von + RAHMEN_S
    laenge = bis - von
    bedarf = laenge + 2 * RAMPE_S
    q = None
    if fuellung == "before":
        q = max(0.0, von - bedarf)
    elif fuellung == "after":
        q = bis
        if dauer_s and q + bedarf > dauer_s:
            q = max(0.0, float(dauer_s) - bedarf)
    return {
        "von": round(von, 3),
        "bis": round(bis, 3),
        "ueber": [],
        "fuellung": None if q is None else round(q, 3),
        "fuellung_s": 0.0 if q is None else round(bedarf, 3),
        "fuellung_db": 0.0,
        "fuellart": fuellung if fuellung in FUELLUNGEN else "none",
    }


def daempfung(ereignis, daempfer_db):
    """Lautstaerkekurve des Originals an dieser Fundstelle.

    Rueckgabe: [(Sekunde in der Datei, Faktor)], stueckweise linear, Faktor
    1.0 ausserhalb. Ueber die ganze Fundstelle -daempfer_db, wie Kinotomo
    (Faktor "volume original", ohne Blick auf den Grund); danach ein
    gleitender Mittelwert ueber RAMPE_S, der die Rampen an den Kanten
    ergibt.
    """
    rahmen = int(round((ereignis["bis"] - ereignis["von"]) / RAHMEN_S))
    if rahmen <= 0 or daempfer_db <= 0:
        return []
    rand = max(1, int(round(RAMPE_S / RAHMEN_S)))
    db = [0.0] * rand
    db += [-float(daempfer_db)] * rahmen
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


def fuellpegel(kurve, daempfer_db, anteil=FUELL_ANTEIL_VORGABE, angleich_db=0.0):
    """Pegelkurve der Fuellung zu einer Daempfungskurve: [(Sekunde, Faktor)].

    Auf dem Plateau der Daempfung steht die Fuellung auf anteil/100
    (Kinotomo "volume added") mal dem Pegelangleich (ereignis["fuellung_db"]),
    an den Rampen faehrt sie im selben Verhaeltnis ein und aus wie das
    Original hinunter - so ist an jeder Stelle der Rampe Original + Fuellung
    zusammen etwa gleich laut.
    """
    tief = 10 ** (-float(daempfer_db) / 20.0)
    hub = 1.0 - tief
    faktor = max(0.0, min(1.0, float(anteil) / 100.0)) * 10 ** (float(angleich_db) / 20.0)
    if hub <= 0:
        return [(t, 0.0) for t, _v in kurve]
    return [(t, faktor * max(0.0, min(1.0, (1.0 - v) / hub))) for t, v in kurve]


def gegenstueck(kurve):
    """1 - Faktor (bis 10.09.2026 der Fuellpegel; heute fuellpegel())."""
    return [(t, max(0.0, 1.0 - v)) for t, v in kurve]
