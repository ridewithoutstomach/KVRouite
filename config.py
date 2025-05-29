# -*- coding: utf-8 -*-
#
# This file is part of VGSync.
#
# Copyright (C) 2025 by Bernd Eller
#
# VGSync is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# VGSync is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with VGSync. If not, see <https://www.gnu.org/licenses/>.
#
# config.py

import os
import sys
import platform
import tempfile
import shutil
from PySide6.QtCore import QSettings

##############################################################################
# 1) Versions-Konfiguration & Modus
##############################################################################

APP_VERSION = "3.31"


#SERVER_VERSION_CHECK_ONLY = False

##############################################################################
# 2) Hilfsfunktionen/Pfade
##############################################################################

def _get_app_base_dir() -> str:
    """
    Gibt den Verzeichnis-Pfad zurück, in dem deine *laufende* Executable liegt.
    Unterscheidet dabei nach Betriebssystem:
    
    - Windows OneFile => sys._MEIPASS
    - Windows OneFolder => sys._MEIPASS oder sys.executable
    - macOS => sys.executable
    - Linux => sys.executable
    - normaler Python => __file__
    """
    if getattr(sys, 'frozen', False):
        # Gefrorene App (PyInstaller, Nuitka, etc.)
        current_system = platform.system()
        if current_system == 'Windows':
            if hasattr(sys, '_MEIPASS'):
                return sys._MEIPASS
            else:
                return os.path.dirname(sys.executable)
        elif current_system == 'Darwin':  # macOS
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))


def _get_license_path() -> str:
    """
    Baut den Pfad zu 'license.lic' auf, basierend auf dem von _get_app_base_dir().
    """
    base_dir = _get_app_base_dir()
    return os.path.join(base_dir, "license.lic")


##############################################################################
# 3) Globale Variablen & Defaults
##############################################################################

# Ob wir einen Lizenz-Fingerprint abgleichen sollen (alter Mechanismus).

# Temp-Ordner
base_temp = tempfile.gettempdir()
TMP_KEYFRAME_DIR = os.path.join(base_temp, "my_vgsync_keyframes")

def get_temp_segments_dir() -> str:
    """
    Gibt den konfigurierten Temp-Ordner zurück, falls gesetzt,
    sonst ein systemweites Standard-Temp-Verzeichnis mit Unterordner.
    """
    s = QSettings("VGSync", "VGSync")
    custom_path = s.value("tempSegmentsDir", "", str)

    if custom_path and os.path.isdir(custom_path):
        return custom_path

    # OS-standard Temp-Verzeichnis + Unterordner
    return os.path.join(tempfile.gettempdir(), "my_vgsync_cut_segments")

#MY_GLOBAL_TMP_DIR = os.path.join(base_temp, "my_vgsync_cut_segments")

MY_GLOBAL_TMP_DIR = get_temp_segments_dir()



LOCAL_VERSION = ""



##############################################################################
# 5) Zusatz-Funktionen für QSettings usw.
##############################################################################

def is_disclaimer_accepted() -> bool:
    """
    Liest aus QSettings (Firma=VGSync, App=VGSync) den Bool-Wert 'disclaimerAccepted'.
    Default = False, falls nicht vorhanden.
    """
    s = QSettings("VGSync", "VGSync")
    val = s.value("disclaimerAccepted", False, type=bool)
    return val


def set_disclaimer_accepted():
    """
    Setzt in QSettings => 'disclaimerAccepted' = True.
    """
    s = QSettings("VGSync", "VGSync")
    s.setValue("disclaimerAccepted", True)


def reset_config():
    """
    Löscht alle in QSettings gespeicherten Werte
    (z. B. disclaimersAccepted, maptilerKey, etc.).
    """
    s = QSettings("VGSync", "VGSync")
    s.clear()


def is_edit_video_enabled() -> bool:
    """
    Beispiel-Funktion: Liest aus QSettings, ob 'video/editEnabled' True/False ist.
    """
    s = QSettings("VGSync", "VGSync")
    val = s.value("video/editEnabled", False, type=bool)
    return val


def set_edit_video_enabled(enabled: bool):
    """
    Schreibt in QSettings, ob 'video/editEnabled' True/False ist.
    """
    s = QSettings("VGSync", "VGSync")
    s.setValue("video/editEnabled", enabled)

"""
def check_app_version_and_reset_if_necessary():
   
   
    s = QSettings("VGSync", "VGSync")
    stored_version = s.value("appVersion", "", type=str)
    if stored_version != APP_VERSION:
        s.clear()
        s.setValue("appVersion", APP_VERSION)
        return True
    else:
        return False
"""    
    
def check_app_version_and_reset_if_necessary():
    """
    Überprüft, ob die gespeicherte Version in QSettings der aktuellen APP_VERSION
    entspricht. Falls nicht, wird nur der 'disclaimerAccepted'-Wert gelöscht
    und die neue APP_VERSION eingetragen.

    Gibt True zurück, wenn der Disclaimer neu gezeigt werden muss, sonst False.
    """
    s = QSettings("VGSync", "VGSync")
    stored_version = s.value("appVersion", "", type=str)
    if stored_version != APP_VERSION:
        s.setValue("appVersion", APP_VERSION)
        s.remove("disclaimerAccepted")  # Nur diesen Wert zurücksetzen
        return True
    else:
        return False
        
        
def clear_temp_directories():
    """Löscht alle Inhalte in den temporären Verzeichnissen."""
    for tmp_dir in [TMP_KEYFRAME_DIR, MY_GLOBAL_TMP_DIR]:
        if os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
                print(f"[INFO] Temp-Verzeichnis geleert: {tmp_dir}")
            except Exception as e:
                print(f"[WARN] Konnte {tmp_dir} nicht löschen: {e}")
        os.makedirs(tmp_dir, exist_ok=True)  # Neu anlegen, falls nötig        

def set_soft_opengl_enabled(enabled: bool):
    s = QSettings("VGSync", "VGSync")
    s.setValue("softOpenGLEnabled", enabled)

#def is_soft_opengl_enabled() -> bool:
#    s = QSettings("VGSync", "VGSync")
#    val = s.value("softOpenGLEnabled", False, type=bool)
#    return val

def is_soft_opengl_enabled():
    s = QSettings("VGSync", "VGSync")
    if s.contains("use_soft_opengl"):
        return s.value("use_soft_opengl", False, type=bool)
    else:
        # Standardverhalten: auf Linux True, sonst False
        if platform.system() == "Linux":
            return True  # Soft-OpenGL automatisch aktiv auf Linux
        else:
            return False  # Windows/macOS: Soft-OpenGL standardmäßig aus
