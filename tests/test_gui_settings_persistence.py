from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import src.gui as gui_module
from src.gui import MainWindow
from src.models import AppSettings, TOOLS_FOR_CODECS


@dataclass
class WindowHarness:
    window: MainWindow
    config_path: Path
    load_mock: Mock
    save_mock: Mock


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        app = QApplication([])

    yield app

    if owns_application:
        app.quit()


@pytest.fixture
def window_harness(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> WindowHarness:
    config_path = tmp_path / "settings.json"
    config_path.write_text("sentinel settings", encoding="utf-8")

    load_mock = Mock(return_value=AppSettings())
    save_mock = Mock()
    available_tools = {
        tool: True
        for codec_tools in TOOLS_FOR_CODECS.values()
        for tool in codec_tools
    }

    monkeypatch.setattr(gui_module, "config_file", lambda: config_path)
    monkeypatch.setattr(gui_module, "load_settings_from_file", load_mock)
    monkeypatch.setattr(gui_module, "save_settings_to_file", save_mock)
    monkeypatch.setattr(gui_module, "detect_tools", lambda: available_tools)
    monkeypatch.setattr(gui_module, "is_frozen", lambda: False)

    window = MainWindow()
    harness = WindowHarness(window, config_path, load_mock, save_mock)
    yield harness

    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_load_settings_only_updates_current_gui_session(
    window_harness: WindowHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported_path = tmp_path / "imported.json"
    imported_input_dir = tmp_path / "imported-workdir"
    imported_settings = AppSettings(
        rename_enabled=False,
        prefix="Imported_",
        counter_enabled=False,
        start_counter=37,
        zero_fill_enabled=False,
        zero_fill_mode="manual",
        zero_fill_digits=8,
        sdr_enabled=False,
        hdr_enabled=True,
        last_input_dir=str(imported_input_dir),
        codec_enabled={
            "jpeg": True,
            "jpegxl": False,
            "heic": True,
            "avif": False,
        },
        codec_quality={
            "jpeg": 91,
            "jpegxl": 92,
            "heic": 93,
            "avif": 94,
        },
    )
    window_harness.load_mock.reset_mock()
    window_harness.load_mock.return_value = imported_settings
    window_harness.save_mock.reset_mock()
    monkeypatch.setattr(
        gui_module.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(imported_path), "JSON Files (*.json)"),
    )

    window_harness.window._load_settings_clicked()

    window_harness.load_mock.assert_called_once_with(
        imported_path, window_harness.window.logger
    )
    window_harness.save_mock.assert_not_called()
    assert window_harness.config_path.read_text(encoding="utf-8") == "sentinel settings"
    assert window_harness.window.settings is imported_settings
    assert window_harness.window.input_dir == imported_input_dir
    assert window_harness.window.edit_prefix.text() == "Imported_"
    assert window_harness.window.spin_counter_start.value() == 37
    assert window_harness.window.spin_zerofill_digits.value() == 8
    assert window_harness.window.codec_quality["avif"].value() == 94


def test_load_images_keeps_directory_in_memory_without_writing_settings(
    window_harness: WindowHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_dir = tmp_path / "session-workdir"
    directory_answers = iter((str(selected_dir), ""))
    monkeypatch.setattr(
        gui_module.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: next(directory_answers),
    )
    window_harness.save_mock.reset_mock()

    window_harness.window._load_images_clicked()

    assert window_harness.window.input_dir == selected_dir
    window_harness.save_mock.assert_not_called()
    assert window_harness.config_path.read_text(encoding="utf-8") == "sentinel settings"

    # Cancelling a later directory dialog must preserve the in-memory workdir.
    window_harness.window._load_images_clicked()

    assert window_harness.window.input_dir == selected_dir
    window_harness.save_mock.assert_not_called()
    assert window_harness.config_path.read_text(encoding="utf-8") == "sentinel settings"


def test_save_settings_writes_all_gui_values_including_input_directory(
    window_harness: WindowHarness,
    tmp_path: Path,
) -> None:
    window = window_harness.window
    selected_dir = tmp_path / "saved-workdir"
    window.input_dir = selected_dir
    window.chk_rename.setChecked(False)
    window.edit_prefix.setText("Saved_")
    window.chk_counter.setChecked(False)
    window.spin_counter_start.setValue(246)
    window.chk_zerofill.setChecked(False)
    window.combo_zerofill.setCurrentText("Manual")
    window.spin_zerofill_digits.setValue(6)
    window.chk_sdr.setChecked(True)
    window.chk_hdr.setChecked(False)

    expected_codec_enabled = {
        "jpeg": True,
        "jpegxl": False,
        "heic": False,
        "avif": True,
    }
    expected_codec_quality = {
        "jpeg": 81,
        "jpegxl": 82,
        "heic": 83,
        "avif": 84,
    }
    for codec, enabled in expected_codec_enabled.items():
        window.codec_checks[codec].setChecked(enabled)
    for codec, quality in expected_codec_quality.items():
        window.codec_quality[codec].setValue(quality)

    window_harness.save_mock.reset_mock()

    window._save_settings_clicked()

    window_harness.save_mock.assert_called_once()
    saved_settings, saved_path = window_harness.save_mock.call_args.args
    assert saved_path == window_harness.config_path
    assert saved_settings == AppSettings(
        rename_enabled=False,
        prefix="Saved_",
        counter_enabled=False,
        start_counter=246,
        zero_fill_enabled=False,
        zero_fill_mode="manual",
        zero_fill_digits=6,
        sdr_enabled=True,
        hdr_enabled=False,
        last_input_dir=str(selected_dir),
        codec_enabled=expected_codec_enabled,
        codec_quality=expected_codec_quality,
    )
    assert window.settings is saved_settings

