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

import os
import sys
import shutil
import platform





# --- Debug/Verbose-Schalter + Konsole behandeln (nur Windows) ---
import sys, platform, builtins

REAL_STDOUT = sys.__stdout__
REAL_STDERR = sys.__stderr__


def _konsole_vertraegt_sonderzeichen():
    """Pfeile, Haken und Warnzeichen in print() nicht zum Absturz werden lassen.

    Die Windows-Konsole laeuft je nach Codepage auf cp1252. Ein "->" als
    Unicode-Pfeil, ein Haken oder ein Warndreieck in einer Debug-Ausgabe wirft
    dort UnicodeEncodeError - mitten im Programm, an einer voellig
    harmlosen Stelle. Gemessen beim Start des gepackten Programms:
    map_widget.py brach an einem "=>"-Pfeil ab.

    errors="replace" ersetzt solche Zeichen durch "?" statt zu werfen. Betrifft
    nur die Anzeige; kein Text der Anwendung haengt daran.
    """
    for strom in (sys.stdout, sys.stderr, REAL_STDOUT, REAL_STDERR):
        try:
            strom.reconfigure(errors="replace")
        except Exception:
            pass


_konsole_vertraegt_sonderzeichen()

def force_print(*args, sep=" ", end="\n"):
    REAL_STDOUT.write(sep.join(map(str, args)) + end)
    REAL_STDOUT.flush()

def force_error(*args, sep=" ", end="\n"):
    REAL_STDERR.write(sep.join(map(str, args)) + end)
    REAL_STDERR.flush()
# ---------------------------------------------------------------------------
# Aufrufoptionen
# ---------------------------------------------------------------------------
# Ein Strich oder zwei - das Programm nimmt beides. "-v" gibt es seit jeher,
# "--selftest" kam spaeter dazu; wer sich an die eine Schreibweise gewoehnt
# hat, soll bei der anderen nicht auflaufen. Es gelten also "-v", "--v",
# "-verbose" und "--verbose" als dasselbe, ebenso "-selftest" wie
# "--selftest".
#
# Frueher wurde nur nach Zeichenketten in der ganzen Kommandozeile gesucht
# (" -v" in ...). Damit fiel "-verbose" durch, und ein Tippfehler wie
# "--seftest" startete stillschweigend die Oberflaeche, ohne ein Wort dazu -
# genau das ist am 03.09.2026 beim Testen passiert.

_OPTIONEN = {
    "?":          "help",
    "h":          "help",
    "help":       "help",
    "v":          "verbose",
    "verbose":    "verbose",
    "selftest":   "selftest",
    "screenshot": "screenshot",
    "menuup":     "menuup",
    "menu-up":    "menuup",
}

#: Wie die Optionen in einer Meldung aufgezaehlt werden.
_OPTIONEN_HILFE = (
    "  -? / -h / --help    show this list and exit",
    "  -v  / --verbose    more output on the console",
    "  -selftest / --selftest    check this installation and exit",
    "  -screenshot / --screenshot    load a test project, play it, save three pictures and exit",
    "  -menuup / --menu-up    open the '...' menu of the GPX table upwards (for screen recordings)",
)


def _optionen_lesen(argv):
    """(erkannte Optionen, unbekannte Argumente).

    Alles, was mit einem Strich beginnt, ist eine Option. Alles andere ist ein
    Dateiname und wird hier nicht angefasst - siehe _file_arg_from_cli.
    """
    erkannt, unbekannt = set(), []
    for arg in argv[1:]:
        if not arg.startswith("-"):
            continue
        name = arg.lstrip("-").lower()
        if name in _OPTIONEN:
            erkannt.add(_OPTIONEN[name])
        else:
            unbekannt.append(arg)
    return erkannt, unbekannt


def _hilfe_ausgeben():
    force_print("Usage: KVRouite [option ...] [file.KVRouiteproj | file.gpx | file.fit | video]")
    force_print("Options (one or two dashes, both are accepted):")
    for _zeile in _OPTIONEN_HILFE:
        force_print(_zeile)


