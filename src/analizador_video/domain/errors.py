"""Errores con mensaje para personas: qué ocurrió, qué afecta, si se guardó y qué hacer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserMessage:
    code: str
    what: str
    affected: str
    saved: bool | None
    action: str
    details: str = ""

    def text(self) -> str:
        parts = [self.what.rstrip(".") + ".", self.affected.rstrip(".") + "."]
        if self.saved is True:
            parts.append("El avance quedó guardado.")
        elif self.saved is False:
            parts.append("No se guardó avance de esta operación.")
        parts.append(self.action.rstrip(".") + ".")
        return " ".join(p for p in parts if p.strip(". "))

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "what": self.what,
            "affected": self.affected,
            "saved": self.saved,
            "action": self.action,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> UserMessage:
        saved = data.get("saved")
        return cls(
            code=str(data.get("code", "error")),
            what=str(data.get("what", "")),
            affected=str(data.get("affected", "")),
            saved=saved if isinstance(saved, bool) else None,
            action=str(data.get("action", "")),
            details=str(data.get("details", "")),
        )


class AppError(Exception):
    """Base de errores esperados. Nunca se muestra el traceback a la persona usuaria."""

    code = "error_aplicacion"

    def __init__(self, what: str, affected: str, action: str, saved: bool | None = None, details: str = ""):
        super().__init__(what)
        self.message = UserMessage(self.code, what, affected, saved, action, details)

    def __str__(self) -> str:
        return self.message.text()


class InputValidationError(AppError):
    code = "entrada_invalida"


class ConfigurationError(AppError):
    code = "configuracion_invalida"


class VideoUnreadableError(AppError):
    code = "video_ilegible"


class SourceMissingError(AppError):
    code = "video_no_encontrado"


class FfmpegMissingError(AppError):
    code = "ffmpeg_no_encontrado"


class StageDependencyError(AppError):
    code = "dependencia_de_etapa"


class BackendUnavailableError(AppError):
    code = "motor_no_disponible"


class ModelNotAvailableError(AppError):
    code = "modelo_no_disponible"


class DeviceIncompatibleError(AppError):
    code = "dispositivo_no_compatible"


class ProjectNotFoundError(AppError):
    code = "proyecto_no_encontrado"


class ProjectBusyError(AppError):
    code = "proyecto_en_uso"


class InsufficientSpaceError(AppError):
    code = "espacio_insuficiente"


class OcrSystemicError(AppError):
    code = "ocr_sistemico"


class DatabaseError(AppError):
    code = "base_de_datos"


class OperationCancelled(Exception):
    """Cancelación cooperativa solicitada por la persona usuaria. No es un error."""


NPU_MODEL_INCOMPATIBLE = "NPU detectada, pero el modelo de transcripción seleccionado no es compatible."
NPU_OCR_INCOMPATIBLE = (
    "NPU detectada, pero los modelos de OCR no son compatibles (el NPU exige formas fijas); el OCR usará GPU o CPU."
)
