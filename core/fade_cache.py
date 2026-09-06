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

"""
Vorgerenderte Blenden fuer die GES-Vorschau.

Warum ueberhaupt: Eine Blende live zu mischen heisst, an dieser Stelle zwei
Videospuren gleichzeitig laufen zu lassen. Die zweite muss GStreamer mitten im
Abspielen in Betrieb nehmen - Datei oeffnen, an die Stelle springen,
vorpuffern. Bei mehreren GB grossen Quellen stockt das Bild dabei sichtbar,
und zwar genau dort, wo man die Blende beurteilen will. Verschieben laesst
sich das (Vorlauf), beseitigen nicht.

Deshalb wird jede Blende einmal als kleiner Clip gerendert und als fertiges
Stueck in die Timeline gelegt. Dann laeuft dort nur EIN Dekodierer auf einer
wenige MB grossen Datei. Gemessen an 4K-Material: rund 2,8 s Rechenzeit und
4 MB je Blende.

Gerendert wird mit GES: eine Miniatur-Timeline mit A unten, B oben und einer
Deckkraftrampe - dieselbe Konstruktion wie im GES-Encoder. Frueher lief das
ueber ffmpegs `xfade`-Filter; ffmpeg wird in KVRouite nur noch fuer den
Copy-Mode benutzt und kommt hier nicht mehr vor.

Die Blende liegt MITTIG auf der Schnittkante - bei 2 s je 1 s davor und
dahinter, wie in Schnittprogrammen ueblich. Der Export macht es genauso, damit
Vorschau und Ergebnis an derselben Stelle dasselbe zeigen.

Jede Seite der Blende besteht aus STUECKEN (Datei, Sekunde darin, Dauer), die
hintereinander die volle Blendenlaenge ergeben. Meist ist das ein einziges
Stueck. Laeuft das Fenster ueber eine Dateigrenze, sind es zwei - dieselbe
Zerlegung, die der Export macht (ges_encoder_manager._Quellen.stuecke). Bis
6.11 kannte ein Auftrag je Seite nur EINE Datei, und die Vorschau fiel an
jeder Dateigrenze stumm auf einen harten Schnitt zurueck, waehrend der Export
die Blende rendert. Gesehen am 06.09.2026 am Projekt Stelvio: Schnitt exakt
1 s vor bis 1 s nach der Grenze, Vorgabe 2 s, Vorschau ohne Blende.

Die Dateien liegen im Instanz-Temp-Ordner (config.TMP_FADE_DIR) und
verschwinden mit ihm. Der Name enthaelt einen Hash ueber alles, was das
Ergebnis bestimmt - aendert sich nichts, wird nicht neu gerendert.
"""

import hashlib
import os
import time

from PySide6.QtCore import QObject, QTimer, Signal

import config

# Aendert sich die Art, wie gerendert wird, muss der Zwischenspeicher
# ungueltig werden. Deshalb geht diese Marke in den Namen ein.
# 3: Stuecke je Seite statt einer Datei je Seite.
_RENDER_VERSION = "3"

_rotation_cache = {}


def source_rotation(path, ffprobe=None):
    """
    Drehung aus dem Container, in Grad. 0, wenn keine hinterlegt ist.

    Wichtig fuer die Vorschau: GoPro-Aufnahmen einer kopfueber montierten
    Kamera tragen -180. GES dreht jeden Clip einzeln anhand dieser Angabe.
    Haette der gerenderte Schnipsel sie nicht, laege er als einziger Clip
    anders herum in der Timeline.
    """
    try:
        st = os.stat(path)
        schluessel = (path, st.st_size, int(st.st_mtime))
    except OSError:
        return 0
    if schluessel in _rotation_cache:
        return _rotation_cache[schluessel]

    # Gelesen wird ueber core.framerate: dort fragt zuerst GStreamer
    # ("image-orientation"), und nur wenn sich die Angabe nicht eindeutig
    # zuordnen laesst, bleibt es bei 0. Die Vorschau ruft das beim
    # Laden fuer jede Datei auf - ein Prozessstart weniger je Datei.
    try:
        from core.framerate import drehung as _drehung
        wert = int(_drehung(path, ffprobe))
    except Exception:
        wert = 0
    _rotation_cache[schluessel] = wert
    return wert


