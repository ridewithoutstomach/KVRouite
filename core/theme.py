# -*- coding: utf-8 -*-
#
# KVRouite - theme.py
#
# Copyright (C) 2026 by Bernd Eller
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
"""
Farbgebung der Oberflaeche: hell, dunkel, oder wie das System es haelt.

Warum das ueberhaupt hier steht: bis 6.02 hat die App weder einen Stil noch
eine Palette gesetzt. Sie bekam, was Windows lieferte - ein heller Rahmen um
Flaechen, die laengst dunkel sind (Chart #222222, Zeitleiste #333333, Videobild
schwarz). Dieser Bruch war der Grund fuer den altmodischen Eindruck.

Was hier NICHT passiert: die gemalten Flaechen anfassen. Zeitleiste, Chart und
Videobild zeichnen mit festen Farben in paintEvent(); eine Qt-Palette erreicht
sie nicht. Schnittmarken, Blenden und die gelben Bereiche sehen deshalb nach
dem Umschalten aus wie vorher - das ist Absicht und keine Luecke.

Die Farbtafel steht bewusst an EINER Stelle. Wer spaeter die Stylesheets in
den Widgets darauf umstellt, aendert Farben dann hier und nicht an 42 Stellen.
"""

import os
import sys

from PySide6.QtCore import QEvent, QObject, QSettings, QTimer
from PySide6.QtGui import QIcon, QImage, QPalette, QColor, QPixmap
from PySide6.QtWidgets import QApplication, QStyleFactory

SCHLUESSEL = "ui/theme"
MODI = ("light", "dark")
VORGABE = "light"          # niemand bekommt ungefragt ein anderes Aussehen

# Was zuletzt tatsaechlich angewendet wurde. Ohne das wuerde farben() nach
# einem Umschalten weiter den GESPEICHERTEN Modus melden und die Widgets
# bekaemen die Farben des alten Zustands.
_angewendet = None

# Stil und Palette, wie Qt sie beim Start von Windows bekommen hat. Der helle
# Betrieb stellt GENAU DIESE wieder her.
#
# Nicht style().standardPalette(): die liefert im Stil "windows11" die alten
# Systemfarben aus Windows-95-Zeiten. Gemessen auf diesem Rechner weichen 9 von
# 18 Rollen ab - Window #f3f3f3 gegen #d4d0c8, Button #ffffff gegen #d4d0c8,
# die Auswahlfarbe #0067c0 gegen das alte Navy #000080. Wer damit auf "Light"
# schaltet, bekommt nicht den Zustand von vorher, sondern ein 25 Jahre altes
# Windows.
_ursprung_palette = None
_ursprung_stil = None
_ursprung_stylesheet = None


def ursprung_merken(app=None) -> None:
    """Einmal beim Start aufrufen - VOR der ersten Aenderung."""
    global _ursprung_palette, _ursprung_stil, _ursprung_stylesheet
    from PySide6.QtGui import QPalette as _P
    app = app or QApplication.instance()
    if app is None or _ursprung_palette is not None:
        return
    _ursprung_palette = _P(app.palette())
    _ursprung_stil = app.style().objectName()
    _ursprung_stylesheet = app.styleSheet() or ""


def _dunkles_stylesheet() -> str:
    """Was die Palette allein nicht schafft.

    Haekchen: Fusion zeichnet das Kaestchen aus Base und einer aus der
    Fensterfarbe abgedunkelten Kante - auf #2b2b2b ist das ein dunkelgraues
    Quadrat auf dunkelgrau, und angehakt bleibt nur der Haken ohne Rahmen
    (gemessen 12.09.2026, Bernd: "man sieht ueberhaupt nicht, dass man hier
    was setzen kann"). Deshalb ein eigener Rahmen in der gedimmten
    Textfarbe und angehakt die Akzentfarbe als Fuellung. Den Haken selbst
    zeichnet Qt mit einem Stylesheet nicht mehr - die blaue Fuellung ist
    das "an".
    """
    f = DUNKEL
    return (
        "QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid %s; "
        "border-radius: 2px; background: %s; }\n"
        "QCheckBox::indicator:checked { background: %s; border-color: %s; }\n"
        "QCheckBox::indicator:disabled { border-color: %s; background: %s; }\n"
        % (f["text_gedimmt"], f["eingabe"], f["akzent"], f["verweis"],
           f["kante_hell"], f["fenster"]))

