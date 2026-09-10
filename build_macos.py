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
"""
Baut KVRouite als macOS-Anwendungsbuendel (KVRouite.app).

    python3 build_macos.py

Warum ein eigenes Skript und keine Erweiterung von build_with_pyinstaller.py:
der Windows-Weg baut einen Ordner mit KVRouite.exe, haengt _internal/ daneben,
entfernt Kommandozeilenwerkzeuge aus dem GStreamer-Paket und ruft am Ende Inno
Setup auf. Auf macOS ist das Ergebnis ein Buendel mit festgelegter innerer
Ordnung, das Symbol ist eine .icns statt einer .ico, und einen Installer gibt
es nicht - ausgeliefert wird das gezippte Buendel. Beides in einer Funktion mit
Weichen zu halten waere unuebersichtlicher als zwei Dateien.

GETEILT wird, was geteilt gehoert: die Gegenproben (kein ffmpeg, kein mpv, die
Rechtstexte) und die Pruefsumme kommen aus build_with_pyinstaller.py. Sie
duerfen nicht auseinanderlaufen - ein Mac-Buendel mit libmpv darin zoege
dieselbe GPL-Quellcodepflicht nach sich wie ein Windows-Build.

WO DIE DATEIEN LANDEN, und warum ausgerechnet dort: die Anwendung sucht
map_page.html neben ihrem Programm, sie rechnet in widgets/map_widget.py mit
os.path.dirname(sys.argv[0]). In einem Buendel ist das Contents/MacOS. Dort
liegen die Web-Dateien deshalb, obwohl Contents/Resources der uebliche Ort
waere. Wer das umstellen will, aendert zuerst die Suche im Programm.
"""

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Aus dem Windows-Skript: Gegenproben und Pruefsumme. Import statt Kopie, damit
# beide Wege dieselben Regeln anwenden und nicht auseinanderlaufen.
from build_with_pyinstaller import (      # noqa: E402
    GSTREAMER_PAKETE,
    QT_MODULE_WURZELN,
    QT_PLUGIN_ORDNER,
    VOICE_MODELLE,
    VOICE_PAKETE,
    _dist_info_ist_platzhalter,
    check_ffmpeg_frei,
    check_mpv_frei,
    gio_module_entfernen,
    copy_only_pdfs,
    copy_tree_all,
    load_app_version,
    voice_voraussetzungen_pruefen,
    write_sha256,
)
# Mach-O erkennen und otool -L lesen - dieselben Funktionen wie in der
# Buendelpruefung, damit beide dasselbe unter "Verweis" verstehen.
from tools.pruefe_macos_buendel import (  # noqa: E402
    ist_mach_o,
    mach_o_dateien_sammeln,
    verweise_lesen,
)

LOCAL_GSTREAMER = os.path.join(BASE_DIR, "gstreamer")
LOCAL_QT = os.path.join(BASE_DIR, "qt")
LOCAL_THIRDPARTY = os.path.join(BASE_DIR, "third-party-licenses")

#: Neben das Programm im Buendel - die Anwendung sucht sie dort.
WEB_RESSOURCEN = ("ol.css", "ol.js", "map_page.html")


def lauf(befehl):
    print("[CMD]", " ".join(befehl))
    subprocess.run(befehl, check=True)


#: Die gi-Module, deren PyInstaller-Hooks auf ein systemweit installiertes
#: GObject-Introspection ausgelegt sind. Aus dem fehlgeschlagenen Lauf vom
#: 02.09.2026 - jedes davon meldete "Unable to find gir directory", und bei
#: Gio brach der Build ab.
#
#: "gi" selbst steht ABSICHTLICH nicht in der Liste: dessen Hook sammelt die
#: Python-Overrides von PyGObject, die zur Laufzeit gebraucht werden. Nur die
#: Hooks der einzelnen Bibliotheken suchen an Systemorten.
GI_MODULE = (
    "gi.repository.GLib", "gi.repository.GObject", "gi.repository.GModule",
    "gi.repository.Gio", "gi.repository.Gst", "gi.repository.GstBase",
    "gi.repository.GstApp", "gi.repository.GstAudio", "gi.repository.GstVideo",
    "gi.repository.GstController", "gi.repository.GstPbutils",
    "gi.repository.GstGL", "gi.repository.GstNet", "gi.repository.GstTag",
    "gi.repository.GstRtp", "gi.repository.GstSdp", "gi.repository.GstCheck",
    "gi.repository.GES",
)


def hooks_verzeichnis_anlegen():
    """Ein Hook-Verzeichnis, das die eingebauten gi-Hooks stilllegt.

    Warum das noetig ist: PyInstaller bringt fuer jedes gi.repository-Modul
    einen Hook mit, der die Bibliothek ueber den SYSTEMWEITEN Weg sucht -
    share/gir-1.0 und die dylibs an den ueblichen Orten. Bei uns kommt
    GStreamer aus den Wheels: die Typelibs liegen in
    gstreamer_libs/lib/girepository-1.0, ein gir-Verzeichnis gibt es gar
    nicht. Unter Windows faellt das nicht auf, weil die .pth-Datei den PATH
    setzt und die DLLs dort gefunden werden. Auf macOS brach der Lauf ab mit
    "Could not resolve any shared library of Gio 2.0".

    Die eigenen Hooks sind leer. Sie sammeln nichts, sie suchen nichts - was
    gebraucht wird, holen die --collect-all der gstreamer-Pakete ohnehin
    heran, samt der Typelibs.

    PyInstaller durchsucht die zusaetzlichen Verzeichnisse vor den eigenen;
    ein gleichnamiger Hook hier ersetzt also den eingebauten.
    """
    ordner = os.path.join(BASE_DIR, "build", "hooks_macos")
    if os.path.isdir(ordner):
        shutil.rmtree(ordner)
    os.makedirs(ordner)
    mit_override = 0
    for modul in GI_MODULE:
        # Die Python-Schicht ueber der Introspection MUSS mit. Ohne sie ist
        # zum Beispiel Gst.init(None) nicht erlaubt - das erste Buendel brach
        # daran ab mit "Argument 1 does not allow None as a value". Der
        # eingebaute Hook haette den Override eingesammelt; wenn wir ihn
        # stilllegen, muessen wir das selbst tun.
        kurz = modul.split(".")[-1]
        override = "gi.overrides." + kurz
        hat_override = importlib.util.find_spec(override) is not None
        if hat_override:
            mit_override += 1
        pfad = os.path.join(ordner, "hook-%s.py" % modul)
        with open(pfad, "w", encoding="utf-8") as f:
            f.write("# Erzeugt von build_macos.py - siehe dort die Begruendung.\n")
            f.write("# Legt die Bibliothekssuche des eingebauten Hooks fuer\n")
            f.write("# %s still, nimmt den Override aber mit.\n" % modul)
            f.write("hiddenimports = %r\n" % ([override] if hat_override else []))
            f.write("datas = []\n")
            f.write("binaries = []\n")
            f.write("excludedimports = []\n")
    print("[INFO] %d eigene gi-Hooks in %s (%d mit Override)"
          % (len(GI_MODULE), ordner, mit_override))
    return ordner


