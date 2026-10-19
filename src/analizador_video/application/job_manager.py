"""Ejecución de trabajos en un proceso aparte (spawn).

Decisión: multiprocessing en lugar de hilos o QProcess.
- OpenCV, CTranslate2, PyTorch y OpenVINO pueden retener el GIL o fallar a nivel nativo; en un
  proceso separado la interfaz sigue respondiendo y un fallo no la cierra.
- Permite pasar eventos tipados (pickle) sin un protocolo de texto propio y funciona dentro del
  ejecutable de PyInstaller (freeze_support).
- Un solo worker a la vez: limita la concurrencia para que Windows siga respondiendo.
Cancelación cooperativa (multiprocessing.Event). El worker vigila al proceso padre y se detiene si
la interfaz terminó inesperadamente (sin procesos huérfanos).
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from analizador_video.application.events import Event, JobFailed, JobFinished
from analizador_video.domain.errors import AppError, OperationCancelled, UserMessage

log = logging.getLogger("analizador_video.jobs")
PARENT_CHECK_SECONDS = 2.0


@dataclass(frozen=True)
class JobSpec:
    kind: str  # analyze | export | diagnose | benchmark
    payload: dict[str, Any]
    app_home: str
    log_level: str = "INFO"


def unexpected_error_message(details: str) -> UserMessage:
    return UserMessage(
        "error_inesperado",
        "Ocurrió un error inesperado durante el procesamiento",
        "La operación en curso se detuvo",
        True,
        "Puedes reintentar con «Continuar análisis». Si se repite, usa «Exportar diagnóstico» y compártelo con soporte",
        details,
    )


def _watch_parent(cancel_event: Any) -> None:
    parent = mp.parent_process()
    while parent is not None:
        time.sleep(PARENT_CHECK_SECONDS)
        if not parent.is_alive():
            cancel_event.set()  # cancelación cooperativa: se guarda el checkpoint
            time.sleep(15)
            os._exit(3)  # último recurso si el trabajo no respondió


def worker_main(spec: JobSpec, events: Any, cancel_event: Any) -> None:
    os.environ["ANALIZADOR_VIDEO_HOME"] = spec.app_home
    from analizador_video.application.cancellation import EventToken
    from analizador_video.application.workers import run_job
    from analizador_video.infrastructure.logging_setup import configure_logging, sanitize
    from analizador_video.infrastructure.paths import logs_dir

    configure_logging(logs_dir(), spec.log_level)
    threading.Thread(target=_watch_parent, args=(cancel_event,), daemon=True).start()
    try:
        run_job(spec, events.put, EventToken(cancel_event))
    except OperationCancelled:
        events.put(JobFinished("cancelled"))
    except AppError as error:
        events.put(JobFailed(None, error.message.to_dict()))
        events.put(JobFinished("failed"))
    except Exception as error:  # límite del proceso: se registra con traceback y se informa sin él
        log.exception("Error inesperado en el worker", extra={"event": "worker_crash"})
        details = sanitize(f"{type(error).__name__}: {error}\n{traceback.format_exc(limit=5)}")[-2000:]
        events.put(JobFailed(None, unexpected_error_message(details).to_dict()))
        events.put(JobFinished("failed"))


class JobHandle:
    def __init__(self, process: BaseProcess, events: Any, cancel_event: Any, spec: JobSpec):
        self.process = process
        self.events = events
        self.cancel_event = cancel_event
        self.spec = spec
        self.finished = False

    def poll(self, limit: int = 500) -> list[Event]:
        items: list[Event] = []
        for _ in range(limit):
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, JobFinished):
                self.finished = True
            items.append(item)
        if not items and not self.finished and not self.process.is_alive():
            self.finished = True  # el proceso terminó sin avisar (cierre forzado o fallo nativo)
            message = unexpected_error_message(f"El proceso terminó con código {self.process.exitcode}.")
            items += [JobFailed(None, message.to_dict()), JobFinished("failed")]
        return items

    def cancel(self) -> None:
        self.cancel_event.set()

    def is_alive(self) -> bool:
        return self.process.is_alive()

    def join(self, timeout: float) -> bool:
        self.process.join(timeout)
        return not self.process.is_alive()

    def terminate(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(5)


class JobManager:
    def __init__(self, app_home: Path, log_level: str = "INFO"):
        self.app_home = app_home
        self.log_level = log_level
        self._ctx = mp.get_context("spawn")
        self.current: JobHandle | None = None

    def busy(self) -> bool:
        return self.current is not None and not self.current.finished and self.current.is_alive()

    def start(self, kind: str, payload: dict[str, Any]) -> JobHandle:
        if self.busy():
            raise RuntimeError("Ya hay un trabajo en ejecución.")
        spec = JobSpec(kind, payload, str(self.app_home), self.log_level)
        events, cancel_event = self._ctx.Queue(), self._ctx.Event()
        process = self._ctx.Process(
            target=worker_main, args=(spec, events, cancel_event), daemon=True, name=f"analizador-{kind}"
        )
        process.start()
        self.current = JobHandle(process, events, cancel_event, spec)
        return self.current

    def shutdown(self, timeout: float = 10.0) -> bool:
        """Cierre seguro: cancela, espera el checkpoint y, como último recurso, termina el proceso."""
        handle = self.current
        if handle is None or not handle.is_alive():
            return True
        handle.cancel()
        if handle.join(timeout):
            return True
        handle.terminate()
        return False


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
