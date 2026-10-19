# Firma y antivirus

- Los ejecutables de PyInstaller sin firmar pueden generar alertas de SmartScreen o del antivirus corporativo.
- Firma `dist\AnalizadorVideo\AnalizadorVideo.exe` con el certificado aprobado por tu organización:
  `signtool sign /fd SHA256 /tr <TSA corporativo> /td SHA256 /f <certificado> AnalizadorVideo.exe`
- No se incluye certificado ni proceso de firma en este repositorio (no hay herramienta corporativa identificada).
- MSI: si existe una herramienta aprobada (WiX, MSIX, Intune), empaqueta la carpeta `dist\AnalizadorVideo` completa.
  Este repositorio entrega el artefacto portable (ZIP), sin instalador.
- FFmpeg no se redistribuye. Revisa la licencia y la política interna antes de incluirlo; la app lo detecta en PATH.
