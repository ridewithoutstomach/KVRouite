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
Height profile editor (B..E): das Hoehenprofil eines Abschnitts mit der Maus
nachbauen.

Waagerecht die Strecke, senkrecht die Hoehe. Das aufgezeichnete Profil bleibt
grau im Hintergrund, B und E sind fest. Klick auf die Linie setzt einen
Stuetzpunkt, Ziehen aendert seine Hoehe, Rechtsklick entfernt ihn. An jedem
Abschnitt steht die Steigung, am letzten, was bis E uebrig bleibt - so sieht
man beim ersten Punkt schon, ob der Rest noch aufgehen kann. Die Rechnung
steht in core/hoehenprofil.py.

Das Fenster blockiert nicht: nebenbei laesst sich im Video spulen, die
Videoposition steht als Strich im Profil, und ein Klick auf einen Stuetzpunkt
faehrt das Video dorthin.
"""

from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QDoubleSpinBox,
                               QInputDialog, QMessageBox, QSizePolicy)

from core import theme
from core import hoehenprofil


class ProfilFlaeche(QWidget):
    """Die Zeichenflaeche mit den Stuetzpunkten."""

    geaendert = Signal()
    stuetzpunktGewaehlt = Signal(float)   # Strecke s des angeklickten Punkts
    auswahlGeaendert = Signal(int)        # Index des gewaehlten Punkts, -1 ohne

    RAND_L, RAND_R, RAND_O, RAND_U = 62, 16, 14, 30
    GRIFF_PX = 9
    # Naeher zusammen kommen zwei Stuetzpunkte nicht: zwei Klicks 1 m
    # auseinander ergaben "339.5 % over 1 m" (07.09.2026).
    MIN_ABSTAND_M = 5.0

    def __init__(self, strecke, alt, h_b, h_e, parent=None, vor=(), nach=()):
        super().__init__(parent)
        self._strecke = list(strecke)
        self._alt = list(alt)
        # Aufzeichnung vor B (s < 0, endet bei 0) und nach E (s > S): nur zum
        # Ansehen, damit man weiss, mit welcher Steigung es in den Abschnitt
        # hinein- und wieder herausgeht.
        self._vor = [(float(s), float(h)) for s, h in vor]
        self._nach = [(float(s), float(h)) for s, h in nach]
        # Stuetzpunkt: [s, h, ausrundung_m]. B und E haben 0, sie sind fest.
        self._stuetzen = [[0.0, float(h_b), 0.0], [float(strecke[-1]), float(h_e), 0.0]]
        self._ausrundung = 30.0     # Vorgabe fuer neue Punkte
        self._gewaehlt = None       # Index in _stuetzen
        self._ziehen = False
        self._video_s = None
        # Der Stuetzpunkt, den der letzte Mausdruck angelegt hat. Kommt
        # danach ein Doppelklick, war der Druck dessen erste Haelfte: der
        # Punkt geht wieder weg, der Doppelklick meint den Abschnitt.
        self._neu_durch_klick = None
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---------------------------------------------------------------- Daten
    def stuetzen(self):
        return [tuple(p) for p in self._stuetzen]

    def ausrundung(self):
        """Vorgabe fuer neue Stuetzpunkte."""
        return self._ausrundung

    def set_ausrundung(self, meter):
        self._ausrundung = max(0.0, float(meter))

    def gewaehlt(self):
        return self._gewaehlt

    def ausrundung_setzen(self, idx, meter):
        """Ausrundung EINES inneren Stuetzpunkts: kurz fuer einen schnellen
        Steigungswechsel, lang fuer einen langsamen."""
        if idx is None or idx <= 0 or idx >= len(self._stuetzen) - 1:
            return
        self._stuetzen[idx][2] = max(0.0, float(meter))
        self.update()
        self.geaendert.emit()

    def ausrundung_alle(self, meter):
        for k in range(1, len(self._stuetzen) - 1):
            self._stuetzen[k][2] = max(0.0, float(meter))
        self._ausrundung = max(0.0, float(meter))
        self.update()
        self.geaendert.emit()

    def hoehen(self):
        """Die Hoehe an jedem Punkt der Spur - das, was uebernommen wird."""
        return hoehenprofil.profil(self._strecke, self._stuetzen, self._ausrundung)

    def _auswaehlen(self, idx):
        if idx != self._gewaehlt:
            self._gewaehlt = idx
            self.auswahlGeaendert.emit(-1 if idx is None else idx)

    def set_video_s(self, s):
        if s != self._video_s:
            self._video_s = s
            self.update()

    def stuetzpunkt_hinzufuegen(self, s, h=None):
        """Neuer Stuetzpunkt bei Strecke s; ohne h auf der aktuellen Linie,
        damit nichts springt. Rueckgabe: sein Index, None wenn zu nah an
        einem vorhandenen."""
        S = self._strecke[-1]
        s = min(max(float(s), 0.0), S)
        for p in self._stuetzen:
            if abs(p[0] - s) < self.MIN_ABSTAND_M:
                return None
        if h is None:
            h = hoehenprofil.hoehe_bei(s, self._stuetzen, self._ausrundung)
        self._stuetzen.append([s, float(h), self._ausrundung])
        self._stuetzen.sort(key=lambda p: p[0])
        idx = next(i for i, p in enumerate(self._stuetzen) if p[0] == s)
        self._auswaehlen(idx)
        self.update()
        self.geaendert.emit()
        return idx

    def hoehe_setzen(self, idx, h):
        """Hoehe eines inneren Stuetzpunkts; B und E sind fest."""
        if idx <= 0 or idx >= len(self._stuetzen) - 1:
            return
        self._stuetzen[idx][1] = float(h)
        self.update()
        self.geaendert.emit()

    def entfernen(self, idx):
        if idx <= 0 or idx >= len(self._stuetzen) - 1:
            return
        del self._stuetzen[idx]
        self._auswaehlen(None)
        self.update()
        self.geaendert.emit()

    def steigung_setzen(self, abschnitt, prozent):
        """Steigung eines Abschnitts vorgeben: der Endpunkt des Abschnitts
        rutscht. Ist der Endpunkt E (fest), rutscht der Anfangspunkt; sind
        beide fest, geht es nicht."""
        n = len(self._stuetzen)
        if abschnitt < 0 or abschnitt >= n - 1:
            return False
        s0, h0 = self._stuetzen[abschnitt][0], self._stuetzen[abschnitt][1]
        s1, h1 = self._stuetzen[abschnitt + 1][0], self._stuetzen[abschnitt + 1][1]
        if abschnitt + 1 < n - 1:
            self._stuetzen[abschnitt + 1][1] = h0 + prozent / 100.0 * (s1 - s0)
        elif abschnitt > 0:
            self._stuetzen[abschnitt][1] = h1 - prozent / 100.0 * (s1 - s0)
        else:
            return False
        self.update()
        self.geaendert.emit()
        return True

    # ------------------------------------------------------------ Geometrie
    def _plot(self):
        return QRectF(self.RAND_L, self.RAND_O,
                      max(10, self.width() - self.RAND_L - self.RAND_R),
                      max(10, self.height() - self.RAND_O - self.RAND_U))

    def _h_bereich(self):
        werte = (list(self._alt) + [p[1] for p in self._stuetzen]
                 + [h for _, h in self._vor] + [h for _, h in self._nach])
        lo, hi = min(werte), max(werte)
        spanne = max(hi - lo, 5.0)
        return lo - spanne * 0.15, hi + spanne * 0.15

    def _s_bereich(self):
        """Gezeichnete Strecke: von der Aufzeichnung vor B bis nach E."""
        s_min = self._vor[0][0] if self._vor else 0.0
        s_max = self._nach[-1][0] if self._nach else self._strecke[-1]
        return s_min, max(s_max, s_min + 1.0)

    def _xy(self, s, h):
        r = self._plot()
        lo, hi = self._h_bereich()
        s_min, s_max = self._s_bereich()
        x = r.left() + (s - s_min) / (s_max - s_min) * r.width()
        y = r.bottom() - (h - lo) / (hi - lo) * r.height()
        return QPointF(x, y)

    def _s_von_x(self, x):
        """Strecke unter x, auf den Abschnitt B..E geklemmt - Stuetzpunkte
        gibt es nur dort."""
        r = self._plot()
        s_min, s_max = self._s_bereich()
        S = self._strecke[-1]
        return min(max(s_min + (x - r.left()) / r.width() * (s_max - s_min), 0.0), S)

    def _h_von_y(self, y):
        r = self._plot()
        lo, hi = self._h_bereich()
        return lo + (r.bottom() - y) / r.height() * (hi - lo)

    def _treffer(self, pos):
        """Index des Stuetzpunkts unter der Maus, sonst None."""
        for i, p_ in enumerate(self._stuetzen):
            p = self._xy(p_[0], p_[1])
            if abs(p.x() - pos.x()) <= self.GRIFF_PX and abs(p.y() - pos.y()) <= self.GRIFF_PX:
                return i
        return None

    def _abschnitt_bei(self, x):
        s = self._s_von_x(x)
        for i in range(len(self._stuetzen) - 1):
            if self._stuetzen[i][0] <= s <= self._stuetzen[i + 1][0]:
                return i
        return None

    # ---------------------------------------------------------------- Maus
    def mousePressEvent(self, ev):
        pos = ev.position()
        idx = self._treffer(pos)
        self._neu_durch_klick = None
        if ev.button() == Qt.RightButton:
            if idx is not None:
                self.entfernen(idx)
            return
        if ev.button() != Qt.LeftButton:
            return
        if idx is None:
            if not self._plot().contains(pos):
                return
            s = self._s_von_x(pos.x())
            idx = self.stuetzpunkt_hinzufuegen(s)
            if idx is None:
                # zu nah an einem vorhandenen Punkt: den waehlen, nicht ziehen
                idx = min(range(len(self._stuetzen)), key=lambda k: abs(self._stuetzen[k][0] - s))
                self._auswaehlen(idx)
                self._ziehen = False
                self.update()
                return
            self._neu_durch_klick = idx
        self._auswaehlen(idx)
        self._ziehen = 0 < idx < len(self._stuetzen) - 1
        # Ausgangslage fuers Feinziehen mit Strg: Maushoehe und Punkthoehe
        self._zieh_start = (self._h_von_y(pos.y()), self._stuetzen[idx][1])
        self.update()
        self.stuetzpunktGewaehlt.emit(self._stuetzen[idx][0])

    def mouseMoveEvent(self, ev):
        if not (self._ziehen and self._gewaehlt is not None):
            return
        self._neu_durch_klick = None      # gezogen = gewollt, kein Doppelklick
        h = self._h_von_y(ev.position().y())
        if ev.modifiers() & Qt.ControlModifier:
            # Strg: die Maus bewegt den Punkt nur ein Zehntel so weit
            h_maus0, h_punkt0 = self._zieh_start
            h = h_punkt0 + (h - h_maus0) / 10.0
        self.hoehe_setzen(self._gewaehlt, self._auf_steigung_gerastet(self._gewaehlt, h))

    def mouseReleaseEvent(self, ev):
        self._ziehen = False

    def _auf_steigung_gerastet(self, idx, h, schritt=0.1):
        """Hoehe so anpassen, dass die Steigung des Abschnitts VOR dem Punkt
        auf ein Vielfaches von 'schritt' Prozent faellt. Ein Pixel Mausweg
        sind sonst 0.3 bis 0.5 %, und 7.0 ist nicht zu treffen."""
        s0, h0 = self._stuetzen[idx - 1][0], self._stuetzen[idx - 1][1]
        ds = self._stuetzen[idx][0] - s0
        if ds <= 0:
            return h
        g = round((h - h0) / ds * 100.0 / schritt) * schritt
        return h0 + g / 100.0 * ds

    def steigung_schritt(self, idx, delta_prozent):
        """Steigung des Abschnitts vor dem Punkt um delta_prozent aendern
        (Pfeiltasten)."""
        if idx is None or idx <= 0 or idx >= len(self._stuetzen) - 1:
            return
        s0, h0 = self._stuetzen[idx - 1][0], self._stuetzen[idx - 1][1]
        ds = self._stuetzen[idx][0] - s0
        if ds <= 0:
            return
        g = (self._stuetzen[idx][1] - h0) / ds * 100.0 + delta_prozent
        g = round(g / 0.01) * 0.01
        self.hoehe_setzen(idx, h0 + g / 100.0 * ds)

    def wheelEvent(self, ev):
        """Mausrad ueber einem inneren Stuetzpunkt: seine Ausrundung in
        5-m-Schritten, ohne den Weg ueber das Eingabefeld."""
        idx = self._treffer(ev.position())
        if idx is None or idx <= 0 or idx >= len(self._stuetzen) - 1:
            super().wheelEvent(ev)
            return
        schritt = 5.0 if ev.angleDelta().y() > 0 else -5.0
        self._auswaehlen(idx)
        self.ausrundung_setzen(idx, self._stuetzen[idx][2] + schritt)
        ev.accept()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._neu_durch_klick is not None:
            # Die erste Haelfte des Doppelklicks hat einen Punkt gesetzt -
            # weg damit, gemeint ist der Abschnitt darunter.
            self.entfernen(self._neu_durch_klick)
            self._neu_durch_klick = None
        elif self._treffer(ev.position()) is not None:
            return
        i = self._abschnitt_bei(ev.position().x())
        if i is None:
            return
        st = hoehenprofil.steigungen(self._stuetzen)
        wert, ok = QInputDialog.getDouble(
            self, "Grade of this section", "Grade in %:", st[i], -60.0, 60.0, 1)
        if ok and not self.steigung_setzen(i, wert):
            QMessageBox.information(self, "Grade", "B and E are fixed. Add a support point first.")

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._gewaehlt is not None:
            self.entfernen(self._gewaehlt)
        elif ev.key() in (Qt.Key_Up, Qt.Key_Down) and self._gewaehlt is not None:
            # Pfeil: 0.1 % am Abschnitt vor dem Punkt; Shift 1 %, Strg 0.01 %
            schritt = 0.1
            if ev.modifiers() & Qt.ShiftModifier:
                schritt = 1.0
            elif ev.modifiers() & Qt.ControlModifier:
                schritt = 0.01
            self.steigung_schritt(self._gewaehlt, schritt if ev.key() == Qt.Key_Up else -schritt)
        else:
            super().keyPressEvent(ev)

    # --------------------------------------------------------------- Malen
    def paintEvent(self, ev):
        f = theme.farben()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(f["eingabe"]))
        r = self._plot()
        lo, hi = self._h_bereich()
        S = self._strecke[-1]
        s_min, s_max = self._s_bereich()

        # Gitter und Achsen
        p.setPen(QPen(QColor(f["gitter"]), 1))
        p.setFont(QFont(self.font().family(), 8))
        schritt_h = _schoener_schritt((hi - lo) / 5)
        h = math_ceil(lo / schritt_h) * schritt_h
        while h <= hi:
            y = self._xy(0, h).y()
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(f["text_gedimmt"]))
            p.drawText(QRectF(0, y - 8, self.RAND_L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{h:.0f} m")
            p.setPen(QPen(QColor(f["gitter"]), 1))
            h += schritt_h
        schritt_s = _schoener_schritt((s_max - s_min) / 6) if s_max > s_min else 1
        s = math_ceil(s_min / schritt_s) * schritt_s
        while s <= s_max + 1e-6:
            x = self._xy(s, lo).x()
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(QColor(f["text_gedimmt"]))
            p.drawText(QRectF(x - 30, r.bottom() + 4, 60, 16), Qt.AlignCenter, f"{s:.0f} m")
            p.setPen(QPen(QColor(f["gitter"]), 1))
            s += schritt_s

        # Aufzeichnung vor B und nach E (grau, etwas kraeftiger) mit Steigung,
        # dazu die Grenzen B und E als senkrechte Linien
        p.setPen(QPen(QColor(f["text_gedimmt"]), 2.0))
        for teil, name in ((self._vor, "before B"), (self._nach, "after E")):
            if len(teil) < 2:
                continue
            punkte = [self._xy(s, h) for s, h in teil]
            for a, b in zip(punkte, punkte[1:]):
                p.drawLine(a, b)
            (s0, h0), (s1, h1) = teil[0], teil[-1]
            g = (h1 - h0) / (s1 - s0) * 100.0 if s1 > s0 else 0.0
            m = self._xy((s0 + s1) / 2, (h0 + h1) / 2)
            box = QRectF(m.x() - 46, m.y() + 8, 92, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(f["fenster"]))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor(f["text_gedimmt"]))
            p.setFont(QFont(self.font().family(), 9, QFont.Bold))
            p.drawText(box, Qt.AlignCenter, f"{name} {g:.1f} %")
            p.setFont(QFont(self.font().family(), 8))
            p.setPen(QPen(QColor(f["text_gedimmt"]), 2.0))
        p.setPen(QPen(QColor(f["gitter"]), 1, Qt.DotLine))
        for s_grenze in (0.0, S):
            x = self._xy(s_grenze, lo).x()
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

        # Aufgezeichnetes Profil (grau)
        p.setPen(QPen(QColor(f["text_gedimmt"]), 1.5))
        punkte = [self._xy(s, h) for s, h in zip(self._strecke, self._alt)]
        for a, b in zip(punkte, punkte[1:]):
            p.drawLine(a, b)

        # Neues Profil (Akzent)
        neu = self.hoehen()
        p.setPen(QPen(QColor(f["akzent"]), 2.2))
        punkte = [self._xy(s, h) for s, h in zip(self._strecke, neu)]
        for a, b in zip(punkte, punkte[1:]):
            p.drawLine(a, b)

        # Videoposition
        if self._video_s is not None:
            x = self._xy(self._video_s, lo).x()
            stift = QPen(QColor(f["verweis"]), 1.5, Qt.DashLine)
            p.setPen(stift)
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

        # Steigungen je Abschnitt
        st = hoehenprofil.steigungen(self._stuetzen)
        p.setFont(QFont(self.font().family(), 9, QFont.Bold))
        for i, g in enumerate(st):
            s0, h0 = self._stuetzen[i][0], self._stuetzen[i][1]
            s1, h1 = self._stuetzen[i + 1][0], self._stuetzen[i + 1][1]
            m = self._xy((s0 + s1) / 2, (h0 + h1) / 2)
            text = f"{g:.1f} %"
            if i == len(st) - 1 and len(st) > 1:
                text = f"rest {g:.1f} %"
            box = QRectF(m.x() - 40, m.y() - 26, 80, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(f["fenster"]))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor(f["text"]))
            p.drawText(box, Qt.AlignCenter, text)

        # Stuetzpunkte, innen mit ihrer Ausrundungslaenge darunter
        wirksam = hoehenprofil._ausrundungen(self._stuetzen, self._ausrundung)
        p.setFont(QFont(self.font().family(), 8))
        for i, p_ in enumerate(self._stuetzen):
            q = self._xy(p_[0], p_[1])
            fest = i == 0 or i == len(self._stuetzen) - 1
            p.setPen(QPen(QColor(f["text"]), 1.5))
            p.setBrush(QBrush(QColor(f["akzent"]) if i == self._gewaehlt else QColor(f["flaeche"])))
            if fest:
                p.drawRect(QRectF(q.x() - 5, q.y() - 5, 10, 10))
            else:
                p.drawEllipse(q, 6, 6)
                # gewuenschte Laenge; ist sie durch den Nachbarabschnitt
                # begrenzt, steht die wirksame in Klammern dahinter
                text = f"{p_[2]:.0f} m"
                if wirksam[i] < p_[2] - 0.5:
                    text += f" ({wirksam[i]:.0f})"
                p.setPen(QColor(f["text_gedimmt"]))
                p.drawText(QRectF(q.x() - 40, q.y() + 8, 80, 14), Qt.AlignCenter, text)
        p.end()


def math_ceil(x):
    import math
    return math.ceil(x)


def _schoener_schritt(roh):
    """1, 2, 5 * 10^n, nahe an 'roh'."""
    import math
    if roh <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(roh))
    for m in (1, 2, 5, 10):
        if m * e >= roh:
            return m * e
    return 10 * e


class HoehenprofilEditor(QDialog):
    """Das Fenster um die Flaeche. Nicht blockierend (show(), nicht exec()).

    uebernehmen(hoehen): die neuen Hoehen fuer die Punkte b..e, wenn der
    Nutzer 'Apply' drueckt. aktuelle_zeile() liefert die GPX-Zeile der
    Videoposition oder None; springen(zeile) faehrt das Video dorthin.
    """

    uebernehmen = Signal(list)

    def __init__(self, gpx_data, b_idx, e_idx, parent=None,
                 aktuelle_zeile=None, springen=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle(f"Height profile editor - rows {b_idx}..{e_idx}")
        self._b, self._e = b_idx, e_idx
        self._aktuelle_zeile = aktuelle_zeile
        self._springen = springen
        self._strecke = hoehenprofil.strecke_2d(gpx_data, b_idx, e_idx)
        alt = [float(gpx_data[i].get("ele", 0.0)) for i in range(b_idx, e_idx + 1)]
        # Ein Stueck Aufzeichnung vor B und nach E, damit man sieht, mit
        # welcher Steigung es hinein- und herausgeht.
        k = 15
        vor, nach = [], []
        a = max(0, b_idx - k)
        if a < b_idx:
            s_vor = hoehenprofil.strecke_2d(gpx_data, a, b_idx)
            vor = [(s - s_vor[-1], float(gpx_data[a + i].get("ele", 0.0)))
                   for i, s in enumerate(s_vor)]
        z = min(len(gpx_data) - 1, e_idx + k)
        if z > e_idx:
            s_nach = hoehenprofil.strecke_2d(gpx_data, e_idx, z)
            nach = [(self._strecke[-1] + s, float(gpx_data[e_idx + i].get("ele", 0.0)))
                    for i, s in enumerate(s_nach)]

        aussen = QVBoxLayout(self)
        hinweis = QLabel(
            "Click on the line to add a support point, drag it up or down, "
            "right-click removes it. Double-click a section to type its grade. "
            "Mouse wheel over a point: its rounding length, short for a fast "
            "change of grade, long for a slow one. "
            "Dragging snaps the grade before the point to 0.1 %; hold Ctrl "
            "to drag ten times finer; arrow keys change it by 0.1 % (Shift 1 %, "
            "Ctrl 0.01 %). B and E are fixed; the grey line is the recording.", self)
        hinweis.setWordWrap(True)
        aussen.addWidget(hinweis)

        self._flaeche = ProfilFlaeche(self._strecke, alt, alt[0], alt[-1], self,
                                      vor=vor, nach=nach)
        aussen.addWidget(self._flaeche, 1)

        zeile = QHBoxLayout()
        self._lb_ausrundung = QLabel("Rounding for new points:", self)
        zeile.addWidget(self._lb_ausrundung)
        self._sb_ausrundung = QDoubleSpinBox(self)
        self._sb_ausrundung.setRange(0.0, 500.0)
        self._sb_ausrundung.setDecimals(0)
        self._sb_ausrundung.setSingleStep(5.0)
        self._sb_ausrundung.setSuffix(" m")
        self._sb_ausrundung.setValue(self._flaeche.ausrundung())
        self._sb_ausrundung.setToolTip(
            "Length of the vertical curve that replaces the kink at a support "
            "point - long for a slow change of grade, short for a fast one. "
            "With a point selected this is its own length; the mouse wheel over "
            "a point does the same in 5 m steps. Limited to the shorter "
            "neighbouring section.")
        self._sb_ausrundung.valueChanged.connect(self._ausrundung_eingegeben)
        zeile.addWidget(self._sb_ausrundung)
        alle = QPushButton("Apply to all points", self)
        alle.setToolTip("Give every support point this rounding length")
        alle.clicked.connect(lambda: self._flaeche.ausrundung_alle(self._sb_ausrundung.value()))
        zeile.addWidget(alle)
        zeile.addStretch(1)
        self._knopf_video = QPushButton("Add point at video position", self)
        self._knopf_video.setEnabled(False)
        self._knopf_video.clicked.connect(self._punkt_bei_video)
        zeile.addWidget(self._knopf_video)
        aussen.addLayout(zeile)

        self._info = QLabel(self)
        self._info.setWordWrap(True)
        aussen.addWidget(self._info)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        self._knopf_apply = QPushButton("Apply", self)
        self._knopf_apply.clicked.connect(self._apply)
        knoepfe.addWidget(self._knopf_apply)
        abbruch = QPushButton("Cancel", self)
        abbruch.clicked.connect(self.reject)
        knoepfe.addWidget(abbruch)
        aussen.addLayout(knoepfe)

        self._flaeche.geaendert.connect(self._info_aktualisieren)
        self._flaeche.geaendert.connect(self._spinbox_nachziehen)
        self._flaeche.stuetzpunktGewaehlt.connect(self._zum_video)
        self._flaeche.auswahlGeaendert.connect(self._spinbox_nachziehen)
        self._info_aktualisieren()

        self._video_zeile = None
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._video_nachziehen)
        if aktuelle_zeile is not None:
            self._timer.start()
        self.resize(900, 560)

    # -------------------------------------------------------------- Video
    def _video_nachziehen(self):
        try:
            zeile = self._aktuelle_zeile()
        except Exception:
            zeile = None
        if zeile is not None and self._b <= zeile <= self._e:
            self._video_zeile = zeile
            self._flaeche.set_video_s(self._strecke[zeile - self._b])
            self._knopf_video.setEnabled(True)
        else:
            self._video_zeile = None
            self._flaeche.set_video_s(None)
            self._knopf_video.setEnabled(False)

    def _punkt_bei_video(self):
        if self._video_zeile is None:
            return
        self._flaeche.stuetzpunkt_hinzufuegen(self._strecke[self._video_zeile - self._b])

    def _zum_video(self, s):
        if self._springen is None:
            return
        # naechster Punkt der Spur zu s
        i = min(range(len(self._strecke)), key=lambda k: abs(self._strecke[k] - s))
        try:
            self._springen(self._b + i)
        except Exception as exc:
            print(f"[PROFIL] Sprung ins Video fehlgeschlagen: {exc}")

    # ---------------------------------------------------------- Ausrundung
    def _innerer_gewaehlt(self):
        idx = self._flaeche.gewaehlt()
        if idx is None or idx <= 0 or idx >= len(self._flaeche.stuetzen()) - 1:
            return None
        return idx

    def _spinbox_nachziehen(self, *_):
        """Das Eingabefeld zeigt die Ausrundung des gewaehlten Punkts, ohne
        Auswahl die Vorgabe fuer neue Punkte."""
        idx = self._innerer_gewaehlt()
        self._sb_ausrundung.blockSignals(True)
        if idx is None:
            self._lb_ausrundung.setText("Rounding for new points:")
            self._sb_ausrundung.setValue(self._flaeche.ausrundung())
        else:
            self._lb_ausrundung.setText(f"Rounding at point {idx}:")
            self._sb_ausrundung.setValue(self._flaeche.stuetzen()[idx][2])
        self._sb_ausrundung.blockSignals(False)

    def _ausrundung_eingegeben(self, meter):
        idx = self._innerer_gewaehlt()
        if idx is None:
            self._flaeche.set_ausrundung(meter)
        else:
            self._flaeche.ausrundung_setzen(idx, meter)

    # --------------------------------------------------------------- Info
    def _info_aktualisieren(self):
        st = hoehenprofil.steigungen(self._flaeche.stuetzen())
        stuetzen = self._flaeche.stuetzen()
        teile = []
        for i, g in enumerate(st):
            laenge = stuetzen[i + 1][0] - stuetzen[i][0]
            teile.append(f"{g:.1f} % over {laenge:.0f} m")
            if i + 1 < len(st):
                teile[-1] += f", rounding {stuetzen[i + 1][2]:.0f} m"
        gesamt = stuetzen[-1][1] - stuetzen[0][1]
        text = f"B to E: {gesamt:+.1f} m over {stuetzen[-1][0]:.0f} m.  Sections: " + ", ".join(teile)
        if len(st) > 1:
            text += f".  Rest to E: {st[-1]:.1f} % over {stuetzen[-1][0] - stuetzen[-2][0]:.0f} m"
        rand = []
        for teil, name in ((self._flaeche._vor, "before B"), (self._flaeche._nach, "after E")):
            if len(teil) >= 2:
                (s0, h0), (s1, h1) = teil[0], teil[-1]
                rand.append(f"{name} {(h1 - h0) / (s1 - s0) * 100.0:.1f} % over {s1 - s0:.0f} m")
        if rand:
            text += ".  Recording: " + ", ".join(rand)
        self._info.setText(text)

    # -------------------------------------------------------------- Apply
    def _apply(self):
        self.uebernehmen.emit(self._flaeche.hoehen())
        self.accept()

    def closeEvent(self, ev):
        self._timer.stop()
        super().closeEvent(ev)
