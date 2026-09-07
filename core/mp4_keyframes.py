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

# core/mp4_keyframes.py
#
# Schnellweg zum Ermitteln der Keyframe-Zeiten einer MP4/MOV-Datei.
#
# Warum ueberhaupt:
# Der uebliche Weg ("ffprobe -skip_frame nokey -show_entries frame=...") laesst
# den Decoder ueber JEDES Paket der Datei laufen. Gemessen an GX010089.MP4
# (11,9 GB, 4K HEVC) mit geleertem Dateicache: 3 min 25 s. Die Keyframe-Liste
# steht in der Datei aber bereits als fertige Tabelle - der "stss"-Box, die
# ffmpeg selbst zum Springen benutzt. Sie zu lesen dauerte bei denselben
# Dateien 0,006 s bzw. 0,391 s, und die Werte waren mit dem ffprobe-Ergebnis
# auf die Mikrosekunde identisch (2112 von 2112 Keyframes, beide Dateien).
#
# WICHTIG - der alte Weg hat immer Vorrang:
# Diese Funktion gibt bei der kleinsten Unklarheit None zurueck. Sie ist ein
# Beschleuniger fuer den eindeutigen Fall, kein Ersatz. Wer sie aufruft, MUSS
# bei None den bisherigen ffprobe-Lauf ausfuehren.

import os
import struct


# Groesse, ab der wir eine Box fuer unplausibel halten (Schutz vor kaputten
# Dateien, die uns sonst in eine riesige Allokation laufen lassen).
_MAX_TABLE_ENTRIES = 50_000_000


