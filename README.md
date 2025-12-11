# TrueHDR/SDR PNG/EXR to JPEG/JPEG XL/HEIC/AVIF Automatic Image Converter and Renamer

Slovenský návod tu: [README-SK.md](README-SK.md)

## Overview

GUI application for converting, renaming, and sorting input PNG/EXR images in SDR and HDR formats into JPEG, JPEG XL, HEIC, and AVIF codecs.

## Features

- Renaming with prefix, numbering, auto/manual zerofill; HDR gets the `_HDR` suffix, copies get `_DuplicateXX`
- Separate SDR/HDR processing; EXR pairs to HDR PNG by order
- Detects availability of tools (`ffmpeg`, `cjpeg`, `cjxl`, `heif-enc`, `avifenc`) and auto-disables missing codec checkboxes
- Logs to `output/logging.log`; rename map in `output/rename.log` (`old.ext -> new.ext`)
- Saves settings to `%LOCALAPPDATA%`

## Requirements

- **Python 3.12**
- **Python packages:**
    - `PySide6>=6.6`
    - `pytest>=7.4`
    - `pyinstaller>=6.3` (EXE build only)
- **External tools in PATH:**
    - `ffmpeg` – image conversion
    - `cjpeg` – from `libjpeg-turbo` for JPEG export
    - `cjxl` – part of `libjxl` for JPEG XL export
    - `heif-enc` – from `libheif` for HEIC export
    - `avifenc` – from `libavif` for AVIF export

## Installation

1) Install [Python 3.12](https://www.python.org/)  
2) Install required dependencies:
```bash
pip install -r requirements.txt
```

## Build (PyInstaller)

Windows example:
```bash
python -m PyInstaller --noconfirm --clean --noconsole --onefile --name TrueHDRConverter script.py
```
Result in `dist/TrueHDRConverter.exe`.

## Usage

- CLI: `python script.py`
- Compiled EXE: `TrueHDRConverter.exe`
- GUI:
    - **Load/Save settings**: as needed
    - **Load images**: pick the directory with images
    - **Configure renaming**: name, counter, zerofill auto/manual, HDR/SDR
    - **Select codecs**: JPEG/JPEG XL/HEIC/AVIF codecs and quality per codec
    - **Processing**: run conversion, shows progress and status

## Behavior

- On start, loads settings from `%LOCALAPPDATA%/TrueHDRConverter/settings.json` (falls back to defaults)
- After selecting a working directory, it creates `output/`, copies all `.png` and `.exr` from the root of that directory into `output/`, and works only there
- When renaming, it writes `output/rename.log` line by line as `old.ext -> new.ext`; error/info logs go to `output/logging.log`
- An overwrite dialog appears if `output/` is not empty

## Tests

- See `tests/README.md` for unit/integration instructions

## References

- [ffmpeg](https://www.ffmpeg.org/) v8.0.1-full
- [libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo) v3.1.3-vc-x64
- [libjxl](https://github.com/libjxl/libjxl) v0.11.1 x64
- [libheif](https://github.com/strukturag/libheif) v1.19.5 x64
- [libavif](https://github.com/AOMediaCodec/libavif) v1.3.0 x64

## License

Free
