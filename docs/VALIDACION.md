# Validación ejecutada (19-oct-2026)

Entorno: Linux (sandbox), Python 3.12, PySide6 6.12 en modo `offscreen`. **No** es el equipo Windows objetivo.

| Verificación | Comando | Resultado |
|---|---|---|
| Lint | `ruff check src tests main.py` | Sin errores |
| Formato | `ruff format --check src tests main.py` | 88 archivos formateados |
| Tipos | `mypy` | Sin errores (69 archivos) |
| Unitarias | `pytest tests/unit` | 83 aprobadas |
| Integración | `pytest tests/integration` | 30 aprobadas (incluye `main.py` heredado y worker real) |
| UI | `pytest tests/ui` | 9 aprobadas (pytest-qt, servicios simulados) |
| Total + cobertura | `pytest --cov=analizador_video` | 122 aprobadas, 1 benchmark excluido, 86 % |

Línea base del repositorio original: 1 aprobada, 1 fallida (`test_align`).

## No ejecutado aquí (pendiente en Windows)
- Build PyInstaller y arranque del `.exe` sin consola en un equipo limpio (`scripts/build_windows.ps1`).
- Benchmark real con modelos y GPU Arc 140V / NPU AI Boost (`pytest -m benchmark tests/benchmarks -s`
  o `analizador-video diagnostico --probar`). Ninguna compatibilidad GPU/NPU se declara hasta entonces.
- EasyOCR y faster-whisper reales (en las pruebas se usan dobles; no hay descarga de modelos).
