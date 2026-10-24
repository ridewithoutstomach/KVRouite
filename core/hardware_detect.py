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


# core/hardware_detect.py

import json
import os
import signal
import subprocess
import sys


# ---------------------------------------------------------------------------
# Encoder-Test ueber GStreamer
# ---------------------------------------------------------------------------
# Die Kennungen links sind die, die das ganze Programm benutzt ("nvidia_hevc"
# und so weiter). Rechts steht das GStreamer-Element. Die Tabelle liegt hier,
# damit es sie nur einmal gibt: managers/ges_encoder_manager.py holt sie sich
# von hier, statt eine eigene Kopie zu fuehren.

GST_HW_ENCODER = {
    "nvidia_h264": ("nvh264enc", "video/x-h264"),
    "nvidia_hevc": ("nvh265enc", "video/x-h265"),
    "amd_h264":    ("amfh264enc", "video/x-h264"),
    "amd_hevc":    ("amfh265enc", "video/x-h265"),
    "intel_h264":  ("qsvh264enc", "video/x-h264"),
    "intel_hevc":  ("qsvh265enc", "video/x-h265"),
    "vaapi_h264":  ("vah264enc", "video/x-h264"),
    "vaapi_hevc":  ("vah265enc", "video/x-h265"),
}


def gstreamer_verfuegbar():
    """True, wenn GStreamer benutzbar ist."""
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        if not Gst.is_initialized():
            Gst.init(None)
        return True
    except Exception:
        return False


def can_encode_with_gst(kennung):
    """Wirklich kodieren - und zwar auf genau dem Weg, den der Export geht.

    Es reicht nicht, den Encoder irgendwie laufen zu lassen. Was hier
    herauskommt, entscheidet darueber, was im Setup zur Auswahl steht, und
    alles was dort steht MUSS exportieren koennen.

    Zu ffmpeg-Zeiten war das von selbst gegeben: dort waehlt man den Encoder
    mit "-c:v h264_nvenc", und einen zweiten Weg gibt es nicht - der Testlauf
    konnte gar nicht anders arbeiten als der Export.

    Der erste GES-Erkennungslauf hat diese Eigenschaft verloren. Er kodierte
    zwar wirklich, aber ueber eine von Hand gebaute Pipeline
    (videotestsrc ! videoconvert ! <encoder> ! fakesink), in der das Element
    beim Namen gerufen wird. Der Export uebergibt stattdessen ein
    Encoding-Profil an encodebin, und encodebin sucht sich das Element selbst
    aus der Registry - wer dort nicht zur Auswahl zugelassen ist, wird nicht
    genommen. Ein Encoder konnte den Test also bestehen und beim Export
    durchfallen. Genau das ist am 03.09.2026 einem Anwender passiert:
    "Detect HW" bot vaapi_h264 an, der Export brach mit "Render settings were
    rejected" ab, bevor ein Bild gelaufen war.

    Deshalb laeuft die Pruefung jetzt durch managers.ges_encoder_manager -
    dieselben zwei Funktionen, die auch jeder Export benutzt, in dieselbe Art
    Zieldatei. Was hier durchlaeuft, laeuft auch im Export durch.

    kennung ist die Programmkennung ("nvidia_h264", "vaapi_h264", ...).
    Liefert (True, "") oder (False, grund). Der Grund landet im Log; wenn ein
    Anwender meldet, seine Karte werde nicht erkannt, steht dort, woran es lag.
    """
    if not gstreamer_verfuegbar():
        return False, "GStreamer not available"
    if sys.platform.startswith("linux"):
        return _probelauf_eigener_prozess(kennung)
    try:
        from managers.ges_encoder_manager import probelauf
    except Exception as exc:
        return False, "export path could not be loaded: %s" % exc
    ok, grund, _zeilen = probelauf(kennung)
    return ok, grund


# ---------------------------------------------------------------------------
# Linux: jeder Probelauf in einem eigenen Python-Prozess
# ---------------------------------------------------------------------------
# Gemeldet in PR #53 (Okt. 2026): Haswell-Notebook unter Linux Mint, VA-API
# mit dem i965-Treiber, dazu qsvh264enc aus gstreamer1.0-plugins-bad. Die
# Intel Media SDK bricht beim Testlauf mit einer C-Assertion ab (SIGABRT) -
# das laesst sich in Python nicht abfangen, KVRouite war sofort weg. Der
# vah264enc auf derselben Maschine haette funktioniert, kam aber nie dran.
#
# Deshalb laeuft unter Linux jeder Kandidat in einem eigenen Prozess. Stirbt
# der, faellt nur dieser Encoder durch, und die Erkennung macht mit dem
# naechsten weiter.
#
# Nur Linux: Unter Windows gab es so einen Absturz nie, und die exe von
# PyInstaller hat keinen Python-Interpreter, mit dem sich der Probelauf
# starten liesse. Unter Linux laeuft KVRouite aus dem Quellcode,
# sys.executable ist also ein echtes Python.

