import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from script import AppSettings, compute_zero_fill, copy_source_files, settings_from_dict  # noqa: E402


def test_compute_zero_fill_raises_manual_to_auto():
    logger = logging.getLogger("test_zero_fill")
    logger.addHandler(logging.NullHandler())
    digits = compute_zero_fill(start=8, count=4, mode="manual", manual_digits=1, logger=logger)
    assert digits == 2


def test_settings_from_dict_clamps_quality():
    logger = logging.getLogger("test_settings")
    logger.addHandler(logging.NullHandler())
    settings = settings_from_dict({"codec_quality": {"jpeg": 150}, "start_counter": 0}, logger)
    assert settings.codec_quality["jpeg"] == 100
    assert settings.start_counter == 0


def test_copy_source_files(tmp_path: Path):
    (tmp_path / "image.png").write_bytes(b"fake")
    (tmp_path / "image_HDR.exr").write_bytes(b"fakeexr")
    (tmp_path / "ignore.txt").write_text("x")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    logger = logging.getLogger("test_copy")
    logger.addHandler(logging.NullHandler())

    png_files, exr_files = copy_source_files(tmp_path, output_dir, logger)

    assert len(png_files) == 1
    assert len(exr_files) == 1
    assert (output_dir / "image.png").exists()
    assert (output_dir / "image_HDR.exr").exists()

