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

    Warum die Pruefung in einem eigenen Unterprozess ausgefuehrt wird:
    Hardware-Treiber (insbesondere Intel QSV/oneVPL ueber qsvh264enc auf
    aelteren Chips wie Haswell, oder instabile GPU-Treiber) koennen bei
    Inkompatibilitaeten hart auf C-Ebene mit abort() / SIGABRT abstuerzen
    (z.B. fehlgeschlagene vaSts-Assertion in mfx_h264_encode_vaapi).
    Laeuft die Erkennung im Hauptprozess, beendet ein solcher Absturz die
    gesamte Anwendung. Im isolierten Unterprozess wird der Absturz sauber
    abgefangen: der fehlerhafte Treiber wird als nicht verfuegbar markiert,
    und nachfolgende Encoder (z.B. funktionierendes vaapi_h264) werden
    weiterhin zuverlaessig erkannt.

    kennung ist die Programmkennung ("nvidia_h264", "vaapi_h264", ...).
    Liefert (True, "") oder (False, grund). Der Grund landet im Log; wenn ein
    Anwender meldet, seine Karte werde nicht erkannt, steht dort, woran es lag.
    """
    if not gstreamer_verfuegbar():
        return False, "GStreamer not available"

    import json
    import subprocess
    import sys

    code = f"""import sys, json
try:
    from managers.ges_encoder_manager import probelauf
    ok, grund, _zeilen = probelauf({repr(kennung)})
    sys.stdout.write(json.dumps({{"ok": ok, "grund": grund}}))
    sys.exit(0)
except Exception as e:
    sys.stdout.write(json.dumps({{"ok": False, "grund": str(e)}}))
    sys.exit(1)
"""

    try:
        res = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=15
        )
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout.strip())
            return data.get("ok", False), data.get("grund", "")
        else:
            err = res.stderr.strip()
            if not err and res.returncode != 0:
                err = f"Driver / probe process crashed (exit code {res.returncode})"
            else:
                err = err.splitlines()[-1] if err else "Probe failed"
            return False, err
    except subprocess.TimeoutExpired:
        return False, "Probe timed out"
    except Exception as exc:
        return False, f"Probe error: {exc}"



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
