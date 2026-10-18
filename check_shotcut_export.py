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
"""
Unit and integration test for core/shotcut_export.py.
Tests XML generation, frame calculations, transitions, and melt/Shotcut compatibility.
"""

import os
import sys
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from core.shotcut_export import (
    export_to_shotcut,
    can_open_in_shotcut,
    _stuecke_berechnen,
    _resolve_partials,
    _rohbereich
)


def test_stuecke_calculation():
    total_dur = 100.0
    skip_list = [
        [0.0, 10.0, -2],     # Startcut
        [30.0, 40.0, 2.0],   # Cut with 2s crossfade
        [60.0, 70.0, 0.0],   # Hard cut
        [90.0, 100.0, -1]    # Endcut
    ]
    stuecke = _stuecke_berechnen(skip_list, total_dur)
    assert len(stuecke) == 3, f"Expected 3 pieces, got {len(stuecke)}"
    assert stuecke[0] == [10.0, 30.0, 0.0, 2.0]
    assert stuecke[1] == [40.0, 60.0, 2.0, 0.0]
    assert stuecke[2] == [70.0, 90.0, 0.0, 0.0]

    # Check rohbereich
    roh0 = _rohbereich(*stuecke[0])
    assert roh0 == (10.0, 31.0, 0.0, 2.0, 0.0, 1.0)
    roh1 = _rohbereich(*stuecke[1])
    assert roh1 == (39.0, 60.0, 2.0, 0.0, 1.0, 0.0)
    roh2 = _rohbereich(*stuecke[2])
    assert roh2 == (70.0, 90.0, 0.0, 0.0, 0.0, 0.0)
    print("  [OK] test_stuecke_calculation passed")


def test_resolve_partials():
    durations = [10.0, 20.0, 15.0]
    # Spanning within video 0
    p1 = _resolve_partials(2.0, 8.0, durations)
    assert p1 == [(0, 2.0, 8.0)], f"Unexpected partials: {p1}"

    # Spanning from video 0 to video 1
    p2 = _resolve_partials(5.0, 15.0, durations)
    assert p2 == [(0, 5.0, 10.0), (1, 0.0, 5.0)], f"Unexpected partials: {p2}"

    # Spanning video 0, 1, 2
    p3 = _resolve_partials(8.0, 35.0, durations)
    assert p3 == [(0, 8.0, 10.0), (1, 0.0, 20.0), (2, 0.0, 5.0)], f"Unexpected partials: {p3}"
    print("  [OK] test_resolve_partials passed")


def test_xml_structure_and_melt():
    with tempfile.TemporaryDirectory() as tmpdir:
        clip1 = "/tmp/test_clip1.mp4"
        clip2 = "/tmp/test_clip2.mp4"

        # If test clips do not exist, create them
        if not os.path.exists(clip1) or not os.path.exists(clip2):
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=1280x720:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip1
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=duration=5:size=1280x720:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=880:duration=5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", clip2
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        out_mlt = os.path.join(tmpdir, "test_output.mlt")
        skip_list = [
            [0.0, 1.0, -2],     # Startcut (trim first second)
            [3.0, 5.0, 1.0],   # Cut 3s..5s with 1.0s crossfade
            [7.0, 8.0, 0.0],   # Hard cut 7s..8s
        ]

        xml_str = export_to_shotcut(
            videos=[clip1, clip2],
            video_durations=[5.0, 5.0],
            skip_list=skip_list,
            out_mlt_path=out_mlt,
            width=1280,
            height=720,
            fps_num=30,
            fps_den=1,
            title="Automated Test Project"
        )

        assert os.path.isfile(out_mlt), "MLT output file was not created"
        tree = ET.parse(out_mlt)
        root = tree.getroot()
        assert root.tag == "mlt"

        # Check profile
        profile = root.find("profile")
        assert profile is not None
        assert profile.attrib.get("width") == "1280"
        assert profile.attrib.get("height") == "720"
        assert profile.attrib.get("frame_rate_num") == "30"

        # Check producers
        producers = root.findall("producer")
        prod_ids = [p.attrib.get("id") for p in producers]
        assert "producer0" in prod_ids
        assert "producer1" in prod_ids
        assert "black" in prod_ids

        # Check transition tractor
        trans_tractors = [t for t in root.findall("tractor") if t.attrib.get("id", "").startswith("tractor_trans_")]
        assert len(trans_tractors) >= 1, "Expected at least 1 transition tractor"
        t0 = trans_tractors[0]
        prop_shotcut_trans = t0.find("./property[@name='shotcut:transition']")
        assert prop_shotcut_trans is not None and prop_shotcut_trans.text == "lumaMix"

        # Check V1 playlist
        playlist0 = root.find("./playlist[@id='playlist0']")
        assert playlist0 is not None
        entries = playlist0.findall("entry")
        assert len(entries) >= 3, f"Expected at least 3 entries on V1, got {len(entries)}"

        # Validate with melt if installed
        if shutil.which("melt"):
            res = subprocess.run(
                ["melt", out_mlt, "-consumer", "null", "terminate_on_pause=1"],
                capture_output=True,
                text=True
            )
            assert res.returncode == 0, f"melt failed with code {res.returncode}:\n{res.stderr}"
            print("  [OK] melt execution succeeded without errors")

    print("  [OK] test_xml_structure_and_melt passed")