def vorhandene_gstreamer_pakete():
    """Welche der GStreamer-Pakete auf DIESEM Rechner installiert sind.

    --collect-all fuer ein Paket, das es nicht gibt, laesst PyInstaller sofort
    abbrechen. Unter Windows liegen alle elf im Wheel; ob das auf macOS ebenso
    ist, entscheidet das dortige Wheel und nicht diese Liste. Deshalb wird
    gefragt statt angenommen - und was fehlt, steht im Log, damit man sieht,
    womit gebaut wurde.
    """
    da, fehlt = [], []
    for paket in GSTREAMER_PAKETE:
        if importlib.util.find_spec(paket) is not None:
            da.append(paket)
        else:
            fehlt.append(paket)
    print("[INFO] GStreamer-Pakete installiert: %d von %d"
          % (len(da), len(GSTREAMER_PAKETE)))
    for p in fehlt:
        print("   nicht installiert:", p)
    if not da:
        raise SystemExit("[ABBRUCH] Kein einziges GStreamer-Paket gefunden - "
                         "ohne die Laufzeit hat ein Buendel keinen Sinn. "
                         "Wurde requirements.txt installiert?")
    return da


def buendel_bauen(ziel_ordner):
    """PyInstaller aufrufen. Rueckgabe: Pfad des .app-Buendels."""
    # Voice Remover: Python-Version, Lizenzfalle, Modelle - VOR dem Packen.
    voice_voraussetzungen_pruefen()
    symbol = os.path.join(BASE_DIR, "MyIcon.icns")
    if not os.path.isfile(symbol):
        print("[WARN] MyIcon.icns fehlt - das Buendel bekommt das Standardsymbol.")

    befehl = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",                 # erzeugt das .app-Buendel
        "--name=KVRouite",
        "--distpath=" + ziel_ordner,
        # Die Kennung taucht im Finder auf und wird fuer Fensterrechte gebraucht.
        "--osx-bundle-identifier=com.kvrouite.app",
    ]
    if os.path.isfile(symbol):
        befehl.append("--icon=" + symbol)
    befehl.append("--additional-hooks-dir=" + hooks_verzeichnis_anlegen())
    # selftest wird nur innerhalb von main() importiert; ausdruecklich nennen,
    # damit PyInstaller es nicht uebersieht.
    befehl.append("--hidden-import=selftest")
    # nachweis.py wird ebenso nur innerhalb von main() importiert.
    befehl.append("--hidden-import=nachweis")
    # GStreamer muss ausdruecklich mit, aber nur was da ist: ein --collect-all
    # auf ein fehlendes Paket bricht PyInstaller sofort ab.
    befehl += ["--collect-all=" + paket for paket in vorhandene_gstreamer_pakete()]
    # Voice Remover: Bibliothek und Modelle - siehe VOICE_PAKETE im
    # Windows-Skript, dieselben Gruende. Die Modelle landen als Daten in
    # Contents/Resources/voice_models; config.finde_datei sucht dort.
    befehl += ["--collect-all=" + paket for paket in VOICE_PAKETE]
    befehl.append("--add-data=" + VOICE_MODELLE + os.pathsep + "voice_models")
    befehl.append("KVRouite.py")
    lauf(befehl)

    buendel = os.path.join(ziel_ordner, "KVRouite.app")
    if not os.path.isdir(buendel):
        raise SystemExit("[ABBRUCH] PyInstaller hat kein KVRouite.app erzeugt.")
    return buendel


def ressourcen_einlegen(buendel):
    """Alles, was die Anwendung zur Laufzeit neben sich sucht."""
    macos_dir = os.path.join(buendel, "Contents", "MacOS")
    os.makedirs(macos_dir, exist_ok=True)

    for name in WEB_RESSOURCEN:
        quelle = os.path.join(BASE_DIR, name)
        if os.path.isfile(quelle):
            print("[COPY]", name, "->", macos_dir)
            shutil.copy2(quelle, os.path.join(macos_dir, name))
        else:
            print("[WARN]", name, "nicht gefunden - die Karte bliebe leer.")

    symbol_ordner = os.path.join(BASE_DIR, "icon")
    if os.path.isdir(symbol_ordner):
        print("[COPY] icon/ ->", macos_dir)
        copy_tree_all(symbol_ordner, os.path.join(macos_dir, "icon"))
    else:
        print("[WARN] icon/ fehlt - die Knoepfe blieben ohne Symbole.")


def rechtstexte_einlegen(buendel):
    """Die Lizenztexte ins Buendel. Rueckgabe: Liste der fehlenden."""
    resources = os.path.join(buendel, "Contents", "Resources")
    os.makedirs(resources, exist_ok=True)
    fehlen = []
    for quelle, ziel, was in ((LOCAL_GSTREAMER, "gstreamer", "GStreamer"),
                              (LOCAL_QT, "qt", "Qt/PySide6"),
                              (LOCAL_THIRDPARTY, "third-party-licenses",
                               "CPython, OpenSSL, Pillow, fitparse")):
        pfad = os.path.join(resources, ziel)
        if os.path.isdir(quelle):
            print("[INFO] Lizenztexte " + was + " -> " + pfad)
            copy_tree_all(quelle, pfad)
        else:
            print("[FEHLER] " + ziel + "/ fehlt - die Lizenztexte fuer " + was
                  + " wuerden NICHT mit ausgeliefert.")
            fehlen.append(ziel)

    lizenz = None
    for name in ("LICENSE", "LICENSE.txt"):
        kandidat = os.path.join(BASE_DIR, name)
        if os.path.isfile(kandidat):
            lizenz = kandidat
            break
    if lizenz:
        print("[COPY GPL]", lizenz, "-> Contents/Resources/LICENSE")
        shutil.copy2(lizenz, os.path.join(resources, "LICENSE"))
    else:
        print("[WARN] LICENSE fehlt im Projekt-Root.")
        fehlen.append("LICENSE")

    doc = os.path.join(BASE_DIR, "doc")
    if os.path.isdir(doc):
        ziel_doc = os.path.join(resources, "doc")
        print("[INFO] Nur die PDFs aus doc/ -> " + ziel_doc)
        copy_only_pdfs(doc, ziel_doc)
        # Das Kinomap-Logo ist kein PDF, wird aber gebraucht: es steht in der
        # GPX-Leiste und im Copyright-Fenster. Der Windows-Build kopiert es
        # ausdruecklich mit, hier fehlte es - der Selbsttest im ersten Buendel
        # hat es gemeldet.
        logo = os.path.join(doc, "Kinomap_Logo.png")
        if os.path.isfile(logo):
            os.makedirs(ziel_doc, exist_ok=True)
            print("[COPY] Kinomap_Logo.png -> " + ziel_doc)
            shutil.copy2(logo, os.path.join(ziel_doc, "Kinomap_Logo.png"))
        else:
            print("[WARN] doc/Kinomap_Logo.png fehlt im Projekt.")
    return fehlen