# Hilfe HIER, noch vor allem anderen. Weiter unten wird fuer den Normalbetrieb
# die Konsole stummgeschaltet (Deskriptoren auf NUL, Fenster versteckt);
# danach kaeme kein Wort mehr an. Wer "-?" tippt, will nur die Liste sehen -
# ohne Qt, ohne Konsolenumbau, ohne Oberflaeche.
if "help" in _optionen_lesen(sys.argv)[0]:
    _hilfe_ausgeben()
    sys.exit(0)


def _is_verbose():
    erkannt, _unbekannt = _optionen_lesen(sys.argv)
    if "verbose" in erkannt:
        return True
    # Beim Selbsttest muss die Ausgabe sichtbar bleiben - sie IST das
    # Ergebnis. Ohne das laeuft er zwar, sagt aber nichts, und ein
    # Rueckgabewert allein hilft bei der Fehlersuche nicht weiter.
    if "selftest" in erkannt:
        return True
    try:
        from PySide6.QtCore import QSettings
        if QSettings("KVRouite","KVRouite").value("app/debug", False, type=bool):
            return True
    except Exception:
        pass
    return False

DEBUG = _is_verbose()

# Python-Prints im Non-Verbose vollständig stummschalten (ohne Performance-Kosten)
if not DEBUG:
    def _noop_print(*args, **kwargs): 
        return None
    builtins.print = _noop_print

    class _NullWriter:
        def write(self, *_args, **_kw): return 0
        def flush(self): pass
    sys.stdout = _NullWriter()
    sys.stderr = _NullWriter()

    # Auch die Ausgaben, die NICHT aus Python kommen - aber nur in der
    # ausgelieferten EXE.
    #
    # sys.stdout/sys.stderr zu ersetzen wirkt nur auf Python. Bibliotheken, die
    # als DLL geladen werden, schreiben an Python vorbei direkt auf die
    # Dateideskriptoren 1 und 2. GLib tut das beim Start und meldet dort, dass
    # es sein Proxy-Modul nicht laden kann (giolibproxy.dll - eine kaputte
    # Abhaengigkeit in den GStreamer-Wheels, folgenlos: GIO nimmt dann seinen
    # Platzhalter, und KVRouite macht seine Netzzugriffe ohnehin ueber Python).
    #
    # Nur gepackt umleiten: wer "python KVRouite.py" aufruft, entwickelt und
    # will die Ausgaben der Bibliotheken sehen. Ihm hier die Deskriptoren
    # wegzunehmen macht die Konsole still, obwohl er das Gegenteil braucht.
    if getattr(sys, "frozen", False):
        try:
            _leer = os.open(os.devnull, os.O_RDWR)
            os.dup2(_leer, 1)
            os.dup2(_leer, 2)
            if _leer > 2:
                os.close(_leer)
        except Exception:
            # Gepackt ohne Fenster gibt es die Deskriptoren teils gar nicht.
            # Dann ist ohnehin nichts zu sehen.
            pass

