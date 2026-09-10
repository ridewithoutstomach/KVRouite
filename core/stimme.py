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

# core/stimme.py
"""
Stimmen aus der Tonspur entfernen (ab 7.0) - der "Voice Remover".

WAS ES TUT
----------
Ein Trennmodell zerlegt die Tonspur einer Quelldatei in "Stimme" und "alles
andere" und KVRouite behaelt das andere. Es gibt keinen Schritt "Stimme
finden": das Modell hoert die ganze Spur ab, und wo niemand spricht, bleibt
der Ton, wie er war. Zwei Modelle stehen zur Wahl (MODELLE), beide werden
mit der App ausgeliefert (Ordner voice_models neben dem Programm, siehe
tools/modelle_holen.py) - KVRouite laedt nichts nach.

    mdx     UVR-MDX-NET-Inst_HQ_3, trainiert vom UVR-Team, laeuft ueber
            onnxruntime. Liefert die Spur ohne Stimme direkt.
    demucs  htdemucs (Demucs v4, Meta), laeuft ueber torch. Liefert vier
            Spuren; KVRouite nimmt die Stimme und zieht sie vom Original ab.

Gemessen am 10.09.2026 an einer GoPro-Aufnahme mit Gespraech (5 min, CPU):
MDX 181 s, Demucs 252 s. Demucs liess das Fahrgeraeusch mehr in Ruhe (im
Mittel 1,0 dB Verlust gegen 3,3 dB bei MDX), beide nahmen die Stimme um bis
zu 13-15 dB heraus. Beide Modelle sind fuer Gesang in Musik trainiert;
Sprache im Fahrtwind ist fuer sie ein Grenzfall.

WER RUFT AUF
------------
managers/ges_encoder_manager.ges_xfade_main - je Quelldatei einmal, mit
Zwischenspeicher: entfernen(). Das Ergebnis ist eine WAV-Datei (44,1 kHz,
Stereo, so wie die Modelle rechnen), die beim Bau der Timeline als Tonspur
an die Stelle des Originaltons tritt. Der Verkehrsdaempfer (core/verkehr)
faehrt danach diese WAV ab statt der Quelldatei.

DIE BIBLIOTHEK
--------------
python-audio-separator (MIT, Andrew Beveridge) - der Trennkern von
Ultimate Vocal Remover als Bibliothek, ohne dessen Tkinter-Oberflaeche.
Sie zieht torch, onnxruntime, librosa, scipy und numpy nach sich. Importiert
wird sie erst hier drin und erst beim ersten Gebrauch: der Import kostet
Sekunden und rund 500 MB Speicher, das soll kein Programmstart bezahlen.

Ein Paket der Bibliothek liefert KVRouite NICHT aus: "diffq-fixed" (unter
Windows), Creative Commons BY-NC. An seiner Stelle installiert
requirements.txt die Platzhalter aus tools/diffq_platzhalter unter genau
den Namen, die die Bibliothek verlangt - pip fragt PyPI dann gar nicht mehr
danach. Auf Python 3.14 waere es anders auch nicht gegangen: fuer diffq-fixed
gibt es dort kein Wheel, und sein Quellpaket baut nicht (bitpack.pyx fehlt)
- gemeldet am 10.09.2026.

ZWISCHENSPEICHER
----------------
Die fertige WAV liegt unter config.TEMP_SEGMENTS_CONTAINER/stimme/, benannt
nach Pfad, Groesse und Aenderungszeit der Quelle und dem Modell. Ein
zweiter Export derselben Datei rechnet nicht noch einmal.
"""

import hashlib
import importlib.util
import logging
import os
import threading
import time

import config

#: Kennung -> (Modelldatei, Anzeigename)
MODELLE = {
    "mdx": ("UVR-MDX-NET-Inst_HQ_3.onnx", "MDX-Net (UVR)"),
    "demucs": ("htdemucs.yaml", "Demucs v4 (Meta)"),
}
VORGABE = "mdx"

#: Abtastrate und Kanaele, mit denen die Modelle rechnen.
RATE = 44100
KANAELE = 2

