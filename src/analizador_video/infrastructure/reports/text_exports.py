"""Exportaciones JSON, TXT y SRT (usan la versión corregida y validan el orden temporal)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from analizador_video.domain.models import TranscriptSegment
from analizador_video.domain.timefmt import format_hms, format_srt
from analizador_video.infrastructure.fileio import atomic_write_json, atomic_write_text
from analizador_video.infrastructure.reports.model import JSON_SCHEMA_VERSION, ReportData, speaker_label

JSON_NAME = "analisis.json"
TXT_NAME = "transcripcion.txt"
SRT_NAME = "transcripcion.srt"


def _ordered_valid(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    ordered = sorted(segments, key=lambda s: (s.start_seconds, s.seq))
    for segment in ordered:
        if segment.end_seconds < segment.start_seconds:
            raise ValueError(f"El segmento {segment.seq} termina antes de comenzar.")
    return ordered


def export_txt(data: ReportData, destination: Path) -> Path:
    lines = [
        f"[{format_hms(s.start_seconds)}] {speaker_label(s, data.include_sensitive)}: {s.text}"
        for s in _ordered_valid(data.segments)
    ]
    path = destination / TXT_NAME
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
    return path


def export_srt(data: ReportData, destination: Path) -> Path:
    blocks = [
        f"{n}\n{format_srt(s.start_seconds)} --> {format_srt(s.end_seconds)}\n"
        f"{speaker_label(s, data.include_sensitive)}: {s.text}\n"
        for n, s in enumerate(_ordered_valid(data.segments), start=1)
    ]
    path = destination / SRT_NAME
    atomic_write_text(path, "\n".join(blocks))
    return path


def build_json(data: ReportData) -> dict[str, Any]:
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "app_version": data.app_version,
        "generado": data.generated_at,
        "proyecto": data.project_name,
        "video": {"nombre": data.video_name, "metadatos": data.metadata.__dict__ if data.metadata else None},
        "configuracion_efectiva": data.effective_config,
        "transcripcion_origen": data.transcript_source_label,
        "capturas": [
            {
                "id": e.capture.id,
                "archivo": e.capture.file_rel if data.include_sensitive else Path(e.capture.file_rel).name,
                "start_seconds": e.start_seconds,
                "end_seconds": e.end_seconds,
                "start_display": e.start_display,
                "end_display": e.end_display,
                "cambio": e.capture.change_score,
                "motivo": e.capture.reason,
                "ocr": e.ocr_text,
                "segmentos": [s.seq for s in e.segments],
            }
            for e in data.evidence
        ],
        "segmentos": [
            {
                "seq": s.seq,
                "start_seconds": s.start_seconds,
                "end_seconds": s.end_seconds,
                "start_display": s.start_display,
                "end_display": s.end_display,
                "speaker": speaker_label(s, data.include_sensitive),
                "text": s.text,
                "source": s.source.value,
                "confidence": s.confidence,
            }
            for s in _ordered_valid(data.segments)
        ],
        "correcciones": data.corrections,
        "advertencias": data.warnings,
    }


def export_json(data: ReportData, destination: Path) -> Path:
    path = destination / JSON_NAME
    atomic_write_json(path, build_json(data))
    return path
