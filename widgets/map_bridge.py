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

# widgets/map_bridge.py

from PySide6.QtCore import QObject, Signal, Slot

class MapBridge(QObject):
    pointClickedSignal = Signal(int)
    pointMovedSignal = Signal(int, float, float)
    syncClickedSignal = Signal(int)  # <-- Neu
    syncClickedNoArg = Signal()   # <-- Neue Signal-Variante ohne Parameter
    newPointInsertedSignal = Signal(float, float, int)
    mapboxProfileChangedSignal = Signal(str)  
    
        
    def __init__(self, parent=None):
        super().__init__(parent)
        
    @Slot(str)
    def jsLog(self, text):
        """
        Wird von JavaScript via channelObj.jsLog("...") aufgerufen.
        => Gibt 'text' im Python-Terminal aus.
        """
        print(f"[JS->Py] {text}")    
    

    @Slot(int)
    def pointClicked(self, index):
        self.pointClickedSignal.emit(index)
    
    @Slot(int, float, float)
    def pointMoved(self, index, lat, lon):
        """
        Wird von JavaScript aufgerufen, wenn ein Feature (Point)
        in der Karte verschoben wurde.
        index: int => id des Punktes
        lat, lon: float => neue Koordinaten
        """
        print(f"[DEBUG] pointMoved => index={index}, lat={lat:.6f}, lon={lon:.6f}")
        # => Jetzt weitergeben an Python-Logik, z.B. über ein Signal:
        self.pointMovedSignal.emit(index, lat, lon)
        # ... oder direkt an self.parent().onPointMoved(index, lat, lon) ...
        
    @Slot(int)
    def syncClicked(self, idx):
        self.syncClickedSignal.emit(idx)   # <-- NEU    
        
    @Slot()
    def syncNoArgSlot(self):
        """
        Diese Slot-Methode kann JS aufrufen: channelObj.syncNoArgSlot()
        => wir lösen damit das Signal syncClickedNoArg in Python aus.
        """
        self.syncClickedNoArg.emit()
        # (Optional: Hier kannst du auch print("JS rief syncNoArgSlot auf!") machen)    
        
    
    @Slot(float, float, int)
    def newPointInserted(self, lat, lon, idx):
        """
        Diese Methode wird von JS via channelObj.newPointInserted(...) aufgerufen.
        """
        print(f"[Py Debug] => newPointInserted => lat={lat}, lon={lon}, idx={idx}")
        # Weitergeben an MainWindow oder sonstige Logik:
        self.newPointInsertedSignal.emit(lat, lon, idx)
    
    @Slot(str)
    def mapboxProfileChanged(self, profile):
        """
        Diese Methode wird von JS via channelObj.mapboxProfileChanged(...) aufgerufen.
        """
        print(f"[Py Debug] => mapboxProfileChanged => profile={profile}")
        # Weitergeben an MainWindow oder sonstige Logik:
        self.mapboxProfileChangedSignal.emit(profile)