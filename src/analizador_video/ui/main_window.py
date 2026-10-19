"""Ventana principal: navegación, coordinación de trabajos y cierre seguro."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from analizador_video import __version__
from analizador_video.application import events as ev
from analizador_video.application.diagnostics import export_support_bundle
from analizador_video.application.job_manager import new_run_id
from analizador_video.application.project_service import CreateProjectRequest, ProjectService
from analizador_video.domain.enums import ProfileName, SourceMode, StageName
from analizador_video.domain.errors import AppError, UserMessage
from analizador_video.infrastructure.preferences import Preferences
from analizador_video.ui import strings as T
from analizador_video.ui.job_controller import JobController
from analizador_video.ui.pages.diagnostics import DiagnosticsPage
from analizador_video.ui.pages.home import HomePage
from analizador_video.ui.pages.processing import ProcessingPage
from analizador_video.ui.pages.project import ProjectPage
from analizador_video.ui.pages.projects import ProjectsPage
from analizador_video.ui.theme import apply_theme
from analizador_video.ui.widgets.common import MessageBanner

NAV = (T.NAV_HOME, T.NAV_PROJECTS, T.NAV_DIAGNOSTICS)


class MainWindow(QMainWindow):
    def __init__(
        self,
        service: ProjectService,
        controller: JobController,
        preferences: Preferences,
        preferences_path: Path | None = None,
    ):
        super().__init__()
        self.service = service
        self.controller = controller
        self.preferences = preferences
        self.preferences_path = preferences_path
        self.setWindowTitle(f"{T.APP_TITLE} {__version__}")
        self.resize(1240, 820)
        self.setMinimumSize(980, 640)

        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        side = QWidget()
        side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        side.setFixedWidth(210)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 12)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setAccessibleName("Navegación principal")
        for index, text in enumerate(NAV, start=1):
            self.nav.addItem(f"{text}   Ctrl+{index}")
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.itemClicked.connect(lambda item: self._navigate(self.nav.row(item)))
        side_layout.addWidget(self.nav, 1)
        self.theme_button = QPushButton()
        self.theme_button.clicked.connect(self.toggle_theme)
        side_layout.addWidget(self.theme_button)
        layout.addWidget(side)

        self.stack = QStackedWidget()
        self.home = HomePage(service, preferences.profile, preferences.copy_video, preferences.device)
        self.projects = ProjectsPage(service)
        self.diagnostics = DiagnosticsPage()
        self.processing = ProcessingPage()
        self.project = ProjectPage(service)
        for page in (self.home, self.projects, self.diagnostics, self.processing, self.project):
            self.stack.addWidget(page)
        body = QWidget()
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.banner = MessageBanner("error")
        body_layout.addWidget(self.banner)
        body_layout.addWidget(self.stack, 1)
        layout.addWidget(body, 1)
        self.setCentralWidget(central)

        self.job_link = QPushButton(T.JOB_RUNNING_LINK)
        self.job_link.setObjectName("Link")
        self.job_link.clicked.connect(lambda: self._show_contextual(self.processing))
        self.job_link.hide()
        self.statusBar().addPermanentWidget(self.job_link)

        self.home.analyzeRequested.connect(self.start_analysis)
        self.home.openProjectRequested.connect(self.open_project)
        self.projects.openRequested.connect(self.open_project)
        self.projects.continueRequested.connect(self.continue_project)
        self.processing.cancelRequested.connect(self.controller.cancel)
        self.processing.resultsRequested.connect(self.open_project)
        self.processing.homeRequested.connect(lambda: self.go(0))
        self.project.continueRequested.connect(self.continue_project)
        self.project.exportRequested.connect(self.start_export)
        self.diagnostics.detectRequested.connect(lambda: self._start_simple("diagnose"))
        self.diagnostics.benchmarkRequested.connect(lambda: self._start_simple("benchmark"))
        self.diagnostics.exportRequested.connect(self.export_diagnostics)
        self.controller.eventReceived.connect(self._on_event)
        self.controller.jobFinished.connect(self._on_job_finished)
        self._shortcuts()
        self._update_theme_button()
        self.go(0)

    # ---------------------------------------------------------------- navegación y accesibilidad
    def _shortcuts(self) -> None:
        def add(sequence: QKeySequence | QKeySequence.StandardKey | str, handler: Any, text: str) -> None:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(sequence))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(handler)
            self.addAction(action)

        add(QKeySequence.StandardKey.Open, self._shortcut_open, "Abrir video")
        add("Ctrl+E", self._shortcut_export, "Exportar")
        add(QKeySequence.StandardKey.Find, self._shortcut_find, "Buscar proyectos")
        add("F5", self.projects.refresh, "Actualizar")
        for index in range(len(NAV)):
            add(f"Ctrl+{index + 1}", lambda _=False, i=index: self.go(i), NAV[index])

    def go(self, row: int) -> None:
        """Navegación explícita (atajos y botones); funciona aunque la fila ya sea la actual."""
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(row)
        self.nav.blockSignals(False)
        self._navigate(row)

    def _shortcut_open(self) -> None:
        self.go(0)
        self.home.browse_video()

    def _shortcut_export(self) -> None:
        if self.stack.currentWidget() is self.project and self.project.export_button.isEnabled():
            self.project.request_export()

    def _shortcut_find(self) -> None:
        self.go(1)
        self.projects.focus_search()

    def _navigate(self, row: int) -> None:
        if row < 0:
            return
        page = (self.home, self.projects, self.diagnostics)[row]
        self.nav.item(row).setSelected(True)
        if page is self.projects:
            self.projects.refresh()
        elif page is self.home:
            self.home.refresh_recent()
        self.stack.setCurrentWidget(page)

    def _show_contextual(self, page: QWidget) -> None:
        self.nav.clearSelection()  # se quita sólo el resaltado
        self.stack.setCurrentWidget(page)

    def toggle_theme(self) -> None:
        self.preferences.theme = "oscuro" if self.preferences.theme == "claro" else "claro"
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, self.preferences.theme)
        self._update_theme_button()
        self._save_preferences()

    def _update_theme_button(self) -> None:
        self.theme_button.setText(T.THEME_TO_LIGHT if self.preferences.theme == "oscuro" else T.THEME_TO_DARK)

    def _save_preferences(self) -> None:
        if self.preferences_path is not None:
            self.preferences.save(self.preferences_path)

    # ---------------------------------------------------------------- trabajos
    def start_analysis(self, video: Path, transcript: Path | None, profile: str, copy_video: bool) -> None:
        if self.controller.busy():
            self.banner.show_text(T.BUSY)
            return
        self.banner.hide()
        try:
            project = self.service.create(
                CreateProjectRequest(
                    video=video,
                    transcript=transcript,
                    profile=ProfileName(profile),
                    source_mode=SourceMode.COPY if copy_video else SourceMode.REFERENCE,
                )
            )
        except AppError as error:
            self.banner.show_message(error.message)
            return
        self.preferences.profile, self.preferences.copy_video = profile, copy_video
        self.preferences.device = self.home.selected_device()
        self._save_preferences()
        self._run_project(project.root, project.name)

    def continue_project(self, root: Path) -> None:
        if self.controller.busy():
            self.banner.show_text(T.BUSY)
            return
        self._run_project(root, self.service.summary(root).name)

    def _run_project(self, root: Path, name: str) -> None:
        stages = [s.value for s in StageName.ordered() if s is not StageName.REPORT]
        payload = {
            "project_root": str(root),
            "run_id": new_run_id(),
            "stages": stages,
            "device": self.preferences.device,
        }
        if not self.controller.start("analyze", payload):
            self.banner.show_text(T.BUSY)
            return
        self.processing.begin(root, name, stages)
        self._show_contextual(self.processing)
        self.job_link.show()

    def open_project(self, root: Path) -> None:
        try:
            self.project.load(root)
        except AppError as error:
            self.banner.show_message(error.message)
            return
        except (LookupError, OSError):
            self.banner.show_message(
                UserMessage(
                    "proyecto_ilegible",
                    "No se pudo abrir el proyecto",
                    "El proyecto no se mostró",
                    None,
                    "Verifica que la carpeta exista o elimina el proyecto desde la lista",
                )
            )
            return
        self.banner.hide()
        self._show_contextual(self.project)

    def start_export(self, root: Path, kinds: list[str], destination: Path | None, include_sensitive: bool) -> None:
        payload = {
            "project_root": str(root),
            "kinds": kinds,
            "include_sensitive": include_sensitive,
            "destination": str(destination) if destination else None,
        }
        if not self.controller.start("export", payload):
            self.project.export_failed(
                UserMessage(
                    "ocupado", T.BUSY, "No se generaron reportes", None, "Espera a que termine el trabajo en curso"
                )
            )

    def _start_simple(self, kind: str) -> None:
        if not self.controller.start(kind, {}):
            self.banner.show_text(T.BUSY)
            return
        self.diagnostics.set_busy(True)

    def export_diagnostics(self, path: Path, data: dict[str, Any]) -> None:
        state: dict[str, Any] = {}
        if self.project.root is not None:
            summary = self.service.summary(self.project.root)
            state = {
                "estado": summary.status,
                "perfil": summary.profile.value,
                "video_disponible": summary.source_available,
            }
        try:
            export_support_bundle(path, data, state)
        except OSError:
            self.diagnostics.banner.show_text("No se pudo guardar el diagnóstico.", "Elige otra carpeta.")
            return
        self.diagnostics.status.setText(T.DIAG_EXPORTED.format(name=path.name))

    def _on_event(self, event: object) -> None:
        kind = self.controller.kind
        if kind == "analyze":
            self.processing.handle(event)
        elif kind == "export":
            if isinstance(event, ev.DataResult):
                self.project.export_finished(list(event.payload.get("files", [])))
            elif isinstance(event, ev.JobFailed):
                self.project.export_failed(UserMessage.from_dict(event.message))
        elif kind in ("diagnose", "benchmark"):
            if isinstance(event, ev.DataResult) and event.kind == "diagnose":
                self.diagnostics.show_data(event.payload)
            elif isinstance(event, ev.LogLine):
                self.diagnostics.status.setText(event.text)
            elif isinstance(event, ev.JobFailed):
                self.diagnostics.banner.show_message(UserMessage.from_dict(event.message))

    def _on_job_finished(self, kind: str, status: str) -> None:
        self.job_link.hide()
        if kind in ("diagnose", "benchmark"):
            self.diagnostics.set_busy(False)
            if kind == "benchmark" and status == "completed":
                self._start_simple("diagnose")  # refresca la matriz con resultados verificados
        elif kind == "analyze":
            self.home.refresh_recent()

    # ---------------------------------------------------------------- cierre seguro
    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.busy():
            answer = QMessageBox.question(
                self,
                T.APP_TITLE,
                T.CLOSE_RUNNING,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.controller.cancel()
                self.controller.shutdown(15.0)
            finally:
                QApplication.restoreOverrideCursor()
        self._save_preferences()
        event.accept()
