"""Datos de entrada de los reportes. Los reportes no consultan la base de datos."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from analizador_video.domain.models import AlignedEvidence, TranscriptSegment, VideoMetadata

JSON_SCHEMA_VERSION = 2
EXCEL_CELL_LIMIT = 32000


@dataclass(frozen=True)
class ReportData:
    project_name: str
    video_name: str
    metadata: VideoMetadata | None
    profile_label: str
    transcript_source_label: str
    evidence: list[AlignedEvidence]
    segments: list[TranscriptSegment]
    project_root: Path
    generated_at: str
    app_version: str
    title: str
    confidentiality: str
    header: str = ""
    footer: str = ""
    warnings: list[str] = field(default_factory=list)
    settings_summary: dict[str, str] = field(default_factory=dict)
    effective_config: dict[str, object] = field(default_factory=dict)
    corrections: list[dict[str, str]] = field(default_factory=list)
    include_sensitive: bool = True  # False: omite rutas locales y nombres de hablantes


@dataclass(frozen=True)
class TimelineRow:
    second: int
    spoken: str
    capture_id: str
    ocr_text: str
    new_screen: bool  # primera fila en que esta captura está vigente


def build_timeline(data: ReportData) -> list[TimelineRow]:
    """Una fila por segundo: lo que se dice (segmentos que se solapan con ese segundo) y la pantalla vigente."""
    end_of_content = max([s.end_seconds for s in data.segments] + [e.end_seconds for e in data.evidence] + [0.0])
    duration = data.metadata.duration_seconds if data.metadata is not None else 0.0
    total = math.ceil(max(duration, end_of_content))
    segments = sorted(data.segments, key=lambda s: s.start_seconds)
    evidence = sorted(data.evidence, key=lambda e: e.start_seconds)
    rows: list[TimelineRow] = []
    active: list[TranscriptSegment] = []
    next_segment = next_screen = 0
    previous_id = ""
    for second in range(total):
        while next_segment < len(segments) and segments[next_segment].start_seconds < second + 1:
            active.append(segments[next_segment])
            next_segment += 1
        active = [s for s in active if max(s.end_seconds, s.start_seconds + 0.001) > second]
        while next_screen + 1 < len(evidence) and evidence[next_screen + 1].start_seconds <= second:
            next_screen += 1
        screen = evidence[next_screen] if evidence and evidence[next_screen].start_seconds <= second else None
        spoken = "\n".join(
            f"{speaker_label(s, data.include_sensitive)}: {safe_text(s.text)}"
            for s in sorted(active, key=lambda s: s.seq)
        )
        capture_id = screen.capture.id if screen else ""
        rows.append(
            TimelineRow(
                second,
                spoken,
                capture_id,
                screen.ocr_text if screen else "",
                bool(capture_id) and capture_id != previous_id,
            )
        )
        previous_id = capture_id
    return rows


def safe_text(value: object) -> str:
    """Elimina caracteres de control que Word y Excel rechazan (conserva saltos y tabuladores)."""
    return "".join(c for c in str(value or "") if c in "\n\t" or ord(c) >= 32)


def speaker_label(segment: TranscriptSegment, include_sensitive: bool) -> str:
    return segment.speaker_or_unknown if include_sensitive else "Participante"
