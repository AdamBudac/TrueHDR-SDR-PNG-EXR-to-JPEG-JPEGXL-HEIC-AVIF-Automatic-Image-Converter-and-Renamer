# TrueHDR/SDR PNG/EXR to JPEG/JPEG XL/HEIC/AVIF Automatic Image Converter and Renamer

Slovenský návod tu: [README-SK.md](README-SK.md)

## Overview

GUI and CLI application for converting, renaming, and sorting input PNG/EXR images in SDR and HDR formats into JPEG, JPEG XL, HEIC, and AVIF codecs.

## Features

- Renaming with prefix, numbering, auto/manual zerofill; HDR gets the `_HDR` suffix, BW gets `_BW`, copies get `_DuplicateXX`
- Separate SDR/HDR processing; supports Color and Black & White (BW) variants
- BW detection via `_BW` suffix or `-2` suffix (case-insensitive)
- Detects availability of tools (`ffmpeg`, `cjpeg`, `cjxl`, `heif-enc`, `avifenc`) and auto-disables missing codec checkboxes
- Stop button to cancel processing mid-run
- Full CLI interface with argparse for automation / scripting
- Logs to `output/logging.log`; rename map in `output/rename.log` (`old.ext -> new.ext`)
- Saves settings to `%APPDATA%`

## Project Structure

```
src/
├── main.py          – Entry point (GUI or CLI via --cli flag)
├── cli.py           – argparse CLI interface
├── gui.py           – PySide6 GUI (MainWindow)
├── styles.qss       – Qt stylesheet
├── models.py        – AppSettings dataclass, ImageType enum, constants
├── config.py        – Load/save settings, config paths, tool detection
├── classifier.py    – Image classification (SDR/HDR, Color/BW)
├── renamer.py       – Rename plan builder and executor
├── converter.py     – Image conversion (external tool wrappers)
└── worker.py        – Background processing thread (QThread)
```

## Requirements

- **Python 3.13**
- **Python packages:**
  - `PySide6==6.11.0`
  - `pytest==9.0.2`
  - `pyinstaller==6.19.0` (EXE build only)
- **External tools in PATH:**
  - `ffmpeg` – image conversion
  - `cjpeg` – from `libjpeg-turbo` for JPEG export
  - `cjxl` – part of `libjxl` for JPEG XL export
  - `heif-enc` – from `libheif` for HEIC export
  - `avifenc` – from `libavif` for AVIF export

## Installation

1. Install [Python 3.13](https://www.python.org/)
2. Install required dependencies:

```bash
pip install -r requirements.txt
```

## Build (PyInstaller)

Use the included build script:

```bash
python tools/build_exe.py
```

This runs PyInstaller with all required flags (`--onefile`, `--noconsole`, `--clean`, `--noconfirm`) and bundles `styles.qss` automatically. Result in `dist/TrueHDRConverter.exe`.

Alternatively, run PyInstaller manually:

```bash
python -m PyInstaller --noconfirm --clean --noconsole --onefile --name TrueHDRConverter --add-data "src/styles.qss;src" src/main.py
```

## Usage

### GUI mode

```bash
python src/main.py
```

Or compiled EXE: `TrueHDRConverter.exe`

GUI workflow:

- **Load/Save settings**: as needed
- **Load images**: pick the directory with images
- **Configure renaming**: name, counter, zerofill auto/manual
- **Select codecs**: JPEG/JPEG XL/HEIC/AVIF codecs and quality per codec
- **Processing**: run conversion, shows progress and status
- **Stop**: cancel processing mid-run

### CLI mode

```bash
python src/main.py --cli --input ./photos
python src/main.py --cli --input ./photos --prefix "Vacation_" --quality-jpeg 90
python src/main.py --cli --input ./photos --settings settings.json --overwrite
python src/main.py --cli --help
```

## Image Classification

Files are classified by their filename suffixes (case-insensitive):

| Suffix pattern                        | Type                    |
| ------------------------------------- | ----------------------- |
| `photo.png`                           | SDR Color               |
| `photo-2.png`, `photo_BW.png`         | SDR Black & White       |
| `photo_HDR.png`                       | HDR Color               |
| `photo-2_HDR.png`, `photo_BW_HDR.png` | HDR Black & White       |
| `photo_HDR.exr`                       | HDR Color (EXR)         |
| `photo-2_HDR.exr`, `photo_BW_HDR.exr` | HDR Black & White (EXR) |

## Behavior

- On start, the app looks for settings in `data/settings.json` (portable mode). If not found, it loads from `%APPDATA%/TrueHDRConverter/settings.json` (falls back to defaults).
- After selecting a working directory, it creates `output/`, copies all `.png` and `.exr` from the root of that directory into `output/`, and works only there
- When renaming, it writes `output/rename.log` line by line as `old.ext -> new.ext`; error/info logs go to `output/logging.log`
- An overwrite dialog appears if `output/` is not empty
- Pressing **Stop** immediately terminates any running conversion processes (aggressive cancellation)

## Tests

The project includes two types of tests, both written for `pytest`:

1. **Unit tests** (`tests/unit_tests.py`)
   - Tests isolated components like `classifier.py` logic, `config.py` clamping, and zero-fill math.
   - Run: `python -m pytest tests/unit_tests.py -v`

2. **Integration test** (`tests/integration_test.py`)
   - Tests the full pipeline end-to-end via `ProcessingWorker`.
   - Uses `unittest.mock` to simulate `ffmpeg` and other tools, so it runs instantly without requiring the actual binaries or real images.
   - Run: `python -m pytest tests/integration_test.py -v`

_Note: You do not need any external tools in your PATH to run the tests successfully._

## References

- [ffmpeg](https://www.ffmpeg.org/) v8.0.1-full
- [libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo) v3.1.3-vc-x64
- [libjxl](https://github.com/libjxl/libjxl) v0.11.1 x64
- [libheif](https://github.com/strukturag/libheif) v1.19.5 x64
- [libavif](https://github.com/AOMediaCodec/libavif) v1.3.0 x64

_Note: The application should work fine with newer versions of these libraries as well._

## License

Free
