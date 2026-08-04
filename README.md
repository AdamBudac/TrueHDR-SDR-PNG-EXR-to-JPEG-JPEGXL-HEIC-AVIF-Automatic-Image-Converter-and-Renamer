# TrueHDR/SDR PNG/EXR to JPEG/JPEG XL/HEIC/AVIF Automatic Image Converter and Renamer

Slovenský návod tu: [README-SK.md](README-SK.md)

## Overview

GUI and CLI application for converting, renaming, and sorting input PNG/EXR/JPG HDR images in SDR and HDR formats into JPEG, JPEG XL, HEIC, and AVIF codecs.

## Features

- Renaming with prefix, numbering, auto/manual zerofill; HDR gets the `_HDR` suffix, BW gets `_BW`, copies get `_DuplicateXX`
- Separate SDR/HDR processing; supports Color and Black & White (BW) variants
- BW detection via `_BW` suffix or `-2` suffix (case-insensitive)
- Detects availability of tools (`cjpeg`, `cjxl`, `heif-enc`, `avifenc`) and auto-disables missing codec checkboxes
- Retries a failed external command once (two attempts total), then continues with the next independent codec and image if the command still fails
- Stop button to cancel processing mid-run
- Full CLI interface with argparse for automation / scripting
- Final modal **Processing summary** dialog with processed, successful, partial, failed, skipped, and retry counters
- Full activity log in `output/logging.log`; rename map in `output/rename.log` (`old.ext -> new.ext`); definitive failures in `output/errors.log`
- HDR JPEG/JPG files (with `_HDR` suffix) are copied and renamed alongside their HDR PNG counterparts (not converted, as they cannot be suitably re-encoded)
- Saves settings to `%APPDATA%`

## Project Structure

```
src/
├── main.py          – Entry point (GUI or CLI via --cli flag)
├── cli.py           – argparse CLI interface
├── gui.py           – PySide6 GUI (MainWindow)
├── summary_dialog.py – Modal final processing summary
├── styles.qss       – Qt stylesheet
├── models.py        – AppSettings dataclass, ImageType enum, constants
├── results.py       – Per-command, per-image, and final result models
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
  - `cjpeg` – from `libjpeg-turbo` for direct SDR PNG-to-JPEG export
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
- **Processing**: run conversion, shows progress and status; after completion, a separate modal **Processing summary** window shows the final counters and outcome
- **Stop**: cancel processing mid-run

#### Processing summary outcomes

The main window remains unchanged and open.  When a run ends, a separate modal
**Processing summary** window appears above it with image, output, command,
retry, failure, and dependency-skip counters. For a cancelled run it also shows
the cancellation state and the number of images not processed.

| Outcome | Meaning |
| ------- | ------- |
| **Processing completed** | Every requested output was created on its first attempt |
| **Processing completed after retries** | At least one command failed initially but succeeded on its second attempt |
| **Processing completed with errors** | The run reached the end, but one or more requested outputs failed definitively or had to be skipped |
| **Processing cancelled** | The user pressed **Stop**; completed work and the number of images not processed are shown |
| **Processing failed** | A fatal pipeline-level error stopped the run; see `logging.log` |

### CLI mode

```bash
python src/main.py --cli --input ./photos
python src/main.py --cli --input ./photos --prefix "Vacation_" --quality-jpeg 90
python src/main.py --cli --input ./photos --settings settings.json --overwrite
python src/main.py --cli --help
```

CLI exit codes:

| Code | Meaning |
| ---- | ------- |
| `0` | Processing completed successfully, including commands recovered by retry |
| `1` | The input directory does not exist, or the output directory is not empty and `--overwrite` was not supplied |
| `2` | Invalid CLI arguments, or a fatal pipeline error stopped processing |
| `3` | Processing completed, but one or more per-image or per-codec operations failed definitively |

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
| `photo_HDR.jpg`                       | HDR Color (JPG)         |
| `photo-2_HDR.jpg`, `photo_BW_HDR.jpg` | HDR Black & White (JPG) |

EXR and JPG/JPEG HDR files are not converted — they are only copied and renamed to match their HDR PNG counterparts. Non-HDR JPEG files in the input directory are ignored.

## Behavior

- On start, the app looks for settings in `data/settings.json` (portable mode). If not found, it loads from `%APPDATA%/TrueHDRConverter/settings.json` (falls back to defaults).
- After selecting a working directory, it creates `output/`, copies all `.png`, `.exr`, and HDR `.jpg`/`.jpeg` files from the root of that directory into `output/`, and works only there
- Every failed external command is retried once with the same arguments, for a maximum of two attempts. If the second attempt also fails, the failed output is skipped and processing continues with the next independent codec and image.
- Retry is command-scoped, not image-scoped: outputs already completed for the image are not encoded again. A partial temporary output is removed before retry, and temporary filenames are unique per image run.
- SDR 8-bit PNG files are encoded directly to JPEG by `cjpeg` from `libjpeg-turbo`, without an intermediate image format or another conversion tool.
- User cancellation is never retried or recorded as a conversion failure.
- After a GUI run finishes, a separate modal **Processing summary** window reports image, output, command, retry, failure, and dependency-skip totals. A cancelled run additionally shows its cancellation state and the number of images not processed.
- An overwrite dialog appears if `output/` is not empty
- Pressing **Stop** immediately terminates any running conversion processes (aggressive cancellation)

## Log Files

All three logs are created fresh in `output/` for every run:

| File | Contents |
| ---- | -------- |
| `logging.log` | Full chronological activity log, including every command attempt, retry, warning, and final summary |
| `rename.log` | Successful renames in the form `old.ext -> new.ext` |
| `errors.log` | Only definitive command or image-operation failures; it remains empty after a clean or fully recovered run |

Each definitive command failure is stored as one detailed block containing the
image, codec, stage, copy/paste-friendly command, both attempts, return code,
captured `stdout`/`stderr`, final Python traceback, and any dependent step that
was skipped.  A first-attempt error that succeeds on retry remains only in
`logging.log` and does not pollute `errors.log`.

## Tests

The automated test suite contains:

- `tests/unit_tests.py` – classification, settings validation, file discovery, and zero-fill helpers
- `tests/integration_test.py` – end-to-end copy, classification, rename, and worker flow with mocked converters
- `tests/test_retry_processing.py` – retry, partial-output cleanup, dependency skip, cancellation, `errors.log`, progress, and result counters
- `tests/test_summary_dialog.py` – all summary outcomes and opening the separate modal result window

Run the complete suite:

```bash
python -m pytest tests/unit_tests.py tests/integration_test.py tests/test_retry_processing.py tests/test_summary_dialog.py -v
```

_Note: You do not need any external tools in your PATH to run the tests successfully._

## References

- [libjpeg-turbo](https://github.com/libjpeg-turbo/libjpeg-turbo) v3.2.0
- [libjxl](https://github.com/libjxl/libjxl) v0.12.0
- [libheif](https://github.com/strukturag/libheif) v1.20.2
- [libavif](https://github.com/AOMediaCodec/libavif) v1.4.2

_Note: The application should work fine with newer versions of these libraries as well._

## License

Free