# ---------------------------------------------------------------- Farbtafel
# Die Werte sind an die schon vorhandenen Flaechen angelehnt: der Rahmen ist
# etwas heller als der Chart (#222222), damit die Inhalte vorne bleiben.
DUNKEL = {
    "fenster":        "#2b2b2b",   # Rahmen, Menueleiste, Leisten
    "flaeche":        "#323232",   # Knoepfe
    "eingabe":        "#232323",   # Listen, Tabellen, Eingabefelder
    "eingabe_wechsel": "#2a2a2a",  # jede zweite Zeile
    "text":           "#e6e6e6",
    "text_grau":      "#7a7a7a",   # abgeschaltete Knoepfe
    "akzent":         "#2f7fd1",   # Auswahl
    "akzent_text":    "#ffffff",
    "hinweis":        "#3a3a3a",   # Tooltip-Grund
    "verweis":        "#5aa9f0",
    "kopf":           "#3a3a3a",   # Kopfzeile eines Fensters
    "kopf_text":      "#dddddd",
    "kopf_linie":     "#555555",
    "text_gedimmt":   "#9a9a9a",   # zurueckgenommen, aber noch lesbar
    "gitter":         "#3f3f3f",   # Linien zwischen Tabellenzellen
    "kopfzeile":      "#383838",   # Spaltenkoepfe und Zeilennummern
    # Die Abstufungen, mit denen Qt Kanten zeichnet: Splittergriffe, Rahmen,
    # Trennlinien. Ohne sie leitet Qt sie aus Button ab und kommt auf
    # Light=#ffffff, Midlight=#e3e3e3, Mid=Dark=#a0a0a0 - daher die weisse
    # Linie, die neben dem Chart stand.
    "kante_hell":     "#404040",
    "kante_mittelhell": "#3a3a3a",
    "kante_mittel":   "#2f2f2f",
    "kante_dunkel":   "#1e1e1e",
    "kante_schatten": "#141414",
}

# Dieselben Rollen fuer den hellen Betrieb. Die Farben stehen hier und nicht
# in den Widgets, damit eine Aenderung eine Datei kostet und nicht zehn.
HELL = {
    "fenster":        "#f0f0f0",
    "flaeche":        "#fdfdfd",
    "eingabe":        "#ffffff",
    "eingabe_wechsel": "#f6f6f6",
    "text":           "#1a1a1a",
    "text_grau":      "#8a8a8a",
    "akzent":         "#3874f2",   # das Blau, das die GPX-Tabelle schon nutzt
    "akzent_text":    "#ffffff",
    "hinweis":        "#ffffdc",
    "verweis":        "#0b5ed7",
    "kopf":           "#e2e2e2",
    "kopf_text":      "#333333",
    "kopf_linie":     "#c4c4c4",
    "text_gedimmt":   "#808080",   # das bisherige Qt.gray
    "gitter":         "#d0d0d0",
    "kopfzeile":      "#f0f0f0",
    "kante_hell":     "#ffffff",
    "kante_mittelhell": "#e3e3e3",
    "kante_mittel":   "#a0a0a0",
    "kante_dunkel":   "#787878",
    "kante_schatten": "#000000",
}


def farben(modus: str = None) -> dict:
    """Die Farbtafel, die gerade gilt. Fuer Stylesheets in den Widgets."""
    return DUNKEL if ist_dunkel(modus) else HELL


def _einstellungen():
    return QSettings("KVRouite", "KVRouite")


def gespeicherter_modus() -> str:
    """"system", "light" oder "dark" - was zuletzt gewaehlt wurde."""
    wert = _einstellungen().value(SCHLUESSEL, VORGABE)
    wert = str(wert).lower() if wert is not None else VORGABE
    return wert if wert in MODI else VORGABE


def modus_merken(modus: str) -> None:
    if modus in MODI:
        _einstellungen().setValue(SCHLUESSEL, modus)


def ist_dunkel(modus: str = None) -> bool:
    """Wird dunkel gezeichnet?

    Ohne Angabe gilt, was zuletzt angewendet wurde - und erst wenn noch
    nichts angewendet ist, der gespeicherte Modus.

    Ein dritter Modus "der Windows-Einstellung folgen" stand hier kurz und ist
    wieder heraus: er haette nur beim Start nachgesehen und danach nichts mehr
    mitbekommen. Wenn er kommen soll, dann richtig - ueber das Signal
    QStyleHints.colorSchemeChanged, damit die App auch waehrend des Betriebs
    mitzieht.
    """
    if modus is None and _angewendet is not None:
        return _angewendet
    return (modus or gespeicherter_modus()) == "dark"


