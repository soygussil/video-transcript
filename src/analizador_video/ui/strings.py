"""Textos de la interfaz (español de México), centralizados para futura localización."""

from __future__ import annotations

from typing import Final

APP_TITLE: Final = "Analizador de video"
NAV_HOME: Final = "Inicio"
NAV_PROJECTS: Final = "Proyectos"
NAV_DIAGNOSTICS: Final = "Diagnóstico"
THEME_TO_DARK: Final = "Usar tema oscuro"
THEME_TO_LIGHT: Final = "Usar tema claro"
JOB_RUNNING_LINK: Final = "Ver análisis en curso"

HOME_TITLE: Final = "Analizar un video"
HOME_SUBTITLE: Final = "Todo se procesa en este equipo. Ningún contenido se envía a Internet."
DROP_TITLE: Final = "Arrastra aquí tu video"
DROP_HINT: Final = "o presiona Entrar para buscarlo (MP4, MKV, MOV, AVI, WEBM, M4V, WMV)"
DROP_ACCESSIBLE: Final = "Zona para arrastrar un video. Presiona Entrar o Espacio para seleccionar un archivo."
SELECT_VIDEO: Final = "Seleccionar video…"
SELECT_TRANSCRIPT: Final = "Agregar transcripción (opcional)…"
REMOVE_TRANSCRIPT: Final = "Quitar transcripción"
TRANSCRIPT_NONE: Final = "Sin transcripción: se usará la transcripción automática si está disponible."
PROFILE_LABEL: Final = "Perfil de procesamiento"
PROFILES: Final = {
    "rapido": ("Rápido", "Menos capturas y modelo ligero. Ideal para una revisión inicial."),
    "balanceado": ("Balanceado", "Equilibrio entre tiempo y detalle. Recomendado."),
    "maxima_precision": ("Máxima precisión", "Más capturas y modelo más preciso. Tarda más."),
}
DEVICE_LABEL: Final = "Acelerador para transcripción y OCR"
DEVICE_CHOICES: Final = {
    "auto": "Automático (usa GPU o NPU sólo si ya pasaron la prueba)",
    "gpu": "GPU Intel Arc",
    "npu": "NPU Intel AI Boost",
    "cpu": "Sólo CPU",
}
DEVICE_HINT_SHORT: Final = "Si falla, continúa con el siguiente y termina en CPU. «Probar compatibilidad»: Diagnóstico."
DEVICE_HINT: Final = (
    "Si el acelerador elegido falla, la aplicación continúa con el siguiente disponible y termina en CPU. "
    "Ejecuta «Probar compatibilidad» en Diagnóstico para que Automático lo aproveche."
)
COPY_VIDEO: Final = "Copiar el video dentro del proyecto (ocupa más espacio)"
ANALYZE: Final = "Analizar video"
RECENT_TITLE: Final = "Proyectos recientes"
RECENT_EMPTY: Final = "Aún no hay proyectos."
OPEN: Final = "Abrir"
VALIDATION_OK: Final = "Listo para analizar."
VIDEO_FILTER: Final = "Videos (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv)"
SUBTITLE_FILTER: Final = "Transcripciones (*.vtt *.srt)"

PROJECTS_TITLE: Final = "Proyectos"
SEARCH_PLACEHOLDER: Final = "Buscar por nombre o archivo (Ctrl+F)"
FILTER_ALL: Final = "Todos los estados"
COL_NAME, COL_FILE, COL_STATUS, COL_UPDATED, COL_PROFILE = (
    "Nombre",
    "Archivo",
    "Estado",
    "Última actualización",
    "Perfil",
)
CONTINUE: Final = "Continuar análisis"
OPEN_FOLDER: Final = "Abrir carpeta"
DELETE: Final = "Eliminar proyecto"
REFRESH: Final = "Actualizar lista"
DELETE_CONFIRM: Final = (
    "¿Eliminar el proyecto «{name}»?\n\nSe borrarán sus capturas, transcripción y reportes. "
    "El video original no se modifica."
)
STATUS_LABELS: Final = {
    "completado": "✔ Completado",
    "pendiente": "○ Pendiente",
    "en_proceso": "▶ En proceso",
    "interrumpido": "⏸ Interrumpido",
    "con_error": "✖ Con error",
}
SOURCE_MISSING: Final = "El video original ya no está en su ubicación. Puedes revisar y exportar, pero no continuar."

