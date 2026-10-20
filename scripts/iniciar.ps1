# Arranque con un clic: instala lo que falte (sólo la primera vez) y abre la aplicación.
# Se reinstala únicamente si cambia pyproject.toml; los modelos se descargan una sola vez.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = ".\.venv\Scripts\python.exe"
$marcaDeps = ".\.venv\.deps_ok"
$marcaModelos = ".\.venv\.modelos_ok"

if (-not (Test-Path $py)) {
    Write-Host "Primera vez: creando el entorno (puede tardar varios minutos)..."
    $creado = $false
    foreach ($version in "3.13", "3.12", "3.11") {
        py "-$version" -m venv .venv 2>$null
        if ($LASTEXITCODE -eq 0) { $creado = $true; break }
    }
    if (-not $creado) { throw "Se necesita Python 3.11, 3.12 o 3.13 (python.org). No se admite 3.14 todavía." }
}

$huella = (Get-FileHash pyproject.toml -Algorithm SHA256).Hash
$previa = if (Test-Path $marcaDeps) { (Get-Content $marcaDeps -Raw).Trim() } else { "" }
if ($huella -ne $previa) {
    Write-Host "Instalando dependencias (sólo esta vez o cuando cambie el proyecto)..."
    & $py -m pip install --upgrade pip
    & $py -m pip install -e ".[whisper,openvino]"
    if ($LASTEXITCODE -ne 0) { throw "Falló la instalación de dependencias. Revisa tu conexión a Internet." }
    Set-Content $marcaDeps $huella
}

if (-not (Test-Path $marcaModelos)) {
    Write-Host "Descargando modelos de OCR y Whisper (una sola vez)..."
    & .\.venv\Scripts\analizador-video.exe modelos descargar --ocr-openvino --whisper-openvino small --si
    if ($LASTEXITCODE -eq 0) { Set-Content $marcaModelos "ok" }
    else { Write-Host "No se pudieron descargar los modelos; se reintentará la próxima vez." }
}

Start-Process .\.venv\Scripts\analizador-video-gui.exe
