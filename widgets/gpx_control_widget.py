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

# gpx_control_widget.py 
## aufgeräumt

import copy
import math
import urllib.request
import urllib.error
import json
import sys, os

from pathlib import Path


from PySide6.QtCore import Qt, Signal, QPoint, QUrl, QEvent, QRectF, QPointF
from PySide6.QtGui import QIcon, QPixmap, QCursor, QDesktopServices, QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QStyle, QVBoxLayout, QLabel, QSizePolicy, QFrame, QMenu, QDialog, QRadioButton, QButtonGroup, QDoubleSpinBox, QMessageBox, QFileDialog, QLineEdit
import os


from PySide6.QtGui import QIcon

from datetime import timedelta
from core.gpx_parser import recalc_gpx_data, get_gpx_video_shift, set_gpx_video_shift, is_gpx_video_shift_set
from core import theme
from core import naht_glaetten
import config

MAX_LOGO_H = 48


class LeistenGriff(QWidget):
    """Anfasser links an der schwebenden GPX-Leiste.

    Nur der Griff nimmt die Maus zum Ziehen an; die Knoepfe daneben bleiben
    Knoepfe. Gezogen wird die Leiste (der Elternteil) innerhalb ihres
    eigenen Elternteils, dem zentralen Fenster. Punktraster wie beim Griff
    des Chart Flow im Videobild - das Zeichen fuer "hier anfassen".
    """

    BREITE = 14

    def __init__(self, leiste, bewegt=None, losgelassen=None):
        super().__init__(leiste)
        self._leiste = leiste
        self._bewegt = bewegt
        self._losgelassen = losgelassen
        self._start_maus = None
        self._start_pos = None
        self.setFixedWidth(self.BREITE)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("Move the GPX bar")

    def paintEvent(self, _ev):
        f = theme.farben()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(f["kopfzeile"]))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 3, 3)
        p.setBrush(QColor(f["text_gedimmt"]))
        mx, my = self.width() // 2, self.height() // 2
        for dx in (-3, 3):
            for dy in (-8, -4, 0, 4, 8):
                p.drawEllipse(mx + dx - 1, my + dy - 1, 3, 3)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_maus = event.globalPosition().toPoint()
            self._start_pos = self._leiste.pos()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._start_maus is None:
            event.ignore()
            return
        delta = event.globalPosition().toPoint() - self._start_maus
        self._leiste.move(self._start_pos + delta)
        if self._bewegt:
            self._bewegt()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._start_maus is not None:
            self._start_maus = None
            if self._losgelassen:
                self._losgelassen()
            event.accept()
        else:
            event.ignore()

    def contextMenuEvent(self, event):
        # Kein Menue am Griff - sonst kaeme das des Slots darunter.
        event.accept()


class NahtDiagramm(QWidget):
    """Tempo je Punkt im Bereich um die Naht: vorher grau, nachher farbig.

    Die Tabelle im Dialog zeigt Mittelwerte ueber 60 Punkte, und ein
    Mittelwert kann taeuschen: "60..1 before 19.3 km/h" neben einer Naht
    mit 15 km/h sah am 08.09.2026 nach zu langsam aus, obwohl die Punkte
    direkt neben der Naht selbst 15 km/h fahren. Das Diagramm zeigt jeden
    Punkt, die Naht steht als gestrichelte Linie in der Mitte. Die Spitze
    der Naht (200 km/h und mehr) wird abgeschnitten, sonst waere der Rest
    ein Strich am Boden; ihr Wert steht als Text an der Linie.
    """

    HOEHE = 170

    def __init__(self, parent=None):
        super().__init__(parent)
        self._punkte = []      # (abstand, v_alt, v_neu)
        self._v = None
        self.setMinimumHeight(self.HOEHE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setzen(self, punkte, vorschlag):
        self._punkte = list(punkte or [])
        self._v = vorschlag
        self.update()

    def paintEvent(self, _ev):
        f = theme.farben()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(f["eingabe"]))
        if not self._punkte or self._v is None:
            p.setPen(QColor(f["text_gedimmt"]))
            p.drawText(self.rect(), Qt.AlignCenter, "no proposal")
            return

        links, rechts, oben, unten = 66, 12, 14, 24
        r = QRectF(links, oben, max(1, self.width() - links - rechts),
                   max(1, self.height() - oben - unten))

        # Skala aus allen Punkten ausser der Naht selbst (die Spitze wird
        # abgeschnitten); etwas Luft nach oben, mindestens 10 km/h.
        werte = [w for a, v_alt, v_neu in self._punkte if a != 0 for w in (v_alt, v_neu)]
        v_max = max(10.0, max(werte) * 1.15) if werte else 10.0
        a_min = min(a for a, _x, _y in self._punkte)
        a_max = max(a for a, _x, _y in self._punkte)
        spanne = max(1, a_max - a_min)

        def x_von(a):
            return r.left() + (a - a_min) / spanne * r.width()

        def y_von(v):
            return r.bottom() - min(v, v_max) / v_max * r.height()

        # Gitter und Achsen
        gitter = QPen(QColor(f["gitter"]))
        p.setPen(gitter)
        schrift = QColor(f["text_gedimmt"])
        for stufe in (0.0, 0.5, 1.0):
            y = r.bottom() - stufe * r.height()
            p.setPen(gitter)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(schrift)
            # Die Einheit steht am obersten Wert, nicht als eigenes Wort:
            # das ueberlappte sonst die Zahl.
            p.drawText(QRectF(0, y - 8, links - 6, 16), Qt.AlignRight | Qt.AlignVCenter,
                       ("%.0f km/h" if stufe == 1.0 else "%.0f") % (stufe * v_max))
        p.setPen(schrift)
        p.drawText(QRectF(r.left(), r.bottom() + 4, 60, 16), Qt.AlignLeft, "%d" % a_min)
        p.drawText(QRectF(r.right() - 60, r.bottom() + 4, 60, 16), Qt.AlignRight, "+%d" % a_max)
        p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 16), Qt.AlignHCenter,
                   "points from the seam")

        # Naht: gestrichelte Linie
        x_naht = x_von(0)
        naht = QPen(QColor(f["text_gedimmt"]))
        naht.setStyle(Qt.DashLine)
        p.setPen(naht)
        p.drawLine(QPointF(x_naht, r.top()), QPointF(x_naht, r.bottom()))

        # Verlaeufe: vorher grau, nachher Akzent. Die Naht wird auf v_max
        # gekappt (min() in y_von), damit die Linie am Rand endet.
        def linie(farbe, spalte, breite):
            stift = QPen(QColor(farbe))
            stift.setWidthF(breite)
            p.setPen(stift)
            letzter = None
            for punkt in self._punkte:
                jetzt = QPointF(x_von(punkt[0]), y_von(punkt[spalte]))
                if letzter is not None:
                    p.drawLine(letzter, jetzt)
                letzter = jetzt

        linie(f["text_gedimmt"], 1, 1.2)
        linie(f["akzent"], 2, 1.8)

        # Beschriftung der Naht und Legende
        v_alt = next((v for a, v, _n in self._punkte if a == 0), 0.0)
        v_neu = next((n for a, _v, n in self._punkte if a == 0), 0.0)
        p.setPen(QColor(f["text"]))
        text = "seam: %.0f -> %.1f km/h" % (v_alt, v_neu)
        breite_text = p.fontMetrics().horizontalAdvance(text) + 8
        # Rechts der Naht, wenn Platz ist, sonst links.
        if x_naht + 6 + breite_text < r.right():
            feld = QRectF(x_naht + 6, r.top(), breite_text, 16)
            p.drawText(feld, Qt.AlignLeft | Qt.AlignVCenter, text)
        else:
            feld = QRectF(x_naht - 6 - breite_text, r.top(), breite_text, 16)
            p.drawText(feld, Qt.AlignRight | Qt.AlignVCenter, text)
        p.setPen(QColor(f["text_gedimmt"]))
        p.drawText(QRectF(r.right() - 150, r.top(), 150, 16), Qt.AlignRight | Qt.AlignVCenter,
                   "grey: before")
        p.setPen(QColor(f["akzent"]))
        p.drawText(QRectF(r.right() - 150, r.top() + 16, 150, 16), Qt.AlignRight | Qt.AlignVCenter,
                   "coloured: after")
        p.end()


