# -*- coding: utf-8 -*-
"""
Prüfung für die isolierte Hardware-Encoder-Erkennung (core/hardware_detect.py).

Testet, dass detect_hw_encoders_gst() und can_encode_with_gst():
1. Nicht abstürzen, selbst wenn ein Treiber auf C-Ebene (z.B. qsvh264enc / MFX vaSts assertion)
   hart mit SIGABRT abbricht.
2. Das Protokoll zu jedem Kandidaten sauber befüllen.
3. Die CPU immer als funktionsfähigen Fallback melden.
"""

import sys
from core.hardware_detect import detect_hw_encoders_gst, can_encode_with_gst, GST_HW_ENCODER

def main():
    print("[TEST] Starte Hardware-Erkennungstest...")
    try:
        gefunden, protokoll = detect_hw_encoders_gst()
    except Exception as exc:
        print(f"[FEHLER] detect_hw_encoders_gst() hat eine Ausnahme geworfen: {exc}")
        return 1

    print(f"[TEST] Gefundene Encoder: {gefunden}")
    assert "CPU" in gefunden, "CPU muss immer in den gefundenen Encodern enthalten sein!"

    for name, ok, grund in protokoll:
        status = "OK   " if ok else "NEIN "
        zusatz = f" ({grund})" if grund else ""
        print(f"  {status} {name}{zusatz}")

    # Zusätzlicher Einzeltest für die vorhandenen Kandidaten
    for kennung in GST_HW_ENCODER:
        ok, grund = can_encode_with_gst(kennung)
        print(f"[TEST] can_encode_with_gst('{kennung}'): ok={ok}, grund={grund[:60] if grund else ''}")

    print("[ERFOLG] Alle Hardware-Encoder-Prüfungen wurden ohne Absturz durchlaufen.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