# Ergebniszeile des Kindprozesses. Treiber und GStreamer schreiben gern
# eigene Zeilen auf stdout; gelesen wird nur die mit dieser Marke.
_MARKE = "KVROUITE_PROBE_RESULT:"

# Ein Probelauf braucht normalerweise unter einer Sekunde, dazu das Laden
# der Module. Haengt ein Treiber, wird der Prozess nach dieser Zeit beendet.
_PROBE_TIMEOUT_S = 60

_KIND_SKRIPT = """
import json, sys
try:
    from managers.ges_encoder_manager import probelauf
    ok, grund, _zeilen = probelauf(sys.argv[1])
except Exception as exc:
    ok, grund = False, "export path could not be loaded: %s" % exc
sys.stdout.flush()
print(""" + repr(_MARKE) + """ + json.dumps([bool(ok), str(grund)]), flush=True)
"""


def _probelauf_eigener_prozess(kennung):
    """probelauf(kennung) in einem eigenen Prozess. Liefert (ok, grund)."""
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        erg = subprocess.run(
            [sys.executable, "-c", _KIND_SKRIPT, kennung],
            cwd=wurzel, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors="replace",
            timeout=_PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, "probe timed out after %d s" % _PROBE_TIMEOUT_S
    except Exception as exc:
        return False, "probe process could not be started: %s" % exc

    for zeile in reversed(erg.stdout.splitlines()):
        if zeile.startswith(_MARKE):
            try:
                ok, grund = json.loads(zeile[len(_MARKE):])
                return bool(ok), grund
            except ValueError:
                break

    # Keine Ergebniszeile: der Prozess ist unterwegs gestorben. Die letzte
    # Zeile von stderr ist meist die Assertion des Treibers.
    if erg.returncode < 0:
        try:
            wie = signal.Signals(-erg.returncode).name
        except ValueError:
            wie = "signal %d" % -erg.returncode
        grund = "probe process crashed (%s)" % wie
    else:
        grund = "probe process ended without result (exit code %d)" % erg.returncode
    letzte = [z.strip() for z in erg.stderr.splitlines() if z.strip()]
    if letzte:
        grund += ": " + letzte[-1][:300]
    return False, grund


def detect_hw_encoders_gst():
    """Alle Kennungen, deren Encoder sich wirklich betreiben laesst.

    "CPU" ist immer dabei. Zurueck kommt (menge, protokoll): das Protokoll
    haelt zu jedem Kandidaten fest, ob er lief und warum nicht.
    """
    gefunden = {"CPU"}
    protokoll = []
    if not gstreamer_verfuegbar():
        return gefunden, [("GStreamer", False, "not available")]
    for kennung, (element, _caps) in GST_HW_ENCODER.items():
        ok, grund = can_encode_with_gst(kennung)
        if ok:
            gefunden.add(kennung)
        protokoll.append((f"{kennung} ({element})", ok, grund))
    return gefunden, protokoll


def list_hw_encoders_gst():
    """Die Kennungen, deren Encoder-Element vorhanden ist - ohne Testlauf.

    Sagt nur, was theoretisch da ist; der Beweis bleibt der Knopf
    "Detect HW", der wirklich kodiert. GStreamer legt die Hersteller-Elemente
    erst an, wenn beim Start eine passende Karte gefunden wurde - auf einem
    Rechner mit nur NVIDIA meldet es zwei Kennungen, waehrend die frueher
    benutzte ffmpeg-Liste sechs auffuehrte, unabhaengig von der Hardware.
    """
    gefunden = {"CPU"}
    if not gstreamer_verfuegbar():
        return gefunden
    from gi.repository import Gst
    for kennung, (element, _caps) in GST_HW_ENCODER.items():
        try:
            if Gst.ElementFactory.make(element, None) is not None:
                gefunden.add(kennung)
        except Exception:
            pass
    return gefunden
