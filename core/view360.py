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
Echte 360-Grad-Ansicht fuer das GES-Backend.

Was hier passiert: 360-Material liegt als EQUIRECTANGULAR-Bild vor - die
gesamte Kugel in ein 2:1-Rechteck gequetscht. Das direkt anzuzeigen sieht
verzerrt aus. Diese Datei rechnet daraus den Ausschnitt, den ein Betrachter
mit einer normalen Kamera saehe (rectilinear), gesteuert ueber drei Werte:

    yaw    Drehung nach links/rechts   (Radiant, -pi .. +pi, laeuft um)
    pitch  Neigung nach oben/unten     (Radiant, -pi/2 .. +pi/2)
    fov    Bildwinkel = Zoom           (Radiant, 30 .. 120 Grad)

WARUM EIN SHADER: GStreamer bindet ffmpegs Filter nicht ein - gst-libav
liefert nur Decoder und Encoder, kein "v360". Ein Element fuer sphaerische
Projektion gibt es in diesem Build nicht. Der Weg ist deshalb "glshader" aus
gst-plugins-base (GL) mit einem eigenen Fragment-Shader. Er wird als
GES.Effect an den Clip gehaengt und wirkt dadurch in der VORSCHAU und im
EXPORT gleichermassen - beide benutzen dieselbe Timeline.

GEMESSEN (GStreamer 1.28.6, Windows, 360_test_1920x960.mp4):
  - Render-Pfad (GES.PipelineFlags.RENDER, x264enc): laeuft bis EOS, Bild
    perspektivisch korrekt.
  - Vorschau-Pfad (appsink wie in ges_backend): 150 Bilder in 5,00 s = 30,0
    fps - genau so schnell wie ohne den Effekt. Der Umweg ueber die
    Grafikkarte kostet hier nichts.

ZWEI FALLEN, beide beim Messen aufgelaufen:

1. Die Uniforms muessen G_TYPE_FLOAT sein. Ein Python-float landet als
   G_TYPE_DOUBLE in der GstStructure, und die Uniform bleibt dann auf 0. Bei
   fov=0 wird 1/tan(0) unendlich, alle Bildpunkte treffen denselben Texel -
   heraus kommt eine einzige Farbe. Deshalb _fval().
2. Der GLSL-Text darf kein BOM haben, sonst bricht der Uebersetzer mit
   "error C0000: syntax error, unexpected $undefined" in Zeile 1 ab. Als
   Konstante im Quelltext ist das kein Thema; wandert der Shader je in eine
   eigene Datei, muss sie ohne BOM geschrieben werden.

