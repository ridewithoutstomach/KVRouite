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

# core/standbild.py
"""
Ein einzelnes Bild aus einem Video als PNG - fuer den Merge-Fade.

Der Merge-Fade an einer Dateigrenze blendet vor der Naht das ERSTE Bild des
folgenden Videos als Standbild ein und nach der Naht das LETZTE Bild des
vorigen Videos wieder aus. Beide Videos laufen dabei ungekuerzt weiter; es
geht kein Bild und keine Millisekunde verloren. Was hier entsteht, sind genau
diese beiden Standbilder. Encoder (managers/ges_encoder_manager) und Vorschau
(core/fade_cache) legen sie als Bildclip mit Deckkraftrampe auf die Timeline.

Gezogen wird in voller Aufloesung der Quelle, ueber dieselbe Art Pipeline wie
die Bildleiste (core/thumb_cache._Greifer), nur ohne Verkleinerung und mit
bildgenauem Sprung (ACCURATE statt KEY_UNIT): das letzte Bild eines Videos
liegt selten auf einem Keyframe.

`gedreht` entscheidet, ob die Drehung aus dem Container (image-orientation)
schon eingerechnet ist. Encoder und Vorschau brauchen beide das GEDREHTE
Bild: GES richtet das Quellmaterial daneben nach seiner Kennzeichnung auf,
und ein PNG traegt keine. Das rohe Bild bleibt fuer Faelle, in denen der
Abnehmer selbst dreht.

Die Dateien liegen im Instanz-Temp-Ordner (config.TMP_FADE_DIR) neben den
Blenden und verschwinden mit ihm. Der Name enthaelt einen Hash ueber Datei,
Groesse, Aenderungszeit, Stelle und Drehung - dasselbe Bild wird nicht
zweimal gezogen.
"""

import hashlib
import os
import time

import config

NS = 1_000_000_000

#: Laenger darf das Ziehen eines Bildes nicht dauern.
ZEITGRENZE_S = 30.0


def _schluessel(pfad, sekunde, gedreht):
    try:
        st = os.stat(pfad)
        kennung = f"{pfad}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        kennung = f"{pfad}|?"
    stelle = "letztes" if sekunde is None else f"{float(sekunde):.6f}"
    text = f"{kennung}|{stelle}|{'gedreht' if gedreht else 'roh'}"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def pfad_fuer(pfad, sekunde, gedreht):
    """Wo das PNG liegt oder liegen wird."""
    return os.path.join(config.TMP_FADE_DIR,
                        f"still_{_schluessel(pfad, sekunde, gedreht)}.png")


def _letztes_bild(Gst, pipeline, senke, pfad):
    """Das letzte Bild der VIDEOSPUR, als Sample - oder None.

    Nicht "Dauer minus ein halbes Bild": die Dauer der Pipeline ist die des
    Containers, und die kann laenger sein als die Videospur. GoPro-Dateien
    fuehren Datenspuren (GPMF), die rund 0,1 s ueber das letzte Videobild
    hinausreichen - gemessen am 09.09.2026 an GX010037_last60.MP4: Container
    60,127 s, Videospur 60,018 s. Ein Sprung auf 60,110 s landet hinter dem
    letzten Bild, und es kommt nichts.

    Deshalb: ein Stueck vor das Ende springen, von dort bis zum Ende der
    Videospur durchlaufen lassen und das letzte gelieferte Bild nehmen. Das
    ist unabhaengig davon, was sonst noch in der Datei liegt. Kommt gar
    nichts, lag der Sprung selbst schon hinter dem Ende - dann weiter vorn
    noch einmal, bis zu 10 s.
    """
    ok, dauer = pipeline.query_duration(Gst.Format.TIME)
    if not ok or dauer <= 0:
        print(f"[STILL] Dauer nicht lesbar: {pfad}")
        return None
    frist = time.perf_counter() + ZEITGRENZE_S
    for rueckgriff_s in (1.0, 3.0, 10.0):
        ziel_ns = max(0, dauer - int(rueckgriff_s * NS))
        pipeline.seek_simple(Gst.Format.TIME,
                             Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                             ziel_ns)
        pipeline.get_state(int(ZEITGRENZE_S * NS))
        # sync=false an der Senke: das laeuft so schnell, wie dekodiert wird.
        pipeline.set_state(Gst.State.PLAYING)
        letztes = None
        anzahl = 0
        while time.perf_counter() < frist:
            # Blockiert bis zum naechsten Bild; None heisst Ende der Spur.
            probe = senke.emit("pull-sample")
            if probe is None:
                break
            letztes = probe
            anzahl += 1
        pipeline.set_state(Gst.State.PAUSED)
        pipeline.get_state(int(ZEITGRENZE_S * NS))
        if letztes is not None:
            puffer = letztes.get_buffer()
            print(f"[STILL] letztes Bild von {os.path.basename(pfad)}: "
                  f"{anzahl} Bild(er) ab {ziel_ns / NS:.3f}s durchlaufen, "
                  f"Bild bei {puffer.pts / NS:.3f}s, Container {dauer / NS:.3f}s")
            return letztes
        if time.perf_counter() >= frist:
            break
    print(f"[STILL] Kein letztes Bild gefunden in {pfad} "
          f"(Container {dauer / NS:.3f}s)")
    return None


