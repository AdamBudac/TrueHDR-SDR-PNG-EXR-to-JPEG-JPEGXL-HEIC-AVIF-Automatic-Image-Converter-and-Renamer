import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import AppSettings, ImageType, compute_zero_fill  # noqa: E402
from src.config import settings_from_dict  # noqa: E402
from src.classifier import normalize_base, classify_files  # noqa: E402
from src.worker import copy_source_files  # noqa: E402


# ---------------------------------------------------------------------------
# Existing tests (updated imports)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# New tests – classifier (BW / HDR detection)
# ---------------------------------------------------------------------------

def test_normalize_base_sdr_color():
    base, img_type = normalize_base("photo")
    assert base == "photo"
    assert img_type == ImageType.SDR_COLOR


def test_normalize_base_sdr_bw_dash2():
    base, img_type = normalize_base("photo-2")
    assert base == "photo"
    assert img_type == ImageType.SDR_BW


def test_normalize_base_sdr_bw_suffix():
    base, img_type = normalize_base("photo_BW")
    assert base == "photo"
    assert img_type == ImageType.SDR_BW


def test_normalize_base_sdr_bw_suffix_lowercase():
    base, img_type = normalize_base("photo_bw")
    assert base == "photo"
    assert img_type == ImageType.SDR_BW


def test_normalize_base_hdr_color():
    base, img_type = normalize_base("photo_HDR")
    assert base == "photo"
    assert img_type == ImageType.HDR_COLOR


def test_normalize_base_hdr_color_lowercase():
    base, img_type = normalize_base("photo_hdr")
    assert base == "photo"
    assert img_type == ImageType.HDR_COLOR


def test_normalize_base_hdr_bw_dash2():
    base, img_type = normalize_base("photo-2_HDR")
    assert base == "photo"
    assert img_type == ImageType.HDR_BW


def test_normalize_base_hdr_bw_suffix():
    base, img_type = normalize_base("photo_BW_HDR")
    assert base == "photo"
    assert img_type == ImageType.HDR_BW


def test_normalize_base_hdr_bw_all_lowercase():
    base, img_type = normalize_base("photo_bw_hdr")
    assert base == "photo"
    assert img_type == ImageType.HDR_BW


def test_normalize_base_hdr_mixed_case():
    base, img_type = normalize_base("photo_Bw_Hdr")
    assert base == "photo"
    assert img_type == ImageType.HDR_BW


def test_classify_files_groups():
    """Verify that classify_files sorts files into the right groups."""
    from pathlib import PurePosixPath as P
    # We use PurePosixPath-like Path objects; classify only reads .stem
    files = [
        Path("photo.png"),
        Path("photo-2.png"),
        Path("photo_BW.png"),
        Path("photo_HDR.png"),
        Path("photo-2_HDR.png"),
        Path("photo_bw_hdr.png"),
    ]
    exr = [Path("photo_HDR.exr")]

    result = classify_files(files, exr)

    assert "photo" in result.sdr_color_groups
    assert "photo" in result.sdr_bw_groups
    assert "photo" in result.hdr_color_groups
    assert "photo" in result.hdr_bw_groups
    assert len(result.sdr_color_groups["photo"]) == 1
    assert len(result.sdr_bw_groups["photo"]) == 2   # -2 and _BW
    assert len(result.hdr_color_groups["photo"]) == 1
    assert len(result.hdr_bw_groups["photo"]) == 2   # -2_HDR and _bw_hdr
