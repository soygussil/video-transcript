import pytest

from analizador_video.domain.enums import CapabilityStatus, DeviceKind
from analizador_video.domain.errors import NPU_MODEL_INCOMPATIBLE, OperationCancelled
from analizador_video.infrastructure.hardware.benchmark import BenchmarkCase, BenchmarkService
from analizador_video.infrastructure.hardware.compatibility import (
    COMPATIBLE,
    NOT_COMPATIBLE,
    NOT_VERIFIED,
    CompatibilityRecord,
    CompatibilityStore,
)
from analizador_video.infrastructure.hardware.detector import (
    HardwareDetector,
    HardwareReport,
    OpenVinoInfo,
    derive_capabilities,
)
from analizador_video.infrastructure.hardware.device_selector import BackendAvailability, DeviceSelector
from tests.fixtures.fakes import CountingToken, FakeOcrBackend, FakeTranscriptionBackend

OV = BackendAvailability("openvino", True, True, (DeviceKind.GPU, DeviceKind.NPU, DeviceKind.CPU))
FW = BackendAvailability("faster_whisper", True, True, (DeviceKind.CPU,))


def record(device, status, runtime="2025.1"):
    return CompatibilityRecord(
        "transcripcion", "openvino", "small", device, status, "motivo", 10.0, 5.0, 1.0, runtime, "2026-10-19T10:00:00"
    )


@pytest.fixture
def store(tmp_path):
    return CompatibilityStore(tmp_path / "compat.json")


def plan(store, requested, backends=(OV, FW), fallback=True, preference="auto", runtime="2025.1"):
    return DeviceSelector(store, runtime).plan_transcription("small", requested, preference, list(backends), fallback)


def test_auto_without_verification_uses_cpu_only(store):
    assert [(c.backend, c.device) for c in plan(store, DeviceKind.AUTO).candidates] == [
        ("faster_whisper", DeviceKind.CPU)
    ]


def test_auto_prefers_verified_devices_then_cpu(store):
    store.save([record("gpu", COMPATIBLE), record("npu", COMPATIBLE)])
    result = plan(store, DeviceKind.AUTO)
    assert [c.device for c in result.candidates] == [DeviceKind.GPU, DeviceKind.NPU, DeviceKind.CPU]


def test_npu_incompatible_message(store):
    store.save([record("npu", NOT_COMPATIBLE)])
    result = plan(store, DeviceKind.NPU)
    assert NPU_MODEL_INCOMPATIBLE in result.warnings
    assert [c.device for c in result.candidates] == [DeviceKind.CPU]


def test_explicit_gpu_tried_even_if_unverified(store):
    result = plan(store, DeviceKind.GPU)
    assert [c.device for c in result.candidates] == [DeviceKind.GPU, DeviceKind.CPU]
    assert "sin verificar" in result.candidates[0].reason


def test_fallback_disabled(store):
    assert [c.device for c in plan(store, DeviceKind.GPU, fallback=False).candidates] == [DeviceKind.GPU]
    assert plan(store, DeviceKind.GPU, backends=(FW,), fallback=False).candidates == []


def test_gpu_requested_without_openvino_warns(store):
    result = plan(store, DeviceKind.GPU, backends=(FW,))
    assert result.warnings and [c.device for c in result.candidates] == [DeviceKind.CPU]


def test_runtime_change_invalidates_verification(store):
    store.save([record("gpu", COMPATIBLE, runtime="2024.4")])
    assert plan(store, DeviceKind.AUTO).candidates[0].device is DeviceKind.CPU


def test_backend_preference_and_ocr_plan(store):
    assert [(c.backend, c.device) for c in plan(store, DeviceKind.CPU, preference="openvino").candidates] == [
        ("openvino", DeviceKind.CPU)
    ]
    ocr = DeviceSelector(store).plan_ocr(
        DeviceKind.NPU, [BackendAvailability("easyocr", True, True, (DeviceKind.CPU,))]
    )
    assert ocr.candidates[0].device is DeviceKind.CPU and "CPU" in ocr.warnings[0]


ROCR = BackendAvailability("rapidocr_openvino", True, True, (DeviceKind.GPU, DeviceKind.NPU, DeviceKind.CPU))
EASY = BackendAvailability("easyocr", True, True, (DeviceKind.CPU,))


def ocr_record(device, status):
    return CompatibilityRecord(
        "ocr", "rapidocr_openvino", "es", device, status, "motivo", 10.0, 5.0, 1.0, "2025.1", "2026-10-19T10:00:00"
    )


def ocr_plan(store, requested):
    return DeviceSelector(store, "2025.1").plan_ocr(requested, [EASY, ROCR], ["es"])


def test_ocr_auto_needs_verification_to_use_gpu_or_npu(store):
    assert [(c.backend, c.device) for c in ocr_plan(store, DeviceKind.AUTO).candidates] == [
        ("rapidocr_openvino", DeviceKind.CPU),
        ("easyocr", DeviceKind.CPU),
    ]
    store.save([ocr_record("npu", NOT_COMPATIBLE), ocr_record("gpu", COMPATIBLE)])
    assert [(c.backend, c.device) for c in ocr_plan(store, DeviceKind.AUTO).candidates][:2] == [
        ("rapidocr_openvino", DeviceKind.GPU),
        ("rapidocr_openvino", DeviceKind.CPU),
    ]


