"""Diagnóstico visual: capacidades detectadas y matriz de compatibilidad verificada."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analizador_video.ui import strings as T
from analizador_video.ui.widgets.common import MessageBanner, label


def _table(headers: tuple[str, ...], name: str) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setAccessibleName(name)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setWordWrap(True)
    return table


class DiagnosticsPage(QWidget):
    detectRequested = Signal()
    benchmarkRequested = Signal()
    exportRequested = Signal(Path, dict)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.data: dict[str, Any] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addWidget(label(T.DIAG_TITLE, "Title"))
        root.addWidget(label(T.DIAG_INTRO, "Subtitle"))
        buttons = QHBoxLayout()
        self.detect = QPushButton(T.DIAG_DETECT)
        self.detect.setObjectName("Primary")
        self.detect.clicked.connect(self.detectRequested.emit)
        self.test = QPushButton(T.DIAG_TEST)
        self.test.setToolTip(T.DIAG_TEST_HINT)
        self.test.setAccessibleDescription(T.DIAG_TEST_HINT)
        self.test.clicked.connect(self.benchmarkRequested.emit)
        self.export = QPushButton(T.DIAG_EXPORT)
        self.export.setEnabled(False)
        self.export.clicked.connect(self._export)
        for button in (self.detect, self.test, self.export):
            buttons.addWidget(button)
        buttons.addStretch(1)
        root.addLayout(buttons)
        self.status = label("", "Muted")
        root.addWidget(self.status)
        self.summary = label("")
        root.addWidget(self.summary)
        self.capabilities = _table((T.DIAG_COMPONENT, T.DIAG_STATUS, T.DIAG_DETAIL), T.DIAG_TITLE)
        root.addWidget(self.capabilities, 2)
        self.matrix = _table(T.DIAG_MATRIX, "Matriz de compatibilidad")
        root.addWidget(self.matrix, 1)
        self.banner = MessageBanner("error")
        root.addWidget(self.banner)

    def set_busy(self, busy: bool) -> None:
        self.detect.setEnabled(not busy)
        self.test.setEnabled(not busy)
        self.status.setText(T.DIAG_RUNNING if busy else "")

    def show_data(self, data: dict[str, Any]) -> None:
        self.data = data
        self.export.setEnabled(True)
        self.summary.setText(
            f"{data.get('cpu', '')} · RAM {data.get('ram_total_gb', '?')} GB · {data.get('os', '')} · "
            f"Python {data.get('python', '')} · Espacio libre {data.get('disk_free_gb', '?')} GB"
        )
        caps = data.get("capabilities", [])
        self.capabilities.setRowCount(len(caps))
        for row, cap in enumerate(caps):
            version = f" ({cap['version']})" if cap.get("version") else ""
            values = [cap["component"], T.DIAG_STATUS_LABELS.get(cap["status"], cap["status"]), cap["detail"] + version]
            for column, value in enumerate(values):
                self.capabilities.setItem(row, column, QTableWidgetItem(value))
        rows = data.get("matriz", [])
        self.matrix.setRowCount(len(rows))
        for row, item in enumerate(rows):
            for column, key in enumerate(("backend", "modelo", "cpu", "gpu", "npu", "estado", "motivo")):
                self.matrix.setItem(row, column, QTableWidgetItem(str(item.get(key, ""))))
        self.capabilities.resizeRowsToContents()
        self.matrix.resizeRowsToContents()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, T.DIAG_EXPORT, "diagnostico_analizador.zip", "ZIP (*.zip)")
        if path:
            self.exportRequested.emit(Path(path), self.data)
