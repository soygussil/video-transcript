"""Despacho de trabajos dentro del worker. Mismos casos de uso que la CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from analizador_video.application.analyze_video import AnalyzeVideo
from analizador_video.application.backends import BackendRegistry
from analizador_video.application.cancellation import EventToken
from analizador_video.application.events import DataResult, EventSink, JobFinished, LogLine
from analizador_video.application.export_reports import ExportReports
from analizador_video.domain.enums import DeviceKind, ReportKind, StageName
from analizador_video.domain.models import StagePlan

if TYPE_CHECKING:
    from analizador_video.application.job_manager import JobSpec


def plan_from_payload(payload: dict[str, Any]) -> StagePlan:
    return StagePlan(
        run=frozenset(StageName(s) for s in payload.get("stages", [s.value for s in StageName.ordered()])),
        force=frozenset(StageName(s) for s in payload.get("force", [])),
        automatic_transcription=bool(payload.get("automatic_transcription", True)),
        run_ocr=bool(payload.get("run_ocr", True)),
        device=DeviceKind(payload.get("device", DeviceKind.AUTO.value)),
    )


def run_job(spec: JobSpec, emit: EventSink, token: EventToken, registry: BackendRegistry | None = None) -> None:
    payload = spec.payload
    if spec.kind == "analyze":
        AnalyzeVideo(registry or BackendRegistry.default()).run(
            Path(payload["project_root"]), plan_from_payload(payload), emit, token, payload["run_id"]
        )
    elif spec.kind == "export":
        artifacts = ExportReports().run(
            Path(payload["project_root"]),
            [ReportKind(k) for k in payload["kinds"]],
            Path(payload["destination"]) if payload.get("destination") else None,
            bool(payload.get("include_sensitive", True)),
            token.is_cancelled,
        )
        emit(DataResult("export", {"files": [str(a.path) for a in artifacts]}))
        emit(JobFinished("completed"))
    elif spec.kind == "diagnose":
        from analizador_video.application.diagnostics import collect_diagnostics

        emit(LogLine("Detectando hardware y componentes…"))
        emit(DataResult("diagnose", collect_diagnostics(registry or BackendRegistry.default())))
        emit(JobFinished("completed"))
    elif spec.kind == "benchmark":
        from analizador_video.application.diagnostics import run_benchmark

        records = run_benchmark(
            registry or BackendRegistry.default(),
            payload.get("models", ["small"]),
            token,
            lambda r: emit(LogLine(f"{r.backend}/{r.model}/{r.device}: {r.status}")),
        )
        emit(DataResult("benchmark", {"records": records}))
        emit(JobFinished("completed"))
    else:
        raise ValueError(f"Tipo de trabajo desconocido: {spec.kind}")
