"""Cancelación cooperativa. El motor revisa el token entre unidades de trabajo."""

from __future__ import annotations

import threading
from typing import Protocol

from analizador_video.domain.errors import OperationCancelled


class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...


class EventToken:
    """Funciona con threading.Event o multiprocessing.Event (misma interfaz)."""

    def __init__(self, event: object | None = None):
        self._event = event if event is not None else threading.Event()

    def cancel(self) -> None:
        self._event.set()  # type: ignore[attr-defined]

    def is_cancelled(self) -> bool:
        return bool(self._event.is_set())  # type: ignore[attr-defined]

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise OperationCancelled()
