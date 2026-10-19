@echo off
rem Compatibilidad con el instalador original. Usa el script de PowerShell.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar_windows.ps1" %*
