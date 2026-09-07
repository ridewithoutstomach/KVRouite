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

# core/thumb_cache.py
"""Vorschaubilder fuer die Zeitleiste.

Holt einzelne Bilder aus den Videodateien und haelt sie im Speicher. Die
Zeitleiste fragt nur ab, was sie zeichnen will; was fehlt, wird im
Hintergrund nachgeholt und per Signal gemeldet.

Gemessen an einer 4K-GoPro-Datei (11,9 GB, 35 min, externe Platte):
24 Bilder zu 160 px Breite in 3,4 s, im Mittel 111 ms je Bild.

Zwei Dinge machen das schnell, und beide muessen so bleiben:

  * Gesprungen wird auf KEYFRAMES (Gst.SeekFlags.KEY_UNIT). Ohne das muesste
    der Decoder den Vorlauf bis zum Zielbild mitrechnen.
  * Die Pipeline bleibt je Datei OFFEN. Sie fuer jedes Bild neu aufzubauen
    kostet ein Vielfaches der eigentlichen Arbeit.
"""

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage


class ThumbCache(QObject):
    """Vorschaubilder holen und vorhalten.

    Der Ladevorgang laeuft in einem eigenen Faden, nacheinander und nicht
    parallel: die Dateien liegen ueblicherweise auf derselben Platte, zwei
    Laeufe wuerden sich beim Lesen gegenseitig ausbremsen.
    """

    #: Es sind neue Bilder da (die Zeitleiste soll sich neu zeichnen).
    bilderBereit = Signal()

    #: Zeitpunkte werden auf diese Genauigkeit gerundet. Feiner waere sinnlos:
    #: gesprungen wird ohnehin auf den naechsten Keyframe, und bei GoPro liegen
    #: die rund eine halbe Sekunde auseinander.
    RASTER_S = 0.5

    #: Obergrenze fuer den Speicher. Ein Bild zu 160x90 in BGRx sind rund
    #: 58 KB, 400 Bilder also etwa 23 MB.
    MAX_BILDER = 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bilder = {}            # (datei, zeit_gerastert) -> QImage
        self._reihenfolge = []       # fuers Verwerfen der aeltesten
        self._offen = []             # noch zu holen
        self._sperre = threading.Lock()
        self._faden = None
        self._abbrechen = False
        # Ob gerade ein Ladefaden arbeitet. Wird vom Faden SELBST unter der
        # Sperre gesetzt und geloescht - is_alive() reicht dafuer nicht: der
        # Faden ist zwischen seinem letzten Auftrag und seinem tatsaechlichen
        # Ende noch "am Leben", und in diesem Fenster wuerde ein neuer
        # Auftrag weder ihn erreichen noch einen neuen Faden starten.
        self._laeuft = False
        self._hoehe = 72

    # ------------------------------------------------------------------
    # Abfrage durch die Zeitleiste
    # ------------------------------------------------------------------
    def bild(self, datei, zeit_s):
        """Das Bild zu dieser Stelle, oder None."""
        with self._sperre:
            return self._bilder.get((datei, self._raster(zeit_s)))

    def bild_oder_nachbar(self, datei, zeit_s, toleranz_s):
        """Das Bild zu dieser Stelle - notfalls das naechstgelegene.

        Beim Zoomen wechselt das Raster, und fuer die neuen Stellen ist noch
        nichts da. Ohne Ersatz bliebe der Streifen so lange leer, und genau
        dann verliert man die Orientierung. Ein leicht versetztes Bild ist
        allemal besser als eine Luecke; sobald das genaue geladen ist, wird
        es ohnehin ersetzt.

        Rueckgabe (bild, genau) - genau=False heisst: das ist ein Nachbar.
        """
        with self._sperre:
            treffer = self._bilder.get((datei, self._raster(zeit_s)))
            if treffer is not None:
                return treffer, True
            bestes, abstand = None, None
            for (d, t), bild in self._bilder.items():
                if d != datei:
                    continue
                a = abs(t - zeit_s)
                if a <= toleranz_s and (abstand is None or a < abstand):
                    bestes, abstand = bild, a
            return bestes, False

    def _raster(self, zeit_s):
        return round(float(zeit_s) / self.RASTER_S) * self.RASTER_S

    # ------------------------------------------------------------------
    # Anfordern
    # ------------------------------------------------------------------
    def anfordern(self, wuensche, hoehe):
        """wuensche: Liste aus (dateipfad, zeit_in_der_datei_s).

        Was schon da ist, wird uebergangen. Der Rest kommt in die Liste des
        Ladefadens; laeuft er noch nicht, wird er gestartet.
        """
        self._hoehe = max(24, int(hoehe))
        neu = []
        with self._sperre:
            vorhanden = set(self._bilder)
            gemerkt = set(self._offen)
            for datei, zeit_s in wuensche:
                schluessel = (datei, self._raster(zeit_s))
                if schluessel in vorhanden or schluessel in gemerkt:
                    continue
                neu.append(schluessel)
            if not neu:
                return 0
            self._offen.extend(neu)
            # Ein vorangegangenes verwerfen() hat vielleicht gerade das
            # Abbruchzeichen gesetzt. Es gilt nur fuer die alten Auftraege -
            # die neuen sollen laufen. Ohne diese Zeile blieb nach jedem
            # Projektwechsel alles liegen: verwerfen() setzte den Abbruch,
            # der noch laufende Faden beendete sich, und weil er in dem
            # Moment noch "am Leben" war, wurde kein neuer gestartet.
            self._abbrechen = False
            starten = not self._laeuft
            if starten:
                self._laeuft = True

        if starten:
            self._faden = threading.Thread(target=self._arbeiten, daemon=True)
            self._faden.start()
        return len(neu)

    def verwerfen(self):
        """Alles vergessen - etwa nach einem Wechsel der Playlist."""
        self._abbrechen = True
        with self._sperre:
            self._bilder.clear()
            self._reihenfolge.clear()
            self._offen.clear()

    # ------------------------------------------------------------------
    # Ladefaden
    # ------------------------------------------------------------------
    def _arbeiten(self):
        pipelines = {}
        try:
            while True:
                with self._sperre:
                    # Ende und Flag IN EINEM Zug unter der Sperre - sonst
                    # entsteht ein Fenster, in dem der Faden schon aufhoert,
                    # aber noch als laufend gilt.
                    if self._abbrechen or not self._offen:
                        self._laeuft = False
                        break
                    # Nach Datei gruppieren, damit die Pipeline nicht staendig
                    # gewechselt wird.
                    self._offen.sort(key=lambda s: (s[0], s[1]))
                    datei, zeit_s = self._offen.pop(0)

                bild = None
                try:
                    pl = pipelines.get(datei)
                    if pl is None:
                        pl = _Greifer(datei, self._hoehe)
                        pipelines[datei] = pl
                    bild = pl.bild_bei(zeit_s)
                except Exception as e:
                    print(f"[THUMB] {Path(datei).name} @ {zeit_s:.1f}s: {e}")

                if bild is not None:
                    with self._sperre:
                        self._bilder[(datei, zeit_s)] = bild
                        self._reihenfolge.append((datei, zeit_s))
                        while len(self._reihenfolge) > self.MAX_BILDER:
                            alt = self._reihenfolge.pop(0)
                            self._bilder.pop(alt, None)
                    self.bilderBereit.emit()
        finally:
            with self._sperre:
                self._laeuft = False
            for pl in pipelines.values():
                try:
                    pl.schliessen()
                except Exception:
                    pass


