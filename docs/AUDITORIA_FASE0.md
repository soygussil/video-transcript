# Auditoría Fase 0 — repositorio original `analizador_video`

Clasificación: **HECHO** (verificado en código o ejecución), **INFERENCIA**, **DESCONOCIDO**.

## Árbol relevante original
```
main.py  config.yaml  README.md  requirements.txt  instalar_windows.bat  .env.example  .gitignore
src/ utils.py frames.py audio.py ocr.py align.py report_word.py report_excel.py
tests/ test_core.py
(raíz) pyvenv.cfg  distutils-precedence.pth  isympy.py   ← restos de un entorno virtual
```

## Hechos
- Entry point único `main.py` (argparse). Flujo: frames → audio/VTT → OCR → align → Word/Excel/JSON/TXT/SRT.
- `.gitignore` contenía `*` (generado por `venv`): el repositorio raíz *era* un entorno virtual.
- `pyvenv.cfg` incluía rutas personales (`C:\Users\<usuario>\...`) y Python 3.13.7; `isympy.py` y
  `distutils-precedence.pth` son archivos de SymPy/setuptools copiados accidentalmente. No se editaron;
  se excluyen del repositorio nuevo.
- Dependencias declaradas sin uso en el código: `openai`, `python-dotenv`, `matplotlib`. `tqdm` sólo en barras de consola.
- `subprocess` importado sin uso en `audio.py`; variable `times` sin uso; `WD_SECTION` sin uso.
- Prueba inicial: **1 aprobada, 1 fallida** (`test_align`, problema A).
- Problemas A–K reproducidos con scripts (p. ej. `hms(0.9996)` → `00:00:00.1000`; `--pasos reporte` → `KeyError`).
- No había CI, empaquetado, recursos gráficos ni pruebas de integración.

## Inferencias
- El repositorio se subió a OneDrive junto con el `.venv`; sus `Lib/` y `Scripts/` no estaban accesibles.
- El uso real es con VTT de Teams (etiquetas `<v Hablante>`), por lo que la importación es la ruta principal.

## Desconocidos
- Compatibilidad real de GPU Arc 140V / NPU AI Boost con Whisper en OpenVINO: **no verificada**; requiere
  ejecutar `analizador-video diagnostico --probar` en el equipo objetivo.
- Política corporativa de firma, MSI y distribución de FFmpeg.
- El entorno de validación fue Linux (sandbox); el ejecutable de Windows no se construyó aquí.
