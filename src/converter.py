"""Image converter – calls external CLI tools to encode images.

All functions are **stateless**; they receive everything they need as arguments.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import threading
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from uuid import uuid4

from src.models import AppSettings, TOOLS_FOR_CODECS
from src.results import (
    CommandAttemptFailure,
    ImageConversionResult,
    OutputResult,
    OutputStatus,
    StepResult,
    StepStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def required_tools_missing(codec: str, tool_map: Dict[str, bool]) -> List[str]:
    """Return the list of tools required by *codec* that are **not** available."""
    required = TOOLS_FOR_CODECS.get(codec, [])
    return [t for t in required if not tool_map.get(t, False)]


class ProcessRunner:
    """Manages execution of subprocesses and allows aggressive cancellation."""

    def __init__(self):
        self._active_process: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Mark as cancelled and kill the currently running process if any."""
        with self._lock:
            self._cancelled = True
            if self._active_process is not None:
                try:
                    self._active_process.kill()
                except Exception:
                    pass

    def run_cmd(self, command: List[str], logger: logging.Logger) -> None:
        """Execute one command attempt as a subprocess."""
        with self._lock:
            if self._cancelled:
                raise InterruptedError("Cancelled by user")

        logger.info("Running: %s", format_command(command))
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )

        with self._lock:
            self._active_process = proc
            cancel_after_start = self._cancelled

        if cancel_after_start:
            try:
                proc.kill()
            except Exception:
                pass

        try:
            stdout, stderr = proc.communicate()
        finally:
            with self._lock:
                if self._active_process is proc:
                    self._active_process = None

        with self._lock:
            if self._cancelled:
                raise InterruptedError("Cancelled by user")

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, command, stdout, stderr)



# ---------------------------------------------------------------------------
# Command execution helpers
# ---------------------------------------------------------------------------

MAX_COMMAND_ATTEMPTS = 2
MAX_DIAGNOSTIC_CHARS = 64 * 1024


class MissingCommandOutputError(RuntimeError):
    """Raised when a successful command did not create a usable output."""


def format_command(command: Sequence[str]) -> str:
    """Return a copy/paste-friendly representation of *command*."""
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))
    return shlex.join(command)


def _decode_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    else:
        text = str(value)
    if len(text) <= MAX_DIAGNOSTIC_CHARS:
        return text
    omitted = len(text) - MAX_DIAGNOSTIC_CHARS
    return f"{text[:MAX_DIAGNOSTIC_CHARS]}\n... [{omitted} characters truncated]"


def _capture_attempt_failure(
    attempt: int, exc: BaseException
) -> CommandAttemptFailure:
    return_code = None
    stdout = ""
    stderr = ""
    if isinstance(exc, subprocess.CalledProcessError):
        return_code = exc.returncode
        stdout = _decode_output(exc.stdout)
        stderr = _decode_output(exc.stderr)
    return CommandAttemptFailure(
        attempt=attempt,
        error_type=type(exc).__name__,
        message=str(exc),
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        traceback_text=traceback.format_exc(),
    )


def _last_nonempty_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _log_final_command_failure(
    logger: logging.Logger,
    image_path: Path,
    codec: str,
    stage: str,
    command: Sequence[str],
    failures: Sequence[CommandAttemptFailure],
    dependent_step: Optional[str] = None,
) -> None:
    lines = [
        "COMMAND_FAILED",
        f"Image: {image_path}",
        f"Codec: {codec}",
        f"Stage: {stage}",
        f"Command: {format_command(command)}",
        f"Attempts: {len(failures)}/{MAX_COMMAND_ATTEMPTS}",
    ]
    if failures and failures[-1].return_code is not None:
        lines.append(f"Return code: {failures[-1].return_code}")
    if dependent_step:
        lines.append(f"Dependent step skipped: {dependent_step}")

    for failure in failures:
        lines.extend(
            [
                "",
                f"Attempt {failure.attempt} error: "
                f"{failure.error_type}: {failure.message}",
            ]
        )
        if failure.stdout:
            lines.extend([f"Attempt {failure.attempt} stdout:", failure.stdout])
        if failure.stderr:
            lines.extend([f"Attempt {failure.attempt} stderr:", failure.stderr])

    if failures:
        lines.extend(["", "Final traceback:", failures[-1].traceback_text])
    lines.extend(["", "-" * 80])
    logger.error("\n".join(lines), extra={"error_log": True})