class _Greifer:
    """Eine offene Pipeline auf einer Datei, aus der Bilder gezogen werden."""

    #: Laenger darf ein einzelnes Bild nicht brauchen.
    ZEITGRENZE_S = 10.0

    def __init__(self, datei, hoehe):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        self._Gst = Gst
        if not Gst.is_initialized():
            Gst.init(None)

        uri = Path(datei).as_uri()
        # videoscale mit fester HOEHE: die Breite ergibt sich aus dem
        # Seitenverhaeltnis der Quelle. Sonst waeren 360-Aufnahmen (2:1)
        # genauso breit wie 16:9-Material und im Streifen verzerrt.
        #
        # pixel-aspect-ratio=1/1 ist dabei nicht optional: ohne die Angabe
        # laesst videoscale die Breite stehen und passt stattdessen das
        # Pixel-Seitenverhaeltnis an. Gemessen kamen so 3840x72 heraus - ein
        # Bild von 1 MB statt 36 KB, und im Streifen waere es 3840 px breit.
        #
        # videoflip method=automatic wertet den image-orientation-Tag aus, den
        # qtdemux aus der Drehmatrix der Datei liest. Ohne ihn steht Material
        # einer kopfueber montierten Kamera im Streifen auf dem Kopf - der
        # Player zeigt es richtig, weil GES den Tag von sich aus beachtet.
        self._pipeline = Gst.parse_launch(
            f'uridecodebin uri="{uri}" ! videoconvert ! '
            'videoflip method=automatic ! videoscale ! '
            f'video/x-raw,format=BGRx,height={int(hoehe)},'
            'pixel-aspect-ratio=1/1 ! '
            'appsink name=s sync=false max-buffers=1 drop=false'
        )
        self._senke = self._pipeline.get_by_name("s")
        self._pipeline.set_state(Gst.State.PAUSED)
        self._pipeline.get_state(Gst.CLOCK_TIME_NONE)

    def bild_bei(self, zeit_s):
        Gst = self._Gst
        t0 = time.perf_counter()
        self._pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(max(0.0, float(zeit_s)) * Gst.SECOND))
        self._pipeline.get_state(Gst.CLOCK_TIME_NONE)
        if time.perf_counter() - t0 > self.ZEITGRENZE_S:
            return None

        probe = self._senke.emit("pull-preroll")
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
            # freigegeben - dieselbe Vorsichtsmassnahme wie im Player.
            bild = QImage(bytes(karte.data), breite, hoehe,
                          breite * 4, QImage.Format_RGB32).copy()
        finally:
            puffer.unmap(karte)
        return bild

    def schliessen(self):
        try:
            self._pipeline.set_state(self._Gst.State.NULL)
        except Exception:
            pass
