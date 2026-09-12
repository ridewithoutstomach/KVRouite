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
# config.py

import atexit
import os
import sys
import platform
import tempfile
import shutil
from PySide6.QtCore import QSettings

##############################################################################
# 1) Versions-Konfiguration & Modus
##############################################################################

APP_VERSION = "7.02"
# use 4.30_pre for a pre Version

# Aufrufoption "-menuup" (siehe KVRouite.py): das "..."-Menue der GPX-Tabelle
# nach oben aufklappen. Nur fuer Bildschirmaufnahmen; wird beim Start gesetzt
# und sonst nirgends gespeichert.
MORE_MENU_OPENS_UPWARD = False


#SERVER_VERSION_CHECK_ONLY = False

##############################################################################
# 2) Hilfsfunktionen/Pfade
##############################################################################

def programm_ordner() -> str:
    """Der Ordner, in dem das laufende Programm liegt.

    Gepackt ist das der Ordner der ausfuehrbaren Datei - unter Windows der mit
    KVRouite.exe, im macOS-Buendel Contents/MacOS. Ungepackt das
    Projektverzeichnis. Bewusst NICHT sys._MEIPASS: das ist bei einem
    onedir-Build der Unterordner _internal, und die Symbole liegen daneben,
    nicht darin.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def datenordner_liste():
    """Alle Orte, an denen mitgelieferte Dateien liegen koennen.

    Es sind mehrere, und das hat einen Grund: die beiden Builds legen nicht
    alles am selben Ort ab. Symbole und die Kartenseite liegen NEBEN dem
    Programm, das Kinomap-Logo und die PDF unter Windows in _internal (also
    sys._MEIPASS), im macOS-Buendel dagegen in Contents/Resources. Statt einen
    der Builds umzustellen und dabei den anderen zu brechen, wird hier
    gesucht - in dieser Reihenfolge.
    """
    orte = [programm_ordner()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        orte.append(meipass)
    if getattr(sys, "frozen", False):
        # macOS-Buendel: Contents/MacOS -> Contents/Resources
        contents = os.path.dirname(programm_ordner())
        orte.append(os.path.join(contents, "Resources"))
    orte.append(os.path.dirname(os.path.abspath(__file__)))
    # Reihenfolge behalten, Doppelte raus
    gesehen, sauber = set(), []
    for o in orte:
        if o and o not in gesehen:
            gesehen.add(o)
            sauber.append(o)
    return sauber


def finde_datei(*teile) -> str:
    """Eine mitgelieferte Datei suchen. Rueckgabe: der gefundene Pfad.

    Wird nichts gefunden, kommt der Pfad im ersten Ort zurueck - dann zeigt
    eine Fehlermeldung wenigstens dorthin, wo die Datei erwartet wurde.
    """
    for wurzel in datenordner_liste():
        kandidat = os.path.join(wurzel, *teile)
        if os.path.exists(kandidat):
            return kandidat
    return os.path.join(datenordner_liste()[0], *teile)


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


##############################################################################
# 3) Globale Variablen & Defaults
##############################################################################

# Ob wir einen Lizenz-Fingerprint abgleichen sollen (alter Mechanismus).

# Temp-Ordner
#
# Aufbau (siehe auch prepare_instance_temp_dir):
#
#   <Basis>/my_KVRouite_cut_segments/      <- Behaelter, wird NIE geloescht
#       run_<pid>_<zufall>/                <- gehoert genau einer laufenden App
#           instance.lock                  <- solange offen, lebt der Besitzer
#           segments/                      <- MY_GLOBAL_TMP_DIR
#           keyframes/                     <- TMP_KEYFRAME_DIR
#
# Frueher teilten sich alle Instanzen einen Ordner. Startete man eine zweite
# App, loeschte deren Start den Ordner der ersten - ein laufender Render brach
# ab. Ausserdem lief "shutil.rmtree" auf den in den Einstellungen gesetzten
# Pfad selbst; ein eigener Ordner wie /home/x/Videos/temp waere dabei
# komplett geloescht worden. Beides ist mit dem Aufbau oben erledigt: geloescht
# wird nur der eigene run-Ordner, und der Behaelter liegt immer eine Ebene
# unter dem, was der Benutzer eingestellt hat.

base_temp = tempfile.gettempdir()


def get_temp_segments_container() -> str:
    """
    Der Ordner, in dem die Instanz-Ordner liegen.

    Ist in den Einstellungen ein eigener Pfad hinterlegt, legen wir darin einen
    Unterordner an, statt den Pfad selbst zu benutzen - so bleibt alles, was
    sonst noch darin liegt, unberuehrt.
    """
    s = QSettings("KVRouite", "KVRouite")
    custom_path = s.value("tempSegmentsDir", "", str)
    base = custom_path if (custom_path and os.path.isdir(custom_path)) else base_temp
    return os.path.join(base, "my_KVRouite_cut_segments")


TEMP_SEGMENTS_CONTAINER = get_temp_segments_container()

_INSTANCE_DIR = os.path.join(
    TEMP_SEGMENTS_CONTAINER,
    "run_%d_%s" % (os.getpid(), os.urandom(4).hex())
)
_INSTANCE_LOCK_PATH = os.path.join(_INSTANCE_DIR, "instance.lock")
_instance_lock_file = None   # bleibt offen, solange die App laeuft

MY_GLOBAL_TMP_DIR = os.path.join(_INSTANCE_DIR, "segments")
TMP_KEYFRAME_DIR = os.path.join(_INSTANCE_DIR, "keyframes")
# Vorgerenderte Blenden fuer die GES-Vorschau. Kleine Dateien: rund 4 MB je
# Blende (2 s, 1280 breit), unabhaengig von der Groesse der Quelldateien.
TMP_FADE_DIR = os.path.join(_INSTANCE_DIR, "fades")


def _lock_exclusive(fh) -> bool:
    """Versucht, die Datei exklusiv zu sperren, ohne zu warten."""
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _is_dir_in_use(lock_path: str) -> bool:
    """
    True, wenn eine andere laufende App diesen Ordner besitzt.

    Der Test laeuft ueber die Sperre und nicht ueber eine PID: eine PID kann
    nach einem Absturz laengst einem anderen Programm gehoeren. Die Sperre gibt
    das Betriebssystem beim Prozessende immer frei, auch bei kill -9.
    Im Zweifel (Datei nicht lesbar, unbekannter Fehler) sagen wir "in Benutzung"
    und fassen den Ordner nicht an.
    """
    if not os.path.exists(lock_path):
        return False
    try:
        fh = open(lock_path, "a+")
    except OSError:
        return True
    try:
        if not _lock_exclusive(fh):
            return True
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        return False
    finally:
        fh.close()


def prepare_instance_temp_dir():
    """
    Legt den eigenen Instanz-Ordner an und haelt die Sperre.

    Wird beim Start aufgerufen. Schlaegt das Sperren fehl, laeuft die App
    trotzdem weiter - dann wird dieser Ordner spaeter eben nicht automatisch
    aufgeraeumt, was harmloser ist als ein Abbruch beim Start.
    """
    global _instance_lock_file
    os.makedirs(MY_GLOBAL_TMP_DIR, exist_ok=True)
    os.makedirs(TMP_FADE_DIR, exist_ok=True)
    os.makedirs(TMP_KEYFRAME_DIR, exist_ok=True)
    if _instance_lock_file is not None:
        return
    try:
        fh = open(_INSTANCE_LOCK_PATH, "a+")
        if _lock_exclusive(fh):
            _instance_lock_file = fh
        else:
            fh.close()
            print("[WARN] Could not lock the temp folder of this instance.")
    except OSError as e:
        print(f"[WARN] Could not create the lock file: {e}")
    # Greift auch bei jedem sys.exit() - etwa wenn die App wegen einer fehlenden
    # Abhaengigkeit oder abgelehntem Disclaimer abbricht. Nur ein Absturz oder
    # kill -9 kommt daran vorbei, und dafuer gibt es cleanup_orphaned_temp_dirs().
    atexit.register(release_instance_temp_dir)


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def cleanup_orphaned_temp_dirs():
    """
    Entfernt Instanz-Ordner, deren App nicht mehr laeuft.

    Damit beantwortet sich der Absturzfall von selbst: stuerzen zwei Instanzen
    ab, findet der naechste Start beide Ordner ohne gehaltene Sperre und raeumt
    sie weg. Ordner einer noch laufenden Instanz bleiben unangetastet.

    Zusaetzlich fliegen lose Dateien direkt im Behaelter raus - die stammen aus
    aelteren Versionen, die noch keinen Instanz-Ordner kannten. Der Behaelter
    selbst gehoert immer uns (bei einem eigenen Pfad liegt er als Unterordner
    darin), deshalb ist das gefahrlos.
    """
    removed_dirs = 0
    freed = 0
    try:
        os.makedirs(TEMP_SEGMENTS_CONTAINER, exist_ok=True)
        entries = os.listdir(TEMP_SEGMENTS_CONTAINER)
    except OSError as e:
        print(f"[WARN] Temp folder not accessible: {e}")
        return

    for name in entries:
        full = os.path.join(TEMP_SEGMENTS_CONTAINER, name)
        if full == _INSTANCE_DIR:
            continue
        try:
            if os.path.isdir(full):
                if not name.startswith("run_"):
                    continue
                if _is_dir_in_use(os.path.join(full, "instance.lock")):
                    continue
                size = _dir_size(full)
                shutil.rmtree(full)
                removed_dirs += 1
                freed += size
            else:
                size = os.path.getsize(full)
                os.remove(full)
                freed += size
        except OSError as e:
            print(f"[WARN] Could not remove {full}: {e}")

    # Der Keyframe-Ordner lag frueher als eigener Ordner im System-Temp. Seit
    # er im Instanz-Ordner liegt, schreibt niemand mehr dorthin - er bliebe
    # sonst fuer immer liegen. Er enthaelt ausschliesslich unsere CSV-Dateien
    # und wurde von der alten Version bei jedem Start ohnehin geleert.
    legacy_keyframes = os.path.join(base_temp, "my_KVRouite_keyframes")
    if os.path.isdir(legacy_keyframes):
        try:
            freed += _dir_size(legacy_keyframes)
            shutil.rmtree(legacy_keyframes)
            print("[INFO] Removed the old keyframe folder "
                  f"{legacy_keyframes}.")
        except OSError as e:
            print(f"[WARN] Could not remove {legacy_keyframes}: {e}")

    if removed_dirs or freed:
        print("[INFO] Removed %d leftover temp folder(s) (%.1f GB freed)."
              % (removed_dirs, freed / (1024 ** 3)))


def release_instance_temp_dir():
    """Beim sauberen Beenden: Sperre freigeben und den eigenen Ordner loeschen."""
    global _instance_lock_file
    if _instance_lock_file is not None:
        try:
            _instance_lock_file.close()
        except OSError:
            pass
        _instance_lock_file = None
    try:
        if os.path.isdir(_INSTANCE_DIR):
            shutil.rmtree(_INSTANCE_DIR)
    except OSError as e:
        print(f"[WARN] Could not remove the temp folder of this instance: {e}")



LOCAL_VERSION = ""



##############################################################################
# 5) Zusatz-Funktionen für QSettings usw.
##############################################################################

def is_disclaimer_accepted() -> bool:
    """
    Liest aus QSettings (Firma=KVRouite, App=KVRouite) den Bool-Wert 'disclaimerAccepted'.
    Default = False, falls nicht vorhanden.
    """
    s = QSettings("KVRouite", "KVRouite")
    val = s.value("disclaimerAccepted", False, type=bool)
    return val


def set_disclaimer_accepted():
    """
    Setzt in QSettings => 'disclaimerAccepted' = True.
    """
    s = QSettings("KVRouite", "KVRouite")
    s.setValue("disclaimerAccepted", True)


def reset_config():
    """
    Löscht alle in QSettings gespeicherten Werte
    (z. B. disclaimersAccepted, maptilerKey, etc.).
    """
    s = QSettings("KVRouite", "KVRouite")
    s.clear()


def is_edit_video_enabled() -> bool:
    """
    Beispiel-Funktion: Liest aus QSettings, ob 'video/editEnabled' True/False ist.
    """
    s = QSettings("KVRouite", "KVRouite")
    val = s.value("video/editEnabled", False, type=bool)
    return val

    
def check_app_version_and_reset_if_necessary():
    """
    Überprüft, ob die gespeicherte Version in QSettings der aktuellen APP_VERSION
    entspricht. Falls nicht, wird nur der 'disclaimerAccepted'-Wert gelöscht
    und die neue APP_VERSION eingetragen.

    Gibt True zurück, wenn der Disclaimer neu gezeigt werden muss, sonst False.
    """
    s = QSettings("KVRouite", "KVRouite")
    stored_version = s.value("appVersion", "", type=str)
    if stored_version != APP_VERSION:
        s.setValue("appVersion", APP_VERSION)
        s.remove("disclaimerAccepted")  # Nur diesen Wert zurücksetzen
        return True
    else:
        return False
        
        
def clear_temp_directories():
    """
    Leert die Arbeitsordner DIESER Instanz.

    Beide Pfade liegen im eigenen run-Ordner, andere laufende Instanzen sind
    davon nicht betroffen. Die Sperrdatei liegt eine Ebene darueber und bleibt
    erhalten.
    """
    for tmp_dir in [TMP_KEYFRAME_DIR, MY_GLOBAL_TMP_DIR]:
        if os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
                print(f"[INFO] Temp-Verzeichnis geleert: {tmp_dir}")
            except Exception as e:
                print(f"[WARN] Konnte {tmp_dir} nicht löschen: {e}")
        os.makedirs(tmp_dir, exist_ok=True)  # Neu anlegen, falls nötig        


def is_soft_opengl_enabled():
    s = QSettings("KVRouite", "KVRouite")
    if s.contains("use_soft_opengl"):
        return s.value("use_soft_opengl", False, type=bool)
    else:
        # Standardverhalten: auf Linux True, sonst False
        if platform.system() == "Linux":
            return True  # Soft-OpenGL automatisch aktiv auf Linux
        else:
            return False  # Windows/macOS: Soft-OpenGL standardmäßig aus
