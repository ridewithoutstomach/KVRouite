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
# path_manager.py

import os
import platform
import shutil
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import QSettings
import ctypes



def add_to_process_path(path_str: str):
    if not path_str:
        return
    old_path = os.environ.get("PATH", "")
    new_path = path_str + os.pathsep + old_path
    os.environ["PATH"] = new_path

def is_ffmpeg_in_folder(folder: str) -> bool:
    if not folder or not os.path.isdir(folder):
        return False
    exe_name = "ffmpeg.exe" if platform.system().lower().startswith("win") else "ffmpeg"
    path_exe = os.path.join(folder, exe_name)
    return os.path.isfile(path_exe)

def find_ffmpeg_folder() -> str:
    """
    1) QSettings
    2) Standard Windows paths
    3) which("ffmpeg")
    Returns a folder path or "" if none found.
    """
    # 1) QSettings
    s = QSettings("KVRouite", "KVRouite")
    stored_folder = s.value("paths/ffmpeg", "", type=str)
    if is_ffmpeg_in_folder(stored_folder):
        return stored_folder

    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(base_dir, "ffmpeg", "bin")
    if is_ffmpeg_in_folder(local_path):
        return local_path


    # 2) Windows standard paths
    if platform.system().lower().startswith("win"):
        possible_paths = [
            r"C:\Program Files\FFmpeg\bin",
            r"C:\Program Files (x86)\FFmpeg\bin",
            r"C:\ffmpeg\bin"
        ]
        for p in possible_paths:
            if is_ffmpeg_in_folder(p):
                return p

    # 3) which("ffmpeg")
    ffmpeg_exec = shutil.which("ffmpeg")
    if ffmpeg_exec:
        return os.path.dirname(ffmpeg_exec)

    return ""

def ensure_mpv(parent_widget) -> bool:
    """
    Stellt sicher, dass libmpv-2.dll verfügbar ist.
    1) Versucht per find_mpv_folder() etwas zu finden.
    2) Wenn nichts gefunden -> Dialog zum Ordnerauswählen.
    3) Prüft Gültigkeit -> Speichert in QSettings -> passt PATH an.
    
    Gibt True zurück, wenn am Ende alles korrekt gefunden/eingestellt wurde,
    sonst False.
    """
    s = QSettings("KVRouite", "KVRouite")
    folder = find_mpv_folder()

    if folder and is_valid_mpv_folder(folder):
        # Falls der Pfad aus QSettings oder Fallback kam,
        # und QSettings derzeit etwas anderes gespeichert hat:
        stored_in_settings = s.value("paths/mpv", "", type=str)
        if stored_in_settings != folder:
            s.setValue("paths/mpv", folder)
    else:
        # => Info-Meldung anzeigen, bevor wir den Datei-Dialog öffnen
        QMessageBox.information(
            parent_widget,
            "MPV library required",
            "Please select the folder where libmpv-2.dll is located.\n"
            "Example (Windows):\n"
            "  C:\\mpv\\lib\n\n"
            "This is needed for preview and playback."
        )
        chosen = QFileDialog.getExistingDirectory(parent_widget, "Select MPV Folder")
        if not chosen:
            return False
        if not is_valid_mpv_folder(chosen):
            QMessageBox.critical(
                parent_widget,
                "MPV Missing",
                f"No valid libmpv-2.dll found in:\n{chosen}"
            )
            return False

        # => store
        s.setValue("paths/mpv", chosen)
        folder = chosen

    # Nun folder und libmpv-2.dll in PATH eintragen
    mpv_dll_path = os.path.join(folder, "libmpv-2.dll")
    os.environ["MPV_LIBRARY_PATH"] = mpv_dll_path
    add_to_process_path(folder)

    # Debug-Ausgaben (optional)
    print("[DEBUG] Final MPV folder =", folder)
    print("[DEBUG] MPV_LIBRARY_PATH =", os.environ["MPV_LIBRARY_PATH"])

    return True

    