def _iter_boxes(f, start, end):
    """Laeuft die Boxen zwischen start und end ab und liefert (typ, inhalt_von, inhalt_bis)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return
        size, typ = struct.unpack(">I4s", hdr)
        head = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        try:
            name = typ.decode("ascii")
        except UnicodeDecodeError:
            return
        yield name, pos + head, pos + size
        pos += size


def _find(f, start, end, path):
    """Sucht einen Box-Pfad, z. B. ["mdia", "minf", "stbl"]. Liefert (von, bis) oder None."""
    for name, bs, be in _iter_boxes(f, start, end):
        if name != path[0]:
            continue
        if len(path) == 1:
            return bs, be
        found = _find(f, bs, be, path[1:])
        if found:
            return found
    return None


def _read_u32(f, count):
    data = f.read(4 * count)
    if len(data) < 4 * count:
        raise ValueError("Tabelle unvollstaendig")
    return struct.unpack(">%dI" % count, data)


def _elst_is_harmless(f, trak_start, trak_end):
    """
    True, wenn es keine Edit-List gibt oder sie nichts verschiebt.

    Eine Edit-List kann den Anfang der Spur verschieben oder eine Luecke
    einfuegen. Dann stimmen die Zeiten aus stts nicht mehr mit dem ueberein,
    was ffprobe meldet - in dem Fall geben wir auf.
    """
    elst = _find(f, trak_start, trak_end, ["edts", "elst"])
    if not elst:
        return True
    start, end = elst
    f.seek(start)
    head = f.read(8)
    if len(head) < 8:
        return False
    version = head[0]
    count = struct.unpack(">I", head[4:8])[0]
    if count != 1:
        return False
    entry_size = 20 if version == 1 else 12
    if start + 8 + entry_size > end:
        return False
    entry = f.read(entry_size)
    if version == 1:
        media_time = struct.unpack(">q", entry[8:16])[0]
    else:
        media_time = struct.unpack(">i", entry[4:8])[0]
    return media_time == 0


def keyframe_times_from_index(path):
    """
    Liefert die Keyframe-Zeitpunkte in Sekunden - oder None.

    None bedeutet: nicht eindeutig entscheidbar, bitte den bisherigen
    ffprobe-Weg benutzen. Das ist der Fall bei

      - allem, was keine MP4/MOV-Datei mit "ftyp" am Anfang ist,
      - fragmentierten Dateien ("moof"/"mvex"), deren Tabellen verteilt sind,
      - fehlender "stss"-Box (dann ist jedes Bild ein Keyframe - der alte Weg
        liefert das korrekt, wir wollen hier nicht raten),
      - vorhandener "ctts"-Box (B-Frames: Dekodier- und Anzeigereihenfolge
        weichen ab, unsere Rechnung waere falsch),
      - einer Edit-List, die etwas verschiebt,
      - jedem Fehler beim Lesen und jeder unplausiblen Liste.
    """
    try:
        if not path or not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_end = f.tell()
            if file_end < 16:
                return None

            # 1) Ueberhaupt eine MP4/MOV? Und nicht fragmentiert?
            top = list(_iter_boxes(f, 0, file_end))
            names = [n for n, _, _ in top]
            if not names or names[0] != "ftyp":
                return None
            if "moof" in names or "sidx" in names:
                return None
            moov = None
            for name, bs, be in top:
                if name == "moov":
                    moov = (bs, be)
                    break
            if not moov:
                return None
            if _find(f, moov[0], moov[1], ["mvex"]):
                return None

            # 2) Erste Video-Spur suchen - das ist die, die "-select_streams v:0" nimmt.
            for name, ts, te in _iter_boxes(f, moov[0], moov[1]):
                if name != "trak":
                    continue
                hdlr = _find(f, ts, te, ["mdia", "hdlr"])
                if not hdlr:
                    continue
                f.seek(hdlr[0] + 8)
                if f.read(4) != b"vide":
                    continue

                if not _elst_is_harmless(f, ts, te):
                    return None

                mdhd = _find(f, ts, te, ["mdia", "mdhd"])
                if not mdhd:
                    return None
                f.seek(mdhd[0])
                version = f.read(4)[0]
                # mdhd: version+flags(4) | v0: creation(4) modification(4) timescale(4) duration(4)
                #                        | v1: creation(8) modification(8) timescale(4) duration(8)
                if version == 1:
                    body = f.read(28)
                    if len(body) < 28:
                        return None
                    timescale = struct.unpack(">I", body[16:20])[0]
                    track_dur = struct.unpack(">Q", body[20:28])[0]
                else:
                    body = f.read(16)
                    if len(body) < 16:
                        return None
                    timescale = struct.unpack(">I", body[8:12])[0]
                    track_dur = struct.unpack(">I", body[12:16])[0]
                if timescale <= 0:
                    return None

                stbl = _find(f, ts, te, ["mdia", "minf", "stbl"])
                if not stbl:
                    return None
                if _find(f, stbl[0], stbl[1], ["ctts"]):
                    return None
                stss = _find(f, stbl[0], stbl[1], ["stss"])
                stts = _find(f, stbl[0], stbl[1], ["stts"])
                if not stss or not stts:
                    return None

                # 3) stss: Nummern der Sync-Samples (1-basiert)
                f.seek(stss[0] + 4)
                sync_count = struct.unpack(">I", f.read(4))[0]
                if sync_count <= 0 or sync_count > _MAX_TABLE_ENTRIES:
                    return None
                sync = _read_u32(f, sync_count)

                # 4) stts: Sample-Nummer -> Dekodierzeit, als Laufweiten gespeichert
                f.seek(stts[0] + 4)
                run_count = struct.unpack(">I", f.read(4))[0]
                if run_count <= 0 or run_count > _MAX_TABLE_ENTRIES:
                    return None
                raw = _read_u32(f, 2 * run_count)
                runs = []
                first_sample = 0
                elapsed = 0
                for i in range(run_count):
                    cnt, delta = raw[2 * i], raw[2 * i + 1]
                    runs.append((first_sample, cnt, delta, elapsed))
                    first_sample += cnt
                    elapsed += cnt * delta
                total_samples = first_sample

                times = []
                run_idx = 0
                for sample_no in sync:
                    idx = sample_no - 1
                    if idx < 0 or idx >= total_samples:
                        return None
                    # sync ist aufsteigend, deshalb reicht ein mitlaufender Zeiger
                    while run_idx < run_count:
                        s0, cnt, delta, t0 = runs[run_idx]
                        if s0 <= idx < s0 + cnt:
                            times.append((t0 + (idx - s0) * delta) / timescale)
                            break
                        run_idx += 1
                    else:
                        return None

                if not _looks_sane(times, track_dur / timescale if track_dur else None):
                    return None
                return times

            return None
    except Exception as e:
        print(f"[INFO] Keyframe index of {os.path.basename(str(path))} not readable "
              f"({e}) - using ffprobe.")
        return None


def _looks_sane(times, track_seconds):
    """Letzter Plausibilitaetstest, bevor wir das Ergebnis benutzen."""
    if not times:
        return False
    if times[0] < 0:
        return False
    for i in range(1, len(times)):
        if times[i] <= times[i - 1]:
            return False
    if track_seconds:
        # eine Sekunde Toleranz fuer Rundung und ein letztes Sample
        if times[-1] > track_seconds + 1.0:
            return False
    return True


def video_duration_from_container(path):
    """Laenge der VIDEOSPUR in Sekunden, direkt aus der MP4/MOV gelesen.

    Warum nicht die Gesamtlaenge des Containers nehmen: die steht in der
    'mvhd'-Box in der Zeitbasis des Films, und die ist oft nur 1000 (also
    Millisekunden). GStreamers Discoverer liefert genau diesen gerundeten Wert
    - gemessen an 1min_Nr2.mp4: 60.834 statt 60.833333, ein Rundungsfehler von
    0,667 ms. Die 'mdhd'-Box der Videospur haelt Laenge und Zeitbasis der Spur
    selbst (hier 15360), und daraus ergibt sich die Zahl exakt. Genau diesen
    Wert meldet auch ffprobe.

    Liefert None, wenn die Datei kein MP4/MOV ist, keine Videospur hat oder
    irgendetwas unklar bleibt. Wer die Funktion aufruft, MUSS diesen Fall
    abfangen und den bisherigen Weg gehen - so wie bei
    keyframe_times_from_index() auch.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        groesse = os.path.getsize(path)
        with open(path, "rb") as f:
            moov = _find(f, 0, groesse, ["moov"])
            if not moov:
                return None
            for name, ts, te in _iter_boxes(f, moov[0], moov[1]):
                if name != "trak":
                    continue
                hdlr = _find(f, ts, te, ["mdia", "hdlr"])
                if not hdlr:
                    continue
                f.seek(hdlr[0] + 8)          # version/flags, vorbehalten
                if f.read(4) != b"vide":
                    continue
                mdhd = _find(f, ts, te, ["mdia", "mdhd"])
                if not mdhd:
                    return None
                f.seek(mdhd[0])
                version = struct.unpack(">B", f.read(1))[0]
                f.read(3)                    # flags
                if version == 1:
                    f.read(16)               # Erstell- und Aenderungszeit
                    zeitbasis = struct.unpack(">I", f.read(4))[0]
                    dauer = struct.unpack(">Q", f.read(8))[0]
                else:
                    f.read(8)
                    zeitbasis = struct.unpack(">I", f.read(4))[0]
                    dauer = struct.unpack(">I", f.read(4))[0]
                if not zeitbasis or not dauer:
                    return None
                if dauer in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                    return None              # unbekannte Laenge
                return dauer / float(zeitbasis)
    except Exception:
        return None
    return None


