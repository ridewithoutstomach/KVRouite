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
Der Wiedergabe-Player von KVRouite, auf Basis von GStreamer Editing
Services (GES).

Warum GES: ein reiner Player kann keine Blende zwischen zwei Clips zeigen und
keine 360-Grad-Projektion rechnen. GES ist eine Schnitt-Engine mit Timeline,
Spuren und Effekten und kann beides - und weil der Export dieselbe Timeline
baut, zeigt die Vorschau wirklich das, was hinterher herauskommt.

Modellunterschied, den diese Datei ueberbrueckt: die App denkt in einer
PLAYLIST, also Clip fuer Clip, und rechnet in "Index + Sekunde im Clip". GES
hat EINE Timeline mit einer durchgehenden Zeitachse. Hier liegen die Clips
deshalb nahtlos hintereinander, und Index/lokale Zeit werden auf
Timeline-Zeit umgerechnet (siehe _clip_at / _clip_start). Nach aussen
verhaelt sich der Player damit wie die Playlist, die das Widget erwartet.

Installation: `pip install gstreamer-bundle` (Windows/macOS, ab GStreamer
1.28). Unter Linux ueber die Distributionspakete (python3-gi, gir1.2-ges-1.0,
gstreamer1.0-plugins-base/good). Fehlt das Paket, wirft der Konstruktor
ImportError. Seit 6.0 gibt es dafuer keinen Ersatz mehr - ohne GStreamer
kann KVRouite kein Video abspielen, und der Start bricht mit einer Meldung
ab, die sagt, was zu installieren ist.

BLENDEN werden NICHT von GES gemischt. GES verdrahtet seinen Crossfade mit dem
Compositor-Operator "over" statt "source"/"add" und wird dadurch in der Mitte
zu dunkel (gemessen: 127 statt 150 bei einer Mischung aus 100 und 200); vor
allem aber muesste dafuer eine zweite Videospur mitten im Abspielen in Betrieb
gehen, was bei grossen Quelldateien sichtbar stockt. Stattdessen wird jede
Blende vorgerendert und als fertiger Clip eingesetzt - siehe core/fade_cache.py.
Sie liegt mittig auf der Schnittkante; die angrenzenden Stuecke werden dafuer um
je eine halbe Blendenlaenge gekuerzt, sodass die Gesamtlaenge gleich bleibt.

FEHLERVERHALTEN, bewusst zweigeteilt - die Aufrufer verlassen sich darauf:
  - Lesende Zugriffe (position, fps, video_size, ...) liefern ruhige Vorgaben,
    wenn nichts geladen ist. Die Aufrufer fangen das mit getattr/try-except
    ohnehin ab.
  - Steuernde Zugriffe (seek_local, play_index) reichen Fehler durch. Die
    Aufrufer fangen SystemError ab und setzen dann *bewusst* kein pause.
    Wuerde das Backend schlucken, aendert sich dieses Verhalten.

Die Zeitrechnung ueber mehrere Clips (boundaries, globale Zeit) liegt NICHT
hier, sondern im VideoEditorWidget - sie ist von der Wiedergabe unabhaengig.

BILDLAGE: GES stellt jeden Clip auf AUTO und liest die Drehung aus dem
Datenstrom. Kommt die Kennzeichnung nicht rechtzeitig, steht der Clip auf dem
Kopf - bei mehreren Clips mal dieser, mal jener. Deshalb wird sie hier fest
vorgegeben, siehe _orientation_method().

