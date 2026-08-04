from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from src.config import attach_file_logger
from src.converter import convert_sdr
from src.models import AppSettings
from src.results import (
    ImageConversionResult,
    ImageStatus,
    OutputResult,
    OutputStatus,
    ProcessingOutcome,
    ProcessingSummary,
    StepResult,
    StepStatus,
)
from src.worker import ProcessingWorker


ALL_TOOLS = {
    "ffmpeg": True,
    "cjpeg": True,
    "cjxl": True,
    "heif-enc": True,
    "avifenc": True,
}


class ScriptedRunner:
    """Fake command runner with per-tool outcomes and real tiny output files."""

    def __init__(
        self, outcomes: Optional[Dict[str, List[Optional[BaseException]]]] = None
    ) -> None:
        self.outcomes = {
            tool: list(tool_outcomes)
            for tool, tool_outcomes in (outcomes or {}).items()
        }
        self.commands: List[List[str]] = []

    def run_cmd(self, command: List[str], logger: logging.Logger) -> None:
        current_command = list(command)
        self.commands.append(current_command)
        tool = current_command[0]
        scripted = self.outcomes.get(tool, [])
        if scripted:
            outcome = scripted.pop(0)
            if outcome is not None:
                raise outcome

        output_path = self._output_path(current_command)
        output_path.write_bytes(b"fake output")

    @staticmethod
    def _output_path(command: List[str]) -> Path:
        tool = command[0]
        if tool == "ffmpeg":
            return Path(command[-1])
        if tool == "cjpeg":
            return Path(command[command.index("-outfile") + 1])
        if tool == "cjxl":
            return Path(command[2])
        if tool == "heif-enc":
            return Path(command[command.index("--output") + 1])
        if tool == "avifenc":
            return Path(command[-1])
        raise AssertionError(f"Unexpected fake command: {command}")


@pytest.fixture
def test_logger():
    logger = logging.Logger("retry-processing-tests", level=logging.DEBUG)
    logger.propagate = False
    logger.addHandler(logging.NullHandler())
    yield logger
    for handler in list(logger.handlers):
        handler.flush()
        logger.removeHandler(handler)
        handler.close()


def _failure(stderr: str, return_code: int = 1) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        return_code,
        ["fake-command"],
        output=b"",
        stderr=stderr.encode("utf-8"),
    )


def _settings(*enabled_codecs: str) -> AppSettings:
    settings = AppSettings()
    settings.rename_enabled = False
    settings.codec_enabled = {
        codec: codec in enabled_codecs
        for codec in ("jpeg", "jpegxl", "heic", "avif")
    }
    return settings


def _output_by_codec(result: ImageConversionResult) -> Dict[str, OutputResult]:
    return {output.codec: output for output in result.outputs}