def find_mpv_folder() -> str:
    """
    Sucht nach libmpv-2.dll:
      1) QSettings
      2) lokaler Fallback mpv/lib
    Gibt einen Ordnerpfad zurück oder "" wenn nichts gefunden.
    """
    s = QSettings("KVRouite", "KVRouite")
    stored_folder = s.value("paths/mpv", "", type=str)
    if is_valid_mpv_folder(stored_folder):
        return stored_folder

    # Lokaler Fallback, z.B. <base_dir>/mpv/lib
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fallback_dir = os.path.join(base_dir, "mpv", "lib")
    if is_valid_mpv_folder(fallback_dir):
        return fallback_dir

    return ""
    
    

def ensure_ffmpeg(parent_widget) -> bool:
    """
    Ensures ffmpeg is available. 
    If a folder is auto-detected (standard path or which), 
    we store it in QSettings so it shows up in "Show current path".
    If not found -> prompt user to pick a folder.
    """
    s = QSettings("KVRouite", "KVRouite")
    folder = find_ffmpeg_folder()

    if folder and is_ffmpeg_in_folder(folder):
        # => falls QSettings leer oder ungültig war, aber wir 
        #    jetzt einen standard Pfad gefunden haben => in QSettings packen
        stored_in_settings = s.value("paths/ffmpeg", "", type=str)
        if stored_in_settings != folder:
            s.setValue("paths/ffmpeg", folder)

        add_to_process_path(folder)
        return True
    else:
        # => Show info BEFORE opening folder dialog
        QMessageBox.information(
            parent_widget,
            "FFmpeg Required",
            "Please select the folder where FFmpeg is installed.\n"
            "Example (Windows):\n"
            "  C:\\ffmpeg\\bin\n"
            "  C:\\Program Files\\FFmpeg\\bin\n\n"
            "This is needed for video cutting and export."
        )
        chosen = QFileDialog.getExistingDirectory(parent_widget, "Select FFmpeg Folder")
        if not chosen:
            return False
        if not is_ffmpeg_in_folder(chosen):
            QMessageBox.critical(
                parent_widget,
                "FFmpeg Missing",
                f"No valid ffmpeg executable found in:\n{chosen}"
            )
            return False

        # => store
        s.setValue("paths/ffmpeg", chosen)
        add_to_process_path(chosen)
        return True
        
    def get_license_path():
        """
        Ermittelt license.lic neben app.py (bzw. dist/app).
        """
        base_dir = get_base_dir()
        return os.path.join(base_dir, "license.lic")
        
        
def is_valid_mpv_folder(folder: str) -> bool:
    """
    Prüft, ob in dem Ordner 'folder' eine libmpv-2.dll vorhanden ist 
    und ob sie sich via ctypes laden lässt.
    Gibt True zurück, falls ja.
    """
    if not folder or not os.path.isdir(folder):
        return False
    dll_path = os.path.join(folder, "libmpv-2.dll")
    if not os.path.isfile(dll_path):
        return False

    # Optional: Test via ctypes
    try:
        _ = ctypes.cdll.LoadLibrary(dll_path)
        return True
    except Exception as e:
        print(f"[WARN] libmpv-2.dll in {folder} konnte nicht geladen werden: {e}")
        return False


def ensure_mpv_library(parent_widget, base_dir: str) -> None:
    
    ensure_mpv(parent_widget)
    
    
### mac:
def is_valid_mpv_folder_mac(folder: str) -> bool:
    """
    Prüft, ob in dem Ordner 'folder' eine libmpv.dylib/libmpv.1.dylib vorhanden ist
    und ob sie sich via ctypes laden lässt.
    """
    if not folder or not os.path.isdir(folder):
        return False

    possible_names = ["libmpv.1.dylib", "libmpv.dylib", "libmpv.2.dylib"]  # je nach Version
    found_any = False
    dll_path = ""
    for name in possible_names:
        test_path = os.path.join(folder, name)
        if os.path.isfile(test_path):
            dll_path = test_path
            found_any = True
            break

    if not found_any:
        return False

    # Test via ctypes:
    try:
        _ = ctypes.cdll.LoadLibrary(dll_path)
        return True
    except Exception as e:
        print(f"[WARN macOS] libmpv konnte nicht geladen werden: {e}")
        return False


