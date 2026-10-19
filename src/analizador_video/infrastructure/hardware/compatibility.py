"""Matriz de compatibilidad verificada (resultado de pruebas reales en este equipo)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from analizador_video.domain.enums import DeviceKind
from analizador_video.infrastructure.fileio import atomic_write_json, read_json_object

COMPATIBLE = "compatible"
NOT_COMPATIBLE = "no_compatible"
NOT_VERIFIED = "no_verificado"


@dataclass(frozen=True)
class CompatibilityRecord:
    task: str  # transcripcion | ocr
    backend: str
    model: str
    device: str
    status: str
    reason: str
    latency_ms: float | None
    load_ms: float | None
    peak_rss_mb: float | None
    runtime_version: str | None
    verified_at: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.task, self.backend, self.model, self.device)


class CompatibilityStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[CompatibilityRecord]:
        try:
            data = read_json_object(self.path)
        except ValueError:
            return []  # archivo dañado: se ignora y se vuelve a verificar
        records = []
        for item in (data or {}).get("records", []):
            try:
                records.append(CompatibilityRecord(**item))
            except TypeError:
                continue
        return records

    def save(self, records: list[CompatibilityRecord]) -> None:
        merged = {r.key: r for r in self.load()}
        merged.update({r.key: r for r in records})
        atomic_write_json(self.path, {"version": 1, "records": [asdict(r) for r in merged.values()]})

    def status(
        self, task: str, backend: str, model: str, device: DeviceKind, runtime_version: str | None
    ) -> CompatibilityRecord | None:
        for record in self.load():
            if record.key == (task, backend, model, device.value):
                # Un cambio de runtime/driver invalida la verificación anterior.
                if runtime_version and record.runtime_version and record.runtime_version != runtime_version:
                    return None
                return record
        return None