def standbild(pfad, sekunde=None, gedreht=False):
    """
    Das Bild bei `sekunde` (None: das letzte Bild der Datei) als PNG.

    Rueckgabe: Pfad des PNG, oder None wenn es nicht ging. Ein bereits
    vorhandenes PNG wird nicht neu gezogen.
    """
    ziel = pfad_fuer(pfad, sekunde, gedreht)
    try:
        if os.path.getsize(ziel) > 0:
            return ziel
    except OSError:
        pass

    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst, GLib
        if not Gst.is_initialized():
            Gst.init(None)
    except Exception as exc:
        print(f"[STILL] GStreamer nicht verfuegbar: {exc}")
        return None

    t0 = time.perf_counter()
    uri = GLib.filename_to_uri(os.path.abspath(pfad), None)
    drehung = "videoflip method=automatic ! " if gedreht else ""
    pipeline = None
    try:
        # RGB statt BGRx: QImage schreibt daraus direkt ein PNG, ohne
        # Kanaele umzusortieren.
        pipeline = Gst.parse_launch(
            f'uridecodebin uri="{uri}" ! videoconvert ! {drehung}'
            'video/x-raw,format=RGB ! '
            'appsink name=s sync=false max-buffers=1 drop=false')
        senke = pipeline.get_by_name("s")
        pipeline.set_state(Gst.State.PAUSED)
        if pipeline.get_state(int(ZEITGRENZE_S * NS))[0] \
                == Gst.StateChangeReturn.FAILURE:
            print(f"[STILL] Datei nicht lesbar: {pfad}")
            return None

        if sekunde is None:
            probe = _letztes_bild(Gst, pipeline, senke, pfad)
        else:
            ziel_ns = int(max(0.0, float(sekunde)) * NS)
            pipeline.seek_simple(Gst.Format.TIME,
                                 Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                                 ziel_ns)
            pipeline.get_state(int(ZEITGRENZE_S * NS))
            probe = senke.emit("pull-preroll")
            if probe is None:
                print(f"[STILL] Kein Bild bei {ziel_ns / NS:.3f}s in {pfad}")
        if probe is None:
            return None
        puffer = probe.get_buffer()
        struktur = probe.get_caps().get_structure(0)
        breite = struktur.get_value("width")
        hoehe = struktur.get_value("height")
        ok, karte = puffer.map(Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            # copy(): der Speicher gehoert GStreamer und wird gleich wieder
            # freigegeben - dieselbe Vorsichtsmassnahme wie in der Bildleiste.
            from PySide6.QtGui import QImage
            bild = QImage(bytes(karte.data), breite, hoehe, breite * 3,
                          QImage.Format_RGB888).copy()
        finally:
            puffer.unmap(karte)
    except Exception as exc:
        print(f"[STILL] Bild nicht ziehbar aus {pfad}: {exc}")
        return None
    finally:
        if pipeline is not None:
            try:
                pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass

    try:
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
    except OSError:
        pass
    if not bild.save(ziel, "PNG"):
        print(f"[STILL] PNG nicht schreibbar: {ziel}")
        return None
    print(f"[STILL] {os.path.basename(pfad)} @ "
          f"{'letztes Bild' if sekunde is None else ('%.3fs' % sekunde)}"
          f"{', gedreht' if gedreht else ''}: {breite}x{hoehe}, "
          f"{time.perf_counter() - t0:.2f}s")
    return ziel