def find_mpv_folder_mac() -> str:
    """
    macOS: Sucht nach libmpv.dylib/libmpv.1.dylib:
      1) QSettings (paths/mpv_mac)
      2) Lokaler Fallback (<base_dir>/mpv/lib)
      3) Mehrere Standardpfade (Homebrew, MacPorts, ...)
      4) Falls nichts gefunden -> ""
    """
    s = QSettings("KVRouite", "KVRouite")
    stored_folder = s.value("paths/mpv_mac", "", type=str)
    if is_valid_mpv_folder_mac(stored_folder):
        return stored_folder

    # 2) Lokaler Fallback, falls du mpv beilegst in <base_dir>/mpv/lib
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fallback_dir = os.path.join(base_dir, "mpv", "lib")
    if is_valid_mpv_folder_mac(fallback_dir):
        return fallback_dir

    # 3) Liste mit Standardpfaden
    possible_mpv_dirs = [
        "/usr/local/lib",     # Homebrew (Intel)
        "/opt/homebrew/lib",  # Homebrew (Apple Silicon)
        "/opt/local/lib",     # MacPorts
        # ggf. mehr
    ]
    for pathdir in possible_mpv_dirs:
        if is_valid_mpv_folder_mac(pathdir):
            return pathdir

    # 4) Nichts gefunden
    return ""


def ensure_mpv_mac(parent_widget) -> bool:
    """
    Stellt sicher, dass libmpv.dylib (macOS) verfügbar ist.
    1) Versucht per find_mpv_folder_mac() etwas zu finden.
    2) Wenn nichts gefunden -> Dialog zum Ordnerauswählen.
    3) Prüft Gültigkeit -> Speichert in QSettings -> passt PATH/MPV_LIBRARY_PATH an.
    
    Gibt True zurück, wenn alles gefunden/eingestellt wurde, sonst False.
    """
    s = QSettings("KVRouite", "KVRouite")
    folder = find_mpv_folder_mac()

    if folder and is_valid_mpv_folder_mac(folder):
        # Falls der Pfad aus QSettings oder Fallback kam,
        # und QSettings derzeit etwas anderes gespeichert hat:
        stored_in_settings = s.value("paths/mpv_mac", "", type=str)
        if stored_in_settings != folder:
            s.setValue("paths/mpv_mac", folder)
    else:
        QMessageBox.information(
            parent_widget,
            "MPV library required (macOS)",
            "Bitte wähle den Ordner, in dem libmpv.dylib/libmpv.1.dylib liegt.\n\n"
            "Beispiel:\n"
            "  /usr/local/lib\n"
            "  /opt/homebrew/lib\n\n"
            "Dies wird für Preview und Playback benötigt."
        )
        chosen = QFileDialog.getExistingDirectory(parent_widget, "Select MPV Folder (macOS)")
        if not chosen:
            return False
        if not is_valid_mpv_folder_mac(chosen):
            QMessageBox.critical(
                parent_widget,
                "MPV Missing (macOS)",
                f"In {chosen} wurde keine gültige libmpv.dylib gefunden."
            )
            return False

        # => store
        s.setValue("paths/mpv_mac", chosen)
        folder = chosen

    # Nun folder + libmpv in PATH und MPV_LIBRARY_PATH eintragen
    # Wir suchen nochmal den tatsächlichen Dateinamen:
    possible_names = ["libmpv.1.dylib", "libmpv.dylib"]
    for name in possible_names:
        test_path = os.path.join(folder, name)
        if os.path.isfile(test_path):
            os.environ["MPV_LIBRARY_PATH"] = test_path
            break

    add_to_process_path(folder)  # optional; für macOS kann auch DYLD_LIBRARY_PATH nötig sein

    print("[DEBUG] Final MPV folder (macOS) =", folder)
    print("[DEBUG] MPV_LIBRARY_PATH (macOS) =", os.environ["MPV_LIBRARY_PATH"])
    return True

