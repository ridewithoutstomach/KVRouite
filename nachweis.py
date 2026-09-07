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
Bildnachweis: die Anwendung mit echtem Material starten und dabei fotografieren.

    KVRouite.exe --screenshot
    KVRouite.app/Contents/MacOS/KVRouite --screenshot

Warum es diese Datei gibt: der Bauplan konnte bisher zwei Dinge zeigen - dass
der Selbsttest durchlaeuft (selftest.py) und dass der Prozess nach 25 Sekunden
noch lebt. Beides sagt nichts darueber, ob wirklich ein Fenster steht, ob die
Karte da ist und ob sich im Video etwas bewegt.

Hier wird deshalb dasselbe getan, was ein Anwender tut: eine GPX-Spur und ein
Video laden, auf Wiedergabe druecken - und dann DREI Bilder im Abstand von
zwei Sekunden machen. Wer die drei Bilder nebeneinanderlegt, sieht am Ball im
Testvideo und an der Zeitleiste, dass sich etwas bewegt hat. Ein einzelnes
Standbild koennte auch ein eingefrorenes Fenster sein.

Aufgenommen wird mit QWidget.grab(), also von Qt selbst, nicht ueber ein
Bildschirmfoto des Systems: so entstehen die Bilder auch mit
QT_QPA_PLATFORM=offscreen, wo es gar keinen Bildschirm gibt. Das geht nur,
weil die Anwendung das Videobild selbst malt - GStreamer liefert die Bilder
ueber appsink an Qt (widgets/video_editor_widget.py erzeugt den Player immer
mit frame_callback, siehe core/ges_backend.py). Waere das Bild von GStreamer
in ein Fensterhandle gezeichnet, stuende in den Aufnahmen ein schwarzes Loch.

