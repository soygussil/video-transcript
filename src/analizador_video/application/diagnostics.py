"""Diagnóstico de hardware, matriz de compatibilidad y paquete de soporte sanitizado."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from analizador_video import __version__
from analizador_video.application.backends import BackendRegistry
from analizador_video.application.cancellation import CancellationToken
from analizador_video.config.settings import load_settings
from analizador_video.domain.enums import CapabilityStatus
from analizador_video.domain.errors import NPU_MODEL_INCOMPATIBLE
from analizador_video.infrastructure.hardware.benchmark import BenchmarkService
from analizador_video.infrastructure.hardware.compatibility import COMPATIBLE, NOT_COMPATIBLE, CompatibilityRecord
from analizador_video.infrastructure.hardware.detector import HardwareDetector
from analizador_video.infrastructure.logging_setup import recent_errors, sanitize
from analizador_video.infrastructure.paths import default_projects_root, logs_dir, models_dir


def compatibility_matrix(registry: BackendRegistry, models: list[str]) -> list[dict[str, str]]:
    """Filas Backend | Modelo | CPU | GPU | NPU | Estado | Motivo, sólo con datos verificados."""
    records = registry.compatibility.load() if registry.compatibility else []
    by_key = {r.key: r for r in records}
    pairs = [
        ("transcripcion", name, model, registry.transcription[name].supported_devices())
        for name in registry.transcription
        for model in models
    ]
    langs = "+".join(load_settings().ocr.idiomas)
    pairs += [("ocr", name, langs, registry.ocr[name].supported_devices()) for name in registry.ocr]
    rows: list[dict[str, str]] = []
    for task, backend, model, supported in pairs:
        cells: dict[str, str] = {}
        reasons: list[str] = []
        for device in ("cpu", "gpu", "npu"):
            if device not in {d.value for d in supported}:
                cells[device] = "No aplica"
                continue
            record = by_key.get((task, backend, model, device))
            if record is None:
                cells[device] = "No verificado"
            elif record.status == COMPATIBLE:
                cells[device] = f"Compatible ({record.latency_ms or 0:.0f} ms)"
            else:
                cells[device] = "No compatible" if record.status == NOT_COMPATIBLE else "No verificado"
                reasons.append(f"{device.upper()}: {record.reason}")
        values = set(cells.values())
        overall = (
            "Compatible"
            if any(v.startswith("Compatible") for v in values)
            else "No compatible"
            if "No compatible" in values and "No verificado" not in values
            else "No verificado"
        )
        rows.append(
            {
                "backend": backend,
                "modelo": model,
                "cpu": cells["cpu"],
                "gpu": cells["gpu"],
                "npu": cells["npu"],
                "estado": overall,
                "motivo": "; ".join(reasons) or "Ejecuta «Probar compatibilidad» para verificar",
            }
        )
    return rows


def collect_diagnostics(registry: BackendRegistry, models: list[str] | None = None) -> dict[str, Any]:
    data = HardwareDetector(models_dir(), default_projects_root()).detect().to_dict()
    chosen = models or [load_settings().transcript.modelo_whisper]
    data["matriz"] = compatibility_matrix(registry, chosen)
    # GPU/NPU: "Disponible" sólo tras una prueba real; nunca porque estén enumeradas.
    records = registry.compatibility.load() if registry.compatibility else []
    for cap in data["capabilities"]:
        device = {"GPU Intel": "gpu", "NPU Intel": "npu"}.get(cap["component"])
        if device is None or cap["status"] != CapabilityStatus.NOT_VERIFIED.value:
            continue
        verified = [r for r in records if r.device == device]
        ok = next((r for r in verified if r.status == COMPATIBLE), None)
        if ok is not None:
            cap["status"] = CapabilityStatus.AVAILABLE.value
            cap["detail"] = f"Verificado con {ok.backend}/{ok.model} el {ok.verified_at[:10]}"
        elif verified and all(r.status == NOT_COMPATIBLE for r in verified):
            cap["status"] = CapabilityStatus.DETECTED_NOT_COMPATIBLE.value
            cap["detail"] = NPU_MODEL_INCOMPATIBLE if device == "npu" else verified[0].reason
    return data


def run_benchmark(
    registry: BackendRegistry,
    models: list[str],
    token: CancellationToken,
    on_result: Callable[[CompatibilityRecord], None] = lambda _r: None,
) -> list[dict[str, Any]]:
    service = BenchmarkService(registry.transcription, registry.ocr, registry.runtime_version)
    records = service.run(service.candidate_cases(models, load_settings().ocr.idiomas), token.is_cancelled, on_result)
    if registry.compatibility is not None:
        registry.compatibility.save(records)
    return [asdict(r) for r in records]


def export_support_bundle(destination: Path, diagnostics: dict[str, Any], project_states: dict[str, Any]) -> Path:
    """ZIP sanitizado: sin transcripciones, OCR, capturas ni secretos."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    settings = load_settings().to_dict()
    settings["reporte"] = {"formatos": settings["reporte"]["formatos"]}
    content = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "app_version": __version__,
        "diagnostico": diagnostics,
        "configuracion_no_sensible": settings,
        "ultimos_errores": recent_errors(logs_dir()),
        "estado_proyecto": project_states,
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("diagnostico.json", sanitize(json.dumps(content, ensure_ascii=False, indent=2, default=str)))
    return destination
