"""Benchmark con modelos y hardware reales. Ejecutar explícitamente en el equipo objetivo:

    pytest -m benchmark tests/benchmarks -s

No descarga modelos: sólo prueba los que ya existen en la carpeta de modelos.
"""

import json

import pytest

from analizador_video.application.backends import BackendRegistry
from analizador_video.application.cancellation import EventToken
from analizador_video.application.diagnostics import collect_diagnostics, run_benchmark

pytestmark = pytest.mark.benchmark


def test_real_compatibility_matrix(tmp_path):
    registry = BackendRegistry.default()
    if not any(b.is_installed() for b in [*registry.transcription.values(), *registry.ocr.values()]):
        pytest.skip("No hay motores de transcripción ni OCR instalados en este equipo.")
    models = ["tiny", "base", "small"]
    records = run_benchmark(registry, models, EventToken())
    data = collect_diagnostics(registry, models)
    (tmp_path / "benchmark.json").write_text(json.dumps({"records": records, "diagnostico": data}, default=str))
    print("\nBackend | Modelo | CPU | GPU | NPU | Estado | Motivo")
    for row in data["matriz"]:
        print(" | ".join(row[k] for k in ("backend", "modelo", "cpu", "gpu", "npu", "estado", "motivo")))
    assert all(r["status"] in ("compatible", "no_compatible", "no_verificado") for r in records)