def gstreamer_pruefen(buendel):
    """Ist die GStreamer-Laufzeit wirklich im Buendel gelandet?

    core/ges_backend.py macht "import gi" auf Modulebene: fehlt die Laufzeit,
    startet das Buendel nicht, und zwar ohne brauchbare Meldung. Gesucht wird
    im ganzen Buendel, weil PyInstaller auf macOS anders einsortiert als unter
    Windows - Contents/Frameworks statt _internal.
    """
    erwartet = vorhandene_gstreamer_pakete()
    gefunden = set()
    for _wurzel, ordner, _dateien in os.walk(buendel):
        for name in ordner:
            if name in erwartet:
                gefunden.add(name)
    fehlend = [p for p in erwartet if p not in gefunden]
    print("[LIZENZ] GStreamer im Buendel: %d von %d installierten Paketen."
          % (len(gefunden), len(erwartet)))
    for p in sorted(gefunden):
        print("   vorhanden:", p)
    for p in fehlend:
        print("   FEHLT    :", p)
    return fehlend


def voice_pruefen(buendel):
    """Der Voice Remover im Buendel - das Gegenstueck zu check_voice_payload
    im Windows-Skript. Gesucht wird im ganzen Buendel: PyInstaller legt auf
    macOS Binaerdateien nach Contents/Frameworks und Daten nach
    Contents/Resources. Rueckgabe: Liste der Befunde."""
    from core import stimme
    erwartet = set(VOICE_PAKETE + ("torch", "onnxruntime", "voice_models"))
    gefunden = {}
    verboten = []
    for wurzel, ordner, _dateien in os.walk(buendel):
        for name in ordner:
            if name in erwartet and name not in gefunden:
                gefunden[name] = os.path.join(wurzel, name)
            # Die dist-info von diffq/diffq-fixed muss der Platzhalter sein
            # (siehe tools/diffq_platzhalter) - erkennbar an "KVRouite".
            if (name.lower().startswith(("diffq_fixed", "diffq-"))
                    and name.endswith(".dist-info")
                    and not _dist_info_ist_platzhalter(os.path.join(wurzel, name))):
                verboten.append(os.path.join(wurzel, name))
    befunde = ["%s fehlt im Buendel" % p for p in sorted(erwartet - set(gefunden))]
    modelle = gefunden.get("voice_models")
    if modelle:
        for _kennung, (datei, name) in stimme.MODELLE.items():
            if not os.path.isfile(os.path.join(modelle, datei)):
                befunde.append("Modell %s (%s) fehlt" % (datei, name))
    befunde += ["%s im Buendel - CC BY-NC, nicht auslieferbar" % v
                for v in verboten]
    print("[LIZENZ] Voice Remover im Buendel: %d von %d Teilen."
          % (len(gefunden), len(erwartet)))
    for b in befunde:
        print("   FEHLER   :", b)
    return befunde




# ---------------------------------------------------------------------------
# Qt abspecken - das Gegenstueck zu qt_abspecken() im Windows-Skript
# ---------------------------------------------------------------------------
# Dasselbe Prinzip, andere Mechanik. Unter Windows liest pefile die
# Importtabellen der DLLs; hier liest otool -L die Ladebefehle der
# Mach-O-Dateien. Und statt flacher DLLs liegen die Qt-Bibliotheken als
# Frameworks in Contents/Frameworks/PySide6/Qt/lib, jedes ein Ordner mit
# Versions/A/<Name> als eigentlicher Bibliothek und einem Geflecht aus
# Symlinks darum (Versions/Current, <Name>, Resources).
#
# PyInstaller teilt das Buendel ausserdem in zwei Baeume: Binaerdateien in
# Contents/Frameworks, Daten in Contents/Resources, und verknuepft beide mit
# Symlinks (siehe pyi_rth_pyside6: der qml-Baum liegt deshalb doppelt). Wird
# auf der einen Seite etwas entfernt, bleibt auf der anderen ein Symlink ins
# Leere zurueck - den raeumt symlinks_ins_leere_entfernen() ab, denn codesign
# --deep stolpert sonst darueber.
#
# Gemessen am arm64-Buendel 6.10: 124 Frameworks mit 391 MB, der qml-Baum
# 30 MB in beiden Baeumen zusammen, 9 MB Qt-Uebersetzungen. Die
# Debug-Fassungen der WebEngine-Ressourcen gibt es auf macOS nicht.
#
# Reihenfolge im Bau: NACH ressourcen_einlegen() und VOR signieren() - wie
# gio_module_entfernen(). Alles, was nach dem Signieren geaendert wird, macht
# das Siegel ungueltig.

#: Verweise, die nicht ins Buendel zeigen muessen: Bestandteile von macOS.
_SYSTEM_PRAEFIXE = ("/usr/lib/", "/System/")

#: Pflichtdateien relativ zu Contents/Frameworks/PySide6. Der V8-Schnappschuss
#: heisst je Architektur anders (v8_context_snapshot.arm64.bin bzw.
#: .x86_64.bin), deshalb steht er nicht hier, sondern wird gesondert gesucht.
_WEBENGINE_RES = os.path.join("Qt", "lib", "QtWebEngineCore.framework",
                              "Versions", "A", "Resources")
QT_PFLICHT_MACOS = (
    os.path.join("Qt", "lib", "QtWebEngineCore.framework", "Versions", "A",
                 "Helpers", "QtWebEngineProcess.app", "Contents", "MacOS",
                 "QtWebEngineProcess"),
    os.path.join("Qt", "plugins", "platforms", "libqcocoa.dylib"),
    os.path.join(_WEBENGINE_RES, "qtwebengine_resources.pak"),
    os.path.join(_WEBENGINE_RES, "qtwebengine_resources_100p.pak"),
    os.path.join(_WEBENGINE_RES, "qtwebengine_resources_200p.pak"),
    os.path.join(_WEBENGINE_RES, "qtwebengine_devtools_resources.pak"),
    os.path.join(_WEBENGINE_RES, "icudtl.dat"),
    os.path.join(_WEBENGINE_RES, "qtwebengine_locales", "en-US.pak"),
    os.path.join(_WEBENGINE_RES, "qtwebengine_locales", "de.pak"),
)


def _qt_orte(buendel):
    """Die drei Orte, um die es geht: Frameworks/PySide6, Resources/PySide6
    und der Framework-Ordner Qt/lib."""
    fw = os.path.join(buendel, "Contents", "Frameworks", "PySide6")
    res = os.path.join(buendel, "Contents", "Resources", "PySide6")
    return fw, res, os.path.join(fw, "Qt", "lib")


def _verweise(pfad):
    """otool -L als Liste; ein Lesefehler ist ein Baufehler, kein Schulterzucken."""
    liste, ausgabe = verweise_lesen(pfad)
    if liste is None:
        raise SystemExit("[ABBRUCH] otool kann %s nicht lesen:\n%s"
                         % (pfad, ausgabe))
    return liste