360 GRAD: der Shader haengt als GES.Effect an jedem Clip (core/view360.py)
und wirkt dadurch in der Vorschau genauso wie im Export - beide bauen dieselbe
Timeline. Ist 360 an, rechnet die Vorschau in 16:9 statt im 2:1-Format der
Quelle, denn 2:1 ist bei Equirect-Material die Kugel und kein Bildformat.
"""

import os
import platform
import time

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtGui import QImage

_GST_IMPORT_ERROR = None
try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GES', '1.0')
    gi.require_version('GstVideo', '1.0')
    gi.require_version('GstController', '1.0')
    gi.require_version('GstApp', '1.0')
    from gi.repository import Gst, GES, GstVideo, GstController, GstApp, GLib  # noqa: F401
except Exception as exc:            # pragma: no cover - haengt an der Umgebung
    _GST_IMPORT_ERROR = exc
    Gst = GES = GstVideo = GstController = GLib = None

from core import view360


def is_available():
    """True, wenn GStreamer/GES importierbar ist."""
    return _GST_IMPORT_ERROR is None


def unavailable_reason():
    return str(_GST_IMPORT_ERROR) if _GST_IMPORT_ERROR else ""


NS = 1_000_000_000



class _BildBruecke(QObject):
    """Bringt Bilder vom GStreamer-Thread in den Qt-Hauptthread.

    GStreamer ruft "new-sample" auf seinem eigenen Streaming-Thread auf. Ein
    Qt-Widget von dort aus anzufassen ist nicht erlaubt und faellt einem
    frueher oder spaeter auf die Fuesse - meist als sporadischer Absturz. Ein
    Qt-Signal loest das sauber: Qt legt es selbst in die Warteschlange des
    Hauptthreads, weil Sender und Empfaenger in verschiedenen Threads leben.
    """

    neuesBild = Signal(object)


class _AppsinkAnzeige:
    """Bilder abholen statt sie GStreamer anzeigen zu lassen.

    Statt in ein Fensterhandle zu zeichnen (d3d11videosink), liefert die
    Pipeline die fertigen Bilder hierher. Nur so kann Qt spaeter etwas
    darueber malen - Auswahlrahmen, Anfasser, Ziehen.

    BGRx ist mit Bedacht gewaehlt: vier Bytes je Bildpunkt, byteweise genau
    das, was QImage.Format_RGB32 erwartet. Es wird also nur kopiert, nicht
    umgerechnet. Gemessen an 4K-Material in 1280x720 bei 30 fps: 3,2 ms je
    Bild, also rund ein Zehntel des Zeitbudgets, und kein Bild verloren.
    """

    #: Wieviele Bilder die Senke zurueckhalten darf. Klein halten: bei einem
    #: Rueckstau soll das neueste Bild gezeigt werden, nicht ein altes.
    PUFFER = 2

    def __init__(self, rueckruf):
        self.bruecke = _BildBruecke()
        self.bruecke.neuesBild.connect(rueckruf)
        self.bin = Gst.parse_bin_from_description(
            "videoconvert ! video/x-raw,format=BGRx ! "
            f"appsink name=kvr-appsink sync=true max-buffers={self.PUFFER} "
            "drop=true emit-signals=true", True)
        self.appsink = self.bin.get_by_name("kvr-appsink")
        self.appsink.connect("new-sample", self._auf_bild)
        # Auch das Vorschaubild abholen. Im Pausenzustand meldet appsink kein
        # "new-sample", sondern "new-preroll" - ohne das bleibt die Anzeige
        # nach dem Laden schwarz, bis man auf Abspielen drueckt. Dasselbe gilt
        # nach jedem Springen im pausierten Zustand.
        self.appsink.connect("new-preroll", self._auf_vorschaubild)

    def _auf_vorschaubild(self, senke):
        return self._verarbeiten(senke.emit("pull-preroll"))

    def _auf_bild(self, senke):
        return self._verarbeiten(senke.emit("pull-sample"))

    def _verarbeiten(self, sample):
        if sample is None:
            return Gst.FlowReturn.OK
        try:
            puffer = sample.get_buffer()
            struktur = sample.get_caps().get_structure(0)
            breite = struktur.get_value("width")
            hoehe = struktur.get_value("height")
            ok, karte = puffer.map(Gst.MapFlags.READ)
            if ok:
                try:
                    # copy(): der Speicher gehoert GStreamer und wird gleich
                    # wieder freigegeben - ohne eigene Kopie zeigt das Widget
                    # spaeter auf Speicher, den es nicht mehr geben muss.
                    bild = QImage(karte.data, breite, hoehe, breite * 4,
                                  QImage.Format_RGB32).copy()
                finally:
                    puffer.unmap(karte)
                self.bruecke.neuesBild.emit(bild)
        except Exception:
            pass
        return Gst.FlowReturn.OK


class GesPlayerBackend:
    """Der Wiedergabe-Player von KVRouite, auf Basis von GES.

    Bis 5.01 stand hier eine Weiche zwischen zwei Wiedergabewegen mit einer
    gemeinsamen Basisklasse. Seit 6.0 gibt es nur
    noch diesen: der zweite konnte weder Blenden noch 360 Grad zeigen und war
    am Export ohnehin nicht beteiligt. Weiche und Basisklasse sind entfallen.
    """

    # Reihenfolge der Video-Senken; der erste, der sich bauen laesst, gewinnt.
    _SINKS_WINDOWS = ("d3d11videosink", "d3d12videosink", "glimagesink", "autovideosink")
    _SINKS_OTHER = ("glimagesink", "xvimagesink", "autovideosink")

    def __init__(self, window_id, log_handler=None, frame_callback=None):
        if _GST_IMPORT_ERROR is not None:
            raise ImportError(
                "GStreamer/GES ist nicht verfuegbar: %s\n"
                "Windows/macOS:  pip install gstreamer-bundle\n"
                "Linux:          python3-gi, gir1.2-ges-1.0, gstreamer1.0-plugins-base/good"
                % _GST_IMPORT_ERROR
            )

        if not Gst.is_initialized():
            Gst.init(None)
        GES.init()

        self._window_id = int(window_id)
        self._log = log_handler
        self._end_callback = None
        self._rate = 1.0
        self._paused = True
        self._total_ns = 0
        # Die letzte Stelle, die die Pipeline wirklich gemeldet hat. Sie ist
        # die Antwort, wenn eine Abfrage ins Leere laeuft - siehe
        # _position_ns() und _position_ns_sicher().
        self._letzte_position_ns = 0
        # Laeuft gerade ein Sprung? Solange antwortet _position_ns_sicher()
        # mit dem Sprungziel statt zu messen - siehe _seek_ns().
        self._seek_laeuft = False
        self._seek_seit = 0.0
        self._sink = None
        self._anzeige = None      # _AppsinkAnzeige, wenn Qt malt
        # Ist ein Rueckruf da, malt Qt die Bilder selbst. Er muss VOR
        # _build_sink() feststehen, deshalb hier im Konstruktor.
        self._bild_rueckruf = frame_callback
        self._warned_no_decoder = False
        self._orient = None

        # 360 Grad, siehe core/view360.py. Die Effekte werden beim Aufbau der
        # Timeline mitgefuehrt, damit sich der Blickwinkel spaeter aendern
        # laesst, ohne die Timeline anzufassen.
        self._360_an = False
        # Ein Blickwinkel je Quelldatei, parallel zu self._assets. Die Liste
        # waechst in load_playlist mit. Bis dahin dient _blick_vorgabe als
        # Ablage - sonst ginge eine Einstellung verloren, die vor dem Laden
        # gemacht wurde (etwa aus einer Projektdatei).
        self._blicke = []
        self._blick_vorgabe = view360.Blickwinkel()
        # (Index der Quelldatei, Effekt) - damit ein Schwenk nur die Clips
        # trifft, die zu diesem Video gehoeren.
        self._effekte = []
        # Drosselung fuers Auffrischen des Standbilds beim Schwenken.
        self._blick_timer = QTimer()
        self._blick_timer.setSingleShot(True)
        self._blick_timer.timeout.connect(self._blick_timer_abgelaufen)
        self._blick_offen = False

        self._assets = []         # [(pfad, asset, roh_start_ns, dauer_ns)]
        self._cuts = []           # [(start_s, ende_s, blende_s)]
        self._keeps = []          # [(roh_start_ns, roh_ende_ns, final_start_ns)]
        self._final_total_ns = 0

        self._timeline = GES.Timeline.new_audio_video()
        # Overlays liegen ganz oben. Eigene Ebene, weil zwei Clips auf
        # derselben Ebene nicht ueberlappen duerfen - ein Overlay kann
        # aber sehr wohl ueber einer Blende liegen.
        self._ovl_layer = self._timeline.append_layer()   # Prioritaet 0
        self._layer = self._timeline.append_layer()       # Prioritaet 1
        self._overlays = []
        self._overlay_export = None
        self._preview_w = 0
        self._preview_h = 0
        # Bildrate, in der die Vorschau wirklich rechnet - siehe
        # _limit_preview_size() und preview_fps(). 0 heisst "noch nicht
        # ermittelt".
        self._preview_fps = 0.0
        self._pipeline = GES.Pipeline()
        self._pipeline.set_timeline(self._timeline)
        self._build_sink()
        self._pipeline.set_mode(GES.PipelineFlags.FULL_PREVIEW)

        # Der Bus wird per Qt-Timer geleert. Ein eigener GLib-Mainloop waere
        # ein zweiter Event-Loop neben Qt; das braucht es hier nicht.
        #
        # Eine Nachricht muss allerdings SOFORT beantwortet werden und darf
        # nicht in der Warteschlange liegen bleiben: mit
        # "prepare-window-handle" fragt die Video-Senke, in welches Fenster sie
        # zeichnen soll. Kommt die Antwort zu spaet, macht sie ein eigenes
        # Fenster auf. Dafuer der Sync-Handler; alles andere laeuft weiter
        # ueber die Warteschlange (BusSyncReply.PASS).
        self._bus = self._pipeline.get_bus()
        # Die gebundene Methode festhalten: gibt man sie direkt weiter, kann
        # Python sie einsammeln, und GStreamer meldet dann bei jeder Nachricht
        # "invalid return from bus sync handler".
        self._sync_handler = self._on_sync_message
        self._bus.set_sync_handler(self._sync_handler, None)
        self._bus_timer = QTimer()
        self._bus_timer.timeout.connect(self._drain_bus)
        self._bus_timer.start(50)

        self._pipeline.set_state(Gst.State.READY)

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def _build_sink(self):
        # Soll Qt selbst malen, holen wir die Bilder ab, statt GStreamer
        # in ein Fensterhandle zeichnen zu lassen. Nur so kann spaeter
        # etwas ueber dem Video liegen (Auswahlrahmen, Anfasser).
        if self._bild_rueckruf is not None:
            try:
                self._anzeige = _AppsinkAnzeige(self._bild_rueckruf)
                self._pipeline.preview_set_video_sink(self._anzeige.bin)
                self._note("Video-Senke: appsink (Qt zeichnet)")
                return
            except Exception as exc:
                self._anzeige = None
                self._note(f"appsink nicht nutzbar ({exc}) - nehme Fensterhandle")

        names = self._SINKS_WINDOWS if platform.system() == "Windows" else self._SINKS_OTHER
        for name in names:
            try:
                # Das gi-Override von ElementFactory.make wirft MissingPluginError,
                # statt None zu liefern. Ohne das try bricht die Suche beim ersten
                # fehlenden Kandidaten ab, statt den naechsten zu probieren.
                sink = Gst.ElementFactory.make(name, "kvr-videosink")
            except Exception:
                sink = None
            if sink is None:
                continue
            self._sink = sink
            self._pipeline.preview_set_video_sink(sink)
            self._attach_window(sink)
            self._note(f"Video-Senke: {name}")
            return
        raise RuntimeError("Keine brauchbare GStreamer-Video-Senke gefunden "
                           f"(versucht: {', '.join(names)})")

    def _attach_window(self, sink):
        """Video in das uebergebene Fenster zeichnen statt in ein eigenes."""
        target = sink
        if isinstance(sink, Gst.Bin):
            # autovideosink & Co. verstecken die echte Senke in einem Bin.
            target = sink.get_by_interface(GstVideo.VideoOverlay) or sink
        try:
            target.set_window_handle(self._window_id)
        except Exception as exc:
            self._note(f"Fenster-Handle konnte nicht gesetzt werden: {exc}")

    def _note(self, text):
        print(f"[GES] {text}")

    def _on_sync_message(self, bus, msg, *_rest):
        """Laeuft im GStreamer-Thread - hier NUR das Fenster-Handle setzen."""
        try:
            if GstVideo.is_video_overlay_prepare_window_handle_message(msg):
                msg.src.set_window_handle(self._window_id)
        except Exception:
            pass
        return Gst.BusSyncReply.PASS

    def _drain_bus(self):
        if self._bus is None:
            return
        while True:
            msg = self._bus.pop()
            if msg is None:
                return
            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                self._note(f"FEHLER: {err} | {dbg}")
                # Scheitert der 360-Shader - kein GL-Kontext ueber
                # Remote-Desktop, Treiber uebersetzt ihn nicht -, bliebe die
                # Vorschau sonst einfach schwarz. Lieber ohne 360 weiterlaufen
                # und sagen, warum.
                if self._360_an and self._ist_360_fehler(msg, str(err), str(dbg)):
                    self._360_abschalten(str(err))
                    continue
            elif msg.type == Gst.MessageType.WARNING:
                err, _dbg = msg.parse_warning()
                text = str(err)
                # GoPro-Dateien haben eine Telemetriespur (gpmd). Die kann
                # niemand dekodieren und wir brauchen sie auch nicht - Bild und
                # Ton laufen. Einmal erwaehnen, danach still sein.
                if "gpmd" in text or "No decoder available" in text:
                    if not self._warned_no_decoder:
                        self._warned_no_decoder = True
                        self._note("Datenspur ohne Decoder wird uebergangen "
                                   "(z.B. GoPro-Telemetrie) - Bild und Ton sind davon nicht betroffen")
                    continue
                self._note(f"Warnung: {text}")
            elif msg.type == Gst.MessageType.ASYNC_DONE:
                # Der Sprung ist durch. Ab jetzt liefert query_position die
                # neue Stelle, und es muss nicht mehr maskiert werden.
                self._seek_laeuft = False
            elif msg.type == Gst.MessageType.EOS:
                self._paused = True
                self._seek_laeuft = False
                if self._end_callback:
                    self._end_callback()

    @staticmethod
    def _ist_360_fehler(msg, fehlertext, debugtext):
        """Kommt dieser Bus-Fehler aus der 360-Kette?"""
        quelle = ""
        try:
            if msg.src is not None:
                quelle = msg.src.get_name() or ""
        except Exception:
            pass
        text = f"{quelle} {fehlertext} {debugtext}".lower()
        return any(w in text for w in
                   ("kvr360", "glshader", "glupload", "gldownload",
                    "shader compilation", "gl context", "opengl"))

    # ------------------------------------------------------------------
    # Schnitte, Blenden und der Aufbau der Timeline
    # ------------------------------------------------------------------
    def supports_cuts(self):
        return True

    def set_cuts(self, cuts):
        """
        Schnitte fuer die Vorschau setzen. `cuts` ist eine Liste von
        (start_s, ende_s, blende_s) oder (start_s, ende_s, blende_s, schnipsel);
        blende_s = 0 bedeutet harte Kante.

        `schnipsel` ist der Pfad einer vorgerenderten Blende (siehe
        core/fade_cache.py). Ohne ihn wird der Schnitt hart dargestellt - die
        Blende kommt nach, sobald die Datei fertig ist.

        Danach zeigt die Vorschau das FERTIGE Video: geschnittene Bereiche
        fehlen, an den Schnitten liegt die Blende. Nach aussen bleibt aber
        alles in Rohmaterial-Zeit - die Umrechnung passiert hier drin, damit
        Zeitanzeige, Timeline-Marker und GPX-Kopplung unveraendert
        weiterrechnen koennen.
        """
        neu = []
        for eintrag in cuts:
            a, b, f = eintrag[0], eintrag[1], eintrag[2]
            schnipsel = eintrag[3] if len(eintrag) > 3 else None
            if float(b) > float(a):
                neu.append((float(a), float(b), float(f), schnipsel))
            elif float(b) == float(a) and float(f) > 0 and schnipsel:
                # Ein Merge-Fade an einer Dateigrenze: kein Schnitt, nur ein
                # vorgerenderter Uebergang, der mittig auf der Naht liegt.
                # Er laeuft hier als Schnitt der Breite 0 durch - damit
                # teilt _compute_keeps die Keeps an der Naht, und _rebuild
                # setzt den Schnipsel wie bei jeder anderen Blende ein: das
                # Stueck davor eine halbe Laenge kuerzer, das Stueck danach
                # eine halbe Laenge spaeter. Die Gesamtlaenge bleibt gleich.
                # Ohne Schnipsel gibt es nichts einzusetzen, dann bleibt die
                # Naht hart und braucht auch keinen Eintrag.
                neu.append((float(a), float(a), float(f), schnipsel))
        neu.sort()
        if neu == self._cuts and self._keeps:
            return True          # nichts geaendert - Umbau waere verschenkt
        self._cuts = neu
        self._rebuild()
        return True

    # Grenzen fuer die Vorschau. GES setzt von sich aus 1280x720 bei 30 fps;
    # das ist als Rechenaufwand gut gewaehlt, verzerrt aber Material, das
    # nicht 16:9 ist (etwa 2:1 bei 360-Grad-Aufnahmen). Deshalb setzen wir es
    # selbst: Breite und Bildrate gedeckelt, Seitenverhaeltnis der Quelle
    # erhalten - ausser bei aktivem 360, da ist die Ausgabe 16:9.
    # WICHTIG ist der Deckel fuer die Bildrate - ohne ihn rechnet
    # die Vorschau bei 60-fps-Material doppelt so viel wie noetig.
    # Geduld beim Oeffnen einer Datei.
    ASSET_TIMEOUT_S = 120

    PREVIEW_MAX_WIDTH = 1280
    PREVIEW_MAX_FPS = 30

    def _preview_groesse(self):
        """(breite, hoehe) der Vorschau. Vor dem ersten Asset (0, 0)."""
        return self._preview_w, self._preview_h

    def _limit_preview_size(self):
        """Vorschauaufloesung begrenzen, Seitenverhaeltnis der Quelle behalten.

        Ausnahme ist der 360-Betrieb: dort IST das 2:1-Format der Quelle die
        Kugel und kein Bildformat. Die Vorschau rechnet dann in 16:9, weil
        genau das hinterher aus dem Export kommt.
        """
        if not self._assets:
            return
        try:
            info = None
            for stream in self._assets[0][1].get_info().get_video_streams():
                info = stream
                break
            if info is None:
                return
            w, h = int(info.get_width()), int(info.get_height())
            if w <= 0 or h <= 0:
                return
            if w > self.PREVIEW_MAX_WIDTH:
                h = max(2, int(round(h * self.PREVIEW_MAX_WIDTH / w)) & ~1)
                w = self.PREVIEW_MAX_WIDTH
            if self._360_an:
                h = view360.ziel_hoehe(w)

            # Bildrate immer festnageln. Ohne Angabe richtet sich der
            # Compositor nach seinen Eingaengen und liefert waehrend einer
            # Blende mehr Bilder als noetig.
            num, den = self.PREVIEW_MAX_FPS, 1
            try:
                sn, sd = info.get_framerate_num(), info.get_framerate_denom()
                if sn and sd and sn / sd < self.PREVIEW_MAX_FPS:
                    num, den = sn, sd        # Quelle ist langsamer - uebernehmen
            except Exception:
                pass

            for track in self._timeline.get_tracks():
                if track.get_property("track-type") == GES.TrackType.VIDEO:
                    track.set_restriction_caps(Gst.Caps.from_string(
                        f"video/x-raw,width={w},height={h},framerate={num}/{den}"))
            self._preview_w = w
            self._preview_h = h
            self._preview_fps = float(num) / float(den)
            self._note(f"Vorschau rechnet in {w}x{h} bei {num/den:.2f} fps"
                       + (" (360)" if self._360_an else ""))
        except Exception as exc:
            self._note(f"Vorschauaufloesung nicht gesetzt: {exc}")

    # GstVideo.VideoOrientationMethod
    _ORIENT_IDENTITY = 0
    _ORIENT_180 = 2
    _ORIENT_AUTO = 8

    def _orientation_method(self):
        """
        Feste Drehung fuer alle Clips, oder None fuer "GES soll selbst schauen".

        GES stellt jeden Clip auf AUTO: das Drehelement liest die Kennzeichnung
        aus dem Datenstrom. Kommt sie nicht rechtzeitig an, bleibt der Clip
        ungedreht - bei kopfueber aufgenommenem Material steht dann einer von
        mehreren Clips auf dem Kopf, mal dieser, mal jener. Deshalb geben wir
        die Drehung vor, wenn alle Quellen dieselbe haben.

        Nur 0 und 180 Grad: bei 90 und 270 vertauschen sich Breite und Hoehe,
        das braucht mehr als nur eine andere Zahl. Da bleibt es bei AUTO.
        """
        if not self._assets:
            return None
        try:
            from core.fade_cache import source_rotation
            werte = {abs(source_rotation(p)) for (p, _a, _s, _d) in self._assets}
        except Exception:
            return None
        if len(werte) != 1:
            return None
        (grad,) = werte
        if grad == 0:
            return self._ORIENT_IDENTITY
        if grad == 180:
            return self._ORIENT_180
        return None

    def _clip_vorbereiten(self, clip, roh_ns=0, bildlage=None):
        """
        Alles, was jeder Clip auf der Timeline braucht: Bildlage und 360.

        Der eine Trichter fuer beides. _rebuild() legt Clips an drei Stellen
        an - Blenden-Schnipsel und zwei Materialwege -, und alle drei gehen
        hier durch. Die vorgerenderten Blenden bekommen den 360-Effekt damit
        ebenfalls, und das ist richtig: fade_cache rendert sie im
        Seitenverhaeltnis der Quelle, sie sind also auch Equirect.

        `roh_ns` sagt, aus welcher Stelle des Rohmaterials das Stueck stammt.
        Daraus ergibt sich die Quelldatei und damit ihr Blickwinkel.

        `bildlage` erzwingt eine Drehmethode fuer diesen Clip. None heisst:
        die feste Drehung der Playlist, falls es eine gibt, sonst AUTO. Die
        vorgerenderten Schnipsel kommen aufgerichtet aus fade_cache und
        werden mit IDENTITY eingesetzt.
        """
        if clip is None:
            return clip
        methode = self._orient if bildlage is None else bildlage
        if methode is not None:
            try:
                src = clip.find_track_element(None, GES.VideoSource)
                if src is not None:
                    src.set_child_property("video-direction", methode)
            except Exception as exc:
                self._note(f"Bildlage nicht setzbar: {exc}")
        if self._360_an:
            self._360_anhaengen(clip, self._clip_at(roh_ns))
        return clip

    def _360_anhaengen(self, clip, index):
        """Shader an einen Clip haengen und ihn randlos aufs Zielbild legen."""
        breite, hoehe = self._preview_groesse()
        effekt = view360.effekt_anhaengen(
            clip, self._blick(index), view360.ziel_aspect(breite, hoehe))
        if effekt is None:
            self._note("360-Effekt liess sich nicht anhaengen")
            return
        view360.rahmen_setzen(clip, breite, hoehe)
        self._effekte.append((index, effekt))

    def _blick(self, index):
        """Blickwinkel der Quelldatei mit diesem Platz."""
        if 0 <= index < len(self._blicke):
            return self._blicke[index]
        return self._blick_vorgabe

    def _raw_total_ns(self):
        return self._assets[-1][2] + self._assets[-1][3] if self._assets else 0

    # Kuerzer als das behalten wir gar nichts erst. In 10 ms passt bei jeder
    # Bildrate bis 100 fps nicht ein einziges vollstaendiges Bild - ein solches
    # Stueck kann also nichts zeigen.
    #
    # Es entsteht auch nicht durch einen Schnitt des Benutzers, sondern durch
    # zwei verschiedene Laengenquellen: die Schnittmarken der App kommen aus
    # der mdhd-Box (framerate.dauer(), real_total_duration), die Rohlaenge hier
    # aus asset.get_duration() von GES. Die beiden gehen um Millisekunden
    # auseinander. Bei einem End-Cut endet der Schnitt deshalb ein Stueckchen
    # VOR dem Rohende, und dahinter blieb bisher ein Splitter stehen - das
    # allerletzte Bild des Rohvideos. Weil dieser Splitter das letzte Stueck
    # der Vorschau war, landete jeder Sprung ans Ende dort, statt auf dem Bild
    # vor dem End-Cut. Nachgestellt am 31.08.2026: 2 Schnitte ergaben
    # 3 Stuecke, roh 120.834s gegen Schnittende 120.833s.
    SPLITTER_NS = NS // 100

    def _compute_keeps(self):
        """Was vom Rohmaterial uebrig bleibt, plus die Position im Ergebnis."""
        total = self._raw_total_ns()
        self._keeps = []
        pos = 0
        final = 0
        for eintrag in self._cuts:
            a, b = eintrag[0], eintrag[1]
            s, e = int(a * NS), int(b * NS)
            if s > pos:
                dur = min(s, total) - pos
                if dur > self.SPLITTER_NS:
                    self._keeps.append((pos, pos + dur, final))
                    final += dur
            pos = max(pos, min(e, total))
        if total - pos > self.SPLITTER_NS:
            self._keeps.append((pos, total, final))
            final += total - pos
        self._final_total_ns = final

    def _raw_to_final(self, raw_ns):
        """Rohzeit -> Zeit im fertigen Video. In einem Schnitt: naechste Kante."""
        for (ks, ke, fs) in self._keeps:
            if raw_ns < ks:
                return fs                      # liegt in einem Schnitt davor
            if raw_ns < ke:
                return fs + (raw_ns - ks)
        return max(0, self._final_total_ns - 1)

    def _final_to_raw(self, final_ns):
        for (ks, ke, fs) in self._keeps:
            if fs <= final_ns < fs + (ke - ks):
                return ks + (final_ns - fs)
        return self._keeps[-1][1] if self._keeps else 0

    def _pieces(self, raw_start, raw_end):
        """Ein Rohzeit-Bereich, zerlegt an den Dateigrenzen."""
        out = []
        for (_path, asset, cs, cd) in self._assets:
            s = max(raw_start, cs)
            e = min(raw_end, cs + cd)
            if e > s:
                out.append((asset, s - cs, e - s, s))   # asset, inpoint, dauer, rohstart
        return out

    def _rebuild(self):
        """Timeline neu aufbauen. Die Abspielstelle bleibt erhalten."""
        if not self._assets:
            return
        merken = self._position_ns_sicher() if self._final_total_ns else 0
        roh_vorher = self._final_to_raw(merken) if self._keeps else 0

        # Waehrend des Umbaus nicht abspielen. Clips zu entfernen und
        # hinzuzufuegen und danach commit_sync() aufzurufen, waehrend die
        # Pipeline laeuft, kann sie zum Stehen bringen - der Aufruf wartet
        # dann im Hauptthread auf etwas, das erst weitergeht, wenn der
        # Hauptthread wieder frei ist.
        lief = not self._paused
        if lief:
            self._pipeline.set_state(Gst.State.PAUSED)
            self._pipeline.get_state(5 * Gst.SECOND)

        for clip in list(self._layer.get_clips()):
            self._layer.remove_clip(clip)
        # Die 360-Effekte hingen an genau diesen Clips und sind mit ihnen weg.
        # _clip_vorbereiten() sammelt gleich die neuen ein.
        self._effekte = []

        self._compute_keeps()

        # Vorgerenderte Blenden laden.
        #
        # Eine Blende liegt MITTIG auf der Schnittkante: bei 2 s reicht sie
        # 1 s in das behaltene Material davor und 1 s in das danach hinein.
        # Deshalb wird das Stueck vor der Kante am Ende und das Stueck dahinter
        # am Anfang um je eine halbe Blendenlaenge gekuerzt - die Gesamtlaenge
        # bleibt dadurch gleich, und die Umrechnung Roh->Fertig aus
        # _compute_keeps stimmt weiterhin.
        nach_kante = {}    # Rohzeit des Schnitt-ENDES  -> (asset, dauer, halb)
        vor_kante = {}     # Rohzeit des Schnitt-ANFANGS -> halb
        for eintrag in self._cuts:
            fade = eintrag[2]
            pfad = eintrag[3] if len(eintrag) > 3 else None
            if fade <= 0 or not pfad or not os.path.exists(pfad):
                continue
            try:
                uri = GLib.filename_to_uri(os.path.abspath(pfad), None)
                asset = GES.UriClipAsset.request_sync(uri)
                dauer = asset.get_duration()
            except Exception as exc:
                self._note(f"Blende nicht ladbar ({pfad}): {exc}")
                continue
            if not dauer or dauer <= 0:
                continue
            halb = int(fade * NS) // 2
            nach_kante[int(eintrag[1] * NS)] = (asset, dauer, halb)
            vor_kante[int(eintrag[0] * NS)] = halb

        mit_blende = 0
        for (ks, ke, fs) in self._keeps:
            sn = nach_kante.get(ks)
            vorne = sn[2] if sn else 0
            hinten = vor_kante.get(ke, 0)
            # Nicht mehr wegnehmen, als das Stueck hergibt.
            if vorne + hinten >= ke - ks:
                vorne = hinten = 0
                sn = None

            if sn is not None:
                asset, dauer, halb = sn
                # Die Blende beginnt eine halbe Laenge VOR der Kante.
                # Fuer 360 zaehlt sie zu dem Video, in das sie fuehrt (ks ist
                # die Rohzeit hinter dem Schnitt) - dorthin schaut man ja beim
                # Ende der Blende.
                # Der Schnipsel ist schon aufgerichtet (fade_cache rendert
                # seit 6.14 mit der Bildlage der Quelle) und bekommt
                # deshalb ausdruecklich KEINE Drehung - weder die feste noch
                # AUTO. Mit AUTO bliebe er roh, er traegt keine
                # Kennzeichnung; mit der festen stuende er auf dem Kopf.
                self._clip_vorbereiten(
                    self._layer.add_asset(asset, fs - halb, 0, dauer,
                                          GES.TrackType.UNKNOWN), ks,
                    bildlage=self._ORIENT_IDENTITY)
                mit_blende += 1
                # Das Folgematerial setzt dort an, wo die Blende WIRKLICH
                # endet. Die gerenderte Datei ist gelegentlich ein Bild
                # kuerzer als bestellt; rechnete man mit der bestellten
                # Laenge, klaffte dort eine Luecke - sichtbar als kurzes
                # schwarzes Aufflackern direkt nach der Blende.
                vorne = dauer - halb

            start, ende = ks + vorne, ke - hinten
            final = fs + vorne
            for (asset, inpoint, dur, rohstart) in self._pieces(start, ende):
                self._clip_vorbereiten(
                    self._layer.add_asset(asset, final + (rohstart - start), inpoint,
                                          dur, GES.TrackType.UNKNOWN), rohstart)

        ovl = self._overlays_einsetzen()
        self._timeline.commit_sync()
        self._total_ns = self._final_total_ns
        if self._keeps:
            self._seek_ns(self._raw_to_final(roh_vorher))
        if lief:
            self._pipeline.set_state(Gst.State.PLAYING)
        self._note(f"Timeline: {len(self._cuts)} Schnitt(e) -> {len(self._keeps)} Stueck(e), "
                   f"Vorschau {self._final_total_ns/NS:.3f}s von roh "
                   f"{self._raw_total_ns()/NS:.3f}s, "
                   f"{len(self._layer.get_clips())} Clip(s), "
                   f"{mit_blende} Blende(n), {ovl} Overlay(s) eingesetzt")

    # ------------------------------------------------------------------
    # Timeline-Hilfen
    # ------------------------------------------------------------------
    def _clip_at(self, raw_ns):
        """Index der Quelldatei, in die die ROHZEIT raw_ns faellt; -1 wenn keine."""
        if not self._assets:
            return -1
        for i, (_p, _a, start, dur) in enumerate(self._assets):
            if start <= raw_ns < start + dur:
                return i
        return len(self._assets) - 1 if raw_ns >= self._raw_total_ns() else -1

    def _clip_start(self, index):
        if 0 <= index < len(self._assets):
            return self._assets[index][2]
        return 0

    def _current_raw_ns(self):
        """Wo wir im ROHMATERIAL stehen - das ist die Sprache der App."""
        if not self._keeps:
            return 0
        return self._final_to_raw(self._position_ns_sicher())

    def _position_ns(self):
        """Stelle in der Timeline - oder None, wenn die Pipeline nicht antwortet.

        NICHT 0. Die 0 ist eine gueltige Stelle, naemlich der Anfang, und
        liesse sich von "weiss nicht" nicht unterscheiden. Waehrend eines
        Sprungs oder eines Zustandswechsels scheitert die Abfrage
        regelmaessig; die 0 lief dann durch _final_to_raw und _clip_at bis in
        die Zeitanzeige, und der Marker stand fuer einen Takt am Anfang.

        Wer nur eine brauchbare Zahl braucht, nimmt _position_ns_sicher().
        """
        ok, pos = self._pipeline.query_position(Gst.Format.TIME)
        if not ok or pos < 0:
            return None
        self._letzte_position_ns = pos
        return pos

    # Laenger als so wird ein Sprung nie als "laeuft noch" behandelt. Es ist
    # dieselbe Sekunde, die frueher blockierend abgewartet wurde. Der Deckel
    # ist die Absicherung fuer den Fall, dass ASYNC_DONE ausbleibt - ohne ihn
    # stuende die Zeitanzeige still, bis der naechste Sprung kommt.
    SEEK_DECKEL_S = 1.0

    def _seek_laeuft_noch(self):
        if not self._seek_laeuft:
            return False
        if time.time() - self._seek_seit > self.SEEK_DECKEL_S:
            self._seek_laeuft = False
            return False
        return True

    def _position_ns_sicher(self):
        """Die Stelle, an der wir stehen SOLLEN.

        Laeuft gerade ein Sprung, ist das sein Ziel - und zwar ohne zu messen.
        Frueher wartete _seek_ns() blockierend auf das Ende des Sprungs, damit
        die naechste Messung schon die neue Stelle liefert. Dieses Warten ist
        weg (bis zu einer Sekunde Stillstand im Hauptthread); an seine Stelle
        tritt diese Maskierung. Ohne sie lieferte jede Abfrage direkt nach
        einem Sprung noch die ALTE Stelle, und der Stepper rechnete von dort
        aus weiter - er machte denselben Schritt ein zweites Mal.

        Sonst wird gemessen, und schlaegt die Messung fehl, gilt die letzte
        bekannte Stelle.

        Wer an die LAUFENDE Wiedergabe andocken will, braucht statt dessen
        _position_ns_frisch().
        """
        if self._seek_laeuft_noch():
            return self._letzte_position_ns
        pos = self._position_ns()
        return self._letzte_position_ns if pos is None else pos

    def _position_ns_frisch(self):
        """Die GEMESSENE Stelle, ohne Ruecksicht auf einen laufenden Sprung.

        Fuer alles, was auf die aktuelle Stelle springt, um von dort
        weiterzumachen: beim Abspielen ist das Ziel eines eben abgesetzten
        Sprungs schon ueberholt, und ein Sprung dorthin ginge zurueck.
        """
        pos = self._position_ns()
        return self._letzte_position_ns if pos is None else pos

    # Ab diesem Tempo wird nur noch grob dekodiert.
    TRICKMODE_AB_TEMPO = 2.0

    def _trick_flags(self):
        """
        Sprungmarken fuer hohes Tempo.

        Bei 4-fach muesste sonst jedes einzelne Bild dekodiert werden - bei
        4K-Material sind das 120 Bilder je Sekunde, das schafft kein Decoder,
        und GStreamer meldet "A lot of buffers are being dropped". Bilder
        wegzuwerfen macht GStreamer nur, wenn man es beim Springen dazusagt:
        TRICKMODE ueberspringt aufwendige Bilder, KEY_UNITS beschraenkt auf
        Keyframes.
        """
        tempo = abs(self._rate)
        if tempo <= self.TRICKMODE_AB_TEMPO:
            return Gst.SeekFlags(0)
        # Nur TRICKMODE. Zusaetzlich TRICKMODE_KEY_UNITS zu setzen klingt
        # naheliegend, macht es aber schlechter: gemessen bei 8-fach 0,38x
        # statt 4,2x - die Pipeline wartet dann auf weit auseinander liegende
        # Keyframes, statt einfach aufwendige Bilder zu ueberspringen.
        f = 0
        for name in ("TRICKMODE", "TRICKMODE_NO_AUDIO"):
            f |= int(getattr(Gst.SeekFlags, name, 0))
        return Gst.SeekFlags(f)

    def _seek_ns(self, pos_ns, flush=True):
        # Kein zweiter Sprung, solange der erste noch laeuft.
        #
        # GStreamer rechnet den neuen sonst gegen ein Segment, das noch zum
        # alten gehoert, und weist ihn ab:
        #   gst_segment_do_seek: assertion 'start <= stop' failed
        # Ein abgewiesener Sprung findet nicht statt. Das Bild bleibt stehen,
        # wo es war - und liegt das nach einem gerade gesetzten Schnitt
        # ausserhalb der Timeline, ist es schwarz. Nachgestellt am 31.08.2026:
        # End-Cut setzen, danach GotoEnd.
        #
        # Ueberlappen tun Spruenge selten: Stepper, GotoEnd und Play setzen je
        # einen einzelnen ab. Wo es doch vorkommt - ein Sprung kurz nach dem
        # Neubau der Timeline, die dabei selbst einen absetzt -, wird auf das
        # Ende des laufenden gewartet. Also so wie frueher, aber nur in diesem
        # Fall und nicht mehr nach JEDEM Sprung.
        if self._seek_laeuft_noch():
            self._pipeline.get_state(Gst.SECOND)
            self._seek_laeuft = False

        pos_ns = max(0, min(int(pos_ns), max(0, self._total_ns - 1)))
        # Ab hier ist die Stelle bekannt, auch wenn die Pipeline noch ein paar
        # Millisekunden braucht, bis sie sie meldet.
        self._letzte_position_ns = pos_ns
        trick = self._trick_flags()
        # Bildgenau und "grob dekodieren" schliessen sich aus.
        flags = trick if trick else Gst.SeekFlags.ACCURATE
        if flush:
            flags |= Gst.SeekFlags.FLUSH
        if abs(self._rate - 1.0) < 1e-6:
            self._pipeline.seek_simple(Gst.Format.TIME, flags, pos_ns)
        else:
            self._pipeline.seek(self._rate, Gst.Format.TIME, flags,
                                Gst.SeekType.SET, pos_ns,
                                Gst.SeekType.NONE, -1)
        # Frueher stand hier get_state(Gst.SECOND) - ein blockierendes Warten
        # auf das Ende des Sprungs, bis zu einer Sekunde Stillstand im
        # Hauptthread, und das bei JEDEM Sprung. Stattdessen wird nur
        # vermerkt, dass ein Sprung laeuft; ASYNC_DONE auf dem Bus loescht den
        # Vermerk wieder (siehe _drain_bus), und solange er steht, antwortet
        # _position_ns_sicher() mit dem Sprungziel statt mit einer Messung,
        # die noch die alte Stelle liefern wuerde.
        self._seek_laeuft = True
        self._seek_seit = time.time()

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def shutdown(self):
        try:
            self._bus_timer.stop()
        except Exception:
            pass
        try:
            self._bus.set_sync_handler(None, None)
        except Exception:
            pass
        try:
            # set_state ist asynchron - ohne das Warten laufen die
            # GStreamer-Threads noch, wenn Python schon beenden will.
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline.get_state(5 * Gst.SECOND)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Playlist
    # ------------------------------------------------------------------
    def _asset_laden(self, uri):
        """
        Asset holen, ohne die Oberflaeche einzufrieren.

        GES analysiert beim Oeffnen die ganze Datei. Gemessen an einer 8,6 GB
        grossen GoPro-Aufnahme: rund 6 Sekunden. Die Analyse laesst sich nicht
        vermeiden, aber sie muss nicht blockieren - deshalb der Weg ueber
        request_async statt request_sync.

        Wichtig dabei: GES stellt die Antwort ueber die GLib-Schleife zu, und
        die laeuft in einer Qt-Anwendung nicht von allein. Deshalb werden hier
        BEIDE Schleifen abwechselnd gedreht - sonst wartet man ewig.
        """
        ergebnis = {}

        def fertig(_quelle, res, _daten):
            try:
                ergebnis["asset"] = GES.Asset.request_finish(res)
            except Exception as exc:
                ergebnis["fehler"] = exc

        try:
            GES.Asset.request_async(GES.UriClip, uri, None, fertig, None)
        except Exception as exc:
            self._note(f"Asynchrones Laden nicht moeglich ({exc}) - lade blockierend")
            return GES.UriClipAsset.request_sync(uri)

        from PySide6.QtWidgets import QApplication
        kontext = GLib.MainContext.default()
        grenze = time.time() + self.ASSET_TIMEOUT_S
        while not ergebnis and time.time() < grenze:
            while kontext.pending():
                kontext.iteration(False)
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
            time.sleep(0.005)

        if "fehler" in ergebnis:
            raise ergebnis["fehler"]
        if "asset" not in ergebnis:
            self._note("Zeitueberschreitung beim Oeffnen - versuche es blockierend")
            return GES.UriClipAsset.request_sync(uri)
        return ergebnis["asset"]

    def load_playlist(self, paths, fortschritt=None):
        """
        `fortschritt(nummer, gesamt, pfad)` wird vor jeder Datei gerufen -
        damit der Aufrufer anzeigen kann, woran gerade gearbeitet wird.
        """
        self.clear()
        if not paths:
            return

        offset = 0
        for nummer, path in enumerate(paths, 1):
            if fortschritt:
                try:
                    fortschritt(nummer, len(paths), path)
                except Exception:
                    pass
            uri = GLib.filename_to_uri(os.path.abspath(path), None)
            try:
                asset = self._asset_laden(uri)
            except Exception as exc:
                self._note(f"Datei nicht ladbar, uebersprungen: {path} ({exc})")
                continue
            if asset is None:
                self._note(f"Datei nicht ladbar, uebersprungen: {path}")
                continue
            dur = asset.get_duration()
            if not dur or dur <= 0:
                self._note(f"Datei ohne Dauer, uebersprungen: {path}")
                continue
            self._assets.append((path, asset, offset, dur))
            offset += dur

        self._blicke_angleichen()
        self._limit_preview_size()
        self._orient = self._orientation_method()
        if self._orient is not None:
            self._note(f"Bildlage fest auf Methode {self._orient} gesetzt")
        self._rebuild()
        self._pipeline.set_state(Gst.State.PAUSED)
        self._pipeline.get_state(5 * Gst.SECOND)
        self._paused = True
        self._note(f"{len(self._assets)} Clip(s), roh {offset/NS:.3f}s, "
                   f"Vorschau {self._final_total_ns/NS:.3f}s")

    def clear(self):
        for ebene in (self._layer, self._ovl_layer):
            for clip in list(ebene.get_clips()):
                ebene.remove_clip(clip)
        self._timeline.commit_sync()
        self._assets = []
        self._keeps = []
        self._cuts = []
        self._overlays = []
        self._total_ns = 0
        self._final_total_ns = 0
        self._preview_fps = 0.0
        self._seek_laeuft = False
        self._pipeline.set_state(Gst.State.READY)
        self._paused = True

    def stop(self):
        self._pipeline.set_state(Gst.State.READY)
        self._paused = True

    def play_index(self, index):
        if 0 <= index < len(self._assets):
            self._seek_ns(self._raw_to_final(self._clip_start(index)))

    def index(self):
        if not self._assets:
            return -1
        return self._clip_at(self._current_raw_ns())

    def count(self):
        return len(self._assets)

    def current_file(self):
        i = self.index()
        return self._assets[i][0] if i >= 0 else None

    # ------------------------------------------------------------------
    # Wiedergabe
    # ------------------------------------------------------------------
    def set_paused(self, paused):
        if not self._assets:
            self._paused = True
            return
        self._pipeline.set_state(Gst.State.PAUSED if paused else Gst.State.PLAYING)
        self._paused = bool(paused)

    def is_paused(self):
        return self._paused

    def seek_local(self, seconds):
        """Sekunde INNERHALB der aktuellen Quelldatei.

        Nicht Timeline-Zeit: die App rechnet in Playlist-Sicht, siehe den
        Hinweis zum Modellunterschied am Dateikopf.
        """
        i = self.index()
        if i < 0:
            i = 0
        raw = self._clip_start(i) + int(float(seconds) * NS)
        self._seek_ns(self._raw_to_final(raw))

    def seek_global_raw(self, sekunden):
        """Sprung auf eine ROHSEKUNDE ueber alle Dateien hinweg - EIN Sprung.

        Die App hat diesen Weg bisher aus play_index() und seek_local()
        zusammengesetzt, weil die Wiedergabe einmal eine Playlist war. Der
        erste Sprung ging dabei an den CLIP-ANFANG, der zweite erst ans Ziel.

        GES hat EINE durchgehende Zeitachse. In welcher Datei eine Rohsekunde
        liegt, geht den Sprung nichts an; _raw_to_final() rechnet die
        Schnitte heraus.
        """
        if not self._assets:
            return
        raw = max(0, int(float(sekunden) * NS))
        self._seek_ns(self._raw_to_final(raw))

    def position_global(self):
        """Rohsekunde ueber alle Dateien hinweg, aus EINER Abfrage.

        Das Gegenstueck zu seek_global_raw(). Wer stattdessen index() und
        position() nacheinander abfragt, misst zweimal: der Versatz stammt
        dann aus der einen Messung, die lokale Zeit aus der anderen - und
        weichen sie voneinander ab, springt das Ergebnis um eine ganze
        Cliplaenge.
        """
        if not self._assets:
            return 0.0
        return max(0.0, self._current_raw_ns() / NS)

    def position(self):
        """Sekunde innerhalb der aktuellen Quelldatei, in ROHZEIT."""
        i = self.index()
        if i < 0:
            return 0.0
        return max(0.0, (self._current_raw_ns() - self._clip_start(i)) / NS)

    def step_frame(self, forward=True):
        # Vorschaurate, nicht Quellrate: gesprungen wird um das, was man
        # wirklich sieht. Siehe preview_fps().
        fps = self.preview_fps() or 25.0
        delta = int(NS / fps)
        self._seek_ns(self._position_ns_sicher() + (delta if forward else -delta))

    def set_rate(self, rate):
        """Abspielgeschwindigkeit setzen.

        Gesprungen wird auf die GEMESSENE Stelle, nicht auf ein laufendes
        Sprungziel: beim Abspielen ist dieses Ziel schon ueberholt, und der
        Sprung ginge ein paar Bilder zurueck.
        """
        self._rate = float(rate) if rate else 1.0
        if self._assets:
            self._seek_ns(self._position_ns_frisch())

    def rate(self):
        return self._rate

    def set_volume(self, volume):
        # GES.Pipeline reicht die Lautstaerke an sein internes playsink durch.
        try:
            self._pipeline.set_property("volume", max(0.0, min(1.0, volume / 100.0)))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Medieninfos
    # ------------------------------------------------------------------
    def _stream_info(self):
        """Videospur-Infos der Quelldatei, in der wir gerade stehen."""
        i = self.index()
        if i < 0:
            return None
        try:
            asset = self._assets[i][1]
            for stream in asset.get_info().get_video_streams():
                return stream
        except Exception:
            pass
        return None

    def preview_fps(self):
        """Bildrate, in der die VORSCHAU rechnet - nicht die der Quelle.

        Die Vorschau ist auf PREVIEW_MAX_FPS gedeckelt; liegt die Quelle
        darunter, gilt die Quelle (siehe _limit_preview_size). Bei 25, 29,97
        oder 30 fps sind beide Werte also gleich und es aendert sich nichts.

        Ueber dem Deckel gehen sie auseinander: bei 60 fps zeigt die Vorschau
        jedes zweite Quellbild. Ein Schritt um eine QUELL-Bilddauer bewegt das
        sichtbare Bild dann nur bei jedem zweiten Mal. Wer ein Bild weiter
        will, muss um eine Bilddauer der VORSCHAU weiter - deshalb rechnet der
        Stepper mit dieser Rate.

        Ist sie noch nicht ermittelt - _limit_preview_size() kann vorzeitig
        aussteigen, wenn kein Videostrom da ist -, gilt die Quellrate,
        gedeckelt. Nicht der Deckel allein: bei 25-fps-Material waere der
        Schritt sonst zu klein.
        """
        if self._preview_fps > 0:
            return self._preview_fps
        quelle = self.fps() or 0.0
        if quelle > 0:
            return min(quelle, float(self.PREVIEW_MAX_FPS))
        return None

    def fps(self):
        info = self._stream_info()
        if info is None:
            return None
        try:
            num = info.get_framerate_num()
            den = info.get_framerate_denom()
            if num and den:
                return float(num) / float(den)
        except Exception:
            pass
        return None

    def video_size(self):
        info = self._stream_info()
        if info is None:
            return 0, 0
        try:
            return int(info.get_width()), int(info.get_height())
        except Exception:
            return 0, 0

    # ------------------------------------------------------------------
    # Overlays
    # ------------------------------------------------------------------
    def set_overlays(self, overlays, export_groesse=None):
        """Overlays fuer die Vorschau setzen.

        `overlays` ist eine Liste von Woerterbuechern mit den Feldern

            start, end        Rohzeit in Sekunden (wie in der Projektdatei)
            fade_in, fade_out Ein- und Ausblenddauer in Sekunden
            image             Pfad zur Bilddatei
            x, y, w, h        Lage und Groesse IN PIXELN DER EXPORTAUFLOESUNG

        `export_groesse` ist (breite, hoehe) des Exports. Die Vorschau rechnet
        in einer kleineren Aufloesung, deshalb muessen Lage und Groesse
        umgerechnet werden - sonst zeigt sie ein Logo, das im Export ein
        Fuenftel des Bildes einnimmt, doppelt so gross. Genau darum geht es
        hier: die Vorschau soll zeigen, was hinterher herauskommt.

        Die Rechtecke kommen fertig ausgerechnet herein, damit Vorschau und
        Export sich nicht auseinanderentwickeln koennen - die ffmpeg-Ausdruecke
        wie "(W-w)-30" werden an einer Stelle ausgewertet, nicht an zweien.
        """
        neu = []
        for ovl in overlays or []:
            try:
                start, ende = float(ovl["start"]), float(ovl["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if ende <= start or not ovl.get("image"):
                continue
            neu.append({
                "start": start, "end": ende,
                "fade_in": float(ovl.get("fade_in", 0) or 0),
                "fade_out": float(ovl.get("fade_out", 0) or 0),
                "image": ovl["image"],
                "x": int(ovl.get("x", 0) or 0), "y": int(ovl.get("y", 0) or 0),
                "w": int(ovl.get("w", 0) or 0), "h": int(ovl.get("h", 0) or 0),
            })
        neu.sort(key=lambda o: o["start"])
        groesse = tuple(export_groesse) if export_groesse else None
        if neu == self._overlays and groesse == self._overlay_export:
            return True                  # nichts geaendert
        self._overlays = neu
        self._overlay_export = groesse
        self._rebuild()
        return True

    def supports_overlays(self):
        return True

    def _overlays_einsetzen(self):
        """Overlays auf die oberste Ebene legen, umgerechnet auf die Vorschau."""
        for clip in list(self._ovl_layer.get_clips()):
            self._ovl_layer.remove_clip(clip)
        if not self._overlays or not self._keeps:
            return 0

        # Verhaeltnis Vorschau zu Export. Ohne bekannte Exportgroesse wird
        # nicht skaliert - dann lieber unveraendert zeigen als falsch.
        faktor = 1.0
        if self._overlay_export and self._overlay_export[0] and self._preview_w:
            faktor = self._preview_w / float(self._overlay_export[0])

        gesetzt = 0
        for ovl in self._overlays:
            start_ns = self._raw_to_final(int(ovl["start"] * NS))
            ende_ns = self._raw_to_final(int(ovl["end"] * NS))
            if ende_ns <= start_ns:
                continue                 # liegt komplett in einem Schnitt
            try:
                uri = GLib.filename_to_uri(os.path.abspath(ovl["image"]), None)
                asset = GES.UriClipAsset.request_sync(uri)
            except Exception as exc:
                self._note(f"Overlay nicht ladbar ({ovl['image']}): {exc}")
                continue
            dauer_ns = ende_ns - start_ns
            clip = self._ovl_layer.add_asset(asset, start_ns, 0, dauer_ns,
                                             GES.TrackType.VIDEO)
            if clip is None:
                self._note(f"Overlay konnte nicht eingefuegt werden: {ovl['image']}")
                continue

            breite = max(1, int(round(ovl["w"] * faktor))) if ovl["w"] else 0
            hoehe = max(1, int(round(ovl["h"] * faktor))) if ovl["h"] else 0
            for el in clip.find_track_elements(None, GES.TrackType.VIDEO,
                                               GES.VideoSource):
                if breite and hoehe:
                    el.set_child_property("width", breite)
                    el.set_child_property("height", hoehe)
                el.set_child_property("posx", int(round(ovl["x"] * faktor)))
                el.set_child_property("posy", int(round(ovl["y"] * faktor)))
                ein, aus = ovl["fade_in"], ovl["fade_out"]
                if ein > 0 or aus > 0:
                    quelle = GstController.InterpolationControlSource()
                    quelle.props.mode = GstController.InterpolationMode.LINEAR
                    el.set_control_source(quelle, "alpha", "direct")
                    quelle.set(0, 0.0 if ein > 0 else 1.0)
                    if ein > 0:
                        quelle.set(min(int(ein * NS), dauer_ns), 1.0)
                    if aus > 0:
                        quelle.set(max(0, dauer_ns - int(aus * NS)), 1.0)
                        quelle.set(dauer_ns, 0.0)
                    else:
                        quelle.set(dauer_ns, 1.0)
            gesetzt += 1
        return gesetzt

    def set_frame_callback(self, rueckruf):
        """Bilder an Qt liefern statt sie selbst anzuzeigen.

        Wirkt nur, wenn die Senke noch nicht gebaut ist - normalerweise
        wird der Rueckruf dem Konstruktor uebergeben. `rueckruf` bekommt
        ein QImage und wird im Qt-Hauptthread aufgerufen.
        """
        self._bild_rueckruf = rueckruf
        return True

    # ------------------------------------------------------------------
    # 360 Grad
    # ------------------------------------------------------------------
    def supports_360(self):
        return view360.verfuegbar()

    def unsupported_360_reason(self):
        """Klartext, warum 360 nicht geht - fuer die Meldung an den Nutzer."""
        return view360.fehlgrund()

    def is_360(self):
        return self._360_an

    def set_360(self, enabled):
        """
        360-Projektion ein- oder ausschalten.

        Das aendert Effektkette UND Zielformat (2:1 der Quelle gegen 16:9 der
        Ausgabe), deshalb muss die Timeline hier einmal neu gebaut werden.
        Fuer das blosse Aendern des Blickwinkels gilt das nicht - siehe
        set_view360().
        """
        enabled = bool(enabled)
        if enabled == self._360_an:
            return True
        if enabled and not view360.verfuegbar():
            self._note(f"360 nicht moeglich: {view360.fehlgrund()}")
            return False
        self._360_an = enabled
        self._limit_preview_size()
        self._rebuild()
        self._note("360 ist " + ("an" if enabled else "aus"))
        return True

    def view360(self, index=None):
        """Blickwinkel des laufenden - oder eines bestimmten - Videos."""
        if index is None:
            index = self.index()
        return self._blick(index).werte()

    def set_view360_liste(self, ansichten):
        """
        Alle Blickwinkel auf einmal setzen - beim Laden eines Projekts.

        `ansichten` ist eine Liste von (yaw, pitch, fov) je Video. Sie darf
        laenger oder kuerzer sein als die Playlist; fehlende Videos bekommen
        die Vorgabe.
        """
        self._blicke = [view360.Blickwinkel(*w) for w in ansichten]
        if self._blicke:
            self._blick_vorgabe = self._blicke[0].kopie()
        self._blicke_angleichen()
        if self._360_an:
            self._alle_uniforms_setzen()
            if self._paused:
                self._blick_auffrischen_anstossen()
        return True

    def _blicke_angleichen(self):
        """Die Liste auf die Anzahl der Quelldateien bringen."""
        fehlend = len(self._assets) - len(self._blicke)
        if fehlend > 0:
            self._blicke += [self._blick_vorgabe.kopie()
                             for _ in range(fehlend)]
        elif fehlend < 0:
            del self._blicke[len(self._assets):]

    def _alle_uniforms_setzen(self):
        breite, hoehe = self._preview_groesse()
        aspect = view360.ziel_aspect(breite, hoehe)
        for index, effekt in self._effekte:
            view360.uniforms_setzen(effekt, self._blick(index), aspect)

    #: Kleinster Abstand zwischen zwei Auffrisch-Spruengen im Standbild.
    #: 60 ms sind rund 16 Spruenge je Sekunde - fluessig genug fuers Auge und
    #: wenig genug, dass der Decoder hinterherkommt.
    BLICK_AUFFRISCHEN_MS = 60

    def set_view360(self, yaw=None, pitch=None, fov=None):
        """
        Blickwinkel setzen.

        Gilt fuer das Video, das gerade laeuft - jede Quelldatei hat ihren
        eigenen Blickwinkel.

        Bewusst OHNE Timeline-Umbau: die Werte gehen als Uniforms direkt an
        die laufenden Shader und greifen am naechsten Bild. Ein _rebuild()
        waere hier verschenkt und wuerde beim Ziehen mit der Maus stocken.
        """
        index = self.index()
        self._blicke_angleichen()
        if 0 <= index < len(self._blicke):
            self._blicke[index].setzen(yaw, pitch, fov)
        else:
            self._blick_vorgabe.setzen(yaw, pitch, fov)
        if not self._360_an:
            return True
        self._alle_uniforms_setzen()
        # Im Standbild rechnet GES von sich aus kein neues Bild - die geaenderte
        # Uniform waere erst beim naechsten Abspielen zu sehen. Gedreht wird
        # aber fast immer im Standbild. Ein Sprung auf die aktuelle Stelle
        # loest ein neues Vorschaubild aus (appsink meldet dann "new-preroll").
        if self._paused:
            self._blick_auffrischen_anstossen()
        return True

    def _blick_auffrischen_anstossen(self):
        """Auffrischen anfordern, aber hoechstens alle BLICK_AUFFRISCHEN_MS.

        Ohne die Drosselung setzt ein Mauszug hunderte Spruenge ab; jeder
        davon leert die Pipeline und dekodiert neu. Der letzte Wunsch geht
        nicht verloren - er wird nachgeholt, sobald die Sperre faellt.
        """
        if self._blick_timer.isActive():
            self._blick_offen = True
            return
        self._blick_offen = False
        self._blick_auffrischen()
        self._blick_timer.start(self.BLICK_AUFFRISCHEN_MS)

    def _blick_timer_abgelaufen(self):
        if self._blick_offen:
            self._blick_offen = False
            self._blick_auffrischen()
            self._blick_timer.start(self.BLICK_AUFFRISCHEN_MS)

    def _blick_auffrischen(self):
        # Auch hier die gemessene Stelle: aufgefrischt wird da, wo das Bild
        # gerade steht. Siehe set_rate() zur Begruendung.
        try:
            self._seek_ns(self._position_ns_frisch())
        except Exception as exc:
            self._note(f"Vorschaubild nicht aufgefrischt: {exc}")

    def _360_abschalten(self, grund):
        """Nach einem Fehler in der Effektkette zurueck auf normale Anzeige."""
        if not self._360_an:
            return
        self._note(f"360 abgeschaltet: {grund}")
        self._360_an = False
        self._limit_preview_size()
        self._rebuild()

    # ------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------
    def set_end_callback(self, callback):
        self._end_callback = callback