def _stbl_tabellen(f, stbl_von, stbl_bis):
    """Liest stsz, stsc und stco/co64 aus einer Sample-Tabelle.

    Liefert (groessen, stsc, versaetze) oder None. `groessen` ist die Liste der
    Sample-Groessen, `stsc` eine Liste (erster_chunk, samples_je_chunk) und
    `versaetze` die Dateipositionen der Chunks.
    """
    stsz = _find(f, stbl_von, stbl_bis, ["stsz"])
    if not stsz:
        return None
    f.seek(stsz[0] + 4)                         # version/flags
    einheitlich, anzahl = struct.unpack(">II", f.read(8))
    if anzahl <= 0:
        return None
    if einheitlich:
        groessen = [einheitlich] * anzahl
    else:
        groessen = list(_read_u32(f, anzahl))

    stsc = _find(f, stbl_von, stbl_bis, ["stsc"])
    if not stsc:
        return None
    f.seek(stsc[0] + 4)
    (n,) = struct.unpack(">I", f.read(4))
    tabelle = []
    for _ in range(n):
        erster, je_chunk, _beschreibung = struct.unpack(">III", f.read(12))
        tabelle.append((erster, je_chunk))
    if not tabelle:
        return None

    box = _find(f, stbl_von, stbl_bis, ["stco"])
    breit = False
    if not box:
        box = _find(f, stbl_von, stbl_bis, ["co64"])
        breit = True
    if not box:
        return None
    f.seek(box[0] + 4)
    (n,) = struct.unpack(">I", f.read(4))
    if breit:
        roh = f.read(8 * n)
        if len(roh) < 8 * n:
            return None
        versaetze = list(struct.unpack(">%dQ" % n, roh))
    else:
        versaetze = list(_read_u32(f, n))
    if not versaetze:
        return None
    return groessen, tabelle, versaetze


def _sample_positionen(groessen, stsc, versaetze):
    """Rechnet aus den Tabellen die (position, groesse) jedes Samples aus."""
    stellen = []
    index = 0
    anzahl_chunks = len(versaetze)
    for i, (erster, je_chunk) in enumerate(stsc):
        letzter = (stsc[i + 1][0] - 1) if i + 1 < len(stsc) else anzahl_chunks
        for chunk in range(erster, letzter + 1):
            if chunk < 1 or chunk > anzahl_chunks:
                return None
            pos = versaetze[chunk - 1]
            for _ in range(je_chunk):
                if index >= len(groessen):
                    return stellen
                stellen.append((pos, groessen[index]))
                pos += groessen[index]
                index += 1
    return stellen


