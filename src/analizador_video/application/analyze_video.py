"""Caso de uso AnalyzeVideo: orquesta las etapas con estado persistido en SQLite.

Cada etapa puede ejecutarse, omitirse (fuera del plan), reutilizarse (ya completa), invalidarse
(--forzar), reanudarse desde su checkpoint o fallar con un mensaje accionable. Si una etapa se
recalcula, sus dependientes ya completos se invalidan. La CLI y la GUI usan esta misma clase.
"""

from __future__ import annotations

import logging
import math
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from analizador_video.application.backends import BackendRegistry
from analizador_video.application.cancellation import CancellationToken
from analizador_video.application.events import (
    EventSink,
    JobFailed,
    JobFinished,
    JobStarted,
    LogLine,
    PartialResult,
    StageFinished,
    StageProgress,
    StageStarted,
    WarningRaised,
)
from analizador_video.application.export_reports import ExportReports, build_evidence
from analizador_video.application.project_service import ProjectLock
from analizador_video.config.settings import Settings, settings_from_dict
from analizador_video.domain.enums import (
    STAGE_DEPENDENTS,
    DeviceKind,
    JobStatus,
    ReportKind,
    SourceMode,
    StageName,
    StageStatus,
    TranscriptSource,
)
from analizador_video.domain.errors import (
    AppError,
    BackendUnavailableError,
    FfmpegMissingError,
    InputValidationError,
    ModelNotAvailableError,
    OcrSystemicError,
    OperationCancelled,
    SourceMissingError,
    StageDependencyError,
)
from analizador_video.domain.models import (
    OcrResult,
    ProcessingError,
    Project,
    ScreenCapture,
    StagePlan,
    StageState,
    TranscriptSegment,
)
from analizador_video.domain.timefmt import format_compact
from analizador_video.infrastructure.audio import (
    NoAudioStreamError,
    extract_audio,
    read_wav_block,
    wav_duration_seconds,
)
from analizador_video.infrastructure.fileio import atomic_write_bytes
from analizador_video.infrastructure.hardware.compatibility import (
    NOT_COMPATIBLE,
    CompatibilityRecord,
)
from analizador_video.infrastructure.hardware.device_selector import BackendAvailability, Candidate, DeviceSelector
from analizador_video.infrastructure.ocr.backends import LoadedOcr, preprocess, read_image, sort_reading_order
from analizador_video.infrastructure.persistence.repository import ProjectRepository
from analizador_video.infrastructure.transcription.backends import LoadedTranscriber
from analizador_video.infrastructure.transcription.subtitles import import_subtitles
from analizador_video.infrastructure.video.frames import (
    DetectedCapture,
    FrameCheckpoint,
    extract_keyframes,
    sample_step,
    thumb_from_jpeg,
    total_samples,
)
from analizador_video.infrastructure.video.probe import fingerprint, probe_video

log = logging.getLogger("analizador_video.engine")
PROGRESS_EMIT_SECONDS = 0.25
CHECKPOINT_SECONDS = 2.0
NON_BLOCKING = (BackendUnavailableError, ModelNotAvailableError, FfmpegMissingError)