#: Rand um jeden Bereich, der getrennt wird (Sekunden je Seite): Kontext
#: fuer das Modell an den Kanten und Luft fuer das Bildraster. Getrennt wird
#: nur, was die Timeline braucht (ges_encoder_manager._ton_bereiche), nicht
#: die ganze Datei - bei einem Schnitt von vier Minuten aus fuenf spart das
#: vier Fuenftel der Rechenzeit (Berns Einwand am 10.09.2026).
RAND_S = 2.0

#: Aendert sich an der Behandlung etwas, zaehlt das hoch - alte WAVs im
#: Zwischenspeicher werden dann nicht mehr benutzt.
VERSION = 1

#: Was audio-separator neben den Modelldateien selbst braucht.
MODELL_METADATEN = ("download_checks.json", "mdx_model_data.json",
                    "vr_model_data.json")


class Abgebrochen(Exception):
    """Der Anwender hat waehrend der Trennung abgebrochen."""


# ---------------------------------------------------------------------------
# Vorhanden?
# ---------------------------------------------------------------------------

def modellordner():
    """Der Ordner mit den Modelldateien: voice_models neben dem Programm."""
    return config.finde_datei("voice_models")


#: Dateien, die das Voice-Zusatzpaket in die gepackte App bringt und ohne
#: die der Voice Remover nicht laeuft. Relativ zu _internal (sys._MEIPASS).
#: torch/lib traegt die Rechenbibliotheken, onnxruntime/capi die
#: Laufzeit, audio_separator seine Datendateien, voice_models die Modelle.
ZUSATZ_MERKMALE = (
    os.path.join("torch", "lib"),
    os.path.join("onnxruntime", "capi"),
    "audio_separator",
    "voice_models",
)


def zusatz_installiert():
    """Gepackte App: liegen die Dateien des Voice-Zusatzpakets in _internal?

    Die Grund-App ("Lite") traegt den Python-Code der Voice-Bibliotheken im
    Archiv der exe, aber nicht deren Binaerdateien und Modelle - die kommen
    mit dem Zusatzpaket (build_with_pyinstaller.py teilt den Bau auf). Ein
    "import torch" liefe ohne sie in einen Fehler, und importlib.find_spec
    faende das Modul trotzdem - deshalb wird hier nach DATEIEN gesehen.
    """
    import sys
    basis = getattr(sys, "_MEIPASS", None)
    if not basis:
        return True             # ungepackt: pip entscheidet, siehe verfuegbar()
    return all(os.path.isdir(os.path.join(basis, teil)) for teil in ZUSATZ_MERKMALE)


def verfuegbar(modell=None):
    """(True, "") wenn die Bibliothek und die Modelldatei(en) da sind, sonst
    (False, Grund). Importiert nichts Schweres - nur nachsehen."""
    import sys
    if getattr(sys, "frozen", False):
        # Gepackte App: der Anwender hat Zip oder Installer, nie pip. Die
        # Meldung nennt deshalb die Datei, die er braucht.
        if not zusatz_installiert():
            version = getattr(config, "APP_VERSION", "")
            return False, (f"install the KVRouite Voice add-on: unpack "
                           f"KVRouite_{version}_Voice_Win_x64.zip into the "
                           f"KVRouite folder, or run "
                           f"KVRouite_v{version}_Voice_Win_x64_Installer.exe")
    else:
        # Aus dem Quelltext gestartet: hier ist pip der Weg.
        for paket in ("audio_separator", "torch", "onnxruntime"):
            if importlib.util.find_spec(paket) is None:
                return False, (f"the package {paket} is not installed "
                               f"(pip install -r requirements-voice.txt)")
    ordner = modellordner()
    if not os.path.isdir(ordner):
        return False, f"the folder voice_models is missing ({ordner})"
    kennungen = [modell] if modell else list(MODELLE)
    for kennung in kennungen:
        datei = MODELLE.get(kennung, (None, None))[0]
        if not datei or not os.path.isfile(os.path.join(ordner, datei)):
            return False, f"model file {datei} is missing in {ordner}"
    return True, ""


# ---------------------------------------------------------------------------
# Zwischenspeicher
# ---------------------------------------------------------------------------

def _kennung(pfad, modell, von_s=0.0, bis_s=None):
    try:
        st = os.stat(pfad)
        text = f"{os.path.abspath(pfad)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        text = os.path.abspath(pfad)
    text += f"|{modell}|{MODELLE[modell][0]}|v{VERSION}"
    # Der Bereich gehoert zum Schluessel: eine andere Schnittliste braucht
    # andere Bereiche, dieselbe findet ihre WAVs wieder.
    text += f"|{von_s:.3f}|{'ende' if bis_s is None else f'{bis_s:.3f}'}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


