# Elimina artefactos de build y cachés (no toca proyectos ni modelos del usuario).
Set-Location (Split-Path $PSScriptRoot -Parent)
foreach ($p in @("build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov", "coverage.xml", ".coverage")) {
  if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