def _verweis_aufloesen(verweis, datei, buendel):
    """Wohin zeigt ein Ladebefehl? Rueckgabe (pfad, system).

    pfad ist der aufgeloeste Pfad im Buendel oder None; system True heisst,
    der Verweis gehoert zu macOS und braucht keine Datei im Buendel.

    @rpath wird so aufgeloest, wie der Lader es zur Laufzeit tut, nur mit
    festen Kandidaten statt der LC_RPATH-Eintraege: Contents/Frameworks, der
    PySide6-Ordner darin, Qt/lib, shiboken6 und der Ordner der Datei selbst.
    Das sind alle Orte, an denen PyInstaller Qt-Bibliotheken ablegt.

    Am 6.10-Buendel abgelesen (LC_LOAD_DYLIB/LC_RPATH aus den Bytes): jeder
    LC_RPATH zeigt ueber @loader_path/.. auf Contents/Frameworks, und die
    Verweise lauten "@rpath/QtCore", "@rpath/libpyside6.abi3.6.11.dylib" -
    ohne Framework-Pfad. Aufgeloest werden sie ueber Symlinks, die
    PyInstaller direkt in Contents/Frameworks anlegt. Deshalb steht
    Contents/Frameworks hier an erster Stelle, und deshalb geht das Ergebnis
    durch realpath(): der Symlink zaehlt nichts, die Datei dahinter alles.
    """
    if verweis.startswith(_SYSTEM_PRAEFIXE):
        return None, True
    frameworks = os.path.join(buendel, "Contents", "Frameworks")
    fw, _res, qt_lib = _qt_orte(buendel)
    hier = os.path.dirname(datei)
    if verweis.startswith("@rpath/"):
        rest = verweis[len("@rpath/"):]
        kandidaten = [frameworks, fw, qt_lib,
                      os.path.join(frameworks, "shiboken6"), hier]
    elif verweis.startswith("@loader_path/"):
        rest = verweis[len("@loader_path/"):]
        kandidaten = [hier]
    elif verweis.startswith("@executable_path/"):
        rest = verweis[len("@executable_path/"):]
        kandidaten = [os.path.join(buendel, "Contents", "MacOS")]
    elif os.path.isabs(verweis):
        # Ein absoluter Pfad ausserhalb von macOS: Bau-Rechner-Pfad. Das
        # meldet tools/pruefe_macos_buendel.py ohnehin; hier zaehlt er als
        # nicht aufloesbar.
        return None, False
    else:
        rest = verweis
        kandidaten = [hier]
    for basis in kandidaten:
        voll = os.path.normpath(os.path.join(basis, rest))
        if os.path.isfile(voll):
            return os.path.realpath(voll), False
    return None, False


def _qt_erreichbar_macos(buendel):
    """Alle Mach-O-Dateien, die von den Wurzeln aus erreichbar sind.

    Rueckgabe (erreichbar, offen): realpath-Menge und die Verweise, die sich
    weder im Buendel noch in macOS finden liessen.
    """
    fw, _res, qt_lib = _qt_orte(buendel)
    wurzeln = []
    for modul in QT_MODULE_WURZELN:
        treffer = [os.path.join(fw, n) for n in os.listdir(fw)
                   if n.startswith(modul + ".") and n.endswith(".so")]
        if not treffer:
            raise SystemExit("[ABBRUCH] Qt-Modul %s fehlt in %s - PyInstaller "
                             "hat es nicht eingesammelt." % (modul, fw))
        wurzeln += treffer
    shib = os.path.join(buendel, "Contents", "Frameworks", "shiboken6")
    if os.path.isdir(shib):
        wurzeln += [os.path.join(shib, n) for n in os.listdir(shib)
                    if n.endswith((".so", ".dylib"))]
    helfer = os.path.join(fw, QT_PFLICHT_MACOS[0])
    if os.path.isfile(helfer):
        wurzeln.append(helfer)
    for ordner in QT_PLUGIN_ORDNER:
        pfad = os.path.join(fw, "Qt", "plugins", ordner)
        if os.path.isdir(pfad):
            wurzeln += [os.path.join(pfad, n) for n in os.listdir(pfad)
                        if n.endswith(".dylib")]

    erreichbar, offen = set(), set()
    stapel = [os.path.realpath(w) for w in wurzeln]
    while stapel:
        datei = stapel.pop()
        if datei in erreichbar or not ist_mach_o(datei):
            continue
        erreichbar.add(datei)
        for verweis in _verweise(datei):
            ziel, system = _verweis_aufloesen(verweis, datei, buendel)
            if system:
                continue
            if ziel is None:
                offen.add(verweis)
            elif ziel not in erreichbar:
                stapel.append(ziel)
    return erreichbar, offen


def _groesse(pfad):
    """Bytes unter pfad, Symlinks nicht mitgezaehlt (sie zeigen woandershin)."""
    if os.path.islink(pfad):
        return 0
    if os.path.isfile(pfad):
        return os.path.getsize(pfad)
    summe = 0
    for wurzel, ordner, dateien in os.walk(pfad):
        ordner[:] = [o for o in ordner
                     if not os.path.islink(os.path.join(wurzel, o))]
        for name in dateien:
            voll = os.path.join(wurzel, name)
            if not os.path.islink(voll):
                summe += os.path.getsize(voll)
    return summe


def _weg_macos(pfad, konto):
    """Datei, Symlink oder Ordner entfernen; Groesse auf konto[0] buchen."""
    if os.path.islink(pfad) or os.path.isfile(pfad):
        konto[0] += _groesse(pfad)
        os.remove(pfad)
    elif os.path.isdir(pfad):
        konto[0] += _groesse(pfad)
        shutil.rmtree(pfad)


def symlinks_ins_leere_finden(ordner):
    """Alle Symlinks unter ordner, deren Ziel es nicht gibt. Symlink-Ordner
    werden nicht betreten - sonst liefe die Suche durch die Frameworks
    mehrfach (Versions/Current -> A)."""
    gefunden = []
    for wurzel, unterordner, dateien in os.walk(ordner):
        for name in list(unterordner) + dateien:
            voll = os.path.join(wurzel, name)
            if os.path.islink(voll):
                if not os.path.exists(voll):
                    gefunden.append(voll)
                if name in unterordner:
                    unterordner.remove(name)
    return gefunden


def symlinks_ins_leere_entfernen(ordner, protokoll=False):
    """Symlinks entfernen, deren Ziel es nicht mehr gibt. Rueckgabe: Anzahl."""
    leer = symlinks_ins_leere_finden(ordner)
    for voll in leer:
        if protokoll:
            print("[QT]   Link ohne Ziel: %s -> %s"
                  % (os.path.relpath(voll, ordner), os.readlink(voll)))
        os.remove(voll)
    return len(leer)


