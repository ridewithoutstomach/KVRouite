#!/usr/bin/env python3

"""
GoPro2GPX with accurate time calculation based on video duration

Original gopro2gpx project:
Copyright (C) 2019 Juan M. Casillas <juanm.casillas@gmail.com>
https://github.com/juanmcasillas/gopro2gpx

Modified by:
Copyright (C) 2024 Bernd Eller <bernd@kvrouite.com>
https://github.com/ridewithoutstomach

Modifications:
- Accurate timestamp calculation based on video duration using FFprobe
- Even distribution of GPS points over the entire video timeline
- Enhanced analysis and debugging functions
- Improved time synchronization between GPS data and video

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""
import os
import sys
import struct
import json
import tempfile
from datetime import datetime, timedelta
import argparse
import math
import gc
import json

MY_GLOBAL_TMP_DIR = os.environ.get("KVR_TEMP_DIR", tempfile.gettempdir())
if not os.path.exists(MY_GLOBAL_TMP_DIR):
    os.makedirs(MY_GLOBAL_TMP_DIR, exist_ok=True)


# -----------------------------
# Hilfsfunktionen
# -----------------------------
def haversine(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lon points"""
    R = 6371000  # m
    from math import radians, sin, cos, sqrt, atan2
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

# -----------------------------
# Trim: Entferne 0/invalid und instabilen Beginn
# -----------------------------
def trim_invalid_gps_points(points, max_jump_distance=500, max_tunnel_time_gap=10):
    if not points or len(points) < 10:
        #print("⚠️ Not enough GPS points to trim.")
        print("[WARNING] Not enough GPS points to trim.")
        
        return points

    clusters = []
    current_cluster = [points[0]]

    for i in range(1, len(points)):
        lat1, lon1, t1 = points[i-1][:3]
        lat2, lon2, t2 = points[i][:3]
        dist = haversine(lat1, lon1, lat2, lon2)
        time_gap = abs(t2 - t1) if isinstance(t2, (int, float)) else 0

        if dist > max_jump_distance and time_gap > max_tunnel_time_gap:
            clusters.append(current_cluster)
            current_cluster = [points[i]]
        else:
            current_cluster.append(points[i])

    clusters.append(current_cluster)
    largest_cluster = max(clusters, key=len)

    removed_count_start = points.index(largest_cluster[0])
    removed_count_end = len(points) - points.index(largest_cluster[-1]) - 1
    removed_count = removed_count_start + removed_count_end

    time_removed_start = largest_cluster[0][2] - points[0][2] if removed_count_start > 0 else 0
    time_removed_end = points[-1][2] - largest_cluster[-1][2] if removed_count_end > 0 else 0
    total_time_removed = time_removed_start + time_removed_end

    ## ⚡ Immer ausgeben
    #print("⚡ DEBUG: Trim report")
    #print(f"  Total points removed: {removed_count}")
    #print(f"  Time removed (seconds): {total_time_removed:.3f} (start: {time_removed_start:.3f}, end: {time_removed_end:.3f})")

    return largest_cluster
    
# -----------------------------
# Robust start time
# -----------------------------
def get_video_start_time(video_path, metadata):
    """
    Liefert die realistische Startzeit des Videos.
    Priorität:
    1. GPSU im Metadata-Stream
    2. Creation time via FFprobe
    3. Fallback: jetzt
    """
    start_time = find_gpsu_time(metadata)
    if start_time:
        # Prüfen, ob Jahr plausibel ist (z.B. 2020-2030)
        if 2000 <= start_time.year <= 2030:
            return start_time
        else:
            #print(f"⚠️ GPSU time implausible ({start_time}), trying creation_time...")
            print(f"[WARNING] GPSU time implausible ({start_time}), trying creation_time...")

    # Aufnahmezeit aus dem Container ("mvhd"). Das ist dieselbe Angabe,
    # die ffprobe als creation_time gemeldet hat - an einer GoPro-Datei
    # geprueft, beide sagen 2025-09-19T07:11:56Z.
    try:
        from core.mp4_keyframes import creation_time_from_container
        aus_container = creation_time_from_container(video_path)
        if aus_container is not None:
            print(f"Using creation_time from container: {aus_container}")
            return aus_container
    except Exception as exc:
        print(f"[WARN] Aufnahmezeit nicht lesbar: {exc}")

    # fallback
    now = datetime.now()
    print(f"Using current time as start time: {now}")
    return now
    


