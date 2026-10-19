"""Configuración tipada, validada y versionada.

Capas: predeterminados (default_config.yaml) <- archivo de la persona usuaria (opcional) <- perfil.
El resultado es la configuración efectiva que se guarda en cada proyecto.
Las claves YAML se conservan en español porque son el contrato público existente.
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, TypeVar

import yaml

from analizador_video.domain.enums import DeviceKind, ProfileName, ReportKind
from analizador_video.domain.errors import ConfigurationError

CONFIG_VERSION = 2
OCR_PREPROCESSING = ("escala_grises", "contraste", "escalado", "umbral", "nitidez")
TRANSCRIPTION_BACKENDS = ("auto", "faster_whisper", "openvino")
WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")
DEVICES = tuple(d.value for d in DeviceKind)


def _num(low: float, high: float) -> dict[str, Any]:
    return {"min": low, "max": high}


@dataclass(frozen=True)
class VideoSettings:
    muestreo_seg: float = field(metadata=_num(0.05, 60))
    ancho_miniatura: int = field(metadata=_num(16, 1920))
    alto_miniatura: int = field(metadata=_num(16, 1080))
    umbral_pixel: float = field(metadata=_num(0, 1))
    umbral_cambio: float = field(metadata=_num(0, 1))
    umbral_estable: float = field(metadata=_num(0, 1))
    espera_max_estable_seg: float = field(metadata=_num(0, 600))
    separacion_minima_seg: float = field(metadata=_num(0, 600))
    captura_periodica_seg: float = field(metadata=_num(0, 3600))
    ancho_salida: int = field(metadata=_num(160, 7680))
    calidad_jpg: int = field(metadata=_num(10, 100))


@dataclass(frozen=True)
class TranscriptSettings:
    automatica: bool
    backend: str = field(metadata={"choices": TRANSCRIPTION_BACKENDS})
    modelo_whisper: str = field(metadata={"choices": WHISPER_MODELS})
    idioma: str = field(metadata={"non_empty": True})
    dispositivo: str = field(metadata={"choices": DEVICES})
    fallback_cpu: bool
    bloque_minutos: float = field(metadata=_num(1, 240))
    unir_mismo_hablante_seg: float = field(metadata=_num(0, 60))


@dataclass(frozen=True)
class OcrSettings:
    activo: bool
    idiomas: tuple[str, ...] = field(metadata={"non_empty": True})
    confianza_minima: float = field(metadata=_num(0, 1))
    dispositivo: str = field(metadata={"choices": DEVICES})
    guardar_cada: int = field(metadata=_num(1, 100000))
    reintentos: int = field(metadata=_num(0, 5))
    max_errores_consecutivos: int = field(metadata=_num(1, 1000))
    preprocesamiento: tuple[str, ...] = field(metadata={"choices": OCR_PREPROCESSING})


@dataclass(frozen=True)
class ReportSettings:
    titulo: str = field(metadata={"non_empty": True})
    confidencialidad: str
    encabezado: str
    pie: str
    formatos: tuple[str, ...] = field(metadata={"choices": tuple(k.value for k in ReportKind)})


@dataclass(frozen=True)
class ModelSettings:
    permitir_descarga: bool


@dataclass(frozen=True)
class Settings:
    version: int
    video: VideoSettings
    transcript: TranscriptSettings
    ocr: OcrSettings
    reporte: ReportSettings
    modelos: ModelSettings
    perfil: ProfileName

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["perfil"] = self.perfil.value
        for section in ("ocr", "reporte"):
            for key, value in data[section].items():
                if isinstance(value, tuple):
                    data[section][key] = list(value)
        return data


_SECTIONS: dict[str, type] = {
    "video": VideoSettings,
    "transcript": TranscriptSettings,
    "ocr": OcrSettings,
    "reporte": ReportSettings,
    "modelos": ModelSettings,
}
T = TypeVar("T")


def default_document() -> dict[str, Any]:
    text = resources.files("analizador_video.config").joinpath("default_config.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data


def migrate_document(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Migra documentos antiguos. v1 (sin 'version') es el config.yaml original del repositorio."""
    notes: list[str] = []
    doc = copy.deepcopy(data)
    version = doc.get("version", 1)
    if version == 1:
        ocr = doc.get("ocr")
        if isinstance(ocr, dict) and "cpu" in ocr:
            ocr["dispositivo"] = "cpu" if ocr.pop("cpu") else "auto"
            notes.append("ocr.cpu se convirtió en ocr.dispositivo.")
        doc["version"] = 2
        notes.append("Configuración migrada de la versión 1 a la 2.")
    elif version != CONFIG_VERSION:
        raise ConfigurationError(
            f"La configuración usa la versión {version}, que esta aplicación no reconoce",
            "No se puede cargar la configuración",
            f"Usa un archivo de versión {CONFIG_VERSION} o exporta uno nuevo desde la aplicación",
        )
    return doc, notes


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _check(key: str, expected: str, meta: Any, value: Any, problems: list[str]) -> tuple[bool, Any]:
    if expected == "bool":
        if not isinstance(value, bool):
            problems.append(f"'{key}' debe ser verdadero o falso.")
            return False, None
        return True, value
    if expected in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"'{key}' debe ser numérico (valor actual: {value!r}).")
            return False, None
        if expected == "int" and int(value) != value:
            problems.append(f"'{key}' debe ser un número entero (valor actual: {value!r}).")
            return False, None
        if not meta["min"] <= value <= meta["max"]:
            problems.append(f"'{key}' debe estar entre {meta['min']} y {meta['max']} (valor actual: {value!r}).")
            return False, None
        return True, int(value) if expected == "int" else float(value)
    if expected.startswith("tuple"):
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            problems.append(f"'{key}' debe ser una lista de textos.")
            return False, None
        items = tuple(v.strip() for v in value)
        if meta.get("non_empty") and not items:
            problems.append(f"'{key}' no puede estar vacío.")
            return False, None
        invalid = [v for v in items if "choices" in meta and v not in meta["choices"]]
        if invalid:
            problems.append(f"'{key}' contiene valores no válidos {invalid}; permitidos: {list(meta['choices'])}.")
            return False, None
        return True, items
    if not isinstance(value, str):
        problems.append(f"'{key}' debe ser texto.")
        return False, None
    if meta.get("non_empty") and not value.strip():
        problems.append(f"'{key}' no puede estar vacío.")
        return False, None
    if "choices" in meta and value not in meta["choices"]:
        problems.append(f"'{key}' debe ser uno de {list(meta['choices'])} (valor actual: {value!r}).")
        return False, None
    return True, value


