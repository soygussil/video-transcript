"""Punto de entrada de la aplicación de escritorio."""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

from analizador_video import APP_ID, APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()  # obligatorio para el worker dentro del ejecutable de PyInstaller
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from analizador_video.application.job_manager import JobManager
    from analizador_video.application.project_service import ProjectService
    from analizador_video.infrastructure.logging_setup import configure_logging
    from analizador_video.infrastructure.paths import app_home, bundled_resource, default_projects_root, logs_dir
    from analizador_video.infrastructure.preferences import Preferences
    from analizador_video.ui.job_controller import JobController
    from analizador_video.ui.main_window import MainWindow
    from analizador_video.ui.theme import apply_theme

    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.{__version__}")  # type: ignore[attr-defined]
    configure_logging(logs_dir())
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_ID)
    icon = bundled_resource("ui/resources/app.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    preferences_path = app_home() / "preferencias.json"
    preferences = Preferences.load(preferences_path)
    apply_theme(app, preferences.theme)
    projects_root = Path(preferences.projects_root) if preferences.projects_root else default_projects_root()
    projects_root.mkdir(parents=True, exist_ok=True)
    window = MainWindow(
        ProjectService(projects_root), JobController(JobManager(app_home())), preferences, preferences_path
    )
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