# Konsolenfenster herrichten - Titel, Puffer leeren, Hinweis, verstecken.
#
# Ausdruecklich NUR in der ausgelieferten EXE. Beim Aufruf ueber
# "python KVRouite.py" gehoert die Konsole dem Entwickler: dort darf die App
# weder den Titel umbiegen noch den Puffer leeren - das loescht alles, was
# vorher in dem Fenster stand.
if platform.system() == "Windows" and getattr(sys, "frozen", False):
    try:
        import ctypes, ctypes.wintypes as wt
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32

        hwnd = k32.GetConsoleWindow()
        if hwnd:
            # Titel setzen (auch wenn Fenster versteckt ist)
            k32.SetConsoleTitleW("KVRouite DEBUG Konsole" if DEBUG else "KVRouite Konsole - Don’t Close")

            if not DEBUG:
                # Konsole 'optisch leer' machen: Puffer löschen
                # 1) Screen-Buffer-Info holen
                class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                    _fields_ = [
                        ("dwSize", wt._COORD),
                        ("dwCursorPosition", wt._COORD),
                        ("wAttributes", ctypes.c_ushort),
                        ("srWindow", wt.SMALL_RECT),
                        ("dwMaximumWindowSize", wt._COORD),
                    ]
                # Das Konsolenfenster DIREKT oeffnen, nicht ueber
                # GetStdHandle(STD_OUTPUT_HANDLE).
                #
                # Gemessen: die Umleitung von Deskriptor 1 auf NUL weiter oben
                # (die den GLib-Muell unterdrueckt) aendert ueber die
                # C-Laufzeit auch das Std-Handle des Prozesses - vorher 184,
                # danach 172. Ein WriteConsoleW auf dieses Handle schlaegt
                # dann fehl (Rueckgabe 0, 0 Zeichen), und zwar lautlos.
                # Deshalb blieb das Fenster schwarz.
                #
                # "CONOUT$" liefert immer das Handle des Konsolenfensters
                # selbst, unabhaengig davon, wohin stdout gerade zeigt.
                k32.CreateFileW.restype = ctypes.c_void_p
                hStdOut = k32.CreateFileW(
                    "CONOUT$",
                    0xC0000000,   # GENERIC_READ | GENERIC_WRITE
                    3,            # FILE_SHARE_READ | FILE_SHARE_WRITE
                    None,
                    3,            # OPEN_EXISTING
                    0, None)
                hStdOut = ctypes.c_void_p(hStdOut)
                csbi = CONSOLE_SCREEN_BUFFER_INFO()
                if k32.GetConsoleScreenBufferInfo(hStdOut, ctypes.byref(csbi)):
                    buf_cells = csbi.dwSize.X * csbi.dwSize.Y
                    # 2) Zeichen + Attribute mit Leerraum füllen
                    chars_written = wt.DWORD(0)
                    k32.FillConsoleOutputCharacterW(hStdOut, ctypes.c_wchar(' '), buf_cells, wt._COORD(0, 0), ctypes.byref(chars_written))
                    k32.FillConsoleOutputAttribute(hStdOut, csbi.wAttributes, buf_cells, wt._COORD(0, 0), ctypes.byref(chars_written))
                    # 3) Cursor auf 0,0
                    k32.SetConsoleCursorPosition(hStdOut, wt._COORD(0, 0))

                # Den Hinweis DIREKT ueber die Konsolen-API schreiben, nicht
                # ueber print oder einen Dateideskriptor.
                #
                # Warum: ein paar Zeilen weiter oben werden fuer den
                # Normalbetrieb die Deskriptoren 1 und 2 auf NUL umgeleitet,
                # damit Bibliotheken wie GLib ihre Meldungen nicht in die
                # Konsole schreiben. Alles, was ueber einen Deskriptor geht,
                # ist danach unsichtbar - auch dieser Hinweis. Genau das ist
                # am 30.08.2026 passiert: das Fenster blieb schwarz und leer.
                #
                # WriteConsoleW schreibt an den Deskriptoren vorbei an das
                # Konsolenfenster selbst. Damit ist der Hinweis unabhaengig
                # davon, wohin stdout gerade zeigt.
                hinweis = ("====   KVRouite Konsole          ====\r\n"
                           "====         Don´t Close!        ====\r\n"
                           "==== closing will close the APP! ====\r\n")
                geschrieben = wt.DWORD(0)
                k32.WriteConsoleW(hStdOut, ctypes.c_wchar_p(hinweis),
                                  len(hinweis), ctypes.byref(geschrieben), None)

                # 4) Fenster unsichtbar (Konsole bleibt vorhanden → Performance ok)
                
                SW_HIDE = 0
                u32.ShowWindow(hwnd, SW_HIDE)
            else:
                # Debug sichtbar lassen – optional Banner
                try:
                    force_print("==== KVRouite DEBUG Konsole ====")
                except Exception:
                    pass
    except Exception:
        pass




