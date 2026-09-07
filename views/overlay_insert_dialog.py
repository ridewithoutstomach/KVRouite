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

# views/overlay_insert_dialog.py
"""Overlay einfuegen - Bild auswaehlen statt Zahlen eintippen.

Vorher gab es hier eine Auswahlliste mit drei festen Plaetzen und einen Knopf
"Add New", hinter dem man Bild, Ecke und Abstaende von Hand eintrug - und was
man dort eintrug, war danach wieder vergessen.

Jetzt stehen drei Quellen in einer Liste:

  * Bilder, die in DIESEM Projekt schon benutzt werden. Auswaehlen heisst
    kopieren: gleiche Groesse, gleiche Lage, nur eine neue Zeit. Genau der
    Fall "dasselbe Logo noch einmal, an anderer Stelle".
  * die Bibliothek - was ueber Projekte hinweg behalten werden sollte.
  * eine beliebige Datei ueber den Dateidialog.

Aufgenommen wird eine neue Datei nur mit ausdruecklichem Haken. Sonst waere
die Bibliothek nach ein paar Jahren voll mit Bildern, die genau einmal
gebraucht wurden.

Der alte Dialog mit dem vollen Satz an Werten (Skalierung, Ecke, Abstaende)
bleibt ueber "Erweitert…" erreichbar - er ist bis auf Weiteres der einzige
Weg, die Groesse einzustellen.
"""

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout,
)

from core import overlay_library

BILDFILTER = ("Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;"
              "All files (*)")


