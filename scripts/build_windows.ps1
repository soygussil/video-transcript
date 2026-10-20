# Build reproducible del ejecutable portable (sin consola). Requiere el entorno de scripts\instalar_windows.ps1.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = ".\.venv\Scripts\python.exe"
& $py -m ruff check src tests
& $py -m mypy
& $py -m pytest -q
& $py -m PyInstaller --noconfirm --clean packaging\pyinstaller\analizador_video.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló" }
$version = & $py -c "import analizador_video; print(analizador_video.__version__)"
Compress-Archive -Path dist\AnalizadorVideo -DestinationPath "dist\AnalizadorVideo-$version-portable.zip" -Force
Write-Host "Listo: dist\AnalizadorVideo-$version-portable.zip"