def _schrift_setzen(app) -> str:
    """Die Oberflaechenschrift des jeweiligen Systems, wenn vorhanden.

    WIRD DERZEIT NICHT AUFGERUFEN. anwenden() laesst die Schrift bewusst in
    Ruhe, damit "Light" genau der Zustand von vor 6.02 bleibt. Die Funktion
    steht bereit, falls die Oberflaechenschrift einmal zur Wahl stehen soll -
    und dann soll sie auf jedem System etwas finden, nicht nur auf Windows.

    Nur die Familie wird gesetzt, nicht die Groesse: mehrere Knoepfe haben
    eine feste Breite, eine groessere Schrift wuerde ihre Beschriftung
    abschneiden.
    """
    from PySide6.QtGui import QFontDatabase
    vorhanden = set(QFontDatabase.families())
    kandidaten = ("Segoe UI Variable Text", "Segoe UI",   # Windows
                  "SF Pro Text", "Helvetica Neue",        # macOS
                  "Inter", "Noto Sans", "DejaVu Sans")    # Linux
    for name in kandidaten:
        if name in vorhanden:
            schrift = app.font()
            if schrift.family() != name:
                schrift.setFamily(name)
                app.setFont(schrift)
            return name
    return app.font().family()


def _dunkle_palette() -> QPalette:
    f = {name: QColor(wert) for name, wert in DUNKEL.items()}
    p = QPalette()
    p.setColor(QPalette.Window, f["fenster"])
    p.setColor(QPalette.WindowText, f["text"])
    p.setColor(QPalette.Base, f["eingabe"])
    p.setColor(QPalette.AlternateBase, f["eingabe_wechsel"])
    p.setColor(QPalette.Text, f["text"])
    p.setColor(QPalette.PlaceholderText, f["text_grau"])
    p.setColor(QPalette.Button, f["flaeche"])
    p.setColor(QPalette.ButtonText, f["text"])
    p.setColor(QPalette.BrightText, QColor("#ff5555"))
    p.setColor(QPalette.ToolTipBase, f["hinweis"])
    p.setColor(QPalette.ToolTipText, f["text"])
    p.setColor(QPalette.Highlight, f["akzent"])
    p.setColor(QPalette.HighlightedText, f["akzent_text"])
    p.setColor(QPalette.Link, f["verweis"])
    p.setColor(QPalette.LinkVisited, f["verweis"])
    # Kanten - siehe Kommentar bei der Farbtafel.
    p.setColor(QPalette.Light, f["kante_hell"])
    p.setColor(QPalette.Midlight, f["kante_mittelhell"])
    p.setColor(QPalette.Mid, f["kante_mittel"])
    p.setColor(QPalette.Dark, f["kante_dunkel"])
    p.setColor(QPalette.Shadow, f["kante_schatten"])
    for rolle in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, rolle, f["text_grau"])
    return p


