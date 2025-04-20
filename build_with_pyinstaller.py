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

import os
import sys
import platform
import subprocess
import shutil
import importlib.util

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Pfade zu ffmpeg/mpv (Original-Quellen), die du mit ausliefern möchtest:
LOCAL_FFMPEG = os.path.join(BASE_DIR, "ffmpeg")  # z.B. hier liegt dein ffmpeg/
LOCAL_MPV    = os.path.join(BASE_DIR, "mpv")     # z.B. hier liegt dein mpv/

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

def build_windows():
    app_version = load_app_version()
    print(f"[INFO] APP_VERSION: {app_version}")

    exe_name = "VGSync"
    main_script = "VGSync.py"

    # Icon-Datei prüfen
    icon_file = os.path.join(BASE_DIR, "icon_icon.ico")
    if not os.path.isfile(icon_file):
        print("[WARN] icon_icon.ico wurde nicht gefunden.")
    else:
        print("[INFO] Icon-Datei gefunden:", icon_file)

    print("[INFO] Starte PyInstaller-Build im OneDir-Modus.")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        f"--name={exe_name}",
        f"--icon={icon_file}",  # EXE-Icon
        main_script
    ]
    run_cmd(cmd)

    exe_path = os.path.join("dist", exe_name, f"{exe_name}.exe")
    if not os.path.isfile(exe_path):
        raise RuntimeError(f"{exe_name}.exe fehlt in dist/{exe_name}.")

    target_dirname = f"VGSync_{app_version}"
    target_dir = os.path.join("dist", target_dirname)
    os.makedirs(target_dir, exist_ok=True)

    # Benenne app.exe -> VGSync.exe
    new_exe_path = os.path.join(target_dir, "VGSync.exe")
    shutil.move(exe_path, new_exe_path)

    # Kopiere alle Dateien aus dist/app -> dist/VGSync_<ver>
    app_dist_dir = os.path.join("dist", exe_name)
    for item in os.listdir(app_dist_dir):
        src_item = os.path.join(app_dist_dir, item)
        dst_item = os.path.join(target_dir, item)
        if item.lower() == f"{exe_name}.exe":
            # bereits verschoben
            continue
        if os.path.isdir(src_item):
            shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
        else:
            shutil.copy2(src_item, dst_item)

    # _internal/ anlegen
    internal_dir = os.path.join(target_dir, "_internal")
    os.makedirs(internal_dir, exist_ok=True)

    # ffmpeg/ & mpv/ nach _internal/ kopieren
    copy_tree_all(LOCAL_FFMPEG, os.path.join(internal_dir, "ffmpeg"))
    copy_tree_all(LOCAL_MPV, os.path.join(internal_dir, "mpv"))

    # --- Icon nach _internal/icon ---
    if os.path.isfile(icon_file):
        icon_target_dir = os.path.join(internal_dir, "icon")
        os.makedirs(icon_target_dir, exist_ok=True)
        icon_target_path = os.path.join(icon_target_dir, os.path.basename(icon_file))
        print("[COPY ICON]", icon_file, "->", icon_target_path)
        shutil.copy2(icon_file, icon_target_path)

    # --- doc-Ordner nach _internal/doc ---
    """
    doc_dir = os.path.join(BASE_DIR, "doc")
    if os.path.isdir(doc_dir):
        doc_target_dir = os.path.join(internal_dir, "doc")
        print(f"[INFO] Kopiere doc/ nach {doc_target_dir}")
        copy_tree_all(doc_dir, doc_target_dir)
    else:
        print("[INFO] 'doc' Ordner nicht vorhanden oder kein Ordner. Überspringe Kopie.")
    """
    doc_dir = os.path.join(BASE_DIR, "doc")
    if os.path.isdir(doc_dir):
        doc_target_dir = os.path.join(internal_dir, "doc")
        print(f"[INFO] Kopiere nur PDF-Dateien aus doc/ nach {doc_target_dir}")
        copy_only_pdfs(doc_dir, doc_target_dir)
    else:
        print("[INFO] 'doc' Ordner nicht vorhanden oder kein Ordner. Überspringe Kopie.")

    # Extra-Dateien (LICENSE usw.) kopieren
    for extra_file in ["LICENSE", "README.md", "ol.css", "ol.js", "map_page.html"]:
        src_file = os.path.join(BASE_DIR, extra_file)
        if os.path.isfile(src_file):
            dst_file = os.path.join(target_dir, os.path.basename(src_file))
            print("[COPY]", src_file, "->", dst_file)
            shutil.copy2(src_file, dst_file)

    print(f"[INFO] Windows-Build fertig in: dist/{target_dirname}/")
    print("[INFO] Dort findest du '_internal/ffmpeg' und '_internal/mpv' sowie VGSync.exe.")
    print("[INFO] Das Icon liegt nun in '_internal/icon/'.")
    print("[INFO] Falls vorhanden, doc/ liegt in '_internal/doc/'.")

def main():
    if platform.system() == "Windows":
        build_windows()
    else:
        print("[WARN] Betriebssystem wird nicht unterstützt (aktuell nur Windows).")
        sys.exit(1)

if __name__ == "__main__":
    main()