NICHT VERSUCHEN: einen Capsfilter in die Bin-Beschreibung des Effekts zu
setzen (also "... ! videoscale ! video/x-raw,width=..."). GES.Effect.new()
gibt dann NULL zurueck, mit der Meldung "ges_effect_new: assertion 'asset'
failed". Die Zielgroesse gehoert an die Restriction-Caps der Spur und an die
Child-Properties width/height der Quelle - siehe rahmen_setzen().
"""

import math

_GST_IMPORT_ERROR = None
try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GES', '1.0')
    from gi.repository import Gst, GES, GObject
except Exception as exc:            # pragma: no cover - haengt an der Umgebung
    _GST_IMPORT_ERROR = exc
    Gst = GES = GObject = None


# Die Kette laesst die AUFLOESUNG unveraendert: der Shader rechnet auf der
# Quelltextur (etwa 1920x960). Auf das Zielformat bringt erst der Positioner
# der Quelle, siehe rahmen_setzen(). Genau diese Aufteilung ist gemessen.
EFFEKT_BIN = ("glupload ! glcolorconvert ! glshader name=kvr360 ! "
              "gldownload ! videoconvert")

# Equirectangular -> rectilinear.
#
# v_texcoord und der Abtaster "tex" sind die Namen, die glshader von sich aus
# vergibt; der eingebaute Vertex-Shader liefert sie.
#
# Rechenweg je Bildpunkt: Bildkoordinate -> Blickrichtung im Kamerasystem
# (uv, Brennweite aus dem Bildwinkel) -> um pitch und yaw gedreht -> als
# Laengen- und Breitengrad gelesen -> daraus die Stelle im Equirect-Bild.
#
# Vorzeichen, damit die Bedienung sich richtig anfuehlt: positives yaw schaut
# nach RECHTS, positives pitch nach OBEN. Fuer die Bildmitte faellt der
# Rechenweg auf lon = yaw und lat = pitch zusammen - daran laesst es sich
# nachpruefen.
#
# "aspect" ist das Seitenverhaeltnis der AUSGABE, nicht das der Textur. Damit
# ist die ungleichmaessige Streckung 2:1 -> 16:9, die der Positioner danach
# vornimmt, genau ausgeglichen: gerade Linien bleiben gerade.
#
# "roll" (seit 7.02) kippt das Bild um die Blickachse - die Horizont-
# korrektur fuer einen leicht schiefen Export. Ein fester Wert je Video
# (Config > 360 Setup), kein Teil der Blickmarken. Positiv = im
# Uhrzeigersinn, angewandt VOR pitch und yaw, damit die Korrektur wie eine
# Neigung der Kamera wirkt und nicht wie ein Kippen des fertigen Bildes.
FRAGMENT = """
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float yaw;
uniform float pitch;
uniform float fov;
uniform float aspect;
uniform float roll;
void main() {
  vec2 uv = (v_texcoord - 0.5) * 2.0;
  uv.x *= aspect;
  float f = 1.0 / tan(fov * 0.5);
  vec3 d = normalize(vec3(uv.x, -uv.y, f));
  float cr = cos(roll), sr = sin(roll);
  d = vec3(d.x * cr - d.y * sr, d.x * sr + d.y * cr, d.z);
  float cp = cos(pitch), sp = sin(pitch);
  d = vec3(d.x, d.y * cp + d.z * sp, -d.y * sp + d.z * cp);
  float cy = cos(yaw), sy = sin(yaw);
  d = vec3(d.x * cy + d.z * sy, d.y, -d.x * sy + d.z * cy);
  float lon = atan(d.x, d.z);
  float lat = asin(clamp(d.y, -1.0, 1.0));
  gl_FragColor = texture2D(tex, vec2(lon / 6.2831853 + 0.5,
                                     0.5 - lat / 3.14159265));
}
"""

# Bildwinkel-Grenzen. Unter 30 Grad wird die Vergroesserung so stark, dass die
# Bildpunkte der Quelle sichtbar werden; ueber 120 Grad kippt die
# rectilineare Projektion an den Raendern ins Unbrauchbare.
FOV_MIN = math.radians(30.0)
FOV_MAX = math.radians(120.0)
FOV_VORGABE = math.radians(90.0)

# Seitenverhaeltnis der Ausgabe, wenn 360 an ist. Das Quellformat 2:1 ist die
# Kugel, kein Bildformat - als Ausgabe will man das nie.
ZIEL_BREITE_TEIL = 16
ZIEL_HOEHE_TEIL = 9


def verfuegbar():
    """True, wenn die GL-Elemente fuer den Shader vorhanden sind."""
    return not fehlgrund()


def fehlgrund():
    """Warum 360 nicht geht - leerer Text, wenn es geht."""
    if _GST_IMPORT_ERROR is not None:
        return f"GStreamer could not be loaded: {_GST_IMPORT_ERROR}"
    # Ohne Gst.init() ist die Registry leer und JEDES Element gilt als nicht
    # vorhanden. Der Aufrufer kann frueher dran sein als das Backend, deshalb
    # hier selbst nachziehen - Gst.init ist mehrfach aufrufbar.
    try:
        if not Gst.is_initialized():
            Gst.init(None)
    except Exception as exc:
        return f"GStreamer could not be started: {exc}"
    fehlt = []
    for name in ("glupload", "glcolorconvert", "glshader", "gldownload"):
        try:
            if Gst.ElementFactory.make(name, None) is None:
                fehlt.append(name)
        except Exception:
            fehlt.append(name)
    if fehlt:
        return ("360 needs the GL elements " + ", ".join(fehlt)
                + " (Linux: package gstreamer1.0-gl)")
    return ""


def ziel_hoehe(breite):
    """Ausgabehoehe zur Breite im 16:9-Format, immer gerade."""
    hoehe = int(round(int(breite) * ZIEL_HOEHE_TEIL / float(ZIEL_BREITE_TEIL)))
    return hoehe + 1 if hoehe % 2 else hoehe


def ziel_aspect(breite, hoehe):
    """Seitenverhaeltnis fuer die Uniform. Faellt auf 16:9 zurueck."""
    try:
        breite, hoehe = float(breite), float(hoehe)
        if breite > 0 and hoehe > 0:
            return breite / hoehe
    except (TypeError, ValueError):
        pass
    return ZIEL_BREITE_TEIL / float(ZIEL_HOEHE_TEIL)


def ist_equirect(breite, hoehe):
    """
    Sieht das nach 360-Material aus?

    Kennzeichen ist das Seitenverhaeltnis 2:1. Dieselbe Regel benutzt die
    Automatik im Hauptfenster schon.
    """
    try:
        breite, hoehe = int(breite), int(hoehe)
    except (TypeError, ValueError):
        return False
    return hoehe > 0 and breite == hoehe * 2


class Blickwinkel:
    """yaw/pitch/fov in Radiant, immer im gueltigen Bereich."""

    __slots__ = ("yaw", "pitch", "fov")

    def __init__(self, yaw=0.0, pitch=0.0, fov=FOV_VORGABE):
        self.yaw = 0.0
        self.pitch = 0.0
        self.fov = FOV_VORGABE
        self.setzen(yaw, pitch, fov)

    def setzen(self, yaw=None, pitch=None, fov=None):
        """Absolut setzen. None laesst den jeweiligen Wert stehen."""
        if yaw is not None:
            # Umlaufen statt anschlagen: ueber die 360-Naht zu schwenken ist
            # der Sinn der Sache.
            self.yaw = (float(yaw) + math.pi) % (2.0 * math.pi) - math.pi
        if pitch is not None:
            # Hier NICHT umlaufen: ueber den Zenit hinaus zu kippen stellt das
            # Bild auf den Kopf.
            self.pitch = max(-math.pi / 2.0, min(math.pi / 2.0, float(pitch)))
        if fov is not None:
            self.fov = max(FOV_MIN, min(FOV_MAX, float(fov)))
        return self

    def verschieben(self, d_yaw=0.0, d_pitch=0.0, d_fov=0.0):
        """Relativ aendern - das, was Maus und Tastatur liefern."""
        return self.setzen(self.yaw + d_yaw, self.pitch + d_pitch,
                           self.fov + d_fov)

    def zuruecksetzen(self):
        return self.setzen(0.0, 0.0, FOV_VORGABE)

    def werte(self):
        return self.yaw, self.pitch, self.fov

    def kopie(self):
        return Blickwinkel(self.yaw, self.pitch, self.fov)

    # --- Projektdatei -----------------------------------------------------
    def als_dict(self):
        # Sechs Nachkommastellen halten die Projektdatei lesbar. Der Verlust
        # ist gemessen hoechstens 0,000013 Grad; ein Bildpunkt entspricht bei
        # 1280 Breite und 90 Grad Bildwinkel 0,07 Grad - also rund das
        # Fuenftausendfache. Sichtbar ist das nicht.
        return {"yaw": round(self.yaw, 6),
                "pitch": round(self.pitch, 6),
                "fov": round(self.fov, 6)}

    @staticmethod
    def aus_dict(daten):
        """Aus der Projektdatei. Unbrauchbares gibt die Vorgabe."""
        if not isinstance(daten, dict):
            return Blickwinkel()

        def _zahl(name, vorgabe):
            try:
                wert = float(daten.get(name, vorgabe))
            except (TypeError, ValueError):
                return vorgabe
            return vorgabe if wert != wert else wert     # NaN abfangen

        return Blickwinkel(_zahl("yaw", 0.0), _zahl("pitch", 0.0),
                           _zahl("fov", FOV_VORGABE))

    def __eq__(self, other):
        if not isinstance(other, Blickwinkel):
            return NotImplemented
        return self.werte() == other.werte()

    def __repr__(self):
        return (f"Blickwinkel(yaw={math.degrees(self.yaw):.1f}deg, "
                f"pitch={math.degrees(self.pitch):.1f}deg, "
                f"fov={math.degrees(self.fov):.1f}deg)")


def _fval(wert):
    """float als G_TYPE_FLOAT. Siehe Falle 1 im Dateikopf."""
    v = GObject.Value()
    v.init(GObject.TYPE_FLOAT)
    v.set_float(float(wert))
    return v


def _uniforms(blickwinkel, aspect, roll=0.0):
    st = Gst.Structure.new_empty("uniforms")
    st.set_value("yaw", _fval(blickwinkel.yaw))
    st.set_value("pitch", _fval(blickwinkel.pitch))
    st.set_value("fov", _fval(blickwinkel.fov))
    st.set_value("aspect", _fval(aspect))
    st.set_value("roll", _fval(roll))
    return st


def effekt_anhaengen(clip, blickwinkel, aspect, roll=0.0):
    """
    Den 360-Shader an einen Clip haengen.

    Rueckgabe ist der Effekt - damit lassen sich die Werte spaeter ohne
    Timeline-Umbau nachziehen - oder None, wenn es nicht ging. Ob das ein
    Fehler ist, entscheidet der Aufrufer.
    """
    if clip is None or _GST_IMPORT_ERROR is not None:
        return None
    try:
        effekt = GES.Effect.new(EFFEKT_BIN)
        if effekt is None:
            return None
        clip.add_top_effect(effekt, -1)
        effekt.set_child_property("fragment", FRAGMENT)
        effekt.set_child_property("uniforms", _uniforms(blickwinkel, aspect, roll))
        return effekt
    except Exception:
        return None


def uniforms_setzen(effekt, blickwinkel, aspect, roll=0.0):
    """
    Nur die Werte neu setzen, ohne die Timeline anzufassen.

    Das ist der Weg fuer Maus und Mausrad: die Aenderung greift am naechsten
    Bild, die Pipeline laeuft dabei durch. Ein Timeline-Neuaufbau waere hier
    verschenkt und wuerde sichtbar stocken.
    """
    if effekt is None or _GST_IMPORT_ERROR is not None:
        return False
    try:
        effekt.set_child_property("uniforms", _uniforms(blickwinkel, aspect, roll))
        return True
    except Exception:
        return False


def shader_element(effekt):
    """
    Das glshader-Element in der Effekt-Bin - oder None.

    GES haengt die Bin aus EFFEKT_BIN in ein NleOperation; dort ist sie
    ueber den Namen "kvr360" erreichbar. Gemessen am 12.09.2026
    (tools/mess_360_keyframes.py): nach commit_sync() der Timeline ist das
    Element da. Vorher kann es fehlen - dann None, und der Aufrufer
    versucht es nach dem Commit noch einmal.
    """
    if effekt is None or _GST_IMPORT_ERROR is not None:
        return None
    try:
        wurzel = effekt.get_nleobject()
    except Exception:
        wurzel = None
    if wurzel is None or not isinstance(wurzel, Gst.Bin):
        return None
    treffer = wurzel.get_by_name("kvr360")
    if treffer is not None:
        return treffer
    try:
        for kind in wurzel.iterate_recurse():
            fabrik = kind.get_factory()
            if fabrik is not None and fabrik.get_name() == "glshader":
                return kind
    except Exception:
        pass
    return None


def _element_in_bin(effekt, fabrikname):
    """Das erste Element dieser Fabrik in der Effekt-Bin - oder None."""
    if effekt is None or _GST_IMPORT_ERROR is not None:
        return None
    try:
        wurzel = effekt.get_nleobject()
        if wurzel is None or not isinstance(wurzel, Gst.Bin):
            return None
        for kind in wurzel.iterate_recurse():
            fabrik = kind.get_factory()
            if fabrik is not None and fabrik.get_name() == fabrikname:
                return kind
    except Exception:
        pass
    return None


def probe_anhaengen(effekt, rohstart_s, von_s, bis_s, kurve_holen, aspect,
                    grundblick_holen=None, roll_holen=None):
    """
    Blickverlauf JE BILD: eine Buffer-Probe am Sink-Pad des Shaders.

    Sie liest den Zeitstempel des Bildes, rechnet daraus die Rohzeit,
    schlaegt in der Kurve nach und setzt die Uniforms, bevor der Shader
    das Bild rechnet. Gemessen am 12.09.2026 (tools/mess_360_keyframes.py,
    Ergebnisse in doc/Plan_360_Editor.md, Abschnitt 2):

      - Der PTS an dieser Stelle ist die ZEIT IN DER QUELLDATEI. Die
        Rohzeit der App ist deshalb rohstart_s + pts, ohne Clip-Start und
        ohne In-Point. Das gilt fuer Quellclips - nicht fuer Standbilder
        oder vorgerenderte Blenden, deren PTS bei 0 beginnt; die bekommen
        keine Probe, sondern einen festen Blick.
      - Der Wert greift fuer genau dieses Bild, nicht erst das naechste.
      - Setzen direkt am Element kostet 0,16 ms je Bild und ist aus dem
        Streaming-Thread heraus unbedenklich.
      - Vor dem eigentlichen Clip liefert GStreamer ein paar Vorlauf-Bilder
        vom Dateianfang; sie landen nicht im Bild und brauchen keine
        Sonderbehandlung.

    kurve_holen: Funktion ohne Argumente, die die aktuelle Kurve liefert
    (core/blickverlauf.Kurve) oder None. Eine Funktion und kein Wert, damit
    die Vorschau die Kurve austauschen oder vorruebergehend abschalten
    kann (Ziehen mit der Maus), ohne die Timeline anzufassen.

    von_s/bis_s: Rohbereich der Quelldatei - nur Marken darin zaehlen.
    grundblick_holen: Funktion ohne Argumente, die den festen Blick der
    Datei liefert - der Ausgangspunkt vor der ersten Marke (siehe
    blickverlauf.Kurve.blick_bei). roll_holen: dasselbe fuer die
    Horizontkorrektur der Datei (Radiant). Liefert True, wenn die Probe
    haengt.
    """
    shader = shader_element(effekt)
    if shader is None:
        return False
    # Die Probe sitzt am Eingang von glupload, NICHT am Shader: dort ist der
    # Puffer noch normaler Speicher und der Thread der des Decoders. Am
    # Sink-Pad des Shaders lief die Probe im GL-Thread; mit x264enc ging
    # das, mit nvh265enc blieb die Pipeline stehen (12.09.2026, kleiner
    # Testclip, nach 150 s abgebrochen - siehe doc/Plan_360_Editor.md).
    # Der Puffer ist derselbe, der gleich durch den Shader geht; die
    # Uniforms greifen deshalb weiterhin fuer genau dieses Bild.
    pad = None
    hochlader = _element_in_bin(effekt, "glupload")
    if hochlader is not None:
        pad = hochlader.get_static_pad("sink")
    if pad is None:
        pad = shader.get_static_pad("sink")
    if pad is None:
        return False
    ns = float(Gst.SECOND)

    def _auf_bild(_pad, info, _daten):
        kurve = kurve_holen()
        if kurve is None:
            return Gst.PadProbeReturn.OK
        try:
            puffer = info.get_buffer()
            if puffer is None or puffer.pts == Gst.CLOCK_TIME_NONE:
                return Gst.PadProbeReturn.OK
            grund = grundblick_holen() if grundblick_holen is not None else None
            blick = kurve.blick_bei(rohstart_s + puffer.pts / ns, von_s, bis_s,
                                    grund)
            if blick is not None:
                roll = roll_holen() if roll_holen is not None else 0.0
                shader.set_property("uniforms", _uniforms(blick, aspect, roll))
        except Exception:
            pass
        return Gst.PadProbeReturn.OK

    pad.add_probe(Gst.PadProbeType.BUFFER, _auf_bild, None)
    return True


def rahmen_setzen(clip, breite, hoehe):
    """
    Die Quelle randlos auf das Zielbild legen.

    Ohne das passt GES das 2:1-Bild mit schwarzen Balken in ein 16:9-Bild ein.
    Die ungleichmaessige Streckung, die dabei entsteht, ist im Shader ueber
    "aspect" schon eingerechnet - das Ergebnis ist geometrisch richtig.

    Dieselben Child-Properties benutzt die App bereits fuer Overlays
    (ges_backend._overlays_einsetzen, ges_encoder_manager._overlays_setzen).
    """
    if clip is None or _GST_IMPORT_ERROR is not None:
        return False
    gesetzt = False
    try:
        for element in clip.find_track_elements(None, GES.TrackType.VIDEO,
                                                GES.VideoSource):
            element.set_child_property("posx", 0)
            element.set_child_property("posy", 0)
            element.set_child_property("width", int(breite))
            element.set_child_property("height", int(hoehe))
            gesetzt = True
    except Exception:
        return False
    return gesetzt