# -----------------------------
# Video duration & metadata
# -----------------------------
def get_video_duration(video_path):
    """Laenge in Sekunden, ueber core.framerate (Container bzw. GStreamer)."""
    try:
        from core.framerate import dauer as _dauer
        wert = _dauer(video_path)
        if wert and wert > 0:
            print(f"Video duration: {wert:.2f} seconds")
            return float(wert)
        print(f"Error getting video duration: keine Laenge lesbar ({video_path})")
        return None
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return None

def extract_metadata(video_path):
    """Rohdaten der GoPro-Telemetriespur ("gpmd"), direkt aus dem Container.

    Die Spur wird nicht dekodiert, sondern nur herauskopiert - genau das,
    was "ffmpeg -codec copy -map 0:N" getan hat. Das Ergebnis ist Byte fuer
    Byte dasselbe (an zwei GoPro-Dateien mit gleicher SHA1 geprueft) und
    braucht 0,02 s statt 13,9 s: kein Prozessstart, keine Zwischendatei, und
    zusammenhaengende Samples werden am Stueck gelesen.

    Voraussetzung ist ein MP4/MOV-Container - bei GoPro-Material immer
    gegeben. Liefert None, wenn keine "gpmd"-Spur gefunden wird.
    """
    try:
        from core.mp4_keyframes import track_data_from_container
        daten = track_data_from_container(video_path, b"gpmd")
    except Exception as exc:
        print(f"[ERROR] Telemetrie nicht lesbar: {exc}")
        return None
    if not daten:
        print("No GPMD stream found")
        return None
    return daten

# -----------------------------
# GPS parsing
# -----------------------------
def find_gpsu_time(metadata):
    gpsu_times = []
    pos = 0
    while pos < len(metadata) - 20:
        try:
            if metadata[pos:pos+4] == b'GPSU':
                data_start = pos + 8
                time_data = metadata[data_start:data_start+20]
                time_str = time_data.decode('ascii', errors='ignore').split('\x00')[0]
                if len(time_str) >= 14:
                    # GPSU traegt nur zwei Jahresziffern (yymmddhhmmss.sss).
                    # GoPro-Kameras mit GPS gibt es seit 2016, also immer 20yy.
                    full_time_str = '20' + time_str
                    try:
                        gpsu_time = datetime.strptime(full_time_str[:17], '%Y%m%d%H%M%S.%f')
                    except ValueError:
                        gpsu_time = datetime.strptime(full_time_str[:14], '%Y%m%d%H%M%S')
                    gpsu_times.append(gpsu_time)
            pos += 1
        except Exception:
            pos += 1
            continue
    if gpsu_times:
        start_time = min(gpsu_times)
        print(f"Using start time: {start_time}")
        return start_time
    return None

