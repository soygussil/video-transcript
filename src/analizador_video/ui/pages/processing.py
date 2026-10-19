"""Procesamiento: etapas con progreso real, dispositivo, advertencias no bloqueantes y cancelación."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from analizador_video.application import events as ev
from analizador_video.domain.errors import UserMessage
from analizador_video.ui import strings as T
from analizador_video.ui.widgets.common import MessageBanner, label

SUCCESS_STATES = {"completed", "completed_with_warnings", "reutilizada"}


class _StageRow:
    def __init__(self, grid: QGridLayout, row: int, stage: str):
        self.name = label(T.STAGE_LABELS.get(stage, stage), wrap=False)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setAccessibleName(T.STAGE_LABELS.get(stage, stage))
        self.status = label(T.STAGE_STATUS["pending"], "Muted", wrap=False)
        self.detail = label("", "Muted")
        for column, widget in enumerate((self.name, self.bar, self.status, self.detail)):
            grid.addWidget(widget, row, column)
        self.fraction = 0.0
        self.first_done: tuple[float, int] | None = None


class ProcessingPage(QWidget):
    cancelRequested = Signal()
    resultsRequested = Signal(Path)
    homeRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.rows: dict[str, _StageRow] = {}
        self.project_root: Path | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        self.title = label(T.PROCESSING_TITLE, "Title")
        root.addWidget(self.title)
        self.device = label("", "Muted")
        root.addWidget(self.device)
        overall_row = QHBoxLayout()
        overall_row.addWidget(label(T.OVERALL, wrap=False))
        self.overall = QProgressBar()
        self.overall.setRange(0, 100)
        self.overall.setAccessibleName(T.OVERALL)
        overall_row.addWidget(self.overall, 1)
        self.eta = label("", "Muted", wrap=False)
        overall_row.addWidget(self.eta)
        root.addLayout(overall_row)
        grid_host = QWidget()
        self.grid = QGridLayout(grid_host)
        self.grid.setColumnStretch(1, 2)
        self.grid.setColumnStretch(3, 3)
        root.addWidget(grid_host)
        self.error = MessageBanner("error")
        root.addWidget(self.error)
        self.result = label("", "Section")
        root.addWidget(self.result)
        root.addWidget(label(T.WARNINGS_TITLE, "Section"))
        self.warnings = QListWidget()
        self.warnings.setAccessibleName(T.WARNINGS_TITLE)
        self.warnings.setMaximumHeight(110)
        self.warnings.setWordWrap(True)
        self.warnings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.warnings)
        root.addWidget(label(T.LOG_TITLE, "Section"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setAccessibleName(T.LOG_TITLE)
        self.log.setMaximumBlockCount(500)
        root.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        self.cancel = QPushButton(T.CANCEL)
        self.cancel.setObjectName("Danger")
        self.cancel.clicked.connect(self._confirm_cancel)
        self.results = QPushButton(T.VIEW_RESULTS)
        self.results.setObjectName("Primary")
        self.results.clicked.connect(self._emit_results)
        self.home = QPushButton(T.BACK_HOME)
        self.home.clicked.connect(self.homeRequested.emit)
        buttons.addWidget(self.cancel)
        buttons.addStretch(1)
        buttons.addWidget(self.home)
        buttons.addWidget(self.results)
        root.addLayout(buttons)

    def begin(self, project_root: Path, name: str, stages: list[str]) -> None:
        self.project_root = project_root
        self.title.setText(f"{T.PROCESSING_TITLE}: {name}")
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.rows = {stage: _StageRow(self.grid, i, stage) for i, stage in enumerate(stages)}
        self.overall.setValue(0)
        for widget in (self.eta, self.device, self.result):
            widget.setText("")
        self.warnings.clear()
        self.log.clear()
        self.error.hide()
        self.cancel.setEnabled(True)
        self.cancel.setText(T.CANCEL)
        self.results.hide()
        self.home.hide()

    def _emit_results(self) -> None:
        if self.project_root is not None:
            self.resultsRequested.emit(self.project_root)

    def _confirm_cancel(self) -> None:
        answer = QMessageBox.question(
            self,
            T.CANCEL,
            T.CANCEL_CONFIRM,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cancel.setEnabled(False)
            self.cancel.setText(T.CANCELLING)
            self.cancelRequested.emit()

    def _row(self, stage: str) -> _StageRow:
        if stage not in self.rows:
            self.rows[stage] = _StageRow(self.grid, len(self.rows), stage)
        return self.rows[stage]

    def _update_overall(self) -> None:
        if self.rows:
            value = int(100 * sum(r.fraction for r in self.rows.values()) / len(self.rows))
            self.overall.setValue(value)
            self.overall.setFormat(f"{value} %")

    def handle(self, event: object) -> None:
        if isinstance(event, ev.JobStarted):
            for stage in event.stages:
                self._row(stage)
        elif isinstance(event, ev.StageStarted):
            row = self._row(event.stage)
            row.status.setText(T.STAGE_STATUS["running"])
            row.first_done = None
            if event.device and event.backend not in ("dominio", "reportes"):
                self.device.setText(
                    T.DEVICE.format(device=f"{(event.backend or '').replace('_', '-')} · {event.device.upper()}")
                )
            if event.total is None:
                row.bar.setRange(0, 0)  # indeterminado mientras no se conoce el total
        elif isinstance(event, ev.StageProgress):
            row = self._row(event.stage)
            if event.total:
                row.bar.setRange(0, 100)
                row.fraction = min(1.0, event.done / event.total)
                row.bar.setValue(int(row.fraction * 100))
                row.bar.setFormat(f"{event.done} de {event.total}")
                self._update_eta(row, event.done, event.total)
            row.detail.setText(event.detail)
            self._update_overall()
        elif isinstance(event, ev.StageFinished):
            row = self._row(event.stage)
            row.bar.setRange(0, 100)
            if event.status in SUCCESS_STATES or event.status == "skipped":
                row.fraction = 1.0
            row.bar.setValue(0 if event.status == "skipped" else int(row.fraction * 100))
            row.bar.setFormat("—" if event.status == "skipped" else "%p %")
            row.status.setText(T.STAGE_STATUS.get(event.status, event.status))
            if event.detail:
                row.detail.setText(event.detail)
            self.eta.setText("")
            self._update_overall()
        elif isinstance(event, ev.WarningRaised):
            self.warnings.addItem(f"⚠ {event.message}")
        elif isinstance(event, ev.LogLine):
            self.log.appendPlainText(event.text)
        elif isinstance(event, ev.PartialResult):
            self.log.appendPlainText(f"Captura {event.item_id} en {event.time_seconds:.1f} s")
        elif isinstance(event, ev.JobFailed):
            self.error.show_message(UserMessage.from_dict(event.message))
        elif isinstance(event, ev.JobFinished):
            self.finish(event.status)

    def _update_eta(self, row: _StageRow, done: int, total: int) -> None:
        """Estimación basada sólo en la velocidad medida en esta ejecución; se etiqueta como aproximada."""
        now = time.monotonic()
        if row.first_done is None:
            row.first_done = (now, done)
            return
        start_time, start_done = row.first_done
        elapsed, progressed = now - start_time, done - start_done
        if elapsed >= 10 and progressed > 0 and done / total >= 0.05:
            self.eta.setText(T.ETA.format(minutes=max(1, round((total - done) * elapsed / progressed / 60))))

    def finish(self, status: str) -> None:
        self.cancel.setEnabled(False)
        self.cancel.setText(T.CANCEL)
        self.eta.setText("")
        self.result.setText(T.JOB_DONE.get(status, status))
        self.results.show()
        self.home.show()
        self.results.setFocus()
        if status in ("completed", "completed_with_warnings"):
            self.overall.setValue(100)
            self.overall.setFormat("100 %")
