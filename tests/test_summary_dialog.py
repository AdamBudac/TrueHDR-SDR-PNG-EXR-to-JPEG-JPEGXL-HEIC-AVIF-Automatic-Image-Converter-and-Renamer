from __future__ import annotations

from pathlib import Path

import pytest

import src.gui as gui_module
from src.gui import MainWindow
from src.results import ProcessingOutcome, ProcessingSummary
from src.summary_dialog import build_summary_view_model


def _summary(tmp_path: Path, **overrides) -> ProcessingSummary:
    values = {
        "output_dir": tmp_path,
        "logging_log_path": tmp_path / "logging.log",
        "rename_log_path": tmp_path / "rename.log",
        "errors_log_path": tmp_path / "errors.log",
        "discovered_images": 2,
        "processed_images": 2,
        "successful_images": 2,
    }
    values.update(overrides)
    return ProcessingSummary(**values)


@pytest.mark.parametrize(
    ("overrides", "expected_outcome", "expected_heading"),
    [
        ({}, ProcessingOutcome.CLEAN, "Processing completed"),
        (
            {"retried_commands": 1, "recovered_commands": 1},
            ProcessingOutcome.RECOVERED,
            "Processing completed after retries",
        ),
        (
            {
                "successful_images": 1,
                "partially_successful_images": 1,
                "failed_commands": 1,
            },
            ProcessingOutcome.PARTIAL,
            "Processing completed with errors",
        ),
        (
            {"fatal_error": "OSError: disk unavailable"},
            ProcessingOutcome.FATAL,
            "Processing failed",
        ),
        (
            {"cancelled": True},
            ProcessingOutcome.CANCELLED,
            "Processing cancelled",
        ),
    ],
)
def test_summary_view_model_for_all_outcomes(
    tmp_path: Path,
    overrides: dict,
    expected_outcome: ProcessingOutcome,
    expected_heading: str,
) -> None:
    summary = _summary(tmp_path, **overrides)

    view_model = build_summary_view_model(summary)

    assert summary.outcome == expected_outcome
    assert view_model.heading == expected_heading
    assert view_model.sections


def test_no_images_has_specific_summary_message(tmp_path: Path) -> None:
    summary = _summary(
        tmp_path,
        discovered_images=0,
        processed_images=0,
        successful_images=0,
    )

    view_model = build_summary_view_model(summary)

    assert view_model.heading == "Nothing to process"
    assert view_model.status_message == "No PNG images found"


def test_main_window_completion_opens_one_modal_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    class FakeButton:
        def __init__(self) -> None:
            self.enabled = None

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = enabled

    class FakeDialog:
        def __init__(self, summary, parent) -> None:
            calls.append(("init", summary, parent))

        def exec(self) -> None:
            calls.append(("exec",))

    class FakeWindow:
        def __init__(self) -> None:
            self.btn_process = FakeButton()
            self.btn_stop = FakeButton()
            self.animation_stopped = False
            self.settings_enabled = None
            self.status = None

        def _stop_processing_animation(self) -> None:
            self.animation_stopped = True

        def _set_settings_buttons_enabled(self, enabled: bool) -> None:
            self.settings_enabled = enabled

        def _set_status(self, message: str, level: str) -> None:
            self.status = (message, level)

    monkeypatch.setattr(gui_module, "ProcessingSummaryDialog", FakeDialog)
    window = FakeWindow()
    summary = _summary(tmp_path)

    MainWindow._on_processing_completed(window, summary)

    assert window.btn_process.enabled is True
    assert window.btn_stop.enabled is False
    assert window.animation_stopped is True
    assert window.settings_enabled is True
    assert window.status == ("Processing completed", "success")
    assert calls == [("init", summary, window), ("exec",)]
