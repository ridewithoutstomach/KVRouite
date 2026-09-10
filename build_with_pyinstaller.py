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
#####################################################

##    use --build-installer to build the installer!

######################################################
import os
import sys
import platform
import subprocess
import shutil
import importlib.util
import hashlib, zipfile

# Die Ausgabe dieses Skripts enthaelt Pfeile. Laeuft die Konsole auf cp1252,
# wirft print() darauf UnicodeEncodeError und der Build bricht mitten im Lauf
# ab. errors="replace" macht daraus ein "?" und laesst ihn weiterlaufen.
for _strom in (sys.stdout, sys.stderr):
    try:
        _strom.reconfigure(errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Seit 6.0 werden WEDER ffmpeg NOCH mpv mitgeliefert. Beide Ordner liegen
# weiterhin im Arbeitsverzeichnis, weil die 5.x-Zweige daraus bauen - dieser
# Builder fasst sie nicht mehr an. Dass nichts davon in den Build rutscht,
# pruefen check_mpv_frei() und check_ffmpeg_frei() am Ende.
#
# ffmpeg bleibt fuer den Copy-Mode noetig, kommt aber aus dem PATH des
# Anwenders. Fehlt es dort, sperrt KVRouite den Copy-Mode und sagt es beim
# Start.

# gstreamer/ enthaelt KEINE Binaries, nur die Rechtstexte (NOTICE, COMPONENTS,
# COPYING.*). Der Ordner muss mit, sonst liefern wir GPL/LGPL-Binaries ohne die
# zugehoerigen Lizenztexte aus - siehe check_gstreamer_payload().
LOCAL_GSTREAMER = os.path.join(BASE_DIR, "gstreamer")

# Dieselbe Rolle fuer die uebrigen Fremdbestandteile: qt/ deckt Qt 6, PySide6
# und shiboken6 ab (LGPL-3 - die verlangt ausdruecklich einen Hinweis UND eine
# beiliegende Kopie von LGPL und GPL), third-party-licenses/ den Rest
# (CPython, OpenSSL, Pillow, fitparse). Auch diese Ordner enthalten keine
# Binaries, nur Text.
LOCAL_QT = os.path.join(BASE_DIR, "qt")
LOCAL_THIRDPARTY = os.path.join(BASE_DIR, "third-party-licenses")

# Die GStreamer-Wheels, die in den Build gehoeren.
#
# PyInstaller findet sie NICHT von selbst. Die Wheels richten sich ueber
# site-packages/gstreamer_bundle.pth ein - eine Zeile, die Python beim Start
# des Interpreters ausfuehrt und die gstreamer_libs.setup_python_environment()
# aufruft. PyInstaller fuehrt .pth-Dateien nicht aus, also importiert nichts
# diese Pakete statisch, also sammelt PyInstaller sie nicht ein. Ohne
# --collect-all landeten zuletzt nur gi und gstreamer_libs im Build, und die
# fertige Anwendung brach beim Start mit "Could not deduce DLL directories,
# please set PYGI_DLL_DIRS" ab.
#
# Die Liste ist genau die aus gstreamer/COMPONENTS.txt - wir liefern aus, was
# dort dokumentiert ist, und nichts sonst.
#
# gstreamer_cli ist trotz seines Namens PFLICHT: darin liegt ges-1.0-0.dll,
# die GES-Bibliothek selbst. Ohne sie meldet die Anwendung beim Start
# "Failed to load shared library 'ges-1.0-0.dll' referenced by the typelib".
# Die zwoelf Kommandozeilenwerkzeuge im selben Paket (gst-launch, gst-inspect
# und Verwandte, zusammen 17 MB) braucht die Anwendung nicht - die entfernt
# cli_werkzeuge_entfernen() nach dem Bau wieder.
GSTREAMER_PAKETE = (
    "gstreamer_bundle",
    "gstreamer_cli",
    "gstreamer_libs",
    "gstreamer_plugins",
    "gstreamer_plugins_libs",
    "gstreamer_plugins_restricted",
    "gstreamer_plugins_gpl",
    "gstreamer_plugins_gpl_restricted",
    "gstreamer_python",
    "gstreamer_gtk",
    "gstreamer_ext_runtime",
)

# Voice Remover (core/stimme, ab 7.0): die Trennbibliothek und ihre Modelle
# kommen komplett in die App - Entscheidung vom 10.09.2026, kein Nachladen.
#
# audio_separator wird von core/stimme erst beim ersten Gebrauch importiert
# (der Import kostet Sekunden), deshalb sieht PyInstaller ihn nicht von
# selbst: --collect-all. torchvision ebenfalls: onnx2torch zieht es herein,
# und seine native Bibliothek (_C_stable.pyd) uebersieht der Hook - ohne
# --collect-all bricht der erste Gebrauch mit "operator torchvision::nms does
# not exist" ab (gemessen am 10.09.2026 an einem Probebau).
VOICE_PAKETE = ("audio_separator", "torchvision")
#: Die Modelldateien, geholt mit tools/modelle_holen.py; landen in
#: _internal/voice_models, wo core/stimme sie ueber config.finde_datei findet.
VOICE_MODELLE = os.path.join(BASE_DIR, "voice_models")


def _ist_platzhalter(name):
    """Ist die installierte Verteilung 'name' der KVRouite-Platzhalter aus
    tools/diffq_platzhalter? Erkennung: "KVRouite" in der Beschreibung."""
    import importlib.metadata
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return "KVRouite" in (dist.metadata.get("Summary") or "")


def _dist_info_ist_platzhalter(pfad):
    """Dasselbe fuer einen dist-info-Ordner im fertigen Build."""
    try:
        with open(os.path.join(pfad, "METADATA"), "r", encoding="utf-8",
                  errors="replace") as f:
            return "KVRouite" in f.read()
    except OSError:
        return False


def voice_voraussetzungen_pruefen():
    """Was VOR dem Packen stimmen muss, sonst ist der Build wertlos oder
    nicht auslieferbar. Bricht mit klarer Meldung ab."""
    # 1) Python 3.12.1 oder neuer. 3.12.0 traegt CPython-Fehler 110543:
    #    code.replace() verliert das Kennzeichen inliner Komprehensionen, und
    #    PyInstaller ruft es fuer jede Datei. Folge: scipy.stats bricht beim
    #    Import mit "NameError: name 'obj' is not defined" - gemessen am
    #    10.09.2026, mit 3.12.10 verschwunden.
    if sys.version_info[:3] < (3, 12, 1):
        raise SystemExit("[ABBRUCH] Python %d.%d.%d - der Voice Remover "
                         "braucht zum Packen Python 3.12.1 oder neuer "
                         "(CPython-Fehler 110543 in 3.12.0)."
                         % sys.version_info[:3])
    # 2) "diffq-fixed" (Original: CC BY-NC 4.0) und "diffq" muessen die
    #    Platzhalter aus tools/diffq_platzhalter sein - requirements.txt
    #    installiert sie unter genau diesen Namen, erkennbar an "KVRouite"
    #    in der Beschreibung. Alles andere darf nicht ausgeliefert werden.
    for name in ("diffq-fixed", "diffq"):
        if not _ist_platzhalter(name):
            raise SystemExit("[ABBRUCH] Das Paket %s ist nicht der KVRouite-"
                             "Platzhalter (oder fehlt). Das Original steht "
                             "unter CC BY-NC: pip uninstall -y diffq-fixed "
                             "diffq, dann pip install -r requirements.txt "
                             "aus dem Projektverzeichnis." % name)
    # 3) Bibliothek und Modelle da?
    for paket in ("audio_separator", "torchvision", "torch", "onnxruntime"):
        if importlib.util.find_spec(paket) is None:
            raise SystemExit("[ABBRUCH] %s ist nicht installiert - "
                             "pip install -r requirements.txt" % paket)
    sys.path.insert(0, BASE_DIR)
    from core import stimme
    ok, grund = stimme.verfuegbar()
    if not ok:
        raise SystemExit("[ABBRUCH] Voice Remover: %s - "
                         "python tools/modelle_holen.py" % grund)
    # 4) Lizenztexte auf dem Stand DIESER venv: das Inventar in
    #    third-party-licenses/voice muss zu den Paketen passen, die gleich
    #    eingepackt werden (audioop-lts etwa gibt es nur ab Python 3.13).
    #    Das Werkzeug schreibt das Inventar neu; fehlt einem Paket der Text,
    #    bricht es mit Rueckgabewert 1 ab - und damit auch der Bau.
    lauf = subprocess.run([sys.executable,
                           os.path.join(BASE_DIR, "tools", "lizenzen_sammeln.py")],
                          capture_output=True, text=True)
    if lauf.returncode != 0:
        print(lauf.stdout[-2000:])
        raise SystemExit("[ABBRUCH] Lizenztexte des Voice Removers unvollstaendig "
                         "- siehe tools/lizenzen_sammeln.py oben.")
    print("[INFO] Voice Remover: Python %d.%d.%d, Bibliothek und Modelle da, "
          "Lizenzinventar aus dieser venv geschrieben."
          % sys.version_info[:3])


def check_voice_payload(internal_dir):
    """Ist der Voice Remover wirklich im Build gelandet, und nichts, was
    nicht hinein darf? Rueckgabe: Liste der Befunde, leer heisst gut."""
    befunde = []
    for paket in VOICE_PAKETE + ("torch", "onnxruntime"):
        if not os.path.isdir(os.path.join(internal_dir, paket)):
            befunde.append("%s fehlt in _internal" % paket)
    modelle = os.path.join(internal_dir, "voice_models")
    if not os.path.isdir(modelle):
        befunde.append("voice_models fehlt in _internal")
    else:
        from core import stimme
        for _kennung, (datei, name) in stimme.MODELLE.items():
            if not os.path.isfile(os.path.join(modelle, datei)):
                befunde.append("Modell %s (%s) fehlt" % (datei, name))
    for name in os.listdir(internal_dir):
        pfad = os.path.join(internal_dir, name)
        if name.lower().startswith(("diffq_fixed", "diffq-")) and name.endswith(".dist-info"):
            if not _dist_info_ist_platzhalter(pfad):
                befunde.append("%s im Build ist nicht der KVRouite-Platzhalter "
                               "- CC BY-NC, nicht auslieferbar" % name)
        elif name.lower() == "diffq" and os.path.isdir(pfad):
            # Der Platzhalter ist reines Python und wandert ins PYZ-Archiv;
            # ein Ordner _internal/diffq mit Binaerdateien waere das Original.
            if any(f.endswith((".pyd", ".so", ".dll")) for f in os.listdir(pfad)):
                befunde.append("_internal/diffq enthaelt Binaerdateien - "
                               "das ist nicht der Platzhalter")
    print("-" * 70)
    if befunde:
        print("[FEHLER] Voice Remover unvollstaendig oder nicht auslieferbar:")
        for b in befunde:
            print("            ", b)
    else:
        groesse = 0
        for paket in VOICE_PAKETE + ("torch", "onnxruntime", "voice_models"):
            for wurzel, _d, dateien in os.walk(os.path.join(internal_dir, paket)):
                groesse += sum(os.path.getsize(os.path.join(wurzel, f)) for f in dateien)
        print("[OK]     Voice Remover vollstaendig: torch, onnxruntime, "
              "audio_separator, torchvision, voice_models - %d MB."
              % (groesse // 1_000_000))
    print("-" * 70)
    return befunde


def write_sha256(path: str) -> str:
    """
    Erzeugt neben <path> eine Datei <path>.sha256 mit Inhalt:
    <sha256>  <dateiname>
    und gibt den Pfad zur .sha256 zurück.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    out_path = path + ".sha256"
    with open(out_path, "w", encoding="ascii") as wf:
        wf.write(f"{h.hexdigest()}  {os.path.basename(path)}\n")

    print("[INFO] SHA256 geschrieben:", out_path)
    return out_path
# ensure_license_txt() ist am 30.08.2026 entfernt worden.
#
# Sie suchte disclaimer_dialog.py im Wurzelverzeichnis - die Datei liegt aber
# in views/ - und meldete deshalb bei jedem Build "nicht gefunden". Ihr
# Rueckgabewert wurde ohnehin nirgends benutzt: die GPL kommt aus der Datei
# LICENSE im Projektwurzelverzeichnis und wird weiter unten gesondert kopiert
# ("[COPY GPL]").
#
# Sie war ausserdem eine Falle: haette sie funktioniert, laege eine aus dem
# Disclaimer erzeugte LICENSE.txt im Wurzelverzeichnis - und die Suche weiter
# unten nimmt ("LICENSE", "LICENSE.txt"). Faellt LICENSE einmal weg, waere ein
# Disclaimer-Text als GPL ausgeliefert worden.

def cli_werkzeuge_entfernen(internal_dir):
    """Die Kommandozeilenwerkzeuge aus gstreamer_cli wieder herausnehmen.

    Das Paket muss mit, weil ges-1.0-0.dll darin liegt - siehe
    GSTREAMER_PAKETE. Die zwoelf .exe daneben (gst-launch, gst-inspect,
    ges-launch und Verwandte) benutzt die Anwendung nicht; sie waeren 17 MB,
    die niemand aufruft. Die DLLs bleiben unangetastet.
    """
    binordner = os.path.join(internal_dir, "gstreamer_cli", "bin")
    if not os.path.isdir(binordner):
        return 0
    entfernt = befreit = 0
    for name in os.listdir(binordner):
        if not name.lower().endswith(".exe"):
            continue
        pfad = os.path.join(binordner, name)
        try:
            befreit += os.path.getsize(pfad)
            os.remove(pfad)
            entfernt += 1
        except OSError as exc:
            print(f"[WARN] {name} nicht entfernbar: {exc}")
    if entfernt:
        print(f"[INFO] {entfernt} Kommandozeilenwerkzeug(e) aus gstreamer_cli "
              f"entfernt ({befreit / (1024*1024):.1f} MB), "
              f"ges-1.0-0.dll bleibt.")
    return entfernt


#: GIO-Module, die wir nicht brauchen und die beim Start eine Fehlermeldung
#: erzeugen. Der Name steht ohne Endung da, damit dieselbe Liste unter Windows
#: (giolibproxy.dll) und macOS (libgiolibproxy.so) greift.
UNNOETIGE_GIO_MODULE = ("giolibproxy",)


def gio_module_entfernen(ziel_ordner):
    """Den Proxy-Aufloeser von GIO aus dem fertigen Ordner nehmen.

    Beim Start meldet das Programm sonst jedes Mal:

        Failed to load module: .../lib/gio/modules/giolibproxy.dll

    Am 03.09.2026 nachgestellt: es fehlt keine Datei, es fehlt ein Suchpfad.
    Die Kette ist giolibproxy.dll -> proxy-1.dll (liegt in bin/, wird
    gefunden) -> pxbackend-1.0.dll (liegt in lib/libproxy/, und dieser
    Unterordner steht nicht im Suchpfad). Windows meldet dann Fehler 126.
    Zwei sonst gleiche Prozesse, einmal mit und einmal ohne diesen Ordner im
    Suchpfad: ohne Fehler 126, mit geladen.

    Das ist ein Verpackungsfehler der GStreamer-Wheels, nicht unserer. Repariert
    wird er hier trotzdem nicht, denn gebraucht wird das Modul nicht: es liest
    die Proxy-Einstellungen des Systems fuer Netzwerkzugriffe ueber GIO.
    KVRouite liest oertliche Dateien, und die Karte hat ihre eigene
    Netzwerkschicht (QtWebEngine). Also kommt das Modul gar nicht erst mit -
    kein Modul, kein Ladeversuch, keine Meldung.

    Das Nachbarmodul gioopenssl bleibt ausdruecklich drin: es laedt fehlerfrei,
    seine Abhaengigkeiten liegen alle in bin/.

    ACHTUNG bei macOS: das muss VOR dem Signieren passieren. Alles, was danach
    am Buendel geaendert wird, macht das Siegel ungueltig.

    Rueckgabe: die entfernten Dateien, relativ zum Zielordner.
    """
    entfernt = []
    for wurzel, _dirs, dateien in os.walk(ziel_ordner):
        teile = wurzel.replace("\\", "/").lower().split("/")
        if teile[-2:] != ["gio", "modules"]:
            continue
        for name in dateien:
            if any(m in name.lower() for m in UNNOETIGE_GIO_MODULE):
                voll = os.path.join(wurzel, name)
                try:
                    os.remove(voll)
                except OSError as fehler:
                    print("[WARN] %s liess sich nicht entfernen: %s"
                          % (name, fehler))
                    continue
                entfernt.append(os.path.relpath(voll, ziel_ordner))
    for eintrag in entfernt:
        print("[CLEAN GIO] entfernt:", eintrag)
    if not entfernt:
        print("[INFO] Kein ueberfluessiges GIO-Modul gefunden - nichts zu tun.")
    return entfernt


# ---------------------------------------------------------------------------
# Qt abspecken
# ---------------------------------------------------------------------------
# PyInstaller sammelt fuer PySide6 weit mehr ein, als die Anwendung laedt.
# Gemessen am 6.01-Build (05.09.2026): 130 Qt-DLLs mit 322 MB, davon ueber
# die Importtabellen erreichbar nur 25 mit 243 MB. Der Rest haengt am
# QML-Baum: Qt6WebEngineCore.dll importiert Qt6Quick, PyInstaller nimmt
# deshalb den ganzen qml/-Ordner mit (5000 Dateien), und dessen Plugin-DLLs
# ziehen Quick3D, Charts, Multimedia, 3D und die Controls-Stile nach -
# lauter Dinge, die kein Stueck Code hier je anfasst. Dazu kommen die
# Debug-Fassungen der WebEngine-Ressourcen (77 MB), die nur ein Debug-Qt
# laedt, und die Qt-eigenen Uebersetzungen (die Oberflaeche ist englisch).
#
# Geraten wird hier nichts. Ausgangspunkt sind die Qt-Module, die der Code
# importiert (QT_MODULE_WURZELN), dazu der WebEngine-Hilfsprozess, der
# Software-OpenGL-Renderer (config.is_soft_opengl_enabled) und die Plugins
# der behaltenen Ordner. Von dort aus werden die Importtabellen der DLLs
# gelesen (pefile, kommt mit PyInstaller) und rekursiv verfolgt. Was nicht
# erreicht wird, fliegt raus. check_qt_payload() prueft danach das Gegenteil:
# dass jede Bibliothek, die bleibt, alle ihre Importe im Buendel oder in
# Windows selbst findet. Zeigt ein Import ins Leere, bricht der Build ab -
# lieber kein Paket als eines, das beim Anwender mit "DLL nicht gefunden"
# stirbt.
#
# Was ausdruecklich BLEIBT, obwohl es keine Importtabelle erreicht:
#   opengl32sw.dll      Software-OpenGL; Qt laedt es zur Laufzeit, wenn der
#                       Anwender "use_soft_opengl" einschaltet oder die
#                       Grafikkarte keinen OpenGL-Kontext hergibt.
#   QtWebEngineProcess  der Chromium-Prozess der Karte, wird gestartet, nicht
#                       importiert.
#   qtwebengine_locales alle 53 Sprachpakete der WebEngine: welches Chromium
#                       laedt, entscheidet die Systemsprache des Anwenders.
#   resources/*.pak     die WebEngine-Ressourcen (ohne .debug-Fassungen).
#   plugins/position    winzig, und Qt6Positioning haengt an WebEngineCore.

#: Die Qt-Module, die der Quellcode importiert (grep "from PySide6."), plus
#: QtPrintSupport, das PyInstallers WebEngine-Hook als hiddenimport setzt.
QT_MODULE_WURZELN = (
    "QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtPrintSupport",
    "QtWebChannel", "QtWebEngineCore", "QtWebEngineWidgets",
)

#: Plugin-Ordner, die bleiben. Nicht dabei: qml-Werkzeuge (qmltooling), die
#: Bildschirmtastatur (platforminputcontexts, braucht den qml/-Baum).
QT_PLUGIN_ORDNER = (
    "platforms", "styles", "imageformats", "iconengines", "generic",
    "tls", "networkinformation", "position",
)

#: Einzelne Dateien in PySide6/, die ohne Importkette bleiben (siehe oben).
QT_LOSE_WURZELN = ("QtWebEngineProcess.exe", "opengl32sw.dll")

#: Pflichtdateien - fehlt eine davon nach dem Abspecken, ist das Buendel
#: kaputt, egal was die Importtabellen sagen.
QT_PFLICHT = (
    "QtWebEngineProcess.exe",
    os.path.join("plugins", "platforms", "qwindows.dll"),
    os.path.join("resources", "qtwebengine_resources.pak"),
    os.path.join("resources", "qtwebengine_resources_100p.pak"),
    os.path.join("resources", "qtwebengine_resources_200p.pak"),
    os.path.join("resources", "qtwebengine_devtools_resources.pak"),
    os.path.join("resources", "icudtl.dat"),
    os.path.join("resources", "v8_context_snapshot.bin"),
    os.path.join("translations", "qtwebengine_locales", "en-US.pak"),
    os.path.join("translations", "qtwebengine_locales", "de.pak"),
)


def _pe_importe(pfad):
    """DLL-Namen aus der Importtabelle, einschliesslich Delay-Imports."""
    import pefile
    namen = []
    pe = pefile.PE(pfad, fast_load=True)
    try:
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        for feld in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for eintrag in getattr(pe, feld, None) or []:
                namen.append(eintrag.dll.decode("ascii", "ignore"))
    finally:
        pe.close()
    return namen


def _qt_suchorte(internal_dir):
    """Wo eine importierte DLL liegen darf: PySide6/, shiboken6/, _internal/.

    Das entspricht dem Suchpfad zur Laufzeit: der Ordner der ladenden DLL,
    dazu _internal (PyInstaller setzt es an den Anfang von PATH, siehe
    pyi_rth_pyside6). Rueckgabe: kleingeschriebener Name -> Pfad.
    """
    orte = {}
    for ordner in (os.path.join(internal_dir, "PySide6"),
                   os.path.join(internal_dir, "shiboken6"),
                   internal_dir):
        if not os.path.isdir(ordner):
            continue
        for name in os.listdir(ordner):
            voll = os.path.join(ordner, name)
            if os.path.isfile(voll):
                orte.setdefault(name.lower(), voll)
    return orte


def _ist_windows_dll(name):
    """Gehoert der Name zu Windows selbst? Geprueft gegen System32 des
    Baurechners; api-ms-*/ext-ms-* sind die Umbrella-Bibliotheken der
    Universal CRT, die jedes Windows 10 hat."""
    n = name.lower()
    if n.startswith("api-ms-") or n.startswith("ext-ms-"):
        return True
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "System32")
    return os.path.isfile(os.path.join(system32, n))


def _qt_erreichbar(internal_dir):
    """Alle Dateien, die von den Wurzeln aus ueber Importtabellen erreichbar
    sind. Rueckgabe (erreichbar, offen): Pfade und die DLL-Namen, die sich
    weder im Buendel noch in Windows finden liessen."""
    ps = os.path.join(internal_dir, "PySide6")
    orte = _qt_suchorte(internal_dir)

    wurzeln = []
    for modul in QT_MODULE_WURZELN:
        treffer = [voll for name, voll in orte.items()
                   if name.startswith(modul.lower() + ".")
                   and name.endswith(".pyd")
                   and os.path.dirname(voll) == ps]
        if not treffer:
            raise SystemExit(f"[ABBRUCH] Qt-Modul {modul} fehlt in PySide6/ - "
                             f"PyInstaller hat es nicht eingesammelt.")
        wurzeln += treffer
    shib = os.path.join(internal_dir, "shiboken6")
    if os.path.isdir(shib):
        wurzeln += [os.path.join(shib, n) for n in os.listdir(shib)
                    if n.lower().endswith((".pyd", ".dll"))]
    for name in QT_LOSE_WURZELN:
        voll = os.path.join(ps, name)
        if os.path.isfile(voll):
            wurzeln.append(voll)
    for ordner in QT_PLUGIN_ORDNER:
        pfad = os.path.join(ps, "plugins", ordner)
        if os.path.isdir(pfad):
            wurzeln += [os.path.join(pfad, n) for n in os.listdir(pfad)
                        if n.lower().endswith(".dll")]

    erreichbar, offen = set(), set()
    stapel = list(wurzeln)
    while stapel:
        pfad = stapel.pop()
        if pfad in erreichbar:
            continue
        erreichbar.add(pfad)
        for name in _pe_importe(pfad):
            ziel = orte.get(name.lower())
            if ziel is None:
                if not _ist_windows_dll(name):
                    offen.add(name)
            elif ziel not in erreichbar:
                stapel.append(ziel)
    return erreichbar, offen


def _mb(bytes_):
    return bytes_ / (1024 * 1024)


def _weg(pfad, konto):
    """Datei oder Ordner entfernen und die Groesse auf konto[0] buchen."""
    if os.path.isdir(pfad):
        for wurzel, _d, dateien in os.walk(pfad):
            konto[0] += sum(os.path.getsize(os.path.join(wurzel, f))
                            for f in dateien)
        shutil.rmtree(pfad, ignore_errors=True)
    elif os.path.isfile(pfad):
        konto[0] += os.path.getsize(pfad)
        os.remove(pfad)


def qt_abspecken(internal_dir):
    """Alles aus PySide6/ nehmen, was die Anwendung nicht erreicht.

    Siehe den Kasten oben. Rueckgabe: befreite Bytes.
    """
    ps = os.path.join(internal_dir, "PySide6")
    if not os.path.isdir(ps):
        print("[QT] PySide6/ fehlt - nichts abzuspecken.")
        return 0

    erreichbar, offen = _qt_erreichbar(internal_dir)
    if offen:
        # Schon VOR dem Abspecken zeigt ein Import ins Leere - dann stimmt
        # am Build etwas nicht, und Loeschen macht es nur unuebersichtlicher.
        raise SystemExit("[ABBRUCH] Qt: Importe ohne Ziel schon vor dem "
                         "Abspecken: " + ", ".join(sorted(offen)))

    konto = [0]
    dll_weg = pyd_weg = 0
    for name in sorted(os.listdir(ps)):
        voll = os.path.join(ps, name)
        n = name.lower()
        if not os.path.isfile(voll) or voll in erreichbar:
            continue
        if n.endswith(".dll"):
            _weg(voll, konto)
            dll_weg += 1
        elif n.endswith(".pyd"):
            _weg(voll, konto)
            pyd_weg += 1
            # das Typ-Stub dazu (QtQml.pyi) - ohne Modul ohne Sinn
            _weg(os.path.join(ps, name.split(".")[0] + ".pyi"), konto)
    print(f"[QT] {dll_weg} DLLs und {pyd_weg} Module entfernt, die kein "
          f"importiertes Modul erreicht ({_mb(konto[0]):.1f} MB)")

    stand = konto[0]
    _weg(os.path.join(ps, "qml"), konto)
    print(f"[QT] qml/ entfernt ({_mb(konto[0] - stand):.1f} MB)")

    stand = konto[0]
    plugins = os.path.join(ps, "plugins")
    weg_ordner = []
    if os.path.isdir(plugins):
        for ordner in sorted(os.listdir(plugins)):
            if ordner not in QT_PLUGIN_ORDNER:
                _weg(os.path.join(plugins, ordner), konto)
                weg_ordner.append(ordner)
    print(f"[QT] Plugin-Ordner entfernt: {', '.join(weg_ordner) or '-'} "
          f"({_mb(konto[0] - stand):.1f} MB)")

    stand = konto[0]
    uebers = os.path.join(ps, "translations")
    qm = 0
    if os.path.isdir(uebers):
        for name in os.listdir(uebers):
            if name.lower().endswith(".qm"):
                _weg(os.path.join(uebers, name), konto)
                qm += 1
    print(f"[QT] {qm} Qt-Uebersetzungen (.qm) entfernt, qtwebengine_locales "
          f"bleiben ({_mb(konto[0] - stand):.1f} MB)")

    stand = konto[0]
    ress = os.path.join(ps, "resources")
    debug = 0
    if os.path.isdir(ress):
        for name in os.listdir(ress):
            if ".debug." in name.lower():
                _weg(os.path.join(ress, name), konto)
                debug += 1
    print(f"[QT] {debug} Debug-Fassungen der WebEngine-Ressourcen entfernt "
          f"({_mb(konto[0] - stand):.1f} MB)")

    print(f"[QT] zusammen {_mb(konto[0]):.1f} MB weniger")
    return konto[0]


def check_qt_payload(internal_dir):
    """Ist das abgespeckte Qt in sich vollstaendig?

    Zwei Fragen. Erstens: findet jede Bibliothek, die noch da ist - DLL,
    Modul, Plugin, Hilfsprozess - alle ihre Importe im Buendel oder in
    Windows? Das ist genau die Frage, die sonst erst der Anwender mit
    "DLL nicht gefunden" beantwortet bekaeme. Zweitens: sind die Dateien da,
    die ohne Importkette gebraucht werden (QT_PFLICHT)?

    Rueckgabe: Liste der Befunde; leer heisst in Ordnung.
    """
    ps = os.path.join(internal_dir, "PySide6")
    befunde = []
    if not os.path.isdir(ps):
        return ["PySide6/ fehlt"]

    for rel in QT_PFLICHT:
        if not os.path.isfile(os.path.join(ps, rel)):
            befunde.append(f"Pflichtdatei fehlt: PySide6/{rel}")

    for modul in QT_MODULE_WURZELN:
        if not any(n.lower().startswith(modul.lower() + ".")
                   and n.lower().endswith(".pyd") for n in os.listdir(ps)):
            befunde.append(f"Modul fehlt: PySide6/{modul}.pyd")

    orte = _qt_suchorte(internal_dir)
    geprueft = 0
    for wurzel, _d, dateien in os.walk(ps):
        for name in dateien:
            if not name.lower().endswith((".dll", ".pyd", ".exe")):
                continue
            voll = os.path.join(wurzel, name)
            geprueft += 1
            for imp in _pe_importe(voll):
                if imp.lower() in orte or _ist_windows_dll(imp):
                    continue
                befunde.append(f"{os.path.relpath(voll, internal_dir)} "
                               f"importiert {imp}, das nirgends liegt")
    print(f"[QT] {geprueft} Bibliotheken geprueft, "
          f"{len(befunde)} Befund(e)")
    for b in befunde:
        print("[QT] FEHLER:", b)
    return befunde


def check_ffmpeg_frei(target_dir):
    """
    Gegenprobe: der GPL-Vollbuild von ffmpeg darf nicht im Build liegen.

    Seit 6.0 wird ffmpeg nicht mehr mitgeliefert; der Copy-Mode holt es aus
    dem PATH des Anwenders. Der Ordner ffmpeg/ (435 MB) liegt aber weiterhin
    im Arbeitsverzeichnis, weil 5.34 daraus baut - er koennte also unbemerkt
    wieder eingepackt werden, und dann gaelte die GPL-Quellcodepflicht wieder,
    obwohl die Rechtstexte dafuer aus dem Build genommen wurden.

    ACHTUNG, hier steckt eine Falle: die GStreamer-Wheels bringen ihre EIGENEN
    FFmpeg-Bibliotheken mit (avcodec-61.dll, avformat-61.dll, avutil-59.dll,
    swresample-5.dll fuer gstlibav.dll). Das ist ein LGPL-Build, er gehoert
    dazu und ist in gstreamer/COMPONENTS.txt dokumentiert. Deshalb wird hier
    NUR auf den Ordner _internal/ffmpeg und auf die ausfuehrbaren Programme
    geprueft, niemals auf av*.dll.

    Rueckgabe ist die Liste der Fundstellen, leer heisst sauber.
    """
    programme = ("ffmpeg.exe", "ffprobe.exe", "ffplay.exe",
                 "ffmpeg", "ffprobe", "ffplay")
    funde = []
    for root, dirs, files in os.walk(target_dir):
        rel = os.path.relpath(root, target_dir)
        for d in dirs:
            if d.lower() == "ffmpeg":
                funde.append(os.path.join(rel, d))
        for f in files:
            if f.lower() in programme:
                funde.append(os.path.join(rel, f))

    print("-" * 70)
    if funde:
        print("[FEHLER] Im Build liegt noch ffmpeg:")
        for p in sorted(set(funde))[:20]:
            print("        ", p)
        if len(set(funde)) > 20:
            print("         ... und %d weitere" % (len(set(funde)) - 20))
        print("         Ab 6.0 wird ffmpeg nicht mehr mit ausgeliefert.")
        print("         Bitte den Build verwerfen und die Ursache beheben.")
    else:
        print("[OK]     Kein ffmpeg-Programm im Build - so soll es ab 6.0 sein.")
        print("         (Die LGPL-FFmpeg-Bibliotheken der GStreamer-Wheels")
        print("          gehoeren dazu und werden hier bewusst nicht geprueft.)")
    print("-" * 70)
    return sorted(set(funde))


def check_mpv_frei(target_dir):
    """
    Gegenprobe: es darf KEIN mpv mehr im Build liegen.

    Seit 6.0 laeuft die Wiedergabe allein ueber GStreamer/GES, und libmpv wird
    nicht mehr ausgeliefert. Der Ordner mpv/ liegt aber weiterhin im
    Arbeitsverzeichnis (die 5.x-Zweige brauchen ihn), und python-mpv kann noch
    in einem venv stecken. Beides koennte unbemerkt wieder in ein Bundle
    geraten - und mit 110 MB libmpv wuerde die GPL-Quellcodepflicht wieder
    gelten, obwohl die Rechtstexte dafuer aus dem Build genommen wurden.

    Deshalb wird hier nachgesehen statt darauf zu vertrauen. Rueckgabe ist die
    Liste der Fundstellen, leer heisst sauber.
    """
    funde = []
    for root, dirs, files in os.walk(target_dir):
        rel = os.path.relpath(root, target_dir)
        for d in dirs:
            if d.lower() == "mpv":
                funde.append(os.path.join(rel, d))
        for f in files:
            n = f.lower()
            # libmpv-2.dll, mpv-1.dll, libmpv.so.2, libmpv.dylib ...
            if n.startswith(("libmpv", "mpv-")) and not n.endswith(".txt"):
                funde.append(os.path.join(rel, f))
            # das Python-Modul python-mpv
            elif n in ("mpv.py", "mpv.pyc"):
                funde.append(os.path.join(rel, f))

    print("-" * 70)
    if funde:
        print("[FEHLER] Im Build liegt noch mpv:")
        for p in sorted(set(funde))[:20]:
            print("        ", p)
        if len(set(funde)) > 20:
            print("         ... und %d weitere" % (len(set(funde)) - 20))
        print("         Ab 6.0 darf libmpv nicht mehr mit ausgeliefert werden.")
        print("         Bitte den Build verwerfen und die Ursache beheben.")
    else:
        print("[OK]     Kein mpv im Build - so soll es ab 6.0 sein.")
    print("-" * 70)
    return sorted(set(funde))


def check_gstreamer_payload(internal_dir):
    """
    Prueft, ob PyInstaller die GStreamer-Runtime tatsaechlich mit eingepackt hat.

    Warum das hier steht: core/ges_backend.py macht "import gi" auf Modulebene,
    deshalb zieht PyInstaller die Wheels aus dem venv automatisch mit - oder
    eben nicht, je nachdem aus welchem venv gebaut wird. Beide Faelle sind
    zulaessig, aber sie muessen unterschiedlich dokumentiert werden:

      - DLLs vorhanden  -> wir verbreiten GPL/LGPL-Binaries. Die Rechtstexte in
                           _internal/gstreamer und das Quellcode-Angebot darin
                           sind dann Pflicht.
      - DLLs fehlen     -> der Build ist UNBRAUCHBAR. Seit 6.0 gibt es keinen
                           zweiten Wiedergabeweg mehr; KVRouite bricht dann
                           beim Start mit einer Meldung ab.

    Geprueft wird ausserdem, ob ALLE Pakete aus GSTREAMER_PAKETE da sind. Ein
    Build mit nur einem Teil davon startet nicht - genau das ist am 30.08.2026
    passiert: es kamen nur gi und gstreamer_libs mit, und die Anwendung brach
    mit "Could not deduce DLL directories" ab. Die alte Fassung dieser
    Pruefung hat das durchgewunken, weil sie nur zaehlte, ob irgendwelche
    gst-DLLs herumliegen.

    Rueckgabe: Liste der fehlenden Pakete, leer heisst vollstaendig.
    """
    marker_dirs = [
        d for d in os.listdir(internal_dir)
        if d.startswith("gstreamer_") and os.path.isdir(os.path.join(internal_dir, d))
    ]
    gi_dir = os.path.isdir(os.path.join(internal_dir, "gi"))

    gst_dlls = 0
    for root, _dirs, files in os.walk(internal_dir):
        # den reinen Lizenzordner nicht mitzaehlen
        if os.path.basename(root) == "gstreamer":
            continue
        gst_dlls += sum(1 for f in files if f.lower().startswith("gst") and f.lower().endswith(".dll"))

    fehlende = [p for p in GSTREAMER_PAKETE
                if not os.path.isdir(os.path.join(internal_dir, p))]

    print("-" * 70)
    if not (marker_dirs or gi_dir or gst_dlls):
        print("[FEHLER] GStreamer ist NICHT im Build enthalten.")
        print("         Seit 6.0 laeuft Wiedergabe, Schnitt und Export allein")
        print("         darueber - dieses Bundle startet nicht. Bitte aus einem")
        print("         venv bauen, in dem requirements.txt installiert ist.")
        print("-" * 70)
        return list(GSTREAMER_PAKETE)

    print("[LIZENZ] GStreamer WIRD mit ausgeliefert:")
    print(f"         {gst_dlls} gst*.dll, {len(GSTREAMER_PAKETE) - len(fehlende)}"
          f" von {len(GSTREAMER_PAKETE)} Paketen{', gi' if gi_dir else ''}")
    notice = os.path.join(internal_dir, "gstreamer", "NOTICE.txt")
    if os.path.isfile(notice):
        print("         Rechtstexte liegen in _internal/gstreamer - OK.")
    else:
        print("[FEHLER] _internal/gstreamer/NOTICE.txt FEHLT. So darf der Build "
              "nicht ausgeliefert werden (GPL/LGPL-Verstoss).")

    if fehlende:
        print("[FEHLER] Der Build ist UNVOLLSTAENDIG. Es fehlen:")
        for p in fehlende:
            print("            ", p)
        print("         So startet die Anwendung nicht. PyInstaller sammelt")
        print("         diese Pakete nur mit --collect-all ein - siehe")
        print("         GSTREAMER_PAKETE am Dateikopf.")
    else:
        x264 = os.path.isdir(os.path.join(internal_dir,
                                          "gstreamer_plugins_gpl_restricted"))
        print("         x264/x265-Plugins (GPL-2.0-or-later): "
              + ("ja" if x264 else "nein  -> GES-Encoder kann nicht rendern!"))
        print("[OK]     GStreamer vollstaendig.")
    print("-" * 70)
    return fehlende


def load_app_version():
    config_path = os.path.join(BASE_DIR, "config.py")
    if not os.path.isfile(config_path):
        print("[ERROR] config.py nicht gefunden!")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("config", config_path)
    config_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_module)

    if not hasattr(config_module, "APP_VERSION"):
        print("[ERROR] In config.py fehlt APP_VERSION!")
        sys.exit(1)
    return config_module.APP_VERSION

def run_cmd(cmd_list):
    print("[RUN]", " ".join(cmd_list))
    subprocess.check_call(cmd_list)

def copy_tree_all(src_dir, dst_dir):
    """
    Kopiert alle Dateien/Ordner rekursiv von src_dir nach dst_dir.
    Existiert src_dir nicht, wird eine Warnung ausgegeben.
    """
    if not os.path.isdir(src_dir):
        print("[WARN] Quellverzeichnis fehlt oder ist kein Ordner:", src_dir)
        return
    os.makedirs(dst_dir, exist_ok=True)
    for root, dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        tgt_sub = os.path.join(dst_dir, rel)
        os.makedirs(tgt_sub, exist_ok=True)
        for f in files:
            sfile = os.path.join(root, f)
            dfile = os.path.join(tgt_sub, f)
            print("[COPY]", sfile, "->", dfile)
            shutil.copy2(sfile, dfile)
            
            
def copy_only_pdfs(src_dir, dst_dir):
    """
    Kopiert nur PDF-Dateien aus src_dir (rekursiv) nach dst_dir.
    """
    if not os.path.isdir(src_dir):
        print("[WARN] Quellverzeichnis fehlt oder ist kein Ordner:", src_dir)
        return
    os.makedirs(dst_dir, exist_ok=True)
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith(".pdf"):
                sfile = os.path.join(root, f)
                rel_path = os.path.relpath(sfile, src_dir)
                dfile = os.path.join(dst_dir, rel_path)
                os.makedirs(os.path.dirname(dfile), exist_ok=True)
                print("[COPY PDF]", sfile, "->", dfile)
                shutil.copy2(sfile, dfile)            

def build_windows(build_setup: bool = False):
    app_version = load_app_version()
    print(f"[INFO] APP_VERSION: {app_version}")

    # ---------------- Basis/Ordner ----------------
    artifacts_root = os.path.join("dist", f"KVRouite_{app_version}")     # dist/KVRouite_<ver>
    os.makedirs(artifacts_root, exist_ok=True)

    exe_name_tmp = "KVRTmp"     # temporärer PyInstaller-Ordnername
    main_script  = "KVRouite.py"

    icon_file = os.path.join(BASE_DIR, "icon_icon.ico")
    if os.path.isfile(icon_file):
        print("[INFO] Icon-Datei gefunden:", icon_file)
    else:
        print("[WARN] icon_icon.ico nicht gefunden – PyInstaller nutzt Default-Icon.")

    # Voice Remover: Python-Version, Lizenzfalle, Modelle - VOR dem Packen.
    voice_voraussetzungen_pruefen()

    # ---------------- PyInstaller -----------------
    # WICHTIG: --distpath = artifacts_root → erzeugt <artifacts_root>\KVRTmp
    print("[INFO] Starte PyInstaller (onedir) → Ziel:", artifacts_root)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        f"--name={exe_name_tmp}",
        f"--distpath={artifacts_root}",
        f"--icon={icon_file}" if os.path.isfile(icon_file) else "",
    ]
    # GStreamer muss ausdruecklich mit, siehe GSTREAMER_PAKETE oben.
    cmd += [f"--collect-all={paket}" for paket in GSTREAMER_PAKETE]
    # Voice Remover: Bibliothek und Modelle, siehe VOICE_PAKETE oben.
    cmd += [f"--collect-all={paket}" for paket in VOICE_PAKETE]
    cmd += [f"--add-data={VOICE_MODELLE}{os.pathsep}voice_models"]
    cmd += [main_script]
    # leere Strings aus cmd entfernen
    cmd = [c for c in cmd if c]
    run_cmd(cmd)

    # ---------------- Nachbearbeitung -------------
    pyi_out_dir = os.path.join(artifacts_root, exe_name_tmp)               # dist/KVRouite_<ver>/KVRTmp
    exe_path    = os.path.join(pyi_out_dir, f"{exe_name_tmp}.exe")
    if not os.path.isfile(exe_path):
        raise RuntimeError(f"[ERROR] {exe_name_tmp}.exe fehlt in {pyi_out_dir} – PyInstaller-Build fehlgeschlagen.")

    target_dirname = f"KVRouite_{app_version}"
    target_dir     = os.path.join(artifacts_root, target_dirname)          # dist/KVRouite_<ver>/KVRouite_<ver>
    os.makedirs(target_dir, exist_ok=True)

    # EXE umbenennen auf KVRouite.exe (neben den restlichen Dateien)
    new_exe_path = os.path.join(target_dir, "KVRouite.exe")
    print(f"[MOVE] {exe_path} -> {new_exe_path}")
    shutil.move(exe_path, new_exe_path)

    # Rest aus PyInstaller-Ordner nach target_dir kopieren
    print(f"[INFO] Kopiere PyInstaller-Output nach {target_dir} …")
    for item in os.listdir(pyi_out_dir):
        src_item = os.path.join(pyi_out_dir, item)
        dst_item = os.path.join(target_dir, item)
        if item.lower() == f"{exe_name_tmp}.exe":
            continue  # EXE bereits verschoben
        if os.path.isdir(src_item):
            shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
        else:
            shutil.copy2(src_item, dst_item)

    # _internal vorbereiten
    internal_dir = os.path.join(target_dir, "_internal")
    os.makedirs(internal_dir, exist_ok=True)
    fehlende_rechtstexte = []
    # Rechtstexte. Ohne sie duerfte der Build nicht ausgeliefert werden, also
    # ist ein fehlender Ordner ein Fehler und keine Randnotiz.
    for quelle, ziel, was in ((LOCAL_GSTREAMER, "gstreamer", "GStreamer"),
                              (LOCAL_QT, "qt", "Qt/PySide6"),
                              (LOCAL_THIRDPARTY, "third-party-licenses",
                               "CPython, OpenSSL, Pillow, fitparse")):
        pfad = os.path.join(internal_dir, ziel)
        print(f"[INFO] Kopiere Lizenztexte {was} → {pfad}")
        if os.path.isdir(quelle):
            copy_tree_all(quelle, pfad)
        else:
            print(f"[FEHLER] {ziel}/ fehlt - die Lizenztexte fuer {was} wuerden "
                  f"NICHT mit ausgeliefert werden.")
            fehlende_rechtstexte.append(ziel)

    cli_werkzeuge_entfernen(internal_dir)
    fehlende_gstreamer_pakete = check_gstreamer_payload(internal_dir)
    voice_befunde = check_voice_payload(internal_dir)
    qt_abspecken(internal_dir)
    qt_befunde = check_qt_payload(internal_dir)

    # Taskbar-Icon zusätzlich in _internal/icon
    if os.path.isfile(icon_file):
        icon_internal_dir = os.path.join(internal_dir, "icon")
        os.makedirs(icon_internal_dir, exist_ok=True)
        icon_target_path = os.path.join(icon_internal_dir, os.path.basename(icon_file))
        print("[COPY TASKBAR ICON]", icon_file, "->", icon_target_path)
        shutil.copy2(icon_file, icon_target_path)

    # GUI-Icons neben EXE (icon/)
    gui_icon_dir_src = os.path.join(BASE_DIR, "icon")
    gui_icon_dir_dst = os.path.join(target_dir, "icon")
    if os.path.isdir(gui_icon_dir_src):
        print("[COPY GUI ICONS]", gui_icon_dir_src, "->", gui_icon_dir_dst)
        copy_tree_all(gui_icon_dir_src, gui_icon_dir_dst)
    else:
        print("[INFO] GUI-Icon-Ordner fehlt – überspringe:", gui_icon_dir_src)

    # doc: nur PDFs in _internal/doc (wie zuvor)
    doc_dir = os.path.join(BASE_DIR, "doc")
    if os.path.isdir(doc_dir):
        doc_target_dir = os.path.join(internal_dir, "doc")
        print(f"[INFO] Kopiere nur PDFs aus doc/ → {doc_target_dir}")
        copy_only_pdfs(doc_dir, doc_target_dir)
        # optionales Bild
        kinomap_logo_src = os.path.join(doc_dir, "Kinomap_Logo.png")
        if os.path.isfile(kinomap_logo_src):
            kinomap_logo_dst = os.path.join(doc_target_dir, "Kinomap_Logo.png")
            os.makedirs(os.path.dirname(kinomap_logo_dst), exist_ok=True)
            print("[COPY KINOMAP LOGO]", kinomap_logo_src, "->", kinomap_logo_dst)
            shutil.copy2(kinomap_logo_src, kinomap_logo_dst)
    else:
        print("[INFO] doc/ nicht vorhanden – überspringe.")

    
    print("[INFO] Kopiere Web-Ressourcen neben die EXE (ol.css, ol.js, map_page.html) …")
    for name in ("ol.css", "ol.js", "map_page.html"):
        candidates = [
            os.path.join(BASE_DIR, name),
            os.path.join(BASE_DIR, "doc", name),
            os.path.join(BASE_DIR, "_internal", name),
            os.path.join(BASE_DIR, "_internal", "doc", name),
        ]
        src = next((p for p in candidates if os.path.isfile(p)), None)
        if src:
            dst = os.path.join(target_dir, name)  # neben KVRouite.exe
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            print("[COPY]", src, "->", dst)
            shutil.copy2(src, dst)
        else:
            print("[INFO]", name, "nicht gefunden – überspringe.")

    # GPL-Lizenz MITLIEFERN (Root-LICENSE → neben die EXE). Agreement NICHT kopieren.
    gpl_license = None
    for cand in ("LICENSE", "LICENSE.txt"):
        p = os.path.join(BASE_DIR, cand)
        if os.path.isfile(p):
            gpl_license = p
            break

    if gpl_license:
        dst = os.path.join(target_dir, "LICENSE")  # bewusst "LICENSE" (nicht Agreement)
        print("[COPY GPL]", gpl_license, "->", dst)
        shutil.copy2(gpl_license, dst)
    else:
        print("[WARN] GPL LICENSE nicht gefunden – bitte LICENSE im Projekt-Root hinterlegen.")

    # README.md NICHT mitliefern
    print("[INFO] README.md wird NICHT in den Zielordner kopiert.")


    print(f"[INFO] PyInstaller-Struktur OK: {os.path.abspath(target_dir)}")
    print("[INFO] Enthält: KVRouite.exe, ol.css, ol.js, map_page.html, icon/, _internal/…")

    # Das GIO-Proxy-Modul heraus, bevor gepackt wird - siehe
    # gio_module_entfernen(). Danach kommt nichts mehr dazu.
    gio_module_entfernen(target_dir)

    # Letzte Gegenprobe, wenn nichts mehr dazukommt: kein mpv im Bundle.
    # Findet sich doch welches, wird hier abgebrochen - ein ZIP oder ein
    # Installer mit libmpv darin waere schon ausgeliefert, bevor es jemand
    # merkt, und zoege die GPL-Quellcodepflicht nach sich.
    if check_mpv_frei(target_dir):
        raise SystemExit("[ABBRUCH] Build enthaelt mpv - nicht ausliefern.")
    if check_ffmpeg_frei(target_dir):
        raise SystemExit("[ABBRUCH] Build enthaelt ffmpeg - nicht ausliefern.")
    if fehlende_gstreamer_pakete:
        raise SystemExit("[ABBRUCH] GStreamer ist unvollstaendig - der Build "
                         "wuerde nicht starten.")
    if voice_befunde:
        raise SystemExit("[ABBRUCH] Voice Remover: %s." % "; ".join(voice_befunde))
    if qt_befunde:
        raise SystemExit("[ABBRUCH] Qt ist nach dem Abspecken unvollstaendig "
                         "(%d Befund(e), siehe [QT] FEHLER oben) - so wuerde "
                         "der Build beim Anwender nicht starten."
                         % len(qt_befunde))
    if fehlende_rechtstexte:
        raise SystemExit("[ABBRUCH] Rechtstexte fehlen (%s) - so darf der Build "
                         "nicht ausgeliefert werden."
                         % ", ".join(fehlende_rechtstexte))

    # ---------------- portable ZIP + SHA ----------------
    ARCH_SUFFIX = "Win_x64"
    zip_name_wo_ext = f"KVRouite_{app_version}_{ARCH_SUFFIX}"
    zip_base = os.path.join(artifacts_root, zip_name_wo_ext)
    print(f"[INFO] Erzeuge ZIP → {zip_base}.zip (Inhalt = {target_dirname}/)")
    zip_path = shutil.make_archive(
        base_name=zip_base,
        format="zip",
        root_dir=artifacts_root,      # Top ist artifacts_root
        base_dir=target_dirname       # wir packen den Ordner KVRouite_<ver> hinein
    )
    print("[INFO] ZIP erstellt:", zip_path)
    write_sha256(zip_path)

    # ---------------- Inno Setup (optional) + SHA ---------------
    if build_setup:
        print("[INFO] Erzeuge Windows-Installer (Inno Setup) …")
        # Versionstext neben EXE (nice-to-have)
        try:
            with open(os.path.join(target_dir, "version.txt"), "w", encoding="utf-8") as vf:
                vf.write(str(app_version))
        except Exception as e:
            print("[WARN] version.txt konnte nicht geschrieben werden:", e)

        iscc = os.environ.get("ISCC", r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
        if not os.path.isfile(iscc):
            print("[ERROR] ISCC.exe nicht gefunden. Setze ENV ISCC oder installiere Inno Setup 6.")
            sys.exit(2)

        iss_file = os.path.join(BASE_DIR, "installer", "KVRouite.iss")
        if not os.path.isfile(iss_file):
            print("[ERROR] installer\\KVRouite.iss fehlt – kann Installer nicht bauen.")
            sys.exit(2)

        icon_in_dist = os.path.join(target_dir, "icon", "icon_icon.ico")
        if not os.path.isfile(icon_in_dist):
            icon_in_dist = icon_file if os.path.isfile(icon_file) else ""

        license_file = None
        for cand in ("LICENSE.txt", "LICENSE"):
            p = os.path.join(BASE_DIR, cand)
            if os.path.isfile(p):
                license_file = p
                break
        eula_path = os.path.join(BASE_DIR, "installer", "AGREEMENT.txt")
        if not os.path.isfile(eula_path):
            print("[ERROR] EULA/AGREEMENT fehlt: installer\\AGREEMENT.txt – ohne diese Datei breche ich den Setup-Build ab.")
            sys.exit(2)


        defines = [
            f"/DMyDistDir={os.path.abspath(target_dir)}",
            f"/DMyAppVersion={app_version}",
        ]
        
        # leere Strings aus defines filtern:
        #defines = [d for d in defines if d]
        
        if icon_in_dist:
            defines.append(f"/DMyIconFile={os.path.abspath(icon_in_dist)}")
        if license_file:
            defines.append(f"/DMyLicense={os.path.abspath(license_file)}")

        # Output nach artifacts_root
        print("[RUN] ISCC → OutputDir =", os.path.abspath(artifacts_root))
        subprocess.run([iscc, "/O" + os.path.abspath(artifacts_root)] + defines + [iss_file], check=True)

        installer_path = os.path.join(artifacts_root, f"KVRouite_v{app_version}_Win_x64_Installer.exe")
        if os.path.isfile(installer_path):
            print("[INFO] Installer erstellt:", installer_path)
            write_sha256(installer_path)
        else:
            print("[WARN] Installer nicht gefunden (erwartet):", installer_path)
    try:
        print("[CLEAN] Entferne temporären PyInstaller-Ordner:", os.path.abspath(pyi_out_dir))
        shutil.rmtree(pyi_out_dir, ignore_errors=True)
    except Exception as e:
        print("[WARN] Konnte Temp-Ordner nicht entfernen:", e)
    print()
    print(f"[INFO] Fertig. Alles liegt in: {os.path.abspath(artifacts_root)}")
    print(f"[INFO] - Ordner: {target_dirname}\\")
    print(f"[INFO] - ZIP   : KVRouite_{app_version}_Win_x64.zip (+ .sha256)")
    if build_setup:
        print(f"[INFO] - SETUP : KVRouite_Setup_v{app_version}_Win_x64.exe (+ .sha256)")




def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--build-installer", action="store_true", help="Build Windows installer via Inno Setup")
    args = p.parse_args()
    if platform.system() != "Windows":
        print("[WARN] Only Windows supported here.")
        sys.exit(1)
    build_windows(build_setup=args.build_installer)

if __name__ == "__main__":
    main()
