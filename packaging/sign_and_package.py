"""Firma la app ya construida y compila su instalador firmado.

Uso (después de ``pyinstaller --noconfirm ReproductorMultimediaPro.spec``)::

    set CODESIGN_THUMBPRINT=<huella SHA-1 del certificado>
    python packaging/sign_and_package.py [--no-installer]

Firma ``dist/ReproductorMultimediaPro/ReproductorMultimediaPro.exe`` con
signtool (Windows SDK) y el certificado del almacén de Windows cuya huella
está en ``CODESIGN_THUMBPRINT``, con sello de tiempo RFC 3161 de
``CODESIGN_TIMESTAMP_URL`` (por defecto el de DigiCert). Luego compila
``installer/ReproductorMultimediaPro.iss`` con Inno Setup 6 pasándole la
herramienta "codesign", así Inno firma el instalador y el desinstalador que
escribe. Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "dist", "ReproductorMultimediaPro", "ReproductorMultimediaPro.exe")
ISS = os.path.join(ROOT, "installer", "ReproductorMultimediaPro.iss")
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


def find_signtool() -> str | None:
    """signtool.exe: en el PATH, o el más nuevo del Windows 10/11 SDK."""
    found = shutil.which("signtool")
    if found:
        return found
    kits = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Windows Kits", "10", "bin")
    if not os.path.isdir(kits):
        return None
    for version in sorted(os.listdir(kits), reverse=True):
        candidate = os.path.join(kits, version, "x64", "signtool.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def find_iscc() -> str | None:
    """ISCC.exe de Inno Setup 6: en el PATH o en sus carpetas de instalación."""
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        for folder in ("Inno Setup 6", os.path.join("Programs", "Inno Setup 6")):
            candidate = os.path.join(base, folder, "ISCC.exe")
            if os.path.isfile(candidate):
                return candidate
    return None


def app_version() -> str:
    """``__version__`` de player/__init__.py, sin importar el paquete (que trae Qt/VLC)."""
    with open(os.path.join(ROOT, "player", "__init__.py"), encoding="utf-8") as handle:
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', handle.read(), re.M)
    if not match:
        raise RuntimeError("player/__init__.py no define __version__")
    return match.group(1)


def sign_command(signtool: str, thumbprint: str, path: str, timestamp_url: str) -> list[str]:
    return [signtool, "sign", "/sha1", thumbprint, "/fd", "SHA256", "/tr", timestamp_url, "/td", "SHA256", path]


def inno_sign_args(signtool: str, thumbprint: str, timestamp_url: str) -> list[str]:
    """Argumentos de ISCC: /DSign activa SignTool=codesign en el .iss ($q = comillas, $f = archivo)."""
    return ["/DSign", f"/Scodesign=$q{signtool}$q sign /sha1 {thumbprint} /fd SHA256 /tr {timestamp_url} /td SHA256 $f"]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    thumbprint = os.environ.get("CODESIGN_THUMBPRINT", "").replace(" ", "")
    if not thumbprint:
        print("Falta CODESIGN_THUMBPRINT: la huella SHA-1 de un certificado de firma de código.")
        return 1
    timestamp = os.environ.get("CODESIGN_TIMESTAMP_URL") or DEFAULT_TIMESTAMP_URL
    signtool = find_signtool()
    if signtool is None:
        print("No se encontró signtool.exe (instala las herramientas de firma del Windows SDK).")
        return 1
    if not os.path.isfile(EXE):
        print(f"No existe {EXE}: corre antes pyinstaller --noconfirm ReproductorMultimediaPro.spec")
        return 1
    print("Firmando:", EXE)
    result = subprocess.run(sign_command(signtool, thumbprint, EXE, timestamp), cwd=ROOT)
    if result.returncode != 0:
        return result.returncode
    if "--no-installer" in args:
        return 0
    iscc = find_iscc()
    if iscc is None:
        print("No se encontró Inno Setup 6 (ISCC.exe): https://jrsoftware.org/isinfo.php")
        return 1
    cmd = [iscc, f"/DAppVersion={app_version()}", *inno_sign_args(signtool, thumbprint, timestamp), ISS]
    print("Compilando el instalador firmado...")
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
