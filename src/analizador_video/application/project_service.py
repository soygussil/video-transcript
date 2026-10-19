"""Casos de uso de proyectos: validar, crear, listar, abrir, bloquear y eliminar."""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from analizador_video import __version__
from analizador_video.config.settings import load_settings
from analizador_video.domain.enums import ProfileName, SourceMode, StageName, StageStatus
from analizador_video.domain.errors import InputValidationError, ProjectBusyError, ProjectNotFoundError
from analizador_video.domain.models import Project, ProjectSummary, SourceVideo
from analizador_video.domain.validation import (
    ValidationIssue,
    safe_filename,
    validate_subtitle_file,
    validate_video_file,
)
from analizador_video.infrastructure.persistence.database import utc_now
from analizador_video.infrastructure.persistence.repository import DB_NAME, ProjectRepository
from analizador_video.infrastructure.system import free_bytes

PROJECT_DIRS = ("source", "frames", "audio", "transcripts", "cache", "reports", "logs")
MIN_FREE_BYTES = 2 * 1024**3
LOCK_NAME = ".en_proceso.lock"


def project_status(stages: dict[StageName, StageStatus], locked: bool) -> str:
    values = set(stages.values())
    if StageStatus.RUNNING in values:
        return "en_proceso" if locked else "interrumpido"
    if StageStatus.FAILED in values:
        return "con_error"
    if values & {StageStatus.CANCELLED, StageStatus.INTERRUPTED}:
        return "interrumpido"
    if (
        stages.get(StageName.FRAMES, StageStatus.PENDING).is_done
        and stages.get(StageName.ALIGN, StageStatus.PENDING).is_done
    ):
        return "completado"
    return "pendiente"


@dataclass(frozen=True)
class CreateProjectRequest:
    video: Path
    transcript: Path | None
    profile: ProfileName
    source_mode: SourceMode = SourceMode.REFERENCE
    name: str | None = None
    project_id: str | None = None
    config_path: Path | None = None


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except ImportError:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


class ProjectLock:
    """Evita que dos procesos modifiquen el mismo proyecto. Detecta bloqueos huérfanos."""

    def __init__(self, root: Path):
        self.path = root / LOCK_NAME
        self._held = False

    def is_locked(self) -> bool:
        try:
            pid = int(self.path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            return False
        return pid > 0 and pid != os.getpid() and _pid_alive(pid)

    def acquire(self) -> None:
        if self.is_locked():
            raise ProjectBusyError(
                "El proyecto ya se está procesando en otra ventana o proceso",
                "No se puede iniciar otro análisis sobre el mismo proyecto",
                "Espera a que termine o cierra la otra ejecución",
                saved=True,
            )
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self._held = True

    def release(self) -> None:
        if self._held and self.path.exists():
            self.path.unlink()
        self._held = False


class ProjectService:
    def __init__(self, projects_root: Path):
        self.projects_root = projects_root

    def validate(
        self, video: Path | None, transcript: Path | None, source_mode: SourceMode = SourceMode.REFERENCE
    ) -> list[ValidationIssue]:
        issues = validate_video_file(video) + validate_subtitle_file(transcript)
        if issues or video is None:
            return issues
        try:
            free = free_bytes(self.projects_root)
        except OSError:
            return [ValidationIssue("destino", "No se puede escribir en la carpeta de proyectos. Revisa los permisos.")]
        size = video.stat().st_size
        needed = MIN_FREE_BYTES + (size if source_mode is SourceMode.COPY else 0)
        if free < needed:
            issues.append(
                ValidationIssue(
                    "destino",
                    f"Hay {free / 1024**3:.1f} GB libres; se recomiendan al menos {needed / 1024**3:.1f} GB.",
                    blocking=source_mode is SourceMode.COPY and free < size,
                )
            )
        return issues

    def new_project_id(self, video: Path) -> str:
        return f"{safe_filename(video.stem, 60)}_{datetime.now():%Y%m%d-%H%M%S}"

    def create(self, request: CreateProjectRequest) -> Project:
        blocking = [i for i in self.validate(request.video, request.transcript, request.source_mode) if i.blocking]
        if blocking:
            raise InputValidationError(
                blocking[0].message, "No se creó el proyecto", "Corrige la selección e inténtalo de nuevo", saved=False
            )
        settings = load_settings(request.config_path, request.profile)
        project_id = safe_filename(request.project_id or self.new_project_id(request.video), 90)
        root = self.projects_root / project_id
        if (root / DB_NAME).exists():
            raise InputValidationError(
                f"Ya existe un proyecto llamado «{project_id}»",
                "No se creó un proyecto nuevo",
                "Abre el proyecto existente desde Proyectos o usa otro nombre",
                saved=False,
            )
        for name in PROJECT_DIRS:
            (root / name).mkdir(parents=True, exist_ok=True)
        transcript_copy: Path | None = None
        if request.transcript is not None:  # pequeña: se copia para que el proyecto sea reproducible
            transcript_copy = root / "transcripts" / safe_filename(request.transcript.name, 120)
            shutil.copy2(request.transcript, transcript_copy)
        now = utc_now()
        project = Project(
            id=project_id,
            name=request.name or request.video.stem,
            root=root,
            source=SourceVideo(request.video.resolve(), request.source_mode, request.video.stat().st_size, ""),
            profile=request.profile,
            transcript_path=transcript_copy,
            created_at=now,
            updated_at=now,
            app_version=__version__,
        )
        repo = ProjectRepository.open(root)
        try:
            repo.create_project(project, settings.to_dict())
        finally:
            repo.close()
        return project

    def resolve(self, reference: Path | str) -> Path:
        candidate = Path(reference)
        if not (candidate / DB_NAME).exists():
            candidate = self.projects_root / candidate
        if not (candidate / DB_NAME).exists():
            raise ProjectNotFoundError(
                f"No se encontró el proyecto «{Path(reference).name}»",
                "No se puede abrir",
                "Verifica la carpeta del proyecto o elígelo desde la lista de Proyectos",
            )
        return candidate

    def summary(self, root: Path) -> ProjectSummary:
        repo = ProjectRepository.open(root)
        try:
            project = repo.get_project()
            stages = {name: state.status for name, state in repo.stages().items()}
        finally:
            repo.close()
        return ProjectSummary(
            project.id,
            project.name,
            root,
            project.source.original_path.name,
            project.profile,
            project_status(stages, ProjectLock(root).is_locked()),
            project.updated_at,
            project.source.effective_path.exists(),
        )

    def list_projects(self) -> list[ProjectSummary]:
        if not self.projects_root.exists():
            return []
        summaries: list[ProjectSummary] = []
        for db in sorted(self.projects_root.glob(f"*/{DB_NAME}")):
            try:
                summaries.append(self.summary(db.parent))
            except (sqlite3.Error, LookupError, ValueError):
                continue  # carpeta ajena o base dañada: no se lista
        return sorted(summaries, key=lambda s: s.updated_at, reverse=True)

    def delete(self, root: Path) -> None:
        resolved = root.resolve()
        if self.projects_root.resolve() not in resolved.parents or not (resolved / DB_NAME).exists():
            raise InputValidationError(
                "La carpeta indicada no es un proyecto de esta aplicación",
                "No se eliminó nada",
                "Elige el proyecto desde la lista de Proyectos",
            )
        if ProjectLock(resolved).is_locked():
            raise ProjectBusyError(
                "El proyecto se está procesando", "No se eliminó", "Cancela el análisis antes de eliminarlo", saved=True
            )
        shutil.rmtree(resolved)
