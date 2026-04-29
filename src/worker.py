"""Processing worker – runs the full pipeline on a background QThread.

Pipeline steps:
1. Copy source files into ``output/``
2. Classify (SDR/HDR, Color/BW)
3. Rename
4. Convert

Supports cooperative cancellation via :meth:`request_stop`.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtCore import QThread, Signal

from src.models import AppSettings, ImageType
from src.config import attach_file_logger
from src.classifier import classify_files
from src.renamer import build_rename_plan, execute_rename_plan, RenamePlan
from src.converter import convert_sdr, convert_hdr, ProcessRunner


# ---------------------------------------------------------------------------
# Cancellation exception
# ---------------------------------------------------------------------------

class CancelledException(Exception):
    """Raised when the user requests to stop processing."""


# ---------------------------------------------------------------------------
# File-copy helper
# ---------------------------------------------------------------------------

# Regex to detect _HDR in a filename stem (case-insensitive)
_HDR_DETECT_RE = __import__("re").compile(r"_HDR", __import__("re").IGNORECASE)


def copy_source_files(
    src_dir: Path, output_dir: Path, logger: logging.Logger
) -> Tuple[List[Path], List[Path], List[Path]]:
    """Copy ``.png``, ``.exr``, and HDR ``.jpg``/``.jpeg`` files from *src_dir* into *output_dir*.

    Returns ``(png_files, exr_files, jpg_hdr_files)`` — paths inside *output_dir*.
    Only ``.jpg``/``.jpeg`` files whose stem contains ``_HDR`` (case-insensitive)
    are treated as HDR sources; other JPEGs are ignored.
    """
    png_files: List[Path] = []
    exr_files: List[Path] = []
    jpg_hdr_files: List[Path] = []
    for item in src_dir.iterdir():
        if not item.is_file():
            continue
        ext = item.suffix.lower()
        if ext in {".png", ".exr"}:
            dest = output_dir / item.name
            shutil.copy2(item, dest)
            if ext == ".png":
                png_files.append(dest)
            else:
                exr_files.append(dest)
        elif ext in {".jpg", ".jpeg"} and _HDR_DETECT_RE.search(item.stem):
            dest = output_dir / item.name
            shutil.copy2(item, dest)
            jpg_hdr_files.append(dest)
    logger.info(
        "Copied %s PNG, %s EXR and %s JPG HDR into %s",
        len(png_files), len(exr_files), len(jpg_hdr_files), output_dir,
    )
    return png_files, exr_files, jpg_hdr_files


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class ProcessingWorker(QThread):
    """Background thread that runs the full conversion pipeline."""

    progress = Signal(int, int)   # (current, total)
    status = Signal(str, str)     # (message, level)
    finished = Signal(bool)       # success?

    def __init__(
        self,
        input_dir: Path,
        settings: AppSettings,
        tool_map: Dict[str, bool],
        logger: logging.Logger,
    ):
        super().__init__()
        self.input_dir = input_dir
        self.settings = settings
        self.tool_map = tool_map
        self.logger = logger
        self._cancelled = False
        self.runner = ProcessRunner()

    # -- public API ----------------------------------------------------------

    def request_stop(self) -> None:
        """Request aggressive cancellation."""
        self._cancelled = True
        self.runner.cancel()

    # -- QThread entry -------------------------------------------------------

    def run(self) -> None:
        try:
            self.process()
            self.finished.emit(True)
        except (CancelledException, InterruptedError):
            self.logger.info("Processing cancelled by user")
            self.status.emit("Processing cancelled", "warning")
            self.finished.emit(False)
        except Exception as exc:
            self.logger.exception("Processing failed: %s", exc)
            self.status.emit("Error – check logging.log", "error")
            self.finished.emit(False)

    # -- pipeline ------------------------------------------------------------

    def _check_cancelled(self) -> None:
        if self._cancelled:
            raise CancelledException()

    def emit_status(self, message: str, level: str = "info") -> None:
        self.status.emit(message, level)

    def process(self) -> None:  # noqa: C901 – sequential pipeline, intentionally long
        if not self.input_dir or not self.input_dir.exists():
            raise FileNotFoundError("Input directory not selected")

        output_dir = self.input_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "logging.log"
        rename_log_path = output_dir / "rename.log"
        attach_file_logger(self.logger, log_path)
        rename_log_path.write_text("", encoding="utf-8")

        self._check_cancelled()

        # 1. Copy -----------------------------------------------------------
        png_files, exr_files, jpg_hdr_files = copy_source_files(
            self.input_dir, output_dir, self.logger,
        )
        png_files = sorted(png_files, key=lambda p: p.name.lower())
        exr_files = sorted(exr_files, key=lambda p: p.name.lower())
        jpg_hdr_files = sorted(jpg_hdr_files, key=lambda p: p.name.lower())
        if not png_files:
            self.emit_status("No PNG files found", "warning")
            return

        self._check_cancelled()

        # 2. Classify -------------------------------------------------------
        classified = classify_files(png_files, exr_files, jpg_hdr_files)

        # 3. Rename ---------------------------------------------------------
        plan = build_rename_plan(classified, self.settings, self.logger)
        executed = execute_rename_plan(plan, rename_log_path, self.logger)

        self._check_cancelled()

        # Build a lookup: source path → executed plan entry (so we know the
        # new path and type for each file after rename).
        renamed_map: Dict[Path, RenamePlan] = {e.source: e for e in executed}

        # Also rename matched EXR and JPG HDR files alongside their HDR counterparts
        self._rename_exr_files(classified, executed, output_dir, rename_log_path)
        self._rename_jpg_hdr_files(classified, executed, output_dir, rename_log_path)

        # 4. Convert --------------------------------------------------------
        total = classified.total_png_count
        processed = 0

        # Iterate over all groups in a unified way
        groups_and_types = [
            (classified.sdr_color_groups, ImageType.SDR_COLOR),
            (classified.sdr_bw_groups, ImageType.SDR_BW),
            (classified.hdr_color_groups, ImageType.HDR_COLOR),
            (classified.hdr_bw_groups, ImageType.HDR_BW),
        ]

        for group_dict, img_type in groups_and_types:
            for base, files in group_dict.items():
                for file_path in sorted(files, key=lambda p: p.name.lower()):
                    self._check_cancelled()

                    # Resolve to the renamed path if applicable
                    actual_path = (
                        renamed_map[file_path].target
                        if file_path in renamed_map
                        else file_path
                    )

                    # Decide whether to convert based on settings
                    if img_type.is_hdr and self.settings.hdr_enabled:
                        convert_hdr(actual_path, self.settings, self.tool_map, self.runner, self.logger)
                    elif not img_type.is_hdr and self.settings.sdr_enabled:
                        convert_sdr(actual_path, self.settings, self.tool_map, self.runner, self.logger)

                    processed += 1
                    self.progress.emit(processed, total)

    def _build_hdr_stem_map(
        self, executed: List[RenamePlan]
    ) -> Dict[str, List[str]]:
        """Build mapping: base -> list of new stems for HDR files (ordered)."""
        hdr_new_stems: Dict[str, List[str]] = {}
        for entry in executed:
            if entry.image_type.is_hdr:
                from src.classifier import normalize_base as _nb
                original_base, _ = _nb(entry.source.stem)
                hdr_new_stems.setdefault(original_base, []).append(
                    entry.target.stem
                )
        return hdr_new_stems

    def _rename_companion_files(
        self,
        groups: Dict[str, List[Path]],
        hdr_new_stems: Dict[str, List[str]],
        output_dir: Path,
        rename_log_path: Path,
        file_label: str,
    ) -> None:
        """Rename companion files (EXR or JPG HDR) to match their HDR PNG counterparts."""
        for base, file_list in groups.items():
            new_stems = hdr_new_stems.get(base, [])
            for dup_idx, src in enumerate(
                sorted(file_list, key=lambda p: p.name.lower())
            ):
                if dup_idx >= len(new_stems):
                    break
                dst = output_dir / f"{new_stems[dup_idx]}{src.suffix}"
                if dst.exists():
                    self.logger.warning(
                        "%s target exists, skipping: %s -> %s",
                        file_label, src.name, dst.name,
                    )
                    continue
                try:
                    src.rename(dst)
                    try:
                        with rename_log_path.open("a", encoding="utf-8") as f:
                            f.write(f"{src.name} -> {dst.name}\n")
                    except Exception:
                        pass
                except FileNotFoundError:
                    self.logger.warning(
                        "%s source missing during rename: %s",
                        file_label, src,
                    )

    def _rename_exr_files(
        self,
        classified,
        executed: List[RenamePlan],
        output_dir: Path,
        rename_log_path: Path,
    ) -> None:
        """Rename EXR files to match their HDR PNG counterparts."""
        hdr_new_stems = self._build_hdr_stem_map(executed)
        self._rename_companion_files(
            classified.exr_groups, hdr_new_stems, output_dir, rename_log_path, "EXR",
        )

    def _rename_jpg_hdr_files(
        self,
        classified,
        executed: List[RenamePlan],
        output_dir: Path,
        rename_log_path: Path,
    ) -> None:
        """Rename JPG HDR files to match their HDR PNG counterparts."""
        hdr_new_stems = self._build_hdr_stem_map(executed)
        self._rename_companion_files(
            classified.jpg_hdr_groups, hdr_new_stems, output_dir, rename_log_path, "JPG HDR",
        )
