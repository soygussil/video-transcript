"""OCR con OpenVINO (RapidOCR / PP-OCRv5) ejecutable en CPU, GPU Intel Arc o NPU, sin PyTorch.

RapidOCR compila sus modelos siempre en "CPU"; aquí se sustituye únicamente la sesión de inferencia
por una que usa el dispositivo pedido. El modelo se descarga sólo con `allow_download`.
"""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from analizador_video.domain.enums import DeviceKind
from analizador_video.domain.errors import BackendUnavailableError, ModelNotAvailableError
from analizador_video.domain.models import OcrBlock

_OV_DEVICE = {DeviceKind.CPU: "CPU", DeviceKind.GPU: "GPU", DeviceKind.NPU: "NPU"}
_PATCH_LOCK = threading.Lock()
_DET_PREFIX, _REC_PREFIX = "ch_PP-OCRv5_det", "latin_PP-OCRv5_rec"


def _install_device_session(device_name: str) -> None:
    """Hace que RapidOCR compile con `device_name`. Se llama bajo _PATCH_LOCK antes de construir RapidOCR."""
    import rapidocr.inference_engine.openvino as engine_module
    from rapidocr.inference_engine.openvino import OpenVINOInferSession

    class DeviceSession(OpenVINOInferSession):
        def __init__(self, cfg: Any):
            from openvino import Core
            from rapidocr.inference_engine.base import FileInfo
            from rapidocr.utils.download_file import DownloadFile, DownloadFileInput
            from rapidocr.utils.log import logger

            core = Core()
            model_path = cfg.get("model_path", None)
            if model_path is None:
                info = self.get_model_url(
                    FileInfo(
                        engine_type=cfg.engine_type,
                        ocr_version=cfg.ocr_version,
                        task_type=cfg.task_type,
                        lang_type=cfg.lang_type,
                        model_type=cfg.model_type,
                    )
                )
                model_path = Path(cfg.model_root_dir) / Path(info["model_dir"]).name
                DownloadFile.run(
                    DownloadFileInput(
                        file_url=info["model_dir"], sha256=info["SHA256"], save_path=model_path, logger=logger
                    )
                )
            model_path = Path(model_path)
            self._verify_model(model_path)
            self.model = core.read_model(model_path)
            self.session = core.compile_model(model=self.model, device_name=device_name).create_infer_request()

    engine_module.OpenVINOInferSession = DeviceSession  # type: ignore[misc]  # get_engine() lo importa en cada construcción


class _OpenVinoOcrReader:
    backend = "rapidocr_openvino"

    def __init__(self, engine: Any, device: DeviceKind):
        self._engine = engine
        self.device = device

    def recognize(self, image: np.ndarray) -> list[OcrBlock]:
        if image.ndim == 2:
            image = np.stack([image] * 3, axis=-1)
        result = self._engine(image, use_cls=False)
        texts = getattr(result, "txts", None)
        if not texts:
            return []
        boxes, scores = result.boxes, result.scores
        return [
            OcrBlock(str(text), round(float(score), 4), tuple((float(p[0]), float(p[1])) for p in box))
            for box, text, score in zip(boxes, texts, scores, strict=True)
        ]


class RapidOcrOpenVinoBackend:
    name = "rapidocr_openvino"

    def __init__(self, models_root: Path):
        self.models_root = models_root / "rapidocr"

    def is_installed(self) -> bool:
        return importlib.util.find_spec("rapidocr") is not None and importlib.util.find_spec("openvino") is not None

    def supported_devices(self) -> tuple[DeviceKind, ...]:
        return (DeviceKind.GPU, DeviceKind.NPU, DeviceKind.CPU)

    def models_available(self, languages: Sequence[str]) -> bool:
        if not self.models_root.exists():
            return False
        names = [p.name for p in self.models_root.glob("*.onnx")]
        return any(n.startswith(_DET_PREFIX) for n in names) and any(n.startswith(_REC_PREFIX) for n in names)

    def load(self, languages: Sequence[str], device: DeviceKind, allow_download: bool) -> _OpenVinoOcrReader:
        if not self.is_installed():
            raise BackendUnavailableError(
                "El OCR con OpenVINO (RapidOCR) no está instalado",
                "No se puede usar GPU o NPU Intel para el OCR",
                "Instala los componentes opcionales 'ocr-openvino'",
            )
        if device is DeviceKind.AUTO:
            raise ValueError("El dispositivo debe resolverse antes de cargar el modelo.")
        if not allow_download and not self.models_available(languages):
            raise ModelNotAvailableError(
                "Los modelos de OCR OpenVINO no están descargados",
                "El OCR acelerado no está disponible",
                "Descárgalos con 'analizador-video modelos descargar --ocr-openvino'",
                saved=True,
            )
        from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

        self.models_root.mkdir(parents=True, exist_ok=True)
        # RapidOCR copia Global.model_root_dir a cada etapa, por eso sólo se fija aquí.
        params: dict[str, Any] = {
            "Global.use_cls": False,
            "Global.model_root_dir": str(self.models_root),
            "Global.log_level": "warning",
        }
        for task, lang in (("Det", LangDet.CH), ("Rec", LangRec.LATIN)):
            params.update(
                {
                    f"{task}.engine_type": EngineType.OPENVINO,
                    f"{task}.ocr_version": OCRVersion.PPOCRV5,
                    f"{task}.lang_type": lang,
                    f"{task}.model_type": ModelType.MOBILE,
                }
            )
        try:
            with _PATCH_LOCK:
                _install_device_session(_OV_DEVICE[device])
                engine = RapidOCR(params=params)
                # RapidOCR carga los modelos en el primer uso; se fuerza aquí para que la descarga y la
                # compilación en el dispositivo fallen ahora (y activen el fallback) y no imagen por imagen.
                engine._load_det_model()
                engine._load_rec_model()
        except (RuntimeError, ValueError, OSError, ImportError, KeyError) as error:
            raise BackendUnavailableError(
                f"OpenVINO no pudo preparar el OCR para {device.value.upper()}",
                "Ese dispositivo no se usará para el OCR",
                "Se usará el siguiente dispositivo permitido",
                details=f"{type(error).__name__}: {str(error)[:400]}",
            ) from error
        return _OpenVinoOcrReader(engine, device)
