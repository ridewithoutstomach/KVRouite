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
# You should have received a copy of the GNU General Public License
# along with KVRouite. If not, see <https://www.gnu.org/licenses/>.
"""
GStreamer im gepackten Programm auffindbar machen - ohne die Wheels zu fragen.

Normalerweise erledigt das gstreamer_libs.setup_python_environment(): sie
rechnet die Pfade aus der Lage der Pakete in site-packages aus. In einem
gepackten Programm gibt es kein site-packages mehr, und im macOS-Buendel
scheitert sie deshalb mit

    Couldn't find site-packages prefix inside .../Contents/Frameworks/gstreamer_python

Die Folge ist nicht harmlos: ohne GI_TYPELIB_PATH findet "import gi" die
Typelibs nicht, und damit faellt alles aus - Wiedergabe, Vorschau, Export.
Gemessen am ersten macOS-Buendel vom 02.09.2026: "Typelib file for namespace
'GObject', version '2.0' not found".

Hier wird dieselbe Umgebung aus dem aufgebaut, was tatsaechlich da ist: den
Ordnern der gstreamer-Pakete neben dem Programm. Unter Windows springt das
nicht ein - dort funktioniert der Weg der Wheels.
"""

import os
import sys

#: Pakete, die Typelibs mitbringen (lib/girepository-1.0).
TYPELIB_PAKETE = ("gstreamer_python", "gstreamer_gtk", "gstreamer_libs")

#: Pakete, die Plugins mitbringen (lib/gstreamer-1.0).
PLUGIN_PAKETE = (
    "gstreamer_cli", "gstreamer_plugins_gpl_restricted", "gstreamer_plugins_gpl",
    "gstreamer_plugins_restricted", "gstreamer_plugins_libs", "gstreamer_plugins",
    "gstreamer_python", "gstreamer_gtk", "gstreamer_libs",
)

#: Wo die Bibliotheken liegen. Windows legt sie nach bin/, die anderen nach lib/.
BIBLIOTHEK_ORDNER = ("bin", "lib")


#: Wohin GStreamer seine Plugin-Liste schreiben darf.
#
# GStreamer legt sich beim Start eine Zwischendatei an, damit es nicht jedes
# Mal alle Plugins durchsuchen muss. Wo die hingehoert, sucht es sich selbst -
# und im macOS-Buendel griff es daneben: die Datei landete als
# Contents/Frameworks/registry.bin IM BUENDEL.
#
# Das ist nicht nur unordentlich. Ein Anwendungsbuendel ist signiert, und die
# Signatur umfasst jede Datei darin. Eine, die beim ersten Start dazukommt,
# macht das Siegel ungueltig - genau die Meldung, die am 02.09.2026 ein
# Anwender geschickt hat ("a sealed resource is missing or invalid"). Das
# Buendel haette sich also bei jedem Anwender beim ersten Doppelklick selbst
# beschaedigt. Gefunden am 03.09.2026 vom Schritt "Hat das Laufen das Buendel
# veraendert?" im macOS-Bauplan, auf beiden Architekturen.
#
# Deshalb wird der Ort hier ausdruecklich vorgegeben, und zwar dort, wo
# Zwischendateien hingehoeren: in den Zwischenspeicher des ANWENDERS, nicht
# ins Programm. Ueberlebt ein Update, ist beschreibbar, und das Buendel wird
# beim Laufen nicht mehr angefasst.
_REGISTRY_ORDNER = "KVRouite"


def _zwischenspeicher():
    """Der Ordner des Anwenders fuer Zwischendateien, je nach System."""
    if sys.platform == "win32":
        basis = os.environ.get("LOCALAPPDATA")
    elif sys.platform == "darwin":
        basis = os.path.expanduser("~/Library/Caches")
    else:
        basis = (os.environ.get("XDG_CACHE_HOME")
                 or os.path.expanduser("~/.cache"))
    if not basis or not os.path.isdir(os.path.dirname(basis) or basis):
        import tempfile
        basis = tempfile.gettempdir()
    return os.path.join(basis, _REGISTRY_ORDNER)


def _programm_kennung():
    """Kurze Kennung des Programmordners, aus dem dieser Prozess laeuft.

    Acht Hexziffern aus dem Pfad von sys._MEIPASS (im gepackten Programm)
    oder des Interpreters (im Quellbaum). Zwei Installationen auf demselben
    Rechner bekommen so zwei verschiedene Plugin-Listen.
    """
    import hashlib
    ort = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.abspath(sys.executable))
    try:
        ort = os.path.normcase(os.path.abspath(ort))
    except Exception:
        pass
    return hashlib.sha1(ort.encode("utf-8", "replace")).hexdigest()[:8]