def parse_gps5_data(metadata):
    """Liest die GPS-Punkte aus der rohen Telemetriespur.

    Zwei Formate, je nach Kamera:
    - GPS5 (bis HERO11): 5 Werte je Messung, die Zeit kommt aus dem
      vorangehenden GPSU-Block, die Messungen liegen 0,2 s auseinander.
    - GPS9 (HERO11 zusaetzlich, ab HERO13 ausschliesslich, auch MAX 2 und
      MISSION 1): 9 Werte je Messung, jede traegt ihre eigene Zeit
      (Tage seit 2000-01-01 und Millisekunden seit Mitternacht). GPSU und
      GPS5 fehlen dort komplett. Die Skalierung steht im SCAL-Block mit
      9 Werten direkt vor dem GPS9-Block. Aufbau an einer HERO13-Datei
      geprueft: TYPE "lllllllSS", 32 Byte je Messung, SCAL
      10000000, 10000000, 1000, 1000, 100, 1, 1000, 100, 1.
    """
    # Beide Formate getrennt sammeln: HERO11 schreibt GPS5 und GPS9
    # nebeneinander, zusammengeworfen gaebe das jeden Punkt doppelt.
    points = []        # GPS5
    points_gps9 = []   # GPS9
    pos = 0
    current_time = None
    # Vorgabe laut GoPro-Doku, wird vom SCAL-Block der Datei ueberschrieben
    gps9_scale = (10000000.0, 10000000.0, 1000.0, 1000.0, 100.0, 1.0, 1000.0, 100.0, 1.0)
    gps9_epoche = datetime(2000, 1, 1)

    while pos < len(metadata) - 8:
        try:
            # SCAL mit 9 Werten → Skalierung fuer GPS9 merken
            if metadata[pos:pos+4] == b'SCAL' and metadata[pos+4] == 0x6C \
                    and metadata[pos+5] == 4 \
                    and struct.unpack_from('>H', metadata, pos+6)[0] == 9 \
                    and pos + 8 + 36 <= len(metadata):
                werte = struct.unpack_from('>9i', metadata, pos + 8)
                if all(w > 0 for w in werte):
                    gps9_scale = tuple(float(w) for w in werte)

            # GPS9 → Positionsdaten mit eigener Zeit je Messung
            if metadata[pos:pos+4] == b'GPS9' and metadata[pos+5] == 32:
                repeat = struct.unpack_from('>H', metadata, pos+6)[0]
                data_start = pos + 8
                for i in range(repeat):
                    offset = data_start + i*32
                    if offset + 32 <= len(metadata):
                        values = struct.unpack_from('>7i2h', metadata, offset)
                        lat = values[0] / gps9_scale[0]
                        lon = values[1] / gps9_scale[1]
                        alt = values[2] / gps9_scale[2]
                        tage = values[5] / gps9_scale[5]
                        sekunden = values[6] / gps9_scale[6]
                        if -90 <= lat <= 90 and -180 <= lon <= 180 and 0 < tage < 20000:
                            timestamp = gps9_epoche + timedelta(days=tage, seconds=sekunden)
                            points_gps9.append((lat, lon, alt, timestamp))

            # GPSU → Zeitstempel extrahieren
            if metadata[pos:pos+4] == b'GPSU':
                data_start = pos + 8
                time_data = metadata[data_start:data_start+20]
                time_str = time_data.decode('ascii', errors='ignore').split('\x00')[0]
                if len(time_str) >= 14:
                    # GPSU traegt nur zwei Jahresziffern (yymmddhhmmss.sss).
                    # GoPro-Kameras mit GPS gibt es seit 2016, also immer 20yy.
                    full_time_str = '20' + time_str
                    try:
                        current_time = datetime.strptime(full_time_str[:17], '%Y%m%d%H%M%S.%f')
                    except ValueError:
                        current_time = datetime.strptime(full_time_str[:14], '%Y%m%d%H%M%S')

            # GPS5 → Positionsdaten extrahieren
            if metadata[pos:pos+4] == b'GPS5':
                type_byte = metadata[pos+4]
                size = metadata[pos+5]
                repeat = struct.unpack_from('>H', metadata, pos+6)[0]
                data_start = pos + 8
                for i in range(repeat):
                    offset = data_start + i*20
                    if offset + 20 <= len(metadata):
                        values = struct.unpack_from('>5i', metadata, offset)
                        lat = values[0] / 10000000.0
                        lon = values[1] / 10000000.0
                        alt = values[2] / 100.0
                        if -90 <= lat <= 90 and -180 <= lon <= 180 and current_time:
                            # Jeder GPS5-Block folgt typischerweise mit 0.2s Abstand (5Hz)
                            timestamp = current_time + timedelta(seconds=i*0.2)
                            points.append((lat, lon, alt, timestamp))
            pos += 1
        except Exception:
            pos += 1
            continue

    # GPS9 hat Vorrang (genauere Zeit, 10 Hz); GPS5 nur, wenn es das
    # einzige Format in der Datei ist (Kameras bis HERO10).
    if points_gps9:
        print(f"GPS9 points: {len(points_gps9)} (GPS5 ignored: {len(points)})")
        points = points_gps9

    #points = trim_invalid_gps_points(points)
    print(f"GPS without trimming: {len(points)}")
    #print(f"Remaining GPS points after trimming: {len(points)}")
    return points