PROCESSING_TITLE: Final = "Analizando"
OVERALL: Final = "Avance general"
STAGE_LABELS: Final = {
    "preparar": "Preparar video",
    "pantallas": "Detectar pantallas",
    "audio": "Transcripción",
    "ocr": "Texto visible (OCR)",
    "alinear": "Alinear visto y dicho",
    "reporte": "Generar reportes",
}
STAGE_STATUS: Final = {
    "pending": "En espera",
    "running": "En curso",
    "completed": "Terminada",
    "completed_with_warnings": "Terminada con advertencias",
    "skipped": "Omitida",
    "cancelled": "Cancelada",
    "failed": "Falló",
    "interrupted": "Interrumpida",
    "reutilizada": "Reutilizada (ya estaba lista)",
}
CANCEL: Final = "Cancelar análisis"
CANCELLING: Final = "Cancelando… guardando avance"
CANCEL_CONFIRM: Final = "¿Cancelar el análisis? El avance se guarda y podrás continuar después."
VIEW_RESULTS: Final = "Ver resultados"
BACK_HOME: Final = "Volver al inicio"
WARNINGS_TITLE: Final = "Advertencias"
LOG_TITLE: Final = "Actividad"
DEVICE: Final = "Dispositivo: {device}"
ETA: Final = "≈ {minutes} min restantes (aproximado)"
JOB_DONE: Final = {
    "completed": "Análisis terminado.",
    "completed_with_warnings": "Análisis terminado con advertencias. Revisa la lista.",
    "cancelled": "Análisis cancelado. El avance quedó guardado.",
    "failed": "El análisis se detuvo por un error. El avance quedó guardado.",
}

PROJECT_CAPTURES: Final = "Capturas ({count})"
PROJECT_NO_CAPTURES: Final = "Este proyecto aún no tiene capturas."
EXPORT_TITLE: Final = "Exportar reportes"
EXPORT_FORMATS: Final = {
    "word": "Word (.docx)",
    "excel": "Excel (.xlsx)",
    "json": "JSON",
    "txt": "Texto (.txt)",
    "srt": "Subtítulos (.srt)",
}
EXPORT_SENSITIVE: Final = "Excluir datos sensibles (nombres de hablantes y rutas locales)"
EXPORT_DESTINATION: Final = "Carpeta de destino: {path}"
CHANGE_FOLDER: Final = "Cambiar carpeta…"
EXPORT: Final = "Exportar (Ctrl+E)"
EXPORTING: Final = "Generando reportes…"
EXPORT_DONE: Final = "Se generaron {count} archivos:"
OPEN_REPORTS: Final = "Abrir carpeta de reportes"
EXPORT_NONE: Final = "Selecciona al menos un formato."

DIAG_TITLE: Final = "Diagnóstico del equipo"
DIAG_INTRO: Final = (
    "Detecta hardware y componentes locales. «Disponible» en GPU o NPU sólo aparece después de una "
    "prueba real con el modelo; que Windows enumere el dispositivo no significa que sea compatible."
)
DIAG_DETECT: Final = "Detectar hardware"
DIAG_TEST: Final = "Probar compatibilidad"
DIAG_TEST_HINT: Final = "Ejecuta inferencias mínimas con los modelos instalados. Puede tardar unos minutos."
DIAG_EXPORT: Final = "Exportar diagnóstico…"
DIAG_COMPONENT, DIAG_STATUS, DIAG_DETAIL = "Componente", "Estado", "Detalle"
DIAG_STATUS_LABELS: Final = {
    "disponible": "✔ Disponible",
    "no_disponible": "– No disponible",
    "requiere_instalacion": "⬇ Requiere instalación",
    "detectado_no_compatible": "⚠ Detectado pero no compatible",
    "no_verificado": "? No verificado",
}
DIAG_MATRIX: Final = ("Backend", "Modelo", "CPU", "GPU", "NPU", "Estado", "Motivo")
DIAG_RUNNING: Final = "Trabajando… la interfaz sigue disponible."
DIAG_EXPORTED: Final = "Diagnóstico guardado en «{name}». No incluye transcripciones, OCR ni capturas."

BUSY: Final = "Ya hay un trabajo en curso. Espera a que termine o cancélalo."
CLOSE_RUNNING: Final = (
    "Hay un análisis en curso. Si cierras la aplicación se detendrá y el avance quedará guardado "
    "para continuar después.\n\n¿Cerrar de todos modos?"
)
DETAILS_SHOW: Final = "Ver detalles técnicos"
DETAILS_HIDE: Final = "Ocultar detalles técnicos"
SAVED_YES: Final = "El avance quedó guardado."