def log_operation_failure(
    logger: logging.Logger,
    image_path: Path,
    operation: str,
    exc: BaseException,
    details: Optional[str] = None,
) -> None:
    """Write one non-command, image-level failure to both run logs."""
    lines = [
        "OPERATION_FAILED",
        f"Image: {image_path}",
        f"Operation: {operation}",
    ]
    if details:
        lines.append(f"Details: {details}")
    lines.extend(
        [
            f"Error: {type(exc).__name__}: {exc}",
            "",
            "Traceback:",
            traceback.format_exc(),
            "",
            "-" * 80,
        ]
    )
    logger.error("\n".join(lines), extra={"error_log": True})


def _remove_partial_output(path: Path) -> None:
    path.unlink(missing_ok=True)


def _run_command_with_retry(
    *,
    command: List[str],
    expected_output: Path,
    image_path: Path,
    codec: str,
    stage: str,
    runner: ProcessRunner,
    logger: logging.Logger,
    dependent_step: Optional[str] = None,
) -> StepResult:
    """Run one exact command at most twice and return a structured result."""
    failures: List[CommandAttemptFailure] = []
    for attempt in range(1, MAX_COMMAND_ATTEMPTS + 1):
        try:
            _remove_partial_output(expected_output)
        except InterruptedError:
            raise
        except OSError as exc:
            failure = _capture_attempt_failure(attempt, exc)
            log_operation_failure(
                logger,
                image_path,
                f"prepare_{stage}",
                exc,
                f"Could not remove partial output before attempt {attempt}: "
                f"{expected_output}",
            )
            return StepResult(
                name=f"prepare_{stage}",
                status=StepStatus.FAILED,
                attempts=0,
                failures=[failure],
                reason=str(exc),
            )

        try:
            logger.info(
                "Command attempt %s/%s for %s (%s: %s)",
                attempt,
                MAX_COMMAND_ATTEMPTS,
                image_path.name,
                codec,
                stage,
            )
            runner.run_cmd(command, logger)
            if (
                not expected_output.is_file()
                or expected_output.stat().st_size <= 0
            ):
                raise MissingCommandOutputError(
                    f"Command completed without a usable output: {expected_output}"
                )
            if attempt > 1:
                logger.info(
                    "Command recovered on attempt %s/%s for %s (%s: %s)",
                    attempt,
                    MAX_COMMAND_ATTEMPTS,
                    image_path.name,
                    codec,
                    stage,
                )
            return StepResult(
                name=stage,
                status=StepStatus.SUCCESS,
                command=tuple(command),
                attempts=attempt,
                failures=failures,
            )
        except InterruptedError:
            raise
        except (subprocess.SubprocessError, OSError, MissingCommandOutputError) as exc:
            failure = _capture_attempt_failure(attempt, exc)
            failures.append(failure)
            diagnostic = _last_nonempty_line(failure.stderr) or failure.message
            if attempt < MAX_COMMAND_ATTEMPTS:
                logger.warning(
                    "Command failed for %s (%s: %s), attempt %s/%s: %s. Retrying.",
                    image_path.name,
                    codec,
                    stage,
                    attempt,
                    MAX_COMMAND_ATTEMPTS,
                    diagnostic,
                )
                continue

            _log_final_command_failure(
                logger,
                image_path,
                codec,
                stage,
                command,
                failures,
                dependent_step,
            )
            try:
                _remove_partial_output(expected_output)
            except OSError as cleanup_exc:
                logger.warning(
                    "Failed to remove partial output %s: %s",
                    expected_output,
                    cleanup_exc,
                )
            return StepResult(
                name=stage,
                status=StepStatus.FAILED,
                command=tuple(command),
                attempts=attempt,
                failures=failures,
                reason=diagnostic,
            )

    raise AssertionError("Command retry loop terminated unexpectedly")


