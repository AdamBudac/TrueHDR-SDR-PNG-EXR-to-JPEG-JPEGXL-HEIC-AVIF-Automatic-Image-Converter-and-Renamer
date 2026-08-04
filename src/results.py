"""Result models shared by conversion, worker, CLI, and GUI layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Tuple


class StepStatus(Enum):
    """Outcome of one conversion step."""

    SUCCESS = auto()
    FAILED = auto()
    SKIPPED_DEPENDENCY = auto()


class OutputStatus(Enum):
    """Outcome of one requested codec output."""

    SUCCESS = auto()
    FAILED = auto()
    SKIPPED = auto()


class ImageStatus(Enum):
    """Aggregated outcome for one source image."""

    SUCCESS = auto()
    PARTIAL = auto()
    FAILED = auto()
    SKIPPED = auto()


class ProcessingOutcome(Enum):
    """Top-level outcome displayed by the CLI and summary dialog."""

    CLEAN = auto()
    RECOVERED = auto()
    PARTIAL = auto()
    FATAL = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class CommandAttemptFailure:
    """Diagnostic information captured for one failed command attempt."""

    attempt: int
    error_type: str
    message: str
    return_code: Optional[int]
    stdout: str
    stderr: str
    traceback_text: str


@dataclass
class StepResult:
    """Result of an external command or a dependent conversion step."""

    name: str
    status: StepStatus
    command: Optional[Tuple[str, ...]] = None
    attempts: int = 0
    failures: List[CommandAttemptFailure] = field(default_factory=list)
    reason: Optional[str] = None


@dataclass
class OutputResult:
    """Result of producing one output format for an image."""

    codec: str
    status: OutputStatus
    output_path: Optional[Path] = None
    steps: List[StepResult] = field(default_factory=list)
    reason: Optional[str] = None


@dataclass
class ImageConversionResult:
    """All output results belonging to one source image."""

    source_path: Path
    outputs: List[OutputResult] = field(default_factory=list)
    skipped_reason: Optional[str] = None
    unexpected_error: Optional[str] = None

    @property
    def status(self) -> ImageStatus:
        attempted = [
            output for output in self.outputs if output.status != OutputStatus.SKIPPED
        ]
        if not attempted:
            return ImageStatus.SKIPPED

        successes = sum(
            output.status == OutputStatus.SUCCESS for output in attempted
        )
        failures = sum(output.status == OutputStatus.FAILED for output in attempted)
        if failures == 0:
            return ImageStatus.SUCCESS
        if successes == 0:
            return ImageStatus.FAILED
        return ImageStatus.PARTIAL

    @classmethod
    def skipped(cls, source_path: Path, reason: str) -> "ImageConversionResult":
        return cls(source_path=source_path, skipped_reason=reason)

    @classmethod
    def failed_unexpected(
        cls, source_path: Path, error: str
    ) -> "ImageConversionResult":
        return cls(
            source_path=source_path,
            outputs=[
                OutputResult(
                    codec="image",
                    status=OutputStatus.FAILED,
                    steps=[
                        StepResult(
                            name="convert_image",
                            status=StepStatus.FAILED,
                            reason="Unexpected image-level processing error",
                        )
                    ],
                    reason="Unexpected image-level processing error",
                )
            ],
            unexpected_error=error,
        )


@dataclass
class ProcessingSummary:
    """Aggregated counters and paths for one processing run."""

    output_dir: Path
    logging_log_path: Path
    rename_log_path: Path
    errors_log_path: Path
    discovered_images: int = 0
    processed_images: int = 0
    successful_images: int = 0
    partially_successful_images: int = 0
    failed_images: int = 0
    skipped_images: int = 0
    successful_outputs: int = 0
    failed_outputs: int = 0
    skipped_outputs: int = 0
    successful_commands: int = 0
    retried_commands: int = 0
    recovered_commands: int = 0
    failed_commands: int = 0
    dependency_skipped_commands: int = 0
    operation_failures: int = 0
    cancelled: bool = False
    fatal_error: Optional[str] = None
    fatal_traceback: Optional[str] = None

    @property
    def not_processed_images(self) -> int:
        return max(
            self.discovered_images - self.processed_images - self.skipped_images,
            0,
        )

    @property
    def outcome(self) -> ProcessingOutcome:
        if self.fatal_error:
            return ProcessingOutcome.FATAL
        if self.cancelled:
            return ProcessingOutcome.CANCELLED
        if (
            self.partially_successful_images
            or self.failed_images
            or self.failed_commands
            or self.operation_failures
            or self.skipped_outputs
        ):
            return ProcessingOutcome.PARTIAL
        if self.retried_commands:
            return ProcessingOutcome.RECOVERED
        return ProcessingOutcome.CLEAN

    def add_image_result(self, result: ImageConversionResult) -> None:
        """Merge one image result into this summary."""
        image_status = result.status
        if image_status == ImageStatus.SKIPPED:
            self.skipped_images += 1
        else:
            self.processed_images += 1
            if image_status == ImageStatus.SUCCESS:
                self.successful_images += 1
            elif image_status == ImageStatus.PARTIAL:
                self.partially_successful_images += 1
            else:
                self.failed_images += 1

        for output in result.outputs:
            if output.status == OutputStatus.SUCCESS:
                self.successful_outputs += 1
            elif output.status == OutputStatus.FAILED:
                self.failed_outputs += 1
            else:
                self.skipped_outputs += 1

            for step in output.steps:
                if step.command is None:
                    if step.status == StepStatus.FAILED:
                        self.operation_failures += 1
                    continue
                if step.status == StepStatus.SUCCESS:
                    self.successful_commands += 1
                elif step.status == StepStatus.FAILED:
                    self.failed_commands += 1
                elif step.status == StepStatus.SKIPPED_DEPENDENCY:
                    self.dependency_skipped_commands += 1

                if step.attempts > 1:
                    self.retried_commands += 1
                    if step.status == StepStatus.SUCCESS:
                        self.recovered_commands += 1
