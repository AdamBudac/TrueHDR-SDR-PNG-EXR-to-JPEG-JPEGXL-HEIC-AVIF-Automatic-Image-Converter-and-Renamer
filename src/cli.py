"""Command-line interface – headless conversion via argparse."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from src.models import AppSettings, ALL_CODECS
from src.config import (
    config_file,
    detect_tools,
    load_settings_from_file,
    save_settings_to_file,
)
from src.worker import ProcessingWorker


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="TrueHDRConverter",
        description="Convert and rename SDR/HDR PNG/EXR images into JPEG, JPEG XL, HEIC, and AVIF.",
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="Path to the directory containing source PNG/EXR images.",
    )
    parser.add_argument(
        "--settings", "-s",
        type=Path,
        default=None,
        help="Path to a settings JSON file.  When omitted the saved / default settings are used.",
    )

    # Rename options
    rename_group = parser.add_argument_group("Renaming")
    rename_group.add_argument("--no-rename", action="store_true", help="Disable renaming.")
    rename_group.add_argument("--prefix", type=str, default=None, help="Filename prefix (default: Image_).")
    rename_group.add_argument("--start-counter", type=int, default=None, help="Starting counter value.")
    rename_group.add_argument("--no-counter", action="store_true", help="Disable counter.")
    rename_group.add_argument("--zerofill-mode", choices=["auto", "manual"], default=None, help="Zerofill mode.")
    rename_group.add_argument("--zerofill-digits", type=int, default=None, help="Manual zerofill width.")

    # Processing scope
    scope_group = parser.add_argument_group("Scope")
    scope_group.add_argument("--no-sdr", action="store_true", help="Skip SDR images.")
    scope_group.add_argument("--no-hdr", action="store_true", help="Skip HDR images.")

    # Codec options
    codec_group = parser.add_argument_group("Codecs")
    codec_group.add_argument(
        "--codecs",
        nargs="+",
        choices=ALL_CODECS,
        default=None,
        help="Codecs to enable (default: all available).  Example: --codecs jpeg jpegxl",
    )
    codec_group.add_argument("--quality-jpeg", type=int, default=None, help="JPEG quality (0-100).")
    codec_group.add_argument("--quality-jpegxl", type=int, default=None, help="JPEG XL quality (0-100).")
    codec_group.add_argument("--quality-heic", type=int, default=None, help="HEIC quality (0-100).")
    codec_group.add_argument("--quality-avif", type=int, default=None, help="AVIF quality (0-100).")

    # Output control
    parser.add_argument(
        "--overwrite", "-y",
        action="store_true",
        help="Overwrite existing output directory without prompting.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print verbose log messages to stdout.",
    )

    return parser


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_cli(argv: list[str] | None = None) -> int:
    """Parse arguments and run the conversion pipeline.  Returns exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # --- Logger ---
    logger = logging.getLogger("converter")
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    # --- Input validation ---
    input_dir: Path = args.input.resolve()
    if not input_dir.is_dir():
        logger.error("Input directory does not exist: %s", input_dir)
        return 1

    # --- Settings ---
    if args.settings:
        settings = load_settings_from_file(args.settings.resolve(), logger)
    else:
        settings = load_settings_from_file(config_file(), logger)

    # Apply CLI overrides
    if args.no_rename:
        settings.rename_enabled = False
    if args.prefix is not None:
        settings.prefix = args.prefix
    if args.no_counter:
        settings.counter_enabled = False
    if args.start_counter is not None:
        settings.start_counter = args.start_counter
    if args.zerofill_mode is not None:
        settings.zero_fill_mode = args.zerofill_mode
    if args.zerofill_digits is not None:
        settings.zero_fill_digits = args.zerofill_digits
    if args.no_sdr:
        settings.sdr_enabled = False
    if args.no_hdr:
        settings.hdr_enabled = False

    if args.codecs is not None:
        settings.codec_enabled = {c: (c in args.codecs) for c in ALL_CODECS}

    for codec in ALL_CODECS:
        q = getattr(args, f"quality_{codec}", None)
        if q is not None:
            settings.codec_quality[codec] = max(0, min(100, q))

    settings.last_input_dir = str(input_dir)

    # --- Output directory ---
    output_dir = input_dir / "output"
    if output_dir.exists() and any(output_dir.iterdir()):
        if args.overwrite:
            shutil.rmtree(output_dir, ignore_errors=True)
        else:
            logger.error(
                "Output directory is not empty: %s  (use --overwrite / -y to proceed)",
                output_dir,
            )
            return 1

    # --- Tool detection ---
    tool_map = detect_tools()
    missing_all = []
    for codec in ALL_CODECS:
        if settings.codec_enabled.get(codec):
            from src.config import required_tools_missing_for_codec
            m = required_tools_missing_for_codec(codec, tool_map)
            if m:
                logger.warning("Disabling %s – missing tools: %s", codec, ", ".join(m))
                settings.codec_enabled[codec] = False
                missing_all.extend(m)

    # --- Run pipeline (synchronous – no QThread needed) ---
    logger.info("Starting conversion for: %s", input_dir)
    worker = ProcessingWorker(input_dir, settings, tool_map, logger)
    try:
        worker.process()
        logger.info("Conversion completed successfully.")
        return 0
    except Exception as exc:
        logger.exception("Conversion failed: %s", exc)
        return 2
