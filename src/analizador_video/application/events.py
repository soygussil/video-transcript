"""Eventos tipados del motor hacia la interfaz o la CLI (serializables entre procesos)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JobStarted:
    run_id: str
    project_id: str
    stages: tuple[str, ...]


@dataclass(frozen=True)
class StageStarted:
    stage: str
    total: int | None = None
    backend: str | None = None
    device: str | None = None


@dataclass(frozen=True)
class StageProgress:
    stage: str
    done: int
    total: int | None
    detail: str = ""


@dataclass(frozen=True)
class WarningRaised:
    stage: str | None
    code: str
    message: str


@dataclass(frozen=True)
class PartialResult:
    stage: str
    item_id: str
    file_rel: str
    time_seconds: float


@dataclass(frozen=True)
class StageFinished:
    stage: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class LogLine:
    text: str


@dataclass(frozen=True)
class JobFailed:
    stage: str | None
    message: dict[str, Any]


@dataclass(frozen=True)
class JobFinished:
    status: str
    warnings: int = 0
    project_root: str = ""


@dataclass(frozen=True)
class DataResult:
    """Resultado de trabajos sin proyecto (diagnóstico, benchmark, exportación)."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


Event = (
    JobStarted
    | StageStarted
    | StageProgress
    | WarningRaised
    | PartialResult
    | StageFinished
    | LogLine
    | JobFailed
    | JobFinished
    | DataResult
)
EventSink = Callable[[Event], None]
