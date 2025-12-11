from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QDialog,
    QDialogButtonBox,
    QStyle,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


TOOLS_FOR_CODECS = {
    "jpeg": ["ffmpeg", "cjpeg"],
    "jpegxl": ["cjxl"],
    "heic": ["heif-enc"],
    "avif": ["avifenc"],
}


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def config_root() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "TrueHDRConverter"


def config_file() -> Path:
    return config_root() / "settings.json"


@dataclass
class AppSettings:
    rename_enabled: bool = True
    prefix: str = "Image_"
    counter_enabled: bool = True
    start_counter: int = 1
    zero_fill_enabled: bool = True
    zero_fill_mode: str = "auto" # auto/manual
    zero_fill_digits: int = 1
    sdr_enabled: bool = True
    hdr_enabled: bool = True
    last_input_dir: Optional[str] = None
    codec_enabled: Dict[str, bool] = field(
        default_factory=lambda: {"jpeg": True, "jpegxl": True, "heic": True, "avif": True}
    )
    codec_quality: Dict[str, int] = field(
        default_factory=lambda: {"jpeg": 95, "jpegxl": 99, "heic": 99, "avif": 99}
    )


DEFAULT_SETTINGS = AppSettings()


def clamp_int(value, default: int, min_value: int, max_value: int, name: str, logger: Optional[logging.Logger]) -> int:
    try:
        parsed = int(value)
    except Exception:
        if logger:
            logger.warning("%s invalid; using default %s", name, default)
        return default
    if parsed < min_value or parsed > max_value:
        if logger:
            logger.warning("%s out of range; clamping to %s-%s", name, min_value, max_value)
        parsed = max(min_value, min(parsed, max_value))
    return parsed


def ensure_config_dir() -> Path:
    path = config_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_from_dict(data: Dict, logger: Optional[logging.Logger]) -> AppSettings:
    settings = AppSettings()
    settings.rename_enabled = bool(data.get("rename_enabled", settings.rename_enabled))
    settings.prefix = str(data.get("prefix", settings.prefix)) or settings.prefix
    settings.counter_enabled = bool(data.get("counter_enabled", settings.counter_enabled))
    settings.start_counter = clamp_int(data.get("start_counter", settings.start_counter), settings.start_counter, 0, 999999, "start_counter", logger)
    settings.zero_fill_enabled = bool(data.get("zero_fill_enabled", settings.zero_fill_enabled))
    settings.zero_fill_mode = "manual" if str(data.get("zero_fill_mode", settings.zero_fill_mode)).lower() == "manual" else "auto"
    settings.zero_fill_digits = clamp_int(
        data.get("zero_fill_digits", settings.zero_fill_digits), settings.zero_fill_digits, 1, 9, "zero_fill_digits", logger
    )
    settings.sdr_enabled = bool(data.get("sdr_enabled", settings.sdr_enabled))
    settings.hdr_enabled = bool(data.get("hdr_enabled", settings.hdr_enabled))
    settings.last_input_dir = data.get("last_input_dir", settings.last_input_dir)

    codec_enabled = data.get("codec_enabled", settings.codec_enabled)
    settings.codec_enabled = {
        "jpeg": bool(codec_enabled.get("jpeg", settings.codec_enabled["jpeg"])),
        "jpegxl": bool(codec_enabled.get("jpegxl", settings.codec_enabled["jpegxl"])),
        "heic": bool(codec_enabled.get("heic", settings.codec_enabled["heic"])),
        "avif": bool(codec_enabled.get("avif", settings.codec_enabled["avif"])),
    }

    codec_quality = data.get("codec_quality", settings.codec_quality)
    settings.codec_quality = {
        "jpeg": clamp_int(codec_quality.get("jpeg", settings.codec_quality["jpeg"]), settings.codec_quality["jpeg"], 0, 100, "jpeg_quality", logger),
        "jpegxl": clamp_int(codec_quality.get("jpegxl", settings.codec_quality["jpegxl"]), settings.codec_quality["jpegxl"], 0, 100, "jpegxl_quality", logger),
        "heic": clamp_int(codec_quality.get("heic", settings.codec_quality["heic"]), settings.codec_quality["heic"], 0, 100, "heic_quality", logger),
        "avif": clamp_int(codec_quality.get("avif", settings.codec_quality["avif"]), settings.codec_quality["avif"], 0, 100, "avif_quality", logger),
    }
    return settings


