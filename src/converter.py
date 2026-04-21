"""Image converter – calls external CLI tools to encode images.

All functions are **stateless**; they receive everything they need as arguments.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional

from src.models import AppSettings, TOOLS_FOR_CODECS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def required_tools_missing(codec: str, tool_map: Dict[str, bool]) -> List[str]:
    """Return the list of tools required by *codec* that are **not** available."""
    required = TOOLS_FOR_CODECS.get(codec, [])
    return [t for t in required if not tool_map.get(t, False)]


class ProcessRunner:
    """Manages execution of subprocesses and allows aggressive cancellation."""

    def __init__(self):
        self._active_process: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Mark as cancelled and kill the currently running process if any."""
        with self._lock:
            self._cancelled = True
            if self._active_process is not None:
                try:
                    self._active_process.kill()
                except Exception:
                    pass

    def run_cmd(self, command: List[str], logger: logging.Logger) -> None:
        """Execute *command* as a subprocess (hidden window on Windows)."""
        with self._lock:
            if self._cancelled:
                raise InterruptedError("Cancelled by user")

        logger.info("Running: %s", " ".join(command))
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )

        with self._lock:
            if self._cancelled:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise InterruptedError("Cancelled by user")
            self._active_process = proc

        stdout, stderr = proc.communicate()

        with self._lock:
            self._active_process = None
            if self._cancelled:
                raise InterruptedError("Cancelled by user")

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, command, stdout, stderr)



# ---------------------------------------------------------------------------
# SDR conversion
# ---------------------------------------------------------------------------

def convert_sdr(
    png_file: Path,
    settings: AppSettings,
    tool_map: Dict[str, bool],
    runner: ProcessRunner,
    logger: logging.Logger,
) -> None:
    """Convert a single SDR PNG into the enabled codec outputs."""
    stem = png_file.with_suffix("")
    temp_base = png_file.with_name("Tempfile")
    temp_base.unlink(missing_ok=True)
    temp_bmp = temp_base.with_suffix(".bmp")
    temp_jpg = temp_base.with_suffix(".jpg")
    temp_jxl = temp_base.with_suffix(".jxl")
    temp_heic = temp_base.with_suffix(".heic")
    temp_avif = temp_base.with_suffix(".avif")
    for f in [temp_bmp, temp_jpg, temp_jxl, temp_heic, temp_avif]:
        f.unlink(missing_ok=True)

    # JPEG (via ffmpeg → BMP → cjpeg)
    if settings.codec_enabled.get("jpeg") and not required_tools_missing("jpeg", tool_map):
        runner.run_cmd(
            ["ffmpeg", "-y", "-i", str(png_file), "-pix_fmt", "rgb24", str(temp_bmp)],
            logger,
        )
        runner.run_cmd(
            [
                "cjpeg", "-quality", str(settings.codec_quality["jpeg"]),
                "-optimize", "-precision", "8",
                "-outfile", str(temp_jpg), str(temp_bmp),
            ],
            logger,
        )
        temp_bmp.unlink(missing_ok=True)
        temp_jpg.rename(stem.with_suffix(".jpg"))

    # JPEG XL
    if settings.codec_enabled.get("jpegxl") and not required_tools_missing("jpegxl", tool_map):
        runner.run_cmd(
            [
                "cjxl", str(png_file), str(temp_jxl),
                "--quality", str(settings.codec_quality["jpegxl"]),
                "--effort", "7", "--brotli_effort", "11",
                "--num_threads", "-1", "--gaborish", "1",
            ],
            logger,
        )
        temp_jxl.rename(stem.with_suffix(".jxl"))

    # HEIC (x265)
    if settings.codec_enabled.get("heic") and not required_tools_missing("heic", tool_map):
        runner.run_cmd(
            [
                "heif-enc",
                "--thumb", "off",
                "--no-alpha", "--no-thumb-alpha",
                "--bit-depth", "8",
                "--quality", str(settings.codec_quality["heic"]),
                "--matrix_coefficients", "6",
                "--colour_primaries", "1",
                "--transfer_characteristic", "13",
                "--full_range_flag", "1",
                "--encoder", "x265",
                "-p", f"quality={settings.codec_quality['heic']}",
                "-p", "preset=slow",
                "-p", "tune=ssim",
                "-p", "complexity=80",
                "-p", "chroma=420",
                "--output", str(temp_heic),
                str(png_file),
            ],
            logger,
        )
        temp_heic.rename(stem.with_suffix(".heic"))

    # AVIF (aom)
    if settings.codec_enabled.get("avif") and not required_tools_missing("avif", tool_map):
        runner.run_cmd(
            [
                "avifenc",
                "--codec", "aom",
                "--speed", "6",
                "--qcolor", str(settings.codec_quality["avif"]),
                "--yuv", "420",
                "--range", "full",
                "--depth", "8",
                "--cicp", "1/13/6",
                "--jobs", "all",
                "--ignore-icc",
                "--advanced", "enable-chroma-deltaq=1",
                str(png_file), str(temp_avif),
            ],
            logger,
        )
        temp_avif.rename(stem.with_suffix(".avif"))