# Unter macOS muss LC_NUMERIC auf "C" stehen: sonst schreiben Bibliotheken,
# die Zahlen als Text weiterreichen, ein Komma als Dezimaltrennzeichen, und
# GStreamer nimmt das nicht an.
current_os = platform.system()
if current_os == "Darwin":
    import locale
    locale.setlocale(locale.LC_NUMERIC, "C")

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
# GStreamer-Umgebung im fertigen Programm selbst aufbauen.
#
# Die GStreamer-Wheels richten sich ueber site-packages/gstreamer_bundle.pth
# ein: eine Zeile, die Python beim Start des Interpreters ausfuehrt und die
# gstreamer_libs.setup_python_environment() aufruft. Die setzt PATH,
# GST_PLUGIN_PATH_1_0, GI_TYPELIB_PATH und vor allem PYGI_DLL_DIRS.
#
# PyInstaller fuehrt .pth-Dateien NICHT aus. Im gepackten Programm fehlt
# deshalb die ganze Einrichtung, und "import gi" bricht ab mit
# "Could not deduce DLL directories, please set PYGI_DLL_DIRS". Hier wird
# nachgeholt, was die .pth sonst erledigt.
#
# Nur im gepackten Zustand: im venv hat die .pth ihre Arbeit schon getan, ein
# zweiter Aufruf wuerde die Pfade doppelt in die Umgebung schreiben.
if getattr(sys, "frozen", False):
    # Zuerst festlegen, wohin GStreamer seine Plugin-Liste schreiben darf -
    # unabhaengig davon, welcher der beiden Wege darunter greift. Ohne das
    # sucht GStreamer sich den Ort selbst und legt die Datei im
    # macOS-Buendel neben die Bibliotheken; damit ist die Signatur des
    # Buendels nach dem ersten Start hinueber. Begruendung und Messung
    # stehen in core/gst_umgebung.py.
    try:
        from core.gst_umgebung import registry_festlegen
        _registry = registry_festlegen()
        if _registry:
            print("[INFO] GST_REGISTRY_1_0 =", _registry)
    except Exception as _exc0:
        print("[WARN] Ort der GStreamer-Plugin-Liste nicht gesetzt:", _exc0)

    try:
        import gstreamer_libs
        gstreamer_libs.setup_python_environment()
    except Exception as _exc:
        # Die Wheel-Funktion rechnet die Pfade aus der Lage in site-packages
        # aus. Im macOS-Buendel gibt es das nicht mehr, sie scheitert dort mit
        # "Couldn't find site-packages prefix". Ohne GI_TYPELIB_PATH findet
        # "import gi" danach nichts, und Wiedergabe, Vorschau und Export
        # fallen alle aus - gemessen am ersten Buendel vom 02.09.2026.
        #
        # Deshalb ein zweiter Weg: dieselbe Umgebung aus dem aufbauen, was
        # tatsaechlich neben dem Programm liegt.
        print("[WARN] GStreamer-Umgebung nicht ueber das Wheel aufgebaut:", _exc)
        try:
            from core.gst_umgebung import umgebung_aufbauen, bericht
            umgebung_aufbauen()
            for _zeile in bericht():
                print("[INFO] " + _zeile)
        except Exception as _exc2:
            print("[WARN] Auch der zweite Weg schlug fehl:", _exc2)

    # Noch einmal, jetzt hat unser Ort das letzte Wort. Grund:
    # gstreamer_libs.setup_python_environment() setzt GST_REGISTRY_1_0 auf
    # ihren eigenen Ort, GST_REGISTRY bleibt auf unserem stehen - zwei
    # Variablen mit verschiedenen Werten. In diesem Zustand hat die gebaute
    # 6.03-EXE am 03.09.2026 die Plugin-Liste an KEINER Stelle mehr
    # gespeichert und sie bei jedem Start neu aufgebaut. Ein vom Anwender
    # selbst gesetzter Ort bleibt unangetastet, das merkt sich der erste
    # Aufruf (core/gst_umgebung.py).
    try:
        from core.gst_umgebung import registry_festlegen as _registry_erneut
        _registry2 = _registry_erneut(erneut=True)
        if _registry2:
            print("[INFO] GST_REGISTRY_1_0 (endgueltig) =", _registry2)
    except Exception as _exc3:
        print("[WARN] Ort der GStreamer-Plugin-Liste nicht bestaetigt:", _exc3)

# ---------------------------------------------------------
import path_manager

# ---------------------------------------------------------
# Jetzt erst den Rest importieren
import urllib.request
import datetime
import config
import path_manager  # zweites Mal import ist okay

