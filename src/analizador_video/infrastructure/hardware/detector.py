"""Detección de hardware y componentes. Nunca declara compatibilidad: sólo lo que observa.

"Detectado" (Windows u OpenVINO enumeran el dispositivo) es distinto de "compatible"
(un modelo compiló y produjo una salida válida; ver BenchmarkService).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from analizador_video import __version__
from analizador_video.domain.enums import CapabilityStatus
from analizador_video.domain.models import HardwareCapability
from analizador_video.infrastructure.system import NO_WINDOW, ffmpeg_version, find_ffmpeg, free_bytes

PACKAGES = (
    "opencv-python-headless",
    "numpy",
    "PySide6-Essentials",
    "faster-whisper",
    "ctranslate2",
    "easyocr",
    "rapidocr",
    "torch",
    "openvino",
    "openvino-genai",
    "python-docx",
    "openpyxl",
)


@dataclass
class OpenVinoInfo:
    installed: bool = False
    version: str | None = None
    genai_installed: bool = False
    devices: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None


@dataclass
class HardwareReport:
    collected_at: str
    app_version: str
    os: str
    python: str
    cpu: str
    cpu_logical_cores: int | None
    ram_total_gb: float | None
    ram_available_gb: float | None
    gpus_os: list[dict[str, str]]
    npus_os: list[dict[str, str]]
    openvino: OpenVinoInfo
    ffmpeg_found: bool
    ffmpeg_version: str | None
    disk_free_gb: float | None
    packages: dict[str, str | None]
    models: dict[str, bool]
    capabilities: list[HardwareCapability] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = [
            {"component": c.component, "status": c.status.value, "detail": c.detail, "version": c.version}
            for c in self.capabilities
        ]
        return data


def _powershell_json(command: str) -> list[dict[str, str]]:
    """Consulta local de WMI/PnP. Sin red. Devuelve [] si no es Windows o falla."""
    if sys.platform != "win32":
        return []
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command + " | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=NO_WINDOW,
            check=False,
        )
        data = json.loads(completed.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    items = data if isinstance(data, list) else [data]
    return [{k: str(v) for k, v in item.items() if v is not None} for item in items if isinstance(item, dict)]


def _ram_gb() -> tuple[float | None, float | None]:
    try:
        import psutil
    except ImportError:
        return None, None
    memory = psutil.virtual_memory()
    return round(memory.total / 2**30, 1), round(memory.available / 2**30, 1)


def _cpu_name() -> str:
    if sys.platform == "win32":
        rows = _powershell_json("Get-CimInstance Win32_Processor | Select-Object Name")
        if rows and rows[0].get("Name"):
            return rows[0]["Name"].strip()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine() or "No detectado"


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _openvino_info() -> OpenVinoInfo:
    info = OpenVinoInfo(genai_installed=importlib.util.find_spec("openvino_genai") is not None)
    if importlib.util.find_spec("openvino") is None:
        return info
    info.installed = True
    try:
        import openvino

        core = openvino.Core()
        info.version = str(openvino.get_version())
        for device in core.available_devices:
            entry = {"id": str(device)}
            for prop in ("FULL_DEVICE_NAME", "GPU_DEVICE_TOTAL_MEM_SIZE", "DEVICE_ARCHITECTURE", "NPU_DRIVER_VERSION"):
                try:
                    entry[prop.lower()] = str(core.get_property(device, prop))
                except (RuntimeError, TypeError):
                    continue
            info.devices.append(entry)
    except (RuntimeError, ImportError, OSError) as error:
        info.error = f"{type(error).__name__}: {str(error)[:300]}"
    return info


def _model_inventory(models_root: Path) -> dict[str, bool]:
    inventory: dict[str, bool] = {}
    fw = models_root / "faster-whisper"
    if fw.exists():
        for entry in fw.iterdir():
            if entry.is_dir() and (entry / "snapshots").exists():
                inventory[f"faster-whisper:{entry.name.split('faster-whisper-')[-1]}"] = True
    ov = models_root / "openvino"
    if ov.exists():
        for entry in ov.glob("whisper-*"):
            inventory[f"openvino:{entry.name}"] = (entry / "openvino_encoder_model.xml").exists()
    inventory["easyocr:modelos"] = (models_root / "easyocr" / "craft_mlt_25k.pth").exists()
    return inventory


class HardwareDetector:
    def __init__(self, models_root: Path, projects_root: Path):
        self.models_root = models_root
        self.projects_root = projects_root

    def detect(self) -> HardwareReport:
        total, available = _ram_gb()
        ffmpeg = find_ffmpeg()
        try:
            disk: float | None = round(free_bytes(self.projects_root) / 2**30, 1)
        except OSError:
            disk = None
        report = HardwareReport(
            collected_at=datetime.now().isoformat(timespec="seconds"),
            app_version=__version__,
            os=f"{platform.system()} {platform.release()} ({platform.version()})",
            python=sys.version.split()[0],
            cpu=_cpu_name(),
            cpu_logical_cores=os.cpu_count(),
            ram_total_gb=total,
            ram_available_gb=available,
            gpus_os=_powershell_json("Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion"),
            npus_os=_powershell_json(
                "Get-PnpDevice -PresentOnly | Where-Object { $_.Class -eq 'ComputeAccelerator' }"
                " | Select-Object FriendlyName,Status"
            ),
            openvino=_openvino_info(),
            ffmpeg_found=ffmpeg is not None,
            ffmpeg_version=ffmpeg_version(ffmpeg) if ffmpeg else None,
            disk_free_gb=disk,
            packages=_package_versions(),
            models=_model_inventory(self.models_root),
        )
        report.capabilities = derive_capabilities(report)
        return report


def derive_capabilities(report: HardwareReport) -> list[HardwareCapability]:
    caps = [HardwareCapability("CPU", CapabilityStatus.AVAILABLE, report.cpu)]
    caps.append(
        HardwareCapability("FFmpeg", CapabilityStatus.AVAILABLE, "Encontrado en PATH", report.ffmpeg_version)
        if report.ffmpeg_found
        else HardwareCapability(
            "FFmpeg",
            CapabilityStatus.NEEDS_INSTALL,
            "Necesario para la transcripción automática; no para importar VTT/SRT",
        )
    )
    ov = report.openvino
    ov_ids = {d["id"].split(".")[0] for d in ov.devices}
    if not ov.installed:
        caps.append(HardwareCapability("OpenVINO", CapabilityStatus.NEEDS_INSTALL, "Componente opcional no instalado"))
    elif ov.error:
        caps.append(HardwareCapability("OpenVINO", CapabilityStatus.DETECTED_NOT_COMPATIBLE, ov.error, ov.version))
    else:
        caps.append(
            HardwareCapability(
                "OpenVINO",
                CapabilityStatus.AVAILABLE,
                "Dispositivos: " + (", ".join(sorted(ov_ids)) or "ninguno"),
                ov.version,
            )
        )
    for kind, label, os_list in (("GPU", "GPU Intel", report.gpus_os), ("NPU", "NPU Intel", report.npus_os)):
        os_names = ", ".join(d.get("Name") or d.get("FriendlyName") or "" for d in os_list).strip(", ")
        if kind in ov_ids:
            caps.append(
                HardwareCapability(
                    label,
                    CapabilityStatus.NOT_VERIFIED,
                    "Reportado por OpenVINO; falta una prueba real con el modelo (Diagnóstico → Probar compatibilidad)",
                )
            )
        elif os_names and not ov.installed:
            caps.append(
                HardwareCapability(
                    label, CapabilityStatus.NEEDS_INSTALL, f"Windows lo enumera ({os_names}); falta el runtime OpenVINO"
                )
            )
        elif os_names:
            caps.append(
                HardwareCapability(
                    label,
                    CapabilityStatus.DETECTED_NOT_COMPATIBLE,
                    f"Windows lo enumera ({os_names}) pero OpenVINO no lo reporta; revisa el driver",
                )
            )
        else:
            caps.append(HardwareCapability(label, CapabilityStatus.UNAVAILABLE, "No detectado"))
    for package, label in (
        ("faster-whisper", "Transcripción (faster-whisper)"),
        ("easyocr", "OCR (EasyOCR)"),
        ("rapidocr", "OCR (RapidOCR + OpenVINO)"),
        ("openvino-genai", "Transcripción (OpenVINO GenAI)"),
    ):
        version = report.packages.get(package)
        caps.append(
            HardwareCapability(label, CapabilityStatus.AVAILABLE, "Instalado", version)
            if version
            else HardwareCapability(label, CapabilityStatus.NEEDS_INSTALL, "Componente opcional no instalado")
        )
    return caps