def find_ffmpeg_folder_mac() -> str:
    """
    macOS: Sucht nach ffmpeg (ohne .exe):
      1) QSettings
      2) which("ffmpeg")
      3) Mehrere Standardpfade (Homebrew, MacPorts, ...)
      4) Falls nichts gefunden -> ""
    """
    s = QSettings("KVRouite", "KVRouite")
    stored_folder = s.value("paths/ffmpeg_mac", "", type=str)
    if is_ffmpeg_in_folder(stored_folder):
        return stored_folder

    # 2) systemweiter PATH prüfen
    ffmpeg_exec = shutil.which("ffmpeg")
    if ffmpeg_exec:
        return os.path.dirname(ffmpeg_exec)

    # 3) Liste mit Standardpfaden (einfach erweiterbar)
    possible_ffmpeg_dirs = [
        "/usr/local/bin",     # Homebrew (Intel)
        "/opt/homebrew/bin",  # Homebrew (Apple Silicon)
        "/opt/local/bin",     # MacPorts
        # Hier kannst du beliebige weitere Pfade ergänzen:
        # "/Applications/ffmpeg/bin",
        # "/User/DeinName/Programme/ffmpeg/bin",
        # usw.
    ]
    for pathdir in possible_ffmpeg_dirs:
        if is_ffmpeg_in_folder(pathdir):
            return pathdir

    # 4) Keiner der Pfade war erfolgreich
    return ""



def ensure_ffmpeg_mac(parent_widget) -> bool:
    """
    Stellt sicher, dass ffmpeg (macOS) verfügbar ist.
    1) Versucht find_ffmpeg_folder_mac().
    2) Falls nicht gefunden -> lässt User den Ordner wählen.
    3) Prüft ffmpeg-Executable -> schreibt in QSettings -> PATH
    """
    s = QSettings("KVRouite", "KVRouite")
    folder = find_ffmpeg_folder_mac()

    if folder and is_ffmpeg_in_folder(folder):
        stored_in_settings = s.value("paths/ffmpeg_mac", "", type=str)
        if stored_in_settings != folder:
            s.setValue("paths/ffmpeg_mac", folder)

        add_to_process_path(folder)
        return True
    else:
        QMessageBox.information(
            parent_widget,
            "FFmpeg Required (macOS)",
            "Bitte wähle den Ordner, in dem ffmpeg liegt.\n\n"
            "Beispiel:\n"
            "  /usr/local/bin\n"
            "  /opt/homebrew/bin\n\n"
            "Ohne FFmpeg sind Video-Cutting und -Export nicht möglich."
        )
        chosen = QFileDialog.getExistingDirectory(parent_widget, "Select FFmpeg Folder (macOS)")
        if not chosen:
            return False
        if not is_ffmpeg_in_folder(chosen):
            QMessageBox.critical(
                parent_widget,
                "FFmpeg Missing (macOS)",
                f"Keine gültige ffmpeg-Executable in:\n{chosen}"
            )
            return False

        s.setValue("paths/ffmpeg_mac", chosen)
        add_to_process_path(chosen)
        return True    
    
def ensure_mpv_linux(path=None):
    # Prüfe systemweite Installation oder direkten Pfad
    candidates = [
        path,
        "/usr/lib/x86_64-linux-gnu/libmpv.so.2",
        "/usr/local/lib/libmpv.so.2",
        "libmpv.so.2"
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return True
    return False
        
