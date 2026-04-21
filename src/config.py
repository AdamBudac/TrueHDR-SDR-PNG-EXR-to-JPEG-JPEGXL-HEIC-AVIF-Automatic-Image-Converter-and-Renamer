"""Configuration management – paths, load/save settings, tool detection, logging setup."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

from src.models import (
    ALL_CODECS,
    AppSettings,
    DEFAULT_SETTINGS,
    TOOLS_FOR_CODECS,
    clamp_int,
)


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def is_frozen() -> bool:
    """Return ``True`` when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def config_root() -> Path:
    """Return the platform-specific directory for application config files."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "TrueHDRConverter"


def config_file() -> Path:
    """Return the path to the default settings JSON file.
    
    Prioritises a local 'data/settings.json' (portable mode) if it exists
    in the current working directory or next to the executable.
    """
    portable_cwd = Path.cwd() / "data" / "settings.json"
    if portable_cwd.exists():
        return portable_cwd
        
    if is_frozen():
        portable_exe = Path(sys.executable).parent / "data" / "settings.json"
        if portable_exe.exists():
            return portable_exe

    return config_root() / "settings.json"


def ensure_config_dir(path: Path) -> None:
    """Create the parent directory for the given config path."""
    path.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Settings serialisation
# ---------------------------------------------------------------------------

def settings_from_dict(data: Dict, logger: Optional[logging.Logger]) -> AppSettings:
    """Parse a raw ``dict`` (e.g. from JSON) into a validated :class:`AppSettings`."""
    settings = AppSettings()
    settings.rename_enabled = bool(data.get("rename_enabled", settings.rename_enabled))
    settings.prefix = str(data.get("prefix", settings.prefix)) or settings.prefix
    settings.counter_enabled = bool(data.get("counter_enabled", settings.counter_enabled))
    settings.start_counter = clamp_int(
        data.get("start_counter", settings.start_counter),
        settings.start_counter, 0, 999999, "start_counter", logger,
    )
    settings.zero_fill_enabled = bool(data.get("zero_fill_enabled", settings.zero_fill_enabled))
    settings.zero_fill_mode = (
        "manual"
        if str(data.get("zero_fill_mode", settings.zero_fill_mode)).lower() == "manual"
        else "auto"
    )
    settings.zero_fill_digits = clamp_int(
        data.get("zero_fill_digits", settings.zero_fill_digits),
        settings.zero_fill_digits, 1, 9, "zero_fill_digits", logger,
    )
    settings.sdr_enabled = bool(data.get("sdr_enabled", settings.sdr_enabled))
    settings.hdr_enabled = bool(data.get("hdr_enabled", settings.hdr_enabled))
    settings.last_input_dir = data.get("last_input_dir", settings.last_input_dir)

    # Codec flags
    codec_enabled = data.get("codec_enabled", settings.codec_enabled)
    settings.codec_enabled = {
        c: bool(codec_enabled.get(c, settings.codec_enabled[c])) for c in ALL_CODECS
    }

    # Codec quality
    codec_quality = data.get("codec_quality", settings.codec_quality)
    settings.codec_quality = {
        c: clamp_int(
            codec_quality.get(c, settings.codec_quality[c]),
            settings.codec_quality[c], 0, 100, f"{c}_quality", logger,
        )
        for c in ALL_CODECS
    }
    return settings


def load_settings_from_file(
    path: Path, logger: Optional[logging.Logger]
) -> AppSettings:
    """Read *path* as JSON and return a validated :class:`AppSettings`."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return settings_from_dict(data, logger)
    except Exception as exc:
        if logger:
            logger.warning("Failed to load settings from %s: %s", path, exc)
        return DEFAULT_SETTINGS


def save_settings_to_file(settings: AppSettings, path: Path) -> None:
    """Write *settings* to *path* as pretty-printed JSON."""
    ensure_config_dir(path)
    with path.open("w", encoding="utf-8") as f:
        json.dump(settings.to_dict(), f, indent=4)


# ---------------------------------------------------------------------------
# External tool detection
# ---------------------------------------------------------------------------

def detect_tools() -> Dict[str, bool]:
    """Check which external CLI tools are available on ``PATH``."""
    availability: Dict[str, bool] = {}
    for tool in {t for tools in TOOLS_FOR_CODECS.values() for t in tools}:
        availability[tool] = shutil.which(tool) is not None
    return availability


def required_tools_missing_for_codec(
    codec: str, tool_map: Dict[str, bool]
) -> List[str]:
    """Return the list of tools required by *codec* that are **not** available."""
    required = TOOLS_FOR_CODECS.get(codec, [])
    return [tool for tool in required if not tool_map.get(tool, False)]


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def attach_file_logger(logger: logging.Logger, log_path: Path) -> None:
    """Replace any existing :class:`FileHandler` on *logger* with one writing to *log_path*."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