class FadeJob:
    """Eine zu rendernde Blende.

    seite_a / seite_b: Liste von (Datei, Sekunde darin, Dauer) - die Stuecke
    der abgehenden und der ankommenden Seite, in Abspielreihenfolge. Ihre
    Dauern ergeben zusammen `duration`. Ein Stueck ohne ganzes Bild - etwa
    ein Rest von Nanosekunden an einer Dateigrenze - faellt beim Rastern in
    _ges_start weg.
    """

    def __init__(self, seite_a, seite_b, duration, width, fps):
        self.a = [(p, float(i), float(d)) for (p, i, d) in seite_a]
        self.b = [(p, float(i), float(d)) for (p, i, d) in seite_b]
        self.duration = float(duration)
        self.width = int(width)
        self.fps = fps              # (zaehler, nenner)

    def key(self):
        """Erkennungsmerkmal. Aendert sich eine Quelldatei, aendert sich der Hash."""
        teile = []
        for seite in (self.a, self.b):
            for (p, inp, d) in seite:
                try:
                    st = os.stat(p)
                    teile.append(f"{p}|{st.st_size}|{int(st.st_mtime)}"
                                 f"|{inp:.6f}|{d:.6f}")
                except OSError:
                    teile.append(f"{p}|?|{inp:.6f}|{d:.6f}")
            teile.append("/")
        teile.append(f"{self.duration:.6f}"
                     f"|{self.width}|{self.fps[0]}/{self.fps[1]}|v{_RENDER_VERSION}")
        h = hashlib.sha1("||".join(teile).encode("utf-8")).hexdigest()[:16]
        return h

    def beschreibung(self):
        """Fuer das Protokoll: die Stuecke beider Seiten, kurz."""
        def kurz(seite):
            return " + ".join(f"{os.path.basename(p)}@{i:.2f}s/{d:.2f}s"
                              for (p, i, d) in seite)
        return f"A: {kurz(self.a)} | B: {kurz(self.b)}"

    def path(self):
        return os.path.join(config.TMP_FADE_DIR, f"fade_{self.key()}.mp4")


