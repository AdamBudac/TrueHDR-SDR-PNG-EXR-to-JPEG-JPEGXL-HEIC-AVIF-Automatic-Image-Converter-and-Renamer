from pathlib import Path
import logging
from unittest.mock import patch

from src.models import AppSettings
from src.config import detect_tools
from src.worker import ProcessingWorker


def fake_convert_sdr(png_file: Path, settings: AppSettings, tool_map: dict, runner, logger: logging.Logger):
    """Mock implementation that just creates dummy output files."""
    stem = png_file.with_suffix("")
    codecs = {"jpeg": ".jpg", "jpegxl": ".jxl", "heic": ".heic", "avif": ".avif"}
    for codec, ext in codecs.items():
        if settings.codec_enabled.get(codec):
            stem.with_suffix(ext).touch()


def fake_convert_hdr(png_file: Path, settings: AppSettings, tool_map: dict, runner, logger: logging.Logger):
    """Mock implementation for HDR that creates dummy output files."""
    stem = png_file.with_suffix("")
    codecs = {"jpegxl": ".jxl", "heic": ".heic", "avif": ".avif"}
    for codec, ext in codecs.items():
        if settings.codec_enabled.get(codec):
            stem.with_suffix(ext).touch()


def test_full_pipeline_integration(tmp_path: Path):
    """
    End-to-end integration test of the ProcessingWorker pipeline.
    It mocks the actual external tool calls (ffmpeg, cjpeg...) to test
    the file discovery, renaming, sorting, and callback logic.
    """
    # 1. Prepare dummy input files
    (tmp_path / "photo_a.png").write_bytes(b"dummy")
    (tmp_path / "photo_b_HDR.png").write_bytes(b"dummy")
    (tmp_path / "photo_b_HDR.exr").write_bytes(b"dummy")
    (tmp_path / "photo_b_HDR.jpg").write_bytes(b"dummy")       # JPG HDR file
    (tmp_path / "unrelated.jpg").write_bytes(b"notHDR")         # non-HDR JPEG – should be ignored
    
    # 2. Setup logger
    logger = logging.getLogger("test-integration")
    logger.addHandler(logging.NullHandler())

    # 3. App Settings configured for renaming
    settings = AppSettings()
    settings.rename_enabled = True
    settings.prefix = "TestImage_"
    settings.start_counter = 1
    settings.zero_fill_mode = "manual"
    settings.zero_fill_digits = 3
    # Enable a few codecs
    settings.codec_enabled = {"jpeg": True, "jpegxl": True, "heic": False, "avif": False}

    # We don't care about actual tools in this mock test, so pretend all are missing 
    # except we bypass the check via our mock anyway.
    tool_map = {}

    # 4. Initialize worker
    worker = ProcessingWorker(tmp_path, settings, tool_map, logger)

    # 5. Patch the expensive / external operations
    with patch("src.worker.convert_sdr", side_effect=fake_convert_sdr), \
         patch("src.worker.convert_hdr", side_effect=fake_convert_hdr):
        
        # Run pipeline
        worker.process()

    # 6. Verify outputs
    output_dir = tmp_path / "output"
    assert output_dir.exists()

    # We expect renamed files based on settings:
    # photo_a.png -> TestImage_001.png -> TestImage_001.jpg, TestImage_001.jxl
    # photo_b_HDR.png -> TestImage_002_HDR.png -> TestImage_002_HDR.jxl (no jpeg for HDR)
    # photo_b_HDR.exr -> TestImage_002_HDR.exr
    # photo_b_HDR.jpg -> TestImage_002_HDR.jpg  (renamed to match HDR PNG)

    assert (output_dir / "TestImage_001.png").exists()
    assert (output_dir / "TestImage_001.jpg").exists()
    assert (output_dir / "TestImage_001.jxl").exists()

    assert (output_dir / "TestImage_002_HDR.png").exists()
    assert (output_dir / "TestImage_002_HDR.jxl").exists()
    
    assert (output_dir / "TestImage_002_HDR.exr").exists()

    # JPG HDR file should be renamed to match the HDR PNG counterpart
    assert (output_dir / "TestImage_002_HDR.jpg").exists()

    # Non-HDR JPEG should NOT be copied
    assert not (output_dir / "unrelated.jpg").exists()

    # Verify rename.log was generated
    rename_log = output_dir / "rename.log"
    assert rename_log.exists()
    log_content = rename_log.read_text("utf-8")
    assert "photo_a.png -> TestImage_001.png" in log_content
    assert "photo_b_HDR.png -> TestImage_002_HDR.png" in log_content
    assert "photo_b_HDR.exr -> TestImage_002_HDR.exr" in log_content
    assert "photo_b_HDR.jpg -> TestImage_002_HDR.jpg" in log_content