def _registry_datei():
    """Pfad der Plugin-Liste. None, wenn der Ordner nicht anzulegen ist.

    Der Dateiname traegt die Architektur, weil eine Liste, die auf einem
    Apple-Silicon-Rechner entstanden ist, auf einem Intel-Rechner nichts
    taugt - GStreamer macht es bei seinem eigenen Vorgabeort genauso.

    Er traegt ausserdem eine Kennung des Programmordners. Die Liste speichert
    die Plugins mit ABSOLUTEM Pfad, und GStreamer behaelt jeden Eintrag, dessen
    Datei es noch gibt - auch wenn sie in einer ANDEREN Installation liegt.
    Am 05.09.2026 gemessen: eine frisch gebaute Fassung unter E:/.../dist
    lud beim ersten Start gstpython.dll aus C:/Program Files/KVRouite, weil
    die installierte Fassung dieselbe Liste vorher gefuellt hatte. Wer die
    portable ZIP neben dem Installer benutzt, mischt sonst zwei Versionen.
    Mit der Kennung hat jede Installation ihre eigene Liste.
    """
    import platform
    ordner = _zwischenspeicher()
    try:
        os.makedirs(ordner, exist_ok=True)
    except Exception:
        return None
    return os.path.join(ordner, "gstreamer-registry-%s-%s.bin"
                        % (platform.machine() or "unknown",
                           _programm_kennung()))


def _im_programm(pfad):
    """Liegt der Pfad im Programmordner - also im Buendel selbst?"""
    if not pfad:
        return False
    try:
        pfad = os.path.abspath(pfad)
    except Exception:
        return False
    orte = [getattr(sys, "_MEIPASS", None),
            os.path.dirname(os.path.abspath(sys.executable))]
    for ort in orte:
        if not ort:
            continue
        ort = os.path.abspath(ort)
        if pfad == ort or pfad.startswith(ort + os.sep):
            return True
    return False


#: Was der Anwender selbst vorgegeben hat - oder None. Wird beim ersten
#: Aufruf von registry_festlegen() festgehalten, siehe dort.
_ANWENDER_ORT = None

#: Der Ort, den wir gewaehlt haben. Einmal ausgerechnet, dann steht er.
_UNSER_ORT = None


def registry_festlegen(erneut=False):
    """Den Ort der Plugin-Liste setzen. Rueckgabe: der Pfad oder None.

    Bewusst eine eigene Funktion und nicht Teil von umgebung_aufbauen(): die
    laeuft nur als Notweg, wenn der Weg ueber das Wheel scheitert
    (KVRouite.py). Der Ort der Plugin-Liste muss aber IMMER stehen, bevor
    GStreamer geladen wird.

    Ein von aussen gesetzter Wert gilt - ABER NICHT, wenn er ins Programm
    selbst zeigt. Genau das tut PyInstaller ungefragt, in seinem eigenen
    Startskript PyInstaller/hooks/rthooks/pyi_rth_gstreamer.py:

        # Prevent permission issues on Windows
        os.environ['GST_REGISTRY'] = os.path.join(sys._MEIPASS, 'registry.bin')

    sys._MEIPASS ist im macOS-Buendel Contents/Frameworks, und dieses
    Startskript laeuft VOR unserem Code. Der erste Versuch am 03.09.2026 hat
    deshalb nichts bewirkt: er sah einen gesetzten Wert und liess ihn stehen -
    der Bauplan meldete weiter "file added: Contents/Frameworks/registry.bin".

    Fuer Windows mag der Ort taugen, fuer ein signiertes macOS-Buendel nicht:
    jede Datei, die nach dem Signieren dazukommt, macht das Siegel ungueltig,
    und das Buendel beschaedigt sich beim ersten Start selbst.

    ZWEIMAL aufrufen, siehe KVRouite.py:

      erneut=False  vor allem anderen. Steht dann schon ein Wert da, der NICHT
                    ins Programm zeigt, stammt er vom Anwender - der gilt, und
                    wir merken ihn uns.

      erneut=True   nachdem gstreamer_libs.setup_python_environment() gelaufen
                    ist. Die setzt GST_REGISTRY_1_0 auf ihren eigenen Ort und
                    ueberschreibt unseren; danach stuenden zwei Variablen mit
                    verschiedenen Werten da (GST_REGISTRY unserer,
                    GST_REGISTRY_1_0 der des Wheels). Am 03.09.2026 an der
                    gebauten 6.03-EXE gemessen: in diesem Zustand wurde die
                    Liste ueberhaupt nicht mehr gespeichert, an keiner der
                    drei moeglichen Stellen - das Programm baute sie bei jedem
                    Start neu auf. Mit dem zweiten Aufruf steht ueberall
                    derselbe Ort, und der Ordner wird von uns angelegt.
    """
    global _ANWENDER_ORT, _UNSER_ORT

    vorher = (os.environ.get("GST_REGISTRY_1_0")
              or os.environ.get("GST_REGISTRY"))
    if erneut:
        if _ANWENDER_ORT:
            # Auch der Wert des Anwenders wird vom Wheel ueberschrieben.
            # "Der Anwender gewinnt" heisst: auch dagegen.
            os.environ["GST_REGISTRY_1_0"] = _ANWENDER_ORT
            os.environ["GST_REGISTRY"] = _ANWENDER_ORT
            return _ANWENDER_ORT
    elif vorher and not _im_programm(vorher):
        _ANWENDER_ORT = vorher
        return None

    if _UNSER_ORT is None:
        _UNSER_ORT = _registry_datei()
    if not _UNSER_ORT:
        return None
    os.environ["GST_REGISTRY_1_0"] = _UNSER_ORT
    os.environ["GST_REGISTRY"] = _UNSER_ORT
    return _UNSER_ORT


