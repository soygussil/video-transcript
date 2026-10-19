"""Pruebas de interfaz con servicios simulados (sin procesos ni modelos)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from analizador_video.application import events as ev
from analizador_video.application.analyze_video import AnalyzeVideo
from analizador_video.application.backends import BackendRegistry
from analizador_video.application.export_reports import ExportReports
from analizador_video.application.project_service import ProjectService
from analizador_video.domain.enums import ReportKind, StageName
from analizador_video.domain.models import StagePlan
from analizador_video.infrastructure.preferences import Preferences
from analizador_video.ui import strings as T
from analizador_video.ui.job_controller import JobController
from analizador_video.ui.main_window import MainWindow
from tests.fixtures.fakes import CountingToken

pytestmark = pytest.mark.ui


class FakeHandle:
    def __init__(self, script: list[object]):
        self.script = list(script)
        self.finished = False
        self.cancelled = False

    def poll(self, limit: int = 500) -> list[object]:
        if self.cancelled and self.script:
            self.script = [ev.StageFinished("pantallas", "cancelled", "Cancelado"), ev.JobFinished("cancelled")]
        items, self.script = self.script[:2], self.script[2:]
        if any(isinstance(i, ev.JobFinished) for i in items):
            self.finished = True
        return items

    def cancel(self) -> None:
        self.cancelled = True


class FakeRunner:
    """Simula el JobManager. Para 'analyze' y 'export' ejecuta los casos de uso reales en el mismo proceso."""

    def __init__(self, scripted: list[object] | None = None):
        self.scripted = scripted
        self.started: list[tuple[str, dict[str, Any]]] = []
        self.shutdown_called = False
        self.handle: FakeHandle | None = None

    def start(self, kind: str, payload: dict[str, Any]) -> FakeHandle:
        self.started.append((kind, payload))
        if self.scripted is not None and kind == "analyze":
            self.handle = FakeHandle(self.scripted)
        elif kind == "analyze":
            events: list[object] = []
            plan = StagePlan(
                frozenset(StageName(s) for s in payload["stages"]), automatic_transcription=False, run_ocr=False
            )
            AnalyzeVideo(BackendRegistry()).run(
                Path(payload["project_root"]), plan, events.append, CountingToken(), payload["run_id"]
            )
            self.handle = FakeHandle(events)
        elif kind == "export":
            artifacts = ExportReports().run(Path(payload["project_root"]), [ReportKind(k) for k in payload["kinds"]])
            self.handle = FakeHandle(
                [ev.DataResult("export", {"files": [str(a.path) for a in artifacts]}), ev.JobFinished("completed")]
            )
        else:
            caps = [{"component": "NPU Intel", "status": "no_verificado", "detail": "Reportado", "version": None}]
            self.handle = FakeHandle(
                [
                    ev.DataResult("diagnose", {"cpu": "CPU", "capabilities": caps, "matriz": []}),
                    ev.JobFinished("completed"),
                ]
            )
        return self.handle

    def busy(self) -> bool:
        return self.handle is not None and not self.handle.finished

    def shutdown(self, timeout: float = 10.0) -> bool:
        self.shutdown_called = True
        return True


@pytest.fixture
def window(qtbot, tmp_path):
    def build(runner: FakeRunner) -> MainWindow:
        root = tmp_path / "Proyectos"
        root.mkdir(exist_ok=True)
        win = MainWindow(
            ProjectService(root), JobController(runner, interval_ms=10), Preferences(), tmp_path / "prefs.json"
        )
        qtbot.addWidget(win)
        win.show()
        return win

    return build


def test_validation_and_analyze_button_state(window, sample_video, tmp_path):
    win = window(FakeRunner([]))
    assert not win.home.analyze.isEnabled()
    bad = tmp_path / "notas.txt"
    bad.write_text("x")
    win.home.set_video(bad)
    assert not win.home.analyze.isEnabled() and "no es compatible" in win.home.validation.title.text()
    win.home.set_video(sample_video)
    assert win.home.analyze.isEnabled() and win.home.ok_label.text() == T.VALIDATION_OK


def test_device_choice_reaches_the_job_and_is_remembered(qtbot, window, sample_video, tmp_path):
    runner = FakeRunner([ev.JobFinished("completed")])
    win = window(runner)
    assert win.home.selected_device() == "auto"
    win.home.device.setCurrentIndex(win.home.device.findData("npu"))
    win.home.set_video(sample_video)
    qtbot.mouseClick(win.home.analyze, Qt.MouseButton.LeftButton)
    kind, payload = runner.started[0]
    assert kind == "analyze" and payload["device"] == "npu"
    assert Preferences.load(tmp_path / "prefs.json").device == "npu"
    qtbot.waitUntil(lambda: not runner.busy(), timeout=3000)


def test_invalid_saved_device_falls_back_to_auto(tmp_path):
    (tmp_path / "p.json").write_text('{"device": "tpu"}', encoding="utf-8")
    assert Preferences.load(tmp_path / "p.json").device == "auto"


def test_progress_warnings_and_completion(qtbot, window, sample_video):
    script = [
        ev.JobStarted("r", "p", ("preparar", "pantallas")),
        ev.StageStarted("preparar"),
        ev.StageFinished("preparar", "completed"),
        ev.StageStarted("pantallas", 10, "opencv", "cpu"),
        ev.StageProgress("pantallas", 5, 10, "2 pantallas"),
        ev.WarningRaised("ocr", "x", "Advertencia"),
        ev.LogLine("Actividad"),
        ev.StageFinished("pantallas", "completed"),
        ev.JobFinished("completed_with_warnings"),
    ]
    runner = FakeRunner(script)
    win = window(runner)
    win.home.set_video(sample_video)
    qtbot.mouseClick(win.home.analyze, Qt.MouseButton.LeftButton)
    assert win.stack.currentWidget() is win.processing
    qtbot.waitUntil(lambda: win.processing.results.isVisible(), timeout=3000)
    assert win.processing.rows["pantallas"].status.text() == T.STAGE_STATUS["completed"]
    assert win.processing.warnings.count() == 1 and "opencv" in win.processing.device.text()


def test_cancel_from_processing(qtbot, window, sample_video, monkeypatch):
    script = [
        ev.StageStarted("pantallas", 100, "opencv", "cpu"),
        *[ev.StageProgress("pantallas", i, 100) for i in range(1, 60)],
        ev.JobFinished("completed"),
    ]
    win = window(FakeRunner(script))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.home.set_video(sample_video)
    win.home.analyze.click()
    qtbot.wait(30)
    win.processing.cancel.click()
    assert win.processing.cancel.text() == T.CANCELLING
    qtbot.waitUntil(lambda: win.processing.results.isVisible(), timeout=3000)
    assert win.processing.result.text() == T.JOB_DONE["cancelled"]


def test_vertical_slice_review_export_and_reopen(qtbot, window, sample_video, sample_vtt, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr("analizador_video.ui.pages.project.open_folder", opened.append)
    win = window(FakeRunner())
    win.home.set_video(sample_video)
    win.home.set_transcript(sample_vtt)
    win.home.analyze.click()
    qtbot.waitUntil(lambda: win.processing.results.isVisible(), timeout=10000)
    win.processing.results.click()
    assert win.stack.currentWidget() is win.project
    qtbot.waitUntil(lambda: win.project.thumbnails_pending() == 0, timeout=5000)
    assert win.project.grid.count() == 3 and not win.project.grid.item(0).icon().isNull()
    qtbot.keyClick(win, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: win.project.open_reports.isVisible(), timeout=10000)
    assert {p.name for p in win.project.last_files} == {"reporte_analisis.docx", "reporte_analisis.xlsx"}
    win.project.open_reports.click()
    assert opened and opened[0].name == "reports"
    qtbot.keyClick(win, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert win.stack.currentWidget() is win.projects and win.projects.table.rowCount() == 1
    assert win.projects.table.item(0, 2).text() == T.STATUS_LABELS["completado"]
    win.projects.open_button.click()
    assert win.stack.currentWidget() is win.project and win.project.title.text() == "demo"


def test_projects_search_and_filter(window, sample_video, qtbot):
    win = window(FakeRunner())
    win.home.set_video(sample_video)
    win.home.analyze.click()
    qtbot.waitUntil(lambda: win.processing.results.isVisible(), timeout=10000)
    qtbot.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert win.projects.search.hasFocus()
    win.projects.search.setText("zzz")
    assert win.projects.table.rowCount() == 0
    win.projects.search.setText("demo")
    assert win.projects.table.rowCount() == 1
    win.projects.status.setCurrentIndex(win.projects.status.findData("con_error"))
    assert win.projects.table.rowCount() == 0


def test_theme_toggle_persists(window, tmp_path):
    win = window(FakeRunner([]))
    win.toggle_theme()
    assert win.theme_button.text() == T.THEME_TO_LIGHT and Preferences.load(tmp_path / "prefs.json").theme == "oscuro"
    win.toggle_theme()
    assert Preferences.load(tmp_path / "prefs.json").theme == "claro"


def test_diagnostics_page_shows_not_verified(qtbot, window):
    win = window(FakeRunner([]))
    qtbot.keyClick(win, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    win.diagnostics.detect.click()
    qtbot.waitUntil(lambda: win.diagnostics.capabilities.rowCount() == 1, timeout=3000)
    assert win.diagnostics.capabilities.item(0, 1).text() == T.DIAG_STATUS_LABELS["no_verificado"]


def test_close_during_processing_shuts_down_worker(qtbot, window, sample_video, monkeypatch):
    runner = FakeRunner(
        [ev.StageStarted("pantallas", 100), *[ev.StageProgress("pantallas", i, 100) for i in range(200)]]
    )
    win = window(runner)
    win.home.set_video(sample_video)
    win.home.analyze.click()
    qtbot.wait(20)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    win.close()
    assert win.isVisible() and not runner.shutdown_called
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.close()
    assert runner.shutdown_called and runner.handle is not None and runner.handle.cancelled


def test_drop_zone_keyboard_and_accessibility(window, qtbot):
    win = window(FakeRunner([]))
    called: list[bool] = []
    win.home.drop.browseRequested.disconnect()
    win.home.drop.browseRequested.connect(lambda: called.append(True))
    win.home.drop.setFocus()
    qtbot.keyClick(win.home.drop, Qt.Key.Key_Return)
    assert called and win.home.drop.accessibleName() == T.DROP_ACCESSIBLE
