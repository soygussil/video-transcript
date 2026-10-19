"""Puente entre el JobManager (procesos) y Qt. La UI sólo consume eventos; no procesa video."""

from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import QObject, QTimer, Signal

from analizador_video.application.events import Event, JobFinished


class JobHandleLike(Protocol):
    finished: bool

    def poll(self, limit: int = 500) -> list[Event]: ...

    def cancel(self) -> None: ...


class JobRunner(Protocol):
    def start(self, kind: str, payload: dict[str, Any]) -> JobHandleLike: ...

    def busy(self) -> bool: ...

    def shutdown(self, timeout: float = 10.0) -> bool: ...


class JobController(QObject):
    eventReceived = Signal(object)
    jobStarted = Signal(str)
    jobFinished = Signal(str, str)  # tipo de trabajo, estado final

    def __init__(self, runner: JobRunner, interval_ms: int = 100, parent: QObject | None = None):
        super().__init__(parent)
        self.runner = runner
        self.kind: str | None = None
        self.handle: JobHandleLike | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._poll)

    def busy(self) -> bool:
        return self.handle is not None and not self.handle.finished

    def start(self, kind: str, payload: dict[str, Any]) -> bool:
        if self.busy() or self.runner.busy():
            return False
        self.kind = kind
        self.handle = self.runner.start(kind, payload)
        self.timer.start()
        self.jobStarted.emit(kind)
        return True

    def cancel(self) -> None:
        if self.handle is not None and not self.handle.finished:
            self.handle.cancel()

    def shutdown(self, timeout: float = 15.0) -> bool:
        self.timer.stop()
        return self.runner.shutdown(timeout)

    def _poll(self) -> None:
        if self.handle is None:
            self.timer.stop()
            return
        for event in self.handle.poll():
            self.eventReceived.emit(event)
            if isinstance(event, JobFinished):
                self.timer.stop()
                self.jobFinished.emit(self.kind or "", event.status)