class _StageSkipped(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class _RunContext:
    repo: ProjectRepository
    project: Project
    settings: Settings
    plan: StagePlan
    emit: EventSink
    cancel: CancellationToken
    run_id: str
    warnings: int = 0
    stage_meta: dict[str, str | None] = field(default_factory=dict)

    def warn(self, stage: StageName | None, code: str, message: str) -> None:
        self.warnings += 1
        self.repo.add_error(ProcessingError(code, stage, message, recoverable=True))
        log.warning(message, extra={"stage": stage.value if stage else None, "event": code, "run_id": self.run_id})
        self.emit(WarningRaised(stage.value if stage else None, code, message))


class _Throttle:
    def __init__(self, seconds: float):
        self.seconds = seconds
        self.last = 0.0

    def ready(self, force: bool = False) -> bool:
        now = time.monotonic()
        if force or now - self.last >= self.seconds:
            self.last = now
            return True
        return False


def _peak_rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    info = psutil.Process().memory_info()
    return round((getattr(info, "peak_wset", None) or info.rss) / 2**20, 1)


class AnalyzeVideo:
    def __init__(self, backends: BackendRegistry | None = None, exporter: ExportReports | None = None):
        self.backends = backends or BackendRegistry()
        self.exporter = exporter or ExportReports()

    # ------------------------------------------------------------------ orquestación
    def run(
        self, project_root: Path, plan: StagePlan, emit: EventSink, cancel: CancellationToken, run_id: str
    ) -> JobStatus:
        lock = ProjectLock(project_root)
        lock.acquire()
        repo = ProjectRepository.open(project_root)
        try:
            if repo.mark_interrupted():
                emit(LogLine("Se recuperó un análisis interrumpido; se continuará desde el último avance guardado."))
            ctx = _RunContext(
                repo, repo.get_project(), settings_from_dict(repo.get_config()), plan, emit, cancel, run_id
            )
            repo.start_run(run_id)
            for stage in plan.force:
                for affected in repo.invalidate(stage):
                    emit(LogLine(f"Se recalculará la etapa «{affected.value}»."))
            ordered = [s for s in StageName.ordered() if s in plan.run]
            emit(JobStarted(run_id, ctx.project.id, tuple(s.value for s in ordered)))
            status = self._run_stages(ctx, ordered)
            repo.finish_run(run_id, status.value)
            repo.touch()
            emit(JobFinished(status.value, ctx.warnings, str(project_root)))
            return status
        finally:
            repo.close()
            lock.release()

    def _run_stages(self, ctx: _RunContext, ordered: list[StageName]) -> JobStatus:
        handlers: dict[StageName, Callable[[_RunContext, StageState], StageStatus]] = {
            StageName.PREPARE: self._prepare,
            StageName.FRAMES: self._frames,
            StageName.TRANSCRIPT: self._transcript,
            StageName.OCR: self._ocr,
            StageName.ALIGN: self._align,
            StageName.REPORT: self._report,
        }
        for stage in ordered:
            state = ctx.repo.get_stage(stage)
            if state.status.is_done:
                if stage is StageName.PREPARE:
                    try:
                        self._verify_source(ctx)
                    except AppError as error:
                        ctx.emit(JobFailed(stage.value, error.message.to_dict()))
                        return JobStatus.FAILED
                ctx.emit(StageFinished(stage.value, "reutilizada", "Resultado previo reutilizado"))
                continue
            ctx.stage_meta = {}
            started = time.perf_counter()
            state.status, state.error_code, state.error_message = StageStatus.RUNNING, None, None
            ctx.repo.save_stage(state)
            try:
                if ctx.cancel.is_cancelled():
                    raise OperationCancelled()
                final = handlers[stage](ctx, state)
            except OperationCancelled:
                self._close_stage(ctx, stage, StageStatus.CANCELLED, started)
                ctx.emit(StageFinished(stage.value, StageStatus.CANCELLED.value, "Cancelado; el avance quedó guardado"))
                return JobStatus.CANCELLED
            except _StageSkipped as skipped:
                self._close_stage(ctx, stage, StageStatus.SKIPPED, started)
                ctx.emit(StageFinished(stage.value, StageStatus.SKIPPED.value, skipped.reason))
                continue
            except AppError as error:
                self._close_stage(ctx, stage, StageStatus.FAILED, started, error)
                ctx.emit(JobFailed(stage.value, error.message.to_dict()))
                return JobStatus.FAILED
            self._close_stage(ctx, stage, final, started)
            ctx.emit(StageFinished(stage.value, final.value))
            if stage is not StageName.PREPARE:
                self._invalidate_stale_dependents(ctx, stage)
        return JobStatus.COMPLETED_WITH_WARNINGS if ctx.warnings else JobStatus.COMPLETED

    def _close_stage(
        self, ctx: _RunContext, stage: StageName, status: StageStatus, started: float, error: AppError | None = None
    ) -> None:
        state = ctx.repo.get_stage(stage)
        state.status = status
        if error is not None:
            state.error_code, state.error_message = error.message.code, error.message.text()
            ctx.repo.add_error(ProcessingError(error.message.code, stage, error.message.text(), recoverable=False))
            log.error(
                error.message.text(), extra={"stage": stage.value, "event": error.message.code, "run_id": ctx.run_id}
            )
        ctx.repo.save_stage(state)
        duration_ms = int((time.perf_counter() - started) * 1000)
        ctx.repo.add_metric(
            ctx.run_id, stage, ctx.stage_meta, duration_ms, state.done or None, _peak_rss_mb(), status.value
        )
        log.info(
            "Etapa finalizada",
            extra={
                "stage": stage.value,
                "result": status.value,
                "duration_ms": duration_ms,
                "run_id": ctx.run_id,
                "backend": ctx.stage_meta.get("backend"),
                "device": ctx.stage_meta.get("device"),
            },
        )

    @staticmethod
    def _invalidate_stale_dependents(ctx: _RunContext, stage: StageName) -> None:
        """Si una etapa se (re)calculó, sus dependientes ya completos quedaron obsoletos."""
        for dependent in STAGE_DEPENDENTS[stage]:
            if ctx.repo.get_stage(dependent).status.is_done:
                for affected in ctx.repo.invalidate(dependent):
                    ctx.emit(LogLine(f"La etapa «{affected.value}» se recalculará porque cambiaron sus datos."))

    @staticmethod
    def _require(ctx: _RunContext, stage: StageName, needed: StageName, message: str) -> None:
        if not ctx.repo.get_stage(needed).status.is_done:
            raise StageDependencyError(
                message,
                f"La etapa «{stage.value}» no puede ejecutarse",
                f"Incluye «{needed.value}» en las etapas a ejecutar",
                saved=True,
            )

    # ------------------------------------------------------------------ preparar
    @staticmethod
    def _verify_source(ctx: _RunContext) -> tuple[Path, str]:
        """Comprueba que el video siga disponible y sin cambios. Devuelve (ruta, huella)."""
        source_video = ctx.project.source
        original, stored = source_video.original_path, source_video.stored_path
        if stored is not None and stored.exists():
            source = stored
        elif original.exists():
            source = original
        else:
            raise SourceMissingError(
                f"El video original «{original.name}» ya no está en su ubicación",
                "No se puede continuar el análisis de este proyecto",
                "Restaura el archivo en su ubicación original o crea un proyecto nuevo con el video",
                saved=True,
            )
        current = fingerprint(source)
        if source_video.fingerprint and source_video.fingerprint != current:
            raise InputValidationError(
                f"El video «{original.name}» cambió desde que se creó el proyecto",
                "Los resultados guardados podrían no corresponder al archivo actual",
                "Crea un proyecto nuevo para este video",
                saved=True,
            )
        return source, current

    def _prepare(self, ctx: _RunContext, state: StageState) -> StageStatus:
        ctx.emit(StageStarted(StageName.PREPARE.value, None))
        source, current = self._verify_source(ctx)
        project = ctx.project
        stored = project.source.stored_path
        if project.source.mode is SourceMode.COPY and (stored is None or not stored.exists()):
            stored = project.root / "source" / project.source.original_path.name
            self._copy_with_progress(project.source.original_path, stored, ctx)
            source = stored
        metadata = probe_video(source)
        ctx.repo.update_source(metadata, stored if project.source.mode is SourceMode.COPY else None, current)
        ctx.project = ctx.repo.get_project()
        ctx.emit(
            LogLine(
                f"Video listo: {metadata.width}×{metadata.height}, {metadata.fps:.2f} cps, "
                f"{metadata.duration_seconds / 60:.1f} min."
            )
        )
        return StageStatus.COMPLETED

    @staticmethod
    def _copy_with_progress(source: Path, target: Path, ctx: _RunContext) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        total, copied = source.stat().st_size, 0
        throttle = _Throttle(PROGRESS_EMIT_SECONDS)
        cancelled = False
        with source.open("rb") as reader, partial.open("wb") as writer:
            while chunk := reader.read(8 * 1024 * 1024):
                if ctx.cancel.is_cancelled():
                    cancelled = True
                    break
                writer.write(chunk)
                copied += len(chunk)
                if throttle.ready():
                    ctx.emit(StageProgress(StageName.PREPARE.value, copied // 2**20, total // 2**20, "MB copiados"))
        if cancelled:
            partial.unlink(missing_ok=True)
            raise OperationCancelled()
        partial.replace(target)
        shutil.copystat(source, target)

    # ------------------------------------------------------------------ pantallas
    def _frames(self, ctx: _RunContext, state: StageState) -> StageStatus:
        self._require(ctx, StageName.FRAMES, StageName.PREPARE, "El video no se ha preparado")
        project, cfg = ctx.project, ctx.settings.video
        meta = project.source.metadata
        assert meta is not None
        frames_dir = project.root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        known = ctx.repo.capture_files()
        for orphan in frames_dir.glob("*.jpg"):  # escritas antes de un cierre inesperado, sin registro
            if f"frames/{orphan.name}" not in known:
                orphan.unlink()
        for leftover in frames_dir.glob(".*.tmp"):
            leftover.unlink()
        captures = ctx.repo.captures()
        checkpoint = FrameCheckpoint.from_dict(state.checkpoint)
        checkpoint.captures = max((c.seq for c in captures), default=0)
        last_thumb = thumb_from_jpeg(project.root / captures[-1].file_rel, cfg) if captures else None
        total = total_samples(meta, cfg)
        step = sample_step(meta.fps, cfg)
        if checkpoint.next_index:
            ctx.emit(LogLine(f"Reanudando la detección de pantallas ({checkpoint.captures} capturas guardadas)."))
        ctx.emit(StageStarted(StageName.FRAMES.value, total, "opencv", DeviceKind.CPU.value))
        ctx.stage_meta = {"backend": "opencv", "device": DeviceKind.CPU.value}
        emit_throttle, save_throttle = _Throttle(PROGRESS_EMIT_SECONDS), _Throttle(CHECKPOINT_SECONDS)

        def on_capture(detected: DetectedCapture, cp: FrameCheckpoint) -> None:
            capture_id = f"P{detected.seq:04d}"
            name = f"{capture_id}_{format_compact(detected.time_seconds)}.jpg"
            atomic_write_bytes(frames_dir / name, detected.jpeg_bytes)
            capture = ScreenCapture(
                capture_id,
                detected.seq,
                f"frames/{name}",
                detected.time_seconds,
                detected.change_score,
                detected.reason,
            )
            state.checkpoint, state.total, state.done = cp.to_dict(), total, min(total, cp.next_index // step)
            ctx.repo.add_capture(capture, state)
            ctx.emit(PartialResult(StageName.FRAMES.value, capture_id, capture.file_rel, detected.time_seconds))

        def on_progress(done: int, all_samples: int, cp: FrameCheckpoint) -> None:
            state.done, state.total, state.checkpoint = done, all_samples, cp.to_dict()
            if save_throttle.ready():
                ctx.repo.save_stage(state)
            if emit_throttle.ready(force=done >= all_samples):
                ctx.emit(
                    StageProgress(StageName.FRAMES.value, done, all_samples, f"{cp.captures} pantallas detectadas")
                )

        final = extract_keyframes(
            project.source.effective_path,
            meta,
            cfg,
            checkpoint,
            last_thumb,
            on_capture,
            on_progress,
            ctx.cancel.is_cancelled,
        )
        state.checkpoint = final.to_dict()
        ctx.repo.save_stage(state)
        if ctx.cancel.is_cancelled():
            raise OperationCancelled()
        state.done = state.total or state.done
        ctx.repo.save_stage(state)
        ctx.emit(LogLine(f"Detección de pantallas terminada: {final.captures} capturas."))
        return StageStatus.COMPLETED

    # ------------------------------------------------------------------ transcripción
    def _transcript(self, ctx: _RunContext, state: StageState) -> StageStatus:
        project, settings = ctx.project, ctx.settings
        if project.transcript_path is not None:
            ctx.emit(StageStarted(StageName.TRANSCRIPT.value, None, "importada", None))
            ctx.stage_meta = {"backend": "importada"}
            result = import_subtitles(project.transcript_path, settings.transcript.unir_mismo_hablante_seg)
            for warning in result.warnings:
                ctx.warn(StageName.TRANSCRIPT, "transcripcion_parcial", warning)
            state.done = state.total = len(result.segments)
            ctx.repo.replace_segments(result.segments, state)
            ctx.emit(LogLine(f"Transcripción importada: {len(result.segments)} segmentos ({result.encoding})."))
            return StageStatus.COMPLETED_WITH_WARNINGS if result.warnings else StageStatus.COMPLETED
        if not (ctx.plan.automatic_transcription and settings.transcript.automatica):
            raise _StageSkipped("Sin transcripción: no se indicó VTT/SRT y la automática está desactivada")
        try:
            return self._automatic_transcription(ctx, state)
        except NON_BLOCKING as error:
            ctx.warn(StageName.TRANSCRIPT, error.message.code, error.message.text())
            raise _StageSkipped(error.message.what) from error

    def _load_transcriber(self, ctx: _RunContext, candidates: list[Candidate]) -> LoadedTranscriber | None:
        cfg = ctx.settings.transcript
        while candidates:
            candidate = candidates.pop(0)
            try:
                return self.backends.transcription[candidate.backend].load(
                    cfg.modelo_whisper, candidate.device, ctx.settings.modelos.permitir_descarga
                )
            except AppError as error:
                ctx.warn(StageName.TRANSCRIPT, "fallback", f"{error.message.what}. Se intentará otra opción.")
                self._record_incompatible(candidate.backend, cfg.modelo_whisper, candidate.device, error.message.what)
        return None

    def _automatic_transcription(self, ctx: _RunContext, state: StageState) -> StageStatus:
        self._require(ctx, StageName.TRANSCRIPT, StageName.PREPARE, "El video no se ha preparado")
        cfg = ctx.settings.transcript
        requested = ctx.plan.device if ctx.plan.device is not DeviceKind.AUTO else DeviceKind(cfg.dispositivo)
        allow = ctx.settings.modelos.permitir_descarga
        available = [
            BackendAvailability(
                name,
                b.is_installed(),
                b.model_available(cfg.modelo_whisper) or (allow and name == "faster_whisper"),
                b.supported_devices(),
            )
            for name, b in self.backends.transcription.items()
        ]
        plan = DeviceSelector(self.backends.compatibility, self.backends.runtime_version).plan_transcription(
            cfg.modelo_whisper, requested, cfg.backend, available, cfg.fallback_cpu
        )
        for warning in plan.warnings:
            ctx.warn(StageName.TRANSCRIPT, "dispositivo", warning)
        if not plan.candidates:
            raise BackendUnavailableError(
                "No hay un motor de transcripción automática disponible",
                "El video se analizará sin transcripción",
                "Importa una transcripción VTT o SRT, o instala y descarga un modelo desde Diagnóstico",
                saved=True,
            )
        audio_path = ctx.project.root / "audio" / "audio_16k.wav"
        if not audio_path.exists():
            ctx.emit(StageStarted(StageName.TRANSCRIPT.value, None, "ffmpeg", DeviceKind.CPU.value))
            ctx.emit(LogLine("Extrayendo audio del video…"))
            try:
                extract_audio(ctx.project.source.effective_path, audio_path, ctx.cancel.is_cancelled)
            except NoAudioStreamError:
                ctx.warn(
                    StageName.TRANSCRIPT, "sin_audio", "El video no tiene pista de audio; no hay nada que transcribir."
                )
                state.done = state.total = 0
                ctx.repo.replace_segments([], state)
                return StageStatus.COMPLETED_WITH_WARNINGS
        duration = wav_duration_seconds(audio_path)
        block_seconds = cfg.bloque_minutos * 60
        blocks = max(1, math.ceil(duration / block_seconds))
        first_block = int(state.checkpoint.get("next_block", 0))
        if first_block == 0 and ctx.repo.max_segment_seq():
            ctx.repo.replace_segments([], state)  # restos sin checkpoint válido
        candidates = list(plan.candidates)
        transcriber = self._load_transcriber(ctx, candidates)
        if transcriber is None:
            raise BackendUnavailableError(
                "Ningún motor de transcripción pudo cargarse",
                "El video se analizará sin transcripción",
                "Revisa Diagnóstico o importa una transcripción VTT o SRT",
                saved=True,
            )
        ctx.stage_meta = {
            "backend": transcriber.backend,
            "device": transcriber.device.value,
            "precision": transcriber.precision,
        }
        ctx.emit(StageStarted(StageName.TRANSCRIPT.value, blocks, transcriber.backend, transcriber.device.value))
        started = time.perf_counter()
        seq, block = ctx.repo.max_segment_seq(), first_block
        while block < blocks:
            if ctx.cancel.is_cancelled():
                raise OperationCancelled()
            offset = block * block_seconds
            audio = read_wav_block(audio_path, offset, block_seconds)
            try:
                raw = transcriber.transcribe(audio, cfg.idioma, offset, ctx.cancel.is_cancelled)
            except (RuntimeError, ValueError, MemoryError) as error:
                failed_device = transcriber.device
                if failed_device is not DeviceKind.CPU:
                    self._record_incompatible(
                        transcriber.backend, cfg.modelo_whisper, failed_device, type(error).__name__
                    )
                next_transcriber = (
                    self._load_transcriber(ctx, candidates) if failed_device is not DeviceKind.CPU else None
                )
                if next_transcriber is None:
                    raise BackendUnavailableError(
                        "La transcripción automática falló",
                        "El video se analizará sin transcripción",
                        "Revisa Diagnóstico o importa una transcripción VTT o SRT",
                        saved=True,
                        details=type(error).__name__,
                    ) from error
                ctx.warn(
                    StageName.TRANSCRIPT,
                    "fallback",
                    f"Falló la transcripción en {failed_device.value.upper()}; "
                    f"se continúa con {next_transcriber.device.value.upper()}.",
                )
                transcriber = next_transcriber
                ctx.stage_meta = {
                    "backend": transcriber.backend,
                    "device": transcriber.device.value,
                    "precision": transcriber.precision,
                }
                continue  # reintenta el mismo bloque
            segments = []
            for item in raw:
                seq += 1
                segments.append(
                    TranscriptSegment(
                        seq, item.start, item.end, "", item.text, TranscriptSource.AUTOMATIC, item.confidence
                    )
                )
            block += 1
            state.checkpoint, state.done, state.total = {"next_block": block}, block, blocks
            ctx.repo.append_segments(segments, state)
            elapsed = time.perf_counter() - started
            processed = min(duration, block * block_seconds) - first_block * block_seconds
            factor = f" · {processed / elapsed:.1f}× tiempo real" if elapsed > 0 else ""
            ctx.emit(StageProgress(StageName.TRANSCRIPT.value, block, blocks, f"Bloque {block} de {blocks}{factor}"))
        return StageStatus.COMPLETED

    def _record_incompatible(self, backend: str, model: str, device: DeviceKind, reason: str) -> None:
        if device is DeviceKind.CPU or self.backends.compatibility is None:
            return
        self.backends.compatibility.save(
            [
                CompatibilityRecord(
                    "transcripcion",
                    backend,
                    model,
                    device.value,
                    NOT_COMPATIBLE,
                    reason,
                    None,
                    None,
                    None,
                    self.backends.runtime_version,
                    datetime.now().isoformat(timespec="seconds"),
                )
            ]
        )

    # ------------------------------------------------------------------ OCR
    def _ocr_unavailable_reason(self, languages: tuple[str, ...]) -> AppError:
        for backend in self.backends.ocr.values():
            try:
                backend.load(languages, DeviceKind.CPU, allow_download=False)
            except NON_BLOCKING as error:
                return error
        return BackendUnavailableError(
            "No hay un motor OCR disponible",
            "Las capturas no tendrán texto visible reconocido",
            "Instala el componente de OCR desde la guía de Diagnóstico",
            saved=True,
        )

    def _ocr(self, ctx: _RunContext, state: StageState) -> StageStatus:
        cfg = ctx.settings.ocr
        if not ctx.plan.run_ocr or not cfg.activo:
            raise _StageSkipped("OCR desactivado para este análisis")
        self._require(ctx, StageName.OCR, StageName.FRAMES, "Las capturas de pantalla no están listas")
        allow = ctx.settings.modelos.permitir_descarga
        available = [
            BackendAvailability(name, b.is_installed(), b.models_available(cfg.idiomas) or allow, b.supported_devices())
            for name, b in self.backends.ocr.items()
        ]
        requested = ctx.plan.device if ctx.plan.device is not DeviceKind.AUTO else DeviceKind(cfg.dispositivo)
        plan = DeviceSelector(self.backends.compatibility, self.backends.runtime_version).plan_ocr(
            requested, available, cfg.idiomas
        )
        for warning in plan.warnings:
            ctx.warn(StageName.OCR, "dispositivo", warning)
        reader: LoadedOcr | None = None
        errors: list[AppError] = []
        for candidate in plan.candidates:
            try:
                reader = self.backends.ocr[candidate.backend].load(cfg.idiomas, candidate.device, allow)
                break
            except NON_BLOCKING as error:
                errors.append(error)
        if reader is None:
            reason = errors[0] if errors else self._ocr_unavailable_reason(cfg.idiomas)
            ctx.warn(StageName.OCR, reason.message.code, reason.message.text())
            raise _StageSkipped(reason.message.what)
        ctx.stage_meta = {"backend": reader.backend, "device": reader.device.value}
        captures = ctx.repo.captures()
        done_ids = set(ctx.repo.ocr_results())
        total = len(captures)
        ctx.emit(StageStarted(StageName.OCR.value, total, reader.backend, reader.device.value))
        buffer: list[OcrResult] = []
        processed_this_run = consecutive = failures = 0
        throttle = _Throttle(PROGRESS_EMIT_SECONDS)

        def flush() -> None:
            state.done, state.total = len(done_ids), total
            ctx.repo.save_ocr(buffer, state)
            buffer.clear()

        for capture in (c for c in captures if c.id not in done_ids):
            if ctx.cancel.is_cancelled():
                flush()
                raise OperationCancelled()
            result = self._ocr_one(ctx, reader, capture)
            buffer.append(result)
            done_ids.add(capture.id)
            if result.error_code:
                failures += 1
                consecutive += 1
                if consecutive >= cfg.max_errores_consecutivos:
                    flush()
                    raise OcrSystemicError(
                        f"El OCR falló en {consecutive} capturas seguidas",
                        "El problema parece ser del motor OCR, no de una imagen",
                        "Revisa Diagnóstico o ejecuta el análisis sin OCR",
                        saved=True,
                    )
            else:
                consecutive = 0
            processed_this_run += 1  # checkpoint por elementos procesados en esta ejecución (no índice absoluto)
            if processed_this_run % cfg.guardar_cada == 0:
                flush()
            if throttle.ready(force=len(done_ids) == total):
                ctx.emit(StageProgress(StageName.OCR.value, len(done_ids), total, f"Captura {capture.id}"))
        flush()
        if failures:
            ctx.warn(StageName.OCR, "ocr_parcial", f"El OCR no pudo leer {failures} capturas; quedaron sin texto.")
            return StageStatus.COMPLETED_WITH_WARNINGS
        return StageStatus.COMPLETED

    @staticmethod
    def _ocr_one(ctx: _RunContext, reader: LoadedOcr, capture: ScreenCapture) -> OcrResult:
        cfg = ctx.settings.ocr
        path = ctx.project.root / capture.file_rel
        if not path.exists():
            return OcrResult(capture.id, "", (), reader.backend, reader.device.value, "imagen_no_encontrada")
        last_error = ""
        for _attempt in range(cfg.reintentos + 1):
            try:
                image = preprocess(read_image(path), cfg.preprocesamiento)
                blocks = sort_reading_order(
                    [b for b in reader.recognize(image) if b.confidence >= cfg.confianza_minima]
                )
                return OcrResult(
                    capture.id, "\n".join(b.text for b in blocks), tuple(blocks), reader.backend, reader.device.value
                )
            except (OSError, ValueError, RuntimeError) as error:  # recuperables por imagen
                last_error = type(error).__name__
                log.warning(
                    "OCR fallido en una captura", extra={"stage": "ocr", "event": "ocr_reintento", "result": last_error}
                )
        # Sólo el tipo de error: nunca rutas internas ni mensajes con datos.
        return OcrResult(capture.id, "", (), reader.backend, reader.device.value, f"ocr_fallido:{last_error}")

    # ------------------------------------------------------------------ alineación y reporte
    def _align(self, ctx: _RunContext, state: StageState) -> StageStatus:
        self._require(ctx, StageName.ALIGN, StageName.FRAMES, "Las capturas de pantalla no están listas")
        ctx.emit(StageStarted(StageName.ALIGN.value, None, "dominio", DeviceKind.CPU.value))
        evidence, _segments = build_evidence(ctx.repo)
        state.done = state.total = len(evidence)
        ctx.repo.save_alignment([(e.capture.id, s.seq) for e in evidence for s in e.segments], state)
        return StageStatus.COMPLETED

    def _report(self, ctx: _RunContext, state: StageState) -> StageStatus:
        self._require(ctx, StageName.REPORT, StageName.ALIGN, "La alineación no está lista")
        kinds = [ReportKind(k) for k in ctx.settings.reporte.formatos]
        ctx.emit(StageStarted(StageName.REPORT.value, len(kinds), "reportes", DeviceKind.CPU.value))
        artifacts = self.exporter.run(ctx.project.root, kinds, is_cancelled=ctx.cancel.is_cancelled)
        if ctx.cancel.is_cancelled():
            raise OperationCancelled()
        state.done = state.total = len(artifacts)
        ctx.repo.save_stage(state)
        ctx.emit(LogLine("Reportes generados: " + ", ".join(a.path.name for a in artifacts)))
        return StageStatus.COMPLETED