def qt_abspecken_macos(buendel):
    """Alles aus PySide6 nehmen, was die Anwendung nicht erreicht.

    Siehe den Kasten oben. Rueckgabe: befreite Bytes.
    """
    fw, res, qt_lib = _qt_orte(buendel)
    if not os.path.isdir(fw):
        print("[QT] Contents/Frameworks/PySide6 fehlt - nichts abzuspecken.")
        return 0

    erreichbar, offen = _qt_erreichbar_macos(buendel)
    if offen:
        raise SystemExit("[ABBRUCH] Qt: Verweise ohne Ziel schon vor dem "
                         "Abspecken: " + ", ".join(sorted(offen)))

    konto = [0]

    # 1) Frameworks, in denen keine erreichte Datei liegt. Geprueft wird
    #    ueber den Ordner, nicht ueber den Symlink <Name>.framework/<Name>:
    #    der zeigt ueber Versions/Current auf die Bibliothek, und ein
    #    Buendel ohne diese Symlinks (siehe zippen) soll genauso behandelt
    #    werden wie eines mit.
    weg_fw = []
    if os.path.isdir(qt_lib):
        for name in sorted(os.listdir(qt_lib)):
            if not name.endswith(".framework"):
                continue
            ordner = os.path.join(qt_lib, name)
            wurzel = os.path.realpath(ordner) + os.sep
            if not any(d.startswith(wurzel) for d in erreichbar):
                _weg_macos(ordner, konto)
                weg_fw.append(name[:-len(".framework")])
    print("[QT] %d Frameworks entfernt, die kein importiertes Modul erreicht "
          "(%.1f MB)" % (len(weg_fw), konto[0] / (1024 * 1024)))

    # 2) Python-Module und lose dylibs im PySide6-Ordner, samt Gegenstueck
    #    im Resources-Baum
    stand = konto[0]
    weg_mod = 0
    for name in sorted(os.listdir(fw)):
        voll = os.path.join(fw, name)
        if os.path.islink(voll) or not os.path.isfile(voll):
            continue
        if not name.endswith((".so", ".dylib")):
            continue
        if os.path.realpath(voll) in erreichbar:
            continue
        _weg_macos(voll, konto)
        weg_mod += 1
        for gegen in (os.path.join(res, name),
                      os.path.join(res, name.split(".")[0] + ".pyi")):
            if os.path.lexists(gegen):
                _weg_macos(gegen, konto)
    print("[QT] %d Module/Bibliotheken entfernt (%.1f MB)"
          % (weg_mod, (konto[0] - stand) / (1024 * 1024)))

    # 3) der qml-Baum, auf beiden Seiten
    stand = konto[0]
    for seite in (fw, res):
        pfad = os.path.join(seite, "Qt", "qml")
        if os.path.lexists(pfad):
            _weg_macos(pfad, konto)
    print("[QT] Qt/qml entfernt (%.1f MB)" % ((konto[0] - stand) / (1024 * 1024)))

    # 4) Plugin-Ordner, die nicht auf der Liste stehen
    stand = konto[0]
    plugins = os.path.join(fw, "Qt", "plugins")
    weg_pl = []
    if os.path.isdir(plugins):
        for name in sorted(os.listdir(plugins)):
            if name not in QT_PLUGIN_ORDNER:
                _weg_macos(os.path.join(plugins, name), konto)
                weg_pl.append(name)
    print("[QT] Plugin-Ordner entfernt: %s (%.1f MB)"
          % (", ".join(weg_pl) or "-", (konto[0] - stand) / (1024 * 1024)))

    # 5) Qt-Uebersetzungen (.qm). Die WebEngine-Sprachpakete liegen im
    #    Framework selbst und bleiben.
    stand = konto[0]
    qm = 0
    uebers = os.path.join(res, "Qt", "translations")
    if os.path.isdir(uebers):
        for name in os.listdir(uebers):
            if name.endswith(".qm"):
                _weg_macos(os.path.join(uebers, name), konto)
                qm += 1
    print("[QT] %d Qt-Uebersetzungen (.qm) entfernt (%.1f MB)"
          % (qm, (konto[0] - stand) / (1024 * 1024)))

    # 6) Symlinks, die jetzt ins Leere zeigen. Dazu gehoert die oberste
    #    Ebene von Contents/Frameworks: PyInstaller schreibt die Ladebefehle
    #    auf "@rpath/QtCore" um, mit @rpath = Contents/Frameworks, und legt
    #    dort fuer jede Framework-Bibliothek einen Symlink QtCore ->
    #    PySide6/Qt/lib/QtCore.framework/Versions/A/QtCore an. Fuer jedes
    #    entfernte Framework bleibt so ein Link ohne Ziel zurueck.
    #    Gesucht wird im GANZEN Buendel, nicht nur unter PySide6. Der erste
    #    Lauf auf GitHub (05.09.2026) scheiterte an der Gegenprobe des
    #    Siegels mit "No such file or directory": PyInstaller legt auch
    #    direkt in Contents/Resources fuer jede Framework-Bibliothek einen
    #    Symlink an (QtQuick3D -> PySide6/Qt/lib/QtQuick3D.framework/
    #    Versions/A/QtQuick3D), der ueber den Verzeichnis-Symlink
    #    Resources/PySide6/Qt/lib in den Frameworks-Baum fuehrt. 104 davon
    #    zeigten nach dem Abspecken ins Leere, standen aber im Siegel.
    leer = symlinks_ins_leere_entfernen(buendel, protokoll=True)
    print("[QT] %d Symlinks ins Leere entfernt" % leer)

    print("[QT] zusammen %.1f MB weniger" % (konto[0] / (1024 * 1024)))
    return konto[0]


def check_qt_payload_macos(buendel):
    """Ist das abgespeckte Qt in sich vollstaendig? Rueckgabe: Befunde.

    Erstens: findet jede Mach-O-Datei unter PySide6 alle ihre Verweise im
    Buendel oder in macOS? Zweitens: sind die Pflichtdateien da? Drittens:
    zeigt kein Symlink unter PySide6 mehr ins Leere?
    """
    fw, res, _qt_lib = _qt_orte(buendel)
    befunde = []
    if not os.path.isdir(fw):
        return ["Contents/Frameworks/PySide6 fehlt"]

    for rel in QT_PFLICHT_MACOS:
        if not os.path.isfile(os.path.join(fw, rel)):
            befunde.append("Pflichtdatei fehlt: PySide6/" + rel)
    res_dir = os.path.join(fw, _WEBENGINE_RES)
    if os.path.isdir(res_dir) and not any(
            n.startswith("v8_context_snapshot") and n.endswith(".bin")
            for n in os.listdir(res_dir)):
        befunde.append("Pflichtdatei fehlt: v8_context_snapshot.*.bin")

    for modul in QT_MODULE_WURZELN:
        if not any(n.startswith(modul + ".") and n.endswith(".so")
                   for n in os.listdir(fw)):
            befunde.append("Modul fehlt: PySide6/%s.abi3.so" % modul)

    geprueft = 0
    for datei in mach_o_dateien_sammeln(fw):
        geprueft += 1
        for verweis in _verweise(datei):
            ziel, system = _verweis_aufloesen(verweis, datei, buendel)
            if system or ziel is not None:
                continue
            befunde.append("%s verweist auf %s, das nirgends liegt"
                           % (os.path.relpath(datei, buendel), verweis))

    for voll in symlinks_ins_leere_finden(buendel):
        befunde.append("Symlink ins Leere: %s -> %s"
                       % (os.path.relpath(voll, buendel), os.readlink(voll)))

    print("[QT] %d Mach-O-Dateien geprueft, %d Befund(e)"
          % (geprueft, len(befunde)))
    for b in befunde:
        print("[QT] FEHLER:", b)
    return befunde


