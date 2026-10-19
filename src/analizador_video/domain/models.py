"""Modelos tipados del dominio (dataclasses; estrategia única en todo el proyecto)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from analizador_video.domain.enums import (
    CapabilityStatus,
    DeviceKind,
    JobStatus,
    ProfileName,
    ReportKind,
    SourceMode,
    StageName,
    StageStatus,
    TranscriptSource,
)
from analizador_video.domain.timefmt import format_hms

UNKNOWN_SPEAKER = "Desconocido"


@dataclass(frozen=True)
class VideoMetadata:
    duration_seconds: float
    fps: float
    frame_count: int
    width: int
    height: int
    codec: str | None = None
    rotation_degrees: int = 0


@dataclass(frozen=True)
class SourceVideo:
    original_path: Path
    mode: SourceMode
    size_bytes: int
    fingerprint: str
    metadata: VideoMetadata | None = None
    stored_path: Path | None = None

    @property
    def effective_path(self) -> Path:
        return self.stored_path if self.stored_path is not None else self.original_path


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    root: Path
    source: SourceVideo
    profile: ProfileName
    transcript_path: Path | None
    created_at: str
    updated_at: str
    app_version: str


@dataclass(frozen=True)
class ProjectSummary:
    id: str
    name: str
    root: Path
    video_name: str
    profile: ProfileName
    status: str
    updated_at: str
    source_available: bool


@dataclass(frozen=True)
class ScreenCapture:
    id: str
    seq: int
    file_rel: str
    time_seconds: float
    change_score: float
    reason: str

    @property
    def time_display(self) -> str:
        return format_hms(self.time_seconds)


@dataclass(frozen=True)
class TranscriptSegment:
    seq: int
    start_seconds: float
    end_seconds: float
    speaker: str
    text: str
    source: TranscriptSource
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.end_seconds < self.start_seconds:
            raise ValueError("Un segmento no puede terminar antes de comenzar.")

    @property
    def start_display(self) -> str:
        return format_hms(self.start_seconds)

    @property
    def end_display(self) -> str:
        return format_hms(self.end_seconds)

    @property
    def speaker_or_unknown(self) -> str:
        return self.speaker.strip() or UNKNOWN_SPEAKER


@dataclass(frozen=True)
class OcrBlock:
    text: str
    confidence: float
    box: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class OcrResult:
    capture_id: str
    text: str
    blocks: tuple[OcrBlock, ...]
    backend: str
    device: str
    error_code: str | None = None


@dataclass(frozen=True)
class AlignedEvidence:
    capture: ScreenCapture
    start_seconds: float
    end_seconds: float
    ocr_text: str
    segments: tuple[TranscriptSegment, ...]

    @property
    def start_display(self) -> str:
        return format_hms(self.start_seconds)

    @property
    def end_display(self) -> str:
        return format_hms(self.end_seconds)


@dataclass(frozen=True)
class ReportArtifact:
    kind: ReportKind
    path: Path
    created_at: str


@dataclass(frozen=True)
class HardwareCapability:
    component: str
    status: CapabilityStatus
    detail: str
    version: str | None = None


@dataclass(frozen=True)
class ProcessingError:
    code: str
    stage: StageName | None
    message: str
    recoverable: bool
    created_at: str = ""


@dataclass(frozen=True)
class UserCorrection:
    entity_type: str
    entity_id: str
    field_name: str
    old_value: str
    new_value: str
    created_at: str


@dataclass
class StageState:
    name: StageName
    status: StageStatus = StageStatus.PENDING
    done: int = 0
    total: int | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class StagePlan:
    """Qué etapas ejecutar y cuáles recalcular. Las demás se reutilizan u omiten."""

    run: frozenset[StageName]
    force: frozenset[StageName] = frozenset()
    automatic_transcription: bool = True
    run_ocr: bool = True
    device: DeviceKind = DeviceKind.AUTO


@dataclass
class AnalysisJob:
    project_id: str
    run_id: str
    status: JobStatus = JobStatus.PENDING
    stages: dict[StageName, StageState] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