# ---------------------------------------------------------------------------
# HDR conversion
# ---------------------------------------------------------------------------

def convert_hdr(
    png_file: Path,
    settings: AppSettings,
    tool_map: Dict[str, bool],
    runner: ProcessRunner,
    logger: logging.Logger,
) -> None:
    """Convert a single HDR PNG into the enabled codec outputs (no JPEG)."""
    stem = png_file.with_suffix("")
    temp_base = png_file.with_name("Tempfile")
    temp_base.unlink(missing_ok=True)
    temp_jxl = temp_base.with_suffix(".jxl")
    temp_heic = temp_base.with_suffix(".heic")
    temp_avif = temp_base.with_suffix(".avif")
    for f in [temp_jxl, temp_heic, temp_avif]:
        f.unlink(missing_ok=True)

    # JPEG XL (HDR color space)
    if settings.codec_enabled.get("jpegxl") and not required_tools_missing("jpegxl", tool_map):
        runner.run_cmd(
            [
                "cjxl", str(png_file), str(temp_jxl),
                "--quality", str(settings.codec_quality["jpegxl"]),
                "--effort", "7", "--brotli_effort", "11",
                "--num_threads", "-1", "--gaborish", "1",
                "-x", "color_space=RGB_D65_202_Rel_PeQ",
            ],
            logger,
        )
        temp_jxl.rename(stem.with_suffix(".jxl"))

    # HEIC (HDR – 10-bit, BT.2020)
    if settings.codec_enabled.get("heic") and not required_tools_missing("heic", tool_map):
        runner.run_cmd(
            [
                "heif-enc",
                "--thumb", "off",
                "--no-alpha", "--no-thumb-alpha",
                "--bit-depth", "10",
                "--quality", str(settings.codec_quality["heic"]),
                "--matrix_coefficients", "9",
                "--colour_primaries", "9",
                "--transfer_characteristic", "13",
                "--full_range_flag", "1",
                "--encoder", "x265",
                "-p", f"quality={settings.codec_quality['heic']}",
                "-p", "preset=slow",
                "-p", "tune=ssim",
                "-p", "complexity=80",
                "-p", "chroma=420",
                "--output", str(temp_heic),
                str(png_file),
            ],
            logger,
        )
        temp_heic.rename(stem.with_suffix(".heic"))

    # AVIF (HDR – 10-bit, BT.2020/HLG)
    if settings.codec_enabled.get("avif") and not required_tools_missing("avif", tool_map):
        runner.run_cmd(
            [
                "avifenc",
                "--codec", "aom",
                "--speed", "6",
                "--qcolor", str(settings.codec_quality["avif"]),
                "--yuv", "420",
                "--range", "full",
                "--depth", "10",
                "--cicp", "9/16/9",
                "--jobs", "all",
                "--ignore-icc",
                "--advanced", "enable-chroma-deltaq=1",
                str(png_file), str(temp_avif),
            ],
            logger,
        )
        temp_avif.rename(stem.with_suffix(".avif"))
