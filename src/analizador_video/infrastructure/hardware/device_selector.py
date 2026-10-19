"""DeviceSelector: plan ordenado de (backend, dispositivo) con fallback a CPU.

- Automático sólo usa GPU/NPU con una verificación real exitosa para ese backend + modelo.
- Una selección explícita (GPU/NPU) se intenta aunque no esté verificada, salvo que exista una
  verificación fallida; si falla, se informa y se continúa con el siguiente candidato.
- CPU es el último recurso (si `cpu_fallback`). Nunca hay fallback a servicios de nube.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from analizador_video.domain.enums import DeviceKind
from analizador_video.domain.errors import NPU_MODEL_INCOMPATIBLE
from analizador_video.infrastructure.hardware.compatibility import COMPATIBLE, NOT_COMPATIBLE, CompatibilityStore


@dataclass(frozen=True)
class Candidate:
    backend: str
    device: DeviceKind
    reason: str


@dataclass
class DevicePlan:
    candidates: list[Candidate]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BackendAvailability:
    name: str
    installed: bool
    model_available: bool
    devices: tuple[DeviceKind, ...]


class DeviceSelector:
    def __init__(self, store: CompatibilityStore | None, runtime_version: str | None = None):
        self.store = store
        self.runtime_version = runtime_version

    def plan_transcription(
        self,
        model: str,
        requested: DeviceKind,
        backend_preference: str,
        backends: list[BackendAvailability],
        cpu_fallback: bool = True,
    ) -> DevicePlan:
        usable = {
            b.name: b for b in backends if b.installed and b.model_available and backend_preference in ("auto", b.name)
        }
        plan = DevicePlan([])
        if requested is DeviceKind.AUTO:
            accelerated = [DeviceKind.GPU, DeviceKind.NPU]
        else:
            accelerated = [requested] if requested in (DeviceKind.GPU, DeviceKind.NPU) else []
        for device in accelerated:
            backend = usable.get("openvino")
            if backend is None or device not in backend.devices:
                if requested is device:
                    plan.warnings.append(
                        f"{device.value.upper()} solicitada, pero no hay un motor compatible "
                        "instalado con un modelo OpenVINO. Se usará CPU."
                    )
                continue
            record = (
                self.store.status("transcripcion", "openvino", model, device, self.runtime_version)
                if self.store is not None
                else None
            )
            if record is not None and record.status == NOT_COMPATIBLE:
                plan.warnings.append(
                    NPU_MODEL_INCOMPATIBLE
                    if device is DeviceKind.NPU
                    else f"GPU detectada, pero el modelo «{model}» no superó la prueba de compatibilidad."
                )
                continue
            verified = record is not None and record.status == COMPATIBLE
            if requested is DeviceKind.AUTO and not verified:
                continue  # Automático privilegia compatibilidad demostrada
            reason = "verificado en este equipo" if verified else "seleccionado manualmente (sin verificar)"
            plan.candidates.append(Candidate("openvino", device, reason))
        if requested in (DeviceKind.CPU, DeviceKind.AUTO) or cpu_fallback:
            if "faster_whisper" in usable:
                plan.candidates.append(Candidate("faster_whisper", DeviceKind.CPU, "CPU (int8)"))
            elif "openvino" in usable:
                plan.candidates.append(Candidate("openvino", DeviceKind.CPU, "CPU con OpenVINO"))
        return plan

    def plan_ocr(
        self,
        requested: DeviceKind,
        backends: list[BackendAvailability],
        languages: Sequence[str] = (),
        accelerated_backend: str = "rapidocr_openvino",
    ) -> DevicePlan:
        """Mismo criterio que la transcripción: Automático sólo acelera con compatibilidad demostrada."""
        usable = {b.name: b for b in backends if b.installed and b.model_available}
        plan = DevicePlan([])
        model = "+".join(languages)
        if requested is DeviceKind.AUTO:
            accelerated = [DeviceKind.GPU, DeviceKind.NPU]
        elif requested is DeviceKind.NPU:
            accelerated = [DeviceKind.NPU, DeviceKind.GPU]  # el NPU suele rechazar OCR: GPU si ya se verificó
        else:
            accelerated = [requested] if requested is DeviceKind.GPU else []
        backend = usable.get(accelerated_backend)
        for device in accelerated:
            if backend is None or device not in backend.devices:
                if requested is device:
                    plan.warnings.append(
                        f"No hay un motor OCR acelerado compatible con {device.value.upper()} Intel "
                        "(falta OpenVINO o sus modelos); el OCR usará CPU."
                    )
                continue
            record = (
                self.store.status("ocr", accelerated_backend, model, device, self.runtime_version)
                if self.store is not None
                else None
            )
            if record is not None and record.status == NOT_COMPATIBLE:
                plan.warnings.append(
                    f"{device.value.upper()} detectada, pero el OCR no superó la prueba de compatibilidad; se usará "
                    "el siguiente dispositivo."
                )
                continue
            verified = record is not None and record.status == COMPATIBLE
            if device is not requested and not verified:
                continue  # sólo se intenta sin verificar el dispositivo pedido de forma explícita
            reason = "verificado en este equipo" if verified else "seleccionado manualmente (sin verificar)"
            plan.candidates.append(Candidate(accelerated_backend, device, reason))
        # CPU: primero el motor OpenVINO (más liviano, sin PyTorch) y luego el resto.
        cpu_backends = sorted(
            (b for b in usable.values() if DeviceKind.CPU in b.devices), key=lambda b: b.name != accelerated_backend
        )
        plan.candidates += [Candidate(b.name, DeviceKind.CPU, "CPU") for b in cpu_backends]
        return plan