class FadeRenderer(QObject):
    """
    Rendert Blenden nacheinander im Hintergrund.

    Nacheinander und nicht parallel: die Quellen liegen oft auf derselben
    Platte, und zwei Renderlaeufe wuerden sich beim Lesen gegenseitig
    ausbremsen statt zu beschleunigen.
    """

    #: Kommt die Pipeline so lange nicht voran, gilt der Lauf als haengend.
    STILLSTAND_GRENZE_S = 30.0
    #: Absolute Obergrenze je Blende, auch wenn es langsam vorangeht.
    GESAMT_GRENZE_S = 180.0
    #: Abstand der Protokollzeilen waehrend eines laufenden Auftrags.
    MELDEN_ALLE_S = 10.0

    #: (fertig, gesamt) - fuer eine Fortschrittsanzeige
    progress = Signal(int, int)
    #: alle angeforderten Blenden liegen vor
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = []
        self._current = None
        self._done = 0
        self._total = 0
        # Zustand des GES-Laufs. Der Bus wird per Zeitgeber abgefragt, damit
        # die Oberflaeche waehrenddessen bedienbar bleibt - dasselbe, was
        # ein eigener Prozess von sich aus erledigt haette.
        self._ges_pipeline = None
        self._ges_bus = None
        self._ges_aus = False
        self._ges_start_zeit = 0.0
        self._ges_letzte_pos = -1
        self._ges_still_seit = 0.0
        self._ges_gemeldet = 0.0
        # Wie oft ein Auftrag schon begonnen wurde. Ab dem dritten Anlauf
        # wird aufgegeben - dann stimmt etwas nicht, und ein Fenster, das
        # ewig bei 0/1 steht, ist das schlechteste Ergebnis.
        self._anlaeufe = {}
        self._ges_timer = QTimer(self)
        self._ges_timer.timeout.connect(self._ges_puls)

    # ------------------------------------------------------------------
    def ready_path(self, job):
        """Pfad der FERTIGEN Datei, oder None.

        Der gerade laufende Auftrag zaehlt ausdruecklich nicht: seine Datei
        existiert bereits und waechst noch. Ohne diese Abfrage hielt eine
        erneute Anforderung den halb geschriebenen Schnipsel fuer fertig -
        die Pruefung war nur "Groesse > 0". Der Auftrag fiel dann aus der
        Liste, cancel() loeschte die Datei wieder, und das Vorschau-Fenster
        blieb bei 0/1 stehen, ohne Fehlermeldung. Genau so gesehen beim
        Wechsel vom grossen zum kleinen Projekt, wo der Moduswechsel
        OFF -> ENCODE zusaetzliche Anforderungen ausloest.
        """
        laeuft = self._current
        if laeuft is not None and laeuft.key() == job.key():
            return None
        p = job.path()
        try:
            if os.path.getsize(p) > 0:
                return p
        except OSError:
            pass
        return None

    def request(self, jobs):
        """
        Blenden anfordern. Bereits vorhandene werden uebersprungen.

        Ein bereits LAUFENDER Auftrag wird weitergefuehrt, wenn er in der
        neuen Anforderung wieder vorkommt. Das ist wichtig, weil die Vorschau
        beim Laden mehrfach neu aufgebaut wird - unter anderem beim Wechsel
        des Bearbeitungsmodus. Wurde bei jeder Anforderung neu begonnen, kam
        derselbe Auftrag nie ans Ziel: das Fenster stand bei 0/1, waehrend im
        Log dreimal hintereinander derselbe Renderlauf startete.

        Rueckgabe: Anzahl der Blenden, die noch gerendert werden muessen.
        """
        offen = [j for j in jobs if self.ready_path(j) is None]
        laeuft = self._current
        if laeuft is not None and any(j.key() == laeuft.key() for j in offen):
            self._queue = [j for j in offen if j.key() != laeuft.key()]
            self._done = 0
            self._total = len(offen)
            print(f"[FADE] laufender Auftrag [{laeuft.key()[:8]}] wird "
                  f"fortgefuehrt, {len(self._queue)} weitere(r) wartend")
            self.progress.emit(0, self._total)
            return self._total

        if laeuft is not None:
            print(f"[FADE] laufender Auftrag [{laeuft.key()[:8]}] wird verworfen, "
                  f"angefordert: {[j.key()[:8] for j in offen]}")
        self.cancel()
        self._queue = offen
        self._done = 0
        self._total = len(offen)
        if not offen:
            self.finished.emit()
            return 0
        self.progress.emit(0, self._total)
        self._next()
        return self._total

    def cancel(self):
        """Laufende und wartende Auftraege verwerfen."""
        self._queue = []
        self._ges_stoppen()
        # Halb geschriebene Datei nicht liegen lassen - sie wuerde beim
        # naechsten Mal als "fertig" gelten.
        if self._current is not None:
            self._verwerfen(self._current)
            self._current = None

    def _verwerfen(self, job):
        try:
            p = job.path()
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

    # ------------------------------------------------------------------
    def _next(self):
        if not self._queue:
            self._current = None
            self.finished.emit()
            return

        job = self._queue.pop(0)
        self._current = job
        schluessel = job.key()
        self._anlaeufe[schluessel] = self._anlaeufe.get(schluessel, 0) + 1

        # Ab dem dritten Anlauf desselben Auftrags wird aufgegeben. Frueher
        # sprang hier ffmpeg ein; das gibt es nicht mehr - ffmpeg wird in
        # KVRouite nur noch fuer den Copy-Mode benutzt. Ein Schnitt ohne
        # Blende ist das kleinere Uebel gegenueber einem Fenster, das sich
        # endlos dreht.
        if self._anlaeufe[schluessel] >= 3:
            print(f"[FADE] [{schluessel[:8]}] dritter Anlauf - aufgegeben, "
                  f"dieser Schnitt bleibt ohne Blende")
            self._verwerfen(job)
            self._weiter()
            return

        # _ges_bereit() legt nebenbei die GStreamer-Versionen fest
        # (gi.require_version). Ohne diesen Aufruf importiert _ges_start()
        # ungebunden und GStreamer meldet eine PyGIWarning.
        if not self._ges_bereit():
            print(f"[FADE] [{schluessel[:8]}] GStreamer nicht verfuegbar - "
                  f"dieser Schnitt bleibt ohne Blende")
            self._verwerfen(job)
            self._weiter()
            return

        try:
            if self._ges_start(job):
                return
            print(f"[FADE] [{schluessel[:8]}] Renderlauf nicht startbar")
        except Exception as exc:
            print(f"[FADE] [{schluessel[:8]}] Renderlauf gescheitert: {exc}")
            self._ges_stoppen()
        self._verwerfen(job)
        self._weiter()

    # ------------------------------------------------------------------
    # Rendern ueber GES
    # ------------------------------------------------------------------
    # Dasselbe Verfahren wie bisher: jede Blende wird einmal vorgerendert und
    # als fertiger Clip in die Vorschau gelegt. Nur das Werkzeug wechselt -
    # GES statt ffmpeg. Die Warteschlange, die Zwischenspeicher-Schluessel,
    # die Signale und die Dateinamen sind dieselben geblieben.
    #
    # Aufbau der Miniatur-Timeline, gleich der im Encoder:
    #
    #     untere Ebene:  die Stuecke von A hintereinander, `duration` lang
    #     obere Ebene:   die Stuecke von B hintereinander, Deckkraft 0 -> 1
    #
    # Die Deckkraftrampe laeuft ueber die GANZE Blende. Besteht B aus zwei
    # Stuecken, bekommt jedes den Abschnitt der Rampe, der auf seinen Platz
    # entfaellt - Stuetzstellen in Medienzeit, ab dem inpoint des Stuecks,
    # wie _alpha_rampe() im Encoder.
    #
    # NICHT gedreht wird dabei mit Absicht. Die Vorschau legt jedem Clip die
    # Drehung des Quellmaterials auf, auch dem Schnipsel (siehe
    # ges_backend._apply_orientation). Waere er schon aufgerichtet, stuende er
    # anschliessend auf dem Kopf. Deshalb "video-direction = identity" - das
    # Gegenstueck zu "-noautorotate" im ffmpeg-Aufruf.

    def _ges_bereit(self):
        if self._ges_aus:
            return False
        try:
            import gi
            gi.require_version("Gst", "1.0")
            gi.require_version("GES", "1.0")
            gi.require_version("GstPbutils", "1.0")
            gi.require_version("GstController", "1.0")
            gi.require_version("GstVideo", "1.0")
            from gi.repository import Gst, GES
            if not Gst.is_initialized():
                Gst.init(None)
            GES.init()
            return Gst.ElementFactory.make("x265enc", None) is not None
        except Exception as exc:
            print(f"[FADE] GStreamer nicht verfuegbar: {exc}")
            self._ges_aus = True
            return False

    def _ges_start(self, job):
        """Baut die Timeline und startet den Render-Lauf. True, wenn er laeuft."""
        import gi
        from gi.repository import Gst, GES, GLib, GstPbutils, GstController, GstVideo

        num, den = job.fps
        ns = 1_000_000_000
        # Ein Bild weniger als bestellt: GES rechnet die Endkante mit und
        # liefert sonst ein Bild zu viel (gemessen 61 statt der bestellten 60
        # bei 2 s und 29,97 fps). Die Vorschau richtet sich ohnehin nach der
        # WIRKLICHEN Laenge des Schnipsels - siehe ges_backend._rebuild, wo
        # "vorne = dauer - halb" gerechnet wird -, aber je naeher die Laenge
        # an der Bestellung liegt, desto weniger verschiebt sich das
        # Folgematerial gegenueber dem Export.
        bilder = max(1, int(round(job.duration * num / den)) - 1)
        dauer_ns = bilder * den * ns // num

        def raster(sekunden):
            """Auf das Bildraster legen, in ns - wie _raster() im Encoder."""
            return int(round(sekunden * num / den)) * den * ns // num

        # Jede Datei einmal laden, auch wenn sie auf beiden Seiten vorkommt.
        assets = {}
        try:
            for (pfad, _i, _d) in job.a + job.b:
                if pfad not in assets:
                    assets[pfad] = GES.UriClipAsset.request_sync(
                        GLib.filename_to_uri(os.path.abspath(pfad), None))
        except Exception as exc:
            print(f"[FADE] Quelle nicht ladbar: {exc}")
            return False
        a = assets[job.a[0][0]]

        # Zielhoehe aus dem ROHEN Bild, weil nicht gedreht wird.
        hoehe = 0
        try:
            strom = a.get_info().get_video_streams()[0]
            hoehe = int(round(strom.get_height() * job.width
                              / float(strom.get_width())))
            if hoehe % 2:
                hoehe += 1
        except Exception:
            hoehe = 0
        if hoehe <= 0:
            print("[FADE] Bildgroesse der Quelle nicht lesbar")
            return False

        timeline = GES.Timeline.new_audio_video()
        for track in timeline.get_tracks():
            if track.get_property("track-type") == GES.TrackType.VIDEO:
                track.set_restriction_caps(Gst.Caps.from_string(
                    f"video/x-raw,width={job.width},height={hoehe},"
                    f"framerate={num}/{den}"))
        oben = timeline.append_layer()
        unten = timeline.append_layer()
        oben.set_auto_transition(False)
        unten.set_auto_transition(False)

        def ohne_drehung(clip):
            for el in clip.find_track_elements(None, GES.TrackType.VIDEO,
                                               GES.VideoSource):
                el.set_child_property("video-direction",
                                      GstVideo.VideoOrientationMethod.IDENTITY)
            return clip

        def stuecke_legen(layer, seite, mit_rampe):
            """Die Stuecke einer Seite luecklos hintereinander auf die Ebene.

            Jedes Stueck endet dort, wo es laut Blende enden soll, gerastert
            auf ganze Bilder. Reicht die Quelle nicht so weit - die Laenge
            aus der Playlist kann um ein Bild von dem abweichen, was GES in
            der Datei sieht -, wird es gekuerzt, und das naechste Stueck
            schliesst direkt an. Die Blende wird dann hoechstens ein Bild
            kuerzer; die Vorschau richtet sich ohnehin nach der WIRKLICHEN
            Laenge der Datei (ges_backend._rebuild).
            """
            lage = 0            # Platz auf der Timeline, ns
            versatz = 0.0       # Sekunde in der Blende, an der das Stueck beginnt
            for (pfad, inpoint_s, dauer_s) in seite:
                von = raster(versatz)
                bis = min(raster(versatz + dauer_s), dauer_ns)
                versatz += dauer_s
                if bis <= von:
                    continue    # kein ganzes Bild - Rest an einer Dateigrenze
                asset = assets[pfad]
                inpoint = raster(inpoint_s)
                rest = asset.get_duration() - inpoint
                if rest <= 0:
                    continue
                laenge = min(bis - von, rest)
                clip = layer.add_asset(asset, lage, inpoint, laenge,
                                       GES.TrackType.UNKNOWN)
                if clip is None:
                    raise RuntimeError(
                        f"Stueck nicht einsetzbar: {os.path.basename(pfad)}"
                        f"@{inpoint_s:.3f}s")
                ohne_drehung(clip)
                if mit_rampe:
                    for el in clip.find_track_elements(None, GES.TrackType.VIDEO,
                                                       GES.VideoSource):
                        quelle = GstController.InterpolationControlSource()
                        quelle.props.mode = GstController.InterpolationMode.LINEAR
                        el.set_control_source(quelle, "alpha", "direct")
                        quelle.set(inpoint, lage / dauer_ns)
                        quelle.set(inpoint + laenge, (lage + laenge) / dauer_ns)
                lage += laenge
            return lage

        if stuecke_legen(unten, job.a, False) <= 0:
            print("[FADE] abgehende Seite ohne Material")
            return False
        if stuecke_legen(oben, job.b, True) <= 0:
            print("[FADE] ankommende Seite ohne Material")
            return False
        timeline.commit_sync()

        behaelter = GstPbutils.EncodingContainerProfile.new(
            "KVRouite-Blende", None,
            Gst.Caps.from_string("video/quicktime,variant=iso"), None)
        # x265enc statt x264enc, und zwar aus einem gemessenen Grund:
        # x264enc nimmt in seinem CRF-Modus den "quantizer" nicht an. Gemessen
        # an 4 s echtem Material in 1280x720: mit quantizer 23 kamen 1,83 Mb/s
        # heraus, mit 30 genau 1,82 - der Wert wirkte also gar nicht, und der
        # Encoder blieb bei seiner Vorgabe (konstante Bitrate, 2048 kbit/s).
        # Deshalb sahen die ersten GES-Blenden sichtbar schlechter aus als die
        # von ffmpeg (1,52 gegen 14,14 Mb/s).
        # Bei x265enc greift "option-string=crf=N" nachweislich (crf 18 gegen
        # 35: 11,54 gegen 0,59 Mb/s), und das Quellmaterial ist ohnehin HEVC.
        video = GstPbutils.EncodingVideoProfile.new(
            Gst.Caps.from_string("video/x-h265"), None, None, 0)
        video.set_preset_name("x265enc")
        eig = Gst.Structure.new_empty("element-properties")
        probe = Gst.ElementFactory.make("x265enc", None)
        for name, wert in (("option-string", "crf=23"), ("speed-preset", "veryfast")):
            try:
                probe.set_property(name, wert)
                eig.set_value(name, probe.get_property(name))
            except Exception:
                pass
        video.set_element_properties(eig)
        behaelter.add_profile(video)

        # GES bricht hart ab, wenn der Zielordner fehlt ("Could not open file
        # ... for writing"). ffmpeg tut das auch, faellt dort aber weniger auf.
        try:
            os.makedirs(os.path.dirname(os.path.abspath(job.path())), exist_ok=True)
        except OSError:
            pass

        pipeline = GES.Pipeline()
        pipeline.set_timeline(timeline)
        if not pipeline.set_render_settings(
                GLib.filename_to_uri(os.path.abspath(job.path()), None), behaelter):
            print("[FADE] Render-Einstellungen abgelehnt")
            return False
        if not pipeline.set_mode(GES.PipelineFlags.RENDER):
            print("[FADE] Render-Modus liess sich nicht setzen")
            return False
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            print("[FADE] Pipeline startete nicht")
            return False

        self._ges_pipeline = pipeline
        self._ges_bus = pipeline.get_bus()
        self._ges_start_zeit = time.time()
        self._ges_letzte_pos = -1
        self._ges_still_seit = self._ges_start_zeit
        self._ges_gemeldet = self._ges_start_zeit
        print(f"[FADE] GES rendert {job.beschreibung()}, {job.duration:.2f}s, "
              f"{job.width}x{hoehe} @ {num}/{den} "
              f"[{job.key()[:8]}, Anlauf {self._anlaeufe.get(job.key(), 1)}]")
        self._ges_timer.start(50)
        return True

    def _ges_puls(self):
        """Nachsehen, ob der Lauf fertig ist - ohne die Oberflaeche zu blockieren."""
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        if self._ges_bus is None:
            # Der Bus ist weg, der Auftrag gilt aber noch als laufend.
            #
            # Frueher wurde hier nur der Timer gestoppt und zurueckgekehrt.
            # Damit stand die Zustandsmaschine still: "finished" kam nie,
            # das Fortschrittsfenster wartete endlos, und der Wachhund
            # weiter unten konnte nicht greifen - er lebt in genau dieser
            # Methode, die dann nicht mehr aufgerufen wurde.
            #
            # Gemessen am 30.08.2026: Prozess untaetig (0,06 s CPU in 20 s),
            # keine [FADE]-Zeile mehr nach "Anlauf 2", keine Blendendatei
            # angelegt, Fenster bei 0/1.
            self._ges_timer.stop()
            if self._current is not None:
                print(f"[FADE] [{self._current.key()[:8]}] Renderlauf ohne Bus "
                      f"- Auftrag verworfen")
                self._verwerfen(self._current)
                self._weiter()
            return
        msg = self._ges_bus.timed_pop_filtered(
            0, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if msg is None:
            # Ueberwachung: ein Renderlauf darf die Oberflaeche nicht
            # unbegrenzt blockieren. Kommt die Pipeline nicht voran, wird sie
            # abgebrochen und der Auftrag verworfen. Ohne das haengt das
            # Vorschau-Fenster bei 0/1, ohne Meldung und ohne Ausweg.
            jetzt = time.time()
            ok, pos = self._ges_pipeline.query_position(Gst.Format.TIME)
            if ok and pos > self._ges_letzte_pos:
                self._ges_letzte_pos = pos
                self._ges_still_seit = jetzt
            if jetzt - self._ges_gemeldet >= self.MELDEN_ALLE_S:
                self._ges_gemeldet = jetzt
                print(f"[FADE] laeuft seit {jetzt - self._ges_start_zeit:.0f}s, "
                      f"Position {max(0, self._ges_letzte_pos) / 1e9:.2f}s")
            stillstand = jetzt - self._ges_still_seit
            gesamt = jetzt - self._ges_start_zeit
            if stillstand > self.STILLSTAND_GRENZE_S or gesamt > self.GESAMT_GRENZE_S:
                grund = ("kein Fortschritt seit "
                         f"{stillstand:.0f}s" if stillstand > self.STILLSTAND_GRENZE_S
                         else f"laenger als {self.GESAMT_GRENZE_S:.0f}s gelaufen")
                print(f"[FADE] Renderlauf abgebrochen ({grund})")
                job = self._current
                self._ges_stoppen()
                if job is not None:
                    self._verwerfen(job)
                    self._current = None
                    self._next()
                else:
                    self._weiter()
            return
        fehler = None
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            fehler = f"{err.message} ({dbg})"
        self._ges_stoppen()
        if fehler:
            print(f"[FADE] Rendern fehlgeschlagen: {fehler}")
            if self._current is not None:
                self._verwerfen(self._current)
        elif self._current is not None:
            p = self._current.path()
            gr = os.path.getsize(p) if os.path.exists(p) else 0
            print(f"[FADE] [{self._current.key()[:8]}] fertig, {gr} Bytes")
        self._weiter()

    def _ges_stoppen(self):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        self._ges_timer.stop()
        self._ges_bus = None
        if self._ges_pipeline is not None:
            try:
                self._ges_pipeline.set_state(Gst.State.NULL)
                self._ges_pipeline.get_state(5 * Gst.SECOND)
            except Exception:
                pass
            self._ges_pipeline = None

    def _weiter(self):
        self._current = None
        self._done += 1
        self.progress.emit(min(self._done, self._total), self._total)
        self._next()
