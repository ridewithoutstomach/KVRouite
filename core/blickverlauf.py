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
Blickmarken (Keyframes) fuer den 360-Modus.

Bis 7.01 hatte jede Quelldatei EINEN festen Blickwinkel (core/view360.py,
Blickwinkel). Hier kommt der Verlauf dazu: an einer Rohzeit t gilt ein
Blick, an einer spaeteren ein anderer, dazwischen schwenkt die Kamera.

Begriffe:

    Blickmarke   ein Zeitpunkt (Rohzeit ueber alle Videos, Sekunden, wie
                 die Schnitte im cut_manager) mit yaw/pitch/fov und der
                 Uebergangsart IN DIESE MARKE HINEIN: "smooth" = die Kamera
                 schwenkt vom vorigen Blick her und kommt hier an, "hard" =
                 der vorige Blick bleibt stehen und springt hier um.
                 (Bis zum 12.09.2026 galt die Art fuer den Abschnitt NACH
                 der Marke - Bernd hat "hard" auf der Marke gesetzt, an der
                 der Sprung sein soll, und nichts gesehen. So herum passt
                 es auch fuer die erste Marke ab dem Grundblick.)
    Blickverlauf die sortierte Liste der Marken. Sie wird bearbeitet
                 (Hauptthread) und fuer die Wiedergabe EINGEFROREN.
    Kurve        der eingefrorene Verlauf. Unveraenderlich, deshalb darf
                 der Streaming-Thread von GStreamer ohne Sperre darin
                 nachschlagen (siehe view360.probe_anhaengen).

Regeln, siehe doc/Plan_360_Editor.md, Abschnitt 3.1:

  - Marken gelten je QUELLDATEI. blick_bei() bekommt den Rohbereich der
    Datei (von, bis) und sieht nur die Marken darin. Ueber eine
    Dateigrenze hinweg wird nicht interpoliert - jede Aufnahme kann anders
    montiert sein.
  - Der feste Blick der Datei (Grundblick) ist der AUSGANGSPUNKT: vom
    Dateianfang bis zur ersten Marke schwenkt die Kamera weich vom
    Grundblick zur ersten Marke und erreicht sie genau dort. Bernd
    (12.09.2026): "das Video muss von Anfang so laufen, wie es gestartet
    ist, und ab dem KF erst die neue Position haben" - niemand setzt eine
    Marke bei 0, nur um den Start festzuhalten. Nach der letzten Marke
    gilt die letzte. Dazwischen wird interpoliert, ausser die HINTERE
    Marke ist "hard": dann bleibt die vordere stehen und springt dort um.
  - Yaw geht den kuerzeren Weg ueber die Naht bei +-180 Grad. Pitch und
    Bildwinkel gehen linear.
  - "smooth" ist Smoothstep (weich anfahren, weich abbremsen). Linear
    wirkt bei Kamerafahrten mechanisch.
  - Hat eine Datei keine Marke, liefert blick_bei() None, und der feste
    Blickwinkel der Datei (Grundblick) gilt wie bisher.

