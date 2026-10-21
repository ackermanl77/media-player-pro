"""Manifiesto de aplicacion del .exe (8.7), escrito por
ReproductorMultimediaPro.spec en la carpeta de trabajo de PyInstaller.

Es el manifiesto por defecto de PyInstaller (asInvoker, la lista supportedOS,
longPathAware, Common-Controls v6) mas:
- activeCodePage UTF-8: la pagina de codigos ANSI del proceso pasa a UTF-8,
  asi que una biblioteca nativa que use las API "A" de Win32 abre rutas como
  C:\\Users\\Ana\\Música\\canción.mp3 (en un Windows en espanol la pagina
  ANSI es cp1252 y cualquier caracter fuera de ella fallaba). Python, Qt y
  libVLC ya usan las API "W"; el unico subprocess que lee texto
  (player/web_video.py) indica encoding="utf-8".
- dpiAwareness PerMonitorV2 (con dpiAware true/pm de respaldo): Qt ya lo pide
  en tiempo de ejecucion, pero declararlo evita que Windows escale la ventana
  como mapa de bits durante el arranque y en dialogos nativos.

Solo biblioteca estandar (se prueba en tests/test_version.py)."""

import os

MANIFEST_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"></requestedExecutionLevel>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"></supportedOS>
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"></supportedOS>
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"></supportedOS>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"></supportedOS>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"></supportedOS>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"></assemblyIdentity>
    </dependentAssembly>
  </dependency>
</assembly>
"""


def write_manifest(out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "ReproductorMultimediaPro.manifest")
    with open(path, "w", encoding="utf-8") as f:
        f.write(MANIFEST_XML)
    return path
