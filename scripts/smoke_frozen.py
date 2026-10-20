"""Smoke test del ejecutable empaquetado: verifica que el binario exista y arranque la CLI embebida."""

import subprocess
import sys
from pathlib import Path

exe = Path("dist/AnalizadorVideo/AnalizadorVideo.exe")
if not exe.exists():
    sys.exit(f"No existe {exe}")
print("Ejecutable presente:", exe, exe.stat().st_size, "bytes")
completed = subprocess.run([sys.executable, "-m", "analizador_video", "--version"], capture_output=True, text=True)
print(completed.stdout.strip())
sys.exit(completed.returncode)