def _flush_logger(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def test_first_attempt_fails_and_second_attempt_succeeds(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    runner = ScriptedRunner(
        {"ffmpeg": [_failure("temporary decoder failure"), None]}
    )

    result = convert_sdr(
        source,
        _settings("jpeg"),
        ALL_TOOLS,
        runner,
        test_logger,
    )

    jpeg = _output_by_codec(result)["jpeg"]
    assert jpeg.status == OutputStatus.SUCCESS
    assert jpeg.steps[0].status == StepStatus.SUCCESS
    assert jpeg.steps[0].attempts == 2
    assert len(jpeg.steps[0].failures) == 1
    assert [command[0] for command in runner.commands] == [
        "ffmpeg",
        "ffmpeg",
        "cjpeg",
    ]
    assert source.with_suffix(".jpg").read_bytes() == b"fake output"


def test_partial_output_is_removed_before_retry(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")

    class PartialOutputRunner(ScriptedRunner):
        def __init__(self) -> None:
            super().__init__()
            self.ffmpeg_attempts = 0

        def run_cmd(self, command: List[str], logger: logging.Logger) -> None:
            if command[0] != "ffmpeg":
                return super().run_cmd(command, logger)

            self.commands.append(list(command))
            self.ffmpeg_attempts += 1
            output_path = self._output_path(command)
            if self.ffmpeg_attempts == 1:
                output_path.write_bytes(b"partial")
                raise _failure("failed after writing a partial BMP")

            assert not output_path.exists()
            output_path.write_bytes(b"complete BMP")

    runner = PartialOutputRunner()

    result = convert_sdr(
        source,
        _settings("jpeg"),
        ALL_TOOLS,
        runner,
        test_logger,
    )

    jpeg = _output_by_codec(result)["jpeg"]
    assert jpeg.status == OutputStatus.SUCCESS
    assert jpeg.steps[0].attempts == 2
    assert source.with_suffix(".jpg").exists()
    assert not list(tmp_path.glob("Tempfile_*"))


def test_failed_bmp_skips_cjpeg_and_continues_with_next_codec(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    runner = ScriptedRunner(
        {
            "ffmpeg": [
                _failure("decoder failure one"),
                _failure("decoder failure two"),
            ]
        }
    )

    result = convert_sdr(
        source,
        _settings("jpeg", "jpegxl"),
        ALL_TOOLS,
        runner,
        test_logger,
    )

    outputs = _output_by_codec(result)
    assert outputs["jpeg"].status == OutputStatus.FAILED
    assert [step.status for step in outputs["jpeg"].steps] == [
        StepStatus.FAILED,
        StepStatus.SKIPPED_DEPENDENCY,
    ]
    assert outputs["jpegxl"].status == OutputStatus.SUCCESS
    assert result.status == ImageStatus.PARTIAL
    assert [command[0] for command in runner.commands] == [
        "ffmpeg",
        "ffmpeg",
        "cjxl",
    ]
    assert not source.with_suffix(".jpg").exists()
    assert source.with_suffix(".jxl").exists()


def test_failed_cjpeg_continues_with_next_codec(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    runner = ScriptedRunner(
        {
            "cjpeg": [
                _failure("jpeg encoder failure one"),
                _failure("jpeg encoder failure two"),
            ]
        }
    )

    result = convert_sdr(
        source,
        _settings("jpeg", "jpegxl"),
        ALL_TOOLS,
        runner,
        test_logger,
    )

    outputs = _output_by_codec(result)
    assert outputs["jpeg"].status == OutputStatus.FAILED
    assert outputs["jpeg"].steps[0].status == StepStatus.SUCCESS
    assert outputs["jpeg"].steps[1].status == StepStatus.FAILED
    assert outputs["jpegxl"].status == OutputStatus.SUCCESS
    assert [command[0] for command in runner.commands] == [
        "ffmpeg",
        "cjpeg",
        "cjpeg",
        "cjxl",
    ]
    assert not source.with_suffix(".jpg").exists()
    assert source.with_suffix(".jxl").exists()


def test_interrupted_error_is_not_retried(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    runner = ScriptedRunner(
        {"ffmpeg": [InterruptedError("cancelled by test")]}
    )

    with pytest.raises(InterruptedError, match="cancelled by test"):
        convert_sdr(
            source,
            _settings("jpeg", "jpegxl"),
            ALL_TOOLS,
            runner,
            test_logger,
        )

    assert [command[0] for command in runner.commands] == ["ffmpeg"]
    assert not list(tmp_path.glob("Tempfile_*"))


def test_errors_log_contains_only_final_failures_with_command_and_stderr(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    logging_log = tmp_path / "logging.log"
    errors_log = tmp_path / "errors.log"
    attach_file_logger(test_logger, logging_log, errors_log)
    runner = ScriptedRunner(
        {
            "ffmpeg": [_failure("transient decoder failure"), None],
            "cjpeg": [
                _failure("final encoder failure one"),
                _failure("final encoder failure two"),
            ],
        }
    )

    convert_sdr(
        source,
        _settings("jpeg"),
        ALL_TOOLS,
        runner,
        test_logger,
    )
    _flush_logger(test_logger)

    main_content = logging_log.read_text(encoding="utf-8")
    error_content = errors_log.read_text(encoding="utf-8")
    assert "transient decoder failure" in main_content
    assert "transient decoder failure" not in error_content
    assert "COMMAND_FAILED" in error_content
    assert "Stage: bmp_to_jpeg" in error_content
    assert "Command: cjpeg" in error_content
    assert "Attempt 1 stderr:\nfinal encoder failure one" in error_content
    assert "Attempt 2 stderr:\nfinal encoder failure two" in error_content


def test_recovered_command_leaves_errors_log_empty(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    source = tmp_path / "photo.png"
    source.write_bytes(b"png")
    logging_log = tmp_path / "logging.log"
    errors_log = tmp_path / "errors.log"
    attach_file_logger(test_logger, logging_log, errors_log)
    runner = ScriptedRunner(
        {"ffmpeg": [_failure("transient decoder failure"), None]}
    )

    result = convert_sdr(
        source,
        _settings("jpeg"),
        ALL_TOOLS,
        runner,
        test_logger,
    )
    _flush_logger(test_logger)

    assert result.status == ImageStatus.SUCCESS
    assert errors_log.exists()
    assert errors_log.read_text(encoding="utf-8") == ""


def test_processing_summary_counters_and_outcomes(tmp_path: Path) -> None:
    summary = ProcessingSummary(
        output_dir=tmp_path,
        logging_log_path=tmp_path / "logging.log",
        rename_log_path=tmp_path / "rename.log",
        errors_log_path=tmp_path / "errors.log",
        discovered_images=4,
    )
    recovered = ImageConversionResult(
        source_path=tmp_path / "recovered.png",
        outputs=[
            OutputResult(
                codec="jpeg",
                status=OutputStatus.SUCCESS,
                steps=[
                    StepResult(
                        name="png_to_bmp",
                        status=StepStatus.SUCCESS,
                        command=("ffmpeg",),
                        attempts=2,
                    )
                ],
            )
        ],
    )
    partial = ImageConversionResult(
        source_path=tmp_path / "partial.png",
        outputs=[
            OutputResult(
                codec="jpeg",
                status=OutputStatus.FAILED,
                steps=[
                    StepResult(
                        name="png_to_bmp",
                        status=StepStatus.FAILED,
                        command=("ffmpeg",),
                        attempts=2,
                    ),
                    StepResult(
                        name="bmp_to_jpeg",
                        status=StepStatus.SKIPPED_DEPENDENCY,
                        command=("cjpeg",),
                    ),
                ],
            ),
            OutputResult(
                codec="jpegxl",
                status=OutputStatus.SUCCESS,
                steps=[
                    StepResult(
                        name="png_to_jpegxl",
                        status=StepStatus.SUCCESS,
                        command=("cjxl",),
                        attempts=1,
                    )
                ],
            ),
        ],
    )
    failed = ImageConversionResult(
        source_path=tmp_path / "failed.png",
        outputs=[
            OutputResult(
                codec="avif",
                status=OutputStatus.FAILED,
                steps=[
                    StepResult(
                        name="png_to_avif",
                        status=StepStatus.FAILED,
                        command=("avifenc",),
                        attempts=1,
                    )
                ],
            )
        ],
    )
    skipped = ImageConversionResult(
        source_path=tmp_path / "skipped.png",
        outputs=[
            OutputResult(codec="heic", status=OutputStatus.SKIPPED)
        ],
        skipped_reason="HEIC tool unavailable",
    )

    summary.add_image_result(recovered)
    assert summary.outcome == ProcessingOutcome.RECOVERED
    summary.add_image_result(partial)
    summary.add_image_result(failed)
    summary.add_image_result(skipped)

    assert summary.processed_images == 3
    assert summary.successful_images == 1
    assert summary.partially_successful_images == 1
    assert summary.failed_images == 1
    assert summary.skipped_images == 1
    assert summary.successful_outputs == 2
    assert summary.failed_outputs == 2
    assert summary.skipped_outputs == 1
    assert summary.successful_commands == 2
    assert summary.failed_commands == 2
    assert summary.retried_commands == 2
    assert summary.recovered_commands == 1
    assert summary.dependency_skipped_commands == 1
    assert summary.not_processed_images == 0
    assert summary.outcome == ProcessingOutcome.PARTIAL


def test_worker_continues_with_next_image_and_reaches_total_progress(
    tmp_path: Path, test_logger: logging.Logger
) -> None:
    (tmp_path / "a.png").write_bytes(b"png a")
    (tmp_path / "b.png").write_bytes(b"png b")
    runner = ScriptedRunner(
        {
            "ffmpeg": [
                _failure("a failed once"),
                _failure("a failed twice"),
                None,
            ]
        }
    )
    worker = ProcessingWorker(
        tmp_path,
        _settings("jpeg"),
        ALL_TOOLS,
        test_logger,
    )
    worker.runner = runner
    progress_updates = []

    def record_progress(current: int, total: int) -> None:
        progress_updates.append((current, total))

    worker.progress.connect(record_progress)
    summary = worker.process()

    assert [command[0] for command in runner.commands] == [
        "ffmpeg",
        "ffmpeg",
        "ffmpeg",
        "cjpeg",
    ]
    assert summary.discovered_images == 2
    assert summary.processed_images == 2
    assert summary.successful_images == 1
    assert summary.failed_images == 1
    assert summary.failed_commands == 1
    assert summary.dependency_skipped_commands == 1
    assert progress_updates == [(1, 2), (2, 2)]
    assert summary.outcome == ProcessingOutcome.PARTIAL
    assert not (tmp_path / "output" / "a.jpg").exists()
    assert (tmp_path / "output" / "b.jpg").exists()