class OverlayInsertDialog(QDialog):
    """Auswahl des Bildes und der Zeitwerte fuer ein neues Overlay."""

    VORSCHAU = 72

    def __init__(self, marker_s, overlay_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Overlay")
        self.setMinimumWidth(460)

        self._manager = overlay_manager
        self.marker_s = float(marker_s)

        #: Das fertige Overlay-Woerterbuch, das der Aufrufer eintragen soll.
        self.ergebnis = None
        #: True, wenn "Erweitert…" das Overlay bereits selbst eingetragen hat.
        self.bereits_hinzugefuegt = False

        self._neue_datei = None

        aufbau = QVBoxLayout(self)
        aufbau.addWidget(QLabel(
            "Choose an image - from this project, from the library\n"
            "or a new file."))

        self.liste = QListWidget()
        self.liste.setIconSize(QSize(self.VORSCHAU, self.VORSCHAU))
        self.liste.setAlternatingRowColors(True)
        self.liste.itemDoubleClicked.connect(lambda _i: self._auf_ok())
        aufbau.addWidget(self.liste, 1)

        zeile = QHBoxLayout()
        knopf_datei = QPushButton("Choose File…")
        knopf_datei.clicked.connect(self._auf_datei_waehlen)
        zeile.addWidget(knopf_datei)
        self.haken_bibliothek = QCheckBox("Add to library")
        self.haken_bibliothek.setEnabled(False)
        self.haken_bibliothek.setToolTip(
            "Only tick this if the image will be needed again later.")
        zeile.addWidget(self.haken_bibliothek)
        zeile.addStretch(1)
        aufbau.addLayout(zeile)

        aufbau.addWidget(QLabel("Duration (s):"))
        self.spin_dur = QDoubleSpinBox()
        self.spin_dur.setRange(0.1, 30.0)
        self.spin_dur.setDecimals(2)
        self.spin_dur.setValue(15.0)
        aufbau.addWidget(self.spin_dur)

        fade = QHBoxLayout()
        fade.addWidget(QLabel("Fade In(s):"))
        self.spin_in = QDoubleSpinBox()
        self.spin_in.setRange(0.0, 5.0)
        self.spin_in.setDecimals(2)
        self.spin_in.setValue(1.0)
        fade.addWidget(self.spin_in)
        fade.addWidget(QLabel("Fade Out(s):"))
        self.spin_out = QDoubleSpinBox()
        self.spin_out.setRange(0.0, 5.0)
        self.spin_out.setDecimals(2)
        self.spin_out.setValue(1.0)
        fade.addWidget(self.spin_out)
        aufbau.addLayout(fade)

        kaesten = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.knopf_erweitert = kaesten.addButton("Advanced…",
                                                 QDialogButtonBox.ActionRole)
        self.knopf_erweitert.setToolTip(
            "Enter scale, corner and offsets by hand.")
        self.knopf_erweitert.clicked.connect(self._auf_erweitert)
        kaesten.accepted.connect(self._auf_ok)
        kaesten.rejected.connect(self.reject)
        aufbau.addWidget(kaesten)

        self._liste_fuellen()

    # ------------------------------------------------------------------ Liste
    def _ueberschrift(self, text):
        eintrag = QListWidgetItem(text)
        eintrag.setFlags(Qt.NoItemFlags)
        schrift = eintrag.font()
        schrift.setBold(True)
        eintrag.setFont(schrift)
        self.liste.addItem(eintrag)

    def _symbol(self, pfad):
        """Vorschaubildchen und Bildgroesse, oder (leeres Symbol, None)."""
        bild = QImage(pfad)
        if bild.isNull():
            return QIcon(), None
        klein = bild.scaled(self.VORSCHAU, self.VORSCHAU,
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QIcon(QPixmap.fromImage(klein)), (bild.width(), bild.height())

    def _bild_eintragen(self, pfad, daten, zusatz=""):
        symbol, groesse = self._symbol(pfad)
        text = os.path.basename(pfad)
        if groesse:
            text += "   %dx%d" % groesse
        elif not os.path.isfile(pfad):
            text += "   (file missing)"
        else:
            text += "   (not a readable image)"
        if zusatz:
            text += "   " + zusatz
        eintrag = QListWidgetItem(symbol, text)
        eintrag.setToolTip(pfad)
        eintrag.setData(Qt.UserRole, daten)
        if groesse is None:
            # Fehlende Bilder bleiben sichtbar, aber nicht waehlbar - sonst
            # wundert man sich, warum ein Eintrag verschwunden ist.
            eintrag.setFlags(eintrag.flags() & ~Qt.ItemIsEnabled)
        self.liste.addItem(eintrag)
        return eintrag

    def _projekt_bilder(self):
        """Bilder aus den Overlays dieses Projekts, je Pfad das zuletzt benutzte."""
        try:
            alle = self._manager.get_all_overlays() or []
        except Exception:
            return []
        nach_pfad = {}
        for ovl in alle:
            pfad = str(ovl.get("image", "") or "").strip()
            if pfad:
                nach_pfad[os.path.normcase(os.path.abspath(pfad))] = ovl
        return list(nach_pfad.values())

    def _liste_fuellen(self):
        self.liste.clear()

        projekt = self._projekt_bilder()
        if projekt:
            self._ueberschrift("Used in this project  -  selecting makes a copy")
            for ovl in projekt:
                skalierung = float(ovl.get("scale", 1.0) or 1.0)
                self._bild_eintragen(
                    str(ovl.get("image", "")),
                    {"quelle": "projekt", "overlay": ovl},
                    zusatz="Scale %g" % skalierung)

        bibliothek = overlay_library.eintraege()
        if bibliothek:
            self._ueberschrift("Library")
            for eintrag in bibliothek:
                self._bild_eintragen(
                    eintrag["pfad"],
                    {"quelle": "bibliothek", "eintrag": eintrag},
                    zusatz="%s, scale %g" % (eintrag["ecke"],
                                                  eintrag["scale"]))

        if not projekt and not bibliothek:
            self._ueberschrift("No images yet - choose a file.")

    # ----------------------------------------------------------------- Knoepfe
    def _auf_datei_waehlen(self):
        pfad, _ = QFileDialog.getOpenFileName(
            self, "Choose overlay image", "", BILDFILTER)
        if not pfad:
            return
        self._neue_datei = pfad
        self.haken_bibliothek.setEnabled(True)
        self._liste_fuellen()
        self._ueberschrift("Newly chosen")
        eintrag = self._bild_eintragen(pfad, {"quelle": "neu", "pfad": pfad})
        self.liste.setCurrentItem(eintrag)
        self.liste.scrollToItem(eintrag)

    def _auf_erweitert(self):
        """Der alte Dialog mit allen Werten. Er traegt das Overlay selbst ein."""
        try:
            klasse = type(self._manager).FullOverlayDialog
        except AttributeError:
            QMessageBox.warning(self, "Not available",
                                "The advanced dialog is missing.")
            return
        dlg = klasse(self.marker_s, self._manager, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.bereits_hinzugefuegt = True
            self.reject()

    def _auf_ok(self):
        eintrag = self.liste.currentItem()
        daten = eintrag.data(Qt.UserRole) if eintrag is not None else None
        if not daten:
            QMessageBox.information(self, "No image selected",
                                    "Please choose an image from the list "
                                    "or open a file.")
            return

        quelle = daten.get("quelle")
        if quelle == "projekt":
            ovl = daten["overlay"]
            pfad = str(ovl.get("image", ""))
            skalierung = float(ovl.get("scale", 1.0) or 1.0)
            x_ausdruck, y_ausdruck = ovl.get("x", 0), ovl.get("y", 0)
        elif quelle == "bibliothek":
            e = daten["eintrag"]
            pfad = e["pfad"]
            skalierung = e["scale"]
            x_ausdruck, y_ausdruck = overlay_library.ausdruecke(
                e["ecke"], e["dx"], e["dy"])
        else:
            pfad = daten["pfad"]
            skalierung = 1.0
            # Ohne eigene Lage in die Bildmitte.
            x_ausdruck, y_ausdruck = overlay_library.ausdruecke("center", 0, 0)
            if (self.haken_bibliothek.isChecked() and
                    not overlay_library.aufnehmen(pfad, skalierung,
                                                  "center", 0, 0)):
                # Das Overlay entsteht trotzdem - nur gemerkt wird es nicht.
                QMessageBox.information(
                    self, "Library is full",
                    f"The library holds {overlay_library.HOECHSTZAHL} "
                    "images.\nThe overlay is inserted, but it is not "
                    "added.\n\nUse Setup -> Overlay Library to free "
                    "a slot.")

        if not pfad or not os.path.isfile(pfad):
            QMessageBox.warning(self, "Image missing",
                                "This file no longer exists:\n" + str(pfad))
            return

        dauer = self.spin_dur.value()
        self.ergebnis = {
            "start":    self.marker_s,
            "end":      self.marker_s + dauer,
            "fade_in":  self.spin_in.value(),
            "fade_out": self.spin_out.value(),
            "image":    pfad,
            "scale":    skalierung,
            "x":        x_ausdruck,
            "y":        y_ausdruck,
        }
        self.accept()
