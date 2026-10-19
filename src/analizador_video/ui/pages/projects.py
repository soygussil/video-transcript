"""Proyectos: búsqueda, filtro por estado y acciones (abrir, continuar, abrir carpeta, eliminar)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analizador_video.application.project_service import ProjectService
from analizador_video.domain.errors import AppError
from analizador_video.domain.models import ProjectSummary
from analizador_video.infrastructure.system import open_folder
from analizador_video.ui import strings as T
from analizador_video.ui.widgets.common import MessageBanner, label


class ProjectsPage(QWidget):
    openRequested = Signal(Path)
    continueRequested = Signal(Path)

    def __init__(self, service: ProjectService, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.service = service
        self.summaries: list[ProjectSummary] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.addWidget(label(T.PROJECTS_TITLE, "Title"))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(T.SEARCH_PLACEHOLDER)
        self.search.setAccessibleName(T.SEARCH_PLACEHOLDER)
        self.search.textChanged.connect(self._apply_filter)
        self.status = QComboBox()
        self.status.setAccessibleName(T.COL_STATUS)
        self.status.addItem(T.FILTER_ALL, "")
        for key, text in T.STATUS_LABELS.items():
            self.status.addItem(text, key)
        self.status.currentIndexChanged.connect(self._apply_filter)
        refresh = QPushButton(T.REFRESH)
        refresh.clicked.connect(self.refresh)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.status, 1)
        filters.addWidget(refresh)
        root.addLayout(filters)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([T.COL_NAME, T.COL_FILE, T.COL_STATUS, T.COL_UPDATED, T.COL_PROFILE])
        self.table.setAccessibleName(T.PROJECTS_TITLE)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemActivated.connect(lambda _item: self._open())
        self.table.itemSelectionChanged.connect(self._update_actions)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.open_button = QPushButton(T.OPEN)
        self.open_button.clicked.connect(self._open)
        self.continue_button = QPushButton(T.CONTINUE)
        self.continue_button.clicked.connect(self._continue)
        self.folder_button = QPushButton(T.OPEN_FOLDER)
        self.folder_button.clicked.connect(self._folder)
        self.delete_button = QPushButton(T.DELETE)
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete)
        for button in (self.open_button, self.continue_button, self.folder_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.delete_button)
        root.addLayout(actions)
        self.banner = MessageBanner("error")
        root.addWidget(self.banner)
        self.refresh()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def refresh(self) -> None:
        self.summaries = self.service.list_projects()
        self._apply_filter()

    def _apply_filter(self) -> None:
        text = self.search.text().strip().lower()
        status = self.status.currentData()
        visible = [
            s
            for s in self.summaries
            if (not text or text in s.name.lower() or text in s.video_name.lower())
            and (not status or s.status == status)
        ]
        self.table.setRowCount(len(visible))
        for row, summary in enumerate(visible):
            values = [
                summary.name,
                summary.video_name + ("" if summary.source_available else "  (video no encontrado)"),
                T.STATUS_LABELS.get(summary.status, summary.status),
                summary.updated_at[:16].replace("T", " "),
                T.PROFILES.get(summary.profile.value, (summary.profile.value, ""))[0],
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, str(summary.root))
                self.table.setItem(row, column, item)
        if visible:
            self.table.selectRow(0)
        self._update_actions()

    def _selected(self) -> ProjectSummary | None:
        items = self.table.selectedItems()
        if not items:
            return None
        root = items[0].data(Qt.ItemDataRole.UserRole)
        return next((s for s in self.summaries if str(s.root) == root), None)

    def _update_actions(self) -> None:
        summary = self._selected()
        for button in (self.open_button, self.folder_button, self.delete_button):
            button.setEnabled(summary is not None)
        self.continue_button.setEnabled(
            summary is not None and summary.status != "completado" and summary.source_available
        )

    def _open(self) -> None:
        summary = self._selected()
        if summary:
            self.openRequested.emit(summary.root)

    def _continue(self) -> None:
        summary = self._selected()
        if summary:
            self.continueRequested.emit(summary.root)

    def _folder(self) -> None:
        summary = self._selected()
        if summary:
            try:
                open_folder(summary.root)
            except OSError:
                self.banner.show_text("No se pudo abrir la carpeta del proyecto.", "Verifica que la carpeta exista.")

    def _delete(self) -> None:
        summary = self._selected()
        if summary is None:
            return
        answer = QMessageBox.question(
            self,
            T.DELETE,
            T.DELETE_CONFIRM.format(name=summary.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete(summary.root)
        except AppError as error:
            self.banner.show_message(error.message)
            return
        except OSError:
            self.banner.show_text(
                "No se pudo eliminar el proyecto.",
                "Cierra los archivos del proyecto abiertos en otros programas e intenta de nuevo.",
            )
            return
        self.banner.hide()
        self.refresh()
