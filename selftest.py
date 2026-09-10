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
"""
Prueft, ob KVRouite tatsaechlich arbeitet - nicht nur startet.

    python3 selftest.py                     im Quellbaum
    KVRouite.app/Contents/MacOS/KVRouite --selftest      im fertigen Buendel
    KVRouite.exe --selftest                             im fertigen Windows-Build

Warum es diese Datei gibt: ein Startversuch beweist nur, dass der Prozess
nicht sofort abstuerzt. Ob die Anwendung ein Video schneiden und ausgeben
kann, ob sie ihre Symbole und die Kartenseite findet, ob GPX gelesen und
wieder geschrieben wird - davon sagt er nichts. Besonders bei einem gepackten
Programm ist das der Unterschied zwischen "laeuft" und "laeuft angeblich":
dort liegen die Dateien woanders als im Quellbaum, und genau daran scheitert
es erfahrungsgemaess.

Dieselben Pruefungen fuer beide Wege, damit sie nicht auseinanderlaufen: der
CI-Lauf gegen den Quellcode und der Aufruf im fertigen Buendel fuehren diesen
Code aus, nicht zwei Fassungen davon.

Rueckgabe: 0 wenn alles stimmt, 1 wenn etwas fehlt. Jeder Schritt sagt, was
er geprueft hat und was dabei herauskam.
"""

import os
import sys
import tempfile
import traceback

#: 8 Sekunden Testmaterial. Genug fuer einen Schnitt in der Mitte, kurz genug
#: fuer einen CI-Lauf.
QUELLE_SEKUNDEN = 8
QUELLE_BREITE = 640
QUELLE_HOEHE = 360
QUELLE_FPS = 30

#: Der Schnitt, der im Export geprueft wird: 3,0 s bis 5,0 s heraus, mit einer
#: Sekunde Ueberblendung. Aus 8 s werden damit rund 6 s.
SCHNITT_VON = 3.0
SCHNITT_BIS = 5.0
SCHNITT_BLENDE = 1.0

GPX_INHALT = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="KVRouite-Selftest" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>Selftest</name><trkseg>
    <trkpt lat="50.9400" lon="6.9600"><ele>50.0</ele><time>2026-01-01T10:00:00Z</time></trkpt>
    <trkpt lat="50.9410" lon="6.9610"><ele>55.0</ele><time>2026-01-01T10:00:02Z</time></trkpt>
    <trkpt lat="50.9420" lon="6.9620"><ele>60.0</ele><time>2026-01-01T10:00:04Z</time></trkpt>
    <trkpt lat="50.9430" lon="6.9630"><ele>58.0</ele><time>2026-01-01T10:00:06Z</time></trkpt>
    <trkpt lat="50.9440" lon="6.9640"><ele>62.0</ele><time>2026-01-01T10:00:08Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""


class Bericht:
    """Sammelt, was geprueft wurde - und was dabei schieflief."""

    def __init__(self):
        self.probleme = []

    def sagen(self, text):
        print("   " + text)

    def pruefen(self, bedingung, was, warum=""):
        if bedingung:
            print("   [ok]     " + was)
        else:
            print("   [FAILED] " + was + ((" - " + warum) if warum else ""))
            self.probleme.append(was)
        return bool(bedingung)


def schritt(nummer, titel):
    print("")
    print("=" * 70)
    print("%d. %s" % (nummer, titel))
    print("=" * 70)


# --------------------------------------------------------------- 1. Dateien
def dateien_pruefen(b: Bericht):
    """Findet die Anwendung, was mitgeliefert wurde?

    Im Quellbaum ist das selbstverstaendlich. In einem gepackten Programm
    nicht: dort liegen die Symbole neben dem Programm, das Kinomap-Logo unter
    Windows in _internal und im macOS-Buendel in Contents/Resources. Genau
    hier ist frueher jedes Symbol verschwunden, weil relative Pfade gegen das
    Arbeitsverzeichnis aufgeloest wurden.
    """
    from config import finde_datei, programm_ordner, datenordner_liste

    b.sagen("Program folder: " + programm_ordner())
    for ort in datenordner_liste():
        b.sagen("Looked in: " + ort)

    erwartet = [
        ("map_page.html",),
        ("ol.js",),
        ("ol.css",),
        ("icon", "go_to_end.png"),
        ("icon", "cut_begin.png"),
        ("icon", "vg_sync_ring.png"),
        ("doc", "Kinomap_Logo.png"),
    ]
    for teile in erwartet:
        pfad = finde_datei(*teile)
        b.pruefen(os.path.isfile(pfad), "/".join(teile), "looked for " + pfad)


