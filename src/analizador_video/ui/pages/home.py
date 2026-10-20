"""Inicio: seleccionar o arrastrar video, transcripción opcional, perfil y validación visible."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from analizador_video.application.project_service import ProjectService
from analizador_video.domain.enums import ProfileName, SourceMode
from analizador_video.domain.validation import VIDEO_EXTENSIONS
from analizador_video.infrastructure.video.region import Region
from analizador_video.ui import strings as T
from analizador_video.ui.widgets.common import DropZone, MessageBanner, label
from analizador_video.ui.widgets.region_dialog import RegionDialog


class HomePage(QWidget):
    analyzeRequested = Signal(Path, object, str, bool)  # video, transcripción|None, perfil, copiar
    openProjectRequested = Signal(Path)

    def __init__(
        self,
        service: ProjectService,
        profile: str,
        copy_video: bool,
        device: str = "auto",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.service = service
        self.video: Path | None = None
        self.transcript: Path | None = None
        self.region = Region()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(label(T.HOME_TITLE, "Title"))
        root.addWidget(label(T.HOME_SUBTITLE, "Subtitle"))
        self.drop = DropZone(VIDEO_EXTENSIONS)
        self.drop.fileDropped.connect(self.set_video)
        self.drop.browseRequested.connect(self.browse_video)
        root.addWidget(self.drop)

        buttons = QHBoxLayout()
        self.select_video = QPushButton(T.SELECT_VIDEO)
        self.select_video.clicked.connect(self.browse_video)
        self.select_transcript = QPushButton(T.SELECT_TRANSCRIPT)
        self.select_transcript.clicked.connect(self.browse_transcript)
        self.remove_transcript = QPushButton(T.REMOVE_TRANSCRIPT)
        self.remove_transcript.clicked.connect(lambda: self.set_transcript(None))
        self.remove_transcript.hide()
        for button in (self.select_video, self.select_transcript, self.remove_transcript):
            buttons.addWidget(button)
        buttons.addStretch(1)
        root.addLayout(buttons)
        self.transcript_label = label(T.TRANSCRIPT_NONE, "Muted")
        root.addWidget(self.transcript_label)

        area = QHBoxLayout()
        self.select_region = QPushButton(T.REGION_BUTTON)
        self.select_region.setEnabled(False)
        self.select_region.clicked.connect(self.choose_region)
        self.region_label = label(T.REGION_FULL_LABEL, "Muted")
        area.addWidget(self.select_region)
        area.addWidget(self.region_label, 1)
        root.addLayout(area)

        box = QFrame()
        box.setObjectName("Card")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(label(T.PROFILE_LABEL, "Section"))
        self.profiles = QButtonGroup(self)
        for key, (title, description) in T.PROFILES.items():
            radio = QRadioButton(f"{title} — {description}")
            radio.setProperty("profile", key)
            radio.setAccessibleName(f"{T.PROFILE_LABEL}: {title}")
            radio.setChecked(key == profile)
            self.profiles.addButton(radio)
            box_layout.addWidget(radio)
        box_layout.addWidget(label(T.DEVICE_LABEL, "Section"))
        self.device = QComboBox()
        self.device.setAccessibleName(T.DEVICE_LABEL)
        self.device.setToolTip(T.DEVICE_HINT)
        for key, title in T.DEVICE_CHOICES.items():
            self.device.addItem(title, key)
        self.device.setCurrentIndex(max(0, self.device.findData(device)))
        box_layout.addWidget(self.device)
        hint = label(T.DEVICE_HINT_SHORT, "Muted")
        hint.setToolTip(T.DEVICE_HINT)
        box_layout.addWidget(hint)
        self.copy_video = QCheckBox(T.COPY_VIDEO)
        self.copy_video.setChecked(copy_video)
        self.copy_video.toggled.connect(lambda _checked: self.refresh_validation())
        box_layout.addWidget(self.copy_video)
        root.addWidget(box)

        self.validation = MessageBanner("warning")
        root.addWidget(self.validation)
        self.ok_label = label("", "Ok")
        root.addWidget(self.ok_label)
        action = QHBoxLayout()
        self.analyze = QPushButton(T.ANALYZE)
        self.analyze.setObjectName("Primary")
        self.analyze.setEnabled(False)
        self.analyze.clicked.connect(self._emit_analyze)
        action.addWidget(self.analyze)
        action.addStretch(1)
        root.addLayout(action)

        root.addWidget(label(T.RECENT_TITLE, "Section"))
        self.recent = QListWidget()
        self.recent.setAccessibleName(T.RECENT_TITLE)
        self.recent.setMaximumHeight(150)
        self.recent.itemActivated.connect(self._open_recent)
        root.addWidget(self.recent)
        root.addStretch(1)
        self.refresh_recent()

    def selected_device(self) -> str:
        return str(self.device.currentData() or "auto")

    def selected_profile(self) -> str:
        button = self.profiles.checkedButton()
        return str(button.property("profile")) if button else ProfileName.BALANCED.value

    def browse_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, T.SELECT_VIDEO, "", T.VIDEO_FILTER)
        if path:
            self.set_video(Path(path))

    def browse_transcript(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, T.SELECT_TRANSCRIPT, "", T.SUBTITLE_FILTER)
        if path:
            self.set_transcript(Path(path))

    def choose_region(self) -> None:
        if self.video is None:
            return
        dialog = RegionDialog(self.video, self.region, self)
        if dialog.exec() == RegionDialog.DialogCode.Accepted:
            self._set_region(dialog.region())

    def _set_region(self, region: Region) -> None:
        self.region = region
        self.region_label.setText(
            T.REGION_FULL_LABEL if region.is_full else T.REGION_CUSTOM_LABEL.format(w=region.w, h=region.h)
        )

    def set_video(self, path: Path) -> None:
        if path != self.video:
            self._set_region(Region())  # el área elegida pertenece al video anterior
        self.video = path
        self.drop.set_selected(path)
        self.refresh_validation()

    def set_transcript(self, path: Path | None) -> None:
        self.transcript = path
        self.transcript_label.setText(f"Transcripción: {path.name}" if path else T.TRANSCRIPT_NONE)
        self.remove_transcript.setVisible(path is not None)
        self.refresh_validation()

    def refresh_validation(self) -> None:
        self.select_region.setEnabled(self.video is not None)
        if self.video is None:
            self.validation.hide()
            self.ok_label.setText("")
            self.analyze.setEnabled(False)
            return
        mode = SourceMode.COPY if self.copy_video.isChecked() else SourceMode.REFERENCE
        issues = self.service.validate(self.video, self.transcript, mode)
        blocking = [i for i in issues if i.blocking]
        if issues:
            self.validation.show_text(issues[0].message, " ".join(i.message for i in issues[1:]))
        else:
            self.validation.hide()
        self.ok_label.setText("" if blocking else T.VALIDATION_OK)
        self.analyze.setEnabled(not blocking)

    def _emit_analyze(self) -> None:
        if self.video is not None and self.analyze.isEnabled():
            self.analyzeRequested.emit(
                self.video, self.transcript, self.selected_profile(), self.copy_video.isChecked()
            )

    def _open_recent(self, item: QListWidgetItem) -> None:
        root = item.data(Qt.ItemDataRole.UserRole)
        if root:
            self.openProjectRequested.emit(Path(root))

    def refresh_recent(self) -> None:
        self.recent.clear()
        projects = self.service.list_projects()[:5]
        if not projects:
            item = QListWidgetItem(T.RECENT_EMPTY)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(item)
            return
        for summary in projects:
            status = T.STATUS_LABELS.get(summary.status, summary.status)
            item = QListWidgetItem(f"{summary.name}  ·  {status}  ·  {summary.updated_at[:16].replace('T', ' ')}")
            item.setData(Qt.ItemDataRole.UserRole, str(summary.root))
            item.setToolTip(f"{T.OPEN}: {summary.video_name}")
            self.recent.addItem(item)
