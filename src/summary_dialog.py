"""Modal processing-summary dialog and its testable presentation model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from src.results import ProcessingOutcome, ProcessingSummary


@dataclass(frozen=True)
class SummarySection:
    """One labelled group of counters displayed in the summary dialog."""

    title: str
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SummaryViewModel:
    """Qt-independent presentation data derived from a processing summary."""

    title: str
    heading: str
    description: str
    icon_name: str
    status_message: str
    status_level: str
    sections: tuple[SummarySection, ...]
    paths: tuple[tuple[str, str], ...]
    error_detail: Optional[str] = None


def build_summary_view_model(summary: ProcessingSummary) -> SummaryViewModel:
    """Return deterministic display data for *summary* without creating widgets."""

    outcome = summary.outcome
    presentations = {
        ProcessingOutcome.CLEAN: (
            "Processing summary",
            "Processing completed",
            "All requested outputs were created successfully.",
            "information",
            "Processing completed",
            "success",
        ),
        ProcessingOutcome.RECOVERED: (
            "Processing summary",
            "Processing completed after retries",
            "One or more commands succeeded on their second attempt.",
            "warning",
            "Processing completed after retries",
            "warning",
        ),
        ProcessingOutcome.PARTIAL: (
            "Processing summary",
            "Processing completed with errors",
            "Some requested outputs could not be created. Other work continued.",
            "warning",
            "Processing completed with errors",
            "warning",
        ),
        ProcessingOutcome.FATAL: (
            "Processing failed",
            "Processing failed",
            "An unexpected error stopped the processing pipeline.",
            "critical",
            "Processing failed - check logging.log",
            "error",
        ),
        ProcessingOutcome.CANCELLED: (
            "Processing summary",
            "Processing cancelled",
            "Processing was stopped by the user.",
            "warning",
            "Processing cancelled",
            "warning",
        ),
    }

    title, heading, description, icon_name, status_message, status_level = (
        presentations[outcome]
    )
    if outcome == ProcessingOutcome.CLEAN and summary.discovered_images == 0:
        heading = "Nothing to process"
        description = "No PNG images were found in the selected directory."
        status_message = "No PNG images found"
        status_level = "warning"

    image_rows = [
        ("Images found", str(summary.discovered_images)),
        ("Processed", str(summary.processed_images)),
        ("Successful", str(summary.successful_images)),
        ("Partially successful", str(summary.partially_successful_images)),
        ("Failed", str(summary.failed_images)),
        ("Skipped", str(summary.skipped_images)),
    ]
    if summary.not_processed_images or outcome in {
        ProcessingOutcome.FATAL,
        ProcessingOutcome.CANCELLED,
    }:
        image_rows.append(("Not processed", str(summary.not_processed_images)))

    sections = (
        SummarySection("Images", tuple(image_rows)),
        SummarySection(
            "Outputs",
            (
                ("Successful", str(summary.successful_outputs)),
                ("Failed", str(summary.failed_outputs)),
                ("Skipped", str(summary.skipped_outputs)),
            ),
        ),
        SummarySection(
            "Commands",
            (
                ("Successful", str(summary.successful_commands)),
                ("Retried", str(summary.retried_commands)),
                ("Recovered on second attempt", str(summary.recovered_commands)),
                ("Failed after two attempts", str(summary.failed_commands)),
                (
                    "Skipped because a prerequisite failed",
                    str(summary.dependency_skipped_commands),
                ),
                ("Other operation failures", str(summary.operation_failures)),
            ),
        ),
    )

    paths = [("Output directory", str(summary.output_dir))]
    has_permanent_errors = bool(
        summary.failed_images
        or summary.failed_outputs
        or summary.failed_commands
        or summary.operation_failures
    )
    if has_permanent_errors:
        paths.append(("Errors log", str(summary.errors_log_path)))
    if outcome == ProcessingOutcome.FATAL:
        paths.append(("Full log", str(summary.logging_log_path)))

    return SummaryViewModel(
        title=title,
        heading=heading,
        description=description,
        icon_name=icon_name,
        status_message=status_message,
        status_level=status_level,
        sections=sections,
        paths=tuple(paths),
        error_detail=summary.fatal_error if outcome == ProcessingOutcome.FATAL else None,
    )


class ProcessingSummaryDialog(QDialog):
    """Display the final processing result in a modal child dialog."""

    _ICON_PIXMAPS = {
        "information": QStyle.StandardPixmap.SP_MessageBoxInformation,
        "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
        "critical": QStyle.StandardPixmap.SP_MessageBoxCritical,
    }

    def __init__(
        self,
        summary: ProcessingSummary,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.view_model = build_summary_view_model(summary)
        self.setWindowTitle(self.view_model.title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setMinimumWidth(560)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        icon_label = QLabel(self)
        icon_label.setObjectName("summaryIcon")
        standard_pixmap = self._ICON_PIXMAPS[self.view_model.icon_name]
        icon_label.setPixmap(self.style().standardIcon(standard_pixmap).pixmap(40, 40))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        heading_label = QLabel(self.view_model.heading, self)
        heading_label.setObjectName("summaryHeading")
        heading_font = heading_label.font()
        heading_font.setBold(True)
        heading_font.setPointSize(heading_font.pointSize() + 2)
        heading_label.setFont(heading_font)
        heading_label.setTextFormat(Qt.TextFormat.PlainText)
        text_layout.addWidget(heading_label)

        description_label = QLabel(self.view_model.description, self)
        description_label.setObjectName("summaryDescription")
        description_label.setWordWrap(True)
        description_label.setTextFormat(Qt.TextFormat.PlainText)
        text_layout.addWidget(description_label)
        header_layout.addLayout(text_layout, 1)
        layout.addLayout(header_layout)

        for section in self.view_model.sections:
            group = QGroupBox(section.title, self)
            group_layout = QGridLayout(group)
            for row, (label_text, value_text) in enumerate(section.rows):
                label = QLabel(label_text, group)
                value = QLabel(value_text, group)
                value.setAlignment(Qt.AlignmentFlag.AlignRight)
                value.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                group_layout.addWidget(label, row, 0)
                group_layout.addWidget(value, row, 1)
            group_layout.setColumnStretch(0, 1)
            layout.addWidget(group)

        if self.view_model.error_detail:
            error_group = QGroupBox("Error", self)
            error_layout = QVBoxLayout(error_group)
            error_label = QLabel(self.view_model.error_detail, error_group)
            error_label.setObjectName("summaryErrorDetail")
            error_label.setWordWrap(True)
            error_label.setTextFormat(Qt.TextFormat.PlainText)
            error_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            error_layout.addWidget(error_label)
            layout.addWidget(error_group)

        paths_group = QGroupBox("Locations", self)
        paths_layout = QGridLayout(paths_group)
        for row, (label_text, path_text) in enumerate(self.view_model.paths):
            label = QLabel(label_text, paths_group)
            path = QLabel(path_text, paths_group)
            path.setWordWrap(True)
            path.setTextFormat(Qt.TextFormat.PlainText)
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            paths_layout.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            paths_layout.addWidget(path, row, 1)
        paths_layout.setColumnStretch(1, 1)
        layout.addWidget(paths_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        buttons.setObjectName("summaryButtons")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
