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

import os
import sys
import shutil
import platform


# ++ADD++  (Mac-spezifischer Monkeypatch + locale Setting)
current_os = platform.system()
if current_os == "Darwin":
    import ctypes.util
    import locale

    old_find_library = ctypes.util.find_library

    def custom_find_library(name: str) -> str:
        if name == "mpv":
            # Beispiel: Pfad zur Homebrew-liegenden libmpv.2.dylib
            return "/opt/homebrew/lib/libmpv.2.dylib"
        return old_find_library(name)

    ctypes.util.find_library = custom_find_library
    locale.setlocale(locale.LC_NUMERIC, "C")
# ++ADD++ Ende Mac-Patch

base_dir = os.path.dirname(os.path.abspath(__file__))

## das ist für die map:
os.environ["QSG_RHI_BACKEND"] = "opengl"

def resource_path(rel_path: str) -> str:
    """
    Gibt den absoluten Pfad zu einer Ressource (z.B. Icon) zurück.
    Funktioniert sowohl im normalen Python-Modus als auch im PyInstaller-Bundle.
    """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(base_dir, rel_path)

# ---------------------------------------------------------
# Zuerst mpv-Pfad einstellen, bevor wir "import mpv" machen
import path_manager

# wurde nach untern verschoben, damit wir den Pfad or dem laden angeben können ( mac)
#path_manager.ensure_mpv_library(parent_widget=None, base_dir=base_dir)

# ---------------------------------------------------------
# Jetzt erst den Rest importieren
import urllib.request
import datetime
import config
import path_manager  # zweites Mal import ist okay

# Qt-Sachen
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget, QSystemTrayIcon
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView #apparently we need to import it before the app starts

# Dein eigenes Zeug:
from config import (
    LOCAL_VERSION,
    TMP_KEYFRAME_DIR,
    MY_GLOBAL_TMP_DIR,
    is_disclaimer_accepted,
    set_disclaimer_accepted
)
from views.disclaimer_dialog import DisclaimerDialog
#from views.mainwindow import MainWindow

# NTP, JSON, etc.
#import ntplib
import json
from datetime import datetime as dt, timezone

# ---------------------------------------------------------
# Funktionen & Main

def clear_temp_segments_dir():
    if os.path.exists(MY_GLOBAL_TMP_DIR):
        try:
            shutil.rmtree(MY_GLOBAL_TMP_DIR)
        except Exception as e:
            print(f"[WARN] Could not remove temp directory: {e}")
    os.makedirs(MY_GLOBAL_TMP_DIR, exist_ok=True)


def center_mainwindow(window):
    frame_geo = window.frameGeometry()
    center_point = window.screen().availableGeometry().center()
    frame_geo.moveCenter(center_point)
    window.move(frame_geo.topLeft())