def _wurzeln():
    """Wo die gstreamer-Pakete im gepackten Programm liegen koennen.

    sys._MEIPASS ist im macOS-Buendel Contents/Frameworks und unter Windows
    der Ordner _internal - in beiden Faellen genau dort, wo --collect-all die
    Pakete abgelegt hat.
    """
    orte = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        orte.append(meipass)
    orte.append(os.path.dirname(os.path.abspath(sys.executable)))
    return [o for o in orte if o and os.path.isdir(o)]


def _sammeln(pakete, *unterordner):
    """Alle vorhandenen <wurzel>/<paket>/<unterordner> - Reihenfolge bleibt."""
    gefunden = []
    for wurzel in _wurzeln():
        for paket in pakete:
            pfad = os.path.join(wurzel, paket, *unterordner)
            if os.path.isdir(pfad) and pfad not in gefunden:
                gefunden.append(pfad)
    return gefunden


def umgebung_aufbauen():
    """Die Umgebungsvariablen setzen. Rueckgabe: was gesetzt wurde.

    Bereits gesetzte Werte werden nicht ueberschrieben, sondern ergaenzt: wer
    von aussen einen eigenen Plugin-Pfad mitgibt, soll ihn behalten.
    """
    gesetzt = {}

    def dazu(name, pfade):
        if not pfade:
            return
        vorher = os.environ.get(name, "")
        teile = [p for p in pfade if p not in vorher.split(os.pathsep)]
        if not teile:
            return
        neu = os.pathsep.join(teile + ([vorher] if vorher else []))
        os.environ[name] = neu
        gesetzt[name] = neu

    datei = registry_festlegen()
    if datei:
        gesetzt["GST_REGISTRY_1_0"] = datei

    typelibs = _sammeln(TYPELIB_PAKETE, "lib", "girepository-1.0")
    dazu("GI_TYPELIB_PATH", typelibs)

    plugins = _sammeln(PLUGIN_PAKETE, "lib", "gstreamer-1.0")
    dazu("GST_PLUGIN_PATH_1_0", plugins)
    dazu("GST_PLUGIN_SYSTEM_PATH_1_0", plugins)

    bibliotheken = []
    for ordner in BIBLIOTHEK_ORDNER:
        bibliotheken += _sammeln(PLUGIN_PAKETE + TYPELIB_PAKETE, ordner)
    if sys.platform == "win32":
        dazu("PATH", bibliotheken)
        dll_ordner = _sammeln(("gstreamer_libs",), "bin")
        dazu("PYGI_DLL_DIRS", dll_ordner)
    else:
        # macOS und Linux suchen ueber den dynamischen Lader.
        dazu("DYLD_LIBRARY_PATH" if sys.platform == "darwin"
             else "LD_LIBRARY_PATH", bibliotheken)

    # Der Plugin-Scanner ist ein eigenes Programm. Fehlt er, meldet GStreamer
    # "External plugin loader failed" und laedt die Plugins im eigenen Prozess
    # weiter - unschoen, aber kein Abbruch.
    for wurzel in _wurzeln():
        scanner = os.path.join(wurzel, "gstreamer_libs", "libexec",
                               "gstreamer-1.0", "gst-plugin-scanner")
        if sys.platform == "win32":
            scanner += ".exe"
        if os.path.isfile(scanner):
            os.environ["GST_PLUGIN_SCANNER_1_0"] = scanner
            gesetzt["GST_PLUGIN_SCANNER_1_0"] = scanner
            # Ohne Ausfuehrungsrecht nuetzt er nichts - im Wheel fehlt es
            # gelegentlich, gemeldet als "isn't executable".
            try:
                if not os.access(scanner, os.X_OK):
                    os.chmod(scanner, 0o755)
            except Exception:
                pass
            break

    return gesetzt


def bericht():
    """Was gerade gilt - fuer die Fehlersuche."""
    zeilen = []
    for name in ("GI_TYPELIB_PATH", "GST_PLUGIN_PATH_1_0",
                 "GST_PLUGIN_SCANNER_1_0", "GST_REGISTRY_1_0", "PYGI_DLL_DIRS",
                 "DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        wert = os.environ.get(name)
        if wert:
            zeilen.append("%s = %s" % (name, wert))
    return zeilen