class NahtDialog(QDialog):
    """Diagnose, Vorschlag und Vorher/Nachher fuer 'Fix speed spike'.

    Eigenstaendig, damit er sich ohne MainWindow oeffnen laesst - so wurde
    er am 06.09.2026 mit den Stelvio-Daten ohne Oberflaeche geprueft. Die
    Bereichsgroessen lassen sich verstellen; jede Aenderung rechnet den
    Vorschlag und die Tabelle neu. `vorschlag` ist nach Accept der Stand,
    der uebernommen werden soll.
    """

    def __init__(self, gpx_data, vorschlag, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import (QSpinBox, QTableWidget, QTableWidgetItem,
                                       QDialogButtonBox, QFormLayout, QHeaderView)
        self._g = gpx_data
        self.vorschlag = vorschlag
        self._QTableWidgetItem = QTableWidgetItem

        self.setWindowTitle("Fix speed spike")
        aussen = QVBoxLayout(self)

        self._diagnose = QLabel(self)
        self._diagnose.setWordWrap(True)
        aussen.addWidget(self._diagnose)

        self._vorschlag_text = QLabel(self)
        self._vorschlag_text.setWordWrap(True)
        aussen.addWidget(self._vorschlag_text)

        form = QFormLayout()
        self._sb_davor = QSpinBox(self)
        self._sb_davor.setRange(1, max(1, vorschlag.max_davor))
        self._sb_davor.setValue(vorschlag.davor)
        self._sb_davor.setSuffix(" points")
        self._sb_danach = QSpinBox(self)
        self._sb_danach.setRange(1, max(1, vorschlag.max_danach))
        self._sb_danach.setValue(vorschlag.danach)
        self._sb_danach.setSuffix(" points")
        self._halt_davor = QLabel(self)
        self._halt_danach = QLabel(self)
        zeile1 = QHBoxLayout()
        zeile1.addWidget(self._sb_davor)
        zeile1.addWidget(self._halt_davor)
        zeile2 = QHBoxLayout()
        zeile2.addWidget(self._sb_danach)
        zeile2.addWidget(self._halt_danach)
        form.addRow("Range before the seam", zeile1)
        form.addRow("Range after the seam", zeile2)
        aussen.addLayout(form)

        self._tabelle = QTableWidget(0, 4, self)
        self._tabelle.setHorizontalHeaderLabels(
            ["Points", "Gradient", "Speed before", "Speed after"])
        self._tabelle.verticalHeader().setVisible(False)
        self._tabelle.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tabelle.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        aussen.addWidget(self._tabelle)

        # Jeder Punkt des Bereichs als Linie - siehe NahtDiagramm.
        self._diagramm = NahtDiagramm(self)
        aussen.addWidget(self._diagramm)

        fest = QLabel("Positions, elevations and gradients are not touched. "
                      "Points after the range keep their times, the video "
                      "stays in sync.\n\n"
                      "Like chT, this changes point times: video cuts can no "
                      "longer be undone afterwards. Set all cuts first, then "
                      "fix the seams. GPX undo is available.", self)
        fest.setWordWrap(True)
        aussen.addWidget(fest)

        self._fehler = QLabel(self)
        self._fehler.setWordWrap(True)
        self._fehler.setStyleSheet("color: #c00;")
        aussen.addWidget(self._fehler)

        self._knoepfe = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        self._knoepfe.button(QDialogButtonBox.Ok).setText("Apply")
        self._knoepfe.accepted.connect(self.accept)
        self._knoepfe.rejected.connect(self.reject)
        aussen.addWidget(self._knoepfe)

        self._sb_davor.valueChanged.connect(self._neu_rechnen)
        self._sb_danach.valueChanged.connect(self._neu_rechnen)
        self._anzeigen(automatisch=True)
        self.resize(640, 720)

    def _neu_rechnen(self):
        try:
            self.vorschlag = naht_glaetten.vorschlagen(
                self._g, self.vorschlag.idx,
                davor=self._sb_davor.value(), danach=self._sb_danach.value())
        except naht_glaetten.NahtFehler as exc:
            self.vorschlag = None
            self._fehler.setText(str(exc))
            self._knoepfe.button(self._knoepfe.StandardButton.Ok).setEnabled(False)
            self._tabelle.setRowCount(0)
            self._diagramm.setzen([], None)
            return
        self._anzeigen(automatisch=False)

    def _anzeigen(self, automatisch):
        v = self.vorschlag
        g = self._g
        self._fehler.setText("")
        self._knoepfe.button(self._knoepfe.StandardButton.Ok).setEnabled(True)

        self._diagnose.setText(
            "<b>Row %d:</b> %.1f m in %.3f s = %.0f km/h. The surroundings "
            "run %.1f km/h (median of %d points each side). About %.1f s of "
            "riding are missing here - typically a cut seam after a camera "
            "failure."
            % (v.idx + 1, v.dm, v.dt_alt, v.v_spitze, v.v_umfeld,
               naht_glaetten.UMFELD, v.naht_s - v.dt_alt))
        self._vorschlag_text.setText(
            "<b>Proposal:</b> give the seam %.1f s and take that time back "
            "from the %d points before and %d after by dividing every step "
            "there by %.3f (a 1.000 s step becomes %.3f s). Everything in the "
            "range runs %.0f %% faster, in its real proportions - the flatter "
            "part stays the faster one, and a short step stays short."
            % (v.naht_s, v.davor, v.danach, v.faktor, v.schritt,
               (v.faktor - 1.0) * 100.0))
        praefix = "auto: " if automatisch else ""
        self._halt_davor.setText(praefix + v.halt_davor)
        self._halt_danach.setText(praefix + v.halt_danach)

        neu = naht_glaetten.vorschau(g, v)
        self._diagramm.setzen(naht_glaetten.verlauf(g, neu, v), v)
        zeilen = naht_glaetten.zeilen(g, neu, v)
        self._tabelle.setRowCount(len(zeilen))
        for r, (bez, steig, v_alt, v_neu) in enumerate(zeilen):
            werte = [bez,
                     "" if bez == "max in range" else "%.1f %%" % steig,
                     "%.1f km/h" % v_alt, "%.1f km/h" % v_neu]
            for c, text in enumerate(werte):
                item = self._QTableWidgetItem(text)
                if c > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._tabelle.setItem(r, c, item)


class GPXControlWidget(QWidget):
    """
    Enthält die Buttons (MarkB, MarkE, x, Delete, chTime, chEle, ch%, Undo, Smooth, Save)
    UND eine Info-Zeile darunter, in der wir vier Labels anzeigen:
    - Video: ...
    - Length(GPX): ...
    - Duration(GPX): ...
    - Elevation Gain: ...
    """

    # Signale
    markBClicked = Signal()
    markEClicked = Signal()
    deselectClicked = Signal()  # "x"
    cutClicked = Signal()
    removeClicked = Signal()
    chTimeClicked = Signal()
    chEleClicked = Signal()
    chPercentClicked = Signal()
    #undoClicked = Signal()
    smoothClicked = Signal()
    #saveClicked = Signal()
    showMaxSlopeClicked = Signal()
    showMinSlopeClicked = Signal()
    averageSpeedClicked = Signal()
    maxSpeedClicked = Signal()
    minSpeedClicked = Signal()
    closeGapsClicked = Signal()
    deleteWayErrorsClicked = Signal()
    deleteTimeErrorsClicked = Signal()


    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._mainwindow = None
        
        


        # SORGT DAFÜR, DASS DAS WIDGET NICHT ENDLOS IN DIE HÖHE WÄCHST
        self.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        )

        # Oberstes (vertikales) Layout, darin: Buttons-Zeile + Info-Zeile
        # Oberstes Layout: HBox -> links die zwei Zeilen (Buttons+Info), rechts das Kinomap-Logo
        self._main_hbox = QHBoxLayout(self)
        self._main_hbox.setContentsMargins(5, 5, 20, 5)
        self._main_hbox.setSpacing(8)

        self.main_vbox = QVBoxLayout()      # bleibt dein bestehendes "zentral-Layout"
        self.main_vbox.setContentsMargins(0, 0, 0, 0)
        self.main_vbox.setSpacing(5)

        # linke Seite (Buttons + Info) in die HBox
        self._main_hbox.addLayout(self.main_vbox, 1)

        
        # ---------------------------------------------
        # (A) Erste Zeile: Buttons
        # ---------------------------------------------
        self._buttons_layout = QHBoxLayout()
        self._buttons_layout.setSpacing(5)
        self.main_vbox.addLayout(self._buttons_layout)

        # 1) MarkB
        self.markB_button = QPushButton("[-", self)
        self.markB_button.setToolTip("Mark the Begin of the Cut in the GPX\n"
                                     "Right-click: mark the point before the last cut")

        self.markB_button.setMaximumWidth(40)
        self.markB_button.clicked.connect(self.markBClicked.emit)
        # Rechtsklick markiert die Luecke des letzten Schnitts (Punkt davor
        # bzw. danach) - fuer eine zweite Aktion ueber die Luecke.
        self.markB_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.markB_button.customContextMenuRequested.connect(
            lambda _pos: self._on_markB_restore())
        self._buttons_layout.addWidget(self.markB_button)

        self._default_markB_style = self.markB_button.styleSheet() or ""

        # 2) MarkE
        self.markE_button = QPushButton("-]", self)
        self.markE_button.setToolTip("Mark the End of the Cut in the GPX\n"
                                     "Right-click: mark the point after the last cut")

        self.markE_button.setMaximumWidth(40)
        self.markE_button.clicked.connect(self.markEClicked.emit)
        self.markE_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.markE_button.customContextMenuRequested.connect(
            lambda _pos: self._on_markE_restore())
        self._buttons_layout.addWidget(self.markE_button)
        
        self._default_markE_style = self.markE_button.styleSheet() or ""

        # 3) x => "deselect"
        self.deselect_button = QPushButton("x", self)
        self.deselect_button.setToolTip("Deselect the marked Area")
        
        self.deselect_button.setMaximumWidth(40)
        self.deselect_button.clicked.connect(self.deselectClicked.emit)
        self._buttons_layout.addWidget(self.deselect_button)

        # 4) Delete
        # U+FE0E haengt hinten dran: das ist die Bitte um die TEXT-Darstellung.
        # Ohne sie zeichnet Windows die Schere als farbiges Emoji, das die
        # Textfarbe nicht annimmt - auf dunklem Grund blieb sie rot.
        self.cut_button = QPushButton("✂︎", self)
        self.cut_button.setToolTip("Cut a marked Area and shift next points time")
        self.cut_button.setMinimumWidth(20)
        
        self.cut_button.clicked.connect(self.cutClicked.emit)
        self._buttons_layout.addWidget(self.cut_button)
        
        # Geviertstrich statt U+2796: das dortige Zeichen ist ein Emoji und
        # bleibt auch mit U+FE0E blau - gemessen. Der Strich nimmt die
        # Textfarbe an und ist aehnlich kraeftig.
        self.minus_button = QPushButton("—", self)
        self.minus_button.setToolTip("Remove a marked Area without time shift")
        self.minus_button.setMinimumWidth(20)
        
        self.minus_button.clicked.connect(self.removeClicked.emit)
        self._buttons_layout.addWidget(self.minus_button)
        

        # 5) chTime
        self.chTime_button = QPushButton("chT", self)
        self.chTime_button.setToolTip("Change the Step (time) of a point")
        self.chTime_button.setMaximumWidth(50)
        self.chTime_button.clicked.connect(self.chTimeClicked.emit)
        self._buttons_layout.addWidget(self.chTime_button)

        # 6) chEle
        self.chEle_button = QPushButton("chEle", self)
        self.chEle_button.setToolTip("Change the height of a single point or move a complete height of a marked area")
        self.chEle_button.setMaximumWidth(50)
        self.chEle_button.clicked.connect(self.chEleClicked.emit)
        self._buttons_layout.addWidget(self.chEle_button)

        # 7) ch%
        #self.chPercent_button = QPushButton("%↗",self)
        self.chPercent_button = QPushButton("ch%",self)
        self.chPercent_button.setToolTip("Change the slope of a point/range of points")
        self.chPercent_button.setMaximumWidth(50)
        self.chPercent_button.clicked.connect(self.chPercentClicked.emit)
        self._buttons_layout.addWidget(self.chPercent_button)
            
        self.more_button = QPushButton("...", self)
        self.more_button.setToolTip("More...")
        self.more_button.setMaximumWidth(50)  
        self._buttons_layout.addWidget(self.more_button)

        # (Menü anlegen)
        self.more_menu = QMenu(self.more_button)
        
        
        
        action_avgspeed = self.more_menu.addAction("Set AverageSpeed")
        action_avgspeed.triggered.connect(self.averageSpeedClicked.emit)

        action_fix_spike = self.more_menu.addAction("Fix speed spike (cut seam)")
        action_fix_spike.triggered.connect(self.on_fix_spike_clicked)

        self._action_closegaps = self.more_menu.addAction("Close Gaps")
        self._action_closegaps.triggered.connect(self.closeGapsClicked.emit)
        
        action_del_way_errors = self.more_menu.addAction("Delete Way Errors")
        action_del_way_errors.triggered.connect(self.deleteWayErrorsClicked.emit)
        
        
        action_delete_time_errors = self.more_menu.addAction("Delete Time Errors")
        action_delete_time_errors.triggered.connect(self.deleteTimeErrorsClicked.emit)
        
        action_cut_before_b = self.more_menu.addAction("Cut all before markB")
        action_cut_before_b.triggered.connect(self.on_cut_before_b_clicked)

        action_cut_after_e = self.more_menu.addAction("Cut all after markB")
        action_cut_after_e.triggered.connect(self.on_cut_after_e_clicked)
        
        
        self._action_set_gpx2video = self.more_menu.addAction("SetGPX2VideoTime")
        self._action_set_gpx2video.setEnabled(False)  # standard aus
        self._action_set_gpx2video.triggered.connect(self._on_set_gpx2video_triggered)

        action_cut_to_video = self.more_menu.addAction("Cut GPX to video (B..E)")
        action_cut_to_video.setStatusTip(
            "Camera was off: cut as much GPX after markB that markE lands on the current video time")
        action_cut_to_video.triggered.connect(self.on_cut_gpx_to_video_clicked)
        
        
        
        action_get_ele_mapbox = self.more_menu.addAction("GetElevation from Mapbox")
        action_get_ele_mapbox.triggered.connect(self._on_get_ele_mapbox)

        
        action_set_height_b2e = self.more_menu.addAction("setHeight(B2E)")
        action_set_height_b2e.triggered.connect(self.on_setHeight_B2E_clicked)

        action_profil = self.more_menu.addAction("Height profile editor (B..E)...")
        action_profil.setStatusTip(
            "Rebuild the heights between markB and markE by hand: support points, grades, rounding")
        action_profil.triggered.connect(self.on_height_profile_clicked)
        self._profil_editor = None
        # Stand nach dem letzten Smooth (core.hoehen_glaetten.Stand), None ohne
        self._glaettung = None
        
        action_resample = self.more_menu.addAction("Resample to 1s")
        action_resample.triggered.connect(self._on_resample_to_1s_clicked)
        
        
        # Menü dem Button zuweisen
        self.more_button.clicked.connect(self._on_more_button_clicked)
              

        

        # 9) Smooth
        self.smooth_button = QPushButton("Smooth", self)
        #self.undo_button.setMaximumWidth(50)
        self.smooth_button.setToolTip("Smooth the complete GPX \nChoose this only if you have complete edited!")
        self.smooth_button.clicked.connect(self.smoothClicked.emit)
        self._buttons_layout.addWidget(self.smooth_button)


        self.slot_button = QPushButton("Slot 1", self)
        self.slot_button.setToolTip("Switch GPX Slot: 1 (Import GPX/FIT, green) ↔ 2 (GoPro Extractor, blue)")
        self.slot_button.setMaximumWidth(70)
        self.slot_button.setCheckable(True)  # checked => Slot 2
        self._buttons_layout.addWidget(self.slot_button)
        self.slot_button.setContextMenuPolicy(Qt.NoContextMenu)    

        # Farben initial: Slot 1 = grün, Slot 2 = gelb
        self._slot1_style = "background-color:#2ecc71; color:black;"
        self._slot2_style = "background-color:#f1c40f; color:black;"
        self.slot_button.setStyleSheet(self._slot1_style)

        self.slot_button.clicked.connect(self._on_slot_button_clicked)
        
        self.slot_button.clicked.connect(self._on_slot_button_clicked)

        def _find_target_icon() -> str:
            from pathlib import Path
            import sys, os

            candidates = []
            # 1) PyInstaller-Bundle
            if hasattr(sys, "_MEIPASS"):
                candidates.append(Path(sys._MEIPASS) / "icon" / "target.png")
            # 2) Laufzeit-/EXE-Ordner (auch bei "python KVRouite.py")
            candidates.append(Path(os.path.abspath(os.path.dirname(sys.argv[0]))) / "icon" / "target.png")
            # 3) Repo-Layout relativ zu dieser Datei
            here = Path(__file__).resolve()
            candidates.append(here.parent / "icon" / "target.png")        # …/icon/target.png
            candidates.append(here.parent.parent / "icon" / "target.png") # …/../icon/target.png

            for c in candidates:
                if c.exists():
                    return str(c)
            return ""  # nichts gefunden => leerer String als Fallback

        # --- Slot-Sync Button (neben "Slot 2") ---
        self.slot_sync_button = QPushButton(self)
        self.slot_sync_button.setToolTip("Slot-Sync: jump to the nearest matching GPX point in Slot 1.")

        target_icon_path = _find_target_icon()
        if target_icon_path and os.path.exists(target_icon_path):
            self.slot_sync_button.setIcon(theme.icon(target_icon_path))
        else:
            self.slot_sync_button.setText("Target")  # Fallback

        self.slot_sync_button.setMaximumWidth(36)
        self.slot_sync_button.clicked.connect(self._on_slot_sync_clicked)
        self._buttons_layout.addWidget(self.slot_sync_button)

        
        self._buttons_layout.addStretch()

        # standardmäßig Slot 1 aktiv -> Button verstecken
        self.slot_sync_button.setVisible(False)

        # ---------------------------------------------
        # (B) Zweite Zeile: Info (Video/Length/Duration/Elev)
        # ---------------------------------------------
        self._info_layout = QHBoxLayout()
        self._info_layout.setSpacing(10)  # Zwischenraum zwischen Labels
        self.main_vbox.addLayout(self._info_layout)
        
        # Kurze Beschriftungen, die Erklaerung steckt im Tooltip. Die Info-Zeile
        # bestimmt die Mindestbreite der rechten Splitter-Spalte - jedes
        # gesparte Pixel haelt die 50/50-Teilung laenger.
        self.label_video = QLabel("V: 00:00:00", self)
        self.label_video.setToolTip(
            "Total length of all videos, cuts already deducted")
        self._info_layout.addWidget(self.label_video)

        # Laenge und Dauer in einem Label: "GPX: 8.94km/00:04:25"
        self.label_gpx = QLabel("GPX: 0.00km/00:00:00", self)
        self.label_gpx.setToolTip(
            "GPX track: total length / total duration")
        self._info_layout.addWidget(self.label_gpx)

        self.label_elev = QLabel("Ele: 0m", self)
        self.label_elev.setToolTip(
            "Elevation gain: sum of all climbs in the GPX track")
        self._info_layout.addWidget(self.label_elev)
        
        self.label_slope_max = QLabel("Max%: 0.0%", self)
        self.label_slope_max.setToolTip(
            "Steepest climb: highest gradient in the GPX track")
        self._info_layout.addWidget(self.label_slope_max)
        
        self.label_slope_min = QLabel("Min%: 0.0%", self)
        self.label_slope_min.setToolTip(
            "Steepest descent: lowest gradient in the GPX track")
        self._info_layout.addWidget(self.label_slope_min)

        self.label_zerospeed = QLabel("Zero: 0", self)
        self.label_zerospeed.setToolTip(
            "Zero speed: GPX points below the zero-speed threshold")
        self._info_layout.addWidget(self.label_zerospeed)
        
        self.label_paused = QLabel("Gaps: 0", self)
        self._info_layout.addWidget(self.label_paused)
        self.label_paused.setToolTip("Time gaps: consecutive GPX points with Δt above threshold")
        

        # Falls du sie mittig haben willst, kannst du z. B. links und rechts stretch:
        #self._info_layout.insertStretch(0)  # links
        self._info_layout.addStretch()      # rechts
        # ===== Rechts: großes Kinomap-Logo über volle Höhe =====
        from config import finde_datei
        logo_path = finde_datei("doc", "Kinomap_Logo.png")
       
        self._kinomap_big = QLabel(self)
        self._kinomap_big.setToolTip("Open Kinomap")
        self._kinomap_big.setCursor(QCursor(Qt.PointingHandCursor))
        self._kinomap_big.setContentsMargins(10, 0, 0, 0)  # etwas Luft zur Mitte
        
        
        self._kinomap_big.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._kinomap_big.setMaximumHeight(MAX_LOGO_H)    

        # Bild laden + Seitenverhältnis merken
        pm = QPixmap(logo_path) if os.path.exists(logo_path) else QPixmap()
        self._kinomap_aspect = (pm.width() / pm.height()) if (not pm.isNull() and pm.height() > 0) else 2.5

        # Label soll Bild proportional skalieren
        self._kinomap_big.setScaledContents(True)
        if not pm.isNull():
            self._kinomap_big.setPixmap(pm)
        else:
            self._kinomap_big.setText("Kinomap")
            self._kinomap_big.setAlignment(Qt.AlignCenter)
            self._kinomap_big.setMinimumWidth(90)

        # Klick öffnet Kinomap
        def _open_kinomap(_evt=None):
            QDesktopServices.openUrl(QUrl("https://www.kinomap.com/"))
        self._kinomap_big.mousePressEvent = _open_kinomap

        # Rechts in die HBox einhängen
        self._main_hbox.addWidget(self._kinomap_big, 0, Qt.AlignRight | Qt.AlignVCenter)

        # Beim Resizen Breite = Höhe * Aspect halten (damit volle Control-Höhe genutzt wird)
        self._kinomap_big.installEventFilter(self)

        # Verhindert, dass show()/hide() des Logos sich ueber resizeEvent selbst
        # wieder aufruft.
        self._logo_toggle_busy = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_logo_visibility()

    def _update_logo_visibility(self):
        """Logo ausblenden, wenn die Leiste sonst nicht mehr auf den Schirm passt.

        Das Logo belegt rund 130 px feste Breite. Auf breiten Fenstern stoert das
        nicht, auf einem 1920er Monitor sind es genau die Pixel, die am Ende
        fehlen. Deshalb: sichtbar solange Platz da ist, sonst weg. Die Schwelle
        wird aus dem tatsaechlichen Bedarf der beiden Zeilen berechnet, nicht
        geraten, damit sie bei anderer Schrift oder Sprache mitwandert.

        Die Hysterese (EIN erst 60 px ueber AUS) verhindert Flackern, wenn der
        Nutzer genau auf der Schwelle am Fensterrand zieht.
        """
        logo = getattr(self, "_kinomap_big", None)
        if logo is None or self._logo_toggle_busy:
            return

        need = max(self._buttons_layout.minimumSize().width(),
                   self._info_layout.minimumSize().width())
        margins = self._main_hbox.contentsMargins()
        need += margins.left() + margins.right()
        logo_cost = getattr(self, "_logo_full_width", 130) + self._main_hbox.spacing()
        avail = self.width()

        self._logo_toggle_busy = True
        try:
            if logo.isHidden():
                if avail >= need + logo_cost + 60:
                    logo.show()
            elif avail < need + logo_cost:
                logo.hide()
        finally:
            self._logo_toggle_busy = False

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_kinomap_big", None) and event.type() == QEvent.Resize:
            h = min(self._kinomap_big.height(), getattr(self, "_logo_max_h", MAX_LOGO_H))
            if h > 0 and getattr(self, "_kinomap_aspect", None):
                w = int(h * self._kinomap_aspect)
                # NICHT setFixedWidth: eine feste Breite wuerde in die
                # Mindestbreite der ganzen Leiste eingehen. Dann kann das
                # Fenster nie klein genug werden, damit das Ausblenden in
                # _update_logo_visibility() ueberhaupt greift.
                self._logo_full_width = max(60, w)
                self._kinomap_big.setMinimumWidth(1)
                self._kinomap_big.setMaximumWidth(self._logo_full_width)
        return super().eventFilter(obj, event)

    def on_setHeight_B2E_clicked(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        if b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range Selected",
                            "Please mark a range (markB..markE) first.")
            return

        # Falls markB > markE => tauschen
        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx

        if (e_idx - b_idx) < 1:
            QMessageBox.warning(self, "Invalid Range",
                            "The selected range must contain at least 2 points.")
            return

        # 1) Start/End-Höhen merken
        start_ele = gpx_data[b_idx].get("ele", 0.0)
        old_end_ele = gpx_data[e_idx].get("ele", 0.0)  # Original-Endhöhe vor Änderung

        # 2) Dialog: User wählt neue End-Höhe
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Set Height B..E (Wave-Preserve) – Range {b_idx}..{e_idx}")
        vbox = QVBoxLayout(dlg)

        lbl_info = QLabel(
            f"You have selected a range from index {b_idx} to {e_idx}.\n"
            "We will preserve the wave shape in [B..E], but shift the end to your new value.\n"
            "The start's elevation remains the same, the end's elevation is changed,\n"
            "and all in-between points keep their relative offsets.\n\n"
            "All subsequent points (after E) will be shifted by the difference from old_end_ele to new_end_ele."
        )
        vbox.addWidget(lbl_info)

        # Start-Höhe (read-only)
        row_start = QHBoxLayout()
        lbl_start = QLabel(f"Start Height ({b_idx}):")
        edit_start = QLineEdit(f"{start_ele:.2f}")
        edit_start.setReadOnly(True)
        row_start.addWidget(lbl_start)
        row_start.addWidget(edit_start)
        vbox.addLayout(row_start)

        # End-Höhe (editierbar)
        row_end = QHBoxLayout()
        lbl_end = QLabel(f"End Height ({e_idx}):")
        spin_end = QDoubleSpinBox()
        spin_end.setRange(-9999.0, 99999.0)  # je nach Bedarf anpassen
        spin_end.setDecimals(2)
        spin_end.setSingleStep(0.1)
        spin_end.setValue(old_end_ele)  # Vorbelegung
        row_end.addWidget(lbl_end)
        row_end.addWidget(spin_end)
        vbox.addLayout(row_end)

        # OK/Cancel
        h_btn = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        h_btn.addWidget(btn_ok)
        h_btn.addWidget(btn_cancel)
        vbox.addLayout(h_btn)
    
        def haversine_m(lat1, lon1, lat2, lon2):
            import math
            R = 6371000.0
            d_lat = math.radians(lat2 - lat1)
            d_lon = math.radians(lon2 - lon1)
            a = (math.sin(d_lat / 2.0) ** 2
                + math.cos(math.radians(lat1))
                * math.cos(math.radians(lat2))
                * math.sin(d_lon / 2.0) ** 2)
            return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        def calc_total_2d_distance(idxA, idxB):
            dist_sum = 0.0
            for x in range(idxA, idxB):
                lat1, lon1 = gpx_data[x]["lat"], gpx_data[x]["lon"]
                lat2, lon2 = gpx_data[x+1]["lat"], gpx_data[x+1]["lon"]
                dist_sum += haversine_m(lat1, lon1, lat2, lon2)
            return dist_sum
    
        def calc_cumulative_dist(idxA, idxI):
            # Distance from idxA to idxI
            return calc_total_2d_distance(idxA, idxI)
    
        def on_ok_dialog():
            new_end_val = spin_end.value()
            dlg.accept()

            # Undo-Snapshot
            self.register_gpx_undo_snapshot(self._schritt("Set height", b_idx, e_idx))
            

            # (A) Gesamtstrecke 2D in [b_idx.. e_idx]
            total_2d = calc_total_2d_distance(b_idx, e_idx)
            if total_2d < 0.001:
                QMessageBox.warning(
                    self, "Zero distance",
                    f"Range {b_idx}..{e_idx} has almost no 2D distance => can't do wave-based approach."
                )
                return
    
            # (B) Alte "Basislinie" + waveOffsets bestimmen
            #     Basislinie alt: L(i) = start_ele + frac*(old_end_ele - start_ele)
            #     waveOffset_i = oldEle_i - L(i)
            wave_offsets = {}
            for i in range(b_idx, e_idx + 1):
                dist_i = calc_cumulative_dist(b_idx, i)
                frac = dist_i / total_2d
                old_line_ele_i = start_ele + frac * (old_end_ele - start_ele)
                actual_ele_i   = gpx_data[i]["ele"]
                wave_offsets[i] = actual_ele_i - old_line_ele_i

            # (C) Neue Basislinie (start_ele -> new_end_val) + Wave Offset
            #     newEle_i = (start_ele + frac*(new_end_val - start_ele)) + waveOffset[i]
            for i in range(b_idx, e_idx + 1):
                dist_i = calc_cumulative_dist(b_idx, i)
                frac   = dist_i / total_2d
                new_line_ele_i = start_ele + frac * (new_end_val - start_ele)
                gpx_data[i]["ele"] = new_line_ele_i + wave_offsets[i]

            # (D) Konstanter Offset für alle Punkte ab e_idx+1
            offset = gpx_data[e_idx]["ele"] - old_end_ele

            # -- FIXED: Statt gpx_data[j]["ele"] + offset => old_data[j]["ele"] + offset 
            for j in range(e_idx + 1, len(gpx_data)):
                #old_ele_j = old_data[j]["ele"]  # der unveränderte Wert vor der Aktion
                #gpx_data[j]["ele"] = old_ele_j + offset
                gpx_data[j]["ele"] += offset
            # Recalc & Refresh
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()

            # -> Chart
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
                
                
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            
            ### nur range in editor llschen wenn autocut is enabled
            
            if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                mw.cut_manager.on_markClear_clicked()        
            

            QMessageBox.information(
                self, "Done",
                f"Range {b_idx}..{e_idx} wave-preserved.\n"
                f"Start remains {start_ele:.2f}m, end changed to {gpx_data[e_idx]['ele']:.2f}m.\n\n"
                f"All subsequent points (>{e_idx}) shifted by +{offset:.2f}m."
            )
            self.markB_index = None
            self.markE_index = None
            

            # Marker-Indexe zurücksetzen
            mw.gpx_widget.gpx_list._markB_idx = None
            mw.gpx_widget.gpx_list._markE_idx = None

            # Buttons zurücksetzen
            self.markB_button.setStyleSheet("")
            self.markE_button.setStyleSheet("")
            
            
        def on_cancel_dialog():
            dlg.reject()

        btn_ok.clicked.connect(on_ok_dialog)
        btn_cancel.clicked.connect(on_cancel_dialog)
        dlg.exec()
    
    
    @staticmethod
    def _bilinear(x0, y0, tx, ty, wert):
        """Gewichtetes Mittel der vier Pixel (x0,y0), (x0+1,y0), (x0,y0+1),
        (x0+1,y0+1) mit den Anteilen tx, ty in [0, 1). 'wert(px, py)' liefert
        den Pixelwert oder None; ein fehlendes Pixel faellt aus dem Mittel,
        fehlen alle, kommt None. Ohne Qt und ohne Netz, damit es sich ohne
        Fenster nachrechnen laesst."""
        summe = gewicht = 0.0
        for px, py, g in ((x0, y0, (1 - tx) * (1 - ty)),
                          (x0 + 1, y0, tx * (1 - ty)),
                          (x0, y0 + 1, (1 - tx) * ty),
                          (x0 + 1, y0 + 1, tx * ty)):
            v = wert(px, py)
            if v is None:
                continue
            summe += v * g
            gewicht += g
        return summe / gewicht if gewicht > 0 else None

    def update_elevation_from_mapbox(self, latlon_list):
        """
        Holt Elevation für latlon_list via Mapbox Terrain-RGB Tiles.
        latlon_list: [(gpx_idx, lat, lon), ...]
        Gibt zurück: (successful_points, tile_count)
        """
        import math
        from PIL import Image
        import io

        mw = self._mainwindow
        if not mw:
            return (0, 0)
        
        token = mw._mapbox_key.strip()
        if not token:
            print("[INFO] No Mapbox key – skipping elevation update")
            #QMessageBox.warning(self, "No Mapbox Key", "No Mapbox API key found. Please set it in Config > Map Keys.")
            return (0, 0)

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        # Zoom 15 ist die feinste Stufe, die das Terrain-RGB-Tileset hat.
        # Vorher Zoom 14 und je Punkt das naechste Pixel: auf 46 Grad Breite
        # ist ein Pixel dort 6.6 m breit, die Punkte liegen 3.3 m auseinander.
        # Zwei, drei Punkte bekamen denselben Wert, dann ein Sprung um 1.5 m,
        # und aus dem Sprung wurden 50 bis 130 % Steigung. Jetzt liegt die
        # Hoehe zwischen den vier Nachbarpixeln (bilinear): eine durchgehende
        # Linie ohne Treppen. Die Aufloesung der Quelle selbst bleibt.
        ZOOM = 15
        TILE = 256  # pngraw-Kacheln von terrain-rgb v4 sind 256 px

        def latlon_to_pixel(lat, lon):
            """Weltweite Pixelkoordinate auf ZOOM, mit Nachkommastellen."""
            n = 2 ** ZOOM * TILE
            x = (lon + 180.0) / 360.0 * n
            y = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
            return x, y

        # Schritt 1: Stuetzpixel je Punkt und die Kacheln dazu. Ein Pixel
        # steht fuer seine Mitte (+0.5). Die vier Nachbarn koennen in der
        # Nachbarkachel liegen, deshalb je Stuetzpixel die Kachel bestimmen.
        stuetzen = []   # (gpx_i, x0, y0, tx, ty): Pixel links oben und Anteile
        needed_tiles = set()
        for gpx_i, lat, lon in latlon_list:
            x, y = latlon_to_pixel(lat, lon)
            fx, fy = x - 0.5, y - 0.5
            x0, y0 = math.floor(fx), math.floor(fy)
            stuetzen.append((gpx_i, x0, y0, fx - x0, fy - y0))
            for px, py in ((x0, y0), (x0 + 1, y0), (x0, y0 + 1), (x0 + 1, y0 + 1)):
                needed_tiles.add((px // TILE, py // TILE))

        # Schritt 2: Tiles herunterladen
        tile_images = {}
        tile_count = 0

        for (xtile, ytile) in needed_tiles:
            url = f"https://api.mapbox.com/v4/mapbox.terrain-rgb/{ZOOM}/{xtile}/{ytile}.pngraw?access_token={token}"
            try:
                with urllib.request.urlopen(url) as response:
                    img_bytes = response.read()
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    tile_images[(xtile, ytile)] = img
                    tile_count += 1
            except Exception as e:
                QMessageBox.warning(self, "Tile Load Error",
                    f"Could not load tile {xtile},{ytile}:\n{e}")
                return (0, 0)
    
        if tile_count == 0:
            return (0, 0)

        # Schritt 3: Höhenwerte extrahieren
        successful_points = 0
    
        def hoehe(px, py):
            """Hoehe des Pixels (px, py) in Weltkoordinaten; None ohne Kachel."""
            img = tile_images.get((px // TILE, py // TILE))
            if img is None or px % TILE >= img.width or py % TILE >= img.height:
                return None
            r, g, b = img.getpixel((px % TILE, py % TILE))
            return -10000 + ((r * 256 * 256 + g * 256 + b) * 0.1)

        # bilinear aus den vier Nachbarpixeln
        for gpx_i, x0, y0, tx, ty in stuetzen:
            ele = self._bilinear(x0, y0, tx, ty, hoehe)
            if ele is None:
                print(f"[WARN] Terrain tile missing for point {gpx_i}")
                continue
            gpx_data[gpx_i]["ele"] = ele
            successful_points += 1

        return (successful_points, tile_count)

    ###
    def _on_get_ele_mapbox(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        if b_idx is None and e_idx is None:
            QMessageBox.warning(self, "No Selection", "Please mark a GPX range or a single point with markB.")
            return

        if b_idx is not None and e_idx is None:
            # Nur ein Punkt (markB) ausgewählt
            if not (0 <= b_idx < len(gpx_data)):
                QMessageBox.warning(self, "Invalid Point", "Marked point index is invalid.")
                return

            reply = QMessageBox.question(
                self,
                "Get Elevation from Mapbox",
                f"This will fetch elevation data for point {b_idx}.\nDo you want to proceed?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            latlon_list = [(b_idx, gpx_data[b_idx]["lat"], gpx_data[b_idx]["lon"])]

        else:
            # Bereich (B..E) ausgewählt
            if b_idx is None or e_idx is None:
                QMessageBox.warning(self, "Invalid Selection", "Both markB and markE must be set for a range.")
                return

            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx

            if e_idx - b_idx < 1:
                QMessageBox.information(self, "Invalid Range", "At least 2 points needed in B..E range.")
                return

            reply = QMessageBox.question(
                self,
                "Get Elevation from Mapbox",
                f"This will fetch precise elevation data from Mapbox for the selected GPX range {b_idx} to {e_idx}.\nDo you want to proceed?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            latlon_list = [(i, gpx_data[i]["lat"], gpx_data[i]["lon"]) for i in range(b_idx, e_idx + 1)]
    
        # Elevation abrufen
        successful_points, tile_count = self.update_elevation_from_mapbox(latlon_list)

        #if tile_count == 0:
        if tile_count == 0 and successful_points == 0:
            #QMessageBox.warning(self, "Mapbox Error", "No elevation tiles could be loaded.\nCheck your Mapbox API key.")
            print("[INFO] No elevation loaded – possibly due to missing Mapbox key")
            return
        if successful_points == 0:
            QMessageBox.warning(self, "No Elevation Found", "Tiles were loaded, but no elevation values could be decoded.")
            return

        # GPX aktualisieren
        self.register_gpx_undo_snapshot(self._schritt("Elevation from Mapbox", b_idx, e_idx))
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        mw.map_widget.clear_marked_range()
        mw.gpx_widget.gpx_list.clear_marked_range()
        
        
        
            
        ### nur range in editor llschen wenn autocut is enabled
        
        if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
            mw.cut_manager.on_markClear_clicked()
                
    
        QMessageBox.information(
            self, "Done",
            f"Elevation updated for {successful_points} point(s) via Mapbox Terrain-RGB."
        )

    
    
    ###
    #TODO: test this
    def _on_set_gpx2video_triggered(self):
        """
        Zeigt eine MessageBox mit den Zeitbereichen (Video + GPX).
        Fragt den User: "Do you want to sync GPX time to the Video time range?"
        Falls OK => wir skalieren den GPX-Bereich B..E auf dieselbe Länge wie Video-B..E
        und shiften alle nachfolgenden GPX-Punkte.
        """
        mw = self._mainwindow
        if not mw:
            return  # kein MainWindow => abbrechen
    
        #gom PySide6.QtWidgets import QMessageBox
        

        # --------------------------------------------------------------------
        # 1) Hilfsfunktion zur Formatierung in "xh ym zs" (siehe vorher)
        # --------------------------------------------------------------------
        def _format_duration(seconds: float) -> str:
            if seconds < 0:
                return "(not set)"
            total_s = int(round(seconds))
            hh = total_s // 3600
            rest = total_s % 3600
            mm = rest // 60
            ss = rest % 60
            parts = []
            if hh > 0:
                parts.append(f"{hh}h")
            if mm > 0:
                parts.append(f"{mm}min")
            if ss > 0 or (hh == 0 and mm == 0):
                parts.append(f"{ss}s")
            return " ".join(parts)

        # --------------------------------------------------------------------
        # 2) Video-Bereich: markB_time_s, markE_time_s
        # --------------------------------------------------------------------
        vB = mw.cut_manager.markB_time_s or -1
        vE = mw.cut_manager.markE_time_s or -1
        if vB < 0 or vE < 0 or vE <= vB:
            video_len = -1
        else:
            video_len = (vE - vB)

        video_start_str = _format_duration(vB)
        video_end_str   = _format_duration(vE)
        video_len_str   = _format_duration(video_len)

        # --------------------------------------------------------------------
        # 3) GPX-Bereich: b_idx, e_idx + rel_s
        # --------------------------------------------------------------------
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
        gpx_data = mw.gpx_widget.gpx_list._gpx_data

        # Start/End als Sekunden
        if b_idx is not None and 0 <= b_idx < len(gpx_data):
            gpx_b_dt = gpx_data[b_idx].get("time", None)
        else:
            gpx_b_dt = None
    
        if e_idx is not None and 0 <= e_idx < len(gpx_data):
            gpx_e_dt = gpx_data[e_idx].get("time", None)
        else:
            gpx_e_dt = None

        if not gpx_b_dt or not gpx_e_dt or gpx_e_dt <= gpx_b_dt:
            gpx_len_sec = -1
        else:
            gpx_len_sec = (gpx_e_dt - gpx_b_dt).total_seconds()

        # relative Anzeige: Sekunden relativ zu (GPX[0].time + video_shift)
        rel0 = gpx_data[0].get("time", None)
        if rel0:
            gpx_rel0 = rel0 + timedelta(seconds=get_gpx_video_shift())
            gpx_start_str = _format_duration((gpx_b_dt - gpx_rel0).total_seconds() if gpx_b_dt else -1)
            gpx_end_str   = _format_duration((gpx_e_dt - gpx_rel0).total_seconds() if gpx_e_dt else -1)
        else:
            gpx_start_str = "(not set)"
            gpx_end_str   = "(not set)"
        gpx_len_str = _format_duration(gpx_len_sec)
    
        # --------------------------------------------------------------------
        # 4) Info an den User (Anzeigen der Bereiche)
        # --------------------------------------------------------------------
        msg_text = (
            "Video Range:\n"
            f"  Start:  {video_start_str}\n"
            f"  End:    {video_end_str}\n"
            f"  Length: {video_len_str}\n\n"
            "GPX Range:\n"
            f"  Start:  {gpx_start_str}\n"
            f"  End:    {gpx_end_str}\n"
            f"  Length: {gpx_len_str}\n\n"
            "Do you want to synchronize the GPX range to the Video range?"
        )

        reply = QMessageBox.question(
            self,
            "SetGPX2VideoTime",
            msg_text,
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if reply != QMessageBox.Ok:
            # => Abbruch
            return
    
        # --------------------------------------------------------------------
        # 5) Nur wenn BEIDE Bereiche valide sind (>=0) => skalieren wir
        # --------------------------------------------------------------------
        if video_len <= 0 or gpx_len_sec <= 0:
            QMessageBox.information(
                self,
                "SetGPX2VideoTime",
                "Invalid range(s). Unable to synchronize."
            )
            return
    
        # => Undo-Snapshot
        self.register_gpx_undo_snapshot(self._schritt("Set GPX to video time", b_idx, e_idx))
    
        # alt = gpx_len_sec, neu = video_len
        old_duration = gpx_len_sec
        new_duration = video_len
        diff_s = new_duration - old_duration
    
        # (A) Skalierung: b_idx..e_idx
        # Wir gehen i von b_idx+1.. e_idx => berechnen fraction:
        # fraction = (time[i] - time[b_idx]) / old_duration
        # new_time[i] = time[b_idx] + fraction*new_duration
        t_b0 = gpx_data[b_idx]["time"]  # datetime
    
        if old_duration < 1e-9:
            # => Abbruch
            QMessageBox.warning(self, "Error", "GPX range is effectively 0s => cannot scale.")
            return

        for i in range(b_idx + 1, e_idx + 1):
            # Sekunden seit t_b0 im Originalbereich
            rel_i = (gpx_data[i]["time"] - t_b0).total_seconds()
            fraction = rel_i / old_duration
            new_rel = fraction * new_duration
            gpx_data[i]["time"] = t_b0 + timedelta(seconds=new_rel)
    
        # (B) Shift aller Punkte nach e_idx um diff_s
        # => d. h. ab e_idx+1 bis zum Ende => time[j] += diff_s
        if e_idx < len(gpx_data)-1 and abs(diff_s) > 1e-9:
            for j in range(e_idx+1, len(gpx_data)):
                old_tj = gpx_data[j]["time"]
                gpx_data[j]["time"] = old_tj + timedelta(seconds=diff_s)
    
        # (C) recalc + set
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
    
        # => Chart, Map
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
    
        # Finale Info
        QMessageBox.information(
            self,
            "SetGPX2VideoTime",
            f"GPX range has been rescaled from { _format_duration(old_duration) } "
            f"to { _format_duration(new_duration) }.\n"
            "Subsequent points were shifted accordingly."
        )
    
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()

        # Video-Markierungen entfernen
        if hasattr(mw, "cut_manager"):
            mw.cut_manager.on_markClear_clicked()

        # Buttons zurücksetzen
        self.markB_button.setStyleSheet("")
        self.markE_button.setStyleSheet("")
        mw.gpx_widget.gpx_list._markB_idx = None
        mw.gpx_widget.gpx_list._markE_idx = None
     
     
    
        
    def set_directions_mode(self, enabled: bool):
        if enabled:
            self._action_closegaps.setText("Close Gaps (Directions)")
        else:
            self._action_closegaps.setText("Close Gaps")    
        
    
    def _on_more_button_clicked(self):
        # Menü manuell anzeigen, normalerweise direkt unterhalb des Buttons.
        #
        # Mit der Aufrufoption "-menuup" stattdessen nach oben: Oberkante des
        # Menues = Oberkante des Buttons minus Menuehoehe, sodass die letzte
        # Zeile ueber dem Button sitzt. sizeHint() ist vor dem ersten
        # Anzeigen gueltig, QMenu berechnet die Eintraege dafuer.
        if config.MORE_MENU_OPENS_UPWARD:
            pos = self.more_button.mapToGlobal(QPoint(0, -self.more_menu.sizeHint().height()))
        else:
            pos = self.more_button.mapToGlobal(QPoint(0, self.more_button.height()))
        self.more_menu.exec_(pos)
        
    def schwebend(self, an: bool, bewegt=None, losgelassen=None):
        """Griff zum Ziehen zeigen (schwebend) oder verbergen (angedockt).

        Schwebend hat die Leiste ihre natuerliche Breite statt der vollen
        Fensterbreite, und einen Rahmen, damit sie sich vom Untergrund
        abhebt - ueber der Karte laege sie sonst wie ausgeschnitten.
        """
        if not hasattr(self, "_griff"):
            self._griff = LeistenGriff(self, bewegt=bewegt, losgelassen=losgelassen)
            self._main_hbox.insertWidget(0, self._griff)
        self._griff._bewegt = bewegt
        self._griff._losgelassen = losgelassen
        self._griff.setVisible(bool(an))
        if an:
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            # Ein QWidget malt seinen Stylesheet-Hintergrund nur mit
            # WA_StyledBackground - ohne das schien die Tabelle durch die
            # Leiste hindurch (gesehen am 08.09.2026 im ersten Bild).
            self.setAttribute(Qt.WA_StyledBackground, True)
            f = theme.farben()
            self.setStyleSheet("GPXControlWidget { background: %s; border: 1px solid %s; }"
                               % (f["fenster"], f["kopf_linie"]))
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setAttribute(Qt.WA_StyledBackground, False)
            self.setStyleSheet("")

    def kompakt(self, an: bool, logo_voll: bool = False):
        """Flachere Leiste - fuer den Platz unter der Karte und schwebend.

        Knoepfe auf 22 px statt der 26 px, die Qt ihnen gibt, engere
        Raender und weniger Abstand zwischen Knopf- und Infozeile. Gemessen:
        58 px werden 44 px. Das Logo: an der Karte 24 px statt 48, damit die
        Leiste flach bleibt; schwebend (logo_voll) die volle Innenhoehe von
        40 px - dort kostet es keine Kartenhoehe, und Bernd wollte es am
        08.09.2026 groesser. Die Breite folgt dem Seitenverhaeltnis im
        eventFilter. Mit an=False kommt alles auf die Vorgaben zurueck.
        """
        self._kompakt = bool(an)
        for knopf in self.findChildren(QPushButton):
            if an:
                knopf.setFixedHeight(22)
            else:
                knopf.setMinimumHeight(0)
                knopf.setMaximumHeight(16777215)   # QWIDGETSIZE_MAX
        if not an:
            self._logo_max_h = MAX_LOGO_H
        elif logo_voll:
            self._logo_max_h = 40
        else:
            self._logo_max_h = 24
        self._kinomap_big.setMaximumHeight(self._logo_max_h)
        # Die Breite gleich mitsetzen: der eventFilter zieht sie sonst erst
        # beim naechsten Resize des Labels nach, und das bleibt aus, wenn
        # die alte Maximalbreite das Wachsen verhindert.
        if getattr(self, "_kinomap_aspect", None):
            self._logo_full_width = max(60, int(self._logo_max_h * self._kinomap_aspect))
            self._kinomap_big.setMaximumWidth(self._logo_full_width)
        if an:
            self._main_hbox.setContentsMargins(4, 2, 8, 2)
            self.main_vbox.setSpacing(2)
        else:
            self._main_hbox.setContentsMargins(5, 5, 20, 5)
            self.main_vbox.setSpacing(5)
        self.updateGeometry()

    def set_mainwindow(self, mw):
        """
        Mit dieser Methode geben wir dem GPXControlWidget
        einen Zeiger auf das MainWindow, damit wir dort
        auf ._gpx_data, .gpx_widget, .map_widget usw. zugreifen können.
        """
        self._mainwindow = mw   
        
            
    def _on_slot_button_clicked(self):
        """
        Slot umschalten – aber Anzeige strikt aus dem *tatsächlichen* MainWindow-State
        ableiten (kein Vorweg-Kippen des Buttons).
        """
        mw = getattr(self, "_mainwindow", None)
        if not mw:
            return

        # Wunschziel aus dem Toggle ableiten (checked => Slot 2)
        target_slot = 2 if self.slot_button.isChecked() else 1

        # Wechsel anfragen (dein MainWindow entscheidet und kann ablehnen)
        ok = mw.switch_gpx_slot(target_slot)

        # Danach IMMER den realen Zustand spiegeln:
        actual = getattr(mw, "_active_gpx_slot", 1)

        # Button & Style konsistent setzen (Signals blocken, damit kein Re-Trigger)
        self.slot_button.blockSignals(True)
        self.slot_button.setChecked(actual == 2)
        self.slot_button.setText(f"Slot {actual}")
        self.slot_button.setStyleSheet(self._slot2_style if actual == 2 else self._slot1_style)
        self.slot_button.blockSignals(False)

        # Optional: Video-UI refresh
        if hasattr(mw.video_control, "update_set_sync_highlight"):
            mw.video_control.update_set_sync_highlight()



        # --- NEU: Optik/Status des Slot-Buttons zentral setzen ---
    def apply_slot_button_style(self, active_slot: int):
        btn = self.slot_button

        # Falls Styles vordefiniert sind, nehmen wir sie. Sonst einfache Defaults.
        slot1_style = getattr(self, "_slot1_style", "QPushButton{background:#2e7d32;color:white;}")  # grün
        slot2_style = getattr(self, "_slot2_style", "QPushButton{background:#f9a825;color:black;}")  # gelb

        btn.blockSignals(True)
        btn.setText(f"Slot {active_slot}")
        if active_slot == 1:
            btn.setChecked(False)              # (bei dir ist Slot2 "checked")
            btn.setStyleSheet(slot1_style)
        else:
            btn.setChecked(True)
            btn.setStyleSheet(slot2_style)
        btn.blockSignals(False)

        # Hart refreshen, damit Styles sofort greifen:
        s = btn.style()
        s.unpolish(btn)
        s.polish(btn)
        btn.update()
        try:
            self.slot_sync_button.setVisible(active_slot == 2)
        except Exception:
            pass
    
    def _on_slot_sync_clicked(self):
        """
        Gleiche Funktion wie Rechtsklick auf den Slot-Button:
        - Nimmt den selektierten GPX-Punkt im aktiven Slot (hier: Slot 2),
        - sucht im anderen Slot den nächstgelegenen Punkt,
        - wechselt ggf. den Slot und selektiert/zoomt dorthin.
        """
        mw = getattr(self, "_mainwindow", None)
        if not mw:
            return
        mw.jump_to_nearest_point_in_other_slot()

    
    

    # ----------------------------------------------------------
    # Methode zum Aktualisieren der Info-Zeile
    # ----------------------------------------------------------
   
    def update_info_line(self,
                     video_time_str: str,
                     length_km: float,
                     duration_str: str,
                     elev_gain: float,
                     slope_max: float = 0.0,
                     slope_min: float = 0.0,
                     zero_speed_count: int = 0,
                     paused_count: int = 0):                         
        """
        Aktualisiert die Labels in der Infozeile:
        - V     (Videoposition)
        - GPX   (Laenge/Dauer, ein Label)
        - Ele   (Hoehengewinn)
        - Max%/Min%, Zero, Gaps
        """
        # Rohwerte merken - die GPX-Summary braucht sie und soll sie nicht aus
        # dem Anzeigetext zurueckrechnen muessen.
        self._elev_gain = float(elev_gain)
        self._length_km = float(length_km)

        self.label_video.setText(f"V: {video_time_str}")
        self.label_gpx.setText(f"GPX: {length_km:.2f}km/{duration_str}")
        self.label_elev.setText(f"Ele: {int(elev_gain)}m")
        self.label_slope_max.setText(f"Max%: {slope_max:.1f}%")
        self.label_slope_min.setText(f"Min%: {slope_min:.1f}%")
        self.label_zerospeed.setText(f"Zero: {zero_speed_count}")
        self.label_paused.setText(f"Gaps: {paused_count}")    
        
        
    def set_markE_visibility(self, visible: bool):
        """
        Zeigt oder versteckt den MarkE-Button.
        """
        self.markE_button.setVisible(visible)    
        self.markB_button.setVisible(visible)   # auch markB vestecken 
        self.deselect_button.setVisible(visible) # auch deselect verstecken
        self.cut_button.setVisible(visible)  
        
    
    def _process_delete_points(self, shift_next: bool = True):
        """
        Delete-/Remove-Button:
          - Standard: leitet an gpx_list.delete_selected_range(shift_next) weiter
          - Sonderfall (Head-Cut): Remove („-“) + Range beginnt bei Index 0
            => Δt inkl. +1 Schrittweite bestimmen
            => löschen
            => Δt ab Index 1 addieren
            => Zeiten auf 0.000 normalisieren
            => GPX–Video-Shift um Δt reduzieren (damit Liste bei 0.000 startet)
            => Recalc + UI-Refresh
        """
        # Lokale Imports, damit datetime/timedelta sicher definiert sind
        from datetime import datetime, timedelta

        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.information(
                self,
                "No GPX loaded",
                "No GPX data is loaded.\nOperation cancelled."
            )
            return

        # --- Graubereich-Check wie gehabt ---
        try:
            cur_shift = get_gpx_video_shift()
        except Exception:
            cur_shift = 0.0
        auto_on = hasattr(mw, "action_auto_sync_video") and mw.action_auto_sync_video.isChecked()
        hit_grey = False
        if (not auto_on) and (cur_shift < 0):
            data = gpx_data
            b = mw.gpx_widget.gpx_list._markB_idx
            e = mw.gpx_widget.gpx_list._markE_idx
            if data and b is not None and e is not None:
                if b > e:
                    b, e = e, b
                positive_time = data[0]["time"] + timedelta(seconds=abs(cur_shift))
                hit_grey = data[b]["time"] < positive_time

        # --- Undo + Busy ---
        mw.register_gpx_undo_snapshot(self._schritt(
            "Cut GPX" if shift_next else "Remove GPX",
            mw.gpx_widget.gpx_list._markB_idx, mw.gpx_widget.gpx_list._markE_idx))
        mw.map_widget.view.page().runJavaScript("showLoading('Deleting GPX-Range...');")

        # --- Head-Cut erkennen (nur für Remove / shift_next == False) ---
        headcut = False
        head_cut_diff_s = 0.0
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
        if not shift_next and gpx_data and b_idx is not None and e_idx is not None:
            b, e = (b_idx, e_idx)
            if b > e:
                b, e = e, b
            if b == 0 and 0 <= e < len(gpx_data):
                t0 = gpx_data[0]["time"]
                tE = gpx_data[e]["time"]
                # Schrittweite ermessen (typisch 1 s), robust:
                if e + 1 < len(gpx_data):
                    step_s = (gpx_data[e + 1]["time"] - gpx_data[e]["time"]).total_seconds()
                elif len(gpx_data) >= 2:
                    step_s = (gpx_data[1]["time"] - gpx_data[0]["time"]).total_seconds()
                else:
                    step_s = 0.0
                # Inklusive Range => + step_s
                head_cut_diff_s = (tE - t0).total_seconds() + step_s
                headcut = head_cut_diff_s > 0.0
                # print(f"[DEBUG] HeadCut candidate: Δt={head_cut_diff_s:.3f}s  (b=0..e={e})")

        # --- Bereich löschen ---
        mw.gpx_widget.gpx_list.delete_selected_range(shift_next)

        # --- Nachbearbeitung NUR für Head-Cut (Remove ab Index 0) ---
        if headcut:
            data_after = mw.gpx_widget.gpx_list._gpx_data
            if data_after and len(data_after) >= 2:
                # 1) Δt ab Index 1 addieren (Index 1..N-1)
                dt_add = timedelta(seconds=head_cut_diff_s)
                for i in range(1, len(data_after)):
                    ti = data_after[i].get("time")
                    if ti is not None:
                        data_after[i]["time"] = ti + dt_add

                # 2) Zeiten auf 0.000 normalisieren (erster verbleibender Punkt als Basis)
                base_dt = data_after[0]["time"]
                epoch0 = datetime(1970, 1, 1)
                for pt in data_after:
                    rel_s = (pt["time"] - base_dt).total_seconds()
                    pt["time"] = epoch0 + timedelta(seconds=rel_s)

                # 3) GPX–Video-Shift anpassen: alterShift - Δt (min. 0)
                try:
                    old_shift = get_gpx_video_shift() or 0.0
                except Exception:
                    old_shift = 0.0
                new_shift = old_shift - head_cut_diff_s
                if new_shift < 0.0:
                    new_shift = 0.0
                try:
                    set_gpx_video_shift(new_shift)
                    if hasattr(mw.video_control, "update_set_sync_highlight"):
                        mw.video_control.update_set_sync_highlight()
                except Exception as e:
                    print(f"[DEBUG] set_gpx_video_shift failed: {e}")

                # 4) Recalc + UI Refresh
                try:
                    from core.gpx_parser import recalc_gpx_data
                    recalc_gpx_data(data_after)
                except Exception as err:
                    print(f"[DEBUG] recalc_gpx_data failed: {err}")

                mw.gpx_widget.gpx_list.set_gpx_data(data_after)
                mw._gpx_data = data_after
                mw._update_gpx_overview()
                if hasattr(mw.chart, "set_gpx_data"):
                    mw.chart.set_gpx_data(data_after)
                if getattr(mw, "mini_chart_widget", None):
                    mw.mini_chart_widget.set_gpx_data(data_after)
                mw.map_widget.loadRoute(mw._build_route_geojson_from_gpx(data_after), do_fit=False)

                mw.map_widget.view.page().runJavaScript("hideLoading();")
                # Headcut-Fall ist vollständig behandelt → früh raus
                return

        # --- Standard-Updates (alle anderen Fälle unverändert) ---
        mw._update_gpx_overview()
        mw._gpx_data = mw.gpx_widget.gpx_list._gpx_data
        route_geojson = mw._build_route_geojson_from_gpx(mw._gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(mw._gpx_data)
        if mw.mini_chart_widget and mw._gpx_data:
            mw.mini_chart_widget.set_gpx_data(mw._gpx_data)
        mw.map_widget.view.page().runJavaScript("hideLoading();")

        # --- Graubereich-Dialog (wie gehabt) ---
        if hit_grey:
            reply = QMessageBox.question(
                self,
                "Sync may be invalid",
                "You manually cut inside the pre-video (grey) section.\n"
                f"The current GPX–video shift ({cur_shift:+.1f}s) will be cleared.\n\n"
                "Do you want to set a new sync now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            set_gpx_video_shift(0)
            route_geojson = mw._build_route_geojson_from_gpx(mw._gpx_data)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)
            mw.gpx_widget.gpx_list.set_gpx_data(mw._gpx_data)
            mw.video_control.activate_controls()
            if hasattr(mw.video_control, "update_set_sync_highlight"):
                mw.video_control.update_set_sync_highlight()
            if reply == QMessageBox.Yes:
                mw.gpx_widget.gpx_list.clear_marked_range()
                if hasattr(mw, "map_widget"):
                    mw.map_widget.clear_marked_range()
                if hasattr(mw.video_control, "update_set_sync_highlight"):
                    mw.video_control.update_set_sync_highlight()
                if hasattr(mw, "chart") and hasattr(mw.chart, "clear_sync_range"):
                    mw.chart.clear_sync_range()    
                QMessageBox.information(
                    mw,
                    "Set a new sync",
                    "Please select the matching GPX point and set the current video frame, "
                    "then click 'Sync' (GSync) to create a new alignment."
                )
            else:
                if hasattr(mw, "chart") and hasattr(mw.chart, "clear_sync_range"):
                    mw.chart.clear_sync_range() 
                    
        if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
            mw.cut_manager.on_markClear_clicked()

    def on_cut_range_clicked(self):
       self._process_delete_points(True)

    def on_remove_range_clicked(self):
       self._process_delete_points(False)
        
        
    def _on_show_max_slope(self):
        mw = self._mainwindow
        # 1) Finde Index    
        #    z. B. idx_max = self._index_of_max_slope
        #    (woher? -> du hast es in _update_gpx_overview() schon)
        #    oder du rechnest hier nochmal:
        data = mw.gpx_widget.gpx_list._gpx_data
        if not data:
            return
        slopes = [pt["gradient"] for pt in data]
        idx_max = slopes.index(max(slopes))  # index des Max-Wertes

        # 2) Markieren in Chart, Map, GpxList, MiniChart
        mw._highlight_index_everywhere(idx_max)    
        
    def _on_show_min_slope(self):
        mw = self._mainwindow
        data = mw.gpx_widget.gpx_list._gpx_data
        if not data:
            return
        slopes = [pt["gradient"] for pt in data]
        idx_min = slopes.index(min(slopes))

        mw._highlight_index_everywhere(idx_min)    
        
    def check_data_for_avg(self) -> bool:
        mw = self._mainwindow 
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return False

        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return False
        
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
    
        if b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range Selected",
                "Please mark a range (markB..markE) first.")
            return False

        if (e_idx - b_idx) < 1:
            QMessageBox.warning(self, "Invalid Range",
                "The selected range must contain at least 2 points.")
            return False
        
        return True
        
    def on_average_speed_clicked(self):
        mw = self._mainwindow 
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        """
        Shows the current average speed for the selected range b_idx.. e_idx
        *without changing total time*.
        If the user accepts, we distribute the times so that
        each subsegment has the same local speed (i.e., flatten spikes),
        but overall time remains the same.
        """
        if not self.check_data_for_avg():
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
    
        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx
    
        # 1) Gesamt-Zeit
        t_start = gpx_data[b_idx]["time"]
        t_end   = gpx_data[e_idx]["time"]
        total_s = (t_end - t_start).total_seconds()
        if total_s <= 0:
            QMessageBox.warning(self, "Invalid Time",
                f"Time in the range {b_idx}..{e_idx} is zero or reversed.")
            return
    
        # 2) Distanz summieren
        total_dist_m = 0.0
        for i in range(b_idx, e_idx):
            lat1, lon1 = gpx_data[i]["lat"],   gpx_data[i]["lon"]
            lat2, lon2 = gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            d2 = self._haversine_m(lat1, lon1, lat2, lon2)
            total_dist_m += d2
        if total_dist_m < 0.001:
            QMessageBox.warning(self, "Zero Distance",
                f"Range {b_idx}..{e_idx} has almost no distance => speed meaningless.")
            return
    
        dist_km = total_dist_m / 1000.0
        time_h = total_s / 3600.0
        old_avg_speed = dist_km / time_h  # km/h
    
        # 3) Frage, ob wir flatten wollen
        msg = (
            f"Range {b_idx}..{e_idx}\n"
            f"Total distance: {dist_km:.3f} km\n"
            f"Total time: {total_s:.1f} s\n\n"
            f"Current average speed in this range: {old_avg_speed:.2f} km/h\n\n"
            "Do you want to flatten spikes so that every subsegment\n"
            "has the same local speed? (Total time remains unchanged!)"
        )
        reply = QMessageBox.question(
            self, "Flatten Speed?",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return  # aborted
    
        # 4) Undo-Snapshot
        self.register_gpx_undo_snapshot(self._schritt("Set average speed", b_idx, e_idx))
        
        # 5) partial-dist array
        partial_dist = [0.0]
        cum = 0.0
        for i in range(b_idx, e_idx):
            d2 = self._haversine_m(
                gpx_data[i]["lat"], gpx_data[i]["lon"],
                gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            )
            cum += d2
            partial_dist.append(cum)
    
        # 6) Verteilen => time[i] = t_start + frac*total_s
        for k in range(1, e_idx - b_idx + 1):
            frac = partial_dist[k] / partial_dist[-1]  # last partial_dist is total_dist_m
            offset_s = total_s * frac
            gpx_data[b_idx + k]["time"] = t_start + timedelta(seconds=offset_s)
    
        # => e_idx bleibt t_end => identisch => also total_s bleibt 
        # => wir ändern NICHT time[e_idx], da offset_s=total_s an k = e_idx - b_idx
    
        # 7) recalc
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
    
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
    
        #route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        #mw.map_widget.loadRoute(route_geojson, do_fit=False)
        
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
            
        ### nur range in editor llschen wenn autocut is enabled
        if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
            mw.cut_manager.on_markClear_clicked()

        QMessageBox.information(
            self, "Flatten done",
            "All subsegments in this range now share the same local speed.\n"
            "Total time remained unchanged."
        )
        
        

    # ------------------------------------------------------------------
    # Geschwindigkeitsspitze an einer Schnittnaht glaetten
    # ------------------------------------------------------------------
    def on_fix_spike_clicked(self):
        """Menue '...' -> 'Fix speed spike (cut seam)'.

        Arbeitet auf der angeklickten Zeile. Ist die keine Spitze, werden
        die gefundenen Spitzen zur Auswahl angeboten. Die Rechnung steht in
        core/naht_glaetten.py, hier ist nur der Dialog und das Uebernehmen -
        das Uebernehmen genauso wie bei chT, denn es ist dieselbe Art
        Aenderung: nur Zeiten.
        """
        from PySide6.QtWidgets import QInputDialog

        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data if mw else None
        if not gpx_data or len(gpx_data) < 3:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        spitzen = naht_glaetten.spitzen_finden(gpx_data)
        row = mw.gpx_widget.gpx_list.table.currentRow()
        if row not in spitzen:
            if not spitzen:
                QMessageBox.information(
                    self, "No speed spike",
                    "No speed spike found in this track.\n\n"
                    "A spike is a segment longer than %.0f m that is at least "
                    "%.0f times faster than its surroundings - what a cut "
                    "after a camera failure leaves behind."
                    % (naht_glaetten.MIN_SPRUNG_M, naht_glaetten.SPITZE_FAKTOR))
                return
            eintraege = ["Row %d: %.0f km/h, %.0f m in %.3f s"
                         % (i + 1, gpx_data[i].get("speed_kmh", 0.0),
                            gpx_data[i].get("delta_m", 0.0),
                            naht_glaetten._dt(gpx_data, i))
                         for i in spitzen]
            text, ok = QInputDialog.getItem(
                self, "Speed spikes found",
                "The selected row is not a speed spike.\n"
                "These were found in the track - pick one:",
                eintraege, 0, False)
            if not ok or text not in eintraege:
                return
            row = spitzen[eintraege.index(text)]
            mw.gpx_widget.gpx_list.select_row_in_pause(row)

        try:
            vorschlag = naht_glaetten.vorschlagen(gpx_data, row)
        except naht_glaetten.NahtFehler as exc:
            QMessageBox.warning(self, "Fix speed spike", str(exc))
            return

        dlg = NahtDialog(gpx_data, vorschlag, self)
        if dlg.exec() != QDialog.Accepted or dlg.vorschlag is None:
            return
        v = dlg.vorschlag

        self.register_gpx_undo_snapshot(self._schritt("Fix speed spike", v.idx))
        naht_s = naht_glaetten.anwenden(gpx_data, v)
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
        if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
            mw.cut_manager.on_markClear_clicked()
        mw.gpx_widget.gpx_list.select_row_in_pause(v.idx)

        print("[NAHT] Zeile %d: %.1f m, %.0f -> %.1f km/h; Naht %.3f s, "
              "%d + %d Punkte, Schritte durch %.3f (1 s -> %.3f s)"
              % (v.idx + 1, v.dm, v.v_spitze, gpx_data[v.idx].get("speed_kmh", 0.0),
                 naht_s, v.davor, v.danach, v.faktor, v.schritt))
        QMessageBox.information(
            self, "Speed spike fixed",
            "Row %d now has %.1f km/h (was %.0f km/h).\n"
            "%d points before and %d after run %.0f %% faster, in their "
            "real proportions. Points after the range kept their times."
            % (v.idx + 1, gpx_data[v.idx].get("speed_kmh", 0.0), v.v_spitze,
               v.davor, v.danach, (v.faktor - 1.0) * 100.0))

    # ------------------------------------------------------------------
    # Kamera war aus: GPX ab B so weit kuerzen, dass E auf die Videozeit faellt
    # ------------------------------------------------------------------
    @staticmethod
    def gpx_ab_punkt_kuerzen(gpx_data, b_idx, dauer_s):
        """Nimmt ab Punkt b_idx genau dauer_s Sekunden aus der Spur.

        Punkte mit Zeit in (t_B, t_B + dauer_s] fallen weg, alle danach
        ruecken um dauer_s vor; Punkt b_idx selbst bleibt und wird die Naht.
        Ein Punkt genau auf t_B + dauer_s faellt mit weg, er laege sonst nach
        dem Vorruecken zeitgleich auf B. Rueckgabe: Anzahl entfernter Punkte.
        Ohne Qt, damit es sich ohne Fenster nachrechnen laesst.
        """
        t_b = gpx_data[b_idx]["time"]
        ende = t_b + timedelta(seconds=dauer_s)
        k = b_idx + 1
        while k < len(gpx_data) and gpx_data[k]["time"] <= ende:
            k += 1
        entfernt = k - (b_idx + 1)
        del gpx_data[b_idx + 1:k]
        d = timedelta(seconds=dauer_s)
        for pt in gpx_data[b_idx + 1:]:
            pt["time"] = pt["time"] - d
        return entfernt

    def on_cut_gpx_to_video_clicked(self):
        """Menue '...' -> 'Cut GPX to video (B..E)'.

        Lage: an einer Merge-Kante war die Kamera aus, die GPX lief weiter.
        Der Video-Cut hat nur die Sekunden um die Kante aus der GPX genommen,
        die Aus-Zeit steckt noch drin, ab der Naht laeuft die GPX dem Video
        davon. Ablauf: MarkB auf die Naht (Rechtsklick [- nach dem Cut),
        im Video zu einem markanten Punkt fahren, dessen GPX-Punkt als MarkE
        markieren, dann dieser Eintrag. Er rechnet Tabellenzeit von E minus
        aktuelle Videozeit = Aus-Zeit der Kamera und nimmt genau so viel
        GPX-Zeit ab B heraus. Danach steht E auf der Videozeit, alles
        dahinter ist wieder synchron. An der Naht bleibt der Sprung in der
        Strecke - dafuer danach Rechtsklick [- / -] und Fix speed spike.
        Nur bei V&G Off: mit V&G On setzen die Video-Buttons den GPX-Punkt
        immer auf die Videozeit, nicht auf den gewaehlten Punkt.
        """
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data if mw else None
        if not gpx_data or len(gpx_data) < 3:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return
        if getattr(mw, "_autoSyncVideoEnabled", False):
            QMessageBox.warning(self, "Cut GPX to video",
                                "Switch V&G off first: markB and markE must be GPX points, "
                                "not video times.")
            return
        if not getattr(mw, "playlist_counter", 0):
            QMessageBox.warning(self, "Cut GPX to video", "No video loaded.")
            return

        gl = mw.gpx_widget.gpx_list
        b_idx, e_idx = gl._markB_idx, gl._markE_idx
        if b_idx is None or e_idx is None:
            QMessageBox.warning(
                self, "Cut GPX to video",
                "Please mark the seam with markB and the GPX point where the "
                "video now stands with markE.")
            return
        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx
        if e_idx - b_idx < 2:
            QMessageBox.warning(self, "Cut GPX to video",
                                "There must be at least one point between markB and markE.")
            return

        fmt = gl._format_hhmmss_milli
        # Tabellenzeit von E = Zeit im geschnittenen Video, auf der E heute
        # liegt. Die Videozeit ebenso im geschnittenen Video (final).
        e_tabelle_s = gl._gpx_times[e_idx]
        video_s = mw.get_final_time_for_global(mw.video_editor.get_current_position_s())
        dauer_s = e_tabelle_s - video_s
        if dauer_s <= 0.0005:
            QMessageBox.warning(
                self, "Cut GPX to video",
                f"GPX point {e_idx} is at {fmt(e_tabelle_s)}, the video at {fmt(video_s)}.\n"
                "The point is not later than the video, there is nothing to cut.")
            return
        abstand_s = (gpx_data[e_idx]["time"] - gpx_data[b_idx]["time"]).total_seconds()
        if abstand_s <= dauer_s:
            QMessageBox.warning(
                self, "Cut GPX to video",
                f"{dauer_s:.3f} s would have to go, but markB and markE are only "
                f"{abstand_s:.3f} s apart. The cut would reach markE itself.\n"
                "Move markE further along the track, or check the video position.")
            return

        reply = QMessageBox.question(
            self, "Cut GPX to video",
            f"Video is at {fmt(video_s)}, GPX point {e_idx} at {fmt(e_tabelle_s)}.\n\n"
            f"Cut {dauer_s:.3f} s of GPX after point {b_idx} so that point {e_idx} "
            "lands on the video time? Everything after the cut moves up by that time.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self.register_gpx_undo_snapshot(self._schritt("Cut GPX to video", b_idx, e_idx))
        n = self.gpx_ab_punkt_kuerzen(gpx_data, b_idx, dauer_s)
        e_neu = e_idx - n
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        gl.clear_marked_range()
        mw.map_widget.clear_marked_range()
        # Die Naht als Luecke merken: Rechtsklick [- / -] markiert B und den
        # nachgerueckten Punkt fuer Fix speed spike.
        gl.luecke_merken(b_idx + 1)
        gl.select_row_in_pause(e_neu)

        print(f"[CUT2VIDEO] {n} Punkte nach Zeile {b_idx} entfernt, {dauer_s:.3f} s; "
              f"Zeile {e_idx} -> {e_neu} jetzt bei {fmt(gl._gpx_times[e_neu])}, "
              f"Video bei {fmt(video_s)}")
        QMessageBox.information(
            self, "Cut GPX to video",
            f"{n} point(s) removed after row {b_idx}, {dauer_s:.3f} s.\n"
            f"Row {e_neu} (was {e_idx}) is now at {fmt(gl._gpx_times[e_neu])}, "
            f"the video at {fmt(video_s)}.\n\n"
            "The seam keeps the distance ridden while the camera was off: "
            "right-click [- and -], then 'Fix speed spike (cut seam)'.")

    # ------------------------------------------------------------------
    # Hoehenprofil B..E von Hand nachbauen (Galerie, Viadukt, Tunnel)
    # ------------------------------------------------------------------
    def on_height_profile_clicked(self):
        """Menue '...' -> 'Height profile editor (B..E)...'.

        Oeffnet das Fenster aus widgets/hoehenprofil_editor.py, nicht
        blockierend. Uebernommen wird erst bei Apply, ueber _profil_uebernehmen.
        """
        from widgets.hoehenprofil_editor import HoehenprofilEditor

        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data if mw else None
        if not gpx_data or len(gpx_data) < 3:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return
        gl = mw.gpx_widget.gpx_list
        b_idx, e_idx = gl._markB_idx, gl._markE_idx
        if b_idx is None or e_idx is None:
            QMessageBox.warning(self, "Height profile editor",
                                "Please mark the section with markB and markE. Both must "
                                "have a trustworthy height.")
            return
        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx
        if e_idx - b_idx < 2:
            QMessageBox.warning(self, "Height profile editor",
                                "There must be at least one point between markB and markE.")
            return
        if self._profil_editor is not None:
            self._profil_editor.raise_()
            self._profil_editor.activateWindow()
            return

        def aktuelle_zeile():
            if not getattr(mw, "playlist_counter", 0) or not is_gpx_video_shift_set():
                return None
            final_s = mw.get_final_time_for_global(mw.video_editor.get_current_position_s())
            return mw.gpx_widget.get_closest_index_for_time(final_s)

        def springen(zeile):
            if getattr(mw, "playlist_counter", 0) and is_gpx_video_shift_set():
                gl.select_row_in_pause(zeile)
                mw.on_map_sync_any(zeile)

        n_vorher = len(gpx_data)
        dlg = HoehenprofilEditor(gpx_data, b_idx, e_idx, parent=self,
                                 aktuelle_zeile=aktuelle_zeile, springen=springen)
        dlg.uebernehmen.connect(
            lambda hoehen: self._profil_uebernehmen(b_idx, e_idx, n_vorher, hoehen))
        dlg.finished.connect(lambda _ergebnis: setattr(self, "_profil_editor", None))
        self._profil_editor = dlg
        dlg.show()

    def _profil_uebernehmen(self, b_idx, e_idx, n_vorher, hoehen):
        """Apply im Profil-Editor: nur Hoehen der Punkte b..e, ein Undo-Schritt."""
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        # Das Fenster stand offen; hat sich die Spur inzwischen veraendert,
        # passen die Zeilen nicht mehr.
        if len(gpx_data) != n_vorher or len(hoehen) != e_idx - b_idx + 1:
            QMessageBox.warning(self, "Height profile editor",
                                "The track changed while the editor was open. Nothing applied.")
            return
        self.register_gpx_undo_snapshot(self._schritt("Height profile", b_idx, e_idx))
        for i, h in enumerate(hoehen):
            gpx_data[b_idx + i]["ele"] = float(h)
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
        mw.gpx_widget.gpx_list.select_row_in_pause(b_idx)
        print(f"[PROFIL] Hoehen {b_idx}..{e_idx} uebernommen")

    def on_show_average_speed_info(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        if not gpx_data or b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range", "Please mark a GPX range (B..E) first.")
            return

        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx

        t_start = gpx_data[b_idx]["time"]
        t_end = gpx_data[e_idx]["time"]
        total_s = (t_end - t_start).total_seconds()
        if total_s <= 0:
            QMessageBox.warning(self, "Invalid Time",
                f"Time in the range {b_idx}..{e_idx} is zero or reversed.")
            return

        total_dist_m = 0.0
        for i in range(b_idx, e_idx):
            lat1 = gpx_data[i]["lat"]
            lon1 = gpx_data[i]["lon"]
            lat2 = gpx_data[i+1]["lat"]
            lon2 = gpx_data[i+1]["lon"]
            total_dist_m += self._haversine_m(lat1, lon1, lat2, lon2)

        if total_dist_m < 0.001:
            QMessageBox.information(self, "Zero Distance", "This range has almost no distance.")
            return

        dist_km = total_dist_m / 1000.0
        time_h = total_s / 3600.0
        avg_speed_kmh = dist_km / time_h

        QMessageBox.information(
            self, "Average Speed Info",
            f"Range {b_idx}..{e_idx}\n"
            f"Distance: {dist_km:.3f} km\n"
            f"Time: {total_s:.1f} s\n\n"
            f"Average Speed: {avg_speed_kmh:.2f} km/h"
        )

    
    
    def _haversine_m(self, lat1, lon1, lat2, lon2):
        """
        Evtl. Hilfsfunktion, 
        distance in Meter
        """
        
        R = 6371000
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat/2)**2 
            + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))
            * math.sin(d_lon/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R*c
        
        
    def on_max_speed_clicked(self):
        mw = self._mainwindow
        """
        Called when the user selects 'MaxSpeed' in the More-Menu.
        We find the GPX point with the highest speed_kmh, 
        then highlight and center that point in map, table, and chart.
        """
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return  # or show a warning

        # Liste der Geschwindigkeiten
        speeds = [pt.get("speed_kmh", 0.0) for pt in gpx_data]
        max_val = max(speeds)
        idx_max = speeds.index(max_val)

        # "Springen" => Map, Chart, Table
        mw._go_to_gpx_index(idx_max)    
        
    def on_min_speed_clicked(self):
        mw = self._mainwindow
        """
        Called when the user selects 'MinSpeed' in the More-Menu.
        We find the GPX point (except the very first point index=0)
        with the lowest speed_kmh, then highlight and center that point
        in map, table, and chart.
        """
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return
        if len(gpx_data) < 2:
            # Kein "echter" Punkt außer Index 0
            return

        # Erstelle eine Liste (speed, index), beginnend ab Index 1
        # => so wird der erste Punkt (Index 0) ausgeschlossen.
        spd_idx_pairs = [
            (pt.get("speed_kmh", 0.0), i)
            for i, pt in enumerate(gpx_data)
            if i > 0  # ab Index 1
        ]
        if not spd_idx_pairs:
            return

        # min(...) mit key=lambda x: x[0] => vergleicht speed
        min_speed, idx_min = min(spd_idx_pairs, key=lambda x: x[0])

        mw._go_to_gpx_index(idx_min)




    def on_smooth_clicked(self):
        mw = self._mainwindow
        """
        Wird aufgerufen, wenn im GPXControlWidget der 'Smooth' Button gedrückt wird.
        - Öffnet einen Dialog mit 2 Parametern: Box_Smoothing (default=10), Flatten_Value (default=2)
        - Bei OK => core.hoehen_glaetten.glaetten() fuer B..E oder die ganze Spur
        - Schreibt Undo-History, damit man zurück kann
        """
        
        from core import hoehen_glaetten as hg

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data or len(gpx_data) < 3:
            QMessageBox.warning(self, "No GPX", "No GPX data available for smoothing!")
            return
        n = len(gpx_data)

        # Bereich: B..E wenn markiert, sonst die ganze Spur - und das steht
        # im Dialog, bisher stand es nirgends.
        gl = mw.gpx_widget.gpx_list
        b, e = gl._markB_idx, gl._markE_idx
        bereich = b is not None and e is not None and abs(e - b) >= 2
        if bereich:
            b, e = min(b, e), max(b, e)
        else:
            b, e = 0, n - 1

        # Der Stand vom letzten Smooth: nochmal ueber dasselbe flacht weiter
        # ab, und wurden seither nur einige Zeilen geaendert (Profil-Editor,
        # chEle), sind die der eigentliche Kandidat.
        stand = self._glaettung
        art, za, zz = hg.geaenderte_zeilen(stand, gpx_data)
        if art == "gleich":
            antwort = QMessageBox.warning(
                self, "Already smoothed",
                f"This track was already smoothed at {stand.wann()} with Box {stand.box}, "
                f"Flatten {stand.flatten:.2f}: the climb went from {stand.anstieg_vorher:.0f} m "
                f"to {stand.anstieg_nachher:.0f} m.\nSmoothing again flattens it further.\n\n"
                "Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if antwort != QMessageBox.Yes:
                return
        elif art == "geaendert" and not bereich:
            frage = QMessageBox(self)
            frage.setIcon(QMessageBox.Question)
            frage.setWindowTitle("Heights changed since the last smooth")
            frage.setText(
                f"Since the last smooth at {stand.wann()} the heights changed in rows "
                f"{za}..{zz} only.\nSmooth only that range, or the whole track again? "
                "The whole track was already smoothed once; doing it again flattens it further.")
            knopf_nur = frage.addButton(f"Only rows {za}..{zz}", QMessageBox.AcceptRole)
            knopf_ganz = frage.addButton("Whole track", QMessageBox.ActionRole)
            frage.addButton(QMessageBox.Cancel)
            frage.setDefaultButton(knopf_nur)
            frage.exec()
            if frage.clickedButton() is knopf_nur:
                # mindestens ein Punkt dazwischen, sonst gibt es nichts zu mitteln
                b, e = max(0, min(za, zz - 2)), min(n - 1, max(zz, za + 2))
                bereich = True
            elif frage.clickedButton() is not knopf_ganz:
                return

        # 1) Dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("GPX Smoothing Parameters")
        vbox = QVBoxLayout(dlg)

        if bereich:
            wo = f"Rows {b}..{e} only ({e - b + 1} points). Heights of B and E stay."
        else:
            wo = f"No range marked: the WHOLE track ({n} points) will be smoothed."
        lbl_wo = QLabel(wo)
        lbl_wo.setStyleSheet("font-weight: bold;")
        vbox.addWidget(lbl_wo)

        lbl_info = QLabel(
            "Apply Slope Box Smoothing + Flatten Value\n\n"
            "Box_Smoothing: Average slope over +/- N points\n"
            "Flatten_Value: Max slope change between adjacent points\n"
            "Default: Box_Smoothing=10, Flatten_Value=2"
        )
        vbox.addWidget(lbl_info)

        # Box Smoothing
        row_box = QHBoxLayout()
        lbl_box = QLabel("Box_Smoothing:")
        spin_box = QDoubleSpinBox()
        spin_box.setRange(1.0, 9999.0)  # z. B. 1..9999
        spin_box.setDecimals(0)        # als ganze Zahl?
        spin_box.setValue(10.0)        # Standard=10
        row_box.addWidget(lbl_box)
        row_box.addWidget(spin_box)
        vbox.addLayout(row_box)
    
        # Flatten Value
        row_flat = QHBoxLayout()
        lbl_flat = QLabel("Flatten_Value:")
        spin_flat = QDoubleSpinBox()
        spin_flat.setRange(0.0, 50.0)
        spin_flat.setDecimals(2)
        spin_flat.setValue(2.0)  # Default=2
        row_flat.addWidget(lbl_flat)
        row_flat.addWidget(spin_flat)
        vbox.addLayout(row_flat)
    
        # Buttons OK/Cancel
        h_btns = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        h_btns.addWidget(btn_ok)
        h_btns.addWidget(btn_cancel)
        vbox.addLayout(h_btns)
    
        def on_ok():
            dlg.accept()
        def on_cancel():
            dlg.reject()
        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(on_cancel)
    
        if not dlg.exec():
            return  # abgebrochen
    
        # Gelesene Werte
        box_smoothing = int(spin_box.value())      # ggf. Ganzzahl
        flatten_val   = spin_flat.value()
    
        # 2) Undo => Kopie
        if bereich:
            self.register_gpx_undo_snapshot(self._schritt("Smooth", b, e))
        else:
            self.register_gpx_undo_snapshot("Smooth (whole track)")

        # 3) => smoothing, Rechnung in core/hoehen_glaetten.py
        vorher = hg.anstieg(gpx_data)
        hoehen = hg.glaetten(gpx_data, b, e, box_smoothing, flatten_val)
        for i, h in enumerate(hoehen):
            gpx_data[b + i]["ele"] = h

        # 4) => Neu set + recalc
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        if bereich:
            gl.clear_marked_range()
            mw.map_widget.clear_marked_range()

        nachher = hg.anstieg(gpx_data)
        self._glaettung = hg.Stand([float(p.get("ele", 0.0)) for p in gpx_data],
                                   box_smoothing, flatten_val, b, e, vorher, nachher)
        print(f"[SMOOTH] {'Zeilen %d..%d' % (b, e) if bereich else 'ganze Spur'}, "
              f"Box {box_smoothing}, Flatten {flatten_val:.2f}, Anstieg {vorher:.1f} -> {nachher:.1f} m")
        QMessageBox.information(
            self, "Smooth done",
            (f"Smoothed rows {b}..{e}" if bereich else f"Smoothed the whole track ({n} points)")
            + f" with Box={box_smoothing}, Flatten={flatten_val:.2f}.\n"
            f"Climb of the track: {vorher:.0f} m before, {nachher:.0f} m after.")

    def glaettung_als_dict(self):
        """Fuer die Projektdatei: Zusammenfassung des letzten Smooth, ohne Hoehen."""
        return self._glaettung.als_dict() if self._glaettung is not None else None

    def glaettung_aus_dict(self, d):
        """Aus der Projektdatei. Ohne Hoehen: die Warnung 'already smoothed'
        gibt es dann, die geaenderten Zeilen nicht."""
        from core import hoehen_glaetten as hg
        self._glaettung = hg.Stand.aus_dict(d)    
        
    # Die Glaettung selbst steht seit 6.11 in core/hoehen_glaetten.py.

    # ===========  NEU am Ende von mainwindow.py ============    
    
    
    
    def on_chEle_clicked(self):
        mw = self._mainwindow
        """
        Wird aufgerufen, wenn der Button 'chEle' im GPXControlWidget gedrückt wird.
        Erweiterung:
        - Falls (markB..markE) existieren und mehr als 1 Punkt umfasst sind,
            öffnet einen Dialog für einen Elevation-Offset (z.B. +1.25m => +1.25).
        - Sonst (kein B..E oder nur 1 Zeile) => alter Single-Point-Dialog.
        """
       
        

        # Referenz auf die GPX-Daten
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX", "No GPX data available.")
            return

        # (A) Prüfe, ob ein Bereich (B..E) vorliegt und mehr als 1 Punkt abdeckt
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        valid_range = False
        if b_idx is not None and e_idx is not None:
            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx  # tauschen
            if 0 <= b_idx < len(gpx_data) and 0 <= e_idx < len(gpx_data) and (e_idx - b_idx) >= 1:
                valid_range = True
    
        if valid_range:
            # -----------------------------------------------
            # (1) Dialog -> "Offset für B..E"
            # -----------------------------------------------
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Offset Elevation for Area {b_idx}..{e_idx}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                "Increase/decrease the elevation of all marked points.\n"
                "For example: +1.25 => +1.25 Meter\n"
                "          -2.00 => -2.00 Meter\n"
            )
            vbox.addWidget(lbl_info)
    
            # SpinBox für Offset
            spin_offset = QDoubleSpinBox()
            spin_offset.setRange(-9999.0, 9999.0)
            spin_offset.setDecimals(2)      # cm-Schritte
            spin_offset.setSingleStep(0.01) # 1 cm
            spin_offset.setValue(0.0)
            vbox.addWidget(spin_offset)
    
            # OK/Cancel
            h_btns = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            h_btns.addWidget(btn_ok)
            h_btns.addWidget(btn_cancel)
            vbox.addLayout(h_btns)
    
            def on_ok():
                dlg.accept()
    
            def on_cancel():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok)
            btn_cancel.clicked.connect(on_cancel)
    
            if not dlg.exec():
                return  # abgebrochen
    
            offset_val = spin_offset.value()
            if abs(offset_val) < 1e-9:
                QMessageBox.information(self, "No change", "Offset=0 => no change.")
                return
    
            # => Undo-Snapshot
            self.register_gpx_undo_snapshot(self._schritt("chEle", b_idx, e_idx))
            
            # => wende offset an: gpx_data[b_idx..e_idx]
            for i in range(b_idx, e_idx + 1):
                old_ele = gpx_data[i].get("ele", 0.0)
                gpx_data[i]["ele"] = old_ele + offset_val
    
            # => recalc
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            
            mw._update_gpx_overview()
    
            # => Chart, Map, MiniChart
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
            route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)
            
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            
            ### nur range in editor llschen wenn autocut is enabled
            if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                mw.cut_manager.on_markClear_clicked()    
            
    
            QMessageBox.information(
                self, "Done",
                f"Elevation of all Points in {b_idx}..{e_idx} chamged by {offset_val:+.2f} m."
            )
            
                
            
            #mw.cut_manager.on_markClear_clicked()   # auch den video editor restetten       
    
        else:
            # -----------------------------------------------
            # (2) Einzel-Punkt-Dialog (alte Logik)
            # -----------------------------------------------
            row = mw.gpx_widget.gpx_list.table.currentRow()
            if row < 0:
                QMessageBox.warning(self, "No selection", "Please select a GPX point.")
                return
    
            if row >= len(gpx_data):
                return
    
            old_ele = gpx_data[row].get("ele", 0.0)
    
            # Undo
            self.register_gpx_undo_snapshot(self._schritt("chEle", row))
    
            # Dialog => neue absolute Höhe
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Elevation – Point {row}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                f"Current elevation: {old_ele:.2f} m\n"
                f"Please enter new absolute value:"
            )
            vbox.addWidget(lbl_info)
    
            spin_ele = QDoubleSpinBox()
            spin_ele.setRange(-500.0, 9000.0)  # z. B. +9k m, -500 m
            spin_ele.setDecimals(2)
            spin_ele.setSingleStep(0.01)
            spin_ele.setValue(old_ele)
            vbox.addWidget(spin_ele)
    
            hbox_btn = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            hbox_btn.addWidget(btn_ok)
            hbox_btn.addWidget(btn_cancel)
            vbox.addLayout(hbox_btn)
    
            def on_ok_single():
                dlg.accept()
    
            def on_cancel_single():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok_single)
            btn_cancel.clicked.connect(on_cancel_single)
    
            if not dlg.exec():
                return  # abgebrochen
    
            new_ele = spin_ele.value()
            if abs(new_ele - old_ele) < 1e-9:
                QMessageBox.information(self, "No change", "Elevation unchanged.")
                return
    
            # -> setze
            gpx_data[row]["ele"] = new_ele
    
            # -> partial recalc (oder full recalc)
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            
            mw._update_gpx_overview()
            
            
            # -> Chart, Map
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
            route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)
            
            
            if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                mw.cut_manager.on_markClear_clicked()    
                
            QMessageBox.information(
                self, "Done",
                f"Elevation of Point {row} changed to {new_ele:.2f} m."
            )
            
            
    #################################################################    
    
    def on_chTime_clicked_gpx(self):
        mw = self._mainwindow

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        valid_range = False
        if b_idx is not None and e_idx is not None:
            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx
            if 0 <= b_idx < n and 0 <= e_idx < n and (e_idx - b_idx) >= 1:
                valid_range = True

        # --- CASE A: Einzelpunkt ---
        if not valid_range:
            row = mw.gpx_widget.gpx_list.table.currentRow()
    
            if row < 0 or row >= n:
                QMessageBox.warning(self, "Invalid Selection", "Please select a valid GPX point.")
                return
            ######
            if row == 0:
                # --- Neuer Sonderfall: GPX[0] erlaubt negativen Delta ---
                self.register_gpx_undo_snapshot(self._schritt("chT", row))

                t0 = gpx_data[0].get("time", None)
                t1 = gpx_data[1].get("time", None)
                if not t0 or not t1:
                    QMessageBox.warning(self, "Missing Time", "First or second point has no time.")
                    return

                old_diff = (t1 - t0).total_seconds()
                dlg = QDialog(self)
                dlg.setWindowTitle("Shift Time: GPX[0]")
                vbox = QVBoxLayout(dlg)

                lbl = QLabel(
                    f"You are changing the time distance between GPX[0] and GPX[1].\n"
                    f"Current difference: {old_diff:.3f} s\n\n"
                    "Enter a **negative** shift (e.g. -10.0) to delay all points after GPX[0]:"
                )
                vbox.addWidget(lbl)
    
                spin = QDoubleSpinBox()
                spin.setRange(-99999.0, -0.001)
                spin.setDecimals(3)
                spin.setSingleStep(0.001)
                spin.setValue(-1.0)
                vbox.addWidget(spin)

                btns = QHBoxLayout()
                ok = QPushButton("OK")
                cancel = QPushButton("Cancel")
                btns.addWidget(ok)
                btns.addWidget(cancel)
                vbox.addLayout(btns)

                ok.clicked.connect(dlg.accept)
                cancel.clicked.connect(dlg.reject)

                if not dlg.exec():
                    return

                shift_val = spin.value()  # z. B. -10.0

                # Alle Punkte ab Index 1 verschieben um +abs(shift_val)
                for j in range(1, n):
                    gpx_data[j]["time"] += timedelta(seconds=abs(shift_val))

                recalc_gpx_data(gpx_data)
                mw.gpx_widget.set_gpx_data(gpx_data)
                mw._gpx_data = gpx_data
                mw._update_gpx_overview()
                mw.chart.set_gpx_data(gpx_data)
                if mw.mini_chart_widget:
                    mw.mini_chart_widget.set_gpx_data(gpx_data)
    
    
                if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                    mw.cut_manager.on_markClear_clicked()       
                    
                QMessageBox.information(
                    self, "Done",
                    f"All GPX points after index 0 have been shifted by {abs(shift_val):.3f} seconds."
                )   
                
                

            ###
            
            # --- Normalfall (row >= 1) ---
            if row < 1:
                QMessageBox.warning(self, "Invalid Selection",
                    "Please select a GPX point (row >= 1). The first point (row=0) has no predecessor.")
                return

            self.register_gpx_undo_snapshot(self._schritt("chT", row))
    
            t_prev = gpx_data[row - 1].get("time", None)
            t_curr = gpx_data[row].get("time", None)
            if not t_prev or not t_curr:
                QMessageBox.warning(self, "Missing Time",
                    f"Point {row-1} or {row} has no 'time' set.")
                return
    
            old_diff_s = (t_curr - t_prev).total_seconds()
            if old_diff_s < 0:
                QMessageBox.warning(self, "Unsorted Track", "time[row] < time[row-1]? The track seems unsorted.")
                return
    
            dlg = QDialog(self)
            dlg.setWindowTitle("Change Step - Single Point")
            vbox = QVBoxLayout(dlg)
    
            info_lbl = QLabel(
                f"Current step = {old_diff_s:.3f} seconds.\n"
                "Please enter a new step (>= 0.001)."
            )
            vbox.addWidget(info_lbl)
    
            spin_new_step = QDoubleSpinBox()
            spin_new_step.setRange(0.001, 999999.0)
            spin_new_step.setValue(old_diff_s)
            spin_new_step.setDecimals(3)
            spin_new_step.setSingleStep(0.001)
            vbox.addWidget(spin_new_step)
    
            btn_box = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            btn_box.addWidget(btn_ok)
            btn_box.addWidget(btn_cancel)
            vbox.addLayout(btn_box)
    
            def on_ok():
                new_val = spin_new_step.value()
                if new_val < 0.001:
                    QMessageBox.warning(dlg, "Invalid Value", "New step cannot be < 0.001!")
                    return
                dlg.accept()
    
            def on_cancel():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok)
            btn_cancel.clicked.connect(on_cancel)
    
            if not dlg.exec():
                return
    
            new_step_s = spin_new_step.value()
            delta_s = new_step_s - old_diff_s
    
            for j in range(row, n):
                t_old = gpx_data[j]["time"]
                gpx_data[j]["time"] = t_old + timedelta(seconds=delta_s)
    
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
                
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            
            if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                mw.cut_manager.on_markClear_clicked()
                
    
            QMessageBox.information(
                self, "Done",
                f"Row {row} step changed by {delta_s:+.3f} s.\n"
                "All subsequent points shifted accordingly."
            )
            
    
        # --- CASE B: Range B..E ---
        else:
            self.register_gpx_undo_snapshot(self._schritt("chT", b_idx, e_idx))
    
            t_start = gpx_data[b_idx]["time"]
            t_end   = gpx_data[e_idx]["time"]
            old_total_s = (t_end - t_start).total_seconds()
            if old_total_s < 0:
                QMessageBox.warning(self, "Unsorted Track", "Time in the selected range is reversed? (unsorted data)")
                return
    
            seg_count = e_idx - b_idx
    
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Step - Range {b_idx}..{e_idx}")
            vbox = QVBoxLayout(dlg)
    
            info_text = (
                f"You have selected a range from index {b_idx} to {e_idx}.\n"
                f"This corresponds to {seg_count} segments.\n\n"
                f"Current total duration in this range: {old_total_s:.3f} s\n"
                "Please enter a new step (in seconds) for each segment."
            )
            lbl_info = QLabel(info_text)
            vbox.addWidget(lbl_info)
    
            spin_range_step = QDoubleSpinBox()
            spin_range_step.setRange(0.001, 999999.0)
            if seg_count > 0:
                spin_range_step.setValue(old_total_s / seg_count)
            else:
                spin_range_step.setValue(1.0)
            spin_range_step.setDecimals(3)
            spin_range_step.setSingleStep(0.001)
            vbox.addWidget(spin_range_step)
    
            btn_box = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            btn_box.addWidget(btn_ok)
            btn_box.addWidget(btn_cancel)
            vbox.addLayout(btn_box)
    
            def on_ok_range():
                new_val = spin_range_step.value()
                if new_val < 0.001:
                    QMessageBox.warning(dlg, "Invalid Value", "New step cannot be < 0.001!")
                    return
                dlg.accept()
    
            def on_cancel_range():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok_range)
            btn_cancel.clicked.connect(on_cancel_range)
    
            if not dlg.exec():
                return
    
            new_step_s = spin_range_step.value()
            new_total_s = seg_count * new_step_s
            diff_s = new_total_s - old_total_s
    
            for i in range(b_idx + 1, e_idx + 1):
                offset_s = (i - b_idx) * new_step_s
                gpx_data[i]["time"] = t_start + timedelta(seconds=offset_s)
    
            if e_idx < n - 1 and abs(diff_s) > 1e-9:
                for j in range(e_idx + 1, n):
                    gpx_data[j]["time"] += timedelta(seconds=diff_s)
    
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
                
                
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            ### nur range in editor llschen wenn autocut is enabled
            
            if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                mw.cut_manager.on_markClear_clicked()
    
            QMessageBox.information(
                self, "Done",
                f"All segments in the range {b_idx}..{e_idx} have been set to {new_step_s:.3f} s.\n"
                f"Old duration was {old_total_s:.3f} s, new duration is {new_total_s:.3f} s.\n"
                f"Subsequent points have been shifted by {diff_s:+.3f} s."
            )
            
    
        
        
    
    
    #################################################################
    def on_chPercent_clicked(self):
        
        mw = self._mainwindow
        """
        Called when the user clicks the 'ch%' button.
        - If no valid range is selected (or only 1 point in that range),
        it changes the slope for a single point (row) relative to row-1.
        - If a valid range [markB..markE] with >=2 points is selected,
        it applies one consistent slope across that entire range,
        and shifts subsequent points accordingly.
        All user-facing texts are in English.
        """
        
        
    
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return
    
        n = len(gpx_data)
        if n < 2:
            QMessageBox.warning(self, "Too few points", "At least 2 GPX points are required.")
            return

        # --- Check if we have a valid markB..markE range ---
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
    
        valid_range = False
        if b_idx is not None and e_idx is not None:
            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx
            if 0 <= b_idx < n and 0 <= e_idx < n and (e_idx - b_idx) >= 1:
                valid_range = True

        # ------------------------------------------------------------------
        # CASE A) No valid range => single-point slope change
        # ------------------------------------------------------------------
        if not valid_range:
            row = mw.gpx_widget.gpx_list.table.currentRow()
            if row < 1:
                QMessageBox.warning(self, "Invalid Selection",
                    "Please select a point with row >= 1.\n"
                    "Cannot compute slope for the very first point (row=0).")
                return
            if row >= n:
                return

            # => Undo
            self.register_gpx_undo_snapshot(self._schritt("ch%", row))
    
            # lat/lon/ele for row-1 and row
            lat1, lon1, ele1 = (
                gpx_data[row-1].get("lat", 0.0),
                gpx_data[row-1].get("lon", 0.0),
                gpx_data[row-1].get("ele", 0.0)
            )
            lat2, lon2, ele2 = (
                gpx_data[row].get("lat", 0.0),
                gpx_data[row].get("lon", 0.0),
                gpx_data[row].get("ele", 0.0)
            )
    
            # Dist2D => we can reuse a small helper or do a direct haversine:
            dist_2d = self._haversine_m(lat1, lon1, lat2, lon2)
            if dist_2d < 0.01:
                QMessageBox.warning(self, "Zero Distance",
                    f"Points {row-1} and {row} have nearly no distance => slope undefined.")
                return
    
            old_slope = 100.0 * ((ele2 - ele1) / dist_2d)
    
            # Dialog => new slope
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Slope (Single Point) - Row {row}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                f"Current slope between row {row-1} and row {row}: {old_slope:.2f}%\n"
                "Please enter the new slope (in %)."
            )
            vbox.addWidget(lbl_info)
    
            spin_slope = QDoubleSpinBox()
            spin_slope.setRange(-200.0, 200.0)  # e.g. -200%.. 200%
            spin_slope.setDecimals(2)
            spin_slope.setSingleStep(0.01)
            spin_slope.setValue(old_slope)
            vbox.addWidget(spin_slope)
    
            h_btn = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            h_btn.addWidget(btn_ok)
            h_btn.addWidget(btn_cancel)
            vbox.addLayout(h_btn)
    
            def on_ok():
                dlg.accept()
    
            def on_cancel():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok)
            btn_cancel.clicked.connect(on_cancel)
    
            if not dlg.exec():
                return
    
            new_slope = spin_slope.value()
            if abs(new_slope - old_slope) < 1e-9:
                QMessageBox.information(self, "No change", "Slope unchanged.")
                return
    
            # => new ele2 = ele1 + dist_2d*(new_slope/100)
            new_ele2 = ele1 + dist_2d * (new_slope / 100.0)
            gpx_data[row]["ele"] = new_ele2
    
            # recalc
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
    
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
    
            # Map
            #route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            #mw.map_widget.loadRoute(route_geojson, do_fit=False)
            
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            
            ### nur range in editor llschen wenn autocut is enabled
            
            if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                mw.cut_manager.on_markClear_clicked()
                

            diff_val = new_slope - old_slope
            QMessageBox.information(
                self, "Done",
                f"Slope changed from {old_slope:.2f}% to {new_slope:.2f}%.\n"
                f"Elevation of row {row} updated accordingly."
            )
            return

        # ------------------------------------------------------------------
        # CASE B) Valid range => single linear slope for [b_idx..e_idx]
        # ------------------------------------------------------------------
        else:
            # => Undo
            self.register_gpx_undo_snapshot(self._schritt("ch%", b_idx, e_idx))
    
            lat_b, lon_b, ele_b = (
                gpx_data[b_idx].get("lat", 0.0),
                gpx_data[b_idx].get("lon", 0.0),
                gpx_data[b_idx].get("ele", 0.0)
            )
            lat_e, lon_e, ele_e = (
                gpx_data[e_idx].get("lat", 0.0),
                gpx_data[e_idx].get("lon", 0.0),
                gpx_data[e_idx].get("ele", 0.0)
            )
    
            # (1) Compute the total 2D distance from b_idx.. e_idx
            #     Summation of each segment's distance in [b_idx.. e_idx-1].
            total_2d = 0.0
            for i in range(b_idx, e_idx):
                la1, lo1 = gpx_data[i]["lat"], gpx_data[i]["lon"]
                la2, lo2 = gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
                dist_2d = self._haversine_m(la1, lo1, la2, lo2)
                total_2d += dist_2d
    
            if total_2d < 0.01:
                QMessageBox.warning(self, "Zero Distance",
                    f"The range {b_idx}..{e_idx} has almost no distance => slope undefined.")
                return
    
            # (2) old average slope
            old_dz = ele_e - ele_b
            old_slope = 100.0 * (old_dz / total_2d)
    
            # (3) Dialog => new slope
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Change Average Slope - Range {b_idx}..{e_idx}")
            vbox = QVBoxLayout(dlg)
    
            lbl_info = QLabel(
                f"You have selected a range from {b_idx} to {e_idx}.\n"
                f"Current average slope in this range: {old_slope:.2f}%\n\n"
                "Please enter the new slope in % (e.g., 5.0 means 5%)."
            )
            vbox.addWidget(lbl_info)
    
            spin_slope = QDoubleSpinBox()
            spin_slope.setRange(-200.0, 200.0)  # e.g. -200..+200%
            spin_slope.setDecimals(2)
            spin_slope.setSingleStep(0.01)
            spin_slope.setValue(old_slope)
            vbox.addWidget(spin_slope)
    
            h_btn = QHBoxLayout()
            btn_ok = QPushButton("OK")
            btn_cancel = QPushButton("Cancel")
            h_btn.addWidget(btn_ok)
            h_btn.addWidget(btn_cancel)
            vbox.addLayout(h_btn)
    
            def on_ok_range():
                dlg.accept()
    
            def on_cancel_range():
                dlg.reject()
    
            btn_ok.clicked.connect(on_ok_range)
            btn_cancel.clicked.connect(on_cancel_range)
    
            if not dlg.exec():
                return
    
            new_slope = spin_slope.value()
            if abs(new_slope - old_slope) < 1e-9:
                QMessageBox.information(self, "No change", "Slope unchanged.")
                return
    
            # (4) new total height difference => new_dz
            new_dz = total_2d * (new_slope / 100.0)
            shift_dz = new_dz - old_dz   # how much we add from e_idx onward
    
            # (5) Recompute elevations linearly from b_idx.. e_idx
            #     Keep ele[b_idx] as it is, 
            #     then for each i in [b_idx+1.. e_idx], 
            #     compute the cumulative distance from b_idx to i.
            def cumulative_distance(b_i, i_i):
                dist_sum = 0.0
                for x in range(b_i, i_i):
                    la1, lo1 = gpx_data[x]["lat"], gpx_data[x]["lon"]
                    la2, lo2 = gpx_data[x+1]["lat"], gpx_data[x+1]["lon"]
                    dist_sum += self._haversine_m(la1, lo1, la2, lo2)
                return dist_sum
    
            for i in range(b_idx+1, e_idx+1):
                dist_i = cumulative_distance(b_idx, i)
                # slope-based new altitude
                new_ele_i = ele_b + (new_slope / 100.0) * dist_i
                gpx_data[i]["ele"] = new_ele_i
    
            # (6) Shift all points after e_idx by shift_dz
            if e_idx < n-1 and abs(shift_dz) > 1e-9:
                for j in range(e_idx+1, n):
                    gpx_data[j]["ele"] = gpx_data[j]["ele"] + shift_dz
    
            # (7) recalc + update
            recalc_gpx_data(gpx_data)
            mw.gpx_widget.set_gpx_data(gpx_data)
            mw._gpx_data = gpx_data
            mw._update_gpx_overview()
    
            mw.chart.set_gpx_data(gpx_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(gpx_data)
    
            #route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
            #mw.map_widget.loadRoute(route_geojson, do_fit=False)
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            
            ### nur range in editor llschen wenn autocut is enabled
            
            if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
                mw.cut_manager.on_markClear_clicked()
                

            QMessageBox.information(
                self, "Done",
                f"Average slope in {b_idx}..{e_idx} changed from {old_slope:.2f}% to {new_slope:.2f}%.\n"
                f"Subsequent points have been shifted by {shift_dz:+.2f} m in elevation."
            )
           
    
    def on_close_gaps_clicked(self):
        mw = self._mainwindow
        if not mw:
            return

        # 1) GPX-Daten + markB..markE prüfen
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
        if b_idx is None or e_idx is None:
            QMessageBox.warning(self, "No Range Selected",
                "Please mark two consecutive points (markB..markE).")
            return

        if b_idx > e_idx:
            b_idx, e_idx = e_idx, b_idx

        # Prüfen, ob wirklich b_idx+1 == e_idx
        if e_idx != b_idx + 1:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Gap",
                "Close Gaps only works if exactly two consecutive points are selected.")
            return

        t1 = gpx_data[b_idx]["time"]
        t2 = gpx_data[e_idx]["time"]
        dt = (t2 - t1).total_seconds()
        if dt < 1.0:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Gap to Close",
                f"Time difference is only {dt:.2f}s (<1s). Nothing to insert.")
            return

        # 2) Check Directions-Flag
        if not mw._directions_enabled:
            # => Altes Verhalten
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            
        else:
            # => Directions=True => zeige Profil-Auswahl (QDialog)
            #    Dann rufe _close_gaps_mapbox(..., profile)
            #    Du kannst standard=cycling, optional=driving/walking
            prof, hoehen_holen = self._ask_profile_mode()
            if not prof:
                # Abbruch
                return

            # Rufe neue Methode
            self._close_gaps_mapbox(b_idx, e_idx, dt, prof, hoehen_holen)

    def _ask_profile_mode(self):
        """
        Zeigt einen kleinen Dialog mit RadioButtons:
        Bike (cycling), Car (driving), Foot (walking).
        Gibt (Profil, hoehen_holen) zurueck, oder (None, None) bei Cancel.

        hoehen_holen: der Haken "Get elevation from Mapbox" (seit 6.14). Ohne
        ihn bekommen die neuen Punkte die Hoehe linear von B nach E, wie bei
        Close Gaps ohne Directions - nur die Lage kommt von der Strasse. Die
        letzte Wahl wird gemerkt (QSettings "gpx/closegaps_elevation").
        """
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QCheckBox

        einstellungen = QSettings("KVRouite", "KVRouite")
        dlg = QDialog(self)
        dlg.setWindowTitle("Select Transport Mode")
        vbox = QVBoxLayout(dlg)

        lbl = QLabel("Directions: Please select a mode:")
        vbox.addWidget(lbl)

        group = QButtonGroup(dlg)
        rb_bike = QRadioButton("Bike (Default)")
        rb_car  = QRadioButton("Car")
        rb_walk = QRadioButton("Foot")
        rb_bike.setChecked(True)
        group.addButton(rb_bike)
        group.addButton(rb_car)
        group.addButton(rb_walk)

        vbox.addWidget(rb_bike)
        vbox.addWidget(rb_car)
        vbox.addWidget(rb_walk)

        cb_hoehen = QCheckBox("Get elevation from Mapbox", dlg)
        cb_hoehen.setChecked(
            einstellungen.value("gpx/closegaps_elevation", True, type=bool))
        cb_hoehen.setToolTip(
            "Checked: every new point gets its height from the Mapbox terrain "
            "tiles.\nUnchecked: the height runs in a straight line from the "
            "first to the last point, at one constant gradient - like Close "
            "Gaps without Directions, only along the road.")
        vbox.addWidget(cb_hoehen)

        hbtn = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        hbtn.addWidget(btn_ok)
        hbtn.addWidget(btn_cancel)
        vbox.addLayout(hbtn)

        def on_ok():
            dlg.accept()
        def on_cancel():
            dlg.reject()

        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(on_cancel)

        if not dlg.exec():
            return None, None  # abbruch

        hoehen_holen = bool(cb_hoehen.isChecked())
        einstellungen.setValue("gpx/closegaps_elevation", hoehen_holen)
        if rb_car.isChecked():
            return "driving", hoehen_holen
        elif rb_walk.isChecked():
            return "walking", hoehen_holen
        else:
            return "cycling", hoehen_holen
        
            
    
    def on_delete_way_errors_clicked(self):
        mw = self._mainwindow
        """
        Sucht alle aufeinanderfolgenden Duplikate in lat/lon,
        entfernt den zweiten Punkt und setzt einen neuen Interpolationspunkt
        zwischen 'ersten' und 'übernächsten' Punkt, um die Zeit
        wieder in zwei (annähernd) gleiche Schritte zu teilen.
        """
        #from PySide6.QtWidgets import QMessageBox
       

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 3:
            QMessageBox.information(self, "Not enough points",
                "At least 3 points are needed to fix Way Errors.")
            return

        # ---------------------------------------------
        # 1) Finde alle Paare (i, i+1) mit identischem lat/lon
        # ---------------------------------------------
        way_errors = []
        for i in range(len(gpx_data)-1):
            lat1, lon1 = gpx_data[i]["lat"], gpx_data[i]["lon"]
            lat2, lon2 = gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            # Wir prüfen "fast" identisch, z.B. |lat1-lat2|<1e-12
            if abs(lat1 - lat2) < 1e-12 and abs(lon1 - lon2) < 1e-12:
                way_errors.append(i)

        count_err = len(way_errors)
        if count_err == 0:
            QMessageBox.information(self, "No Way Errors",
                "No duplicate coordinates found.")
            return

        # ---------------------------------------------
        # 2) Nachfrage => "We found X errors. Fix them all?"
        # ---------------------------------------------
        answer = QMessageBox.question(
            self,
            "Delete Way Errors?",
            f"We found {count_err} Way Errors (duplicate lat/lon).\n"
            f"Should we fix them all?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        # ---------------------------------------------
        # 3) Undo-Snapshot
        # ---------------------------------------------
        self.register_gpx_undo_snapshot("Delete way errors")

        # ---------------------------------------------
        # 4) Fixen der Fehler - am besten in absteigender Index-Reihenfolge
        #
        #    Grund: Wenn wir i+1 entfernen, rückt i+2 -> i+1 usw.
        #           In absteigender Reihenfolge stören wir die
        #           kleineren Indizes nicht.
        # ---------------------------------------------
        way_errors.sort(reverse=True)

        for i in way_errors:
            if i >= len(gpx_data)-1:
                # Schon rausgeflogen oder am Ende -> skip
                continue

            # => i, i+1 haben identische lat/lon
            # => wir wollen i+1 löschen
            # => Dann haben wir Lücke => i.. i+2 (nach dem Löschen),
            #    wir teilen die Zeit. 
            # => ABER wir brauchen i+2 => check, ob i+2 existiert:
            if i+2 >= len(gpx_data):
                # wir können nicht vermitteln, da kein i+2
                # z.B. am Ende der Liste
                continue

            # (A) Hole Zeiten
            t_i   = gpx_data[i]["time"]
            t_ip2 = gpx_data[i+2]["time"]
            dt_total = (t_ip2 - t_i).total_seconds()
            if dt_total <= 0:
                # unsortiert => skip
                continue

            # (B) Hole Koordinaten i, i+2
            lat_i, lon_i, ele_i = (
                gpx_data[i]["lat"], gpx_data[i]["lon"], gpx_data[i]["ele"]
            )
            lat_ip2, lon_ip2, ele_ip2 = (
                gpx_data[i+2]["lat"], gpx_data[i+2]["lon"], gpx_data[i+2]["ele"]
            )

            # => Den zu entfernenden Punkt i+1
            # => wir schmeißen ihn raus
            gpx_data.pop(i+1)

            # => nun i+2 ist zum "i+1" geworden
            # => wir legen in der Mitte einen neuen Punkt an
            t_mid = t_i + timedelta(seconds=dt_total/2)
            lat_mid = lat_i + 0.5*(lat_ip2 - lat_i)
            lon_mid = lon_i + 0.5*(lon_ip2 - lon_i)
            ele_mid = ele_i + 0.5*(ele_ip2 - ele_i)

            new_pt = {
                "lat": lat_mid,
                "lon": lon_mid,
                "ele": ele_mid,
                "time": t_mid,
                "delta_m": 0.0,
                "speed_kmh": 0.0,
                "gradient": 0.0
            }
            # => Insert an i+1
            gpx_data.insert(i+1, new_pt)

            # => i+2 existiert weiterhin, plus wir haben i+1 als middle
            # => Zeit: i..(i+1) ~ dt_total/2, (i+1)..(i+2) ~ dt_total/2
            # => lat/lon linear

        # ---------------------------------------------
        # 5) Recalc + Updates
        # ---------------------------------------------
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()

        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)

        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)

        QMessageBox.information(
            self,
            "Delete Way Errors",
            f"{count_err} Way Errors fixed (where possible)."
        )
    
        
    def on_delete_time_errors_clicked(self):
        mw = self._mainwindow
        """
        Called when the user selects 'Delete Time Errors' in the More-menu.
        We look for all GPX points i where time[i] == time[i-1] => step=0.
        Then we ask the user if we should remove them all.
        After confirmation, we remove them from gpx_data, recalc, and update.
        """
        #from PySide6.QtWidgets import QMessageBox
      

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data available.")
            return

        n = len(gpx_data)
        if n < 2:
            QMessageBox.information(self, "Not enough points", 
                "There are not enough points to check for time errors.")
            return

        # 1) Alle Indizes i (1..n-1) suchen, bei denen time[i] == time[i-1]
        zero_step_indices = []
        for i in range(1, n):
            t_cur = gpx_data[i]["time"]
            t_prev = gpx_data[i-1]["time"]
            if t_cur == t_prev:
                zero_step_indices.append(i)

        count_err = len(zero_step_indices)
        if count_err == 0:
            QMessageBox.information(self, "No Time Errors",
                "No points with 0s step found.")
            return

        # 2) Nachfrage => "We found X time errors. Do you want to remove them?"
        answer = QMessageBox.question(
            self,
            "Delete Time Errors?",
            f"We found {count_err} time errors (0s step). Do you want to remove them all?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        # 3) Undo-Snapshot
        self.register_gpx_undo_snapshot("Delete time errors")

        # 4) Entfernen der betroffenen Indizes (in absteigender Reihenfolge!)
        zero_step_indices.sort(reverse=True)
        for i in zero_step_indices:
            # i < len(gpx_data) ?
            if i < len(gpx_data):
                gpx_data.pop(i)

        # 5) recalc + updates
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()

        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)

        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)

        QMessageBox.information(
            self, "Done",
            f"{count_err} Time Errors removed."
        )    
        
    def on_cut_before_b_clicked(self):
        """
        Deletes all GPX points from index 0 up to and including MarkB
        and then shifts the time so that the new first time = 0.
        Then update chart/map/minichart/table etc.
        """
        mw = self._mainwindow
        if mw is None:
            return  # kein MainWindow-Objekt gesetzt
    
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        if b_idx is None:
            # Falls gar kein MarkB existiert => Abbruch
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cut <B", "No MarkB set.")
            return
    
        # Schneller Zugriff
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return
        
        if b_idx < 0 or b_idx >= len(gpx_data):
            # Sicherheitscheck
            return
            
                # --- NEU: Prüfen, ob dieser Cut den grauen Bereich trifft ---
        
        try:
            cur_shift = get_gpx_video_shift()
        except Exception:
            cur_shift = 0
        auto_on = hasattr(mw, "action_auto_sync_video") and mw.action_auto_sync_video.isChecked()

        hit_grey = False
        if (not auto_on) and (cur_shift < 0):
            # Bei "Cut before B" schneidest du immer von 0..B -> das berührt grau, sobald es grau gibt
            hit_grey = True


        # 1) Undo-Snapshot
        self.register_gpx_undo_snapshot(self._schritt("Cut all before", b_idx))
    
        # 2) Löschen der Daten von 0..b_idx (inkl. b_idx)
        del gpx_data[0 : b_idx+1]

        if not gpx_data:
            # Falls jetzt gar nichts mehr übrig bleibt
            # -> wir setzen die Liste leer und updaten
            mw.gpx_widget.set_gpx_data([])
            mw._gpx_data = []
            # Alle Widgets neu leeren
            mw.chart.set_gpx_data([])
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data([])
            mw.map_widget.loadRoute(None, do_fit=False)
            mw._update_gpx_overview()
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            return
    
        # 3) Zeiten so verschieben, dass neuer Startpunkt rel_s=0
        
        set_gpx_video_shift(0) #TODO: test this 
        recalc_gpx_data(gpx_data)
    
        # 4) Data neu in GUI setzen
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
    
        # 5) Tabellen/Charts/Map etc. neu aufbauen
        mw._update_gpx_overview()
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        
        # 6) Markierungen zurücksetzen
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
        
                # --- NEU: Falls manuell in grau geschnitten wurde -> Sync verwerfen + ggf. neu syncen ---
        if hit_grey:
            reply = QMessageBox.question(
                self,
                "Sync may be invalid",
                "You cut away the pre-video (grey) section.\n"
                f"The current GPX–video shift ({cur_shift:+.1f}s) will be cleared.\n\n"
                "Do you want to set a new sync now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            set_gpx_video_shift(0)
            route_geojson = mw._build_route_geojson_from_gpx(mw._gpx_data)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)

            mw.gpx_widget.gpx_list.set_gpx_data(mw._gpx_data)
            mw.video_control.activate_controls()
            if hasattr(mw.video_control, "update_set_sync_highlight"):
                mw.video_control.update_set_sync_highlight()

            if reply == QMessageBox.Yes:
                mw.gpx_widget.gpx_list.clear_marked_range()
                if hasattr(mw, "map_widget"):
                    mw.map_widget.clear_marked_range()
        
                if hasattr(mw.video_control, "update_set_sync_highlight"):
                    mw.video_control.update_set_sync_highlight()

                QMessageBox.information(
                    mw,
                    "Set a new sync",
                    "Please select the matching GPX point and set the current video frame, "
                    "then click 'Sync' (GSync) to create a new alignment."
                )

    
    
    def on_cut_after_e_clicked(self):
        """
        Löscht alle GPX-Punkte ab MarkE bis zum Ende (einschl. E).
        Falls kein MarkE existiert, aber ein MarkB gesetzt ist, 
        verwenden wir ersatzweise MarkB als E.
        """
        mw = self._mainwindow
        if mw is None:
            return
    
        # Primär: MarkE-Index
        e_idx = mw.gpx_widget.gpx_list._markE_idx

        # Fallback: falls MarkE nicht gesetzt, nimm MarkB
        if e_idx is None:
            e_idx = mw.gpx_widget.gpx_list._markB_idx

        # Falls weder B noch E gesetzt => Fehlermeldung
        if e_idx is None:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Cut >E", "No MarkE or MarkB set.")
            return
    
        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return
    
        if e_idx < 0 or e_idx >= len(gpx_data):
            return

        # 1) Undo-Snapshot
        self.register_gpx_undo_snapshot(self._schritt("Cut all after", e_idx))
    
        # 2) Löschen ab e_idx (inkl.) bis zum Ende
        del gpx_data[e_idx:]

        if not gpx_data:
            # Falls dabei alles wegfällt
            mw.gpx_widget.set_gpx_data([])
            mw._gpx_data = []
            mw.chart.set_gpx_data([])
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data([])
            mw.map_widget.loadRoute(None, do_fit=False)
            mw._update_gpx_overview()
            mw.gpx_widget.gpx_list.clear_marked_range()
            mw.map_widget.clear_marked_range()
            return
        
        # 3) recalc
        
        recalc_gpx_data(gpx_data)
        
        # 4) Neu setzen und Widgets aktualisieren
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        
        mw._update_gpx_overview()
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        
        # 5) Markierungen zurücksetzen
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
    
        
        
    def highlight_markB_button(self):
        """Zeigt MarkB-Button in roter Farbe an."""
        self.markB_button.setStyleSheet("background-color: red; color: white;")

    def highlight_markE_button(self):
        """Zeigt MarkE-Button in roter Farbe an."""
        self.markE_button.setStyleSheet("background-color: red; color: white;")

    def reset_mark_buttons(self):
        """Setzt MarkB- und MarkE-Button auf ihr ursprüngliches StyleSheet zurück."""
        self.markB_button.setStyleSheet(self._default_markB_style)
        self.markE_button.setStyleSheet(self._default_markE_style)

    def _on_markB_restore(self):
        """Rechtsklick auf [-: den Punkt vor der Luecke des letzten Schnitts
        markieren. Karte, Chart und Button-Farbe folgen ueber markBSet wie
        beim Setzen. Nur bei V&G Off - mit V&G On sind die Buttons ohnehin
        versteckt, und die Video-Buttons haben keinen Rechtsklick."""
        mw = self._mainwindow
        if not mw or getattr(mw, "_autoSyncVideoEnabled", False):
            return
        self._punkt_anfahren(mw.gpx_widget.gpx_list.restore_markB())

    def _on_markE_restore(self):
        """Rechtsklick auf -]: den Punkt nach der Luecke des letzten Schnitts markieren."""
        mw = self._mainwindow
        if not mw or getattr(mw, "_autoSyncVideoEnabled", False):
            return
        self._punkt_anfahren(mw.gpx_widget.gpx_list.restore_markE())

    def _punkt_anfahren(self, idx):
        """Den gerade markierten Punkt zeigen: Zeile selektiert, Karte darauf
        zentriert, Chart und Mini-Chart darauf, und bei "Sync all with video"
        auch das Video. Sonst stand das Video irgendwo, und Karte und Chart
        zeigten den Punkt nicht.

        Bewusst NICHT der Weg des Zeilenklicks (rowClickedInPause): der
        faerbt den Punkt in der Karte blau und ueberdeckt damit die rote
        Marke, die der Rechtsklick gerade gesetzt hat. Die Karte wird hier
        nur zentriert, der Punkt bleibt rot."""
        if idx is None:
            return
        mw = self._mainwindow
        mw.gpx_widget.gpx_list.select_row_in_pause(idx)
        mw.map_widget.center_on_index(idx)
        mw.chart.highlight_gpx_index(idx)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_current_index(idx)
        if getattr(mw, "_autoSyncNewPointsWithVideoTime", False) and mw.playlist_counter > 0:
            mw.on_map_sync_any(idx)
        
        
    def _close_gaps_local_interpolation(self, b_idx: int, e_idx: int, dt: float):
        """
        Das ist dein alter Code, der zwischen b_idx und e_idx
        lineare Punkte einfügt, damit jeder Schritt ~1s lang ist.
        """
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data

        # 1) Undo-Snapshot
        self.register_gpx_undo_snapshot(self._schritt("Close gaps (interpolation)", b_idx, e_idx))

        # 2) Koordinaten
        lat1, lon1, ele1 = gpx_data[b_idx]["lat"], gpx_data[b_idx]["lon"], gpx_data[b_idx]["ele"]
        lat2, lon2, ele2 = gpx_data[e_idx]["lat"], gpx_data[e_idx]["lon"], gpx_data[e_idx]["ele"]
        t1 = gpx_data[b_idx]["time"]

        # 3) Wie bisher: Anzahl Intervalle = round(dt)
        
        num_intervals = int(round(dt))
        if num_intervals < 2:
            #from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Gap to Close",
                f"Time difference ~{dt:.2f}s => no extra points needed.")
            return

        sub_s = dt / num_intervals
        new_points = []
        for i in range(1, num_intervals):
            frac = i / num_intervals
            new_t = t1 + timedelta(seconds=sub_s * i)
            lat_new = lat1 + frac*(lat2 - lat1)
            lon_new = lon1 + frac*(lon2 - lon1)
            ele_new = ele1 + frac*(ele2 - ele1)
            pt = {
                "lat": lat_new,
                "lon": lon_new,
                "ele": ele_new,
                "time": new_t,
                "delta_m": 0.0,
                "speed_kmh": 0.0,
                "gradient": 0.0
            }
            new_points.append(pt)

        # 4) Einfügen
        for i, p in enumerate(new_points):
            gpx_data.insert(b_idx + 1 + i, p)
    
        # 5) recalc
        
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
    
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
            
        ### nur range in editor llschen wenn autocut is enabled
        
        if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
            mw.cut_manager.on_markClear_clicked()
                

        #from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Close Gaps",
            f"Inserted {len(new_points)} new point(s)\n(time-based local interpolation).")

        
    
    
    def _close_gaps_mapbox(self, b_idx: int, e_idx: int, dt: float, profile: str,
                           hoehen_holen: bool = True):
        """
        Ruft die Mapbox Directions API auf (profil = 'driving','cycling','walking'),
        berechnet time-based Densify in 1s-Schritten,
        und ersetzt b_idx..e_idx im GPX durch die neue Route.

        hoehen_holen=False: statt der Terrain-Kacheln bekommen die neuen
        Punkte die Hoehe linear von B nach E. Die Punkte liegen nach
        Wegstrecke gleichmaessig (konstante Geschwindigkeit), das ergibt
        entlang der Strasse ein durchgehend gleiches Gefaelle - wie Close
        Gaps ohne Directions, nur auf der Strasse statt auf der Geraden.
        """
        mw = self._mainwindow
        gpx_data = mw.gpx_widget.gpx_list._gpx_data

       
        #from PySide6.QtWidgets import QMessageBox
      
    
        # 1) Undo-Snapshot
        self.register_gpx_undo_snapshot(self._schritt("Close gaps (Mapbox)", b_idx, e_idx))

        lat1, lon1 = gpx_data[b_idx]["lat"], gpx_data[b_idx]["lon"]
        lat2, lon2 = gpx_data[e_idx]["lat"], gpx_data[e_idx]["lon"]

        # 2) Key prüfen
        if not mw._mapbox_key:
            QMessageBox.warning(self, "Mapbox Key missing",
                "Directions=True, but no mapbox_key is set.\nFalling back to local interpolation.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        # 3) URL bauen (Mapbox-Directions)
        base_url = "https://api.mapbox.com/directions/v5/mapbox"
        url = (f"{base_url}/{profile}/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
            f"?geometries=geojson&overview=full&access_token={mw._mapbox_key}")
    
        # 4) HTTP an Mapbox per urllib
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
        except Exception as ex:
            QMessageBox.critical(self, "Mapbox Error",
                f"Could not fetch route from Mapbox:\n{ex}\n\nFalling back to local interpolation.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        if "routes" not in data or not data["routes"]:
            QMessageBox.warning(self, "No Route",
                "Mapbox returned no 'routes'.\nFalling back to local interpolation.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        coords = data["routes"][0]["geometry"]["coordinates"]  # => [[lon, lat], [lon, lat], ...]
    
        if len(coords) < 2:
            QMessageBox.warning(self, "Invalid route",
                "Too few points in the Mapbox route.\nFalling back to local interpolation.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        # 5) Distanzberechnung => wir bauen Segmente, 
        #    dann verteilen wir dt in 1s-Schritte => time-based densify
        def haversine_m(latA, lonA, latB, lonB):
            import math
            R = 6371000
            rLA = math.radians(latA)
            rLB = math.radians(latB)
            dLat = rLB - rLA
            dLon = math.radians(lonB - lonA)
            a = (math.sin(dLat/2)**2
                + math.cos(rLA)*math.cos(rLB)*math.sin(dLon/2)**2)
            return R*2*math.atan2(math.sqrt(a), math.sqrt(1-a))

        # Koords in (lat, lon) => big_coords
        big_coords = [(c[1], c[0]) for c in coords]  # c[0]=lon, c[1]=lat

        segments = []
        total_dist = 0.0
        for i in range(len(big_coords)-1):
            la1, lo1 = big_coords[i]
            la2, lo2 = big_coords[i+1]
            d = haversine_m(la1, lo1, la2, lo2)
            segments.append((la1, lo1, la2, lo2, d, total_dist))
            total_dist += d

        if total_dist < 0.01:
            QMessageBox.information(self, "No Distance", 
                "Mapbox returned quasi Start=End.\nFall back to local.")
            self._close_gaps_local_interpolation(b_idx, e_idx, dt)
            return

        # Hilfsfunc
        def get_coord_at_dist(dist_val):
            # dist_val=0 => Start, dist_val>=total_dist => End
            if dist_val<=0:
                return big_coords[0]
            if dist_val>=total_dist:
                return big_coords[-1]
            for seg in segments:
                la1, lo1, la2, lo2, dseg, segStart = seg
                segEnd = segStart + dseg
                if dist_val>=segStart and dist_val<=segEnd:
                    frac = (dist_val-segStart)/dseg
                    lat_ = la1 + frac*(la2-la1)
                    lon_ = lo1 + frac*(lo2-lo1)
                    return (lat_, lon_)
            # fallback
            return big_coords[-1]

        # => now 1s-Schritte
       
        new_points = []
        t_start = gpx_data[b_idx]["time"]
        # final => gpx_data[e_idx]["time"] => dt sek

        speed_ms = total_dist/dt
        # how many integer steps => floor(dt)
        steps_count = int(math.floor(dt))
        if steps_count<1:
            steps_count=1

        for i in range(steps_count+1):
            dist_i = i*speed_ms
            if dist_i>total_dist:
                dist_i=total_dist
            (lat_, lon_) = get_coord_at_dist(dist_i)
            t_new = t_start + timedelta(seconds=i)
            pt = {
                "lat": lat_,
                "lon": lon_,
                "ele": 0,  
                "time": t_new,
                "delta_m": 0.0,
                "speed_kmh": 0.0,
                "gradient": 0.0
            }
            new_points.append(pt)

        # Letzter Punkt => exaktes E
        latE, lonE = gpx_data[e_idx]["lat"], gpx_data[e_idx]["lon"]
        new_points[-1]["lat"] = latE
        new_points[-1]["lon"] = lonE
        new_points[-1]["time"] = gpx_data[e_idx]["time"]

        # Hoehe linear B -> E, wenn keine Terrain-Kacheln gewuenscht sind.
        # Der letzte neue Punkt IST E (Lage und Zeit oben uebernommen), er
        # bekommt E's Hoehe; die dazwischen den Anteil nach Zaehler, was bei
        # gleichmaessiger Verteilung nach Wegstrecke dem Anteil der Strecke
        # entspricht.
        if not hoehen_holen:
            eleB = float(gpx_data[b_idx].get("ele", 0.0) or 0.0)
            eleE = float(gpx_data[e_idx].get("ele", 0.0) or 0.0)
            letzter = len(new_points) - 1
            for i in range(1, len(new_points)):
                frac = i / letzter if letzter > 0 else 1.0
                new_points[i]["ele"] = eleB + frac * (eleE - eleB)

        # 6) b_idx+1.. e_idx entfernen
        del gpx_data[b_idx+1 : e_idx+1]

        mapbox_ele_update_list =[]
        # Füge new_points[1..] ein (index=0 ist b_idx selbst)
        for i, p in enumerate(new_points[1:], start=1):
            gpx_data.insert(b_idx + i, p)
            mapbox_ele_update_list.append((b_idx + i,p["lat"], p["lon"]))
        # 7) recalc
        mw.gpx_widget.set_gpx_data(gpx_data)
        if hoehen_holen:
            self.update_elevation_from_mapbox(mapbox_ele_update_list)

        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()

        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
            
        ### nur range in editor llschen wenn autocut is enabled
        
        if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
            mw.cut_manager.on_markClear_clicked()        

        QMessageBox.information(self, "Close Gaps (Mapbox)",
            f"Inserted {len(new_points)-1} new point(s)\n"
            f"via Directions={profile}, total time {dt:.2f}s kept.\n"
            + ("Elevation from Mapbox terrain tiles." if hoehen_holen else
               "Elevation runs in a straight line from the first to the "
               "last point (no terrain lookup)."))

        
        

    def _schritt(self, name, b_idx=None, e_idx=None):
        """Name fuer Edit > Undo history mit Zeile(n) und GPX-Zeit."""
        return self._mainwindow.gpx_widget.gpx_list.schritt_text(name, b_idx, e_idx)

    def register_gpx_undo_snapshot(self, name="GPX edit"):
        # 'name' steht in Edit > Undo history.
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            return

        snapshot = copy.deepcopy(gpx_data)

        def undo():
            mw.gpx_widget.set_gpx_data(snapshot)
            mw._gpx_data = snapshot
            mw._update_gpx_overview()
            mw.chart.set_gpx_data(snapshot)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(snapshot)
            route_geojson = mw._build_route_geojson_from_gpx(snapshot)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw._undo_ablegen(undo, name)
        
    def _format_duration_with_ms(self, total_seconds: float) -> str:
        """
        Formatiert Sekunden in HH:MM:SS.mmm Format mit Millisekunden.
        """
        if total_seconds < 0:
            return "00:00:00.000"
    
        total_ms = int(round(total_seconds * 1000))
        hours = total_ms // (3600 * 1000)
        minutes = (total_ms % (3600 * 1000)) // (60 * 1000)
        seconds = (total_ms % (60 * 1000)) // 1000
        milliseconds = total_ms % 1000
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def on_show_gpx_summary(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data:
            QMessageBox.warning(self, "No GPX Data", "No GPX data loaded.")
            return

        n_points = len(gpx_data)
        t_start = gpx_data[0]["time"]
        t_end = gpx_data[-1]["time"]
        duration_s = (t_end - t_start).total_seconds()
    
        # Verwende die neue Formatierung mit Millisekunden
        duration_str = self._format_duration_with_ms(duration_s)

        dist_m = sum(
            self._haversine_m(
                gpx_data[i]["lat"], gpx_data[i]["lon"],
                gpx_data[i+1]["lat"], gpx_data[i+1]["lon"]
            )
            for i in range(n_points - 1)
        )
        
        # Distanz NICHT aus dem Anzeigetext zurueckrechnen: sobald sich die
        # Beschriftung aendert (zusaetzlicher Doppelpunkt, Komma statt Punkt),
        # scheitert das Parsen still und die Summary zeigt 0.00 km.
        # Genommen wird derselbe Wert, den die Info-Zeile anzeigt - sonst
        # stuenden in Leiste und Summary zwei verschiedene Kilometerzahlen.
        dist_km = float(getattr(self, "_length_km", dist_m / 1000.0))
    
        # Höhendaten
        ele_start = gpx_data[0].get("ele", 0.0)
        ele_end   = gpx_data[-1].get("ele", 0.0)
        # Wie oben: der Wert kommt aus update_info_line(), nicht aus dem Text.
        elev_gain = float(getattr(self, "_elev_gain", 0.0))
    
        # Geschwindigkeiten
        speeds = [pt.get("speed_kmh", 0.0) for pt in gpx_data if "speed_kmh" in pt]
        max_speed = max(speeds) if speeds else 0.0
        min_speed = min(speeds) if speeds else 0.0
    
        # Video-Dauer berechnen (mit Millisekunden)
        if mw and hasattr(mw, 'real_total_duration') and hasattr(mw.cut_manager, 'get_total_cuts'):
            total_dur = mw.real_total_duration
            sum_cuts = mw.cut_manager.get_total_cuts()
            final_dur = total_dur - sum_cuts
            if final_dur < 0:
                final_dur = 0
            video_duration_str = self._format_duration_with_ms(final_dur)
            # Laenge vor den Schnitten. Stand bis 6.01 weiss im Videobild;
            # die Einblendung dort ist entfallen, gebraucht wird die Zahl
            # aber weiterhin - deshalb steht sie jetzt hier.
            video_before_str = self._format_duration_with_ms(total_dur)
        else:
            video_duration_str = "00:00:00.000"
            video_before_str = "00:00:00.000"
    
        # -- Neuen Dialog bauen
        dlg = QDialog(self)
        dlg.setWindowTitle("GPX Summary")
        dlg.setMinimumWidth(400)  # Etwas breiter für die längeren Zeitangaben
    
        layout = QVBoxLayout(dlg)
        label = QLabel(dlg)
        label.setTextFormat(Qt.RichText)
        label.setText(
            f"<div style='margin-left:50px;'>"
            f"<b>GPX Summary</b><br><br>"
            f"<table>"
            f"<tr><td><b>Total Points:</b></td><td>{n_points}</td></tr>"
            f"<tr><td><b>GPX Duration:</b></td><td>{duration_str}</td></tr>"
            f"<tr><td><b>Video before cuts:</b></td><td>{video_before_str}</td></tr>"
            f"<tr><td><b>Video Duration:</b></td><td>{video_duration_str}</td></tr>"
            f"<tr><td><b>Distance:</b></td><td>{dist_km:.2f} km</td></tr>"
            f"<tr><td><b>Start Elevation:</b></td><td>{ele_start:.1f} m</td></tr>"
            f"<tr><td><b>End Elevation:</b></td><td>{ele_end:.1f} m</td></tr>"
            f"<tr><td><b>Elevation Gain:</b></td><td>{elev_gain:.1f} m</td></tr>"
            f"<tr><td><b>Max Speed:</b></td><td>{max_speed:.1f} km/h</td></tr>"
            f"<tr><td><b>Min Speed:</b></td><td>{min_speed:.1f} km/h</td></tr>"
            f"</table>"
        )
        layout.addWidget(label)
    
        btn = QPushButton("OK", dlg)
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, alignment=Qt.AlignRight)
    
        dlg.exec()    
        
    def _on_resample_to_1s_clicked(self):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data or len(gpx_data) < 2:
            QMessageBox.warning(self, "No GPX Data", "No or insufficient GPX data loaded.")
            return

        # Prüfe, ob ein gültiger Bereich (B..E) markiert ist
        b_idx = mw.gpx_widget.gpx_list._markB_idx
        e_idx = mw.gpx_widget.gpx_list._markE_idx
        has_range = False
        if b_idx is not None and e_idx is not None:
            if b_idx > e_idx:
                b_idx, e_idx = e_idx, b_idx
            if 0 <= b_idx < len(gpx_data) and 0 <= e_idx < len(gpx_data) and (e_idx - b_idx) >= 1:
                has_range = True

        if not has_range:
            # === ALT: kompletter Track wie gehabt ===
            reply = QMessageBox.question(
                self,
                "Resample to 1s",
                "This function should be applied before syncing or editing!\n\n"
                "Do you really want to resample the entire track to 1-second intervals?\n\n"
                "This may slightly change the total distance and elevation.\n"
                "If this GPX was already synchronized with the video, "
                "you should re-check the alignment afterwards.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            # Undo-Snapshot
            self.register_gpx_undo_snapshot("Resample to 1 s (whole track)")

            # Resample kompletter Track (nutzt deine MainWindow-Logik)
            new_data = mw._resample_to_1s(gpx_data)  # :contentReference[oaicite:3]{index=3}

            # Setzen + UI-Refresh (dein Muster)
            mw._gpx_data = new_data
            mw.gpx_widget.set_gpx_data(new_data)
            mw._update_gpx_overview()
            route_geojson = mw._build_route_geojson_from_gpx(new_data)
            mw.map_widget.loadRoute(route_geojson, do_fit=False)
            mw.chart.set_gpx_data(new_data)
            if mw.mini_chart_widget:
                mw.mini_chart_widget.set_gpx_data(new_data)

            QMessageBox.information(self, "Done", "GPX track has been resampled to 1s intervals.")
            return

        # === NEU: nur markierten Bereich B..E resamplen ===
        # Kurzer, bereichs-bezogener Hinweis
        reply = QMessageBox.question(
            self,
            "Resample range to 1s",
            (f"You selected a range {b_idx}..{e_idx}.\n"
             "Only this range will be resampled to 1-second intervals.\n\n"
             "Note: Total duration of the range may slightly change;\n"
             "subsequent points will be shifted by that difference.\n\n"
             "Proceed?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        # Undo-Snapshot (dein GPX-Undo)
        self.register_gpx_undo_snapshot(self._schritt("Resample to 1 s", b_idx, e_idx))

        # Originaldauer des Segments
        t_start = gpx_data[b_idx]["time"]
        t_end   = gpx_data[e_idx]["time"]
        old_total_s = (t_end - t_start).total_seconds()
        if old_total_s <= 0:
            QMessageBox.warning(self, "Invalid Range", "Selected range has zero or negative duration.")
            return

        # Teilsegment kopieren und mit deiner MainWindow-Routine resamplen
        segment = [pt.copy() for pt in gpx_data[b_idx:e_idx + 1]]
        
        new_segment = mw._resample_to_1s(segment)  # nutzt base_time = segment[0]['time']  :contentReference[oaicite:5]{index=5}
        if not new_segment or len(new_segment) < 2:
            QMessageBox.warning(self, "Resample failed", "Could not resample the selected range.")
            return

        new_total_s = (new_segment[-1]["time"] - new_segment[0]["time"]).total_seconds()
        diff_s = new_total_s - old_total_s

        # Segment austauschen (Anzahl Punkte kann sich ändern)
        # Achtung: Wir arbeiten direkt auf gpx_data, danach recalc + Refresh wie überall.
        gpx_data[b_idx:e_idx + 1] = new_segment

        # Nachfolgende Punkte zeitlich verschieben (falls nötig)
        if (abs(diff_s) > 1e-9) and (b_idx + len(new_segment) - 1 < len(gpx_data) - 1):
            shift_from = b_idx + len(new_segment)  # erster Punkt NACH dem neuen Ende
            for j in range(shift_from, len(gpx_data)):
                gpx_data[j]["time"] = gpx_data[j]["time"] + timedelta(seconds=diff_s)
        for pt in gpx_data:
            if "abs_s" in pt:
                del pt["abs_s"]
        # Recalc + UI-Refresh – exakt dein Muster
        recalc_gpx_data(gpx_data)
        mw.gpx_widget.set_gpx_data(gpx_data)
        mw._gpx_data = gpx_data
        mw._update_gpx_overview()
        route_geojson = mw._build_route_geojson_from_gpx(gpx_data)
        mw.map_widget.loadRoute(route_geojson, do_fit=False)
        mw.chart.set_gpx_data(gpx_data)
        if mw.mini_chart_widget:
            mw.mini_chart_widget.set_gpx_data(gpx_data)

        # Range in UI leeren (Liste + Map) + ggf. Video-AutoSync-Range löschen – wie an anderer Stelle
        mw.gpx_widget.gpx_list.clear_marked_range()
        mw.map_widget.clear_marked_range()
        if hasattr(mw, "_autoSyncVideoEnabled") and mw._autoSyncVideoEnabled:
            mw.cut_manager.on_markClear_clicked()  # :contentReference[oaicite:6]{index=6}

        # Info für den User
        QMessageBox.information(
            self, "Done",
            (f"Range {b_idx}..{e_idx} resampled to 1s.\n"
             f"Old duration: {old_total_s:.3f} s\n"
             f"New duration: {new_total_s:.3f} s\n"
             f"Shift applied to subsequent points: {diff_s:+.3f} s")
        )
    
        
    

    def export_fit_immersion(self, threshold: float = 1.0):
        mw = self._mainwindow
        if not mw:
            return

        gpx_data = mw.gpx_widget.gpx_list._gpx_data
        if not gpx_data or len(gpx_data) < 2:
            return "<difficulty></difficulty>"

        start_time = gpx_data[0].get("time")
        if not start_time:
            return "<difficulty></difficulty>"

        def format_time(seconds: float) -> str:
            total_seconds = int(seconds)
            minutes = total_seconds // 60
            secs = total_seconds % 60
            return f"{minutes}:{secs:02d}"

        def calc_avg_slope(start_idx, end_idx):
            segment = gpx_data[start_idx:end_idx+1]
            total_dist = sum(p.get("delta_m", 0.0) for p in segment[1:])
            elev_diff = segment[-1]["ele"] - segment[0]["ele"]
            if total_dist > 0:
                return (elev_diff / total_dist) * 100
            else:
                return 0.0

        def convert_slope(slope):
            return int(round(15 + (slope/15) * 85))

        output = []
        segment_start = 0
        last_slope = calc_avg_slope(segment_start, segment_start+1)
        last_value = convert_slope(last_slope)
        output.append(f"0:00/{last_value}")

        i = segment_start + 2
        while i < len(gpx_data):
            best_index = None
            best_delta = 0
            current_slope = last_slope

            for j in range(i, min(i + 60, len(gpx_data))):
                avg_slope = calc_avg_slope(segment_start, j)
                delta = convert_slope(avg_slope) - last_value

                if abs(delta) >= threshold and abs(delta) > abs(best_delta):
                    best_index = j
                    best_delta = delta
                    current_slope = avg_slope

            if best_index is not None:
                t = gpx_data[best_index]["time"]
                rel_sec = (t - start_time).total_seconds()
                new_val = convert_slope(current_slope)
                output.append(f"{format_time(rel_sec)}/{new_val}")
                segment_start = best_index
                last_slope = current_slope
                last_value = new_val
                i = best_index + 1
            else:
                i += 1

        t = gpx_data[-1]["time"]
        rel_sec = (t - start_time).total_seconds()
        output.append(f"{format_time(rel_sec)}/{convert_slope(last_slope)}")

        result = f"<difficulty>{';'.join(output)}</difficulty>"
        print(result)
        return result

