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
Messung, Stufe 0 des 360-Editor-Plans (doc/Plan_360_Editor.md):

    Lassen sich die Uniforms des 360-Shaders JE BILD setzen - in der
    Vorschau und im Export - ohne Tempoverlust?

Der Weg, der hier gemessen wird: eine Buffer-Probe am Sink-Pad des glshader
in der Effekt-Bin. Sie liest den Zeitstempel des Buffers, rechnet daraus den
Blick und setzt die Uniforms, bevor der Shader das Bild rechnet.

Aufruf im venv, aus dem Projektordner:

    python tools/mess_360_keyframes.py [quelle.mp4] [ausgabeordner]

Vorgabe: 360_test_1920x960.mp4 aus dem Projektordner, Ausgabe nach
%TEMP%/kvr_mess_360. Laeuft rund eine Minute. Aendert nichts am Programm.

Gemessen wird, in dieser Reihenfolge (Nummern wie im Plan, Abschnitt 2):

  1. Zeitachse des Buffer-Zeitstempels in der Probe. Dafuer liegen ZWEI
     Clips auf der Timeline: Clip A 0..2 s (In-Point 0), Clip B ab 2 s mit
     In-Point 3 s. Die Probe haengt an B und gibt PTS, Segmentbeginn,
     Running-Time und Stream-Time aus.
     ERGEBNIS (12.09.2026): der PTS ist die QUELLZEIT der Datei (3,067 bis
     13,033 s), das Segment beginnt beim ersten gelieferten Bild, die
     Running-Time ist clip-lokal. Vor dem eigentlichen Segment kommen vier
     Vorlauf-Buffer vom Dateianfang (eigenes Segment ab 0,067 s), die
     nicht im Bild landen. Siehe Probe._timeline_zeit.
  2. Darf der Streaming-Thread die Property setzen? Zwei Varianten:
       A  ueber GES: effekt.set_child_property("uniforms", ...)
       B  direkt am glshader-Element: shader.set_property("uniforms", ...)
     Bus-Warnungen und -Fehler werden gezaehlt; ein Haenger faellt an der
     Frist auf.
  3. Greift der Wert fuer DIESEN Buffer oder erst fuer den naechsten?
     Sprungtest auf einer Ein-Clip-Timeline (Ausgabe-PTS = Quell-PTS):
     yaw = 0 bis 5,0 s, danach yaw = 45 Grad. Gesucht wird das erste
     Ausgabebild, das sich stark vom Vorgaenger unterscheidet; sein PTS
     sagt, ob der Wert schon fuer den Buffer bei 5,000 s galt.
     (Nicht 180 Grad: die Testtafel im Testclip zeigt dort "BACK" statt
     "FRONT" bei sonst gleichem Raster, der Differenzwert bleibt bei 1.)
  4. Tempo: Render mit Probe gegen Render ohne Probe (Bilder je Sekunde
     Rechenzeit), Vorschau mit Probe (Bilder in 5 s Echtzeit).
  5. Bildnachweis: Schwenktest, yaw laeuft in 10 s einmal um. Bilder bei
     0, 2,5 und 5 s werden als PNG abgelegt und ihre Unterschiede
     ausgegeben.

