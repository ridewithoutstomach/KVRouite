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

# views/anhoeren_dialog.py
"""
Das Abhoerfenster (ab 7.0): eine fertig gerenderte Datei abspielen, nur den
Ton, mit Play, Pause, Stop und einer Zeitanzeige.

Gebraucht fuer "Listen …" im Menue eines Bandes (mainwindow._stelle_anhoeren):
der Ausschnitt 10 s vor bis 10 s nach einer Stelle wird so gerendert, wie
der Export es taete, und hier angehoert - erst danach laesst sich sagen, ob
die Stelle sitzt und die Fuellung taugt (Bernd, 10.09.2026 nacht: "ich kann
es hoeren, du kannst nur messen").

Abgespielt wird ueber playbin mit fakesink fuers Bild; die Datei ist klein
(320 Pixel breit), es geht nur um den Ton. Beim Schliessen wird die
Pipeline abgebaut.
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QDialogButtonBox
)


class AnhoerenDialog(QDialog):
    def __init__(self, pfad, titel, stelle=None, parent=None):
        """pfad: die gerenderte Datei. stelle: (von, bis) der Stelle in
        Sekunden DER DATEI, wird in der Zeitanzeige markiert."""
        super().__init__(parent)
        self.setWindowTitle("Listen - " + titel)
        self._pfad = pfad
        self._stelle = stelle
        self._dauer_ns = 0
        self._play = None
        self._sucht = False

        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst, GLib
        self._Gst = Gst
        if not Gst.is_initialized():
            Gst.init(None)
        self._play = Gst.ElementFactory.make("playbin", None)
        if self._play is None:
            raise RuntimeError("playbin is not available")
        self._play.set_property("uri", GLib.filename_to_uri(os.path.abspath(pfad), None))
        # Nur der Ton (flags=AUDIO): das Bild wird gar nicht dekodiert. Ein
        # fakesink fuers Bild liefe ohne Uhr durch und meldete sofort das
        # Ende - die Position stand dann bei der Gesamtlaenge.
        self._play.set_property("flags", 0x02)

        aussen = QVBoxLayout(self)
        self.lage = QLabel(titel, self)
        aussen.addWidget(self.lage)
        hinweis = QLabel("30 s before the stretch, the stretch as it will be "
                         "exported, 30 s after. \"Jump to stretch\" starts 3 s "
                         "before it.", self)
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet("color: gray;")
        aussen.addWidget(hinweis)

        self.schieber = QSlider(Qt.Horizontal, self)
        self.schieber.setRange(0, 1000)
        self.schieber.sliderPressed.connect(self._suche_an)
        self.schieber.sliderReleased.connect(self._suche_aus)
        aussen.addWidget(self.schieber)

        zeile = QHBoxLayout()
        self.zeit = QLabel("0:00.0 / 0:00.0", self)
        zeile.addWidget(self.zeit)
        zeile.addStretch(1)
        self.btn_play = QPushButton("Play", self)
        self.btn_play.clicked.connect(self._play_pause)
        zeile.addWidget(self.btn_play)
        self.btn_stop = QPushButton("Stop", self)
        self.btn_stop.clicked.connect(self._stop)
        zeile.addWidget(self.btn_stop)
        self.btn_stelle = QPushButton("Jump to stretch", self)
        self.btn_stelle.setEnabled(stelle is not None)
        self.btn_stelle.clicked.connect(self._zur_stelle)
        zeile.addWidget(self.btn_stelle)
        aussen.addLayout(zeile)

        knoepfe = QDialogButtonBox(QDialogButtonBox.Close, self)
        knoepfe.rejected.connect(self.reject)
        knoepfe.accepted.connect(self.accept)
        aussen.addWidget(knoepfe)

        self._takt = QTimer(self)
        self._takt.setInterval(100)
        self._takt.timeout.connect(self._nachziehen)
        self._takt.start()
        self.resize(520, 180)
        self._play.set_state(Gst.State.PLAYING)
        self.btn_play.setText("Pause")

    # ---- Steuerung
    def _play_pause(self):
        Gst = self._Gst
        _ok, zustand, _p = self._play.get_state(0)
        if zustand == Gst.State.PLAYING:
            self._play.set_state(Gst.State.PAUSED)
            self.btn_play.setText("Play")
        else:
            self._play.set_state(Gst.State.PLAYING)
            self.btn_play.setText("Pause")

    def _stop(self):
        Gst = self._Gst
        self._play.set_state(Gst.State.PAUSED)
        self._springen(0)
        self.btn_play.setText("Play")

    def _zur_stelle(self):
        if self._stelle is None:
            return
        Gst = self._Gst
        self._springen(int(max(0.0, self._stelle[0] - 3.0) * Gst.SECOND))
        self._play.set_state(Gst.State.PLAYING)
        self.btn_play.setText("Pause")

    def _springen(self, ns):
        Gst = self._Gst
        self._play.seek_simple(Gst.Format.TIME,
                               Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, ns)

    def _suche_an(self):
        self._sucht = True

    def _suche_aus(self):
        self._sucht = False
        if self._dauer_ns > 0:
            self._springen(int(self.schieber.value() / 1000.0 * self._dauer_ns))

    # ---- Anzeige
    def _nachziehen(self):
        Gst = self._Gst
        if self._play is None:
            return
        # Ende erreicht? Dann von vorn anbieten.
        msg = self._play.get_bus().pop_filtered(Gst.MessageType.EOS | Gst.MessageType.ERROR)
        if msg is not None:
            self._play.set_state(Gst.State.PAUSED)
            self._springen(0)
            self.btn_play.setText("Play")
        if self._dauer_ns <= 0:
            ok, dauer = self._play.query_duration(Gst.Format.TIME)
            if ok:
                self._dauer_ns = dauer
        ok, pos = self._play.query_position(Gst.Format.TIME)
        if not ok:
            return
        if self._dauer_ns > 0 and not self._sucht:
            self.schieber.blockSignals(True)
            self.schieber.setValue(int(pos * 1000 / self._dauer_ns))
            self.schieber.blockSignals(False)
        text = "%s / %s" % (_kurz(pos / Gst.SECOND), _kurz(self._dauer_ns / Gst.SECOND))
        if self._stelle is not None:
            a, b = self._stelle
            drin = a <= pos / Gst.SECOND <= b
            text += "   " + ("<< inside the stretch >>" if drin else
                             "stretch %s - %s" % (_kurz(a), _kurz(b)))
        self.zeit.setText(text)

    def closeEvent(self, event):
        self._abbauen()
        super().closeEvent(event)

    def done(self, code):
        self._abbauen()
        super().done(code)

    def _abbauen(self):
        self._takt.stop()
        if self._play is not None:
            self._play.set_state(self._Gst.State.NULL)
            self._play = None


def _kurz(sekunden):
    sekunden = max(0.0, float(sekunden))
    m = int(sekunden // 60)
    return "%d:%04.1f" % (m, sekunden - m * 60)
