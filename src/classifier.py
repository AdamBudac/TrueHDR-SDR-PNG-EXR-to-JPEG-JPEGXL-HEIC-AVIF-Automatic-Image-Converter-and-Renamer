"""Image classifier – determines image type (SDR/HDR, Color/BW) from filenames.

Detection is **case-insensitive** for both ``_HDR`` and ``_BW`` / ``-2`` suffixes.

Examples
--------
>>> normalize_base("photo.png")          # ("photo",  ImageType.SDR_COLOR)
>>> normalize_base("photo-2.png")        # ("photo",  ImageType.SDR_BW)
>>> normalize_base("photo_BW.png")       # ("photo",  ImageType.SDR_BW)
>>> normalize_base("photo_HDR.png")      # ("photo",  ImageType.HDR_COLOR)
>>> normalize_base("photo-2_HDR.png")    # ("photo",  ImageType.HDR_BW)
>>> normalize_base("photo_bw_hdr.png")   # ("photo",  ImageType.HDR_BW)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.models import ImageType


# ---------------------------------------------------------------------------
# Regex patterns (compiled once)
# ---------------------------------------------------------------------------

# Matches _HDR at any position (case-insensitive) – we strip it and flag the image
_HDR_RE = re.compile(r"_HDR", re.IGNORECASE)

# Matches BW markers: literal "_BW" or trailing "-2" (case-insensitive)
# The "-2" must be at the very end (after HDR has already been stripped)
_BW_SUFFIX_RE = re.compile(r"_BW$", re.IGNORECASE)
_BW_DASH2_RE = re.compile(r"-2$")

# Trailing metadata that should be stripped (parenthesised remarks, en-dash notes)
_TRAILING_META_RE = re.compile(r"(?:\s+–\s*[^()]*|\s*\(\s*[^()]*\s*\))\s*$")


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------

def normalize_base(stem: str) -> Tuple[str, ImageType]:
    """Derive a canonical *base name* and :class:`ImageType` from a file stem.

    The function strips HDR and BW suffixes (case-insensitively) and any
    trailing parenthesised or en-dash metadata from the stem.

    Returns
    -------
    (base_name, image_type)
    """
    is_hdr = False
    is_bw = False

    # 1. Detect and remove _HDR (case-insensitive)
    if _HDR_RE.search(stem):
        stem = _HDR_RE.sub("", stem)
        is_hdr = True

    # 2. Detect and remove _BW (case-insensitive) or trailing -2
    if _BW_SUFFIX_RE.search(stem):
        stem = _BW_SUFFIX_RE.sub("", stem)
        is_bw = True
    elif _BW_DASH2_RE.search(stem):
        stem = _BW_DASH2_RE.sub("", stem)
        is_bw = True

    # 3. Strip trailing metadata (parentheses, en-dash remarks)
    while True:
        new_stem = _TRAILING_META_RE.sub("", stem)
        if new_stem == stem:
            break
        stem = new_stem

    # 4. Clean up remaining whitespace / separators at edges
    stem = stem.strip(" _-")

    # 5. Determine ImageType
    if is_hdr and is_bw:
        img_type = ImageType.HDR_BW
    elif is_hdr:
        img_type = ImageType.HDR_COLOR
    elif is_bw:
        img_type = ImageType.SDR_BW
    else:
        img_type = ImageType.SDR_COLOR

    return stem, img_type


# ---------------------------------------------------------------------------
# Grouped classification result
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedImages:
    """Result of classifying a set of image files by type."""

    sdr_color_groups: Dict[str, List[Path]] = field(default_factory=dict)
    sdr_bw_groups: Dict[str, List[Path]] = field(default_factory=dict)
    hdr_color_groups: Dict[str, List[Path]] = field(default_factory=dict)
    hdr_bw_groups: Dict[str, List[Path]] = field(default_factory=dict)
    exr_groups: Dict[str, List[Path]] = field(default_factory=dict)
    jpg_hdr_groups: Dict[str, List[Path]] = field(default_factory=dict)

    @property
    def unique_bases(self) -> List[str]:
        """Sorted union of all base names across every group."""
        all_bases = (
            set(self.sdr_color_groups)
            | set(self.sdr_bw_groups)
            | set(self.hdr_color_groups)
            | set(self.hdr_bw_groups)
        )
        return sorted(all_bases, key=str.lower)

    @property
    def sdr_base_count(self) -> int:
        """Number of unique base names that have at least one SDR file."""
        return len(set(self.sdr_color_groups) | set(self.sdr_bw_groups))

    @property
    def total_png_count(self) -> int:
        """Total number of PNG files across all groups (SDR + HDR, color + BW)."""
        return (
            sum(len(v) for v in self.sdr_color_groups.values())
            + sum(len(v) for v in self.sdr_bw_groups.values())
            + sum(len(v) for v in self.hdr_color_groups.values())
            + sum(len(v) for v in self.hdr_bw_groups.values())
        )


def classify_files(
    png_files: List[Path],
    exr_files: List[Path],
    jpg_hdr_files: Optional[List[Path]] = None,
) -> ClassifiedImages:
    """Classify *png_files*, *exr_files*, and *jpg_hdr_files* into groups by base name and type."""
    result = ClassifiedImages()

    for p in png_files:
        base, img_type = normalize_base(p.stem)
        if img_type == ImageType.SDR_COLOR:
            result.sdr_color_groups.setdefault(base, []).append(p)
        elif img_type == ImageType.SDR_BW:
            result.sdr_bw_groups.setdefault(base, []).append(p)
        elif img_type == ImageType.HDR_COLOR:
            result.hdr_color_groups.setdefault(base, []).append(p)
        elif img_type == ImageType.HDR_BW:
            result.hdr_bw_groups.setdefault(base, []).append(p)

    for e in exr_files:
        # EXR files are always HDR; strip _HDR if present before grouping
        raw_stem = _HDR_RE.sub("", e.stem)
        base, _ = normalize_base(raw_stem)
        result.exr_groups.setdefault(base, []).append(e)

    for j in (jpg_hdr_files or []):
        # JPG HDR files are always HDR; strip _HDR if present before grouping
        raw_stem = _HDR_RE.sub("", j.stem)
        base, _ = normalize_base(raw_stem)
        result.jpg_hdr_groups.setdefault(base, []).append(j)

    return result