def check_ffmpeg_and_vlc_or_exit():
    """
    Ein simpler Check, ob ffmpeg und vlc in PATH vorhanden sind.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    vlc_path    = shutil.which("vlc")

    if not ffmpeg_path or not os.path.exists(ffmpeg_path):
        return False, "ffmpeg"
    # Falls du VLC zwingend brauchst, kannst du hier checken.
    # if not vlc_path or not os.path.exists(vlc_path):
    #     return False, "vlc"

    return True, ""


def main():
    # Workaround bei manchen Grafikkarten
    QGuiApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)

    app = QApplication(sys.argv)
    
    
    current_os = platform.system()
    
    # Zuerst mpv-Pfad einstellen, bevor wir "import mpv" machen
    #path_manager.ensure_mpv_library(parent_widget=None, base_dir=base_dir)
    # dann erst mainwindow starten:
    
    # ++ADD++: Windows/macOS Pfad-Check:
    if current_os == "Windows":
        if not path_manager.ensure_mpv(None):
            QMessageBox.critical(None, "Missing MPV (Windows)", "MPV (libmpv-2.dll) wurde nicht gefunden.")
            sys.exit(1)
        if not path_manager.ensure_ffmpeg(None):
            QMessageBox.critical(None, "Missing FFmpeg (Windows)", "FFmpeg wurde nicht gefunden.")
            sys.exit(1)

    elif current_os == "Darwin":
        if not path_manager.ensure_mpv_mac(None):
            QMessageBox.critical(None, "Missing MPV (macOS)", "libmpv.dylib wurde nicht gefunden.")
            sys.exit(1)
        if not path_manager.ensure_ffmpeg_mac(None):
            QMessageBox.critical(None, "Missing FFmpeg (macOS)", "FFmpeg wurde nicht gefunden.")
            sys.exit(1)
    else:
        QMessageBox.critical(None, "Unsupported OS", f"Dein Betriebssystem ({current_os}) wird derzeit nicht unterstützt.")
        sys.exit(1)
        ##
    # ++ADD++ Ende
    
    
    from views.mainwindow import MainWindow
    
    # Tray-Icon (nur Windows)
    if platform.system() == "Windows":
        # Pfad: icon/icon_icon.ico
        icon_file = resource_path(os.path.join("icon", "icon_icon.ico"))
        print("[DEBUG] Icon-Pfad =", icon_file, "| exists?", os.path.isfile(icon_file))

        app.setWindowIcon(QIcon(icon_file))
        trayIcon = QSystemTrayIcon(QIcon(icon_file), parent=None)
        trayIcon.show()

    # Temp-Verzeichnisse leeren
    config.clear_temp_directories()

    # Konfig/Version checken
    new_version_started = config.check_app_version_and_reset_if_necessary()
    if new_version_started:
        QMessageBox.warning(
            None,
            "New Version Detected",
            f"A new version ({config.APP_VERSION}) was launched. "
            "All your previous settings have been reset."
        )


    
    
   

    # Zusätzlicher Check
    parent_widget = QWidget()
    parent_widget.hide()
    ok2, missing = check_ffmpeg_and_vlc_or_exit()
    if not ok2:
        msg_box = QMessageBox(parent_widget)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("Missing Dependency")
        msg_box.setText(
            f"Could not find '{missing}'!\n"
            "Please install it (or provide it) and restart the program.\n\n"
            "Be sure it's in your PATH-Variable."
        )
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()
        sys.exit(0)

    # Disclaimer-Dialog (nur wenn nicht akzeptiert)
    if not is_disclaimer_accepted():
        dlg_disclaimer = DisclaimerDialog()
        dlg_disclaimer.show()
        app.processEvents()
        dlg_disclaimer.raise_()
        dlg_disclaimer.activateWindow()

        result = dlg_disclaimer.exec()
        if result == QDialog.Accepted:
            set_disclaimer_accepted()
        else:
            sys.exit(0)

    # Temp Ordner fürs Schneiden
    clear_temp_segments_dir()

    # Video-Editing on/off
    user_wants_editing = False
    if user_wants_editing:
        if os.path.exists(TMP_KEYFRAME_DIR):
            shutil.rmtree(TMP_KEYFRAME_DIR)
        os.makedirs(TMP_KEYFRAME_DIR, exist_ok=True)

    # Hauptfenster
    window = MainWindow(user_wants_editing=user_wants_editing)

    # Dynamische Anpassung an Bildschirm-Seitenverhältnis
    screen = app.primaryScreen()
    geometry = screen.availableGeometry()

    target_ratio = 16 / 9
    screen_ratio = geometry.width() / geometry.height()

    if screen_ratio >= target_ratio:
        new_height = int(geometry.height() * 0.9)
        new_width  = int(new_height * target_ratio)
    else:
        new_width  = int(geometry.width() * 0.9)
        new_height = int(new_width / target_ratio)

    window.resize(new_width, new_height)
    window.show()

    app.processEvents()
    center_mainwindow(window)
    window.raise_()
    window.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
