"""Data models, constants, and pure helper functions.

This module has **no** dependencies on other project modules.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOLS_FOR_CODECS: Dict[str, List[str]] = {
    "jpeg": ["ffmpeg", "cjpeg"],
    "jpegxl": ["cjxl"],
    "heic": ["heif-enc"],
    "avif": ["avifenc"],
}

ALL_CODECS = list(TOOLS_FOR_CODECS.keys())


# ---------------------------------------------------------------------------
# Image classification enum
# ---------------------------------------------------------------------------

class ImageType(Enum):
    """Classification of an image based on filename suffixes."""
    SDR_COLOR = auto()
    SDR_BW = auto()
    HDR_COLOR = auto()
    HDR_BW = auto()

    @property
    def is_hdr(self) -> bool:
        return self in (ImageType.HDR_COLOR, ImageType.HDR_BW)

    @property
    def is_bw(self) -> bool:
        return self in (ImageType.SDR_BW, ImageType.HDR_BW)


# ---------------------------------------------------------------------------
# Application settings
# ---------------------------------------------------------------------------

@dataclass
class AppSettings:
    """Persistent application configuration."""

    rename_enabled: bool = True
    prefix: str = "Image_"
    counter_enabled: bool = True
    start_counter: int = 1
    zero_fill_enabled: bool = True
    zero_fill_mode: str = "auto"  # "auto" | "manual"
    zero_fill_digits: int = 1
    sdr_enabled: bool = True
    hdr_enabled: bool = True
    last_input_dir: Optional[str] = None
    codec_enabled: Dict[str, bool] = field(
        default_factory=lambda: {c: True for c in ALL_CODECS}
    )
    codec_quality: Dict[str, int] = field(
        default_factory=lambda: {"jpeg": 95, "jpegxl": 99, "heic": 99, "avif": 99}
    )

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_SETTINGS = AppSettings()


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def clamp_int(
    value,
    default: int,
    min_value: int,
    max_value: int,
    name: str,
    logger: Optional[logging.Logger],
) -> int:
    """Parse *value* as ``int``, clamp to *[min_value, max_value]*.

    Falls back to *default* when *value* cannot be parsed.
    """
    try:
        parsed = int(value)
    except Exception:
        if logger:
            logger.warning("%s invalid; using default %s", name, default)
        return default
    if parsed < min_value or parsed > max_value:
        if logger:
            logger.warning(
                "%s out of range; clamping to %s-%s", name, min_value, max_value
            )
        parsed = max(min_value, min(parsed, max_value))
    return parsed


def compute_zero_fill(
    start: int,
    count: int,
    mode: str,
    manual_digits: int,
    logger: Optional[logging.Logger],
) -> int:
    """Return the number of digits to use for zero-filled counters."""
    if count <= 0:
        return manual_digits if mode == "manual" else 1
    auto_digits = len(str(start + count - 1))
    if mode == "manual":
        if manual_digits < auto_digits and logger:
            logger.warning(
                "Manual zerofill too small (%s); using auto %s",
                manual_digits,
                auto_digits,
            )
        return max(manual_digits, auto_digits)
    return auto_digits