# Qt-Sachen
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget, QSystemTrayIcon
from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler

from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView #apparently we need to import it before the app starts


def _qt_message_handler(mode, context, message):
    """Qt-Meldungen auf den echten stderr schreiben.

    stdout/stderr sind im Betrieb umgelenkt; Qt-Meldungen sollen trotzdem
    auf der Konsole landen, deshalb geht es hier direkt an REAL_STDERR.

    Bis 6.01 wurde hier zusaetzlich die Meldung "belongs to QRhi"
    geschluckt. Die trat ausschliesslich beim Abkoppeln der Karte in ein
    zweites Top-Level-Fenster auf - jedes Fenster hat seine eigene QRhi,
    Chromium haengt seine Kompositor-Textur aber an die QWebEnginePage.
    Mit dem Detach ist auch die Meldung entfallen, der Filter also mit.
    """
    try:
        REAL_STDERR.write(message + "\n")
        REAL_STDERR.flush()
    except Exception:
        pass


qInstallMessageHandler(_qt_message_handler)

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


def _file_arg_from_cli(argv):
    """Erste uebergebene existierende Datei aus der Kommandozeile.

    Wird von der Windows-Dateizuordnung benutzt: der Installer traegt
    "KVRouite.exe" "%1" als Open-Befehl fuer .KVRouiteproj ein, Windows
    haengt beim Doppelklick den Pfad an. Optionen wie -v werden ignoriert.
    """
    for arg in argv[1:]:
        if arg.startswith("-"):
            continue
        if os.path.isfile(arg):
            return os.path.abspath(arg)
    return None


