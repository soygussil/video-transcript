"""Caso de uso de exportación: construye datos estructurados (con correcciones) y genera reportes."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from analizador_video import __version__
from analizador_video.config.settings import settings_from_dict
from analizador_video.domain.alignment import align
from analizador_video.domain.enums import ReportKind, TranscriptSource
from analizador_video.domain.models import AlignedEvidence, ReportArtifact, TranscriptSegment, UserCorrection
from analizador_video.infrastructure.persistence.repository import ProjectRepository
from analizador_video.infrastructure.reports.model import ReportData
from analizador_video.infrastructure.reports.service import ReportService

PROFILE_LABELS = {"rapido": "Rápido", "balanceado": "Balanceado", "maxima_precision": "Máxima precisión"}
SOURCE_LABELS = {
    TranscriptSource.IMPORTED.value: "Importada (VTT/SRT)",
    TranscriptSource.AUTOMATIC.value: "Transcripción automática local",
    TranscriptSource.NONE.value: "Sin transcripción",
}


def latest_corrections(corrections: Iterable[UserCorrection]) -> dict[tuple[str, str, str], str]:
    """La corrección más reciente de cada (entidad, id, campo) prevalece."""
    return {(c.entity_type, c.entity_id, c.field_name): c.new_value for c in corrections}


def apply_corrections(
    segments: list[TranscriptSegment], ocr_text: dict[str, str], corrections: Iterable[UserCorrection]
) -> tuple[list[TranscriptSegment], dict[str, str]]:
    latest = latest_corrections(corrections)
    fixed = [
        replace(
            s,
            text=latest.get(("segmento", str(s.seq), "text"), s.text),
            speaker=latest.get(("segmento", str(s.seq), "speaker"), s.speaker),
        )
        for s in segments
    ]
    ocr = {cid: latest.get(("ocr", cid, "text"), text) for cid, text in ocr_text.items()}
    for (entity, entity_id, field_name), value in latest.items():
        if entity == "ocr" and field_name == "text":
            ocr.setdefault(entity_id, value)
    return fixed, ocr


def build_evidence(repo: ProjectRepository) -> tuple[list[AlignedEvidence], list[TranscriptSegment]]:
    project = repo.get_project()
    ocr_text = {cid: result.text for cid, result in repo.ocr_results().items()}
    segments, ocr_text = apply_corrections(repo.segments(), ocr_text, repo.corrections())
    duration = project.source.metadata.duration_seconds if project.source.metadata else None
    return align(repo.captures(), segments, ocr_text, duration or None), segments


def build_report_data(repo: ProjectRepository, include_sensitive: bool = True) -> ReportData:
    project = repo.get_project()
    settings = settings_from_dict(repo.get_config())
    evidence, segments = build_evidence(repo)
    source = segments[0].source.value if segments else TranscriptSource.NONE.value
    return ReportData(
        project_name=project.name,
        video_name=project.source.original_path.name,
        metadata=project.source.metadata,
        profile_label=PROFILE_LABELS.get(project.profile.value, project.profile.value),
        transcript_source_label=SOURCE_LABELS.get(source, source),
        evidence=evidence,
        segments=segments,
        project_root=repo.root,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        app_version=__version__,
        title=settings.reporte.titulo,
        confidentiality=settings.reporte.confidencialidad,
        header=settings.reporte.encabezado,
        footer=settings.reporte.pie,
        warnings=[e.message for e in reversed(repo.errors(200)) if e.recoverable],
        settings_summary={
            "Muestreo de pantallas (s)": f"{settings.video.muestreo_seg:g}",
            "Umbral de cambio": f"{settings.video.umbral_cambio:g}",
            "Idiomas OCR": ", ".join(settings.ocr.idiomas),
            "Confianza mínima OCR": f"{settings.ocr.confianza_minima:g}",
            "Modelo de transcripción": settings.transcript.modelo_whisper,
        },
        effective_config=settings.to_dict(),
        corrections=[
            {"entidad": c.entity_type, "id": c.entity_id, "campo": c.field_name, "fecha": c.created_at}
            for c in repo.corrections()
        ],
        include_sensitive=include_sensitive,
    )


class ExportReports:
    def __init__(self, service: ReportService | None = None):
        self.service = service or ReportService()

    def run(
        self,
        project_root: Path,
        kinds: Iterable[ReportKind],
        destination: Path | None = None,
        include_sensitive: bool = True,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> list[ReportArtifact]:
        repo = ProjectRepository.open(project_root)
        try:
            data = build_report_data(repo, include_sensitive)
            artifacts = self.service.generate(data, kinds, destination or (project_root / "reports"), is_cancelled)
            repo.add_reports(artifacts)
            repo.touch()
        finally:
            repo.close()
        return artifacts