def _publish_output(
    *,
    temp_path: Path,
    final_path: Path,
    image_path: Path,
    codec: str,
    logger: logging.Logger,
) -> StepResult:
    stage = f"publish_{codec}"
    try:
        temp_path.rename(final_path)
        return StepResult(name=stage, status=StepStatus.SUCCESS)
    except OSError as exc:
        failure = _capture_attempt_failure(1, exc)
        log_operation_failure(
            logger,
            image_path,
            stage,
            exc,
            f"{temp_path} -> {final_path}",
        )
        return StepResult(
            name=stage,
            status=StepStatus.FAILED,
            attempts=1,
            failures=[failure],
            reason=str(exc),
        )


def _direct_output(
    *,
    codec: str,
    stage: str,
    command: List[str],
    temp_path: Path,
    final_path: Path,
    image_path: Path,
    runner: ProcessRunner,
    logger: logging.Logger,
) -> OutputResult:
    command_result = _run_command_with_retry(
        command=command,
        expected_output=temp_path,
        image_path=image_path,
        codec=codec,
        stage=stage,
        runner=runner,
        logger=logger,
    )
    steps = [command_result]
    if command_result.status == StepStatus.FAILED:
        return OutputResult(
            codec=codec,
            status=OutputStatus.FAILED,
            output_path=final_path,
            steps=steps,
            reason=command_result.reason,
        )

    publish_result = _publish_output(
        temp_path=temp_path,
        final_path=final_path,
        image_path=image_path,
        codec=codec,
        logger=logger,
    )
    steps.append(publish_result)
    return OutputResult(
        codec=codec,
        status=(
            OutputStatus.SUCCESS
            if publish_result.status == StepStatus.SUCCESS
            else OutputStatus.FAILED
        ),
        output_path=final_path,
        steps=steps,
        reason=publish_result.reason,
    )


def _unavailable_output(
    codec: str, image_path: Path, missing_tools: Sequence[str], logger: logging.Logger
) -> OutputResult:
    reason = f"Missing tools: {', '.join(missing_tools)}"
    logger.warning("Skipping %s for %s – %s", codec, image_path.name, reason)
    return OutputResult(codec=codec, status=OutputStatus.SKIPPED, reason=reason)


def _cleanup_temp_files(paths: Sequence[Path], logger: logging.Logger) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to clean temporary file %s: %s", path, exc)


# ---------------------------------------------------------------------------
# SDR conversion
# ---------------------------------------------------------------------------

