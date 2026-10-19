"""Enumeraciones del dominio. Los valores son contratos persistidos en SQLite: no renombrar."""

from __future__ import annotations

from enum import StrEnum


class StageName(StrEnum):
    """Etapas del análisis. Los valores coinciden con los nombres públicos de `--pasos`."""

    PREPARE = "preparar"
    FRAMES = "pantallas"
    TRANSCRIPT = "audio"
    OCR = "ocr"
    ALIGN = "alinear"
    REPORT = "reporte"

    @classmethod
    def ordered(cls) -> list[StageName]:
        return [cls.PREPARE, cls.FRAMES, cls.TRANSCRIPT, cls.OCR, cls.ALIGN, cls.REPORT]


# Invalidar una etapa invalida a sus dependientes.
STAGE_DEPENDENTS: dict[StageName, tuple[StageName, ...]] = {
    StageName.PREPARE: (StageName.FRAMES, StageName.TRANSCRIPT),
    StageName.FRAMES: (StageName.OCR, StageName.ALIGN),
    StageName.TRANSCRIPT: (StageName.ALIGN,),
    StageName.OCR: (StageName.ALIGN,),
    StageName.ALIGN: (StageName.REPORT,),
    StageName.REPORT: (),
}


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"

    @property
    def is_done(self) -> bool:
        return self in (StageStatus.COMPLETED, StageStatus.COMPLETED_WITH_WARNINGS)


class JobStatus(StrEnum):
    """Estados de una ejecución. No existe PAUSED porque la pausa no está implementada."""

    PENDING = "pending"
    PREPARING = "preparing"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_WARNINGS, JobStatus.FAILED)


class ProfileName(StrEnum):
    FAST = "rapido"
    BALANCED = "balanceado"
    MAX_ACCURACY = "maxima_precision"


class DeviceKind(StrEnum):
    AUTO = "auto"
    GPU = "gpu"
    NPU = "npu"
    CPU = "cpu"


class SourceMode(StrEnum):
    REFERENCE = "referencia"
    COPY = "copia"


class TranscriptSource(StrEnum):
    IMPORTED = "importada"
    AUTOMATIC = "automatica"
    NONE = "ninguna"


class ReportKind(StrEnum):
    WORD = "word"
    EXCEL = "excel"
    JSON = "json"
    TXT = "txt"
    SRT = "srt"


class CapabilityStatus(StrEnum):
    AVAILABLE = "disponible"
    UNAVAILABLE = "no_disponible"
    NEEDS_INSTALL = "requiere_instalacion"
    DETECTED_NOT_COMPATIBLE = "detectado_no_compatible"
    NOT_VERIFIED = "no_verificado"
