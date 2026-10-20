# Crea el entorno de desarrollo en .venv (no requiere permisos de administrador).
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\instalar_windows.ps1 [-SinOpenVino] [-ConEasyOcr]
#   Por defecto instala OpenVINO (GPU Arc / NPU Intel AI Boost) y el OCR liviano RapidOCR, sin PyTorch.
#   -ConEasyOcr agrega EasyOCR (sólo CPU, descarga PyTorch: varios GB).
param([switch]$SinOpenVino, [switch]$ConEasyOcr)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$created = $false
foreach ($version in "3.13", "3.12", "3.11") {
    py "-$version" -m venv .venv 2>$null
    if ($LASTEXITCODE -eq 0) { $created = $true; break }
}
if (-not $created) { throw "Se necesita Python 3.11, 3.12 o 3.13 (el proyecto no admite 3.14 todavía)." }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
$extras = "whisper,dev"
if (-not $SinOpenVino) { $extras += ",openvino" }
if ($ConEasyOcr) { $extras += ",ocr" }
& .\.venv\Scripts\python.exe -m pip install -e ".[$extras]"
Write-Host "Instalación completada. Abre la app con:  .\.venv\Scripts\analizador-video-gui.exe"
Write-Host "Luego descarga los modelos (una vez, con Internet):"
Write-Host "  .\.venv\Scripts\analizador-video.exe modelos descargar --ocr-openvino --whisper-openvino small"
Write-Host "Y en la app: Diagnóstico -> Probar compatibilidad (para que Automático use GPU/NPU)."