def test_overlay_export():
    """Test overlay track (V2), qtblend transition, qimage producer, and alpha fade filters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        clip = os.path.join(tmpdir, "clip.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=30",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", clip],
            capture_output=True, check=True
        )
        overlay_img = os.path.join(tmpdir, "logo.png")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:size=100x100:duration=1",
             "-frames:v", "1", overlay_img],
            capture_output=True, check=True
        )

        out_mlt = os.path.join(tmpdir, "test_overlay.mlt")
        overlays = [{
            "image": overlay_img,
            "start": 1.0,
            "end": 3.0,
            "fade_in": 0.5,
            "fade_out": 0.5
        }]

        export_to_shotcut(
            videos=[clip],
            video_durations=[4.0],
            skip_list=[],
            out_mlt_path=out_mlt,
            width=320,
            height=240,
            fps_num=30,
            fps_den=1,
            title="Overlay Test",
            overlays=overlays
        )

        tree = ET.parse(out_mlt)
        root = tree.getroot()

        # Check V2 playlist and overlay producer
        pl1 = root.find("./playlist[@id='playlist1']")
        assert pl1 is not None, "V2 playlist not found"

        ovl_prod = root.find("./producer[@id='producer_ovl_0']")
        assert ovl_prod is not None, "Overlay producer not found"
        mlt_service = ovl_prod.find("./property[@name='mlt_service']")
        assert mlt_service is not None and mlt_service.text == "qimage", f"Expected qimage, got {mlt_service.text if mlt_service else None}"

        # Check filters
        filters = ovl_prod.findall("filter")
        assert len(filters) == 2, f"Expected 2 fade filters, got {len(filters)}"
        alpha_prop = filters[0].find("./property[@name='alpha']")
        assert alpha_prop is not None and "00:00:00.000=0" in alpha_prop.text

        # Check transitions (qtblend between track 1 and 2)
        trans_v2 = root.find(".//tractor[@id='tractor0']/transition[@id='transition_v2_v']")
        assert trans_v2 is not None, "transition_v2_v not found"
        a_track = trans_v2.find("./property[@name='a_track']").text
        b_track = trans_v2.find("./property[@name='b_track']").text
        service = trans_v2.find("./property[@name='mlt_service']").text
        assert (a_track, b_track, service) == ("1", "2", "qtblend"), f"Unexpected transition: a={a_track}, b={b_track}, service={service}"

        if shutil.which("melt"):
            res = subprocess.run(
                ["melt", out_mlt, "-consumer", "null", "terminate_on_pause=1"],
                capture_output=True,
                text=True
            )
            assert res.returncode == 0, f"melt failed with overlay project: {res.stderr}"
            print("  [OK] melt execution with overlay succeeded")

    print("  [OK] test_overlay_export passed")


if __name__ == "__main__":
    print("Running Shotcut export checks...")
    test_stuecke_calculation()
    test_resolve_partials()
    test_xml_structure_and_melt()
    test_overlay_export()
    print("All Shotcut export checks passed successfully!")

