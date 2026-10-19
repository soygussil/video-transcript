"""Importa resultados del formato anterior (salida/<video>/frames.json, transcript.json, ocr.json)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from analizador_video.application.project_service import CreateProjectRequest, ProjectService
from analizador_video.domain.enums import ProfileName, StageName, StageStatus, TranscriptSource
from analizador_video.domain.errors import InputValidationError
from analizador_video.domain.models import OcrBlock, OcrResult, ScreenCapture, TranscriptSegment
from analizador_video.domain.validation import resolve_within, safe_filename
from analizador_video.infrastructure.persistence.repository import ProjectRepository


def _items(folder: Path, name: str) -> list[dict[str, Any]]:
    path = folder / name
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InputValidationError(
            f"El archivo {name} del resultado anterior está dañado",
            "No se importó el resultado",
            "Vuelve a generarlo o importa sólo el video",
            saved=False,
        ) from error
    items = data.get("items") if isinstance(data, dict) else None
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def import_legacy_output(folder: Path, video: Path, service: ProjectService) -> Path:
    frames = _items(folder, "frames.json")
    if not frames:
        raise InputValidationError(
            "La carpeta no contiene un resultado anterior válido (frames.json)",
            "No se importó nada",
            "Selecciona la carpeta salida/<nombre_del_video> de la versión anterior",
            saved=False,
        )
    sources = [
        resolve_within(folder, str(item.get("archivo", ""))) for item in frames
    ]  # rechaza traversal antes de crear
    project = service.create(
        CreateProjectRequest(
            video=video, transcript=None, profile=ProfileName.BALANCED, name=f"{video.stem} (importado)"
        )
    )
    repo = ProjectRepository.open(project.root)
    try:
        state = repo.get_stage(StageName.FRAMES)
        state.status = StageStatus.COMPLETED
        state.done = state.total = len(frames)
        for seq, (item, source) in enumerate(zip(frames, sources, strict=True), start=1):
            name = safe_filename(source.name, 120)
            if source.exists():
                shutil.copy2(source, project.root / "frames" / name)
            repo.add_capture(
                ScreenCapture(
                    str(item.get("id", f"P{seq:04d}")),
                    seq,
                    f"frames/{name}",
                    float(item.get("tiempo", 0.0)),
                    float(item.get("cambio", 0.0)),
                    str(item.get("motivo", "importado")),
                ),
                state,
            )
        transcript = [t for t in _items(folder, "transcript.json") if "inicio" in t and "fin" in t]
        if transcript:
            segments = [
                TranscriptSegment(
                    i,
                    float(t["inicio"]),
                    max(float(t["inicio"]), float(t["fin"])),
                    str(t.get("hablante", "")),
                    str(t.get("texto", "")),
                    TranscriptSource.IMPORTED,
                )
                for i, t in enumerate(transcript, start=1)
            ]
            seg_state = repo.get_stage(StageName.TRANSCRIPT)
            seg_state.status, seg_state.done, seg_state.total = StageStatus.COMPLETED, len(segments), len(segments)
            repo.replace_segments(segments, seg_state)
        ocr_items = [o for o in _items(folder, "ocr.json") if "id" in o]
        if ocr_items:
            results = [
                OcrResult(
                    str(o["id"]),
                    str(o.get("texto", "")),
                    tuple(
                        OcrBlock(
                            str(b.get("texto", "")),
                            float(b.get("confianza", 0.0)),
                            tuple((float(p[0]), float(p[1])) for p in b.get("caja", [])),
                        )
                        for b in o.get("elementos", [])
                    ),
                    "easyocr",
                    "cpu",
                    "importado_con_error" if o.get("error") else None,
                )
                for o in ocr_items
            ]
            ocr_state = repo.get_stage(StageName.OCR)
            ocr_state.status, ocr_state.done, ocr_state.total = StageStatus.COMPLETED, len(results), len(results)
            repo.save_ocr(results, ocr_state)
    finally:
        repo.close()
    return project.root
