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

# core/sprache.py
"""
Sprechstellen in der Tonspur finden (ab 7.0) - der Zubringer des Voice
Removers.

WAS ES TUT
----------
Silero VAD (MIT, Silero Team; Modell silero_vad.onnx, 2,3 MB, in
voice_models/ neben den Trennmodellen) hoert die Tonspur in Schritten von
32 ms ab und sagt je Schritt, wie wahrscheinlich dort gesprochen wird. Aus
den Wahrscheinlichkeiten werden Sprechstellen: Anfang, wenn der Wert ueber
die Einschaltschwelle steigt, Ende, wenn er laenger als MIN_PAUSE_S unter
der Ausschaltschwelle bleibt; Rand dazu, nahe Stellen verschmolzen. Die
beiden Schwellen haengen an der EMPFINDLICHKEIT (1 bis 5, Regler auf der
Seite Audio) - der Anwender stellt nach, was der Detektor uebersieht oder
zu viel findet. Vollstaendig ist eine solche Erkennung nie; die Stellen sind
Vorschlaege, die in der Zeitleiste und im Audio Zoom nachgebessert werden.

Der Voice Remover trennt danach nur in den Sprechstellen (mit Rand) statt
im ganzen Material - siehe managers/ges_encoder_manager.ges_xfade_main.

Gemessen am 10.09.2026 an einer GoPro-Aufnahme mit Gespraech (5 min):
0,9 s Rechenzeit auf der CPU, 13 Sprechstellen; die Gegenprobe auf einer
Aufnahme ohne Gespraech (Wind, Reifen, Motorraeder) fand nichts.

WER RUFT AUF
------------
core/verkehr.analyse(): waehrend des Abfahrens der Tonspur liefert die
Pipeline die Abtastwerte in 16 kHz mono; wahrscheinlichkeiten() rechnet
daraus die Werte je Schritt, die mit dem Pegel zusammen im Zwischenspeicher
liegen. stellen() macht daraus die Sprechstellen - ohne Rechenlauf, deshalb
kann der Regler sofort wirken. views/mainwindow.stimmen_suchen() fuehrt das
zusammen.
"""

import importlib.util
import os

import config

#: Die Modelldatei in voice_models (tools/modelle_holen.py holt sie).
MODELL = "silero_vad.onnx"
#: Woher: das Repository von Silero, Datei src/silero_vad/data/silero_vad.onnx.
MODELL_URL = ("https://raw.githubusercontent.com/snakers4/silero-vad/master/"
              "src/silero_vad/data/silero_vad.onnx")

#: Womit das Modell rechnet: 16 kHz mono, Schritte von 512 Abtastwerten mit
#: 64 Werten Vorlauf aus dem vorigen Schritt.
RATE = 16000
SCHRITT = 512
VORLAUF = 64
SCHRITT_S = SCHRITT / float(RATE)

#: Empfindlichkeit -> (Einschalt-, Ausschaltschwelle) der Wahrscheinlichkeit.
#: 3 ist die Vorgabe; hoeher findet mehr (auch mehr Falsches), niedriger
#: weniger. Die Sonde am 10.09.2026 lief mit 0,5/0,35 und uebersah zwei
#: Gespraechsstellen - deshalb liegt die Vorgabe darunter.
SCHWELLEN = {
    1: (0.75, 0.50),
    2: (0.60, 0.40),
    3: (0.45, 0.25),
    4: (0.35, 0.18),
    5: (0.25, 0.12),
    # 6 und 7 (Bernd, 10.09.2026): fuer Stimmen im Wind, die das Modell nur
    # noch schwach hoert. Melden auch eher Voegel oder Bremsen.
    6: (0.15, 0.08),
    7: (0.08, 0.04),
}
EMPFINDLICHKEIT_VORGABE = 3
EMPFINDLICHKEIT_MAX = 7

#: Hochpass vor dem Detektor, in Hz - nur fuer das Suchen, der Ton im Export
#: bleibt unberuehrt. Gemessen am 10.09.2026 an Original_Voice.mp4: ab 3:40
#: liegt fast die ganze Energie unter 250 Hz (Wind am Mikrofon), das Modell
#: gab dort 0,00 aus; mit dem Hochpass fand es 4:46-5:01 wieder, die
#: Stellen davor blieben. 0 schaltet ihn ab.
HOCHPASS_HZ = 250.0
HOCHPASS_ORDNUNG = 4

#: Formregeln der Sprechstellen (Sekunden).
MIN_SPRACHE_S = 0.3     # kuerzere Stellen fallen weg
MIN_PAUSE_S = 0.6       # kuerzere Pausen bleiben Teil der Stelle
RAND_S = 0.3            # Rand um jede Stelle
LUECKE_S = 1.5          # naeher beieinander -> eine Stelle