Das Material baut sich diese Datei selbst, mit denselben Bausteinen wie der
Selbsttest: 8 Sekunden Testvideo mit einem springenden Ball und eine kurze
GPX-Spur. Es wird also nichts vorausgesetzt, was auf einem Bauserver nicht da
waere.
"""

import os
import tempfile

#: Wann die drei Bilder entstehen - Sekunden nach dem Druck auf Wiedergabe.
ZEITPUNKTE = (2.0, 4.0, 6.0)

#: Wieviel Zeit Karte, Video und Zeitleiste zum Laden bekommen, bevor die
#: Wiedergabe startet. Die Karte kommt ueber QtWebEngine und ist nicht sofort
#: da; auf einem Bauserver ohne Grafikkarte dauert es laenger als hier.
LADEZEIT = 12.0

#: Groesse des Fensters fuer die Aufnahme - siehe bilder_machen().
def _fenstergroesse():
    """Fenstergroesse fuer die Aufnahme, ueber die Umgebung einstellbar.

    KVROUITE_PROOF_SIZE="1200x800" setzt sie. Gebraucht wird das, um denselben
    Nachweis zweimal zu fahren - einmal klein, einmal gross: unter
    QT_QPA_PLATFORM=offscreen meldet Qt einen virtuellen Bildschirm von
    800x800, und was darueber hinausgeht, bekommt von Chromium keine
    Zeichenflaeche mehr. Alles andere im Fenster malt Qt selbst und ist davon
    nicht betroffen - die Karte ist das einzige, was fehlt.
    """
    wert = os.environ.get("KVROUITE_PROOF_SIZE", "").lower().strip()
    if "x" in wert:
        try:
            b, h = wert.split("x", 1)
            return (max(640, int(b)), max(480, int(h)))
        except ValueError:
            pass
    return (1920, 1200)


FENSTERGROESSE = _fenstergroesse()

#: So heissen die Bilder. Die Nummer wird angehaengt.
DATEINAME = "KVRouite_screenshot"
#: Hier landet die Antwort der Kartenseite als eine einzige Zeile. Im
#: Bauprotokoll steht sie sonst zwischen tausenden anderen und ist nicht zu
#: finden; der Bauplan liest diese Datei und stellt sie oben in die
#: Zusammenfassung.
KARTENDATEI = "KVRouite_proof_map.txt"


def _material(ordner):
    """Testvideo und Testspur erzeugen. Rueckgabe: (video, gpx, fehler)."""
    import selftest
    video = os.path.join(ordner, "nachweis_video.mp4")
    fehler = selftest._testvideo_bauen(video)
    if fehler:
        return None, None, fehler
    gpx = os.path.join(ordner, "nachweis_spur.gpx")
    with open(gpx, "w", encoding="utf-8") as datei:
        datei.write(selftest.GPX_INHALT)
    return video, gpx, None


#: Wie die Fragen beantwortet werden, die beim Laden eines Videos kommen.
#: Schluessel ist der Fenstertitel, Wert der Rueckgabewert von exec().
#: "Edit video" bietet Copy / Encode / No Edit an - 2 ist Encode, seit 6.0 der
#: uebliche Weg. Alles andere wird mit der Vorbelegung bestaetigt (accept),
#: also so, wie ein Anwender es durchklicken wuerde.
DIALOG_ANTWORTEN = {"Edit video": 2}


def _dialoge_beantworten(app, log):
    """Modale Fragen automatisch beantworten. Rueckgabe: der Zeitgeber.

    Beim Laden eines Videos fragt die Anwendung zweimal nach: einmal nach dem
    Bearbeitungsmodus (views/mainwindow.py, process_open_mp4) und einmal nach
    der Ausgabe-Bildrate (_fps_nach_laden). Beide laufen mit exec() in einer
    eigenen Ereignisschleife und warten auf einen Klick - auf einem Bauserver
    klickt niemand, und der Lauf steht.

    Frueher habe ich versucht, die Dialoge zu umgehen, indem die Einzelschritte
    von process_open_mp4() nachgebaut wurden. Das ging schief: die zweite Frage
    steckt eine Ebene tiefer in add_to_playlist(), und mit jedem Nachbau
    entfernt sich der Nachweis von dem Weg, den ein Anwender wirklich geht.
    Deshalb jetzt andersherum - der echte Weg wird gegangen, und die Fragen
    werden beantwortet.

    Der Zeitgeber muss vom Aufrufer festgehalten werden, sonst raeumt Python
    ihn weg.
    """
    from PySide6.QtCore import QTimer

    def nachsehen():
        fenster = app.activeModalWidget()
        if fenster is None:
            return
        titel = fenster.windowTitle() or fenster.__class__.__name__
        antwort = DIALOG_ANTWORTEN.get(titel)
        try:
            if antwort is not None:
                fenster.done(antwort)
                log("[PROOF] dialog answered: %s -> %d" % (titel, antwort))
            else:
                fenster.accept()
                log("[PROOF] dialog answered: %s -> default" % titel)
        except Exception as exc:
            log("[PROOF] dialog %s could not be answered: %s" % (titel, exc))

    zeitgeber = QTimer()
    zeitgeber.timeout.connect(nachsehen)
    zeitgeber.start(200)
    return zeitgeber


#: Fragt die Kartenseite, ob OpenLayers wirklich eine Karte gebaut hat.
#: Ein Bild kann das nicht belegen: unter QT_QPA_PLATFORM=offscreen liefert
#: Chromium keine Zeichenflaeche, die Aufnahme zeigt dort ein leeres Feld -
#: gemessen unter Windows bei jeder Fenstergroesse. Das Kartenobjekt entsteht
#: trotzdem, und danach laesst sich fragen.
KARTENFRAGE = """
(function () {
  try {
    if (typeof map === 'undefined' || !map) { return 'kein map-Objekt'; }
    var ebenen = map.getLayers().getLength();
    var groesse = map.getSize();
    return 'ok layers=' + ebenen + ' size=' +
           (groesse ? groesse[0] + 'x' + groesse[1] : 'null');
  } catch (e) { return 'Fehler: ' + e; }
})()
"""


def _karte_fragen(fenster, log, ablage):
    """Die Kartenseite nach ihrem Zustand fragen. Antwort landet in ablage."""
    try:
        karte = getattr(fenster, "map_widget", None)
        ansicht = getattr(karte, "view", None) if karte is not None else None
        if ansicht is None:
            ablage["antwort"] = "kein Kartenfenster"
            return

        def zurueck(wert):
            ablage["antwort"] = str(wert)
            log("[PROOF] map page says: %s" % wert)
            try:
                with open(os.path.abspath(KARTENDATEI), "w",
                          encoding="utf-8") as datei:
                    datei.write(str(wert) + "\n")
            except Exception as exc:
                log("[PROOF] %s not written: %s" % (KARTENDATEI, exc))

        ansicht.page().runJavaScript(KARTENFRAGE, zurueck)
    except Exception as exc:
        ablage["antwort"] = "Fehler: %s" % exc
        log("[PROOF] map could not be asked: %s" % exc)


def _lage_melden(app, fenster, log):
    """Was das Fenster wirklich vorfindet - Bildschirm, Groesse, Kartenfeld.

    Ohne diese Zahlen ist ein Bild mit fehlender Karte nicht zu deuten. Alles
    im Fenster malt Qt selbst: Video (GStreamer liefert die Bilder ueber
    appsink), Chart, Tabelle, Zeitleiste. Die Karte ist das einzige, was NICHT
    Qt malt - Chromium rendert in einem eigenen Prozess. Deshalb kann genau
    sie fehlen, waehrend alles andere steht, und deshalb muss man wissen,
    welche Flaeche sie ueberhaupt bekommen hat.
    """
    try:
        schirm = app.primaryScreen()
        g = schirm.geometry() if schirm else None
        log("[PROOF] platform=%s  screen=%s"
            % (os.environ.get("QT_QPA_PLATFORM", "(default)"),
               ("%dx%d" % (g.width(), g.height())) if g else "keiner"))
        log("[PROOF] window=%dx%d (angefordert %dx%d)"
            % (fenster.width(), fenster.height(),
               FENSTERGROESSE[0], FENSTERGROESSE[1]))
        karte = getattr(fenster, "map_widget", None)
        if karte is None:
            log("[PROOF] map widget: nicht vorhanden")
        else:
            ansicht = getattr(karte, "view", None)
            log("[PROOF] map widget=%dx%d  webview=%s"
                % (karte.width(), karte.height(),
                   ("%dx%d" % (ansicht.width(), ansicht.height()))
                   if ansicht is not None else "keine"))
    except Exception as exc:
        log("[PROOF] Lage konnte nicht ermittelt werden: %s" % exc)


def _sofort_beenden(code, log):
    """Den Prozess beenden, ohne Qt und GStreamer abraeumen zu lassen.

    Der Weg ueber app.exit() ist der saubere - aber im gepackten macOS-Buendel
    ist der Lauf danach mit einem Segmentation fault ausgestiegen (Bauplan vom
    03.09.2026, Rueckgabewert 139), und zwar NACHDEM alle drei Bilder
    geschrieben waren: das Artefakt enthielt sie, und der Schritt danach
    ("Hat das Laufen das Buendel veraendert?") lief grueen durch. Der Absturz
    passiert also beim Abraeumen von GStreamer und QtWebEngine, nicht bei der
    Arbeit.

    Fuer den Nachweis zaehlen die Bilder, nicht das Aufraeumen. Deshalb wird
    hier hart beendet, mit dem Rueckgabewert, den der Nachweis verdient hat.
    Das ist NUR in diesem Modus so - eine normale Sitzung beendet sich
    weiterhin ordentlich ueber app.exec().
    """
    import sys
    log("[PROOF] exiting with %d" % code)
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.flush()
        except Exception:
            pass
    os._exit(code)


def bilder_machen(fenster, app, log):
    """Laden, abspielen, drei Bilder, beenden. Setzt den Rueckgabewert.

    Rueckgabewert 0, wenn alle drei Bilder entstanden sind, sonst 1.
    """
    from PySide6.QtCore import QTimer

    ordner = tempfile.mkdtemp(prefix="kvrouite_nachweis_")
    video, gpx, fehler = _material(ordner)
    if fehler:
        log("[PROOF] test material could not be created: %s" % fehler)
        _sofort_beenden(1, log)
    log("[PROOF] test material in %s" % ordner)

    # Fenstergroesse festsetzen. Ohne Bildschirm meldet Qt einen winzigen
    # virtuellen Bildschirm, und KVRouite.py bemisst das Fenster daran (90 %
    # der Bildschirmbreite). Auf dem Bauserver kamen so 796x428 heraus - bei
    # der Groesse quetscht das Raster alles zusammen, und die Karte bekommt
    # gar keinen Platz mehr. Die Bilder sahen danach aus, als sei die
    # Anwendung kaputt, dabei war nur das Fenster zu klein. Mit dieser Groesse
    # zeigt die Aufnahme dasselbe Bild wie auf einem normalen Rechner.
    fenster.resize(*FENSTERGROESSE)
    _lage_melden(app, fenster, log)
    # Muss VOR dem Laden laufen: die erste Frage kommt sofort.
    zeitgeber = _dialoge_beantworten(app, log)

    gemacht = []
    karte = {"antwort": None}

    def schuss(nummer):
        ziel = os.path.abspath("%s_%d.png" % (DATEINAME, nummer))
        try:
            bild = fenster.grab()
            if bild.save(ziel, "PNG"):
                gemacht.append(ziel)
                log("[PROOF] picture %d: %s  (%dx%d)"
                    % (nummer, ziel, bild.width(), bild.height()))
            else:
                log("[PROOF] picture %d could not be written: %s"
                    % (nummer, ziel))
        except Exception as exc:
            log("[PROOF] picture %d failed: %s" % (nummer, exc))

    def fertig():
        zeitgeber.stop()
        antwort = karte.get("antwort")
        if antwort is None:
            antwort = "keine Antwort der Kartenseite"
            log("[PROOF] the map page did not answer in time.")
            try:
                with open(os.path.abspath(KARTENDATEI), "w",
                          encoding="utf-8") as datei:
                    datei.write(antwort + "\n")
            except Exception:
                pass
        if not (antwort or "").startswith("ok"):
            log("[PROOF] MAP FAILED: %s" % antwort)
            _sofort_beenden(1, log)
        if len(gemacht) == len(ZEITPUNKTE):
            log("[PROOF] %d pictures taken - compare them: if the ball in the "
                "video and the playhead have moved, playback really ran."
                % len(gemacht))
            _sofort_beenden(0, log)
        else:
            log("[PROOF] only %d of %d pictures were taken."
                % (len(gemacht), len(ZEITPUNKTE)))
            _sofort_beenden(1, log)

    def abspielen():
        try:
            fenster.on_play_pause()
            log("[PROOF] playback started")
        except Exception as exc:
            log("[PROOF] playback could not be started: %s" % exc)
        # Die Karte fragen, sobald das erste Bild faellt - bis dahin hatte die
        # Seite Zeit, sich aufzubauen.
        QTimer.singleShot(int(ZEITPUNKTE[0] * 1000),
                          lambda: _karte_fragen(fenster, log, karte))
        for nummer, sekunde in enumerate(ZEITPUNKTE, 1):
            QTimer.singleShot(int(sekunde * 1000),
                              lambda n=nummer: schuss(n))
        QTimer.singleShot(int((ZEITPUNKTE[-1] + 1.0) * 1000), fertig)

    def laden():
        # open_recent() ist genau das, was ein Doppelklick im Menue "zuletzt
        # geoeffnet" ausloest - es verzweigt nach der Endung.
        for datei in (gpx, video):
            try:
                fenster.open_recent(datei)
                log("[PROOF] loaded: %s" % os.path.basename(datei))
            except Exception as exc:
                log("[PROOF] could not load %s: %s"
                    % (os.path.basename(datei), exc))
        QTimer.singleShot(int(LADEZEIT * 1000), abspielen)

    # Erst wenn das Fenster wirklich steht, sonst laedt die Karte in ein
    # Fenster, das es noch nicht gibt.
    QTimer.singleShot(1000, laden)