def main():
    # Selbsttest statt Oberflaeche: prueft, ob die Anwendung wirklich
    # arbeitet - Dateien finden, Symbole laden, GPX lesen und schreiben, ein
    # Video schneiden und ausgeben. Gedacht fuer das FERTIGE Programm:
    #
    #     KVRouite.exe --selftest        (oder -selftest)
    #     KVRouite.app/Contents/MacOS/KVRouite --selftest
    #
    # Ein Startversuch beweist nur, dass nichts abstuerzt. Ob ein gepacktes
    # Programm seine mitgelieferten Dateien findet, zeigt erst dieser Weg -
    # und genau daran ist das macOS-Buendel zuerst gescheitert.
    erkannt, unbekannt = _optionen_lesen(sys.argv)
    if unbekannt:
        force_error("Unknown option: " + " ".join(unbekannt))
        force_error("Known options:")
        for _zeile in _OPTIONEN_HILFE:
            force_error(_zeile)
        sys.exit(2)

    if "selftest" in erkannt:
        import selftest
        sys.exit(selftest.alles_pruefen())

    # "-menuup": das "..."-Menue der GPX-Tabelle klappt nach oben auf statt
    # nach unten. Gebraucht fuer Bildschirmaufnahmen: unten am Fensterrand
    # schiebt Qt das Menue sonst ueber die Taskleiste hinaus.
    config.MORE_MENU_OPENS_UPWARD = "menuup" in erkannt

    # Workaround bei manchen Grafikkarten
    
    
    if config.is_soft_opengl_enabled():
        QGuiApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)

    # QtWebEngine (Karte) und die Videoausgabe leben im selben Prozess und nutzen
    # beide OpenGL. Muss VOR QApplication(...) gesetzt werden, sonst wirkt es
    # nicht. Unter Qt 6.8 aendert es nichts, es ist also ein Codepfad fuer
    # beide Versionen.
    #
    # Der Anlass war das Abkoppeln der Karte in ein eigenes Fenster: ohne
    # geteilten Kontext blieb dieses Fenster ab Qt 6.11 schwarz. Das Abkoppeln
    # gibt es seit 6.02 nicht mehr. Das Attribut bleibt trotzdem gesetzt - ob
    # der geteilte Kontext auch sonst etwas stabilisiert, ist nicht gemessen,
    # und es kostet nichts.
    QGuiApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)

    # Farbgebung setzen, bevor das erste Fenster entsteht. Bis 6.02 gab es
    # weder Stil noch Palette - die Oberflaeche nahm, was Windows lieferte.
    from core import theme
    theme.anwenden(app)
    
    
    current_os = platform.system()
    
    # GStreamer/GES IST seit 6.0 eine Startbedingung.
    #
    # Bis 5.01 gab es zwei Wiedergabewege, und wenn GES fehlte, lief die App
    # auf libmpv weiter. Der zweite Weg ist entfallen: ohne GStreamer kann
    # KVRouite kein Video anzeigen, schneiden oder exportieren. Es hier
    # abzufangen ist freundlicher, als spaeter mit einem ImportError aus dem
    # Aufbau der Oberflaeche zu fallen.
    if current_os not in ("Windows", "Darwin", "Linux"):
        QMessageBox.critical(
            None, "Unsupported OS",
            f"Your operating system ({current_os}) is not supported at the moment.")
        sys.exit(1)

    from core.ges_backend import is_available as ges_verfuegbar
    from core.ges_backend import unavailable_reason as ges_grund
    if not ges_verfuegbar():
        if current_os == "Linux":
            hilfe = ("sudo apt install python3-gi python3-gi-cairo "
                     "gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 "
                     "gir1.2-ges-1.0 gstreamer1.0-plugins-base "
                     "gstreamer1.0-plugins-good gstreamer1.0-plugins-bad "
                     "gstreamer1.0-plugins-ugly gstreamer1.0-libav "
                     "gstreamer1.0-gl gstreamer1.0-x\n\n"
                     "Das venv muss mit --system-site-packages angelegt sein.")
        else:
            hilfe = "pip install -r requirements.txt"
        QMessageBox.critical(
            None, "GStreamer is missing",
            "KVRouite plays, cuts and renders video through GStreamer "
            "Editing Services (GES). It could not be loaded, so the "
            "application cannot start.\n\n"
            f"Reason:\n{ges_grund()}\n\n"
            f"To install it:\n{hilfe}\n\n"
            "Run check_ges.py to see what exactly is missing.")
        sys.exit(1)

    # ffmpeg ist KEINE Startbedingung und wird seit 6.0 auch nicht mehr
    # mitgeliefert. Gebraucht wird es allein vom Copy-Mode; Wiedergabe,
    # Vorschau samt Blenden, Bildraten, Laengen, Drehung, Hardware-Erkennung
    # und der Export laufen ueber GStreamer. Gesucht wird deshalb nur, was auf
    # dem Rechner schon da ist, und es wird in den PATH gelegt, damit die
    # spaeteren Pruefungen mit shutil.which() es auch finden.
    #
    # Bewusst NICHT ueber path_manager.ensure_ffmpeg(): das oeffnet bei
    # Misserfolg einen Ordner-Dialog, und genau das soll beim Start nicht
    # passieren.
    # Eine Suche fuer alle Systeme: sie kennt die ueblichen Orte des jeweiligen
    # Systems und den Namen, unter dem ein von Hand gesetzter Ordner steht.
    ffmpeg_ordner = path_manager.find_ffmpeg_folder()
    if ffmpeg_ordner and path_manager.is_ffmpeg_in_folder(ffmpeg_ordner):
        path_manager.add_to_process_path(ffmpeg_ordner)
        print("[DEBUG] ffmpeg gefunden in", ffmpeg_ordner)

    # Einmal deutlich sagen, was ohne ffmpeg fehlt. Nur der Copy-Mode haengt
    # daran, deshalb ein Hinweis und kein Abbruch - und nur beim ersten Mal.
    # Ohne das faende der Anwender bloss einen ausgegrauten Menueeintrag vor
    # und wuesste nicht, warum.
    #
    # Der Merker wird zurueckgenommen, sobald ffmpeg wieder da ist. Sonst
    # hiesse "einmal" ein einziges Mal ueberhaupt: wer ffmpeg spaeter
    # deinstalliert oder den PATH aendert, saesse wieder vor einem
    # ausgegrauten Menueeintrag ohne Erklaerung. So kommt der Hinweis bei
    # jedem NEUEN Fehlen genau einmal.
    from PySide6.QtCore import QSettings as _QS
    einstellungen = _QS("KVRouite", "KVRouite")
    MERKER = "hints/ffmpeg_missing_shown"

    fehlende_werkzeuge = path_manager.fehlende_ffmpeg_werkzeuge()
    if not fehlende_werkzeuge:
        if einstellungen.contains(MERKER):
            einstellungen.remove(MERKER)
    else:
        print("[WARN] " + path_manager.copy_mode_fehlgrund()
              + " - der Copy-Mode steht nicht zur Verfuegung.")
        if not einstellungen.value(MERKER, False, type=bool):
            kasten = QMessageBox(None)
            kasten.setIcon(QMessageBox.Information)
            kasten.setWindowTitle("ffmpeg not found")
            kasten.setText(
                "KVRouite did not find " + " and ".join(fehlende_werkzeuge)
                + " in your PATH.\n\n"
                "This affects one thing: COPY MODE stays greyed out. It cuts "
                "on keyframes with ffmpeg and uses ffprobe to index them, so "
                "it cannot run without them.\n\n"
                "Nothing else is affected - KVRouite works as usual.\n\n"
                "If you want copy mode: install ffmpeg - it includes ffprobe - "
                "and make sure it is in your PATH. You can also point KVRouite "
                "at it under Config > FFmpeg > Set ffmpeg Path.")
            kasten.setStandardButtons(QMessageBox.Ok)
            kasten.exec()
            einstellungen.setValue(MERKER, True)
    
    
    from views.mainwindow import MainWindow
    
    # Tray-Icon (nur Windows)
    if platform.system() == "Windows":
        # Pfad: icon/icon_icon.ico
        icon_file = resource_path(os.path.join("icon", "icon_icon.ico"))
        print("[DEBUG] Icon-Pfad =", icon_file, "| exists?", os.path.isfile(icon_file))

        app.setWindowIcon(QIcon(icon_file))
        trayIcon = QSystemTrayIcon(QIcon(icon_file), parent=None)
        trayIcon.show()

    # Eigenen Instanz-Ordner anlegen und sperren, dann die Ordner
    # abgestuerzter Vorlaeufer aufraeumen. Erst danach darf irgendetwas in die
    # Temp-Ordner schreiben.
    config.prepare_instance_temp_dir()
    config.cleanup_orphaned_temp_dirs()

    # Temp-Verzeichnisse leeren
    config.clear_temp_directories()


    # Frueher stand hier eine zweite Pruefung, die ohne ffmpeg im PATH
    # das Programm beendet hat. Sie ist weggefallen: ffmpeg ist keine
    # Startbedingung mehr (siehe oben).
    parent_widget = QWidget()
    parent_widget.hide()

    # Disclaimer-Dialog (nur wenn nicht akzeptiert)
    
    config.check_app_version_and_reset_if_necessary()
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

    # Hat der Nutzer beim letzten Mal eine eigene Fenstergroesse/-position
    # hinterlassen, gilt die. Sonst bleibt es exakt beim bisherigen Start:
    # Standardgroesse oben, danach mittig setzen.
    restored = window.apply_saved_window_geometry()

    window.show()

    app.processEvents()
    if not restored:
        center_mainwindow(window)
    window.raise_()
    window.activateWindow()

    # Datei aus der Kommandozeile oeffnen (Doppelklick auf ein Projekt im
    # Explorer). open_recent() verzweigt bereits nach Endung und ruft fuer
    # .KVRouiteproj das process_open_project() auf. Erst nach dem Anzeigen
    # ausfuehren, damit Fehlermeldungen ein fertiges Fenster als Eltern haben.
    cli_file = _file_arg_from_cli(sys.argv)
    if cli_file:
        window.open_file_when_map_ready(cli_file)

    if "screenshot" in erkannt:
        # Bildnachweis: GPX und Video laden, abspielen, drei Bilder machen.
        # Der Ablauf steht in nachweis.py, damit hier nur der Anstoss liegt -
        # so wie beim Selbsttest auch.
        import nachweis
        nachweis.bilder_machen(window, app, force_print)

    exit_code = app.exec()
    # Beim sauberen Beenden den eigenen Temp-Ordner mitnehmen.
    config.release_instance_temp_dir()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
