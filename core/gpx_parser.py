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

# core/gpx_parser.py

import math
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from dateutil.parser import parse as dateutil_parse


gpx_start_time = datetime(2000, 1, 1, 0, 0, 0)  # Standard-Zeitstempel für rel_s    



def parse_gpx(gpx_file_path):
    
    """
    Liest eine GPX-Datei ein, extrahiert lat, lon, ele (Höhe) und time.
    Zusätzlich berechnet die Funktion distance, speed, gradient etc.
    Rückgabe: Liste von Dicts mit Feldern: 
        lat, lon, ele, time, delta_m, speed_kmh, gradient, rel_s
    """
    tree = ET.parse(gpx_file_path)
    root = tree.getroot()

    ns = {"default": "http://www.topografix.com/GPX/1/1"}
    trkpts = root.findall(".//default:trkpt", ns)
    if not trkpts:
        print("[DEBUG] Keine <trkpt> Elemente gefunden!")
        return []

    parsed_points = []
    for pt in trkpts:
        lat = float(pt.attrib["lat"])
        lon = float(pt.attrib["lon"])
        ele_el = pt.find("default:ele", ns)
        ele = float(ele_el.text) if ele_el is not None else 0.0
        time_el = pt.find("default:time", ns)
        if time_el is not None:
            time_str = time_el.text
            try:
                dt = dateutil_parse(time_str)
            except ValueError:
                dt = None
        else:
            dt = None

        parsed_points.append({
            "lat": lat,
            "lon": lon,
            "ele": ele,
            "time": dt
        })

    # (A) => Hier berechnen wir rel_s ab dem ersten Punkt
    if len(parsed_points) > 0:
        gpx_start_time = parsed_points[0]["time"]

    # Haversine etc.
    def haversine_m(lat1, lon1, lat2, lon2):
        R = 6371000
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat/2)**2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(d_lon/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c

    results = []
    total_distance_m = 0.0
    for i in range(len(parsed_points)):
        p = parsed_points[i]
        if i == 0:
            data = {
                "lat": p["lat"], 
                "lon": p["lon"],
                "ele": p["ele"], 
                "time": p["time"],
                "delta_m": 0.0, 
                "speed_kmh": 0.0, 
                "gradient": 0.0,
            }
        else:
            p_prev = parsed_points[i-1]
            dist_2d = haversine_m(p_prev["lat"], p_prev["lon"], p["lat"], p["lon"])
            elev_diff = p["ele"] - p_prev["ele"]
            dist_3d = math.sqrt(dist_2d**2 + elev_diff**2)
            time_diff_s = 0
            if p["time"] and p_prev["time"]:
                time_diff_s = (p["time"] - p_prev["time"]).total_seconds()
            delta_m = dist_3d
            total_distance_m += delta_m
            speed_kmh = 0.0
            if time_diff_s > 0:
                speed_kmh = (dist_3d / time_diff_s) * 3.6
            gradient = 0.0
            if dist_2d > 0:
                gradient = (elev_diff / dist_2d) * 100

            data = {
                "lat": p["lat"], 
                "lon": p["lon"],
                "ele": p["ele"], 
                "time": p["time"],
                "delta_m": delta_m,
                "speed_kmh": speed_kmh,
                "gradient": gradient
            }

        results.append(data)
    return results


def recalc_gpx_data(gpx_data: list[dict], shift_time: bool = True):
    
    """
    Aktualisiert delta_m, speed_kmh, gradient und rel_s,
    basierend auf bereits eingelesenen (u. U. modifizierten) gpx_data-Einträgen.
    """
    
    
    if not gpx_data:
        return


    # B) rel_s
    if(shift_time):
        first_time=gpx_data[0].get("time")

    # C) Hilfsfunktion Haversine
    def haversine_m(lat1, lon1, lat2, lon2):
        R = 6371000
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat/2)**2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(d_lon/2)**2)
        c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R*c

    # D) Alle Punkte durchgehen
    for i, pt in enumerate(gpx_data):
        if i == 0:
            pt["delta_m"]   = 0.0
            pt["speed_kmh"] = 0.0
            pt["gradient"]  = 0.0
        else:
            prev = gpx_data[i-1]
            lat1, lon1 = prev["lat"], prev["lon"]
            lat2, lon2 = pt["lat"],   pt["lon"]

            dist_2d = haversine_m(lat1, lon1, lat2, lon2)
            elev_diff = pt["ele"] - prev["ele"]
            dist_3d = math.sqrt(dist_2d*dist_2d + elev_diff*elev_diff)

            pt["delta_m"] = dist_3d

            time_diff_s = 0.0
            if pt["time"] and prev["time"]:
                time_diff_s = (pt["time"] - prev["time"]).total_seconds()

            if time_diff_s > 0:
                pt["speed_kmh"] = (dist_3d / time_diff_s)*3.6
            else:
                pt["speed_kmh"] = 0.0

            if dist_2d > 0:
                pt["gradient"] = (elev_diff/dist_2d)*100
            else:
                pt["gradient"] = 0.0

    # Keine Rückgabe, weil gpx_data in-place aktualisiert wird
    
def ensure_gpx_stable_ids(gpx_data: list[dict]):
    """
    Weist jedem GPX-Punkt ein 'stable_id' zu, falls nicht vorhanden.
    Bleibt unverändert, selbst wenn Index / Reihenfolge sich ändert.
    """
    for pt in gpx_data:
        if not pt.get("stable_id"):
            pt["stable_id"] = str(uuid.uuid4())