# ------------------------------------------------------------ 2. Oberflaeche
def symbole_pruefen(b: Bericht):
    """Lassen sich die Symbole wirklich laden - nicht nur finden?

    Ein gefundener Pfad heisst noch nicht, dass ein Bild daraus wird. Geprueft
    wird ueber denselben Weg, den die Knoepfe gehen: core.theme.icon().
    """
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])
    from core import theme

    for modus in ("light", "dark"):
        theme.anwenden(QApplication.instance(), modus)
        for name in ("icon/go_to_end.png", "icon/cut_begin.png",
                     "icon/vg_sync_ring.png", "icon/vg_icon_on2.png"):
            symbol = theme.icon(name)
            b.pruefen(not symbol.isNull(), "%s in %s" % (name, modus))


# -------------------------------------------------------------- 3. GStreamer
def gstreamer_pruefen(b: Bericht):
    """Ist die Laufzeit da, die Wiedergabe und Export tragen?"""
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    b.sagen("GStreamer " + ".".join(str(z) for z in Gst.version()[:3]))

    for name in ("x264enc", "videotestsrc", "mp4mux", "qtdemux", "videoconvert"):
        b.pruefen(Gst.ElementFactory.make(name, None) is not None,
                  "Element " + name)

    try:
        gi.require_version("GES", "1.0")
        from gi.repository import GES
        GES.init()
        zeitachse = GES.Timeline.new_audio_video()
        b.pruefen(zeitachse is not None, "GES timeline can be created")
    except Exception as exc:
        b.pruefen(False, "GES available", str(exc))


# ------------------------------------------------------------------- 4. GPX
def gpx_rundlauf(b: Bericht, ordner):
    """GPX lesen, exportieren, wieder lesen - kommt dasselbe heraus?"""
    from core.gpx_parser import parse_gpx, recalc_gpx_data

    quelle = os.path.join(ordner, "selftest_quelle.gpx")
    with open(quelle, "w", encoding="utf-8") as f:
        f.write(GPX_INHALT)

    punkte = parse_gpx(quelle)
    if not b.pruefen(len(punkte) == 5, "5 points read",
                     "bekommen: %d" % len(punkte)):
        return
    recalc_gpx_data(punkte)

    # Derselbe Schreiber, den der Menuepunkt "Export GPX..." benutzt. Er
    # braucht kein self, laesst sich also ohne Hauptfenster aufrufen.
    from views.mainwindow import MainWindow
    ziel = os.path.join(ordner, "selftest_export.gpx")
    MainWindow._save_gpx_to_file(None, punkte, ziel)
    if not b.pruefen(os.path.isfile(ziel), "GPX written"):
        return
    b.sagen("%d bytes" % os.path.getsize(ziel))

    zurueck = parse_gpx(ziel)
    if not b.pruefen(len(zurueck) == len(punkte), "same number of points read back",
                     "%d gegen %d" % (len(punkte), len(zurueck))):
        return

    abweichungen = []
    for i, (a, z) in enumerate(zip(punkte, zurueck)):
        for feld in ("lat", "lon", "ele"):
            va, vz = a.get(feld), z.get(feld)
            if va is None or vz is None or abs(float(va) - float(vz)) > 1e-6:
                abweichungen.append("Punkt %d: %s %s != %s" % (i, feld, va, vz))
        if a.get("time") and z.get("time") and a["time"] != z["time"]:
            abweichungen.append("Punkt %d: Zeit %s != %s" % (i, a["time"], z["time"]))
    b.pruefen(not abweichungen, "values unchanged",
              "; ".join(abweichungen[:3]))


