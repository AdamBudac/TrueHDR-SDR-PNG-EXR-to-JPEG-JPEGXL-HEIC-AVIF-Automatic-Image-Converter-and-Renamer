"""Renamer – builds and executes rename plans for classified images."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.models import AppSettings, ImageType, compute_zero_fill
from src.classifier import ClassifiedImages


# ---------------------------------------------------------------------------
# Rename plan data
# ---------------------------------------------------------------------------

@dataclass
class RenamePlan:
    """A single pending rename operation."""

    source: Path
    target: Path
    image_type: ImageType


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------

def build_rename_plan(
    classified: ClassifiedImages,
    settings: AppSettings,
    logger: Optional[logging.Logger],
) -> List[RenamePlan]:
    """Create a list of :class:`RenamePlan` entries for every file that needs renaming.

    If ``settings.rename_enabled`` is ``False`` the returned list is empty
    (files keep their original names).
    """
    if not settings.rename_enabled:
        return []

    unique_bases = classified.unique_bases
    sdr_base_count = classified.sdr_base_count

    # Compute zero-fill width
    if settings.counter_enabled:
        digits = compute_zero_fill(
            settings.start_counter,
            max(sdr_base_count, len(unique_bases)),
            settings.zero_fill_mode,
            settings.zero_fill_digits,
            logger,
        )
    else:
        digits = 1

    # Determine duplicate-suffix width
    max_dup = 0
    for group_dict in (
        classified.sdr_color_groups,
        classified.sdr_bw_groups,
        classified.hdr_color_groups,
        classified.hdr_bw_groups,
    ):
        for files in group_dict.values():
            max_dup = max(max_dup, len(files) - 1)
    dup_digits = max(1, len(str(max_dup))) if max_dup > 0 else 1

    plan: List[RenamePlan] = []

    for idx, base in enumerate(unique_bases, start=settings.start_counter):
        number = str(idx)
        if settings.zero_fill_enabled:
            number = number.zfill(digits)

        # Helper to add files from one group
        def _add_group(
            group_files: List[Path],
            image_type: ImageType,
        ) -> None:
            sorted_files = sorted(group_files, key=lambda p: p.name.lower())
            for dup_idx, file_path in enumerate(sorted_files):
                dup_suffix = (
                    "" if dup_idx == 0
                    else f"_Duplicate{str(dup_idx).zfill(dup_digits)}"
                )
                # Build suffix based on type
                type_suffix = ""
                if image_type.is_bw:
                    type_suffix += "_BW"
                if image_type.is_hdr:
                    type_suffix += "_HDR"

                new_stem = f"{settings.prefix}{number}{type_suffix}{dup_suffix}"
                target = file_path.with_name(f"{new_stem}{file_path.suffix}")
                plan.append(RenamePlan(source=file_path, target=target, image_type=image_type))

        # Process each category for this base name
        _add_group(classified.sdr_color_groups.get(base, []), ImageType.SDR_COLOR)
        _add_group(classified.sdr_bw_groups.get(base, []), ImageType.SDR_BW)
        _add_group(classified.hdr_color_groups.get(base, []), ImageType.HDR_COLOR)
        _add_group(classified.hdr_bw_groups.get(base, []), ImageType.HDR_BW)

    return plan


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------

def execute_rename_plan(
    plan: List[RenamePlan],
    rename_log_path: Path,
    logger: logging.Logger,
) -> List[RenamePlan]:
    """Execute all renames in *plan*, writing a mapping log.

    Returns the plan with ``target`` paths updated to reflect what actually
    happened (skipped entries are removed).
    """
    executed: List[RenamePlan] = []
    for entry in plan:
        if entry.target.exists():
            logger.warning(
                "Target exists, skipping: %s -> %s",
                entry.source.name, entry.target.name,
            )
            continue
        entry.source.rename(entry.target)
        _log_rename(entry.source, entry.target, rename_log_path, logger)
        executed.append(entry)
    return executed


def _log_rename(
    src: Path, dst: Path, rename_log_path: Path, logger: logging.Logger
) -> None:
    """Append a single rename record to the rename log."""
    try:
        with rename_log_path.open("a", encoding="utf-8") as f:
            f.write(f"{src.name} -> {dst.name}\n")
    except Exception as exc:
        logger.warning("Failed to log rename: %s -> %s (%s)", src, dst, exc)