def telemetrie_info(metadata):
    """Kameraname und GPS-Format der Telemetriespur, fuer die Anzeige.

    Der Kameraname steht im DVNM-Block des Geraets (z. B. "HERO10 Black",
    "HERO13 Black"); daneben gibt es DVNM-Eintraege fuer Untergeraete
    ("Global Settings" u. ae.), die werden uebersprungen. Das Format ist
    das, was parse_gps5_data tatsaechlich benutzt: GPS9 vor GPS5.
    Liefert (kamera, format), beides Strings, kamera ggf. "unknown".
    """
    kamera = "unknown"
    if metadata:
        pos = 0
        while True:
            pos = metadata.find(b'DVNM', pos)
            if pos < 0 or pos + 8 > len(metadata):
                break
            try:
                typ = metadata[pos+4]
                laenge = metadata[pos+5] * struct.unpack_from('>H', metadata, pos+6)[0]
                if typ == 0x63 and laenge > 0:  # 'c' = Text
                    name = metadata[pos+8:pos+8+laenge].rstrip(b'\x00').decode('ascii', 'replace').strip()
                    if name.upper().startswith(("HERO", "MAX", "MISSION", "FUSION")):
                        kamera = name
                        break
            except Exception:
                pass
            pos += 4

    if metadata and b'GPS9' in metadata:
        fmt = "GPS9"
    elif metadata and b'GPS5' in metadata:
        fmt = "GPS5"
    else:
        fmt = "no GPS"
    return kamera, fmt


# -----------------------------
# Temp-JSON-Zwischenspeicherung (RAM-Entlastung)
# -----------------------------
import gc
import json

def save_temp_points(points, video_path, tmp_dir=MY_GLOBAL_TMP_DIR):
    """
    Speichert extrahierte Rohpunkte in eine temporäre JSON-Datei.
    Rückgabe: Pfad zur Datei oder None.
    """
    if not points:
        return None

    base_name = os.path.basename(video_path)
    safe_name = os.path.splitext(base_name)[0].replace(" ", "_")
    temp_json_path = os.path.join(tmp_dir, f"KVR_GOPRO_RAW_{safe_name}.json")

    try:
        with open(temp_json_path, "w", encoding="utf-8") as f:
            # Konvertiere Zeitstempel in ISO (serialisierbar)
            json.dump([
                {"lat": lat, "lon": lon, "ele": alt, "time": timestamp.isoformat()}
                for (lat, lon, alt, timestamp) in points
            ], f)
        print(f"[DEBUG] Saved raw GPS to {temp_json_path} ({len(points)} pts)")
        return temp_json_path
    except Exception as e:
        print(f"[ERROR] Could not save temp JSON: {e}")
        return None