Das Skript nutzt dieselben Bausteine wie die App: core/view360.py fuer
Shader, Effekt und Uniforms, dieselbe appsink-Beschreibung wie
core/ges_backend.py, dasselbe Profilmuster wie managers/ges_encoder_manager.
"""

import math
import os
import sys
import threading
import time

HIER = os.path.dirname(os.path.abspath(__file__))
PROJEKT = os.path.dirname(HIER)
sys.path.insert(0, PROJEKT)

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GES", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GES, GstPbutils, GLib   # noqa: E402

Gst.init(None)
GES.init()

from core import view360   # noqa: E402

try:
    import numpy as np
except Exception:          # pragma: no cover - Messung geht auch ohne
    np = None

NS = Gst.SECOND
BREITE, HOEHE, FPS = 1280, 720, 30
ASPECT = view360.ziel_aspect(BREITE, HOEHE)

#: Timeline-Aufbau fuer die Zeitachsen-Messung (Punkt 1).
CLIP_A_DAUER_S = 2.0
CLIP_B_INPOINT_S = 3.0
CLIP_B_DAUER_S = 10.0
GESAMT_S = CLIP_A_DAUER_S + CLIP_B_DAUER_S

#: Sprungtest (Punkt 3): ab dieser Timelinezeit springt yaw auf SPRUNG_GRAD.
SPRUNG_S = 5.0
SPRUNG_GRAD = 45.0


def sagen(text=""):
    print(text, flush=True)


# ---------------------------------------------------------------------------
# Blickfunktionen: Timelinezeit (Sekunden) -> Blickwinkel
# ---------------------------------------------------------------------------
def blick_schwenk(t_timeline):
    """Yaw laeuft in GESAMT_S einmal um 360 Grad."""
    anteil = (t_timeline / GESAMT_S) % 1.0
    return view360.Blickwinkel(yaw=anteil * 2.0 * 3.141592653589793)


def blick_sprung(t_timeline):
    """Yaw 0 bis SPRUNG_S, danach SPRUNG_GRAD.

    Nicht 180 Grad: das Testbild 360_test_1920x960.mp4 (eine Testtafel)
    zeigt bei 180 Grad dieselbe Tafel mit "BACK" statt "FRONT" - fuer den
    Differenzwert praktisch dasselbe Bild. 45 Grad trifft zwischen zwei
    Tafeln und ist eindeutig.
    """
    return view360.Blickwinkel(
        yaw=math.radians(SPRUNG_GRAD) if t_timeline >= SPRUNG_S - 1e-9 else 0.0)


# ---------------------------------------------------------------------------
# Effekt und Probe
# ---------------------------------------------------------------------------
def shader_finden(effekt):
    """Das glshader-Element in der Effekt-Bin.

    GES.TrackElement.get_nleobject() liefert das nle-Objekt, in dem die
    Effekt-Bin haengt; darin wird nach dem Namen "kvr360" gesucht, den die
    Bin-Beschreibung vergibt. Rueckgabe None, wenn nichts gefunden wird -
    dann ist Variante B nicht moeglich, das ist ein Messergebnis.
    """
    wurzel = None
    for name in ("get_nleobject", "get_element"):
        holen = getattr(effekt, name, None)
        if holen is None:
            continue
        try:
            wurzel = holen()
        except Exception:
            wurzel = None
        if wurzel is not None:
            break
    if wurzel is None:
        return None
    if isinstance(wurzel, Gst.Bin):
        treffer = wurzel.get_by_name("kvr360")
        if treffer is not None:
            return treffer
        # Rekursiv, falls der Name in einer Zwischen-Bin steckt.
        for kind in wurzel.iterate_recurse():
            try:
                if kind.get_name() == "kvr360":
                    return kind
                fabrik = kind.get_factory()
                if fabrik is not None and fabrik.get_name() == "glshader":
                    return kind
            except Exception:
                continue
    return None


class Probe:
    """Buffer-Probe am Sink-Pad des Shaders.

    variante: "A" setzt ueber GES (effekt.set_child_property),
              "B" direkt am Element (shader.set_property).
    blickfunktion: Timelinezeit in Sekunden -> Blickwinkel.
    clip_start_s / clip_inpoint_s: fuer die Umrechnung des PTS, sobald die
    Zeitachse bekannt ist. Hier wird der PTS als das genommen, was er ist,
    und alle drei Deutungen werden protokolliert.
    """

    def __init__(self, effekt, shader, variante, blickfunktion,
                 clip_start_s, clip_inpoint_s):
        self.effekt = effekt
        self.shader = shader
        self.variante = variante
        self.blickfunktion = blickfunktion
        self.clip_start_s = clip_start_s
        self.clip_inpoint_s = clip_inpoint_s
        self.anzahl = 0
        self.erste = []          # (pts_s, seg_start_s, running_s, stream_s)
        self.segmente = {}       # seg.start (s) -> Anzahl Buffer darin
        self.fehler = []
        self.threads = set()
        self.hauptthread = threading.get_ident()
        self.setzzeit_ns = 0     # Summe der Zeit, die das Setzen kostet

    def anhaengen(self):
        ziel = self.shader if self.shader is not None else None
        if ziel is None:
            return False
        pad = ziel.get_static_pad("sink")
        if pad is None:
            return False
        pad.add_probe(Gst.PadProbeType.BUFFER, self._auf_buffer, None)
        return True

    def _timeline_zeit(self, pts_s):
        """PTS -> Timelinezeit.

        GEMESSEN (12.09.2026, GStreamer 1.28.6): der Zeitstempel, den die
        Probe am glshader sieht, ist die QUELLZEIT der Datei - bei einem
        Clip mit In-Point 3,0 s laeuft der PTS von 3,067 bis 13,033 s. Das
        Segment beginnt beim ersten gelieferten Bild (start=3,067,
        time=0, base=0), die Running-Time ist also clip-lokal.

        Fuer KVRouite ist das die beste Nachricht: die Rohzeit der App ist
        "Rohstart der Datei + Zeit in der Datei", also genau
        Datei-Rohstart + PTS. Die Probe braucht weder Clip-Start noch
        In-Point, nur den Rohstart der Quelldatei.

        Hier, mit einer einzelnen Datei als Quelle, ist die Timelinezeit
        clip_start + (pts - inpoint).
        """
        return self.clip_start_s + (pts_s - self.clip_inpoint_s)

    def _auf_buffer(self, pad, info, _daten):
        try:
            puffer = info.get_buffer()
            if puffer is None:
                return Gst.PadProbeReturn.OK
            pts = puffer.pts
            if pts == Gst.CLOCK_TIME_NONE:
                return Gst.PadProbeReturn.OK
            pts_s = pts / NS
            self.threads.add(threading.get_ident())

            seg_start = running = stream = float("nan")
            ereignis = pad.get_sticky_event(Gst.EventType.SEGMENT, 0)
            if ereignis is not None:
                segment = ereignis.parse_segment()
                seg_start = segment.start / NS
                r = segment.to_running_time(Gst.Format.TIME, pts)
                s = segment.to_stream_time(Gst.Format.TIME, pts)
                running = r / NS if r != Gst.CLOCK_TIME_NONE else float("nan")
                stream = s / NS if s != Gst.CLOCK_TIME_NONE else float("nan")
            schluessel = round(seg_start, 3)
            self.segmente[schluessel] = self.segmente.get(schluessel, 0) + 1
            if len(self.erste) < 3 or (len(self.segmente) > 1
                                       and self.segmente[schluessel] <= 2):
                self.erste.append((pts_s, seg_start, running, stream))

            blick = self.blickfunktion(self._timeline_zeit(pts_s))
            t0 = time.perf_counter_ns()
            if self.variante == "A":
                if not view360.uniforms_setzen(self.effekt, blick, ASPECT):
                    self.fehler.append("uniforms_setzen lieferte False")
            else:
                self.shader.set_property(
                    "uniforms", view360._uniforms(blick, ASPECT))
            self.setzzeit_ns += time.perf_counter_ns() - t0
            self.anzahl += 1
        except Exception as exc:
            self.fehler.append(repr(exc))
        return Gst.PadProbeReturn.OK

    def bericht(self):
        sagen(f"    Probe {self.variante}: {self.anzahl} Buffer in "
              f"{len(self.segmente)} Segment(en), "
              f"Threads: {len(self.threads)} "
              f"({'Streaming-Thread' if self.hauptthread not in self.threads else 'HAUPTTHREAD!'}), "
              f"Setzen im Mittel: "
              f"{(self.setzzeit_ns / max(1, self.anzahl)) / 1e6:.3f} ms")
        for start, anzahl in sorted(self.segmente.items()):
            sagen(f"      Segment ab {start:.3f}s: {anzahl} Buffer"
                  + ("  (Vorlauf vom Dateianfang, landet nicht im Bild)"
                     if len(self.segmente) > 1
                     and abs(start - self.clip_inpoint_s) > 0.5 else ""))
        for pts_s, seg_start, running, stream in self.erste:
            sagen(f"      pts={pts_s:.3f}s  seg.start={seg_start:.3f}s  "
                  f"running={running:.3f}s  stream={stream:.3f}s  "
                  f"-> Timeline {self._timeline_zeit(pts_s):.3f}s")
        if self.fehler:
            sagen(f"      FEHLER in der Probe ({len(self.fehler)}): "
                  f"{self.fehler[0]}")


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def timeline_bauen(quelle, mit_effekt=True):
    """Zwei Clips wie im Dateikopf beschrieben. Liefert (timeline, effekte).

    effekte: Liste (clip_start_s, clip_inpoint_s, effekt) je Clip.
    """
    asset = GES.UriClipAsset.request_sync(Gst.filename_to_uri(quelle))
    dauer_ns = asset.get_duration()
    noetig = (CLIP_B_INPOINT_S + CLIP_B_DAUER_S) * NS
    if dauer_ns < noetig:
        raise SystemExit(
            f"Quelle ist zu kurz: {dauer_ns / NS:.1f} s, "
            f"gebraucht werden {noetig / NS:.1f} s")

    timeline = GES.Timeline.new_audio_video()
    for track in timeline.get_tracks():
        if track.get_property("track-type") == GES.TrackType.VIDEO:
            track.set_restriction_caps(Gst.Caps.from_string(
                f"video/x-raw,width={BREITE},height={HOEHE},framerate={FPS}/1"))
    ebene = timeline.append_layer()
    ebene.set_auto_transition(False)

    plan = ((0.0, 0.0, CLIP_A_DAUER_S),
            (CLIP_A_DAUER_S, CLIP_B_INPOINT_S, CLIP_B_DAUER_S))
    effekte = []
    for start_s, inpoint_s, dauer_s in plan:
        clip = ebene.add_asset(asset, int(start_s * NS), int(inpoint_s * NS),
                               int(dauer_s * NS), GES.TrackType.VIDEO)
        if clip is None:
            raise SystemExit("Clip liess sich nicht anlegen")
        effekt = None
        if mit_effekt:
            effekt = view360.effekt_anhaengen(clip, view360.Blickwinkel(),
                                              ASPECT)
            if effekt is None:
                raise SystemExit("360-Effekt liess sich nicht anhaengen: "
                                 + (view360.fehlgrund() or "unbekannt"))
            view360.rahmen_setzen(clip, BREITE, HOEHE)
        effekte.append((start_s, inpoint_s, effekt))
    timeline.commit_sync()
    return timeline, effekte


def timeline_einfach(quelle, dauer_s=CLIP_B_DAUER_S):
    """Ein Clip ab 0 mit In-Point 0 - fuer den Sprungtest.

    So entspricht jedes Ausgabebild genau dem Quellbild mit demselben
    Zeitstempel, und die Frage "dieser oder der naechste Buffer" laesst sich
    an den PTS der Ausgabe ablesen, ohne Versatz durch In-Point oder
    Clip-Start.
    """
    asset = GES.UriClipAsset.request_sync(Gst.filename_to_uri(quelle))
    timeline = GES.Timeline.new_audio_video()
    for track in timeline.get_tracks():
        if track.get_property("track-type") == GES.TrackType.VIDEO:
            track.set_restriction_caps(Gst.Caps.from_string(
                f"video/x-raw,width={BREITE},height={HOEHE},framerate={FPS}/1"))
    ebene = timeline.append_layer()
    ebene.set_auto_transition(False)
    clip = ebene.add_asset(asset, 0, 0, int(dauer_s * NS), GES.TrackType.VIDEO)
    effekt = view360.effekt_anhaengen(clip, view360.Blickwinkel(), ASPECT)
    if effekt is None:
        raise SystemExit("360-Effekt liess sich nicht anhaengen")
    view360.rahmen_setzen(clip, BREITE, HOEHE)
    timeline.commit_sync()
    return timeline, [(0.0, 0.0, effekt)]


def profil_bauen():
    """x264 in MP4, schnellstes Preset - es geht um die Probe, nicht um die
    Kodierung."""
    behaelter = GstPbutils.EncodingContainerProfile.new(
        "Messung", "MP4 without audio",
        Gst.Caps.from_string("video/quicktime,variant=iso"), None)
    video = GstPbutils.EncodingVideoProfile.new(
        Gst.Caps.from_string("video/x-h264,profile=high"), None, None, 0)
    video.set_preset_name("x264enc")
    behaelter.add_profile(video)
    return behaelter


def bus_zaehlen(bus):
    """Warnungen und Fehler vom Bus einsammeln, ohne zu blockieren."""
    warnungen, fehler = [], []
    while True:
        msg = bus.pop_filtered(Gst.MessageType.WARNING | Gst.MessageType.ERROR)
        if msg is None:
            break
        err, dbg = (msg.parse_warning() if msg.type == Gst.MessageType.WARNING
                    else msg.parse_error())
        (warnungen if msg.type == Gst.MessageType.WARNING else fehler).append(
            f"{err.message} ({dbg})")
    return warnungen, fehler


# ---------------------------------------------------------------------------
# Render-Pfad
# ---------------------------------------------------------------------------
def rendern(timeline, ziel, frist_s=120.0):
    """Rendert die Timeline nach ziel. Liefert (sekunden, warnungen, fehler)."""
    pipeline = GES.Pipeline()
    pipeline.set_timeline(timeline)
    if not pipeline.set_render_settings(
            GLib.filename_to_uri(os.path.abspath(ziel), None), profil_bauen()):
        raise SystemExit("Render-Einstellungen abgelehnt")
    if not pipeline.set_mode(GES.PipelineFlags.RENDER):
        raise SystemExit("Render-Modus abgelehnt")
    bus = pipeline.get_bus()
    begonnen = time.perf_counter()
    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise SystemExit("Pipeline startet nicht")
    warnungen, fehler = [], []
    ende = None
    while True:
        msg = bus.timed_pop_filtered(
            200 * Gst.MSECOND,
            Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.WARNING)
        if msg is not None:
            if msg.type == Gst.MessageType.WARNING:
                err, dbg = msg.parse_warning()
                warnungen.append(f"{err.message} ({dbg})")
                continue
            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                fehler.append(f"{err.message} ({dbg})")
            ende = time.perf_counter()
            break
        if time.perf_counter() - begonnen > frist_s:
            fehler.append(f"Frist von {frist_s:.0f} s ueberschritten (Haenger?)")
            ende = time.perf_counter()
            break
    pipeline.set_state(Gst.State.NULL)
    pipeline.get_state(5 * Gst.SECOND)
    return ende - begonnen, warnungen, fehler


# ---------------------------------------------------------------------------
# Vorschau-Pfad (appsink wie in core/ges_backend.py)
# ---------------------------------------------------------------------------
def vorschau_messen(timeline, sekunden=5.0):
    """Bilder, die in 'sekunden' Echtzeit beim appsink ankommen."""
    senke = Gst.parse_bin_from_description(
        "videoconvert ! video/x-raw,format=BGRx ! "
        "appsink name=kvr-appsink sync=true max-buffers=2 drop=true "
        "emit-signals=true", True)
    appsink = senke.get_by_name("kvr-appsink")
    zaehler = {"bilder": 0}

    def auf_bild(s):
        sample = s.emit("pull-sample")
        if sample is not None:
            zaehler["bilder"] += 1
        return Gst.FlowReturn.OK

    appsink.connect("new-sample", auf_bild)
    pipeline = GES.Pipeline()
    pipeline.set_timeline(timeline)
    pipeline.preview_set_video_sink(senke)
    pipeline.set_mode(GES.PipelineFlags.FULL_PREVIEW)
    bus = pipeline.get_bus()
    pipeline.set_state(Gst.State.PAUSED)
    pipeline.get_state(20 * Gst.SECOND)
    begonnen = time.perf_counter()
    pipeline.set_state(Gst.State.PLAYING)
    while time.perf_counter() - begonnen < sekunden:
        msg = bus.timed_pop_filtered(50 * Gst.MSECOND,
                                     Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if msg is not None and msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            sagen(f"    FEHLER Vorschau: {err.message} ({dbg})")
            break
    vergangen = time.perf_counter() - begonnen
    pipeline.set_state(Gst.State.NULL)
    pipeline.get_state(5 * Gst.SECOND)
    warnungen, fehler = bus_zaehlen(bus)
    return zaehler["bilder"], vergangen, warnungen, fehler


# ---------------------------------------------------------------------------
# Ergebnis pruefen: Bilder aus dem gerenderten MP4 lesen
# ---------------------------------------------------------------------------
def bilder_lesen(pfad):
    """Alle Bilder der Datei als (pts_s, breite, hoehe, bytes)."""
    pipeline = Gst.parse_launch(
        "filesrc name=q ! decodebin ! videoconvert ! "
        "video/x-raw,format=BGRx ! appsink name=s sync=false "
        "emit-signals=false max-buffers=8")
    pipeline.get_by_name("q").set_property("location", pfad)
    appsink = pipeline.get_by_name("s")
    pipeline.set_state(Gst.State.PLAYING)
    bilder = []
    while True:
        sample = appsink.emit("try-pull-sample", 5 * Gst.SECOND)
        if sample is None:
            break
        puffer = sample.get_buffer()
        st = sample.get_caps().get_structure(0)
        ok, karte = puffer.map(Gst.MapFlags.READ)
        if not ok:
            continue
        try:
            bilder.append((puffer.pts / NS, st.get_value("width"),
                           st.get_value("height"), bytes(karte.data)))
        finally:
            puffer.unmap(karte)
        if appsink.get_property("eos"):
            break
    pipeline.set_state(Gst.State.NULL)
    pipeline.get_state(5 * Gst.SECOND)
    return bilder


def unterschied(a, b):
    """Mittlerer Betrag der Differenz je Byte, 0..255. Ohne numpy nur jedes
    64. Byte - fuer "gleich oder verschieden" reicht das."""
    if np is not None:
        x = np.frombuffer(a, dtype=np.uint8).astype(np.int16)
        y = np.frombuffer(b, dtype=np.uint8).astype(np.int16)
        return float(np.abs(x - y).mean())
    x, y = a[::64], b[::64]
    return sum(abs(p - q) for p, q in zip(x, y)) / max(1, len(x))


def png_schreiben(bild, pfad):
    try:
        from PySide6.QtGui import QImage
    except Exception:
        return False
    pts, b, h, daten = bild
    q = QImage(daten, b, h, b * 4, QImage.Format_RGB32).copy()
    return q.save(pfad)


def bild_bei(bilder, t_s):
    return min(bilder, key=lambda x: abs(x[0] - t_s))


# ---------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------
def lauf_render(quelle, ordner, name, variante, blickfunktion,
                bauen=timeline_bauen):
    """Ein Render-Lauf mit Probe am letzten Clip. Liefert (ziel, sekunden,
    probe, gesamt_s)."""
    timeline, effekte = bauen(quelle)
    start_b, inpoint_b, effekt_b = effekte[-1]
    gesamt_s = timeline.get_duration() / NS
    shader = shader_finden(effekt_b)
    if shader is None:
        sagen("    glshader in der Effekt-Bin NICHT gefunden - Probe unmoeglich")
        return None, 0.0, None, gesamt_s
    probe = Probe(effekt_b, shader, variante, blickfunktion, start_b, inpoint_b)
    if not probe.anhaengen():
        sagen("    Probe liess sich nicht anhaengen (kein Sink-Pad?)")
        return None, 0.0, None, gesamt_s
    ziel = os.path.join(ordner, name)
    sekunden, warnungen, fehler = rendern(timeline, ziel)
    probe.bericht()
    sagen(f"    Render: {sekunden:.2f} s fuer {gesamt_s:.0f} s Video "
          f"({gesamt_s * FPS / sekunden:.1f} Bilder/s Rechenzeit), "
          f"{len(warnungen)} Warnungen, {len(fehler)} Fehler")
    for w in warnungen[:3]:
        sagen(f"      WARNUNG: {w}")
    for f in fehler[:3]:
        sagen(f"      FEHLER: {f}")
    return ziel, sekunden, probe, gesamt_s


def main():
    quelle = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        PROJEKT, "360_test_1920x960.mp4")
    ordner = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.environ.get("TEMP", PROJEKT), "kvr_mess_360")
    os.makedirs(ordner, exist_ok=True)
    if not os.path.isfile(quelle):
        raise SystemExit(f"Quelle nicht gefunden: {quelle}")

    sagen(f"GStreamer {Gst.version_string()}, numpy: {'ja' if np else 'nein'}")
    sagen(f"Quelle:  {quelle}")
    sagen(f"Ausgabe: {ordner}")
    if not view360.verfuegbar():
        raise SystemExit("360 nicht verfuegbar: " + view360.fehlgrund())
    sagen()

    # -- 0. Referenz: Render ohne Probe --------------------------------------
    sagen("[0] Render OHNE Probe (Referenz fuer das Tempo)")
    timeline, _ = timeline_bauen(quelle)
    ref_s, w, f = rendern(timeline, os.path.join(ordner, "ohne_probe.mp4"))
    sagen(f"    Render: {ref_s:.2f} s ({GESAMT_S * FPS / ref_s:.1f} Bilder/s), "
          f"{len(w)} Warnungen, {len(f)} Fehler")
    sagen()

    # -- 1+2+4+5. Schwenktest, Variante A und B ------------------------------
    ergebnisse = {}
    for variante in ("A", "B"):
        sagen(f"[1/2/4/5] Schwenktest, Variante {variante} "
              f"({'GES set_child_property' if variante == 'A' else 'shader.set_property'})")
        ziel, sek, probe, _ = lauf_render(quelle, ordner,
                                          f"schwenk_{variante}.mp4",
                                          variante, blick_schwenk)
        ergebnisse[variante] = (ziel, sek, probe)
        sagen()

    # -- 5. Bildnachweis am Schwenk (Variante A, sonst B) --------------------
    ziel = ergebnisse["A"][0] or ergebnisse["B"][0]
    if ziel and os.path.isfile(ziel):
        sagen(f"[5] Bildnachweis aus {os.path.basename(ziel)}")
        bilder = bilder_lesen(ziel)
        sagen(f"    {len(bilder)} Bilder gelesen, erwartet {int(GESAMT_S * FPS)}")
        if bilder:
            b0 = bild_bei(bilder, 0.0)
            b25 = bild_bei(bilder, 2.5)
            b5 = bild_bei(bilder, 5.0)
            b_ende = bild_bei(bilder, GESAMT_S - 1.0 / FPS)
            for name, bild in (("bild_0.0s.png", b0), ("bild_2.5s.png", b25),
                               ("bild_5.0s.png", b5)):
                png_schreiben(bild, os.path.join(ordner, name))
            sagen(f"    Unterschied 0,0 s gegen 2,5 s: {unterschied(b0[3], b25[3]):.1f}")
            sagen(f"    Unterschied 0,0 s gegen 5,0 s: {unterschied(b0[3], b5[3]):.1f}")
            sagen(f"    Unterschied 2,5 s gegen 5,0 s: {unterschied(b25[3], b5[3]):.1f}")
            sagen(f"    Unterschied 0,0 s gegen Ende (yaw wieder ~0): "
                  f"{unterschied(b0[3], b_ende[3]):.1f}")
            sagen("    (Werte unter 2 = praktisch gleich, ueber 20 = klar verschieden)")
        sagen()

    # -- 3. Sprungtest: dieser Buffer oder der naechste? ---------------------
    # Ein Clip ab 0 mit In-Point 0: Ausgabe-PTS = Quell-PTS. Die Probe
    # schaltet bei Quellzeit >= 5,000 s auf 180 Grad um. Das erste
    # veraenderte Ausgabebild sagt, ob der Wert fuer denselben Buffer galt.
    sagen(f"[3] Sprungtest (yaw 0 -> {SPRUNG_GRAD:.0f} Grad ab Quellzeit "
          f"{SPRUNG_S:.3f} s), ein Clip, Variante A")
    ziel, sek, probe, _ = lauf_render(quelle, ordner, "sprung_A.mp4", "A",
                                      blick_sprung, bauen=timeline_einfach)
    if ziel and os.path.isfile(ziel):
        bilder = bilder_lesen(ziel)
        if len(bilder) > 3:
            diffs = [(i, unterschied(bilder[i - 1][3], bilder[i][3]))
                     for i in range(1, len(bilder))]
            grund = sorted(d for _, d in diffs)[len(diffs) // 2]
            i, d = max(diffs, key=lambda x: x[1])
            pts_sprung = bilder[i][0]
            pts_davor = bilder[i - 1][0]
            sagen(f"    Erstes veraendertes Bild: Nr. {i}, pts {pts_sprung:.3f} s "
                  f"(Vorgaenger {pts_davor:.3f} s), Differenz {d:.1f}, "
                  f"typische Bild-zu-Bild-Differenz {grund:.1f}")
            bild_s = 1.0 / FPS
            if d < 20:
                sagen("    -> KEIN Sprung im Bild - die Uniforms greifen nicht")
            elif pts_davor < SPRUNG_S - 1e-6 <= pts_sprung + 1e-6 \
                    and pts_sprung - SPRUNG_S < bild_s - 1e-6:
                sagen(f"    -> Wert greift fuer DENSELBEN Buffer: das erste "
                      f"Bild mit pts >= {SPRUNG_S:.3f} s ist bereits gedreht")
            elif SPRUNG_S <= pts_davor + 1e-6:
                sagen(f"    -> Wert greift erst fuer den NAECHSTEN Buffer "
                      f"(Versatz {(pts_sprung - SPRUNG_S) / bild_s:.0f} Bild)")
            else:
                sagen("    -> unerwartet, bitte pts oben pruefen")
    sagen()

    # -- 4. Vorschau-Pfad mit Probe ------------------------------------------
    sagen("[4] Vorschau (appsink, sync=true) 5 s mit Probe, Variante A")
    timeline, effekte = timeline_bauen(quelle)
    start_b, inpoint_b, effekt_b = effekte[1]
    shader = shader_finden(effekt_b)
    if shader is not None:
        probe = Probe(effekt_b, shader, "A", blick_schwenk, start_b, inpoint_b)
        probe.anhaengen()
    bilder, vergangen, warnungen, fehler = vorschau_messen(timeline, 5.0)
    sagen(f"    {bilder} Bilder in {vergangen:.2f} s = {bilder / vergangen:.1f} fps "
          f"(Massstab aus view360.py: 150 in 5,00 s = 30,0 fps), "
          f"{len(warnungen)} Warnungen, {len(fehler)} Fehler")
    if shader is not None:
        # Die Vorschau begann bei 0 s, Clip B (mit Probe) erst ab 2 s:
        # erwartet werden also rund 3 s * 30 = 90 Buffer in der Probe.
        probe.bericht()
    sagen()

    # -- Zusammenfassung ------------------------------------------------------
    sagen("Zusammenfassung")
    sagen(f"  Render ohne Probe: {GESAMT_S * FPS / ref_s:6.1f} Bilder/s")
    for variante in ("A", "B"):
        z, sek, p = ergebnisse[variante]
        if z and sek > 0:
            sagen(f"  Render Probe {variante}: {GESAMT_S * FPS / sek:6.1f} Bilder/s"
                  f"  (Fehler in der Probe: {len(p.fehler)})")
    sagen("  Zeitachse der Probe: Quellzeit der Datei (PTS), "
          "siehe Probe._timeline_zeit")
    sagen(f"  PNGs und MP4s liegen in {ordner}")


if __name__ == "__main__":
    main()