def load_settings_from_file(path: Path, logger: Optional[logging.Logger]) -> AppSettings:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return settings_from_dict(data, logger)
    except Exception as exc:
        if logger:
            logger.warning("Failed to load settings from %s: %s", path, exc)
        return DEFAULT_SETTINGS


def save_settings_to_file(settings: AppSettings, path: Path) -> None:
    ensure_config_dir()
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=4)


def detect_tools() -> Dict[str, bool]:
    availability = {}
    for tool in {t for tools in TOOLS_FOR_CODECS.values() for t in tools}:
        availability[tool] = shutil.which(tool) is not None
    return availability


def required_tools_missing_for_codec(codec: str, tool_map: Dict[str, bool]) -> List[str]:
    required = TOOLS_FOR_CODECS.get(codec, [])
    return [tool for tool in required if not tool_map.get(tool, False)]


def compute_zero_fill(start: int, count: int, mode: str, manual_digits: int, logger: Optional[logging.Logger]) -> int:
    if count <= 0:
        return manual_digits if mode == "manual" else 1
    auto_digits = len(str(start + count - 1))
    if mode == "manual":
        if manual_digits < auto_digits and logger:
            logger.warning("Manual zerofill too small (%s); using auto %s", manual_digits, auto_digits)
        return max(manual_digits, auto_digits)
    return auto_digits


def copy_source_files(src_dir: Path, output_dir: Path, logger: logging.Logger) -> Tuple[List[Path], List[Path]]:
    png_files: List[Path] = []
    exr_files: List[Path] = []
    for item in src_dir.iterdir():
        if item.is_file() and item.suffix.lower() in {".png", ".exr"}:
            dest = output_dir / item.name
            shutil.copy2(item, dest)
            if dest.suffix.lower() == ".png":
                png_files.append(dest)
            else:
                exr_files.append(dest)
    logger.info("Copied %s PNG and %s EXR into %s", len(png_files), len(exr_files), output_dir)
    return png_files, exr_files


def run_cmd(command: List[str], logger: logging.Logger) -> None:
    logger.info("Running: %s", " ".join(command))
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        startupinfo=startupinfo,
    )


