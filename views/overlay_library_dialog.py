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

# views/overlay_library_dialog.py
"""Die Overlay-Bibliothek pflegen.

An dieser Stelle sass frueher das Overlay-Setup mit genau drei festen
Plaetzen. Die Beschraenkung auf drei war der Grund, warum man beim Einfuegen
staendig Bild, Ecke und Abstaende neu eintippen musste - was daneben lag,
liess sich nirgends behalten.

Hier stehen stattdessen bis zu einer Hoechstzahl beliebige Bilder, mit einer
Vorgabelage je Bild. Die Grenze ist Absicht: eine Bibliothek soll eine
ueberschaubare Auswahl sein und keine Ablage, in der man nach Jahren nichts
mehr wiederfindet.

Geaendert wird auf einer Kopie; erst OK schreibt sie zurueck. Wer sich
vertut, kommt mit Abbrechen heraus, ohne Schaden angerichtet zu haben.
"""

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from core import overlay_library

BILDFILTER = ("Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff);;"
              "All files (*)")


class OverlayLibraryDialog(QDialog):
    """Bilder aufnehmen, entfernen und ihre Vorgabelage einstellen."""

    VORSCHAU = 72

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Overlay Library")
        self.setMinimumSize(560, 480)

        # Auf einer Kopie arbeiten - Abbrechen soll wirklich nichts hinterlassen.
        self._eintraege = [dict(e) for e in overlay_library.eintraege()]
        self._laedt = False

        aufbau = QVBoxLayout(self)

        self.kopfzeile = QLabel()
        aufbau.addWidget(self.kopfzeile)

        self.liste = QListWidget()
        self.liste.setIconSize(QSize(self.VORSCHAU, self.VORSCHAU))
        self.liste.setAlternatingRowColors(True)
        self.liste.currentRowChanged.connect(self._auf_auswahl)
        aufbau.addWidget(self.liste, 1)

        zeile = QHBoxLayout()
        self.knopf_hinzu = QPushButton("Add File…")
        self.knopf_hinzu.clicked.connect(self._auf_hinzufuegen)
        zeile.addWidget(self.knopf_hinzu)
        self.knopf_weg = QPushButton("Remove")
        self.knopf_weg.clicked.connect(self._auf_entfernen)
        zeile.addWidget(self.knopf_weg)
        zeile.addStretch(1)
        aufbau.addLayout(zeile)

        self.kasten = QGroupBox("Default for this image")
        felder = QFormLayout(self.kasten)
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.01, 20.0)
        self.spin_scale.setDecimals(2)
        self.spin_scale.setSingleStep(0.05)
        self.spin_scale.valueChanged.connect(self._auf_feld)
        felder.addRow("Scale:", self.spin_scale)

        self.combo_ecke = QComboBox()
        self.combo_ecke.addItems(list(overlay_library.ECKEN))
        self.combo_ecke.currentIndexChanged.connect(self._auf_feld)
        felder.addRow("Corner:", self.combo_ecke)

        self.spin_dx = QSpinBox()
        self.spin_dx.setRange(-9999, 9999)
        self.spin_dx.valueChanged.connect(self._auf_feld)
        felder.addRow("Offset dx:", self.spin_dx)

        self.spin_dy = QSpinBox()
        self.spin_dy.setRange(-9999, 9999)
        self.spin_dy.valueChanged.connect(self._auf_feld)
        felder.addRow("Offset dy:", self.spin_dy)
        aufbau.addWidget(self.kasten)

        aufbau.addWidget(QLabel(
            "The default position is used when inserting. After that the\n"
            "overlay can be dragged freely in the preview image."))

        kaesten = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        kaesten.accepted.connect(self._auf_ok)
        kaesten.rejected.connect(self.reject)
        aufbau.addWidget(kaesten)

        self._liste_fuellen()

    # ------------------------------------------------------------------ Liste
    def _beschriftung(self, eintrag):
        text = os.path.basename(eintrag["pfad"])
        bild = QImage(eintrag["pfad"])
        if bild.isNull():
            text += "   (file missing)"
        else:
            text += f"   {bild.width()}x{bild.height()}"
        text += (f"\n{eintrag['ecke']},  scale {eintrag['scale']:g},  "
                 f"dx {eintrag['dx']},  dy {eintrag['dy']}")
        return text

    def _symbol(self, pfad):
        bild = QImage(pfad)
        if bild.isNull():
            return QIcon()
        klein = bild.scaled(self.VORSCHAU, self.VORSCHAU,
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QIcon(QPixmap.fromImage(klein))

    def _liste_fuellen(self, auswahl=0):
        self._laedt = True
        self.liste.clear()
        for eintrag in self._eintraege:
            zeile = QListWidgetItem(self._symbol(eintrag["pfad"]),
                                    self._beschriftung(eintrag))
            zeile.setToolTip(eintrag["pfad"])
            self.liste.addItem(zeile)
        self._laedt = False

        if self._eintraege:
            self.liste.setCurrentRow(min(auswahl, len(self._eintraege) - 1))
        self._kopfzeile_auffrischen()
        self._auf_auswahl(self.liste.currentRow())

    def _kopfzeile_auffrischen(self):
        anzahl = len(self._eintraege)
        grenze = overlay_library.HOECHSTZAHL
        self.kopfzeile.setText(
            f"Images offered when inserting an overlay: "
            f"{anzahl} of {grenze}.")
        self.knopf_hinzu.setEnabled(anzahl < grenze)

    def _auf_auswahl(self, zeile):
        gueltig = 0 <= zeile < len(self._eintraege)
        self.kasten.setEnabled(gueltig)
        self.knopf_weg.setEnabled(gueltig)
        if not gueltig:
            return
        eintrag = self._eintraege[zeile]
        self._laedt = True
        self.spin_scale.setValue(float(eintrag["scale"]))
        self.combo_ecke.setCurrentText(eintrag["ecke"])
        self.spin_dx.setValue(int(eintrag["dx"]))
        self.spin_dy.setValue(int(eintrag["dy"]))
        self._laedt = False

    def _auf_feld(self, *_):
        """Ein Feld wurde geaendert - in den ausgewaehlten Eintrag schreiben."""
        if self._laedt:
            return
        zeile = self.liste.currentRow()
        if not (0 <= zeile < len(self._eintraege)):
            return
        eintrag = self._eintraege[zeile]
        eintrag["scale"] = self.spin_scale.value()
        eintrag["ecke"] = self.combo_ecke.currentText()
        eintrag["dx"] = self.spin_dx.value()
        eintrag["dy"] = self.spin_dy.value()
        self.liste.item(zeile).setText(self._beschriftung(eintrag))

    # ---------------------------------------------------------------- Knoepfe
    def _auf_hinzufuegen(self):
        if len(self._eintraege) >= overlay_library.HOECHSTZAHL:
            QMessageBox.information(
                self, "Library is full",
                f"It holds {overlay_library.HOECHSTZAHL} images.\n"
                "Remove one first.")
            return
        pfad, _ = QFileDialog.getOpenFileName(
            self, "Add image", "", BILDFILTER)
        if not pfad:
            return
        for i, vorhanden in enumerate(self._eintraege):
            if os.path.normcase(os.path.abspath(vorhanden["pfad"])) == \
                    os.path.normcase(os.path.abspath(pfad)):
                QMessageBox.information(self, "Already there",
                                        "This image is already in the "
                                        "library.")
                self.liste.setCurrentRow(i)
                return
        self._eintraege.append({"pfad": pfad, "scale": 1.0, "ecke": "top-left",
                                "dx": 10, "dy": 10})
        self._liste_fuellen(len(self._eintraege) - 1)

    def _auf_entfernen(self):
        zeile = self.liste.currentRow()
        if not (0 <= zeile < len(self._eintraege)):
            return
        name = os.path.basename(self._eintraege[zeile]["pfad"])
        antwort = QMessageBox.question(
            self, "Remove from library",
            f"Remove {name} from the library?\n\n"
            "The image file itself stays where it is, and overlays that "
            "already use this image stay unchanged.")
        if antwort != QMessageBox.Yes:
            return
        self._eintraege.pop(zeile)
        self._liste_fuellen(zeile)

    def _auf_ok(self):
        overlay_library.speichern(self._eintraege)
        self.accept()