def track_data_from_container(path, formatcode=b"gpmd"):
    """Rohdaten einer Datenspur, direkt aus der MP4/MOV gelesen.

    Ersetzt den Umweg ueber

        ffprobe -show_streams            (welcher Strom ist "gpmd"?)
        ffmpeg -codec copy -map 0:N -f rawvideo

    Der ffmpeg-Aufruf dekodiert nichts: er nimmt die Samples der Spur, wie sie
    im Container liegen, und schreibt sie hintereinander in eine Datei. Genau
    das passiert hier - nur ohne Prozessstart und ohne Zwischendatei. Gesucht
    wird die Spur, deren Eintrag in "stsd" den uebergebenen Formatcode traegt;
    bei GoPro-Telemetrie ist das "gpmd".

    Liefert die Rohdaten als bytes, oder None, wenn irgendetwas unklar bleibt.
    Wer die Funktion aufruft, MUSS diesen Fall abfangen und den bisherigen Weg
    gehen - so wie bei keyframe_times_from_index() auch.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        groesse = os.path.getsize(path)
        with open(path, "rb") as f:
            moov = _find(f, 0, groesse, ["moov"])
            if not moov:
                return None
            for name, ts, te in _iter_boxes(f, moov[0], moov[1]):
                if name != "trak":
                    continue
                stbl = _find(f, ts, te, ["mdia", "minf", "stbl"])
                if not stbl:
                    continue
                stsd = _find(f, stbl[0], stbl[1], ["stsd"])
                if not stsd:
                    continue
                f.seek(stsd[0] + 4)
                (eintraege,) = struct.unpack(">I", f.read(4))
                passt = False
                pos = stsd[0] + 8
                for _ in range(eintraege):
                    if pos + 8 > stsd[1]:
                        break
                    f.seek(pos)
                    laenge, code = struct.unpack(">I4s", f.read(8))
                    if code == formatcode:
                        passt = True
                        break
                    if laenge < 8:
                        break
                    pos += laenge
                if not passt:
                    continue

                tabellen = _stbl_tabellen(f, stbl[0], stbl[1])
                if not tabellen:
                    return None
                stellen = _sample_positionen(*tabellen)
                if not stellen:
                    return None
                # Aneinandergrenzende Samples in einem Zug lesen. Sie liegen
                # innerhalb eines Chunks hintereinander, und einzeln gelesen
                # waeren es bei einer GoPro-Datei rund 200.000 Zugriffe -
                # gemessen 12,3 s gegen 1,0 s zusammengefasst.
                laeufe = []
                for versatz, laenge in stellen:
                    if versatz < 0 or laenge < 0 or versatz + laenge > groesse:
                        return None
                    if laeufe and laeufe[-1][0] + laeufe[-1][1] == versatz:
                        laeufe[-1][1] += laenge
                    else:
                        laeufe.append([versatz, laenge])
                stuecke = []
                for versatz, laenge in laeufe:
                    f.seek(versatz)
                    daten = f.read(laenge)
                    if len(daten) != laenge:
                        return None
                    stuecke.append(daten)
                return b"".join(stuecke)
    except Exception:
        return None
    return None


def creation_time_from_container(path):
    """Aufnahmezeitpunkt aus der "mvhd"-Box, als datetime mit Zeitzone UTC.

    Ersetzt "ffprobe -show_format" fuer das Feld creation_time. Im Container
    steht dort die Sekundenzahl seit dem 01.01.1904, und ffprobe legt sie
    genauso aus. An einer GoPro-Datei geprueft: ffprobe, GStreamer und diese
    Funktion melden uebereinstimmend 2025-09-19T07:11:56Z; bei einer Datei
    ohne Eintrag liefern alle drei nichts.

    Liefert None, wenn nichts hinterlegt ist oder die Datei nicht gelesen
    werden kann - dann geht der Aufrufer den bisherigen Weg.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        groesse = os.path.getsize(path)
        with open(path, "rb") as f:
            moov = _find(f, 0, groesse, ["moov"])
            if not moov:
                return None
            mvhd = _find(f, moov[0], moov[1], ["mvhd"])
            if not mvhd:
                return None
            f.seek(mvhd[0])
            version = struct.unpack(">B", f.read(1))[0]
            f.read(3)                                    # flags
            if version == 1:
                sekunden = struct.unpack(">Q", f.read(8))[0]
            else:
                sekunden = struct.unpack(">I", f.read(4))[0]
        if not sekunden:
            return None
        from datetime import datetime, timedelta, timezone
        zeit = (datetime(1904, 1, 1, tzinfo=timezone.utc)
                + timedelta(seconds=int(sekunden)))
        # Unplausible Werte lieber gar nicht melden, als eine falsche
        # Startzeit in die GPX-Kopplung zu tragen.
        if not (2000 <= zeit.year <= 2100):
            return None
        return zeit
    except Exception:
        return None