class ProcessingWorker(QThread):
    progress = Signal(int, int)
    status = Signal(str, str)
    finished = Signal(bool)

    def __init__(self, input_dir: Path, settings: AppSettings, tool_map: Dict[str, bool], logger: logging.Logger):
        super().__init__()
        self.input_dir = input_dir
        self.settings = settings
        self.tool_map = tool_map
        self.logger = logger

    def emit_status(self, message: str, level: str = "info") -> None:
        self.status.emit(message, level)

    def run(self) -> None:
        try:
            self.process()
            self.finished.emit(True)
        except Exception as exc:
            self.logger.exception("Processing failed: %s", exc)
            self.emit_status("Error - check errors.log", "error")
            self.finished.emit(False)

    def process(self) -> None:
        if not self.input_dir or not self.input_dir.exists():
            raise FileNotFoundError("Input directory not selected")

        output_dir = self.input_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "logging.log"
        rename_log_path = output_dir / "rename.log"
        attach_file_logger(self.logger, log_path)
        rename_log_path.write_text("", encoding="utf-8")

        def log_rename(src: Path, dst: Path) -> None:
            try:
                with rename_log_path.open("a", encoding="utf-8") as f:
                    f.write(f"{src.name} -> {dst.name}\n")
            except Exception as exc:
                self.logger.warning("Failed to log rename: %s -> %s (%s)", src, dst, exc)

        png_files, exr_files = copy_source_files(self.input_dir, output_dir, self.logger)
        png_files = sorted(png_files, key=lambda p: p.name.lower())
        exr_files = sorted(exr_files, key=lambda p: p.name.lower())
        if not png_files:
            self.emit_status("No PNG files found", "warning")
            return

        def normalize_base(stem: str) -> Tuple[str, bool]:
            import re

            is_hdr = False
            if "_HDR" in stem:
                stem, tail = stem.rsplit("_HDR", 1)
                stem = stem + tail
                is_hdr = True

            while True:
                new_stem = re.sub(r"(?:\s+–\s*[^()]*|\s*\(\s*[^()]*\s*\))\s*$", "", stem)
                if new_stem == stem:
                    break
                stem = new_stem

            stem = stem.strip(" _-")
            return stem, is_hdr

        sdr_groups: Dict[str, List[Path]] = {}
        hdr_groups: Dict[str, List[Path]] = {}
        exr_groups: Dict[str, List[Path]] = {}

        for p in png_files:
            base, is_hdr = normalize_base(p.stem)
            if is_hdr:
                hdr_groups.setdefault(base, []).append(p)
            else:
                sdr_groups.setdefault(base, []).append(p)

        for e in exr_files:
            base, _ = normalize_base(e.stem.replace("_HDR", ""))
            exr_groups.setdefault(base, []).append(e)

        unique_bases = sorted(set(sdr_groups.keys()) | set(hdr_groups.keys()), key=str.lower)
        sdr_base_count = len(sdr_groups)
        if self.settings.rename_enabled and self.settings.counter_enabled:
            digits = compute_zero_fill(self.settings.start_counter, sdr_base_count, self.settings.zero_fill_mode, self.settings.zero_fill_digits, self.logger)
        else:
            digits = 1

        max_dup = 0
        for files in sdr_groups.values():
            max_dup = max(max_dup, len(files) - 1)
        for files in hdr_groups.values():
            max_dup = max(max_dup, len(files) - 1)
        dup_digits = max(1, len(str(max_dup))) if max_dup > 0 else 1

        total = sum(len(v) for v in sdr_groups.values()) + sum(len(v) for v in hdr_groups.values())
        processed = 0

        for idx, base in enumerate(unique_bases, start=self.settings.start_counter):
            sdr_files = sorted(sdr_groups.get(base, []), key=lambda p: p.name.lower())
            number = str(idx)
            if self.settings.zero_fill_enabled:
                number = number.zfill(digits)

            for dup_idx, file_path in enumerate(sdr_files):
                dup_suffix = "" if dup_idx == 0 else f"_Duplicate{str(dup_idx).zfill(dup_digits)}"
                new_stem = f"{self.settings.prefix}{number}{dup_suffix}" if self.settings.rename_enabled else file_path.stem
                target = file_path.with_name(f"{new_stem}{file_path.suffix}")
                if target.exists():
                    self.logger.warning("Target exists, skipping duplicate: %s -> %s", file_path.name, target.name)
                    continue
                if self.settings.rename_enabled:
                    file_path.rename(target)
                    log_rename(file_path, target)
                    file_path = target
                if self.settings.sdr_enabled:
                    self.convert_sdr(file_path)
                processed += 1
                self.progress.emit(processed, total)

            hdr_files = sorted(hdr_groups.get(base, []), key=lambda p: p.name.lower())
            exr_list = sorted(exr_groups.get(base, []), key=lambda p: p.name.lower())

            for dup_idx, file_path in enumerate(hdr_files):
                dup_suffix = "" if dup_idx == 0 else f"_Duplicate{str(dup_idx).zfill(dup_digits)}"
                new_stem = f"{self.settings.prefix}{number}_HDR{dup_suffix}" if self.settings.rename_enabled else file_path.stem
                target = file_path.with_name(f"{new_stem}{file_path.suffix}")
                if target.exists():
                    self.logger.warning("HDR target exists, skipping duplicate: %s -> %s", file_path.name, target.name)
                    continue
                if self.settings.rename_enabled:
                    file_path.rename(target)
                    log_rename(file_path, target)
                    file_path = target
                if dup_idx < len(exr_list):
                    exr_src = exr_list[dup_idx]
                    exr_dst = output_dir / f"{new_stem}.exr"
                    if exr_dst.exists():
                        self.logger.warning("HDR EXR target exists, skipping duplicate: %s -> %s", exr_src.name, exr_dst.name)
                    else:
                        try:
                            exr_src.rename(exr_dst)
                            log_rename(exr_src, exr_dst)
                        except FileNotFoundError:
                            self.logger.warning("HDR EXR source missing during rename: %s", exr_src)
                if self.settings.hdr_enabled:
                    self.convert_hdr(file_path)
                processed += 1
                self.progress.emit(processed, total)

    def convert_sdr(self, png_file: Path) -> None:
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

        if self.settings.codec_enabled.get("jpeg") and not required_tools_missing_for_codec("jpeg", self.tool_map):
            run_cmd(["ffmpeg", "-y", "-i", str(png_file), "-pix_fmt", "rgb24", str(temp_bmp)], self.logger)
            run_cmd(
                ["cjpeg", "-quality", str(self.settings.codec_quality["jpeg"]), "-optimize", "-precision", "8", "-outfile", str(temp_jpg), str(temp_bmp)],
                self.logger,
            )
            temp_bmp.unlink(missing_ok=True)
            temp_jpg.rename(stem.with_suffix(".jpg"))

        if self.settings.codec_enabled.get("jpegxl") and not required_tools_missing_for_codec("jpegxl", self.tool_map):
            run_cmd(["cjxl", str(png_file), str(temp_jxl), "--quality", str(self.settings.codec_quality["jpegxl"]), "--effort", "7", "--brotli_effort", "11", "--num_threads", "-1", "--gaborish", "1"], self.logger)
            temp_jxl.rename(stem.with_suffix(".jxl"))

        if self.settings.codec_enabled.get("heic") and not required_tools_missing_for_codec("heic", self.tool_map):
            run_cmd(
                [
                    "heif-enc",
                    "--thumb",
                    "off",
                    "--no-alpha",
                    "--no-thumb-alpha",
                    "--bit-depth",
                    "8",
                    "--quality",
                    str(self.settings.codec_quality["heic"]),
                    "--matrix_coefficients",
                    "6",
                    "--colour_primaries",
                    "1",
                    "--transfer_characteristic",
                    "13",
                    "--full_range_flag",
                    "1",
                    "--encoder",
                    "x265",
                    "-p",
                    f"quality={self.settings.codec_quality['heic']}",
                    "-p",
                    "preset=slow",
                    "-p",
                    "tune=ssim",
                    "-p",
                    "complexity=80",
                    "-p",
                    "chroma=420",
                    "--output",
                    str(temp_heic),
                    str(png_file),
                ],
                self.logger,
            )
            temp_heic.rename(stem.with_suffix(".heic"))

        if self.settings.codec_enabled.get("avif") and not required_tools_missing_for_codec("avif", self.tool_map):
            run_cmd(
                [
                    "avifenc",
                    "--codec",
                    "aom",
                    "--speed",
                    "6",
                    "--qcolor",
                    str(self.settings.codec_quality["avif"]),
                    "--yuv",
                    "420",
                    "--range",
                    "full",
                    "--depth",
                    "8",
                    "--cicp",
                    "1/13/6",
                    "--jobs",
                    "all",
                    "--ignore-icc",
                    "--advanced",
                    "enable-chroma-deltaq=1",
                    str(png_file),
                    str(temp_avif),
                ],
                self.logger,
            )
            temp_avif.rename(stem.with_suffix(".avif"))

    def convert_hdr(self, png_file: Path) -> None:
        stem = png_file.with_suffix("")
        temp_base = png_file.with_name("Tempfile")
        temp_base.unlink(missing_ok=True)
        temp_jxl = temp_base.with_suffix(".jxl")
        temp_heic = temp_base.with_suffix(".heic")
        temp_avif = temp_base.with_suffix(".avif")
        for f in [temp_jxl, temp_heic, temp_avif]:
            f.unlink(missing_ok=True)

        if self.settings.codec_enabled.get("jpegxl") and not required_tools_missing_for_codec("jpegxl", self.tool_map):
            run_cmd(
                [
                    "cjxl",
                    str(png_file),
                    str(temp_jxl),
                    "--quality",
                    str(self.settings.codec_quality["jpegxl"]),
                    "--effort",
                    "7",
                    "--brotli_effort",
                    "11",
                    "--num_threads",
                    "-1",
                    "--gaborish",
                    "1",
                    "-x",
                    "color_space=RGB_D65_202_Rel_PeQ",
                ],
                self.logger,
            )
            temp_jxl.rename(stem.with_suffix(".jxl"))

        if self.settings.codec_enabled.get("heic") and not required_tools_missing_for_codec("heic", self.tool_map):
            run_cmd(
                [
                    "heif-enc",
                    "--thumb",
                    "off",
                    "--no-alpha",
                    "--no-thumb-alpha",
                    "--bit-depth",
                    "10",
                    "--quality",
                    str(self.settings.codec_quality["heic"]),
                    "--matrix_coefficients",
                    "9",
                    "--colour_primaries",
                    "9",
                    "--transfer_characteristic",
                    "13",
                    "--full_range_flag",
                    "1",
                    "--encoder",
                    "x265",
                    "-p",
                    f"quality={self.settings.codec_quality['heic']}",
                    "-p",
                    "preset=slow",
                    "-p",
                    "tune=ssim",
                    "-p",
                    "complexity=80",
                    "-p",
                    "chroma=420",
                    "--output",
                    str(temp_heic),
                    str(png_file),
                ],
                self.logger,
            )
            temp_heic.rename(stem.with_suffix(".heic"))

        if self.settings.codec_enabled.get("avif") and not required_tools_missing_for_codec("avif", self.tool_map):
            run_cmd(
                [
                    "avifenc",
                    "--codec",
                    "aom",
                    "--speed",
                    "6",
                    "--qcolor",
                    str(self.settings.codec_quality["avif"]),
                    "--yuv",
                    "420",
                    "--range",
                    "full",
                    "--depth",
                    "10",
                    "--cicp",
                    "9/16/9",
                    "--jobs",
                    "all",
                    "--ignore-icc",
                    "--advanced",
                    "enable-chroma-deltaq=1",
                    str(png_file),
                    str(temp_avif),
                ],
                self.logger,
            )
            temp_avif.rename(stem.with_suffix(".avif"))