def _coerce(section: str, cls: type[T], raw: Any, problems: list[str]) -> T | None:
    if not isinstance(raw, dict):
        problems.append(f"Falta la sección '{section}'.")
        return None
    fields = dataclasses.fields(cls)  # type: ignore[arg-type]
    for unknown in sorted(set(raw) - {f.name for f in fields}):
        problems.append(f"'{section}.{unknown}' no es una opción reconocida.")
    values: dict[str, Any] = {}
    for f in fields:
        key = f"{section}.{f.name}"
        if f.name not in raw:
            problems.append(f"Falta '{key}'.")
            continue
        expected = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", str(f.type))
        ok, value = _check(key, expected, f.metadata, raw[f.name], problems)
        if ok:
            values[f.name] = value
    if len(values) != len(fields):
        return None
    return cls(**values)


def build_settings(document: dict[str, Any], profile: ProfileName = ProfileName.BALANCED) -> Settings:
    doc, _ = migrate_document(document)
    profiles = doc.get("perfiles") or {}
    overrides = profiles.get(profile.value, {}) if isinstance(profiles, dict) else {}
    effective = _deep_merge(doc, overrides if isinstance(overrides, dict) else {})
    problems: list[str] = []
    for unknown in sorted(set(effective) - set(_SECTIONS) - {"version", "perfiles", "perfil"}):
        problems.append(f"Sección desconocida '{unknown}'.")
    parsed = {name: _coerce(name, cls, effective.get(name), problems) for name, cls in _SECTIONS.items()}
    if problems:
        raise ConfigurationError(
            "La configuración no es válida",
            "No se puede iniciar el análisis con estos valores",
            "Corrige los valores indicados o restablece la configuración predeterminada",
            details="\n".join(problems),
        )
    return Settings(version=CONFIG_VERSION, perfil=profile, **parsed)  # type: ignore[arg-type]


def read_document(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(
            f"No se encontró el archivo de configuración «{path.name}»",
            "No se puede cargar la configuración",
            "Verifica la ruta o ejecuta sin --config para usar los valores predeterminados",
        ) from error
    except (yaml.YAMLError, UnicodeDecodeError) as error:
        raise ConfigurationError(
            f"El archivo «{path.name}» no es YAML válido",
            "No se puede cargar la configuración",
            "Corrige el archivo o exporta uno nuevo desde la aplicación",
        ) from error
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"El archivo «{path.name}» no contiene secciones de configuración",
            "No se puede cargar la configuración",
            "Usa un archivo exportado por la aplicación",
        )
    return data


def load_settings(path: Path | None = None, profile: ProfileName = ProfileName.BALANCED) -> Settings:
    """Carga la configuración efectiva. `path` puede ser un config.yaml v1 (original) o v2."""
    document = default_document()
    if path is not None:
        user, _ = migrate_document(read_document(path))
        user.pop("perfil", None)
        document = _deep_merge(document, user)
    return build_settings(document, profile)


def settings_from_dict(data: dict[str, Any]) -> Settings:
    """Reconstruye la configuración efectiva guardada en un proyecto."""
    profile = ProfileName(data.get("perfil", ProfileName.BALANCED.value))
    doc = {k: v for k, v in data.items() if k != "perfil"}
    doc.setdefault("version", CONFIG_VERSION)
    return build_settings(doc, profile)


def export_settings(settings: Settings, path: Path) -> None:
    path.write_text(yaml.safe_dump(settings.to_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8")