def _titelleiste_faerben(fenster, dunkel: bool) -> bool:
    """Die Fensterleiste von Windows mitfaerben.

    Qt faerbt nur den Inhalt. Der Rahmen samt Titel und den drei Knoepfen
    gehoert dem Fenstermanager, und der fragt nicht die Qt-Palette, sondern
    ein Fensterattribut: DWMWA_USE_IMMERSIVE_DARK_MODE (20). Ohne das steht
    ein weisser Balken ueber einem dunklen Fenster.

    Nur Windows 10 ab Build 18985 und Windows 11 kennen das Attribut; auf
    aelteren Fassungen und auf Linux/macOS passiert schlicht nichts.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        kennung = int(fenster.winId())
        if not kennung:
            return False
        wert = ctypes.c_int(1 if dunkel else 0)
        ergebnis = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(kennung), 20, ctypes.byref(wert),
            ctypes.sizeof(wert))
        if ergebnis != 0:
            return False

        # Bei einem schon sichtbaren Fenster merkt Windows die Aenderung erst,
        # wenn der Rahmen neu gebaut wird. Ohne das hier blieb der Kopf nach
        # einem Wechsel dark -> light -> dark hell stehen: gesetzt war das
        # Attribut, gezeichnet wurde der alte Rahmen.
        if fenster.isVisible():
            SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
            SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(kennung), None, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
                | SWP_FRAMECHANGED)
        return True
    except Exception:
        return False


def titelleiste_anpassen(fenster) -> bool:
    """Fuer Fenster, die erst nach anwenden() entstehen."""
    return _titelleiste_faerben(fenster, ist_dunkel())


class _Fensterwaechter(QObject):
    """Faerbt die Leiste JEDES Fensters, sobald es gezeigt wird.

    Ohne das haetten nur die Fenster eine dunkle Leiste, die beim Umschalten
    schon offen waren. Dialoge, Meldungen und Fortschrittsfenster entstehen
    aber erst spaeter und sind eigene Fenster mit eigener Leiste - sie kamen
    mit weissem Kopf ueber dunklem Inhalt.

    Ein Beobachter an der Anwendung statt Code in jedem Dialog: es gibt zu
    viele Stellen, an denen Fenster entstehen, und die naechste waere wieder
    vergessen worden.
    """

    def eventFilter(self, objekt, ereignis):
        if ereignis.type() == QEvent.Show:
            try:
                if objekt.isWindow():
                    # Verzoegert, siehe _titelleisten_nachziehen(): Qt setzt
                    # dasselbe Attribut selbst und wuerde uns sonst wieder
                    # ueberschreiben.
                    QTimer.singleShot(
                        0, lambda w=objekt: _titelleiste_faerben(w, ist_dunkel()))
            except Exception:
                pass
        return False


_waechter = None


def _titelleisten_nachziehen(app, dunkel: bool) -> None:
    """Alle Fensterleisten setzen, NACHDEM Qt seine eigene Runde hatte.

    Qt 6.11 setzt DWMWA_USE_IMMERSIVE_DARK_MODE selbst, abgeleitet vom
    Farbschema von Windows. Beim Stilwechsel kommt das nach unserem Aufruf und
    macht ihn zunichte: gemessen blieb der Kopf nach dark -> light -> dark hell,
    obwohl wir das Attribut auf 1 gesetzt hatten. Deshalb noch einmal, wenn die
    Ereignisschlange leer ist.
    """
    for fenster in app.topLevelWidgets():
        try:
            if fenster.isWindow():
                _titelleiste_faerben(fenster, dunkel)
        except Exception:
            pass


def _waechter_anhaengen(app) -> None:
    global _waechter
    if _waechter is None and sys.platform == "win32":
        _waechter = _Fensterwaechter(app)
        app.installEventFilter(_waechter)


# ------------------------------------------------------------------ Symbole
_icon_merker = {}


def _ist_graustufig(bild: QImage) -> bool:
    """Traegt das Symbol Farbe, oder ist es eine reine Strichzeichnung?

    Entscheidet, ob umgekehrt werden darf: eine schwarze Strichzeichnung wird
    im dunklen Betrieb zur weissen. Ein farbiges Symbol - das rote VG-Zeichen,
    das gruene - bleibt, wie es ist; umgekehrt saehe es falsch aus.
    """
    schritt = max(1, bild.width() // 60)
    summe = 0
    gezaehlt = 0
    for y in range(0, bild.height(), schritt):
        for x in range(0, bild.width(), schritt):
            farbe = bild.pixelColor(x, y)
            if farbe.alpha() < 30:
                continue
            summe += farbe.saturation()
            gezaehlt += 1
    if not gezaehlt:
        return False
    return (summe / gezaehlt) < 60


def _einfaerben(bild: QImage, farbe: QColor) -> QImage:
    """Eine Strichzeichnung in EINER Farbe neu aufbauen.

    Die Deckung wird aus der Dunkelheit gerechnet: was schwarz war, wird voll
    deckend, was weiss war, verschwindet. Damit ist es gleich, ob ein Symbol
    auf transparentem oder auf weissem Grund gezeichnet wurde - uebrig bleibt
    nur der Strich.

    Der erste Anlauf hat stattdessen die Helligkeit umgekehrt. Bei Symbolen
    mit Alphakanal ging das gut, bei denen mit weissem Grund wurde daraus ein
    schwarzer Kasten - cut_begin.png und cut_end.png sahen genau so aus.
    """
    quelle = bild.convertToFormat(QImage.Format_ARGB32)
    aus = QImage(quelle.size(), QImage.Format_ARGB32)
    aus.fill(0)
    r, g, b = farbe.red(), farbe.green(), farbe.blue()
    for y in range(quelle.height()):
        for x in range(quelle.width()):
            f = quelle.pixelColor(x, y)
            a = f.alpha()
            if a == 0:
                continue
            dunkelheit = 255 - f.lightness()
            neu = QColor(r, g, b)
            neu.setAlpha(int(a * dunkelheit / 255))
            aus.setPixelColor(x, y, neu)
    return aus


def icon(pfad: str) -> QIcon:
    """Ein Symbol laden - im dunklen Betrieb umgekehrt, wenn es einfarbig ist.

    Der Weg ueber eine Funktion statt zweier Dateisaetze: die Symbole liegen
    nur einmal im Projekt, und ein neues Symbol zieht von selbst mit.
    """
    # Ein relativer Pfad wuerde gegen das ARBEITSVERZEICHNIS aufgeloest. Beim
    # Doppelklick auf ein macOS-Buendel ist das "/", und dann fehlt jedes
    # Symbol. Deshalb ueber config.finde_datei().
    if not os.path.isabs(pfad):
        from config import finde_datei
        pfad = finde_datei(*pfad.replace("\\", "/").split("/"))
    schluessel = (pfad, ist_dunkel())
    fertig = _icon_merker.get(schluessel)
    if fertig is not None:
        return fertig
    bild = QImage(pfad)
    if bild.isNull():
        return QIcon(pfad)
    if ist_dunkel() and _ist_graustufig(bild):
        bild = _einfaerben(bild, QColor(DUNKEL["text"]))
    fertig = QIcon(QPixmap.fromImage(bild))
    _icon_merker[schluessel] = fertig
    return fertig


def standardsymbol(widget, kennung) -> QIcon:
    """Ein Symbol des Stils (QStyle.SP_...) - im dunklen Betrieb aufgehellt.

    Play, Pause, Vor und Zurueck kommen aus dem Stil. Fusion zeichnet sie
    schwarz, unabhaengig von der Palette; auf dunklem Grund waren sie kaum zu
    sehen.
    """
    symbol = widget.style().standardIcon(kennung)
    if not ist_dunkel():
        return symbol
    groesse = 32
    bild = symbol.pixmap(groesse, groesse).toImage()
    if bild.isNull():
        return symbol
    return QIcon(QPixmap.fromImage(_einfaerben(bild, QColor(DUNKEL["text"]))))


def _heller_stil() -> str:
    """Der native Stil, wenn es ihn gibt - sonst Fusion."""
    vorhanden = set(QStyleFactory.keys())
    for name in ("windows11", "windowsvista", "Windows"):
        if name in vorhanden:
            return name
    return "Fusion"


def anwenden(app: QApplication = None, modus: str = None) -> bool:
    """Stil und Palette setzen. Rueckgabe: True, wenn dunkel gezeichnet wird.

    Ohne `modus` gilt der gespeicherte. Wird zur Laufzeit umgeschaltet, muessen
    die schon gebauten Fenster neu durch den Stil - deshalb unpolish/polish.
    """
    global _angewendet
    app = app or QApplication.instance()
    if app is None:
        return False
    ursprung_merken(app)     # bevor irgendetwas gesetzt wird
    dunkel = ist_dunkel(modus)
    _angewendet = dunkel

    if dunkel:
        # Fusion, weil der native Windows-Stil Knoepfe und Menues unabhaengig
        # von der Palette hell zeichnet - dunkel bliebe dort wirkungslos.
        app.setStyle("Fusion")
        app.setPalette(_dunkle_palette())
        app.setStyleSheet((_ursprung_stylesheet or "") + "\n" + _dunkles_stylesheet())
    else:
        # Genau der Zustand von vor der ersten Umschaltung.
        ursprung_merken(app)
        if _ursprung_stil:
            app.setStyle(_ursprung_stil)
        else:
            app.setStyle(_heller_stil())
        if _ursprung_palette is not None:
            app.setPalette(_ursprung_palette)
        app.setStyleSheet(_ursprung_stylesheet or "")

    # Die Schrift wird hier bewusst NICHT angefasst: "Light" soll genau der
    # Zustand von vor 6.02 sein. _schrift_setzen() steht bereit, falls die
    # Oberflaechenschrift spaeter zur Wahl stehen soll.

    _waechter_anhaengen(app)

    stil = app.style()
    for fenster in app.topLevelWidgets():
        if fenster.isWindow():
            _titelleiste_faerben(fenster, dunkel)
        for widget in [fenster] + fenster.findChildren(object):
            # Wer eigene Farben setzt, baut sie hier neu auf - sonst bliebe
            # ein im Konstruktor gesetztes Stylesheet auf den alten Farben.
            neu_aufbauen = getattr(widget, "theme_aktualisieren", None)
            if callable(neu_aufbauen):
                try:
                    neu_aufbauen()
                except Exception:
                    pass
            if hasattr(widget, "style") and hasattr(widget, "update"):
                try:
                    stil.unpolish(widget)
                    stil.polish(widget)
                    widget.update()
                except Exception:
                    pass

    QTimer.singleShot(0, lambda: _titelleisten_nachziehen(app, dunkel))
    return dunkel