def attach_file_logger(logger: logging.Logger, log_path: Path) -> None:
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("True HDR/SDR Automatic Image Converter")
        self.settings = load_settings_from_file(config_file(), None)
        self.tool_map = detect_tools()
        self.logger = logging.getLogger("converter")
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(logging.NullHandler())
        self.running_mode = "exe" if is_frozen() else "script"
        self.logger.info("Starting application in %s mode", self.running_mode)
        self.input_dir: Optional[Path] = None
        self.worker: Optional[ProcessingWorker] = None
        self._processing_timer = QTimer(self)
        self._processing_timer.setInterval(1000)
        self._processing_timer.timeout.connect(self._tick_processing_animation)
        self._processing_phase = 0

        self._build_ui()
        self._apply_settings_to_ui(self.settings)
        if self.settings.last_input_dir:
            self.input_dir = Path(self.settings.last_input_dir)
        self._update_tool_states()
        self._last_status_message = "Ready"
        self._last_status_level = "info"
        self._set_status(self._last_status_message, self._last_status_level)
        self._center_window()

    def _center_window(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = self.frameGeometry()
        center = screen.availableGeometry().center()
        geo.moveCenter(center)
        self.move(geo.topLeft())

    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)

        # Settings section
        settings_group = QGroupBox("Settings")
        settings_layout = QVBoxLayout(settings_group)

        # Buttons row (12-col; each button spans 4 cols)
        buttons_grid = QGridLayout()
        self.btn_load_settings = QPushButton("Load settings")
        self.btn_save_settings = QPushButton("Save settings")
        self.btn_load_images = QPushButton("Select image directory")
        buttons_grid.addWidget(self.btn_load_settings, 0, 0, 1, 4)
        buttons_grid.addWidget(self.btn_save_settings, 0, 4, 1, 4)
        buttons_grid.addWidget(self.btn_load_images, 0, 8, 1, 4)
        for c in range(12):
            buttons_grid.setColumnStretch(c, 1)
        settings_layout.addLayout(buttons_grid)

        # Grid for settings rows (12-col like bootstrap)
        grid = QGridLayout()
        for c in range(12):
            grid.setColumnStretch(c, 1)
        grid.setColumnMinimumWidth(0, 24)  # checkbox col

        # Rename: checkbox with text spans 6 cols, input 6 cols
        self.chk_rename = QCheckBox("Rename")
        self.edit_prefix = QLineEdit()
        grid.addWidget(self.chk_rename, 0, 0, 1, 6)
        grid.addWidget(self.edit_prefix, 0, 6, 1, 6)

        # Counter: checkbox with text spans 6 cols, input 6 cols
        self.chk_counter = QCheckBox("Counter")
        self.spin_counter_start = QSpinBox()
        self.spin_counter_start.setRange(0, 999999)
        grid.addWidget(self.chk_counter, 1, 0, 1, 6)
        grid.addWidget(self.spin_counter_start, 1, 6, 1, 6)

        # Zerofill: checkbox with text spans 6 cols, inputs share remaining 6 cols evenly
        self.chk_zerofill = QCheckBox("Zerofill")
        self.combo_zerofill = QComboBox()
        self.combo_zerofill.addItems(["Auto", "Manual"])
        self.spin_zerofill_digits = QSpinBox()
        self.spin_zerofill_digits.setRange(1, 99)
        zerofill_inputs = QHBoxLayout()
        zerofill_inputs.addWidget(self.combo_zerofill)
        zerofill_inputs.addWidget(self.spin_zerofill_digits)
        zerofill_inputs.setStretch(0, 1)
        zerofill_inputs.setStretch(1, 1)
        grid.addWidget(self.chk_zerofill, 2, 0, 1, 6)
        grid.addLayout(zerofill_inputs, 2, 6, 1, 6)

        # SDR
        self.chk_sdr = QCheckBox("Process SDR images")
        grid.addWidget(self.chk_sdr, 3, 0, 1, 6)

        # HDR
        self.chk_hdr = QCheckBox("Process HDR images")
        grid.addWidget(self.chk_hdr, 4, 0, 1, 6)

        settings_layout.addLayout(grid)

        layout.addWidget(settings_group)

        # Codecs section
        codecs_group = QGroupBox("Codecs")
        codecs_layout = QVBoxLayout(codecs_group)

        self.codec_checks: Dict[str, QCheckBox] = {}
        self.codec_quality: Dict[str, QSpinBox] = {}

        for label, key in [("JPEG", "jpeg"), ("JPEG XL", "jpegxl"), ("HEIC", "heic"), ("AVIF", "avif")]:
            row = QHBoxLayout()
            chk = QCheckBox(label)
            spin = QSpinBox()
            spin.setRange(0, 100)
            row.addWidget(chk)
            row.addWidget(spin)
            codecs_layout.addLayout(row)
            self.codec_checks[key] = chk
            self.codec_quality[key] = spin

        layout.addWidget(codecs_group)

        # Processing section
        processing_group = QGroupBox("Processing")
        processing_layout = QVBoxLayout(processing_group)
        self.btn_process = QPushButton("Process images")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status_label = QLabel("Ready")
        self.status_label.setAutoFillBackground(True)

        processing_layout.addWidget(self.btn_process)
        processing_layout.addWidget(self.progress_bar)
        processing_layout.addWidget(self.status_label)
        layout.addWidget(processing_group)

        self.btn_load_settings.clicked.connect(self._load_settings_clicked)
        self.btn_save_settings.clicked.connect(self._save_settings_clicked)
        self.btn_load_images.clicked.connect(self._load_images_clicked)
        self.btn_process.clicked.connect(self._process_clicked)

        self.setCentralWidget(container)

    def _apply_settings_to_ui(self, settings: AppSettings) -> None:
        self.chk_rename.setChecked(settings.rename_enabled)
        self.edit_prefix.setText(settings.prefix)
        self.chk_counter.setChecked(settings.counter_enabled)
        self.spin_counter_start.setValue(settings.start_counter)
        self.chk_zerofill.setChecked(settings.zero_fill_enabled)
        self.combo_zerofill.setCurrentText("Manual" if settings.zero_fill_mode == "manual" else "Auto")
        self.spin_zerofill_digits.setValue(settings.zero_fill_digits)
        self.chk_sdr.setChecked(settings.sdr_enabled)
        self.chk_hdr.setChecked(settings.hdr_enabled)

        self.codec_checks["jpeg"].setChecked(settings.codec_enabled.get("jpeg", True))
        self.codec_quality["jpeg"].setValue(settings.codec_quality.get("jpeg", 95))
        self.codec_checks["jpegxl"].setChecked(settings.codec_enabled.get("jpegxl", True))
        self.codec_quality["jpegxl"].setValue(settings.codec_quality.get("jpegxl", 99))
        self.codec_checks["heic"].setChecked(settings.codec_enabled.get("heic", True))
        self.codec_quality["heic"].setValue(settings.codec_quality.get("heic", 99))
        self.codec_checks["avif"].setChecked(settings.codec_enabled.get("avif", True))
        self.codec_quality["avif"].setValue(settings.codec_quality.get("avif", 99))

    def _collect_settings_from_ui(self) -> AppSettings:
        settings = AppSettings()
        settings.rename_enabled = self.chk_rename.isChecked()
        settings.prefix = self.edit_prefix.text() or settings.prefix
        settings.counter_enabled = self.chk_counter.isChecked()
        settings.start_counter = self.spin_counter_start.value()
        settings.zero_fill_enabled = self.chk_zerofill.isChecked()
        settings.zero_fill_mode = "manual" if self.combo_zerofill.currentText().lower() == "manual" else "auto"
        settings.zero_fill_digits = self.spin_zerofill_digits.value()
        settings.sdr_enabled = self.chk_sdr.isChecked()
        settings.hdr_enabled = self.chk_hdr.isChecked()
        settings.codec_enabled = {k: chk.isChecked() for k, chk in self.codec_checks.items()}
        settings.codec_quality = {k: spin.value() for k, spin in self.codec_quality.items()}
        if self.input_dir:
            settings.last_input_dir = str(self.input_dir)
        return settings

    def _compute_status_color(self, level: str) -> Optional[QColor]:
        if level == "info":
            return None
        is_light = True
        app = QApplication.instance()
        if app:
            is_light = app.palette().color(QPalette.Window).value() > 128

        if is_light:
            if level == "warning":
                return QColor(255, 127, 0)
            if level == "error":
                return QColor(255, 0, 0)
            if level == "success":
                return QColor(0, 223, 0)
            return QColor(0, 95, 255)
        # dark
        if level == "warning":
            return QColor(255, 159, 0)
        if level == "error":
            return QColor(255, 31, 31)
        if level == "success":
            return QColor(0, 255, 0)
        return QColor(95, 223, 255)

    def _apply_status_palette(self) -> None:
        app = QApplication.instance()
        base_palette = app.palette() if app else self.status_label.palette()
        color = self._compute_status_color(self._last_status_level)
        if color is None:
            self.status_label.setPalette(base_palette)
        else:
            palette = base_palette
            palette.setColor(QPalette.WindowText, color)
            self.status_label.setPalette(palette)

    def _confirm_overwrite_output(self) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Output not empty")
        layout = QVBoxLayout(dialog)

        row = QHBoxLayout()
        icon_label = QLabel()
        icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning)
        icon_label.setPixmap(icon.pixmap(32, 32))
        row.addWidget(icon_label, 0, Qt.AlignTop)

        text_label = QLabel("Output directory contains files that might be overwritten.\nDo you want to proceed?")
        text_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        row.addWidget(text_label, 1)
        layout.addLayout(row)

        buttons = QDialogButtonBox()
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        overwrite_btn = buttons.addButton("Overwrite", QDialogButtonBox.AcceptRole)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(buttons)
        buttons_layout.addStretch(1)
        layout.addLayout(buttons_layout)

        def accept():
            dialog.accept()

        def reject():
            dialog.reject()

        buttons.accepted.connect(accept)
        buttons.rejected.connect(reject)
        dialog.setLayout(layout)
        result = dialog.exec()
        return result == QDialog.Accepted

    def _show_warning_dialog(self, title: str, text: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)

        row = QHBoxLayout()
        icon_label = QLabel()
        icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning)
        icon_label.setPixmap(icon.pixmap(32, 32))
        row.addWidget(icon_label, 0, Qt.AlignTop)

        text_label = QLabel(text)
        text_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        row.addWidget(text_label, 1)
        layout.addLayout(row)

        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("OK", QDialogButtonBox.AcceptRole)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(buttons)
        buttons_layout.addStretch(1)
        layout.addLayout(buttons_layout)

        def accept():
            dialog.accept()

        buttons.accepted.connect(accept)
        dialog.setLayout(layout)
        dialog.exec()

    def _set_status(self, message: str, level: str = "info") -> None:
        self._last_status_message = message
        self._last_status_level = level
        self._apply_status_palette()
        self.status_label.setText(message)
        if not message.lower().startswith("processing"):
            self._stop_processing_animation()

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.PaletteChange:
            self._apply_status_palette()
        super().changeEvent(event)

    def _update_tool_states(self) -> None:
        missing = []
        for codec, chk in self.codec_checks.items():
            missing_tools = required_tools_missing_for_codec(codec, self.tool_map)
            enabled = len(missing_tools) == 0
            chk.setEnabled(enabled)
            if not enabled:
                chk.setChecked(False)
                missing.extend(missing_tools)
        if missing:
            self._set_status(f"Missing tools: {', '.join(sorted(set(missing)))}", "warning")

    def _load_settings_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Load settings", "", "JSON Files (*.json);;All Files (*)")
        if not file_path:
            return
        settings = load_settings_from_file(Path(file_path), self.logger)
        self.settings = settings
        self._apply_settings_to_ui(settings)
        save_settings_to_file(settings, config_file())
        self.input_dir = Path(settings.last_input_dir) if settings.last_input_dir else None
        self._set_status("Settings loaded", "info")

    def _save_settings_clicked(self) -> None:
        settings = self._collect_settings_from_ui()
        save_settings_to_file(settings, config_file())
        self.settings = settings
        self._set_status("Settings saved", "info")

    def _load_images_clicked(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "Select image directory", "")
        if dir_path:
            self.input_dir = Path(dir_path)
            self._set_status("Image directory selected", "info")
            self.progress_bar.setValue(0)
            # persist chosen dir for next run
            s = self._collect_settings_from_ui()
            s.last_input_dir = str(self.input_dir)
            save_settings_to_file(s, config_file())
        else:
            if self.input_dir:
                self._set_status("Image directory selected", "info")
            else:
                self._set_status("No directory selected", "warning")

    def _process_clicked(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not self.input_dir:
            self._show_warning_dialog("Input missing", "Please select an image directory first.")
            return

        output_dir = self.input_dir / "output"
        if output_dir.exists() and any(output_dir.iterdir()):
            if not self._confirm_overwrite_output():
                return
            shutil.rmtree(output_dir, ignore_errors=True)

        self._set_settings_buttons_enabled(False)
        self.tool_map = detect_tools()
        self._update_tool_states()
        self.settings = self._collect_settings_from_ui()
        self.progress_bar.setValue(0)
        self._start_processing_animation()

        self.worker = ProcessingWorker(self.input_dir, self.settings, self.tool_map, self.logger)
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._set_status)
        self.worker.finished.connect(self._on_finished)
        self.btn_process.setEnabled(False)
        self.worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        if total <= 0:
            return
        percent = int((current / total) * 100)
        self.progress_bar.setValue(percent)

    def _on_finished(self, success: bool) -> None:
        self.btn_process.setEnabled(True)
        if success:
            self._set_status("Processing completed", "success")
        self._stop_processing_animation()
        self._set_settings_buttons_enabled(True)

    def _start_processing_animation(self) -> None:
        self._processing_phase = 0
        self._processing_timer.start()
        self._set_status("Processing.", "info")

    def _stop_processing_animation(self) -> None:
        if self._processing_timer.isActive():
            self._processing_timer.stop()

    def _tick_processing_animation(self) -> None:
        dots = "." * ((self._processing_phase % 3) + 1)
        self._processing_phase += 1
        self._set_status(f"Processing{dots}", "info")

    def _set_settings_buttons_enabled(self, enabled: bool) -> None:
        self.btn_load_settings.setEnabled(enabled)
        self.btn_save_settings.setEnabled(enabled)
        self.btn_load_images.setEnabled(enabled)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
