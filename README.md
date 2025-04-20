# VGSync

VGSync is a Python-based desktop application designed to synchronize GPX data with video footage. It uses `mpv` for high-precision video playback and `ffmpeg` for media processing.

- Version: see Releases
- Platform: Windows 64-bit only
- License: GNU General Public License v3.0 or later (GPL-3.0-or-later)

---

## Requirements

- Python 3.10.9 (64-bit) / Python 3.12.0 (64-bit)
- `mpv` binary (must be placed in `mpv/`)
- `ffmpeg` binary (must be placed in `ffmpeg/`)

> Binaries are **not included in the Git repository** due to size limitations.  
> You must download and extract them manually from the GitHub [Releases](https://github.com/ridewithoutstomach/VGSync/releases).

---

## Installation

We strongly recommend using a Python virtual environment:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 🔧 Install External Binaries

Download the following ZIP files from the latest [VGSync Release](https://github.com/ridewithoutstomach/VGSync/releases/tag/v3.27):

- [ffmpeg.zip](https://github.com/ridewithoutstomach/VGSync/releases/download/binaries-ffmpeg-mpv-v1/ffmpeg.zip) → extract into: `ffmpeg/`
- [mpv.zip](https://github.com/ridewithoutstomach/VGSync/releases/download/binaries-ffmpeg-mpv-v1/mpv.zip) → extract into: `mpv/`


The folders `ffmpeg/` and `mpv/` contain `VGSync_ffmpeg.txt` and `VGSync_mpv.txt` as guidance.

---

## Running the Application

```bash
python VGSync.py
```

## Pre-Built Windows Executable

If you prefer not to install Python or deal with dependencies manually, you can use the **pre-built Windows binary**:

1. Download the ZIP file (`VGSync_3.27_Win_x64.zip` or similarly named `VGSync_[VERSION]_Win_x64.zip`) from the [GitHub Releases page](https://github.com/ridewithoutstomach/VGSync/releases).
2. Extract the ZIP file into any folder of your choice.
3. Double-click `VGSync.exe` to run the application.
---

## Building the Windows Executable

```bash
python build_with_pyinstaller.py
```

The resulting `.exe` file will be located at:

```
dist/VGSync_3.27/VGSync.exe
```

---

## Third-Party Components

This project includes and relies on the following third-party components:

### FFmpeg

- Version: 7.1-full_build
- License: GPLv3
- Website: https://ffmpeg.org
- Binaries provided in: `ffmpeg/`
- Original source code included in: `third-party-src/FFmpeg-7.1-source.zip`
- Release notes are included in the source archive

### mpv

- Version: 0.40.0
- License: LGPLv2.1+
- Website: https://mpv.io
- Binaries provided in: `mpv/`
- Original source code included in: `third-party-src/mpv-0.40.0-source.zip`
- Release notes are included in the source archive

All third-party components are redistributed in accordance with their respective licenses. The complete and unmodified source code is included in the `third-party-src/` directory and will be retained and made available for at least three (3) years in accordance with GPL and LGPL requirements.

---

## License

This project is licensed under the GNU General Public License v3.0 or later.

You are free to:

- Use, copy, and distribute this software
- Study and modify the source code
- Redistribute modified versions under the same license

The full text of the license is included in the file `LICENSE`.

This distribution includes the full source code of VGSync, along with all required third-party binaries and their sources, in compliance with GPL requirements.

---

## Contact

For questions, suggestions, or contributions, please open an issue or pull request on GitHub.
