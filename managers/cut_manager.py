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

# managers/cut_manager.py
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QObject, Signal

class VideoCutManager(QObject):
    cutsChanged = Signal(float)

    def __init__(self, video_editor, timeline, parent=None):
        super().__init__(parent)
        self.video_editor = video_editor
        self.timeline = timeline
        self.markB_time_s = -1.0
        self.markE_time_s = -1.0
        self._cut_intervals = []
        # Schnitte, die OHNE Blende ausgefuehrt werden sollen (harte Kante).
        # Gespeichert als gerundete (start, end)-Schluessel, damit
        # _cut_intervals selbst unveraendert bleibt.
        self._hard_cuts = set()

        # Blendenlaengen je Schnitt, in Sekunden. Was hier NICHT steht, folgt
        # der Vorgabe aus dem Encoder Setup (encoder/xfade). Gleiches Muster
        # wie _hard_cuts: ein Dict neben der Schnittliste, mit dem gerundeten
        # (start, end)-Schluessel.
        #
        # Eine harte Kante bleibt in _hard_cuts und wird hier NICHT als 0
        # abgelegt. Sonst gaebe es zwei Schreibweisen fuer dasselbe, und die
        # koennten auseinanderlaufen. Beim Auswerten kommen beide zusammen -
        # siehe blende_fuer_bereich().
        self._blenden = {}

        # Merge-Fades an den Naehten der Videoliste (ab 6.14). Schluessel ist
        # die Nummer der Naht: 0 liegt zwischen Video 1 und 2. Der Wert ist
        # die Laenge in Sekunden oder None fuer die Vorgabe aus dem Encoder
        # Setup (encoder/xfade) - dasselbe Muster wie _blenden. Was hier
        # nicht steht, ist eine harte Naht.
        #
        # Bewusst KEIN Schnitt der Breite 0 in _cut_intervals: ein
        # Merge-Fade nimmt nichts weg, hat keine GPX-Aufzeichnung, laesst
        # sich nicht verschieben und braucht keine Ruecknahme. Die rund 18
        # Stellen, die _cut_intervals entpacken, gehen ihn nichts an.
        #
        # Die Nummer statt der Rohzeit als Schluessel, weil die Naht ihre
        # Rohzeit aendert, sobald sich die Dauer eines Videos davor um ein
        # Bild anders misst - die Nummer bleibt. Faellt ein Video aus der
        # Liste, ruecken die Naehte dahinter nach; siehe prune_merge_fades().
        self._merge_fades = {}
        self.video_durations = []

        # ---- Ruecknahme von Schnitten (ab 6.02, Etappe 1: nur aufzeichnen) --
        #
        # Was ein Schnitt aus der GPX-Spur entfernt hat, wird hier abgelegt -
        # nach demselben Muster wie _hard_cuts: ein Dict neben der
        # Schnittliste, mit dem gerundeten (start, end)-Schluessel. So bleibt
        # _cut_intervals eine reine Liste von Zeitpaaren; sie wird an rund
        # 18 Stellen im Programm entpackt und darf sich nicht aendern.
        #
        # Der Schluessel ist stabil, weil Schnitte in ROHZEIT gespeichert
        # werden: Faellt ein frueherer Schnitt weg, verschiebt sich nur, wo
        # ein spaeterer im fertigen Video landet - nicht sein Schluessel.
        #
        # Je Schnitt wird abgelegt:
        #   "entfernt"      die herausgeschnittenen Punkte mit Originalzeiten
        #   "verworfen"     Punkte, die die Ordnungspruefung zusaetzlich
        #                   weggelassen hat (sonst waeren sie unwiederbringlich)
        #   "interpoliert"  der an der Naht neu erzeugte Punkt, falls es einen
        #                   gab - beim Zurueckholen muss er wieder weg
        #   "dauer_s"       um wie viel alles danach nach vorn gerueckt ist
        #   "achsen_versatz_s"   nur beim Startschnitt: um wie viel die GANZE
        #                   Zeitachse verschoben wurde. Er setzt die Spur auf
        #                   ihren alten Anfangszeitstempel zurueck, damit
        #                   verschiebt sich alles - nicht nur das dahinter.
        #   "video_shift_vorher" ebenfalls nur beim Startschnitt: der
        #                   Video/GPX-Versatz, den er auf 0 gesetzt hat
        #
        # Ein Abdruck JE SCHNITT stand hier urspruenglich auch - den gibt es
        # nicht und kann es nicht geben: er waere schon nach dem naechsten
        # Schnitt ueberholt. Ob eine Aufzeichnung noch gilt, entscheidet der
        # EINE Abdruck der Spur unten, und der geht seit 6.03 mit in die
        # Projektdatei (get_gpx_abdruck).
        self._cut_points = {}

        # Fingerabdruck der GPX-Spur nach der letzten EIGENEN Aktion. Weicht
        # er ab, hat jemand anders die Spur bearbeitet - dann ist Zuruecknehmen
        # nicht mehr sicher. Ein Zaehler waere hier falsch: er muesste in jeder
        # Bearbeitungsfunktion gepflegt werden, und eine uebersehene Stelle
        # ergaebe eine falsche Zusage. Der Fingerabdruck kann nichts uebersehen.
        self._gpx_fingerabdruck = None
        
        
    def set_video_durations(self, durations_list):
        self.video_durations = durations_list

    def on_markB_clicked(self):
        current_global_s = self._get_current_global_time()
        if self.markE_time_s >= 0 and current_global_s >= self.markE_time_s:
            QMessageBox.warning(
                None,
                "Invalid MarkB",
                f"You cannot set MarkB ({current_global_s:.2f}s) behind MarkE ({self.markE_time_s:.2f}s)!"
            )
            return  # Abbrechen, gar nicht setzen
            
        self.markB_time_s = current_global_s
        self.timeline.set_markB_time(current_global_s)

    def on_markE_clicked(self):
        current_global_s = self._get_current_global_time()
        if self.markB_time_s >= 0 and current_global_s <= self.markB_time_s:
            QMessageBox.warning(
                None,
                "Invalid MarkE",
                f"You cannot set MarkE ({current_global_s:.2f}s) in front of MarkB ({self.markB_time_s:.2f}s)!"
            )
            return
        video_total = sum(self.video_durations)
        if video_total - current_global_s < 1 : # das letzte Bild laesst sich nicht anwaehlen, deshalb klemmen wir von Hand
            current_global_s = video_total
        self.markE_time_s = current_global_s
        self.timeline.set_markE_time(current_global_s)

    def on_cut_clicked(self):
        if self.markB_time_s < 0 or self.markE_time_s < 0:
            return
        start_s = min(self.markB_time_s, self.markE_time_s)
        end_s   = max(self.markB_time_s, self.markE_time_s)
        video_total = sum(self.video_durations)
        start_s = max(0.0, start_s)
        end_s   = min(end_s, video_total)
        if (end_s - start_s) < 0.01:
            print("[DEBUG] Cut-Bereich zu klein, Abbruch. Start:", start_s, "Ende:", end_s)
            return
        # Ein neuer End-Schnitt ERSETZT einen vorhandenen End-Schnitt,
        # er kommt nicht zusaetzlich dazu. Sonst waere der ueberlappende
        # Bereich doppelt gezaehlt und ein spaeteres Ende nicht einstellbar.
        if self.is_end_cut(end_s):
            self.remove_end_cut_intervals()

        print(f"[DEBUG] CUT hinzugefügt: ({start_s:.3f}, {end_s:.3f})")
        self.prune_hard_cuts()
        self._cut_intervals.append((start_s, end_s))
        self.timeline.add_cut_interval(start_s, end_s)
        self.markB_time_s = -1
        self.markE_time_s = -1
        self.timeline.set_markB_time(-1)
        self.timeline.set_markE_time(-1)
        self._emit_cuts_changed()
        self.video_editor.set_cut_intervals(self._cut_intervals)
    
    def on_markClear_clicked(self):
        if self.markB_time_s >= 0 or self.markE_time_s >= 0:
            self.markB_time_s = -1.0
            self.markE_time_s = -1.0
            self.timeline.set_markB_time(-1)
            self.timeline.set_markE_time(-1)

    def get_merged_cut_intervals(self):
        """
        Gibt die Schnitte zurueck, wobei ueberlappende bzw. aneinander
        stossende Bereiche zu einem zusammengefasst werden.

        Ohne dieses Zusammenfassen wuerde ein doppelt geschnittener Bereich
        auch doppelt gezaehlt - die Restlaenge waere dann zu klein oder sogar
        negativ. Dieselbe Logik nutzt _compute_keep_intervals() im MainWindow.
        """
        if not self._cut_intervals:
            return []

        sorted_cuts = sorted(self._cut_intervals, key=lambda x: x[0])
        merged = []
        cur_start, cur_end = sorted_cuts[0]
        for (st, en) in sorted_cuts[1:]:
            if st <= cur_end:
                if en > cur_end:
                    cur_end = en
            else:
                merged.append((cur_start, cur_end))
                cur_start, cur_end = st, en
        merged.append((cur_start, cur_end))
        return merged

    def get_total_cuts(self) -> float:
        total_cut = 0.0
        for (start_s, end_s) in self.get_merged_cut_intervals():
            total_cut += (end_s - start_s)
        print(f"[DEBUG] get_total_cuts => {total_cut:.3f}")
        return total_cut

    def get_cut_intervals(self):
        return self._cut_intervals

    # ------------------------------------------------------------------
    # Harte Schnitte (kein Crossfade)
    # ------------------------------------------------------------------
    @staticmethod
    def _cut_key(start_s, end_s):
        return (round(float(start_s), 3), round(float(end_s), 3))

    # ------------------------------------------------------------------
    # Ruecknahme von Schnitten: Aufzeichnung und Fingerabdruck
    # ------------------------------------------------------------------
    # Zwei getrennte Abdruecke, weil nicht jede Aenderung gleich schwer wiegt:
    #
    #   ZEITEN  entscheiden ueber die Struktur. Die Ruecknahme arbeitet
    #           ausschliesslich mit Zeitvergleichen - stimmen die nicht mehr,
    #           landen die Punkte an der falschen Stelle. Harte Sperre.
    #
    #   WERTE   (Lage, Hoehe) aendern nichts an der Struktur. Die Punkte
    #           kommen richtig zurueck, tragen aber den Stand von damals -
    #           nach einer Hoehenaenderung oder Glaettung entsteht so eine
    #           Stufe im Profil. Das sieht man im Chart, deshalb genuegt eine
    #           Warnung statt einer Sperre.
    #
    # Gemessen: _apply_smoothing() rechnet nur ueber ele und die Distanzen,
    # es fasst time nicht an. Zeiten schreiben chT, Close Gaps, Resample und
    # einige weitere - genau die Faelle, die gesperrt gehoeren.
    @staticmethod
    def zeit_fingerabdruck(gpx_data) -> str:
        """Abdruck ueber die Zeitfolge (und damit die Anzahl der Punkte)."""
        import hashlib
        h = hashlib.blake2b(digest_size=16)
        for pt in (gpx_data or []):
            t = pt.get("time")
            h.update((t.isoformat() if hasattr(t, "isoformat") else str(t)
                      ).encode("utf-8"))
            h.update(b"|")
        return h.hexdigest()

    @staticmethod
    def wert_fingerabdruck(gpx_data) -> str:
        """Abdruck ueber Lage und Hoehe.

        delta_m, speed_kmh und gradient bleiben aussen vor - die rechnet
        recalc_gpx_data() aus diesen Werten, sie wuerden nichts zusaetzlich
        erkennen, aber jeden Abdruck teurer machen.
        """
        import hashlib
        h = hashlib.blake2b(digest_size=16)
        for pt in (gpx_data or []):
            h.update(repr((
                round(float(pt.get("lat", 0.0)), 9),
                round(float(pt.get("lon", 0.0)), 9),
                round(float(pt.get("ele", 0.0)), 4),
            )).encode("utf-8"))
        return h.hexdigest()

    def fingerabdruck_merken(self, gpx_data):
        """Nach einer eigenen Aktion den Zustand der Spur festhalten."""
        self._gpx_fingerabdruck = (self.zeit_fingerabdruck(gpx_data),
                                   self.wert_fingerabdruck(gpx_data))
        return self._gpx_fingerabdruck

    def zeiten_unveraendert(self, gpx_data) -> bool:
        if not self._gpx_fingerabdruck:
            return False
        return self.zeit_fingerabdruck(gpx_data) == self._gpx_fingerabdruck[0]

    def werte_unveraendert(self, gpx_data) -> bool:
        if not self._gpx_fingerabdruck:
            return False
        return self.wert_fingerabdruck(gpx_data) == self._gpx_fingerabdruck[1]

    def spur_unveraendert(self, gpx_data) -> bool:
        """True, wenn seit unserer letzten Aktion nichts veraendert wurde."""
        return (self.zeiten_unveraendert(gpx_data)
                and self.werte_unveraendert(gpx_data))

    def aufzeichnung_merken(self, start_s, end_s, entfernt, verworfen,
                            interpoliert, dauer_s, beginn_dt=None,
                            achsen_versatz_s=0.0, video_shift_vorher=None):
        """Was ein Schnitt aus der GPX-Spur genommen hat, beim Schnitt ablegen.

        beginn_dt ist der Schnittanfang in GPX-Zeit und muss mitgegeben
        werden. Er laesst sich NICHT aus dem ersten entfernten Punkt
        ableiten: faellt der Schnittanfang genau auf einen vorhandenen
        Punkt - etwa auf die Naht eines angrenzenden Schnitts -, bleibt
        dieser Punkt stehen und der erste entfernte liegt spaeter. Beim
        Zuruecknehmen wuerde dann zu wenig zurueckgeschoben.
        """
        self._cut_points[self._cut_key(start_s, end_s)] = {
            "entfernt": entfernt or [],
            "verworfen": verworfen or [],
            "interpoliert": interpoliert,
            "dauer_s": float(dauer_s or 0.0),
            "beginn_dt": beginn_dt,
            "achsen_versatz_s": float(achsen_versatz_s or 0.0),
            "video_shift_vorher": video_shift_vorher,
        }

    def aufzeichnung(self, start_s, end_s):
        """Aufzeichnung eines Schnitts, oder None."""
        return self._cut_points.get(self._cut_key(start_s, end_s))

    def hat_aufzeichnung(self, start_s, end_s) -> bool:
        return self._cut_key(start_s, end_s) in self._cut_points

    def prune_cut_points(self):
        """Aufzeichnungen wegwerfen, zu denen es keinen Schnitt mehr gibt.

        Dieselbe Ueberlegung wie bei prune_hard_cuts(): sonst erbte ein
        spaeter an derselben Stelle gesetzter Schnitt die alte Aufzeichnung.
        """
        alive = {self._cut_key(a, b) for (a, b) in self._cut_intervals}
        for key in [k for k in self._cut_points if k not in alive]:
            del self._cut_points[key]

    def aufzeichnungen_nachfuehren(self, ab_dt, delta_s, alle=False):
        """Aufzeichnungen hinter ab_dt um delta_s in der Zeit verschieben.

        Eine Aufzeichnung steht in dem Zeitrahmen, den die Spur HATTE, als der
        Schnitt gesetzt wurde. Verschiebt sich die Spur danach - weil ein
        davorliegender Schnitt zurueckgenommen oder ein neuer davor gesetzt
        wird -, zeigt sie ins Leere. Betroffen ist alles hinter der
        veraenderten Stelle, und zwar der Anfang und die Punktzeiten
        gleichermassen.

        Ohne dieses Nachfuehren kommt die Spur bei mehreren Schnitten STILL
        falsch zurueck. Gemessen an einer Spur aus 60 Punkten mit zwei
        Schnitten: wird der vordere zuerst zurueckgenommen, weichen danach
        11 von 60 Punkten ab; mit dem Nachfuehren sind es null. Nachzustellen
        mit check_cut_undo.py.

        alle=True verschiebt jede Aufzeichnung, unabhaengig von ab_dt. Das
        braucht der Startschnitt: er setzt die ganze Zeitachse zurueck, da
        wandert auch, was VOR ihm aufgezeichnet wurde. Ein Zeitpunkt "ganz
        frueh" als ab_dt waere dafuer die schlechtere Loesung - GPX-Zeiten
        koennen mit oder ohne Zeitzone vorliegen, und der Vergleich zweier
        solcher Werte wirft.

        Rueckgabe: Anzahl der nachgefuehrten Aufzeichnungen.
        """
        from datetime import timedelta

        if not delta_s:
            return 0
        if not alle and ab_dt is None:
            return 0
        d = timedelta(seconds=float(delta_s))
        anzahl = 0
        for aufz in self._cut_points.values():
            beginn = aufz.get("beginn_dt")
            if not alle:
                if beginn is None or beginn < ab_dt:
                    continue
                if aufz.get("achsen_versatz_s"):
                    # Aufzeichnung eines Startschnitts. Sie steht im
                    # Zeitrahmen VOR seiner Neubasierung; ein Schnitt dahinter
                    # beruehrt sie nicht. Ihr beginn_dt sieht nur zufaellig
                    # aus wie eine Zeit im jetzigen Rahmen - mitgeschoben
                    # zeigte es anschliessend nicht mehr auf die Naht.
                    continue
            aufz["beginn_dt"] = beginn + d
            for feld in ("entfernt", "verworfen"):
                for pt in aufz.get(feld) or []:
                    if pt.get("time") is not None:
                        pt["time"] = pt["time"] + d
            naht = aufz.get("interpoliert")
            if naht and naht.get("time") is not None:
                naht["time"] = naht["time"] + d
            anzahl += 1
        return anzahl

    # ------------------------------------------------------------------
    # Aufzeichnungen fuer die Projektdatei
    # ------------------------------------------------------------------
    # Ohne diese beiden Funktionen war das Zuruecknehmen nach jedem
    # "Open Project" tot: die Aufzeichnungen standen nur im Speicher, ein
    # geladenes Projekt beginnt mit einem leeren _cut_points, und die erste
    # Sperre in ruecknahme_moeglich() greift dann fuer jeden Schnitt.
    #
    # Als LISTE und nicht als Dict, weil der Schluessel ein Zahlenpaar ist -
    # JSON kennt nur Text als Schluessel. Start und Ende stehen deshalb im
    # Datensatz selbst; beim Laden entsteht der Schluessel daraus neu.
    #
    # Die Zeiten gehen als Text durch die Datei (json.dump(default=str)) und
    # kommen mit datetime.fromisoformat() zurueck - derselbe Weg, den gpx_data
    # schon geht. Gemessen: "2025-01-01 12:00:00.123456" kommt
    # mikrosekundengenau zurueck.

    def get_gpx_abdruck(self):
        """Fuer die Projektdatei: der Abdruck der letzten EIGENEN Aktion."""
        if not self._gpx_fingerabdruck:
            return None
        return [self._gpx_fingerabdruck[0], self._gpx_fingerabdruck[1]]

    def set_gpx_abdruck(self, wert) -> bool:
        """Abdruck aus der Projektdatei uebernehmen - nicht neu rechnen.

        Das ist der springende Punkt beim Laden. Wuerde der Abdruck aus der
        geladenen Spur neu gerechnet, passte er IMMER, und die Aufzeichnungen
        waeren ungeprueft freigegeben - auch dann, wenn zwischen dem letzten
        Schnitt und dem Speichern noch chT, Close Gaps oder Resample gelaufen
        sind. Aus der Datei kommt dagegen der Zustand von der letzten eigenen
        Aktion. Stimmt die geladene Spur damit nicht ueberein, greifen die
        vorhandenen Sperren in ruecknahme_moeglich() - genau wie in der
        Sitzung, in der geschnitten wurde.

        Eine Nahtprobe an der Spur selbst waere die naheliegende Alternative
        gewesen und ist verworfen: gemessen faengt sie eine um volle Sekunden
        verschobene Spur nicht, weil dort einfach ein anderer Punkt auf der
        Naht sitzt. Siehe check_cut_undo.py.
        """
        try:
            zeiten, werte = wert
        except (TypeError, ValueError):
            self._gpx_fingerabdruck = None
            return False
        self._gpx_fingerabdruck = (str(zeiten), str(werte))
        return True

    #: delta_m, speed_kmh und gradient rechnet recalc_gpx_data() beim
    #: Zuruecknehmen ohnehin aus Lage, Hoehe und Zeit neu - sie schreibt sie
    #: fuer JEDEN Punkt unbedingt. In der Projektdatei sind sie deshalb
    #: verlorene Bytes. Gemessen an maptest2.KVRouiteproj: die
    #: Aufzeichnungen schrumpfen von 3384 kB auf 1922 kB, 43 Prozent.
    _ABGELEITET = ("delta_m", "speed_kmh", "gradient")

    @classmethod
    def _punkt_schlank(cls, pt):
        if not pt:
            return pt
        return {k: v for k, v in pt.items() if k not in cls._ABGELEITET}

    def get_cut_points(self) -> list:
        """Fuer die Projektdatei: Liste von Datensaetzen."""
        self.prune_cut_points()
        raus = []
        for (start_s, end_s), aufz in sorted(self._cut_points.items()):
            eintrag = dict(aufz)
            eintrag["start"] = start_s
            eintrag["end"] = end_s
            for feld in ("entfernt", "verworfen"):
                eintrag[feld] = [self._punkt_schlank(p)
                                 for p in (aufz.get(feld) or [])]
            if aufz.get("interpoliert"):
                eintrag["interpoliert"] = self._punkt_schlank(
                    aufz["interpoliert"])
            raus.append(eintrag)
        return raus

    @staticmethod
    def _zeit_lesen(wert):
        """Zeit aus der Projektdatei: Text zu datetime, sonst unveraendert."""
        from datetime import datetime
        if isinstance(wert, str):
            try:
                return datetime.fromisoformat(wert)
            except ValueError:
                return None
        return wert

    def set_cut_points(self, eintraege) -> int:
        """Aufzeichnungen aus der Projektdatei uebernehmen.

        Aeltere Projektdateien kennen den Schluessel nicht; dann bleibt es beim
        leeren Stand und die Schnitte sind gesperrt wie bisher - die vorhandene
        Meldung dazu trifft dann auch wirklich zu.

        Datensaetze ohne Anfang oder ohne entfernte Punkte werden gar nicht
        erst uebernommen. Sie wuerden im Menue eine Moeglichkeit anbieten, die
        anschliessend nichts zurueckholen kann.

        Rueckgabe: Anzahl der uebernommenen Aufzeichnungen.
        """
        self._cut_points = {}
        for eintrag in (eintraege or []):
            try:
                start_s = float(eintrag["start"])
                end_s = float(eintrag["end"])
            except (TypeError, KeyError, ValueError, IndexError):
                continue

            aufz = {
                "entfernt": [dict(p) for p in (eintrag.get("entfernt") or [])],
                "verworfen": [dict(p) for p in (eintrag.get("verworfen") or [])],
                "interpoliert": (dict(eintrag["interpoliert"])
                                 if eintrag.get("interpoliert") else None),
                "dauer_s": float(eintrag.get("dauer_s") or 0.0),
                "beginn_dt": self._zeit_lesen(eintrag.get("beginn_dt")),
                "achsen_versatz_s": float(
                    eintrag.get("achsen_versatz_s") or 0.0),
                "video_shift_vorher": eintrag.get("video_shift_vorher"),
            }
            for feld in ("entfernt", "verworfen"):
                for pt in aufz[feld]:
                    pt["time"] = self._zeit_lesen(pt.get("time"))
            if aufz["interpoliert"] is not None:
                aufz["interpoliert"]["time"] = self._zeit_lesen(
                    aufz["interpoliert"].get("time"))

            if aufz["beginn_dt"] is None or not aufz["entfernt"]:
                print("[CUT-REC] Aufzeichnung %.3f-%.3f unvollstaendig, "
                      "wird nicht uebernommen" % (start_s, end_s))
                continue
            self._cut_points[self._cut_key(start_s, end_s)] = aufz

        self.prune_cut_points()
        return len(self._cut_points)

    def spur_ohne_schnitt(self, start_s, end_s, gpx_data):
        """Die GPX-Spur so, wie sie ohne diesen Schnitt aussaehe.

        Kehrt genau das um, was on_cut_clicked_video() im Middle-Cut-Zweig
        getan hat, und in derselben Reihenfolge rueckwaerts:

          1. der an der Naht erzeugte Punkt faellt weg - es gab ihn vorher nicht
          2. die entfernten Punkte kommen mit ihren Originalzeiten zurueck
          3. alles dahinter rueckt um die Schnittdauer wieder nach hinten
          4. die von der Ordnungspruefung verworfenen Punkte kommen dazu

        Aendert nichts an der uebergebenen Liste; gibt eine neue zurueck.
        Rueckgabe None, wenn es keine Aufzeichnung gibt.
        """
        import copy
        from datetime import timedelta

        aufz = self.aufzeichnung(start_s, end_s)
        if aufz is None:
            return None

        entfernt = aufz.get("entfernt") or []
        verworfen = aufz.get("verworfen") or []
        naht = aufz.get("interpoliert")
        dauer = float(aufz.get("dauer_s") or 0.0)
        if not entfernt:
            return None

        # Der aufgezeichnete Schnittanfang. Der Rueckfall auf den Nahtpunkt
        # bzw. den ersten entfernten Punkt gilt nur fuer Aufzeichnungen ohne
        # dieses Feld - er trifft nicht jeden Fall, siehe aufzeichnung_merken().
        beginn = aufz.get("beginn_dt")
        if beginn is None:
            beginn = naht.get("time") if naht else entfernt[0].get("time")
        if beginn is None:
            return None

        # Beim Startschnitt ist die ganze Zeitachse verschoben worden.
        # Sie muss zuerst zurueck; danach passt beginn_dt wieder, und der
        # Rest der Rechnung ist derselbe wie beim Mittelschnitt.
        versatz = float(aufz.get("achsen_versatz_s") or 0.0)
        if versatz:
            quelle = []
            for pt in (gpx_data or []):
                p = copy.deepcopy(pt)
                if p.get("time") is not None:
                    p["time"] = p["time"] + timedelta(seconds=versatz)
                quelle.append(p)
        else:
            quelle = gpx_data or []

        neu = []
        for pt in quelle:
            t = pt.get("time")
            if t is None:
                neu.append(copy.deepcopy(pt))
                continue
            if t < beginn:
                # vor dem Schnitt - unveraendert
                neu.append(copy.deepcopy(pt))
            elif t == beginn:
                # Genau auf dem Schnittanfang. Zwei Faelle:
                #   mit Naht  - das ist der erzeugte Punkt, er faellt weg
                #   ohne Naht - ein vorhandener Punkt lag exakt dort und wurde
                #               beim Schneiden behalten; er blieb ungeschoben
                #               und bleibt es auch jetzt
                if naht is not None:
                    continue
                neu.append(copy.deepcopy(pt))
            else:
                # dahinter - um die Schnittdauer zurueckschieben
                p = copy.deepcopy(pt)
                p["time"] = t + timedelta(seconds=dauer)
                neu.append(p)

        # Das Herausgeschnittene wieder hinein, dazu die verworfenen Punkte.
        # Deren Zeit war schon nach vorn geschoben, als sie verworfen wurden -
        # sie brauchen dieselbe Rueckrechnung wie der Rest dahinter.
        zurueck = [copy.deepcopy(p) for p in entfernt]
        for p in verworfen:
            q = copy.deepcopy(p)
            t = q.get("time")
            if t is not None:
                q["time"] = t + timedelta(seconds=dauer)
            zurueck.append(q)
        neu.extend(zurueck)

        neu.sort(key=lambda p: (p.get("time") is None, p.get("time")))
        return neu

    def ruecknahme_moeglich(self, start_s, end_s, gpx_data):
        """Darf dieser Schnitt zurueckgenommen werden?

        Rueckgabe (moeglich, grund, warnung):
          moeglich  False heisst gesperrt, grund erklaert es
          warnung   leer, oder ein Hinweis, den der Nutzer vorher
                    bestaetigen soll - das Zuruecknehmen bleibt erlaubt

        Bei den Sperren gilt: im Zweifel gesperrt. Eine falsche Zusage waere
        schlimmer als eine fehlende Moeglichkeit, weil der Fehler stumm
        bliebe - die Spur kaeme leicht falsch zurueck und faellt erst auf,
        wenn Video und Spur auseinanderlaufen.
        """
        if not self.hat_aufzeichnung(start_s, end_s):
            return False, ("There is no record of what this cut removed from "
                           "the GPX track. It comes from a project that was "
                           "saved before this function existed."), ""
        if self.wird_ueberdeckt(start_s, end_s):
            return False, ("This cut lies inside a later, larger cut. The "
                           "points would come back into a range the video does "
                           "not show anyway."), ""
        if not gpx_data:
            return True, "", ""

        # Zeiten: Struktur. Ohne sie stimmt gar nichts mehr.
        if not self.zeiten_unveraendert(gpx_data):
            return False, ("The times of the GPX track have been changed since "
                           "this cut (for example by chT, Close Gaps or "
                           "Resample). Undoing it would insert the points at "
                           "the wrong place."), ""

        # Werte: kommen richtig zurueck, aber mit dem Stand von damals.
        if not self.werte_unveraendert(gpx_data):
            return True, "", ("Elevations or positions have been changed since "
                              "this cut - for example by smoothing or an "
                              "elevation correction.\n\n"
                              "The returning points still carry the state from "
                              "back then. This can create a step in the "
                              "elevation profile at that place.\n\n"
                              "Please check that range in the chart afterwards "
                              "and apply the change again if needed.")
        return True, "", ""

    def wird_ueberdeckt(self, start_s, end_s, eps: float = 0.001) -> bool:
        """Deckt ein anderer Schnitt diesen vollstaendig ab?

        Solange das Setzen ueberlappender Schnitte moeglich ist, kann das
        vorkommen - im Video ist der innere Schnitt dann bedeutungslos, seine
        Punkte wuerden beim Zuruecknehmen in einen Bereich zurueckkehren, der
        gar nicht gezeigt wird.
        """
        for (a, b) in self._cut_intervals:
            if (a, b) == (start_s, end_s):
                continue
            if a <= start_s + eps and b >= end_s - eps:
                return True
        return False

    def schnitt_entfernen(self, start_s, end_s):
        """Den Schnitt selbst aus der Video-Seite nehmen.

        Die GPX-Spur bleibt unberuehrt - dafuer ist spur_ohne_schnitt() da.
        Rueckgabe True, wenn ein Schnitt entfernt wurde.
        """
        key = self._cut_key(start_s, end_s)
        treffer = [iv for iv in self._cut_intervals
                   if self._cut_key(iv[0], iv[1]) == key]
        if not treffer:
            return False
        for iv in treffer:
            self._cut_intervals.remove(iv)
        self._cut_points.pop(key, None)

        self.prune_hard_cuts()
        self.timeline.clear_all_cuts()
        for (a, b) in self._cut_intervals:
            self.timeline.add_cut_interval(a, b)
        self._sync_timeline_hard_cuts()
        self._emit_cuts_changed()
        self.video_editor.set_cut_intervals(self._cut_intervals)
        return True

    # ------------------------------------------------------------------
    # Blendenlaenge je Schnitt
    # ------------------------------------------------------------------
    def get_blende(self, start_s, end_s):
        """Eingestellte Laenge dieses Schnitts, oder None fuer die Vorgabe."""
        return self._blenden.get(self._cut_key(start_s, end_s))

    def set_blende(self, start_s, end_s, sekunden):
        """Laenge setzen. None laesst den Schnitt wieder der Vorgabe folgen."""
        key = self._cut_key(start_s, end_s)
        if sekunden is None:
            self._blenden.pop(key, None)
        else:
            self._blenden[key] = float(sekunden)

    def blende_fuer_bereich(self, start_s, end_s, vorgabe, eps: float = 0.001):
        """Blendenlaenge fuer einen - moeglicherweise zusammengefassten - Bereich.

        Grenzen mehrere Schnitte aneinander, sind sie im Video EIN Uebergang.
        Der kann nur eine Blende haben, deshalb gewinnt die kuerzeste der
        beteiligten. Eine harte Kante zaehlt dabei als 0 und setzt sich damit
        von selbst durch - dieselbe Ueberlegung wie in hat_harte_kante(), nur
        mit Zahlen statt mit ja/nein.

        vorgabe ist der Wert aus dem Encoder Setup; er gilt fuer jeden
        Schnitt, fuer den nichts Eigenes eingestellt wurde.
        """
        werte = []
        for (a, b) in self._cut_intervals:
            if a >= start_s - eps and b <= end_s + eps:
                key = self._cut_key(a, b)
                if key in self._hard_cuts:
                    werte.append(0.0)
                else:
                    werte.append(float(self._blenden.get(key, vorgabe)))
        if not werte:
            return float(vorgabe)
        return min(werte)

    def get_blenden(self) -> list:
        """Fuer die Projektdatei: [[start, end, sekunden], ...]."""
        self.prune_blenden()
        return [[a, b, self._blenden[(a, b)]] for (a, b) in sorted(self._blenden)]

    def set_blenden(self, eintraege):
        """Aus der Projektdatei. Fehlt der Schluessel, folgt alles der Vorgabe."""
        self._blenden = {}
        for item in (eintraege or []):
            try:
                self._blenden[self._cut_key(item[0], item[1])] = float(item[2])
            except (TypeError, IndexError, ValueError):
                continue
        self.prune_blenden()

    def prune_blenden(self):
        """Laengen wegwerfen, zu denen es keinen Schnitt mehr gibt.

        Dieselbe Ueberlegung wie bei prune_hard_cuts(): sonst erbte ein
        spaeter an derselben Stelle gesetzter Schnitt die alte Laenge.
        """
        alive = {self._cut_key(a, b) for (a, b) in self._cut_intervals}
        for key in [k for k in self._blenden if k not in alive]:
            del self._blenden[key]

    # ------------------------------------------------------------------
    # Merge-Fades an den Naehten der Videoliste
    # ------------------------------------------------------------------
    def hat_merge_fade(self, naht: int) -> bool:
        return int(naht) in self._merge_fades

    def get_merge_fade(self, naht: int):
        """Eingestellte Laenge dieser Naht, None fuer die Vorgabe.

        Ob ueberhaupt ein Merge-Fade gesetzt ist, sagt hat_merge_fade() -
        None kann hier beides heissen.
        """
        return self._merge_fades.get(int(naht))

    def set_merge_fade(self, naht: int, an: bool, sekunden=None):
        """Merge-Fade an dieser Naht setzen oder wegnehmen.

        sekunden=None laesst die Naht der Vorgabe folgen.
        """
        naht = int(naht)
        if not an:
            self._merge_fades.pop(naht, None)
        else:
            self._merge_fades[naht] = (None if sekunden is None
                                       else float(sekunden))

    def merge_fade_laenge(self, naht: int, vorgabe) -> float:
        """Laenge des Merge-Fade an dieser Naht, 0 wenn keiner gesetzt ist."""
        naht = int(naht)
        if naht not in self._merge_fades:
            return 0.0
        eigen = self._merge_fades[naht]
        return float(vorgabe if eigen is None else eigen)

    def get_merge_fades(self) -> list:
        """Fuer die Projektdatei: [[naht, sekunden_oder_null], ...]."""
        return [[n, self._merge_fades[n]] for n in sorted(self._merge_fades)]

    def set_merge_fades(self, eintraege):
        """Aus der Projektdatei. Fehlt der Schluessel, gibt es keine."""
        self._merge_fades = {}
        for item in (eintraege or []):
            try:
                naht = int(item[0])
                wert = item[1] if len(item) > 1 else None
                self._merge_fades[naht] = (None if wert is None
                                           else float(wert))
            except (TypeError, IndexError, ValueError):
                continue

    def prune_merge_fades(self, anzahl_videos: int):
        """Naehte wegwerfen, die es bei dieser Anzahl Videos nicht gibt.

        n Videos haben n-1 Naehte. Nach dem Entfernen eines Videos aus der
        Liste bleibt eine Naht mit zu grosser Nummer uebrig - sie zeigte auf
        eine Grenze, die es nicht mehr gibt.
        """
        hoechste = int(anzahl_videos) - 2
        for naht in [n for n in self._merge_fades if n < 0 or n > hoechste]:
            del self._merge_fades[naht]

    def is_hard_cut(self, start_s, end_s) -> bool:
        return self._cut_key(start_s, end_s) in self._hard_cuts

    def set_hard_cut(self, start_s, end_s, hard: bool = True):
        key = self._cut_key(start_s, end_s)
        if hard:
            self._hard_cuts.add(key)
        else:
            self._hard_cuts.discard(key)
        self._sync_timeline_hard_cuts()

    def hat_harte_kante(self, start_s, end_s, eps: float = 0.001) -> bool:
        """Ist irgendein Schnitt in diesem Bereich eine harte Kante?

        Fuer zusammengefasste Bereiche: grenzen mehrere Schnitte aneinander,
        sind sie im Video ein einziger Uebergang. Der ist entweder hart oder
        hat eine Blende - eine innere Kante gibt es nicht. Reicht eine
        Markierung, gilt der ganze Uebergang als hart.
        """
        for (a, b) in self._cut_intervals:
            if a >= start_s - eps and b <= end_s + eps:
                if self._cut_key(a, b) in self._hard_cuts:
                    return True
        return False

    def toggle_hard_cut(self, start_s, end_s) -> bool:
        """Schaltet um und liefert den neuen Zustand (True = harte Kante)."""
        new_state = not self.is_hard_cut(start_s, end_s)
        self.set_hard_cut(start_s, end_s, new_state)
        return new_state

    def get_hard_cuts(self) -> list:
        """Fuer die Projektdatei: Liste [[start, end], ...]."""
        self.prune_hard_cuts()
        return [[a, b] for (a, b) in sorted(self._hard_cuts)]

    def set_hard_cuts(self, pairs):
        self._hard_cuts = set()
        for item in (pairs or []):
            try:
                self._hard_cuts.add(self._cut_key(item[0], item[1]))
            except (TypeError, IndexError, ValueError):
                continue
        self.prune_hard_cuts()
        self._sync_timeline_hard_cuts()

    def prune_hard_cuts(self):
        """Markierungen wegwerfen, zu denen es keinen Schnitt mehr gibt.

        Sonst wuerde ein spaeter an genau derselben Stelle gesetzter Schnitt
        die alte Markierung erben.

        Die eingestellten Blendenlaengen gehen hier mit. Sie haengen an
        denselben Schluesseln und muessen unter denselben Bedingungen weg;
        an den rund vier Aufrufstellen je zwei Zeilen zu schreiben waere die
        Gelegenheit, eine davon zu vergessen.
        """
        alive = {self._cut_key(a, b) for (a, b) in self._cut_intervals}
        self._hard_cuts &= alive
        self.prune_blenden()
        self._sync_timeline_hard_cuts()

    def _sync_timeline_hard_cuts(self):
        try:
            self.timeline.set_hard_cut_keys(self._hard_cuts)
        except AttributeError:
            pass

    def is_end_cut(self, end_s: float, eps: float = 0.1) -> bool:
        """True, wenn end_s bis ans Ende des Gesamtvideos reicht."""
        video_total = sum(self.video_durations)
        return abs(end_s - video_total) < eps

    def remove_end_cut_intervals(self, eps: float = 0.1) -> list:
        """
        Entfernt vorhandene End-Schnitte (Schnitte, die bis ans Videoende
        reichen) und aktualisiert die Timeline.

        Gegenstueck zu on_set_begin_clicked() im MainWindow, das denselben
        Austausch fuer den Anfangsschnitt macht. Ohne das wuerde ein zweiter
        End-Schnitt zusaetzlich angelegt statt den ersten zu ersetzen - und
        ein spaeteres Videoende liesse sich gar nicht mehr einstellen.

        Gibt die entfernten Intervalle zurueck.
        """
        removed = [iv for iv in self._cut_intervals if self.is_end_cut(iv[1], eps)]
        if not removed:
            return []

        for iv in removed:
            self._cut_intervals.remove(iv)
        print(f"[DEBUG] vorhandene End-Cuts ersetzt: {removed}")

        # Auch die Aufzeichnung des ersetzten End-Schnitts faellt weg. Sonst
        # erbte der neue End-Schnitt sie, falls er auf denselben Schluessel
        # faellt - und was der alte weggenommen hat, ist ohnehin nicht mehr
        # zurueckzuholen: der neue schneidet auf der bereits gekuerzten Spur.
        self.prune_cut_points()
        self.prune_hard_cuts()
        self.timeline.clear_all_cuts()
        for (a, b) in self._cut_intervals:
            self.timeline.add_cut_interval(a, b)
        self._sync_timeline_hard_cuts()
        return removed

    def _has_active_file(self) -> bool:
        """Prüft, ob der Player noch eine gültige Datei (playlist/current_index) geladen hat."""
        # 1) Hat der VideoEditor eine Playlist?
        if not self.video_editor.playlist:
            return False

        # 2) current_index darf nicht außerhalb liegen
        idx = self.video_editor.get_current_index()
        if idx < 0 or idx >= len(self.video_editor.playlist):
            return False

        # 3) Es muss auch wirklich eine Datei geladen sein
        fname = self.video_editor.get_current_file()
        if not fname:
            return False

        return True
    
    

    def _get_current_global_time(self) -> float:
        return self.video_editor.get_current_position_s()
    
    def _emit_cuts_changed(self):
        total_cut = self.get_total_cuts()
        self.cutsChanged.emit(total_cut)
    
    def is_in_cut_segment(self, time_s: float) -> bool:
        """
        Returns True, wenn 'time_s' innerhalb eines vorhandenen
        Schnittbereichs (start_s <= time_s < end_s) liegt.

        Verglichen wird auf Millisekunden: die Sprungzeit kommt auf ms
        gerundet an, die Schnittzeiten aus dem Player nicht. Eine Sprungzeit
        genau auf dem Schnittende rutschte so durch die Rundung knapp davor
        und galt als drinnen. Nur die Pruefung vor dem Sprung, nicht der Export.
        """
        t = round(time_s, 3)
        for (start_s, end_s) in self._cut_intervals:
            if round(start_s, 3) <= t < round(end_s, 3):
                return True
        return False