Reines Python, ohne Qt und ohne GStreamer - damit laesst sich die
Interpolation mit festen Zahlen nachrechnen.
"""

import bisect
import math

from core.view360 import Blickwinkel, FOV_VORGABE

WEICH = "smooth"
HART = "hard"
ARTEN = (WEICH, HART)

#: Zwei Marken naeher als das gelten als DIESELBE Stelle: Setzen ueberschreibt,
#: Loeschen trifft. 50 ms sind gut ein Bild bei 25 fps - genauer setzt niemand
#: mit dem Marker, und zwei Marken in einem Bild ergeben keinen Sinn.
TOLERANZ_S = 0.05

_ZWEI_PI = 2.0 * math.pi


class Blickmarke:
    __slots__ = ("t", "yaw", "pitch", "fov", "art")

    def __init__(self, t, yaw=0.0, pitch=0.0, fov=FOV_VORGABE, art=WEICH):
        self.t = float(t)
        b = Blickwinkel(yaw, pitch, fov)      # wickelt yaw, klemmt pitch/fov
        self.yaw, self.pitch, self.fov = b.yaw, b.pitch, b.fov
        self.art = art if art in ARTEN else WEICH

    def blick(self):
        return Blickwinkel(self.yaw, self.pitch, self.fov)

    def als_dict(self):
        return {"t": round(self.t, 3),
                "yaw": round(self.yaw, 6),
                "pitch": round(self.pitch, 6),
                "fov": round(self.fov, 6),
                "mode": self.art}

    @staticmethod
    def aus_dict(daten):
        """None, wenn der Eintrag unbrauchbar ist - der Verlauf ueberliest ihn."""
        if not isinstance(daten, dict):
            return None
        try:
            t = float(daten["t"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(t) or t < 0:
            return None

        def _zahl(name, vorgabe):
            try:
                wert = float(daten.get(name, vorgabe))
                return wert if math.isfinite(wert) else vorgabe
            except (TypeError, ValueError):
                return vorgabe
        return Blickmarke(t, _zahl("yaw", 0.0), _zahl("pitch", 0.0),
                          _zahl("fov", FOV_VORGABE), daten.get("mode", WEICH))

    def __repr__(self):
        return (f"Blickmarke(t={self.t:.3f}s, yaw={math.degrees(self.yaw):.1f}deg, "
                f"pitch={math.degrees(self.pitch):.1f}deg, "
                f"fov={math.degrees(self.fov):.1f}deg, {self.art})")


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------
def _yaw_weg(von, nach):
    """Kuerzester Drehweg von 'von' nach 'nach', in -pi..+pi."""
    return (nach - von + math.pi) % _ZWEI_PI - math.pi


def _zwischen(a, b, t):
    """Blick zwischen den Marken a und b zur Zeit t (a.t <= t <= b.t).
    Die Art von b sagt, wie b erreicht wird: hart = a bleibt bis b stehen."""
    if b.t <= a.t:
        return b.blick()
    if b.art == HART:
        return a.blick() if t < b.t else b.blick()
    s = (t - a.t) / (b.t - a.t)
    s = 0.0 if s < 0.0 else 1.0 if s > 1.0 else s
    s = s * s * (3.0 - 2.0 * s)                 # Smoothstep
    return Blickwinkel(a.yaw + _yaw_weg(a.yaw, b.yaw) * s,
                       a.pitch + (b.pitch - a.pitch) * s,
                       a.fov + (b.fov - a.fov) * s)


class Kurve:
    """Eingefrorener Verlauf: Tupel, keine Methoden, die etwas aendern."""

    __slots__ = ("zeiten", "marken")

    def __init__(self, marken):
        self.marken = tuple(marken)
        self.zeiten = tuple(m.t for m in self.marken)

    def __len__(self):
        return len(self.marken)

    def hat_marken(self, von, bis):
        """Liegt mindestens eine Marke im Rohbereich [von, bis)?"""
        i = bisect.bisect_left(self.zeiten, von)
        return i < len(self.zeiten) and self.zeiten[i] < bis

    def blick_bei(self, t, von, bis, grundblick=None):
        """
        Blick zur Rohzeit t, nur mit den Marken im Bereich [von, bis).

        None, wenn dort keine Marke liegt - dann gilt der Grundblick der
        Datei, das entscheidet der Aufrufer.

        grundblick: der feste Blick der Datei. Vor der ersten Marke wird
        von ihm aus (ab Dateianfang `von`) zur ersten Marke geschwenkt -
        oder er bleibt stehen, wenn die erste Marke "hard" ist. Ohne
        Angabe gilt vor der ersten Marke die erste.
        """
        lo = bisect.bisect_left(self.zeiten, von)
        hi = bisect.bisect_left(self.zeiten, bis)
        if lo >= hi:
            return None
        if t <= self.zeiten[lo]:
            erste = self.marken[lo]
            if grundblick is None or erste.t <= von:
                return erste.blick()
            start = Blickmarke(von, grundblick.yaw, grundblick.pitch,
                               grundblick.fov, WEICH)
            if t <= von:
                return start.blick()
            return _zwischen(start, erste, t)
        if t >= self.zeiten[hi - 1]:
            return self.marken[hi - 1].blick()
        i = bisect.bisect_right(self.zeiten, t, lo, hi)   # erste Marke NACH t
        return _zwischen(self.marken[i - 1], self.marken[i], t)


class Blickverlauf:
    """Die bearbeitbare Liste. Immer nach t sortiert."""

    def __init__(self, marken=None):
        self._marken = sorted((m for m in (marken or []) if m is not None),
                              key=lambda m: m.t)

    # -- lesen ---------------------------------------------------------------
    def __len__(self):
        return len(self._marken)

    def __iter__(self):
        return iter(self._marken)

    def leer(self):
        return not self._marken

    def zeiten(self):
        return [m.t for m in self._marken]

    def einfrieren(self):
        """Unveraenderliche Kurve fuer die Wiedergabe; None ohne Marken."""
        return Kurve(self._marken) if self._marken else None

    def _index_bei(self, t, toleranz=TOLERANZ_S):
        """Index der Marke an t (innerhalb der Toleranz) oder -1."""
        zeiten = [m.t for m in self._marken]
        i = bisect.bisect_left(zeiten, t)
        beste, abstand = -1, toleranz
        for k in (i - 1, i):
            if 0 <= k < len(zeiten) and abs(zeiten[k] - t) <= abstand:
                beste, abstand = k, abs(zeiten[k] - t)
        return beste

    def bei(self, t, toleranz=TOLERANZ_S):
        i = self._index_bei(t, toleranz)
        return self._marken[i] if i >= 0 else None

    def vorherige(self, t, toleranz=TOLERANZ_S):
        """Letzte Marke deutlich VOR t, oder None."""
        letzte = None
        for m in self._marken:
            if m.t < t - toleranz:
                letzte = m
            else:
                break
        return letzte

    def naechste(self, t, toleranz=TOLERANZ_S):
        """Erste Marke deutlich NACH t, oder None."""
        for m in self._marken:
            if m.t > t + toleranz:
                return m
        return None

    def im_bereich(self, von, bis):
        return [m for m in self._marken if von <= m.t < bis]

    # -- aendern -------------------------------------------------------------
    def setzen(self, t, yaw, pitch, fov, art=None):
        """
        Marke an t setzen. Liegt dort schon eine (Toleranz), werden ihre
        Werte ueberschrieben und ihre Uebergangsart bleibt, wenn keine neue
        angegeben ist. Liefert die Marke.
        """
        i = self._index_bei(t)
        if i >= 0:
            alt = self._marken[i]
            neu = Blickmarke(alt.t, yaw, pitch, fov,
                             art if art in ARTEN else alt.art)
            self._marken[i] = neu
            return neu
        neu = Blickmarke(t, yaw, pitch, fov, art if art in ARTEN else WEICH)
        bisect.insort(self._marken, neu, key=lambda m: m.t)
        return neu

    def art_setzen(self, t, art):
        m = self.bei(t)
        if m is None or art not in ARTEN:
            return False
        m.art = art
        return True

    def verschieben(self, t_alt, t_neu):
        """Marke von t_alt nach t_neu ruecken. False, wenn keine da ist."""
        i = self._index_bei(t_alt)
        if i < 0:
            return False
        m = self._marken.pop(i)
        m.t = float(max(0.0, t_neu))
        bisect.insort(self._marken, m, key=lambda x: x.t)
        return True

    def entfernen(self, t, toleranz=TOLERANZ_S):
        i = self._index_bei(t, toleranz)
        if i < 0:
            return False
        del self._marken[i]
        return True

    def alle_entfernen(self, von=None, bis=None):
        """Alle Marken, oder nur die im Rohbereich [von, bis)."""
        if von is None and bis is None:
            self._marken = []
            return
        von = -math.inf if von is None else von
        bis = math.inf if bis is None else bis
        self._marken = [m for m in self._marken if not (von <= m.t < bis)]

    # -- Projekt -------------------------------------------------------------
    def als_liste(self):
        return [m.als_dict() for m in self._marken]

    @classmethod
    def aus_liste(cls, roh):
        """Unbrauchbare Eintraege werden ueberlesen, nicht beanstandet."""
        if not isinstance(roh, (list, tuple)):
            return cls()
        return cls(Blickmarke.aus_dict(d) for d in roh)

    def kopie(self):
        return Blickverlauf(Blickmarke(m.t, m.yaw, m.pitch, m.fov, m.art)
                            for m in self._marken)

    def __repr__(self):
        return f"Blickverlauf({len(self._marken)} Marken)"