def architektur():
    """Fuer welche CPU dieser Lauf baut - "arm64" oder "x86_64".

    Der Wert kommt aus platform.machine(), also aus dem Python, das gerade
    laeuft, und damit aus genau dem, was PyInstaller gleich baut. Nicht aus
    dem Namen der Maschine: GitHub nennt seine Runner "macos-15" und
    "macos-15-intel", das ist die macOS-Version plus ein Zusatz und sagt ueber
    den Prozessor nichts Verlaessliches. Und wer auf einem Apple-Silicon-Mac
    ein Python unter Rosetta startet, baut x86_64 - platform.machine() sagt
    dann x86_64, der Maschinenname weiter arm64. Der Name des Archivs muss
    dem folgen, was drin ist.

    Warum das zaehlt: bis zum 02.09.2026 hiessen beide Archive gleich
    (KVRouite_6.02_macOS.zip). Nebeneinander gelegt ueberschrieb eines das
    andere, und die Pruefsummendatei zeigte danach auf die falsche Datei.
    """
    return platform.machine()


def signieren(buendel):
    """Das Buendel signieren - ZUM SCHLUSS, wenn nichts mehr dazukommt.

    PyInstaller signiert das Buendel selbst (ad hoc; auf Apple Silicon MUSS es
    das, sonst startet gar nichts). Danach legen ressourcen_einlegen() und
    rechtstexte_einlegen() aber noch Dateien hinein, und die stehen dann nicht
    im Siegel. Auf einem fremden Mac sieht das so aus:

        KVRouite.app: a sealed resource is missing or invalid
        file added: .../Contents/MacOS/ol.css
        file added: .../Contents/MacOS/map_page.html
        file added: .../Contents/Resources/qt/NOTICE.txt
        ...

    So gemeldet am 02.09.2026 von einem Anwender - die Liste war Zeile fuer
    Zeile unsere eigene Kopierliste.

    Auf dem Bauserver faellt das nicht auf, und zwar aus zwei Gruenden: das
    Buendel entsteht dort lokal und traegt deshalb kein Quarantaene-Merkmal,
    ohne das schaut Gatekeeper gar nicht hin; und gestartet wird ueber die
    Signatur des HAUPTPROGRAMMS, die unveraendert gueltig ist - das Siegel
    ueber die Beidateien wird nur bei einer ausdruecklichen Pruefung
    ausgewertet. Der Lauf war also gruen, das Buendel trotzdem kaputt.

    Deshalb wird hier zum Schluss neu signiert und sofort gegengeprueft.
    Ad hoc ("-"), nicht mit einem Zertifikat: das nimmt Gatekeeper die Meldung
    ueber das kaputte Siegel. Die Meldung ueber den unbekannten Entwickler
    bleibt - dafuer braeuchte es ein Apple-Entwicklerzertifikat.

    --deep allein reicht nicht - es nimmt den Hilfsprogrammen die Rechte
    ---------------------------------------------------------------------
    Der erste Anlauf signierte nur mit --deep, und damit war die KARTE weg.
    --deep signiert jedes eingebettete Programm mit, und dabei verliert es
    SEINE EIGENEN Entitlements. Betroffen ist QtWebEngineProcess, der Renderer der
    Web-Ansicht: Qt legt ihm QtWebEngineProcess.entitlements bei, darin steht
    com.apple.security.cs.allow-jit. Auf Apple Silicon darf ohne dieses Recht
    kein Prozess ausfuehrbaren Speicher anlegen - und genau das tut Chromium.
    Der Renderer stirbt beim Start, die Anwendung laeuft weiter, und die Karte
    bleibt weiss. Das Videobild ist nicht betroffen, GStreamer braucht kein JIT.

    Nachgemessen am ausgelieferten 6.03-Buendel: der Signaturblock von
    QtWebEngineProcess enthielt nur CodeDirectory (0xfade0c02), Requirements
    (0xfade0c01) und die Signatur (0xfade0b01) - kein Entitlements-Blob
    (0xfade7171). Vor 6.03 wurde hier gar nicht nachsigniert, deshalb trug der
    Helfer noch die Originalsignatur aus dem Qt-Wheel und die Karte war da.

    Der zweite Anlauf liess --deep ganz weg - und scheiterte am aeusseren
    Siegel, weil dann nichts Eingebettetes signiert war. Der Ablauf hat
    deshalb DREI Schritte, und die Reihenfolge ist der ganze Trick:

      1. --deep ueber alles. Das muss sein: die GStreamer-Bibliotheken kommen
         erst NACH PyInstaller ins Buendel und sind unsigniert. Ohne diesen
         Durchgang bricht Schritt 3 mit "code object is not signed at all" ab -
         das aeussere Siegel verlangt, dass alles Eingebettete gueltig
         signiert ist. Genau daran ist der erste Anlauf gescheitert.
      2. Die Hilfsprogramme DANACH noch einmal, jedes mit seinen eigenen
         Entitlements. Damit ist repariert, was Schritt 1 ihnen genommen hat.
      3. Jede SCHALE um das Hilfsprogramm herum, von innen nach aussen, und
         zuletzt das Buendel selbst - alle ohne --deep. Ein Siegel umfasst
         das, was darin liegt; wer innen etwas aendert, macht jedes Siegel
         darueber ungueltig. QtWebEngineProcess.app liegt in
         QtWebEngineCore.framework, und genau daran ist der dritte Anlauf
         gescheitert:

             KVRouite.app: nested code is modified or invalid
             In subcomponent: .../QtWebEngineCore.framework

         Damals wurde nur das aeussere Buendel nachsigniert, das Framework
         dazwischen nicht. Die Schalen werden deshalb nicht aufgezaehlt,
         sondern aus dem Pfad des Hilfsprogramms abgeleitet - ein anderer
         Qt-Aufbau bringt andere Schalen mit, und die waeren sonst wieder
         vergessen.

         Ohne --deep, sonst faengt Schritt 1 wieder von vorn an und die
         Rechte waeren erneut weg.

    Zum PRUEFEN ist --deep dagegen richtig, dort steht es weiter unten.
    """
    codesign = shutil.which("codesign")
    if codesign is None:
        raise SystemExit("[ABBRUCH] codesign nicht gefunden - ohne gueltiges "
                         "Siegel darf das Buendel nicht ausgeliefert werden.")

    print("[SIGN] 1/3 alles Eingebettete signieren (--deep)")
    signieren_lauf([codesign, "--force", "--deep", "--sign", "-", buendel])

    helfer = hilfsprogramme_mit_rechten(buendel)
    if not helfer:
        raise SystemExit(
            "[ABBRUCH] Kein Hilfsprogramm mit Entitlements gefunden. "
            "QtWebEngineProcess muss eines sein - ohne seine Rechte bliebe "
            "die Karte leer, und das faellt sonst erst im fertigen Buendel auf.")
    schalen = []
    for programm, rechte in helfer:
        print("[SIGN] 2/3 Rechte zurueckgeben: %s"
              % os.path.relpath(programm, buendel))
        signieren_lauf([codesign, "--force", "--sign", "-",
                        "--entitlements", rechte, programm])
        schalen.extend(umgebende_schalen(programm, buendel))

    # Von innen nach aussen: der laengere Pfad liegt tiefer. Ein Siegel darf
    # erst gesetzt werden, wenn alles darin fertig ist.
    for schale in sorted(set(schalen), key=len, reverse=True):
        print("[SIGN] 3/3 Schale nachversiegeln: %s"
              % os.path.relpath(schale, buendel))
        signieren_lauf([codesign, "--force", "--sign", "-", schale])

    print("[SIGN] 3/3 Buendel versiegeln (ohne --deep)")
    signieren_lauf([codesign, "--force", "--sign", "-", buendel])

    print("[SIGN] Gegenprobe - meldet jede Datei, die nicht im Siegel steht")
    try:
        signieren_lauf([codesign, "--verify", "--deep", "--strict",
                        "--verbose=2", buendel])
    except SystemExit:
        siegel_diagnose(codesign, buendel)
        raise

    for programm, _rechte in helfer:
        rechte_nachweisen(codesign, programm, buendel)
    print("[SIGN] Siegel in Ordnung")