def _cache_ordner():
    return os.path.join(config.TEMP_SEGMENTS_CONTAINER, "stimme")


def cache_datei(pfad, modell, von_s=0.0, bis_s=None):
    """Wo die WAV ohne Stimme fuer diesen Bereich der Quelle liegt (oder
    laege). von_s/bis_s in Sekunden der Datei; bis_s None = bis zum Ende."""
    return os.path.join(_cache_ordner(),
                        f"{_kennung(pfad, modell, von_s, bis_s)}_{modell}.wav")


def wav_dauer(pfad):
    """Laenge einer WAV in Sekunden, aus dem Kopf gelesen."""
    import wave
    with wave.open(pfad, "rb") as w:
        return w.getnframes() / float(w.getframerate() or RATE)


# ---------------------------------------------------------------------------
# Ton aus der Quelle ziehen
# ---------------------------------------------------------------------------

def quelle_als_wav(pfad, ziel, abbruch=None, fortschritt=None,
                   von_s=None, bis_s=None):
    """Die Tonspur der Quelldatei als WAV (RATE, KANAELE, 16 bit).

    playbin mit ausgeschaltetem Bild - nur der Ton wird dekodiert. Das ist
    derselbe Weg wie beim Pegelsucher (core/verkehr.pegel_messen); die
    Laufzeit geht ins Lesen der Videodaten von der Platte - bei einer
    4K-Datei von 2,5 GB gut eine halbe Minute fuer die ganze Datei.
    fortschritt(prozent) wird alle 200 ms mit der Lage gerufen, damit das
    Exportfenster in der Zeit nicht wie eingefroren wirkt.

    von_s/bis_s: nur diesen Bereich der Datei (Sekunden) - ein Sprung an den
    Anfang vor dem Abspielen, Halt am Ende. Dann wird auch nur dieser Teil
    der Datei gelesen. None = ganze Datei.
    """
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst, GLib
    if not Gst.is_initialized():
        Gst.init(None)

    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    senke = Gst.parse_bin_from_description(
        "audioconvert ! audioresample ! "
        f"audio/x-raw,format=S16LE,channels={KANAELE},rate={RATE},"
        "layout=interleaved ! wavenc ! filesink name=ziel", True)
    senke.get_by_name("ziel").set_property("location", ziel)
    play = Gst.ElementFactory.make("playbin", None)
    play.set_property("uri", GLib.filename_to_uri(os.path.abspath(pfad), None))
    play.set_property("flags", 0x02)            # AUDIO
    play.set_property("audio-sink", senke)
    bereich = von_s is not None or bis_s is not None
    if bereich:
        # Erst PAUSED und warten, bis die Pipeline steht - ein Sprung davor
        # geht ins Leere. Dann Anfang und Ende setzen, dann abspielen.
        if play.set_state(Gst.State.PAUSED) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("audio extraction pipeline did not start")
        play.get_state(30 * Gst.SECOND)
        start = int(round((von_s or 0.0) * Gst.SECOND))
        if bis_s is None:
            ok = play.seek(1.0, Gst.Format.TIME,
                           Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                           Gst.SeekType.SET, start, Gst.SeekType.NONE, -1)
        else:
            ok = play.seek(1.0, Gst.Format.TIME,
                           Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                           Gst.SeekType.SET, start,
                           Gst.SeekType.SET, int(round(bis_s * Gst.SECOND)))
        if not ok:
            play.set_state(Gst.State.NULL)
            raise RuntimeError(f"audio extraction: seek to {von_s}s failed")
    if play.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("audio extraction pipeline did not start")
    bus = play.get_bus()
    dauer_ns = 0
    gemeldet = -1
    anfang_ns = int(round((von_s or 0.0) * Gst.SECOND))
    try:
        while True:
            msg = bus.timed_pop_filtered(
                200 * Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if msg is None:
                if abbruch is not None and abbruch():
                    raise Abgebrochen()
                if fortschritt is not None:
                    if dauer_ns <= 0:
                        if bis_s is not None:
                            dauer_ns = int(round(bis_s * Gst.SECOND)) - anfang_ns
                        else:
                            ok, dauer_ns = play.query_duration(Gst.Format.TIME)
                            if not ok:
                                dauer_ns = 0
                            dauer_ns -= anfang_ns
                    ok, lage = play.query_position(Gst.Format.TIME)
                    if ok and dauer_ns > 0:
                        prozent = min(100, int((lage - anfang_ns) * 100 / dauer_ns))
                        if prozent > gemeldet:
                            gemeldet = prozent
                            fortschritt(prozent)
                continue
            if msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                raise RuntimeError(f"audio extraction failed: {err.message}")
            break
    finally:
        play.set_state(Gst.State.NULL)
    if not os.path.isfile(ziel) or os.path.getsize(ziel) < 1000:
        raise RuntimeError("audio extraction produced no data")
    return ziel


# ---------------------------------------------------------------------------
# Trennen
# ---------------------------------------------------------------------------

#: Der laufende Auftrag fuer die tqdm-Umleitung: [melden, stopp, laufender
#: Balken, Nummer des Balkens]. Modulweit, weil die Bibliothek tqdm nur
#: EINMAL importiert ("from tqdm import tqdm" in ihren Modulen) - die
#: Unterklasse wird also nur einmal eingesetzt und muss bei jedem Auftrag
#: hier nachsehen, wen sie rufen soll. Beim ersten Bau am 10.09.2026 hing
#: sonst jede weitere Datei am Ruf der ersten.
_auftrag = [None, None, None, 0]


def _tqdm_umleiten(melden, stopp):
    """Die Fortschrittsbalken der Bibliothek auf unseren Ruf umlenken.

    audio-separator zaehlt seine Rechenschritte mit tqdm; das schreibt
    Balken nach stderr, im Exportfenster ein Wust aus Zeilen. Hier wird
    tqdm.tqdm VOR dem Import der Bibliothek durch eine Unterklasse ersetzt,
    die je Schritt melden(durchgang, prozent) ruft und still bleibt. Ueber
    denselben Weg kommt der Abbruch in die Schleife: stopp ist ein
    threading.Event, das der Aufrufer setzt.

    Jeder Balken ist ein DURCHGANG ueber die Tonspur: MDX macht zwei,
    Demucs so viele, wie es Verschiebungen rechnet. Alle werden gemeldet,
    mit ihrer Nummer - bis 10.09.2026 nur der erste, und nach dessen "100%"
    stand das Fenster minutenlang ohne Meldung.
    """
    import tqdm as _tqdm

    _auftrag[0], _auftrag[1], _auftrag[2], _auftrag[3] = melden, stopp, None, 0
    if getattr(_tqdm, "_kvrouite_original", None) is not None:
        return          # schon eingesetzt - der Auftrag oben genuegt

    class _Still(_tqdm.tqdm):
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = False
            kwargs["file"] = open(os.devnull, "w")
            super().__init__(*args, **kwargs)
            _auftrag[3] += 1
            _auftrag[2] = self

        def update(self, n=1):
            super().update(n)
            ruf, halt, laufend, nummer = _auftrag
            if halt is not None and halt.is_set():
                raise Abgebrochen()
            if ruf is not None and laufend is self and self.total:
                ruf(nummer, min(100, int(self.n * 100 / self.total)))

    _tqdm._kvrouite_original = _tqdm.tqdm
    _tqdm.tqdm = _Still
    try:
        import tqdm.auto
        tqdm.auto.tqdm = _Still
    except Exception:
        pass


def _trennen(quelle_wav, modell, ausgabe_ordner, stamm, fortschritt, stopp):
    """Im Arbeitsfaden: die Bibliothek laufen lassen. Rueckgabe: die WAV,
    die KVRouite braucht - ohne Stimme bei MDX, NUR Stimme bei Demucs."""
    _tqdm_umleiten(fortschritt, stopp)
    from audio_separator.separator import Separator
    # audio-separator ruft beim Anlegen "ffmpeg -version" auf und bricht
    # ohne ffmpeg ab - es braucht ffmpeg aber nur, um andere Formate als WAV
    # zu schreiben. KVRouite liefert seit 6.0 kein ffmpeg mit und gibt hier
    # WAV hinein und WAV heraus; die Pruefung wird deshalb abgeschaltet.
    # Gesehen am 10.09.2026: "FFmpeg is not installed" in einer venv ohne
    # ffmpeg im Suchpfad, obwohl alles Noetige da war.
    Separator.check_ffmpeg_installed = lambda self: None
    datei, _name = MODELLE[modell]
    stem = "Instrumental" if modell == "mdx" else "Vocals"
    # use_soundfile: die Ausgabe ueber soundfile (libsndfile) schreiben, nicht
    # ueber pydub - pydub ruft auch fuer WAV ffmpeg auf und scheiterte ohne
    # ffmpeg mit "Failed to publish audio output ... with pydub" (10.09.2026).
    # log_level ERROR: die Bibliothek meldet "Using soundfile for writing"
    # als WARNING, und alles ab WARNING landet ueber stderr im Exportfenster.
    sep = Separator(output_dir=ausgabe_ordner, output_format="WAV",
                    model_file_dir=modellordner(), log_level=logging.ERROR,
                    output_single_stem=stem, use_soundfile=True)
    sep.load_model(model_filename=datei)
    ergebnis = sep.separate(quelle_wav, custom_output_names={stem: stamm})
    for name in ergebnis or []:
        pfad = name if os.path.isabs(name) else os.path.join(ausgabe_ordner, name)
        if os.path.isfile(pfad):
            return pfad
    raise RuntimeError("the separator wrote no output file")


def _abziehen(original_wav, stimme_wav, ziel):
    """Demucs: Original minus Stimme = alles andere. numpy kommt mit torch."""
    import wave
    import numpy as np

    def lesen(p):
        with wave.open(p, "rb") as w:
            rate, ch = w.getframerate(), w.getnchannels()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        return rate, ch, x.reshape(-1, ch).astype(np.int32)

    r1, c1, a = lesen(original_wav)
    r2, c2, b = lesen(stimme_wav)
    if r1 != r2 or c1 != c2:
        raise RuntimeError(f"vocal stem does not match the source "
                           f"({r2} Hz/{c2} ch vs {r1} Hz/{c1} ch)")
    n = min(len(a), len(b))
    rest = np.clip(a[:n] - b[:n], -32768, 32767).astype("<i2")
    with wave.open(ziel, "wb") as w:
        w.setnchannels(c1)
        w.setsampwidth(2)
        w.setframerate(r1)
        w.writeframes(rest.tobytes())


def entfernen(pfad, modell=VORGABE, log=None, fortschritt=None, abbruch=None,
              bereiche=None):
    """Die Tonspur der Quelldatei ohne Stimme, als WAVs im Zwischenspeicher.

    bereiche: [(von_s, bis_s), ...] - nur diese Teile der Datei werden
    ausgelesen und getrennt (ges_encoder_manager._ton_bereiche). None heisst
    die ganze Datei.

    Rueckgabe: [(von_s, bis_s, wav), ...] - je Bereich die WAV, die bei
    von_s beginnt; bis_s ist ihr wirkliches Ende (aus der WAV gelesen).
    fortschritt(prozent) wird waehrend der Trennung gerufen, abbruch()
    alle 200 ms gefragt; True darin fuehrt zu Abgebrochen.
    """
    log = log or (lambda text: None)
    if modell not in MODELLE:
        raise ValueError(f"unknown voice model '{modell}'")
    ok, grund = verfuegbar(modell)
    if not ok:
        raise RuntimeError(f"voice removal is not available: {grund}")
    if not bereiche:
        bereiche = [(0.0, None)]

    ergebnis = []
    for von_s, bis_s in bereiche:
        von_s = float(von_s or 0.0)
        bis_s = None if bis_s is None else float(bis_s)
        wav = _bereich_entfernen(pfad, modell, von_s, bis_s, log, fortschritt,
                                 abbruch)
        ergebnis.append((von_s, von_s + wav_dauer(wav), wav))
    return ergebnis


def _bereich_entfernen(pfad, modell, von_s, bis_s, log, fortschritt, abbruch):
    """Ein Bereich der Datei: auslesen, trennen, in den Zwischenspeicher."""
    name = os.path.basename(pfad)
    if bis_s is not None or von_s > 0:
        name += f" {von_s:.0f}-{'end' if bis_s is None else f'{bis_s:.0f}'}s"
    ziel = cache_datei(pfad, modell, von_s, bis_s)
    if os.path.isfile(ziel) and os.path.getsize(ziel) > 1000:
        log(f"[VOICE] {name}: from cache ({MODELLE[modell][1]})")
        return ziel

    ordner = _cache_ordner()
    os.makedirs(ordner, exist_ok=True)
    stamm = os.path.splitext(os.path.basename(ziel))[0]
    quelle = os.path.join(ordner, stamm + "_quelle.wav")

    log(f"[VOICE] {name}: extracting the audio track...")
    t0 = time.time()
    zuletzt = [-1]

    def lese_fortschritt(prozent):
        if prozent // 10 != zuletzt[0]:
            zuletzt[0] = prozent // 10
            log(f"[VOICE] {name}: extracting {prozent:3d}%")
    quelle_als_wav(pfad, quelle, abbruch, lese_fortschritt,
                   None if (von_s <= 0 and bis_s is None) else von_s, bis_s)
    log(f"[VOICE] {name}: loading {MODELLE[modell][1]} and separating "
        f"{wav_dauer(quelle):.0f}s of audio - on the CPU this takes roughly "
        f"as long as the audio lasts, in several passes...")

    stopp = threading.Event()
    ergebnis = {}
    # Der Arbeitsfaden legt seinen Stand nur hier ab; ins Protokoll
    # schreibt AUSSCHLIESSLICH der Hauptfaden aus der Warteschleife unten.
    # log fuehrt ins Exportfenster (Qt), und Qt-Fenster duerfen nur vom
    # Hauptfaden angefasst werden - beim ersten Lauf am 10.09.2026 kam der
    # Ruf aus dem Arbeitsfaden, und die Oberflaeche stand ("Keine
    # Rueckmeldung"), waehrend die Rechnung weiterlief.
    stand = {"durchgang": 0, "prozent": -1}

    def melden(durchgang, prozent):
        stand["durchgang"], stand["prozent"] = durchgang, prozent

    def arbeit():
        try:
            ergebnis["pfad"] = _trennen(quelle, modell, ordner, stamm + "_stem",
                                        melden, stopp)
        except BaseException as exc:      # auch Abgebrochen
            ergebnis["fehler"] = exc

    faden = threading.Thread(target=arbeit, name="kvrouite-voice", daemon=True)
    faden.start()
    gemeldet = (0, -1)          # (Durchgang, Zehner)
    zuletzt_gemeldet = time.time()
    while faden.is_alive():
        faden.join(0.2)
        durchgang, prozent = stand["durchgang"], stand["prozent"]
        jetzt = time.time()
        if durchgang > 0 and (durchgang, prozent // 10) != gemeldet:
            # Je volle zehn Prozent eine Zeile, je Durchgang eine Reihe.
            gemeldet = (durchgang, prozent // 10)
            log(f"[VOICE] {name}: pass {durchgang} {prozent:3d}%")
            zuletzt_gemeldet = jetzt
            if fortschritt is not None:
                fortschritt(prozent)
        elif jetzt - zuletzt_gemeldet >= 20.0:
            # Lebenszeichen, wenn die Bibliothek gerade nichts zaehlt: das
            # Laden des Modells, der Nachlauf, das Schreiben der Datei.
            was = "loading the model" if durchgang == 0 else "finishing"
            log(f"[VOICE] {name}: {was}, still working ({jetzt - t0:.0f}s)...")
            zuletzt_gemeldet = jetzt
        if abbruch is not None and abbruch():
            stopp.set()
    fehler = ergebnis.get("fehler")
    if isinstance(fehler, Abgebrochen) or stopp.is_set():
        raise Abgebrochen()
    if fehler is not None:
        raise RuntimeError(f"voice separation failed: {fehler}")

    stem = ergebnis["pfad"]
    if modell == "mdx":
        os.replace(stem, ziel)
    else:
        log(f"[VOICE] {name}: subtracting the voice from the original...")
        _abziehen(quelle, stem, ziel)
        try:
            os.remove(stem)
        except OSError:
            pass
    try:
        os.remove(quelle)
    except OSError:
        pass
    log(f"[VOICE] {name}: done in {time.time() - t0:.0f}s")
    return ziel