def load_temp_points(temp_json_path):
    """
    Lädt Punkte aus der Temp-JSON zurück in List[dict] mit datetime-Objekt.
    """
    try:
        with open(temp_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Konvertiere ISO-Zeiten zurück
        for pt in data:
            pt["time"] = datetime.fromisoformat(pt["time"])
        print(f"[DEBUG] Loaded {len(data)} points from {temp_json_path}")
        return data
    except Exception as e:
        print(f"[ERROR] Could not load temp JSON: {e}")
        return []



# -----------------------------
# Resample GPS to 1s
# -----------------------------

def resample_to_1s_auto(points):
    """
    Automatisches Resampling ohne Benutzerabfrage - für GoPro-Extraktion
    """
    if not points or len(points) < 2:
        return points

    # Basiszeit vom ersten Punkt
    base_time = points[0]["time"]
    
    # Letzte Zeit für Gesamtdauer
    last_time = points[-1]["time"]
    total_seconds = int((last_time - base_time).total_seconds())
    
    new_data = []
    current_idx = 0
    
    for target_second in range(0, total_seconds + 1):
        target_time = base_time + timedelta(seconds=target_second)
        
        # Finde die beiden Punkte, zwischen denen target_time liegt
        while (current_idx < len(points) - 1 and 
               points[current_idx + 1]["time"] < target_time):
            current_idx += 1
        
        if current_idx >= len(points) - 1:
            break
            
        pt_before = points[current_idx]
        pt_after = points[current_idx + 1]
        
        time_before = pt_before["time"]
        time_after = pt_after["time"]
        
        if time_before == time_after:
            ratio = 0.0
        else:
            ratio = (target_time - time_before).total_seconds() / (time_after - time_before).total_seconds()
        
        # Interpoliere die Werte
        lat = pt_before["lat"] + ratio * (pt_after["lat"] - pt_before["lat"])
        lon = pt_before["lon"] + ratio * (pt_after["lon"] - pt_before["lon"])
        ele = pt_before["ele"] + ratio * (pt_after["ele"] - pt_before["ele"])
        
        new_data.append({
            "lat": lat,
            "lon": lon, 
            "ele": ele,
            "time": target_time
        })
    
    return new_data 
# GPX export
# -----------------------------
def create_gpx_with_time(points, output_path):
    if not points:
        print("No points to write to GPX")
        return False

    gpx_template = '''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="GoPro2GPX" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <time>{start_time}</time>
  </metadata>
  <trk>
    <name>GoPro GPS Track</name>
    <trkseg>
{points}
    </trkseg>
  </trk>
</gpx>'''

    point_lines = []
    for pt in points:
        time_str = pt["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        point_lines.append(f'      <trkpt lat="{pt["lat"]:.6f}" lon="{pt["lon"]:.6f}">')
        point_lines.append(f'        <ele>{pt["ele"]:.1f}</ele>')
        point_lines.append(f'        <time>{time_str}</time>')
        point_lines.append('      </trkpt>')

    start_time_str = points[0]["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(gpx_template.format(start_time=start_time_str, points='\n'.join(point_lines)))

    print(f"GPX file created: {output_path}")
    return True

# -----------------------------
# Analysis
# -----------------------------
def analyze_gps_distribution(points, video_duration):
    total_points = len(points)
    if total_points == 0 or video_duration == 0:
        return
    print(f"Total GPS points: {total_points}")
    print(f"Video duration: {video_duration:.2f} seconds")
    print(f"Average GPS frequency: {total_points / video_duration:.2f} Hz")
    print(f"Time between points: {video_duration / total_points:.3f} s")
    
# -----------------------------
# Fix GPX duration
# -----------------------------
# -----------------------------
# Fix GPX duration by shifting points
# -----------------------------
# -----------------------------
# Fix GPX duration by shifting points (with minimal threshold)
# -----------------------------
def adjust_gpx_to_video_duration(points, video_duration):
    """
    Passt die GPX-Zeiten an, sodass die Gesamt-GPX-Dauer der Video-Dauer entspricht.
    Der zweite Punkt wird um die Differenz verschoben, alle nachfolgenden Punkte ebenfalls.
    Führt keine Änderung aus, wenn die Differenz < 0.5 Sekunden ist.
    """
    if not points or len(points) < 2:
        print("⚠️ Not enough points to adjust GPX.")
        return points

    gpx_start = points[0]["time"]
    gpx_end = points[-1]["time"]
    gpx_duration = (gpx_end - gpx_start).total_seconds()
    
    diff = video_duration - gpx_duration
    if abs(diff) < 0.5:
        # Kleine Differenz ignorieren
        return points

    #print(f"⚡ DEBUG: Shifting GPX points by {diff:.3f} s to match video duration")
    print(f"[DEBUG] Shifting GPX points by {diff:.3f} s to match video duration")

    # Alle Punkte ab dem zweiten Punkt verschieben
    for i in range(1, len(points)):
        points[i]["time"] += timedelta(seconds=diff)

    return points
    

# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description='Extract GPS from GoPro video with accurate timestamps')
    parser.add_argument('input_file')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Error: File not found: {args.input_file}")
        return

    video_duration = get_video_duration(args.input_file)
    if not video_duration:
        return

    metadata = extract_metadata(args.input_file)
    if not metadata:
        return

    #gps_start_time = find_gpsu_time(metadata) or datetime.now()
    gps_start_time = get_video_start_time(args.input_file, metadata)
    points = parse_gps5_data(metadata)
    
    if not points:
        return

    
    
    
    points_with_time = points  # Rohpunkte haben schon die echte Zeit
    #points_resampled = resample_to_1s(points_with_time)

    points_resampled = adjust_gpx_to_video_duration(points_resampled, video_duration)
    
    output_path = os.path.join(MY_GLOBAL_TMP_DIR, "KVR_GOPRO_Extract.tmp.gpx")
    
    success = create_gpx_with_time(points_resampled, output_path)
    
    gpx_start = points_resampled[0]["time"]
    gpx_end = points_resampled[-1]["time"]
    gpx_duration = (gpx_end - gpx_start).total_seconds()

    diff_seconds = video_duration - gpx_duration
    diff_percent = (diff_seconds / video_duration) * 100 if video_duration else 0

    #print("\n⚡ DEBUG: GPX vs Video Duration")
    print("[DEBUG] GPX vs Video Duration")
    print(f"  Video duration: {video_duration:.3f} s")
    print(f"  GPX duration:   {gpx_duration:.3f} s")
    print(f"  Difference:     {diff_seconds:+.3f} s ({diff_percent:+.2f}%)")
    analyze_gps_distribution(points_resampled, video_duration)
   

if __name__ == "__main__":
    main()