#: QSettings-Schluessel der Empfindlichkeit (Knopf "Sens" im Video-Control).
#: Kein Teil der Encoder-Presets: sie beschreibt den Suchlauf, nicht den
#: Export.
EINSTELLUNG_KEY = "encoder/voice_sensitivity"


def modellpfad():
    return os.path.join(config.finde_datei("voice_models"), MODELL)


def verfuegbar():
    """(True, "") wenn onnxruntime, numpy und das Modell da sind."""
    for paket in ("onnxruntime", "numpy"):
        if importlib.util.find_spec(paket) is None:
            return False, f"the package {paket} is not installed"
    if not os.path.isfile(modellpfad()):
        return False, f"model file {MODELL} is missing in voice_models"
    return True, ""


def hochpass(x):
    """Das tiefe Wummern (Wind, Rumpeln) aus der Kopie fuer den Detektor
    nehmen - Butterworth-Hochpass HOCHPASS_HZ, ueber scipy, das mit dem
    Voice-Zusatz kommt. Fehlt scipy, bleibt der Ton wie er ist."""
    if not HOCHPASS_HZ or len(x) == 0:
        return x
    try:
        from scipy import signal
    except ImportError:
        return x
    import numpy as np
    sos = signal.butter(HOCHPASS_ORDNUNG, HOCHPASS_HZ, "highpass", fs=RATE,
                        output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def wahrscheinlichkeiten(proben):
    """Sprachwahrscheinlichkeit je Schritt aus 16-kHz-mono-Abtastwerten.

    proben: bytes, S16LE, oder eine Liste solcher Stuecke. Rueckgabe: Liste
    von Werten 0..1, je SCHRITT_S Sekunden einer. Laeuft ueber onnxruntime;
    numpy fuer die Eingabefelder, beides kommt mit dem Voice-Zusatz.
    """
    import numpy as np
    import onnxruntime as ort

    if isinstance(proben, (list, tuple)):
        proben = b"".join(proben)
    x = np.frombuffer(proben, dtype="<i2").astype(np.float32) / 32768.0
    x = hochpass(x)
    sitzung = ort.InferenceSession(modellpfad(), providers=["CPUExecutionProvider"])
    zustand = np.zeros((2, 1, 128), dtype=np.float32)
    vorlauf = np.zeros((1, VORLAUF), dtype=np.float32)
    rate = np.array(RATE, dtype=np.int64)
    werte = []
    for i in range(0, len(x) - SCHRITT + 1, SCHRITT):
        stueck = x[i:i + SCHRITT][None, :]
        eingabe = np.concatenate([vorlauf, stueck], axis=1)
        aus, zustand = sitzung.run(None, {"input": eingabe, "state": zustand,
                                          "sr": rate})
        werte.append(float(aus[0, 0]))
        vorlauf = eingabe[:, -VORLAUF:]
    return werte


def stellen(werte, empfindlichkeit=EMPFINDLICHKEIT_VORGABE, dauer_s=None):
    """Sprechstellen aus den Wahrscheinlichkeiten: [[von_s, bis_s], ...].

    Hysterese ueber die Schwellen der Empfindlichkeit, Mindestlaenge, Rand,
    Verschmelzen naher Stellen. dauer_s begrenzt das Ende (Laenge der Datei).
    """
    an_db, aus_db = SCHWELLEN.get(int(empfindlichkeit), SCHWELLEN[EMPFINDLICHKEIT_VORGABE])
    if dauer_s is None:
        dauer_s = len(werte) * SCHRITT_S
    roh = []
    an = False
    start = 0.0
    pause_seit = None
    for k, p in enumerate(werte):
        t = k * SCHRITT_S
        if not an and p >= an_db:
            an, start, pause_seit = True, t, None
        elif an:
            if p < aus_db:
                if pause_seit is None:
                    pause_seit = t
                elif t - pause_seit >= MIN_PAUSE_S:
                    roh.append([start, pause_seit])
                    an, pause_seit = False, None
            else:
                pause_seit = None
    if an:
        roh.append([start, len(werte) * SCHRITT_S])
    ergebnis = []
    for a, b in roh:
        if b - a < MIN_SPRACHE_S:
            continue
        a, b = max(0.0, a - RAND_S), min(dauer_s, b + RAND_S)
        if ergebnis and a - ergebnis[-1][1] < LUECKE_S:
            ergebnis[-1][1] = max(ergebnis[-1][1], b)
        else:
            ergebnis.append([a, b])
    return [[round(a, 2), round(b, 2)] for a, b in ergebnis if b > a]


def gesamt_s(stellen_liste):
    return sum(max(0.0, b - a) for a, b in stellen_liste)
