# Analizador de video

Aplicación de escritorio para Windows que analiza videos de procesos, demostraciones y sesiones funcionales:
detecta las pantallas clave, importa o genera la transcripción, reconoce el texto visible (OCR), alinea
«lo que se vio» con «lo que se dijo» y genera reportes Word, Excel, JSON, TXT y SRT.

**Todo se procesa en el equipo.** No hay telemetría, no se envía contenido a la nube y la aplicación funciona
sin Azure OpenAI, OpenAI ni ningún otro LLM.

## Instalación (desarrollo)

Requisitos: Windows 10/11, Python 3.11–3.13. FFmpeg sólo es necesario para la transcripción automática.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar_windows.ps1            # CPU
powershell -ExecutionPolicy Bypass -File scripts\instalar_windows.ps1 -ConOpenVino  # + GPU/NPU Intel (opcional)
.\.venv\Scripts\analizador-video-gui.exe
```

`instalar_windows.bat` sigue funcionando y llama al script anterior.

## Uso con la interfaz

1. **Inicio**: arrastra el video (o `Ctrl+O`), agrega opcionalmente un VTT/SRT, elige el perfil y presiona
   **Analizar video**. La validación aparece antes de empezar.
2. **Procesamiento**: progreso por etapa, dispositivo usado, advertencias y **Cancelar análisis**. El avance
   se guarda continuamente; si cierras la aplicación, puedes continuar después.
3. **Proyecto**: capturas, estado de cada etapa y exportación (Word, Excel, JSON, TXT, SRT) sin reprocesar.
4. **Proyectos**: búsqueda, filtro por estado, abrir, continuar, abrir carpeta y eliminar.
5. **Diagnóstico**: hardware, componentes y matriz de compatibilidad; **Exportar diagnóstico** genera un
   ZIP sanitizado para soporte.

Atajos: `Ctrl+O` abrir video · `Ctrl+E` exportar · `Ctrl+F` buscar proyectos · `Ctrl+1/2/3` navegar ·
`F5` actualizar · `Esc` cierra diálogos (nunca cancela procesos).

## Uso por línea de comandos

```powershell
analizador-video analizar "C:\Videos\sesion.mp4" --transcript "C:\Videos\sesion.vtt" --perfil balanceado
analizador-video continuar sesion
analizador-video exportar sesion --formatos word,excel --sin-datos-sensibles
analizador-video diagnostico --probar --modelos small
analizador-video modelos listar
analizador-video modelos descargar --ocr --whisper small     # pide confirmación
analizador-video importar-legado salida\sesion --video "C:\Videos\sesion.mp4"
analizador-video gui
```

Opciones: `--pasos pantallas,audio,ocr,alinear,reporte`, `--forzar ocr|todo`, `--dispositivo auto|gpu|npu|cpu`,
`--sin-ocr`, `--sin-transcripcion-automatica`, `--config`, `--log-level`.

Códigos de salida: `0` éxito (incluye advertencias) · `1` fallo de procesamiento · `2` entrada o
configuración inválida · `130` cancelado (el avance queda guardado).

La CLI anterior se conserva: `python main.py --video ... --transcript ... --sin-ia`.
`--sin-ia` está **obsoleto** y equivale a `--sin-transcripcion-automatica`.

## Archivos generados

```
Documentos\Analizador de video\Proyectos\<proyecto>\
  project.db        estado del proyecto (SQLite; sin binarios)
  source\           copia del video sólo si se eligió «Copiar el video»
  frames\           capturas JPG
  audio\            audio_16k.wav (sólo con transcripción automática)
  transcripts\      copia del VTT/SRT importado
  reports\          reporte_analisis.docx, reporte_analisis.xlsx, analisis.json, transcripcion.txt, transcripcion.srt
%LOCALAPPDATA%\AnalizadorVideo\   logs, preferencias, modelos y compatibilidad verificada
```

## Transcripción, OCR y aceleración (GPU/NPU Intel)

| Tarea | Motor | Dispositivos |
|---|---|---|
| Transcripción importada | VTT/SRT (UTF-8, UTF-8 BOM, UTF-16, CP1252 con aviso) | — |
| Transcripción automática | faster-whisper (int8) | CPU |
| Transcripción automática | OpenVINO GenAI (modelo exportado a IR) | GPU, NPU, CPU |
| OCR | EasyOCR | CPU |
| Capturas y reportes | OpenCV, python-docx, openpyxl | CPU |

- **Automático** usa GPU o NPU **sólo** si «Probar compatibilidad» verificó en este equipo que el modelo
  compila y produce una salida válida. Si falla, se registra, se avisa y se continúa en CPU. Nunca hay
  fallback a la nube.
- Que Windows u OpenVINO enumeren la NPU no la marca como disponible. Si el modelo no es compatible se
  muestra: *«NPU detectada, pero el modelo de transcripción seleccionado no es compatible.»*
- Modelo OpenVINO: exporta Whisper con `optimum-cli export openvino --model openai/whisper-small
  %LOCALAPPDATA%\AnalizadorVideo\modelos\openvino\whisper-small` (requiere `optimum-intel`, descarga explícita).
- Los modelos nunca se descargan sin confirmación (`modelos.permitir_descarga: false` por defecto).

## Configuración

No necesitas editar YAML: la interfaz guarda preferencias. Para soporte o automatización, `--config` acepta
un YAML parcial (v2) o el `config.yaml` original (v1, se migra automáticamente). Los valores predeterminados
y los perfiles viven en `src/analizador_video/config/default_config.yaml`; todo se valida con mensajes claros.

## Privacidad

- Sin telemetría ni llamadas de red durante el procesamiento.
- Los logs son JSON, rotan y se sanitizan (rutas personales y secretos); no incluyen transcripción ni OCR.
- «Exportar diagnóstico» no incluye transcripciones, OCR ni capturas.
- Exportar con «Excluir datos sensibles» reemplaza hablantes por «Participante» y omite rutas locales.
- `.env.example` no se usa; se conserva como referencia para un posible backend de nube **opcional** futuro.

## Diagnóstico de problemas

| Mensaje | Qué hacer |
|---|---|
| No se encontró FFmpeg | Instala FFmpeg y agrégalo al PATH, o usa un VTT/SRT. |
| Modelos de OCR / transcripción no descargados | `analizador-video modelos descargar --ocr --whisper small` |
| El video original ya no está en su ubicación | Restáuralo o crea el proyecto con «Copiar el video». |
| GPU/NPU «No verificado» | Diagnóstico → Probar compatibilidad. |

## Desarrollo y calidad

```powershell
.\.venv\Scripts\python -m pytest              # unitarias, integración y UI (sin modelos)
.\.venv\Scripts\python -m pytest -m benchmark tests\benchmarks -s   # hardware y modelos reales
.\.venv\Scripts\python -m ruff check src tests ; .\.venv\Scripts\python -m mypy
powershell -File scripts\build_windows.ps1     # ejecutable portable sin consola en dist\
```

Arquitectura, contratos y decisiones: `docs/ARQUITECTURA.md`. Auditoría inicial: `docs/AUDITORIA_FASE0.md`.
