"""PySide6 GUI – MainWindow and all UI-related logic."""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from src.models import AppSettings
from src.config import (
    config_file,
    detect_tools,
    is_frozen,
    load_settings_from_file,
    required_tools_missing_for_codec,
    save_settings_to_file,
)
from src.worker import ProcessingWorker


# ---------------------------------------------------------------------------
# Stylesheet loader
# ---------------------------------------------------------------------------

def _load_stylesheet() -> str:
    """Return the contents of ``styles.qss`` bundled next to this module."""
    qss_path = Path(__file__).with_name("styles.qss")
    if qss_path.exists():
        return qss_path.read_text(encoding="utf-8")
    return ""


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self) -> None:
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

    # -- window positioning --------------------------------------------------

    def _center_window(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = self.frameGeometry()
        center = screen.availableGeometry().center()
        geo.moveCenter(center)
        self.move(geo.topLeft())

    # -- UI construction -----------------------------------------------------

    def _build_ui(self) -> None:  # noqa: C901
        container = QWidget()
        layout = QVBoxLayout(container)

        # --- Settings section -----------------------------------------------
        settings_group = QGroupBox("Settings")
        settings_layout = QVBoxLayout(settings_group)

        # Buttons row (12-col grid; each button spans 4 cols)
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

        # Settings grid (12-col like Bootstrap)
        grid = QGridLayout()
        for c in range(12):
            grid.setColumnStretch(c, 1)
        grid.setColumnMinimumWidth(0, 24)

        # Rename
        self.chk_rename = QCheckBox("Rename")
        self.edit_prefix = QLineEdit()
        grid.addWidget(self.chk_rename, 0, 0, 1, 6)
        grid.addWidget(self.edit_prefix, 0, 6, 1, 6)

        # Counter
        self.chk_counter = QCheckBox("Counter")
        self.spin_counter_start = QSpinBox()
        self.spin_counter_start.setRange(0, 999999)
        grid.addWidget(self.chk_counter, 1, 0, 1, 6)
        grid.addWidget(self.spin_counter_start, 1, 6, 1, 6)

        # Zerofill
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

        # SDR / HDR checkboxes
        self.chk_sdr = QCheckBox("Process SDR images")
        grid.addWidget(self.chk_sdr, 3, 0, 1, 6)
        self.chk_hdr = QCheckBox("Process HDR images")
        grid.addWidget(self.chk_hdr, 4, 0, 1, 6)

        settings_layout.addLayout(grid)
        layout.addWidget(settings_group)

        # --- Codecs section -------------------------------------------------
        codecs_group = QGroupBox("Codecs")
        codecs_layout = QVBoxLayout(codecs_group)

        self.codec_checks: Dict[str, QCheckBox] = {}
        self.codec_quality: Dict[str, QSpinBox] = {}

        for label, key in [
            ("JPEG", "jpeg"),
            ("JPEG XL", "jpegxl"),
            ("HEIC", "heic"),
            ("AVIF", "avif"),
        ]:
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

        # --- Processing section ---------------------------------------------
        processing_group = QGroupBox("Processing")
        processing_layout = QVBoxLayout(processing_group)

        # Process + Stop buttons in one row
        btn_row = QHBoxLayout()
        self.btn_process = QPushButton("Process images")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_process)
        btn_row.addWidget(self.btn_stop)
        processing_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAutoFillBackground(True)

        processing_layout.addWidget(self.progress_bar)
        processing_layout.addWidget(self.status_label)
        layout.addWidget(processing_group)

        # --- Connections ----------------------------------------------------
        self.btn_load_settings.clicked.connect(self._load_settings_clicked)
        self.btn_save_settings.clicked.connect(self._save_settings_clicked)
        self.btn_load_images.clicked.connect(self._load_images_clicked)
        self.btn_process.clicked.connect(self._process_clicked)
        self.btn_stop.clicked.connect(self._stop_clicked)

        self.setCentralWidget(container)

    # -- settings ↔ UI -------------------------------------------------------

    def _apply_settings_to_ui(self, settings: AppSettings) -> None:
        self.chk_rename.setChecked(settings.rename_enabled)
        self.edit_prefix.setText(settings.prefix)
        self.chk_counter.setChecked(settings.counter_enabled)
        self.spin_counter_start.setValue(settings.start_counter)
        self.chk_zerofill.setChecked(settings.zero_fill_enabled)
        self.combo_zerofill.setCurrentText(
            "Manual" if settings.zero_fill_mode == "manual" else "Auto"
        )
        self.spin_zerofill_digits.setValue(settings.zero_fill_digits)
        self.chk_sdr.setChecked(settings.sdr_enabled)
        self.chk_hdr.setChecked(settings.hdr_enabled)

        for key in self.codec_checks:
            self.codec_checks[key].setChecked(settings.codec_enabled.get(key, True))
            self.codec_quality[key].setValue(settings.codec_quality.get(key, 95))

    def _collect_settings_from_ui(self) -> AppSettings:
        settings = AppSettings()
        settings.rename_enabled = self.chk_rename.isChecked()
        settings.prefix = self.edit_prefix.text() or settings.prefix
        settings.counter_enabled = self.chk_counter.isChecked()
        settings.start_counter = self.spin_counter_start.value()
        settings.zero_fill_enabled = self.chk_zerofill.isChecked()
        settings.zero_fill_mode = (
            "manual" if self.combo_zerofill.currentText().lower() == "manual" else "auto"
        )
        settings.zero_fill_digits = self.spin_zerofill_digits.value()
        settings.sdr_enabled = self.chk_sdr.isChecked()
        settings.hdr_enabled = self.chk_hdr.isChecked()
        settings.codec_enabled = {k: chk.isChecked() for k, chk in self.codec_checks.items()}
        settings.codec_quality = {k: spin.value() for k, spin in self.codec_quality.items()}
        if self.input_dir:
            settings.last_input_dir = str(self.input_dir)
        return settings

    # -- status label --------------------------------------------------------

    def _compute_status_color(self, level: str) -> Optional[QColor]:
        if level == "info":
            return None
        app = QApplication.instance()
        is_light = True
        if app:
            is_light = app.palette().color(QPalette.Window).value() > 128

        if is_light:
            colors = {
                "warning": QColor(255, 127, 0),
                "error": QColor(255, 0, 0),
                "success": QColor(0, 223, 0),
            }
        else:
            colors = {
                "warning": QColor(255, 159, 0),
                "error": QColor(255, 31, 31),
                "success": QColor(0, 255, 0),
            }
        return colors.get(level, QColor(0, 95, 255) if is_light else QColor(95, 223, 255))

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

    # -- tool availability ---------------------------------------------------

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
            self._set_status(
                f"Missing tools: {', '.join(sorted(set(missing)))}",
                "warning",
            )

    # -- dialogs -------------------------------------------------------------

    def _confirm_overwrite_output(self) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Output not empty")
        layout = QVBoxLayout(dialog)

        row = QHBoxLayout()
        icon_label = QLabel()
        icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning)
        icon_label.setPixmap(icon.pixmap(32, 32))
        row.addWidget(icon_label, 0, Qt.AlignTop)

        text_label = QLabel(
            "Output directory contains files that might be overwritten.\n"
            "Do you want to proceed?"
        )
        text_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        row.addWidget(text_label, 1)
        layout.addLayout(row)

        buttons = QDialogButtonBox()
        buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        buttons.addButton("Overwrite", QDialogButtonBox.AcceptRole)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(buttons)
        buttons_layout.addStretch(1)
        layout.addLayout(buttons_layout)

        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
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
        buttons.addButton("OK", QDialogButtonBox.AcceptRole)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(buttons)
        buttons_layout.addStretch(1)
        layout.addLayout(buttons_layout)

        buttons.accepted.connect(dialog.accept)
        dialog.setLayout(layout)
        dialog.exec()

    # -- button handlers -----------------------------------------------------

    def _load_settings_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load settings", "", "JSON Files (*.json);;All Files (*)"
        )
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
            self._show_warning_dialog(
                "Input missing", "Please select an image directory first."
            )
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

        self.worker = ProcessingWorker(
            self.input_dir, self.settings, self.tool_map, self.logger,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self._set_status)
        self.worker.finished.connect(self._on_finished)
        self.btn_process.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker.start()

    def _stop_clicked(self) -> None:
        """Handle the Stop button – request cooperative cancellation."""
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.btn_stop.setEnabled(False)
            self._set_status("Stopping…", "warning")

    # -- worker callbacks ----------------------------------------------------

    def _on_progress(self, current: int, total: int) -> None:
        if total <= 0:
            return
        percent = int((current / total) * 100)
        self.progress_bar.setValue(percent)

    def _on_finished(self, success: bool) -> None:
        self.btn_process.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if success:
            self._set_status("Processing completed", "success")
        self._stop_processing_animation()
        self._set_settings_buttons_enabled(True)

    # -- processing animation ------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_gui() -> int:
    """Create the application, show the main window, and enter the event loop."""
    app = QApplication(sys.argv)
    app.setStyleSheet(_load_stylesheet())
    window = MainWindow()
    window.show()
    return app.exec()
