# Cambios

## 0.2.0 — Aplicación de escritorio

### Agregado
- Paquete `src/analizador_video` con capas de dominio, aplicación, infraestructura, CLI y UI (PySide6).
- Proyectos en SQLite (`project.db`) con migraciones versionadas, respaldo automático y rollback.
- Reanudación por etapa con checkpoints; recuperación tras cierre inesperado; bloqueo de proyecto.
- Procesamiento en un proceso worker (la UI nunca procesa video), cancelación cooperativa y cierre seguro.
- Interfaz: Inicio (arrastrar y soltar, perfiles, validación), Procesamiento, Proyecto (capturas, exportación),
  Proyectos (búsqueda y filtros), Diagnóstico; temas claro y oscuro; atajos de teclado.
- Perfiles Rápido, Balanceado y Máxima precisión; configuración tipada y validada.
- Detección de hardware, matriz de compatibilidad verificada, `DeviceSelector` con fallback a CPU y
  `BenchmarkService`; backend OpenVINO GenAI opcional para GPU/NPU Intel.
- Exportación JSON (esquema 2), TXT y SRT con correcciones manuales; opción «Excluir datos sensibles».
- CLI `analizador-video` (analizar, continuar, exportar, diagnostico, modelos, importar-legado, gui).
- Importador de resultados del formato anterior (`salida/<video>/*.json`).
- Logging JSON con rotación y sanitización; paquete de diagnóstico.
- PyInstaller (`.spec`, información de versión, icono), scripts de build y limpieza, CI de GitHub Actions.

### Corregido (Fase 1)
- A: la prueba de alineación no coincidía con el formato de `dicho`; contrato único documentado.
- B: `--sin-ia` no tenía efecto; ahora es un alias obsoleto de `--sin-transcripcion-automatica`.
- C: `--pasos` no controlaba `alinear`; cada etapa se ejecuta, omite, reutiliza o invalida.
- D: reanudar sin JSON previo producía `KeyError`; ahora hay un mensaje accionable.
- E: los checkpoints de OCR dependían del índice absoluto; ahora cuentan lo procesado en la ejecución.
- F: `guardar_cada` se valida como entero > 0.
- G: el Word se llamaba `reporte_fotos_transcript_por_segundo.docx`; ahora `reporte_analisis.docx`.
- H: `bloque_minutos` no se usaba; ahora define bloques reanudables de transcripción.
- I: el formato de tiempo podía producir `.1000`; ahora redondea a milisegundos y usa `divmod`.
- J: el OCR capturaba `Exception` y guardaba rutas internas; ahora errores tipados, sin rutas.
- K: validación completa de entradas y configuración.

### Cambios incompatibles
- Estructura de la carpeta de resultados: antes `salida/<video>/pantallas`, `frames.json`, etc.; ahora un
  proyecto con `project.db`, `frames/` y `reports/`. **Migración:** `analizador-video importar-legado`.
  Las carpetas antiguas no se modifican (respaldo implícito).
- `config.yaml`: formato v2; el v1 se migra automáticamente al cargarlo (`ocr.cpu` → `ocr.dispositivo`).
- Retiradas de dependencias sin uso: `openai`, `python-dotenv`, `matplotlib`, `tqdm`.

### Rollback
- Código: volver a la versión 0.1 del repositorio; los resultados antiguos siguen intactos.
- Base de datos: cada migración crea `project.backup-v<N>.db`; restaurar con
  `analizador_video.infrastructure.persistence.database.restore_backup` o copiando el archivo con la app cerrada.