def siegel_diagnose(codesign, buendel):
    """Wenn die Gegenprobe scheitert: WELCHES eingebettete Teil ist es?

    codesign --verify --deep nennt bei "No such file or directory" nur das
    Buendel, nicht das Teil, an dem es haengt (so am 05.09.2026 auf GitHub,
    nach dem Abspecken von Qt). Deshalb hier zweierlei: alle Symlinks ohne
    Ziel im ganzen Buendel, und jedes eingebettete Teil einzeln geprueft -
    jeder Eintrag direkt in Contents/Frameworks und jedes Framework unter
    PySide6/Qt/lib. Nur Protokoll, nichts wird geaendert.
    """
    print("[SIGN] Diagnose: Symlinks ohne Ziel im ganzen Buendel")
    leer = symlinks_ins_leere_finden(buendel)
    for voll in leer[:60]:
        print("      %s -> %s" % (os.path.relpath(voll, buendel),
                                  os.readlink(voll)))
    print("      %d gefunden" % len(leer))

    print("[SIGN] Diagnose: eingebettete Teile einzeln pruefen")
    frameworks = os.path.join(buendel, "Contents", "Frameworks")
    teile = []
    if os.path.isdir(frameworks):
        for name in sorted(os.listdir(frameworks)):
            voll = os.path.join(frameworks, name)
            if not os.path.islink(voll):
                teile.append(voll)
    qt_lib = os.path.join(frameworks, "PySide6", "Qt", "lib")
    if os.path.isdir(qt_lib):
        teile += [os.path.join(qt_lib, n) for n in sorted(os.listdir(qt_lib))
                  if n.endswith(".framework")]
    schlecht = 0
    for teil in teile:
        if os.path.isdir(teil) and not teil.endswith((".framework", ".app")):
            continue                      # Paketordner, kein Code-Objekt
        if os.path.isfile(teil) and not ist_mach_o(teil):
            continue
        ergebnis = subprocess.run([codesign, "--verify", "--strict", teil],
                                  capture_output=True)
        if ergebnis.returncode != 0:
            schlecht += 1
            grund = (ergebnis.stderr or b"").decode("utf-8", "replace").strip()
            print("      FEHLER %s: %s"
                  % (os.path.relpath(teil, buendel), grund.replace(chr(10), " | ")))
    print("      %d von %d Teilen mit Befund" % (schlecht, len(teile)))


def signieren_lauf(befehl):
    """Wie lauf(), aber die Meldung von codesign landet im Protokoll.

    codesign schreibt seinen Grund nach stderr, und im Bauprotokoll ging der
    zwischen den uebrigen Ausgaben unter - der erste fehlgeschlagene Lauf
    zeigte nur "Process completed with exit code 1". Hier steht er
    ausdruecklich und mit Rahmen.
    """
    print("[CMD]", " ".join(befehl))
    ergebnis = subprocess.run(befehl, capture_output=True)
    for strom in (ergebnis.stdout, ergebnis.stderr):
        text = (strom or b"").decode("utf-8", "replace").strip()
        if text:
            for zeile in text.splitlines():
                print("      %s" % zeile)
    if ergebnis.returncode != 0:
        raise SystemExit(
            "[ABBRUCH] codesign endete mit %d. Der Grund steht in den Zeilen "
            "darueber." % ergebnis.returncode)


def hilfsprogramme_mit_rechten(buendel):
    """Eingebettete .app-Buendel, die eigene Entitlements mitbringen.

    Gesucht wird nach der Datei und nicht nach einem festen Pfad: der Ort von
    QtWebEngineProcess haengt an der Qt-Version, und kaeme spaeter ein
    weiteres Hilfsprogramm mit eigenen Rechten dazu, waere es hier von selbst
    dabei.

    Rueckgabe: Liste (pfad_zum_app_buendel, pfad_zur_entitlements_datei).
    """
    gefunden = []
    for wurzel, _ordner, dateien in os.walk(buendel):
        for name in dateien:
            if not name.endswith(".entitlements"):
                continue
            rechte = os.path.join(wurzel, name)
            # .../Foo.app/Contents/Resources/Foo.entitlements -> .../Foo.app
            teil = wurzel
            while teil and not teil.endswith(".app"):
                naechst = os.path.dirname(teil)
                if naechst == teil:
                    teil = None
                    break
                teil = naechst
            if teil and os.path.abspath(teil) != os.path.abspath(buendel):
                gefunden.append((teil, rechte))
    return sorted(set(gefunden))


def umgebende_schalen(programm, buendel):
    """Signierte Behaelter zwischen programm und buendel, von innen nach aussen.

    Ein Siegel umfasst alles, was darin liegt. Wer ein Hilfsprogramm tief im
    Buendel neu signiert, macht damit jedes Siegel darueber ungueltig - beim
    QtWebEngine-Helfer ist das QtWebEngineCore.framework, und danach das
    Buendel selbst. Beide muessen danach neu versiegelt werden, sonst meldet
    die Gegenprobe "nested code is modified or invalid".

    Abgeleitet aus dem Pfad und nicht aufgezaehlt: ein anderer Qt-Aufbau
    bringt andere Schalen mit.
    """
    raus = []
    ende = os.path.abspath(buendel)
    pfad = os.path.dirname(os.path.abspath(programm))
    while pfad and pfad != ende and pfad.startswith(ende):
        if pfad.endswith(".framework") or pfad.endswith(".app"):
            raus.append(pfad)
        naechst = os.path.dirname(pfad)
        if naechst == pfad:
            break
        pfad = naechst
    return raus


