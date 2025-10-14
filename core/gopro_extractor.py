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
import subprocess
import json
import tempfile
from datetime import datetime, timedelta
import argparse
import math

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
            print("[WARNING] GPSU time implausible ({start_time}), trying creation_time...")

    # FFprobe creation_time
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        creation_time_str = data.get('format', {}).get('tags', {}).get('creation_time')
        if creation_time_str:
            try:
                creation_time = datetime.fromisoformat(creation_time_str.replace('Z', '+00:00'))
                print(f"Using creation_time from metadata: {creation_time}")
                return creation_time
            except Exception:
                pass
    except Exception as e:
        print(f"Error reading creation_time: {e}")

    # fallback
    now = datetime.now()
    print(f"Using current time as start time: {now}")
    return now
    


# -----------------------------
# Video duration & metadata
# -----------------------------
def get_video_duration(video_path):
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'json', video_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        print(f"Video duration: {duration:.2f} seconds")
        return duration
    except Exception as e:
        print(f"Error getting video duration: {e}")
        return None

def extract_metadata(video_path):
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', video_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        gpmd_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_tag_string') == 'gpmd':
                gpmd_stream = stream
                break
        if not gpmd_stream:
            print("No GPMD stream found")
            return None
        stream_index = gpmd_stream['index']
        with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as f:
            temp_path = f.name
        cmd = ['ffmpeg', '-y', '-i', video_path, '-codec', 'copy', '-map', f'0:{stream_index}', '-f', 'rawvideo', temp_path]
        subprocess.run(cmd, capture_output=True)
        with open(temp_path, 'rb') as f:
            metadata = f.read()
        os.unlink(temp_path)
        return metadata
    except Exception as e:
        print(f"Error: {e}")
        return None

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
                    full_time_str = ('20' if time_str[0] in ['0','1'] else '19') + time_str
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
    points = []
    pos = 0
    current_time = None

    while pos < len(metadata) - 8:
        try:
            # GPSU → Zeitstempel extrahieren
            if metadata[pos:pos+4] == b'GPSU':
                data_start = pos + 8
                time_data = metadata[data_start:data_start+20]
                time_str = time_data.decode('ascii', errors='ignore').split('\x00')[0]
                if len(time_str) >= 14:
                    full_time_str = ('20' if time_str[0] in ['0','1'] else '19') + time_str
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

    points = trim_invalid_gps_points(points)
    print(f"Remaining GPS points after trimming: {len(points)}")
    return points

# -----------------------------
# Timestamps
# -----------------------------

# -----------------------------
# Resample GPS to 1s
# -----------------------------
def resample_to_1s(points_with_time):
    """
    Interpoliert die GPS-Punkte auf 1-Sekunden-Intervalle
    ohne die Zeit über die Video-Länge zu strecken.
    Punkte müssen bereits echte Zeitstempel haben.
    """
    if not points_with_time or len(points_with_time) < 2:
        return points_with_time

    # Basiszeit
    base_time = points_with_time[0][3]
    gpx_data = []
    for lat, lon, ele, t in points_with_time:
        gpx_data.append({"lat": lat, "lon": lon, "ele": ele, "time": t})

    # absolute Sekunden vom Start
    for pt in gpx_data:
        pt["abs_s"] = (pt["time"] - base_time).total_seconds()

    new_data = []
    target_s = 0
    total_s = int(gpx_data[-1]["abs_s"])
    i = 0

    while target_s <= total_s:
        # nächster Intervallpunkt finden
        while i < len(gpx_data) - 2 and gpx_data[i+1]["abs_s"] < target_s:
            i += 1

        pt1 = gpx_data[i]
        pt2 = gpx_data[i+1]

        s1, s2 = pt1["abs_s"], pt2["abs_s"]
        ratio = (target_s - s1) / (s2 - s1) if s2 != s1 else 0

        lat = pt1["lat"] + ratio * (pt2["lat"] - pt1["lat"])
        lon = pt1["lon"] + ratio * (pt2["lon"] - pt1["lon"])
        ele = pt1["ele"] + ratio * (pt2["ele"] - pt1["ele"])

        new_data.append({
            "lat": lat,
            "lon": lon,
            "ele": ele,
            "time": base_time + timedelta(seconds=target_s)
        })

        target_s += 1

    return new_data



# -----------------------------
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
    print("[DEBUG] Shifting GPX points by {diff:.3f} s to match video duration")

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
    points_resampled = resample_to_1s(points_with_time)

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
   
"""   
def main_direct(video_path: str):
    try:
        video_duration = get_video_duration(video_path)
        if not video_duration:
            return False

        metadata = extract_metadata(video_path)
        if not metadata:
            return False

        gps_start_time = get_video_start_time(video_path, metadata)
        points = parse_gps5_data(metadata)
        if not points:
            return False

        points_resampled = resample_to_1s(points)
        points_resampled = adjust_gpx_to_video_duration(points_resampled, video_duration)

        output_path = os.path.join(MY_GLOBAL_TMP_DIR, "KVR_GOPRO_Extract.tmp.gpx")
        success = create_gpx_with_time(points_resampled, output_path)
        return success
    except Exception as e:
        print(f"[ERROR] main_direct: {e}")
        return False
"""    

if __name__ == "__main__":
    main()