def convert_sdr(
    png_file: Path,
    settings: AppSettings,
    tool_map: Dict[str, bool],
    runner: ProcessRunner,
    logger: logging.Logger,
) -> ImageConversionResult:
    """Convert one SDR PNG while isolating failures between codec outputs."""
    result = ImageConversionResult(source_path=png_file)
    stem = png_file.with_suffix("")
    temp_base = png_file.with_name(f"Tempfile_{uuid4().hex}")
    temp_bmp = temp_base.with_suffix(".bmp")
    temp_jpg = temp_base.with_suffix(".jpg")
    temp_jxl = temp_base.with_suffix(".jxl")
    temp_heic = temp_base.with_suffix(".heic")
    temp_avif = temp_base.with_suffix(".avif")
    temp_files = [temp_bmp, temp_jpg, temp_jxl, temp_heic, temp_avif]
    _cleanup_temp_files(temp_files, logger)

    try:
        if settings.codec_enabled.get("jpeg"):
            missing = required_tools_missing("jpeg", tool_map)
            if missing:
                result.outputs.append(
                    _unavailable_output("jpeg", png_file, missing, logger)
                )
            else:
                ffmpeg_command = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(png_file),
                    "-pix_fmt",
                    "rgb24",
                    str(temp_bmp),
                ]
                bmp_result = _run_command_with_retry(
                    command=ffmpeg_command,
                    expected_output=temp_bmp,
                    image_path=png_file,
                    codec="jpeg",
                    stage="png_to_bmp",
                    runner=runner,
                    logger=logger,
                    dependent_step="bmp_to_jpeg (cjpeg)",
                )
                jpeg_steps = [bmp_result]
                if bmp_result.status == StepStatus.FAILED:
                    cjpeg_command = [
                        "cjpeg",
                        "-quality",
                        str(settings.codec_quality["jpeg"]),
                        "-optimize",
                        "-precision",
                        "8",
                        "-outfile",
                        str(temp_jpg),
                        str(temp_bmp),
                    ]
                    jpeg_steps.append(
                        StepResult(
                            name="bmp_to_jpeg",
                            status=StepStatus.SKIPPED_DEPENDENCY,
                            command=tuple(cjpeg_command),
                            reason="png_to_bmp failed after two attempts",
                        )
                    )
                    logger.warning(
                        "Skipping cjpeg for %s because the BMP prerequisite failed",
                        png_file.name,
                    )
                    result.outputs.append(
                        OutputResult(
                            codec="jpeg",
                            status=OutputStatus.FAILED,
                            output_path=stem.with_suffix(".jpg"),
                            steps=jpeg_steps,
                            reason=bmp_result.reason,
                        )
                    )
                else:
                    cjpeg_command = [
                        "cjpeg",
                        "-quality",
                        str(settings.codec_quality["jpeg"]),
                        "-optimize",
                        "-precision",
                        "8",
                        "-outfile",
                        str(temp_jpg),
                        str(temp_bmp),
                    ]
                    jpeg_result = _run_command_with_retry(
                        command=cjpeg_command,
                        expected_output=temp_jpg,
                        image_path=png_file,
                        codec="jpeg",
                        stage="bmp_to_jpeg",
                        runner=runner,
                        logger=logger,
                    )
                    jpeg_steps.append(jpeg_result)
                    if jpeg_result.status == StepStatus.FAILED:
                        result.outputs.append(
                            OutputResult(
                                codec="jpeg",
                                status=OutputStatus.FAILED,
                                output_path=stem.with_suffix(".jpg"),
                                steps=jpeg_steps,
                                reason=jpeg_result.reason,
                            )
                        )
                    else:
                        publish_result = _publish_output(
                            temp_path=temp_jpg,
                            final_path=stem.with_suffix(".jpg"),
                            image_path=png_file,
                            codec="jpeg",
                            logger=logger,
                        )
                        jpeg_steps.append(publish_result)
                        result.outputs.append(
                            OutputResult(
                                codec="jpeg",
                                status=(
                                    OutputStatus.SUCCESS
                                    if publish_result.status == StepStatus.SUCCESS
                                    else OutputStatus.FAILED
                                ),
                                output_path=stem.with_suffix(".jpg"),
                                steps=jpeg_steps,
                                reason=publish_result.reason,
                            )
                        )

        if settings.codec_enabled.get("jpegxl"):
            missing = required_tools_missing("jpegxl", tool_map)
            if missing:
                result.outputs.append(
                    _unavailable_output("jpegxl", png_file, missing, logger)
                )
            else:
                result.outputs.append(
                    _direct_output(
                        codec="jpegxl",
                        stage="png_to_jpegxl",
                        command=[
                            "cjxl",
                            str(png_file),
                            str(temp_jxl),
                            "--quality",
                            str(settings.codec_quality["jpegxl"]),
                            "--effort",
                            "7",
                            "--brotli_effort",
                            "11",
                            "--num_threads",
                            "-1",
                            "--gaborish",
                            "1",
                        ],
                        temp_path=temp_jxl,
                        final_path=stem.with_suffix(".jxl"),
                        image_path=png_file,
                        runner=runner,
                        logger=logger,
                    )
                )

        if settings.codec_enabled.get("heic"):
            missing = required_tools_missing("heic", tool_map)
            if missing:
                result.outputs.append(
                    _unavailable_output("heic", png_file, missing, logger)
                )
            else:
                result.outputs.append(
                    _direct_output(
                        codec="heic",
                        stage="png_to_heic",
                        command=[
                            "heif-enc",
                            "--thumb",
                            "off",
                            "--no-alpha",
                            "--no-thumb-alpha",
                            "--bit-depth",
                            "8",
                            "--quality",
                            str(settings.codec_quality["heic"]),
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
                            f"quality={settings.codec_quality['heic']}",
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
                        temp_path=temp_heic,
                        final_path=stem.with_suffix(".heic"),
                        image_path=png_file,
                        runner=runner,
                        logger=logger,
                    )
                )

        if settings.codec_enabled.get("avif"):
            missing = required_tools_missing("avif", tool_map)
            if missing:
                result.outputs.append(
                    _unavailable_output("avif", png_file, missing, logger)
                )
            else:
                result.outputs.append(
                    _direct_output(
                        codec="avif",
                        stage="png_to_avif",
                        command=[
                            "avifenc",
                            "--codec",
                            "aom",
                            "--speed",
                            "6",
                            "--qcolor",
                            str(settings.codec_quality["avif"]),
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
                        temp_path=temp_avif,
                        final_path=stem.with_suffix(".avif"),
                        image_path=png_file,
                        runner=runner,
                        logger=logger,
                    )
                )
    finally:
        _cleanup_temp_files(temp_files, logger)

    return result


# ---------------------------------------------------------------------------
# HDR conversion
# ---------------------------------------------------------------------------

def convert_hdr(
    png_file: Path,
    settings: AppSettings,
    tool_map: Dict[str, bool],
    runner: ProcessRunner,
    logger: logging.Logger,
) -> ImageConversionResult:
    """Convert one HDR PNG while isolating failures between codec outputs."""
    result = ImageConversionResult(source_path=png_file)
    stem = png_file.with_suffix("")
    temp_base = png_file.with_name(f"Tempfile_{uuid4().hex}")
    temp_bmp = temp_base.with_suffix(".bmp")
    temp_jpg = temp_base.with_suffix(".jpg")
    temp_jxl = temp_base.with_suffix(".jxl")
    temp_heic = temp_base.with_suffix(".heic")
    temp_avif = temp_base.with_suffix(".avif")
    temp_files = [temp_bmp, temp_jpg, temp_jxl, temp_heic, temp_avif]
    _cleanup_temp_files(temp_files, logger)

    try:
        if settings.codec_enabled.get("jpegxl"):
            missing = required_tools_missing("jpegxl", tool_map)
            if missing:
                result.outputs.append(
                    _unavailable_output("jpegxl", png_file, missing, logger)
                )
            else:
                result.outputs.append(
                    _direct_output(
                        codec="jpegxl",
                        stage="png_to_jpegxl_hdr",
                        command=[
                            "cjxl",
                            str(png_file),
                            str(temp_jxl),
                            "--quality",
                            str(settings.codec_quality["jpegxl"]),
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
                        temp_path=temp_jxl,
                        final_path=stem.with_suffix(".jxl"),
                        image_path=png_file,
                        runner=runner,
                        logger=logger,
                    )
                )

        if settings.codec_enabled.get("heic"):
            missing = required_tools_missing("heic", tool_map)
            if missing:
                result.outputs.append(
                    _unavailable_output("heic", png_file, missing, logger)
                )
            else:
                result.outputs.append(
                    _direct_output(
                        codec="heic",
                        stage="png_to_heic_hdr",
                        command=[
                            "heif-enc",
                            "--thumb",
                            "off",
                            "--no-alpha",
                            "--no-thumb-alpha",
                            "--bit-depth",
                            "10",
                            "--quality",
                            str(settings.codec_quality["heic"]),
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
                            f"quality={settings.codec_quality['heic']}",
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
                        temp_path=temp_heic,
                        final_path=stem.with_suffix(".heic"),
                        image_path=png_file,
                        runner=runner,
                        logger=logger,
                    )
                )

        if settings.codec_enabled.get("avif"):
            missing = required_tools_missing("avif", tool_map)
            if missing:
                result.outputs.append(
                    _unavailable_output("avif", png_file, missing, logger)
                )
            else:
                result.outputs.append(
                    _direct_output(
                        codec="avif",
                        stage="png_to_avif_hdr",
                        command=[
                            "avifenc",
                            "--codec",
                            "aom",
                            "--speed",
                            "6",
                            "--qcolor",
                            str(settings.codec_quality["avif"]),
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
                        temp_path=temp_avif,
                        final_path=stem.with_suffix(".avif"),
                        image_path=png_file,
                        runner=runner,
                        logger=logger,
                    )
                )
    finally:
        _cleanup_temp_files(temp_files, logger)

    return result
