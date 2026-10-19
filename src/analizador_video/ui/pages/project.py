"""Proyecto: estado, capturas (miniaturas cargadas por lotes) y exportación de reportes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analizador_video.application.export_reports import PROFILE_LABELS
from analizador_video.application.project_service import ProjectService
from analizador_video.domain.enums import ReportKind
from analizador_video.domain.errors import UserMessage
from analizador_video.domain.models import ScreenCapture
from analizador_video.domain.validation import resolve_within
from analizador_video.infrastructure.persistence.repository import ProjectRepository
from analizador_video.infrastructure.system import open_folder
from analizador_video.ui import strings as T
from analizador_video.ui.widgets.common import MessageBanner, label

THUMB = QSize(240, 135)
BATCH = 24


def load_thumbnail(path: Path, size: QSize) -> QPixmap:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    if reader.size().isValid():
        reader.setScaledSize(reader.size().scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


class ProjectPage(QWidget):
    continueRequested = Signal(Path)
    exportRequested = Signal(Path, list, object, bool)  # raíz, formatos, destino|None, incluir sensibles

    def __init__(self, service: ProjectService, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.service = service
        self.root: Path | None = None
        self.destination: Path | None = None
        self.captures: list[ScreenCapture] = []
        self.last_files: list[Path] = []
        self._pending: list[tuple[QListWidgetItem, Path]] = []
        self._loader = QTimer(self)
        self._loader.setInterval(0)
        self._loader.timeout.connect(self._load_batch)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        self.title = label("", "Title")
        self.subtitle = label("", "Subtitle")
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        self.source_warning = MessageBanner("warning")
        layout.addWidget(self.source_warning)
        self.stages = label("", "Muted")
        layout.addWidget(self.stages)
        top = QHBoxLayout()
        self.continue_button = QPushButton(T.CONTINUE)
        self.continue_button.setObjectName("Primary")
        self.continue_button.clicked.connect(self._emit_continue)
        self.folder_button = QPushButton(T.OPEN_FOLDER)
        self.folder_button.clicked.connect(lambda: self._open(self.root))
        top.addWidget(self.continue_button)
        top.addWidget(self.folder_button)
        top.addStretch(1)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.captures_title = label("", "Section")
        left_layout.addWidget(self.captures_title)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(THUMB)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setSpacing(10)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(True)
        self.grid.setAccessibleName("Capturas del video")
        self.grid.currentItemChanged.connect(self._show_detail)
        left_layout.addWidget(self.grid, 1)
        self.detail = label("", "Muted")
        left_layout.addWidget(self.detail)
        splitter.addWidget(left)

        export = QFrame()
        export.setObjectName("Card")
        ex = QVBoxLayout(export)
        ex.addWidget(label(T.EXPORT_TITLE, "Section"))
        self.format_boxes: dict[ReportKind, QCheckBox] = {}
        for kind in ReportKind:
            box = QCheckBox(T.EXPORT_FORMATS[kind.value])
            box.setChecked(kind in (ReportKind.WORD, ReportKind.EXCEL))
            self.format_boxes[kind] = box
            ex.addWidget(box)
        self.sensitive = QCheckBox(T.EXPORT_SENSITIVE)
        ex.addWidget(self.sensitive)
        self.destination_label = label("", "Muted")
        ex.addWidget(self.destination_label)
        change = QPushButton(T.CHANGE_FOLDER)
        change.clicked.connect(self._choose_destination)
        ex.addWidget(change)
        self.export_button = QPushButton(T.EXPORT)
        self.export_button.setObjectName("Primary")
        self.export_button.clicked.connect(self.request_export)
        ex.addWidget(self.export_button)
        self.export_status = label("", "Ok")
        ex.addWidget(self.export_status)
        self.export_files = QListWidget()
        self.export_files.setAccessibleName("Archivos generados")
        self.export_files.setMaximumHeight(130)
        self.export_files.hide()
        ex.addWidget(self.export_files)
        self.open_reports = QPushButton(T.OPEN_REPORTS)
        self.open_reports.clicked.connect(lambda: self._open(self.destination))
        self.open_reports.hide()
        ex.addWidget(self.open_reports)
        self.export_error = MessageBanner("error")
        ex.addWidget(self.export_error)
        ex.addStretch(1)
        splitter.addWidget(export)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([760, 360])
        layout.addWidget(splitter, 1)

    def load(self, root: Path) -> None:
        self.root = root
        summary = self.service.summary(root)
        repo = ProjectRepository.open(root)
        try:
            project = repo.get_project()
            self.captures = repo.captures()
            stages = repo.stages()
        finally:
            repo.close()
        self.title.setText(project.name)
        meta = project.source.metadata
        duration = f" · {meta.duration_seconds / 60:.1f} min" if meta else ""
        self.subtitle.setText(
            f"{project.source.original_path.name}{duration} · "
            f"{PROFILE_LABELS.get(project.profile.value, project.profile.value)} · "
            f"{T.STATUS_LABELS.get(summary.status, summary.status)}"
        )
        self.subtitle.setToolTip(str(project.source.original_path))
        if summary.source_available:
            self.source_warning.hide()
        else:
            self.source_warning.show_text(T.SOURCE_MISSING)
        self.stages.setText(
            "  ·  ".join(
                f"{T.STAGE_LABELS.get(n.value, n.value)}: {T.STAGE_STATUS.get(s.status.value, s.status.value)}"
                for n, s in stages.items()
            )
        )
        self.continue_button.setVisible(summary.status != "completado")
        self.continue_button.setEnabled(summary.source_available)
        self.destination = root / "reports"
        self.destination_label.setText(T.EXPORT_DESTINATION.format(path=self.destination.name))
        self.destination_label.setToolTip(str(self.destination))
        self.export_status.setText("")
        for widget in (self.export_files, self.open_reports, self.export_error):
            widget.hide()
        self._fill_grid()

    def _emit_continue(self) -> None:
        if self.root is not None:
            self.continueRequested.emit(self.root)

    def _fill_grid(self) -> None:
        self._loader.stop()
        self.grid.clear()
        self._pending.clear()
        self.captures_title.setText(T.PROJECT_CAPTURES.format(count=len(self.captures)))
        self.detail.setText("" if self.captures else T.PROJECT_NO_CAPTURES)
        assert self.root is not None
        for capture in self.captures:
            item = QListWidgetItem(f"{capture.id}\n{capture.time_display}")
            item.setData(Qt.ItemDataRole.UserRole, capture.id)
            item.setSizeHint(QSize(THUMB.width() + 16, THUMB.height() + 48))
            item.setToolTip(f"{capture.id} · {capture.time_display} · {capture.reason}")
            self.grid.addItem(item)
            try:
                self._pending.append((item, resolve_within(self.root, capture.file_rel)))
            except ValueError:
                continue
        if self._pending:
            self._loader.start()

    def _load_batch(self) -> None:
        for _ in range(BATCH):
            if not self._pending:
                self._loader.stop()
                return
            item, path = self._pending.pop(0)
            pixmap = load_thumbnail(path, THUMB)
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))

    def thumbnails_pending(self) -> int:
        return len(self._pending)

    def _show_detail(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        capture = next((c for c in self.captures if current and c.id == current.data(Qt.ItemDataRole.UserRole)), None)
        if capture:
            self.detail.setText(
                f"{capture.id} · {capture.time_display} · motivo: {capture.reason.replace('_', ' ')}"
                f" · cambio {capture.change_score:.3f}"
            )

    def selected_kinds(self) -> list[str]:
        return [k.value for k, box in self.format_boxes.items() if box.isChecked()]

    def _choose_destination(self) -> None:
        path = QFileDialog.getExistingDirectory(self, T.CHANGE_FOLDER, str(self.destination or ""))
        if path:
            self.destination = Path(path)
            self.destination_label.setText(T.EXPORT_DESTINATION.format(path=self.destination.name))
            self.destination_label.setToolTip(path)

    def request_export(self) -> None:
        if self.root is None:
            return
        kinds = self.selected_kinds()
        if not kinds:
            self.export_status.setText(T.EXPORT_NONE)
            return
        self.export_error.hide()
        self.export_button.setEnabled(False)
        self.export_status.setText(T.EXPORTING)
        default = self.root / "reports"
        self.exportRequested.emit(
            self.root, kinds, None if self.destination == default else self.destination, not self.sensitive.isChecked()
        )

    def export_finished(self, files: list[str]) -> None:
        self.export_button.setEnabled(True)
        self.last_files = [Path(f) for f in files]
        self.export_status.setText(T.EXPORT_DONE.format(count=len(files)))
        self.export_files.clear()
        for path in self.last_files:
            self.export_files.addItem(path.name)
        self.export_files.show()
        self.open_reports.show()

    def export_failed(self, message: UserMessage) -> None:
        self.export_button.setEnabled(True)
        self.export_status.setText("")
        self.export_error.show_message(message)

    def _open(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            open_folder(path)
        except OSError:
            self.export_error.show_text("No se pudo abrir la carpeta.", "Verifica que la carpeta exista.")