def test_ocr_explicit_npu_is_tried_unless_known_incompatible(store):
    assert ocr_plan(store, DeviceKind.NPU).candidates[0].device is DeviceKind.NPU
    store.save([ocr_record("npu", NOT_COMPATIBLE)])
    result = ocr_plan(store, DeviceKind.NPU)
    assert result.candidates[0].device is DeviceKind.CPU and "NPU" in result.warnings[0]


def test_store_ignores_corrupt_file(tmp_path):
    path = tmp_path / "compat.json"
    path.write_text("{roto", encoding="utf-8")
    assert CompatibilityStore(path).load() == []


def service(ov=None, fw_model=True):
    ov = ov or FakeTranscriptionBackend(
        "openvino", (DeviceKind.GPU, DeviceKind.NPU, DeviceKind.CPU), failing_devices={DeviceKind.NPU}
    )
    fw = FakeTranscriptionBackend("faster_whisper", (DeviceKind.CPU,), model=fw_model)
    return BenchmarkService({"openvino": ov, "faster_whisper": fw}, {"fake_ocr": FakeOcrBackend()}, "2025.1")


def test_benchmark_matrix_records_real_outcomes():
    svc = service()
    records = {(r.backend, r.device): r for r in svc.run(svc.candidate_cases(["small"], ["es", "en"]), lambda: False)}
    assert records[("openvino", "gpu")].status == COMPATIBLE
    assert records[("openvino", "npu")].status == NOT_COMPATIBLE
    assert records[("openvino", "npu")].reason == NPU_MODEL_INCOMPATIBLE
    assert records[("faster_whisper", "cpu")].latency_ms is not None
    assert records[("fake_ocr", "cpu")].status == COMPATIBLE


def test_benchmark_compile_failure_and_missing_model():
    svc = service(
        ov=FakeTranscriptionBackend("openvino", (DeviceKind.GPU,), load_failures={DeviceKind.GPU}), fw_model=False
    )
    records = {(r.backend, r.device): r for r in svc.run(svc.candidate_cases(["small"], ["es"]), lambda: False)}
    assert records[("openvino", "gpu")].status == NOT_COMPATIBLE
    assert records[("faster_whisper", "cpu")].status == NOT_VERIFIED


def test_benchmark_cancellation():
    svc = service()
    with pytest.raises(OperationCancelled):
        svc.run(svc.candidate_cases(["small"], ["es"]), CountingToken(after=1).is_cancelled)


def test_benchmark_invalid_output_detected():
    class BadTranscriber:
        backend, device, precision = "openvino", DeviceKind.GPU, "fp16"

        def transcribe(self, *args):
            return "no es una lista"

    class BadBackend(FakeTranscriptionBackend):
        def load(self, model, device, allow_download):
            return BadTranscriber()

    svc = BenchmarkService({"openvino": BadBackend("openvino", (DeviceKind.GPU,))}, {}, None)
    result = svc.run([BenchmarkCase("transcripcion", "openvino", "small", DeviceKind.GPU)], lambda: False)
    assert result[0].status == NOT_COMPATIBLE and "formato" in result[0].reason


def _report(**kwargs):
    base = dict(
        collected_at="",
        app_version="",
        os="",
        python="",
        cpu="CPU",
        cpu_logical_cores=8,
        ram_total_gb=32.0,
        ram_available_gb=20.0,
        gpus_os=[],
        npus_os=[],
        openvino=OpenVinoInfo(),
        ffmpeg_found=False,
        ffmpeg_version=None,
        disk_free_gb=100.0,
        packages={},
        models={},
    )
    base.update(kwargs)
    return {c.component: c for c in derive_capabilities(HardwareReport(**base))}


def test_npu_listed_by_windows_is_never_available_without_runtime():
    caps = _report(npus_os=[{"FriendlyName": "Intel(R) AI Boost"}])
    assert caps["NPU Intel"].status is CapabilityStatus.NEEDS_INSTALL
    assert caps["FFmpeg"].status is CapabilityStatus.NEEDS_INSTALL


def test_openvino_reported_device_is_only_not_verified():
    ov = OpenVinoInfo(installed=True, version="2025.1", devices=[{"id": "CPU"}, {"id": "GPU"}, {"id": "NPU"}])
    caps = _report(openvino=ov)
    assert caps["GPU Intel"].status is CapabilityStatus.NOT_VERIFIED
    assert caps["NPU Intel"].status is CapabilityStatus.NOT_VERIFIED


def test_driver_problem_detected():
    ov = OpenVinoInfo(installed=True, version="2025.1", devices=[{"id": "CPU"}])
    caps = _report(openvino=ov, gpus_os=[{"Name": "Intel(R) Arc(TM) 140V GPU"}])
    assert caps["GPU Intel"].status is CapabilityStatus.DETECTED_NOT_COMPATIBLE


def test_detector_runs_on_this_machine(tmp_path):
    report = HardwareDetector(tmp_path / "modelos", tmp_path).detect()
    assert report.cpu and report.cpu_logical_cores and report.to_dict()["capabilities"][0]["component"] == "CPU"