def rechte_nachweisen(codesign, programm, buendel):
    """Belegen, dass die Entitlements die Signierung ueberlebt haben.

    Ohne diesen Nachweis waere der Bauplan wieder da, wo er beim Siegel schon
    einmal war: gruen, aber nichts geprueft. Die Ausgabe von codesign ist je
    nach macOS-Version XML oder ein Blob mit Vorspann - deshalb wird schlicht
    im Rohtext nach dem Recht gesucht, das den Unterschied macht.
    """
    ergebnis = subprocess.run(
        [codesign, "-d", "--entitlements", "-", programm],
        capture_output=True)
    roh = (ergebnis.stdout or b"") + (ergebnis.stderr or b"")
    kurz = os.path.relpath(programm, buendel)
    if b"allow-jit" in roh:
        print("[SIGN] Rechte vorhanden (allow-jit): %s" % kurz)
        return
    raise SystemExit(
        "[ABBRUCH] %s hat keine Entitlements mehr. Ohne allow-jit kann der "
        "Renderer der Web-Ansicht auf Apple Silicon keinen ausfuehrbaren "
        "Speicher anlegen - die Karte bliebe leer. Ausgabe von codesign:\n%s"
        % (kurz, roh.decode("utf-8", "replace")))


def zippen(buendel, ziel_ordner, app_version):
    """Das Buendel als ZIP - so wird es abgelegt und weitergegeben.

    Gepackt wird mit ditto und nicht mit zipfile, und dafuer gibt es zwei
    Gruende. Erstens die Rechte: ohne das Ausfuehrbar-Bit an
    Contents/MacOS/KVRouite startet das entpackte Buendel nicht. Zweitens die
    Verweise: in Contents/Frameworks stehen Symlinks (Versions/Current zeigt
    auf A). zipfile legt fuer jeden davon eine VOLLE KOPIE ab - das Archiv
    waechst, und die Struktur eines Frameworks ist danach nicht mehr die, die
    macOS erwartet.

    ditto gehoert zu macOS und ist genau dafuer da. Der Rueckfall auf zipfile
    steht nur fuer den Fall, dass es einmal fehlt; er ist ausdruecklich die
    schlechtere Fassung und sagt das auch.
    """
    name = "KVRouite_%s_macOS_%s.zip" % (app_version, architektur())
    ziel = os.path.join(ziel_ordner, name)
    print("[INFO] Packe", ziel)

    ditto = shutil.which("ditto")
    if ditto:
        lauf([ditto, "-c", "-k", "--sequesterRsrc", "--keepParent",
              buendel, ziel])
        print("[INFO] ZIP erstellt (ditto):", ziel)
        return ziel

    print("[WARN] ditto nicht gefunden - packe mit zipfile. Symlinks werden "
          "dabei zu Kopien, und die Rechte haengen am Dateisystem.")
    wurzel_oben = os.path.dirname(buendel)
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as archiv:
        for wurzel, _ordner, dateien in os.walk(buendel):
            for datei in dateien:
                voll = os.path.join(wurzel, datei)
                drin = os.path.relpath(voll, wurzel_oben)
                eintrag = zipfile.ZipInfo.from_file(voll, drin)
                eintrag.external_attr = (os.stat(voll).st_mode & 0xFFFF) << 16
                eintrag.compress_type = zipfile.ZIP_DEFLATED
                with open(voll, "rb") as f:
                    archiv.writestr(eintrag, f.read())
    print("[INFO] ZIP erstellt (zipfile):", ziel)
    return ziel


def build_macos():
    if sys.platform != "darwin":
        raise SystemExit("[ABBRUCH] Dieses Skript baut fuer macOS und laeuft "
                         "nur dort. Fuer Windows: build_with_pyinstaller.py")

    app_version = load_app_version()
    print("[INFO] APP_VERSION:", app_version)
    print("[INFO] Architektur:", architektur())

    ziel_ordner = os.path.join(
        BASE_DIR, "dist",
        "KVRouite_%s_macOS_%s" % (app_version, architektur()))
    if os.path.isdir(ziel_ordner):
        print("[INFO] Alten Ordner entfernen:", ziel_ordner)
        shutil.rmtree(ziel_ordner)
    os.makedirs(ziel_ordner, exist_ok=True)

    buendel = buendel_bauen(ziel_ordner)
    ressourcen_einlegen(buendel)
    fehlende_rechtstexte = rechtstexte_einlegen(buendel)
    fehlende_gstreamer = gstreamer_pruefen(buendel)
    voice_befunde = voice_pruefen(buendel)

    # Qt abspecken - VOR dem Signieren, wie alles, was das Buendel anfasst.
    qt_abspecken_macos(buendel)
    qt_befunde = check_qt_payload_macos(buendel)

    # Das GIO-Proxy-Modul heraus - VOR dem Signieren, sonst waere das Siegel
    # sofort wieder ungueltig.
    gio_module_entfernen(buendel)

    # Die Gegenproben ganz zum Schluss, wenn nichts mehr dazukommt.
    if check_mpv_frei(buendel):
        raise SystemExit("[ABBRUCH] Buendel enthaelt mpv - nicht ausliefern.")
    if check_ffmpeg_frei(buendel):
        raise SystemExit("[ABBRUCH] Buendel enthaelt ffmpeg - nicht ausliefern.")
    if fehlende_gstreamer:
        raise SystemExit("[ABBRUCH] GStreamer ist unvollstaendig (%s) - das "
                         "Buendel wuerde nicht starten."
                         % ", ".join(fehlende_gstreamer))
    if voice_befunde:
        raise SystemExit("[ABBRUCH] Voice Remover: %s." % "; ".join(voice_befunde))
    if fehlende_rechtstexte:
        raise SystemExit("[ABBRUCH] Rechtstexte fehlen (%s) - so darf das "
                         "Buendel nicht ausgeliefert werden."
                         % ", ".join(fehlende_rechtstexte))
    if qt_befunde:
        raise SystemExit("[ABBRUCH] Qt ist nach dem Abspecken unvollstaendig "
                         "(%d Befund(e), siehe [QT] FEHLER oben) - so wuerde "
                         "das Buendel beim Anwender nicht starten."
                         % len(qt_befunde))

    # Signieren als LETZTER Schritt, der das Buendel anfasst - danach wird nur
    # noch gepackt. Kommt hier jemals etwas dazu, muss es DAVOR passieren.
    signieren(buendel)

    archiv = zippen(buendel, ziel_ordner, app_version)
    write_sha256(archiv)

    print("")
    print("[FERTIG] Buendel:", buendel)
    print("[FERTIG] Archiv :", archiv)
    print("")
    print("Das Buendel ist ad hoc signiert - das Siegel ist vollstaendig und")
    print("passt zum Inhalt. Es ist NICHT notarisiert: auf einem fremden Mac")
    print("meldet Gatekeeper einen unbekannten Entwickler. Der Anwender oeffnet")
    print("es einmal ueber Systemeinstellungen -> Datenschutz & Sicherheit ->")
    print("\"Trotzdem oeffnen\"; der frueher uebliche Rechtsklick -> Oeffnen ist")
    print("seit macOS 15 (Sequoia) abgeschafft. Fuer den Wegfall auch dieser")
    print("Meldung braeuchte es ein Entwicklerzertifikat von Apple.")
    return buendel


def main():
    build_macos()


if __name__ == "__main__":
    main()