# ---------------------------------------------------------------- 5. Export
def _testvideo_bauen(ziel):
    """8 Sekunden Testbild als MP4 - ohne Ton, wie der Export selbst."""
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    # Der Dateiname wird als EIGENSCHAFT gesetzt und nicht in die
    # Beschreibung geschrieben: parse_launch() liest den Text, und ein
    # Windows-Pfad verliert dabei seine Backslashes - aus C:\Users\... wurde
    # C:Users..., und das Schreiben scheiterte mit "Permission denied".
    rohr = Gst.parse_launch(
        "videotestsrc num-buffers=%d pattern=ball ! "
        "video/x-raw,width=%d,height=%d,framerate=%d/1 ! "
        "x264enc key-int-max=%d ! mp4mux ! filesink name=ziel"
        % (QUELLE_SEKUNDEN * QUELLE_FPS, QUELLE_BREITE, QUELLE_HOEHE,
           QUELLE_FPS, QUELLE_FPS))
    rohr.get_by_name("ziel").set_property("location", ziel)
    rohr.set_state(Gst.State.PLAYING)
    nachricht = rohr.get_bus().timed_pop_filtered(
        60 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    rohr.set_state(Gst.State.NULL)
    if nachricht is None:
        return "Zeitueberschreitung beim Erzeugen des Testvideos"
    if nachricht.type == Gst.MessageType.ERROR:
        return str(nachricht.parse_error())
    return None


def _messen(pfad):
    """Dauer, Codec und Bildgroesse einer Datei."""
    import gi
    gi.require_version("Gst", "1.0")
    gi.require_version("GstPbutils", "1.0")
    from gi.repository import Gst, GstPbutils
    disc = GstPbutils.Discoverer.new(30 * Gst.SECOND)
    info = disc.discover_uri(Gst.filename_to_uri(pfad))
    spur = info.get_video_streams()[0]
    codec = spur.get_caps().to_string().split(",")[0]
    return (info.get_duration() / Gst.SECOND, codec,
            spur.get_width(), spur.get_height())


def export_rundlauf(b: Bericht, ordner):
    """Ein Video mit Schnitt und Ueberblendung ausgeben - der eigentliche Test.

    Gegangen wird derselbe Weg wie im Programm: encoder_manager ruft dort
    ges_xfade_main() mit einer JSON-Beschreibung auf.
    """
    import json

    quelle = os.path.join(ordner, "selftest_quelle.mp4")
    fehler = _testvideo_bauen(quelle)
    if not b.pruefen(fehler is None, "test video created", fehler or ""):
        return
    dauer, codec, breite, hoehe = _messen(quelle)
    b.sagen("Source: %.2fs, %s, %dx%d, %d bytes"
            % (dauer, codec, breite, hoehe, os.path.getsize(quelle)))

    ziel = os.path.join(ordner, "selftest_export.mp4")
    cfg_pfad = os.path.join(ordner, "selftest_cfg.json")
    cfg = {
        "videos": [quelle],
        "skip_instructions": [[SCHNITT_VON, SCHNITT_BIS, SCHNITT_BLENDE]],
        "overlay_instructions": [],
        "final_output": ziel,
        "encoder": "libx264",
        "hardware_encode": "none",
        "crf": 28,
        "fps": "%d/1" % QUELLE_FPS,
        "width": QUELLE_BREITE,
    }
    with open(cfg_pfad, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    from managers.ges_encoder_manager import ges_xfade_main
    print("   --- output of the render run ---")
    try:
        ges_xfade_main(cfg_pfad)
    except Exception as exc:
        b.pruefen(False, "export finished", str(exc))
        return
    print("   --- end ---")

    if not b.pruefen(os.path.isfile(ziel), "file created"):
        return
    groesse = os.path.getsize(ziel)
    dauer_z, codec_z, breite_z, hoehe_z = _messen(ziel)
    b.sagen("Result: %.2fs, %s, %dx%d, %d bytes"
            % (dauer_z, codec_z, breite_z, hoehe_z, groesse))

    erwartet = QUELLE_SEKUNDEN - (SCHNITT_BIS - SCHNITT_VON)
    b.pruefen(groesse > 10000, "file not empty", "%d bytes" % groesse)
    b.pruefen(abs(dauer_z - erwartet) <= 1.0,
              "duration about %.0fs after the cut" % erwartet,
              "measured %.2fs" % dauer_z)
    b.pruefen("h264" in codec_z, "encoded as h264", codec_z)
    b.pruefen((breite_z, hoehe_z) == (QUELLE_BREITE, QUELLE_HOEHE),
              "frame size unchanged", "%dx%d" % (breite_z, hoehe_z))


def hw_export_rundlauf(b: Bericht, ordner):
    """Jeden gemeldeten Hardware-Encoder einmal wirklich durch den Export schicken.

    Warum das ein eigener Schritt sein muss: der Erkennungslauf in
    core/hardware_detect.can_encode_with_gst baut seine Pipeline von Hand und
    nennt das Element beim Namen - damit ist bewiesen, dass das Element laeuft.
    Der Export geht einen anderen Weg: GES gibt ein Encoding-Profil an
    encodebin, und encodebin sucht sich sein Element ueber die Registry. Was
    dabei unterhalb von Rank "marginal" liegt, existiert fuer encodebin nicht.

    Ein Encoder kann also die Erkennung bestehen und am Export scheitern. So
    am 03.09.2026 gemeldet: vah264enc unter Linux, "Detect HW" meldete ihn,
    der Export brach mit "Render settings were rejected" ab, bevor ein Bild
    gelaufen war. Bis dahin lief hier nur ein Export mit
    hardware_encode="none" - der Weg des Anwenders wurde nie geprueft.
    """
    import json
    from core.hardware_detect import detect_hw_encoders_gst

    lauffaehig, protokoll = detect_hw_encoders_gst()
    for name, ok, grund in protokoll:
        b.sagen("Detection: %-28s %s"
                % (name, "works" if ok else "no" + (" - " + grund if grund else "")))

    kennungen = sorted(k for k in lauffaehig if k != "CPU")
    if not kennungen:
        b.sagen("No hardware encoder on this computer - nothing to check.")
        return

    quelle = os.path.join(ordner, "selftest_quelle.mp4")
    if not os.path.isfile(quelle):
        fehler = _testvideo_bauen(quelle)
        if not b.pruefen(fehler is None, "test video created", fehler or ""):
            return

    from managers.ges_encoder_manager import ges_xfade_main

    for kennung in kennungen:
        ziel = os.path.join(ordner, "selftest_%s.mp4" % kennung)
        cfg_pfad = os.path.join(ordner, "selftest_%s.json" % kennung)
        cfg = {
            "videos": [quelle],
            "skip_instructions": [[SCHNITT_VON, SCHNITT_BIS, SCHNITT_BLENDE]],
            "overlay_instructions": [],
            "final_output": ziel,
            "encoder": "libx265" if kennung.endswith("hevc") else "libx264",
            "hardware_encode": kennung,
            "crf": 28,
            "fps": "%d/1" % QUELLE_FPS,
            "width": QUELLE_BREITE,
        }
        with open(cfg_pfad, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        print("   --- render run with %s ---" % kennung)
        try:
            ges_xfade_main(cfg_pfad)
        except Exception as exc:
            print("   --- end ---")
            b.pruefen(False, "export with %s" % kennung, str(exc))
            continue
        print("   --- end ---")

        if not b.pruefen(os.path.isfile(ziel), "file created with %s" % kennung):
            continue
        groesse = os.path.getsize(ziel)
        dauer_z, codec_z, breite_z, hoehe_z = _messen(ziel)
        b.sagen("Result %s: %.2fs, %s, %dx%d, %d bytes"
                % (kennung, dauer_z, codec_z, breite_z, hoehe_z, groesse))
        erwartet = QUELLE_SEKUNDEN - (SCHNITT_BIS - SCHNITT_VON)
        b.pruefen(groesse > 10000, "file not empty (%s)" % kennung,
                  "%d bytes" % groesse)
        b.pruefen(abs(dauer_z - erwartet) <= 1.0,
                  "duration about %.0fs after the cut (%s)" % (erwartet, kennung),
                  "measured %.2fs" % dauer_z)
        # _messen liefert die Caps ("video/x-h265"), nicht den
        # ffmpeg-Namen "hevc".
        erwarteter_codec = "h265" if kennung.endswith("hevc") else "h264"
        b.pruefen(erwarteter_codec in codec_z,
                  "encoded as %s (%s)" % (erwarteter_codec, kennung), codec_z)


# ------------------------------------------------------------------- Ablauf
def audio_pruefen(b: Bericht):
    """Ist das Audio-Zusatzpaket da, und laeuft es?

    Seit 7.0 gibt es die App als Lite (ohne Audio) und mit dem Zusatzpaket
    (Tonspur, Daempfer, Voice Remover). Fehlt der Zusatz, ist das KEIN
    Fehler - es wird nur gesagt. Ist er da, muessen sich torch, onnxruntime
    und die Bibliothek laden lassen und die Modelldateien vorhanden sein:
    genau das, was nach dem Entpacken des Zusatz-Zips schiefgehen kann.
    """
    from core import stimme

    ok, grund = stimme.verfuegbar()
    if not ok:
        b.sagen("Audio add-on: not installed - this is the Lite application")
        b.sagen("   (" + grund + ")")
        return
    b.sagen("Audio add-on: installed, models in " + stimme.modellordner())
    try:
        import torch
        b.pruefen(True, "torch %s loads" % torch.__version__)
    except Exception as exc:
        b.pruefen(False, "torch loads", str(exc))
    try:
        import onnxruntime
        b.pruefen(True, "onnxruntime %s loads" % onnxruntime.__version__)
    except Exception as exc:
        b.pruefen(False, "onnxruntime loads", str(exc))
    try:
        import audio_separator  # noqa: F401
        b.pruefen(True, "audio_separator loads")
    except Exception as exc:
        b.pruefen(False, "audio_separator loads", str(exc))
    for kennung, (datei, name) in stimme.MODELLE.items():
        pfad = os.path.join(stimme.modellordner(), datei)
        b.pruefen(os.path.isfile(pfad), "model %s (%s)" % (datei, name),
                  "missing in " + stimme.modellordner())
    # Der Sprachdetektor ("Find voices") - dasselbe Paket, eigenes Modell.
    from core import sprache
    ok, grund = sprache.verfuegbar()
    b.pruefen(ok, "speech detector %s (Silero VAD)" % sprache.MODELL, grund)


def alles_pruefen(ordner=None):
    """Alle Schritte. Rueckgabe: 0 wenn alles stimmt, sonst 1."""
    eigener_ordner = ordner is None
    if eigener_ordner:
        ordner = tempfile.mkdtemp(prefix="kvrouite_selftest_")

    print("KVRouite self-test")
    print("Work folder:", ordner)
    print("Program:", sys.executable)
    print("bundled:", bool(getattr(sys, "frozen", False)))

    b = Bericht()
    aufgaben = (
        ("Files shipped with the program", lambda: dateien_pruefen(b)),
        ("Loading the icons", lambda: symbole_pruefen(b)),
        ("GStreamer and GES", lambda: gstreamer_pruefen(b)),
        ("Audio add-on (Lite or full)", lambda: audio_pruefen(b)),
        ("Reading, writing and re-reading GPX", lambda: gpx_rundlauf(b, ordner)),
        ("Cutting and exporting a video", lambda: export_rundlauf(b, ordner)),
        ("Really using the hardware encoders",
         lambda: hw_export_rundlauf(b, ordner)),
    )
    for nummer, (titel, aufgabe) in enumerate(aufgaben, 1):
        schritt(nummer, titel)
        try:
            aufgabe()
        except Exception:
            print("   [FAILED] this step was aborted:")
            for zeile in traceback.format_exc().splitlines():
                print("      " + zeile)
            b.probleme.append(titel + " (aborted)")

    print("")
    print("=" * 70)
    if b.probleme:
        print("RESULT: %d point(s) are not right:" % len(b.probleme))
        for p in b.probleme:
            print("   -", p)
        print("=" * 70)
        return 1
    print("RESULT: everything checked and in order.")
    print("=" * 70)
    return 0


def main():
    # Ohne Bildschirm laufen lassen, wenn keiner da ist - der Test braucht
    # kein Fenster, und auf einem Bauserver gibt es keins.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return alles_pruefen()


if __name__ == "__main__":
    sys.exit(main())
