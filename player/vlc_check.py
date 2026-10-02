"""Diagnostico de la instalacion de VLC al arrancar. Modulo puro (sin Qt ni
VLC): run.py lo usa para explicar POR QUE no se pudo cargar libVLC, en vez
de un traceback de ctypes.

El ejecutable no incluye libVLC a proposito (ver README): hace falta VLC
media player instalado, de la misma arquitectura (64 bits) que el
programa, y de la rama 3.0."""

import os
import re
import struct
import sys

VLC_DOWNLOAD_URL = "https://www.videolan.org/vlc/"
MIN_VLC_VERSION = (3, 0, 0)


def python_bits() -> int:
    return struct.calcsize("P") * 8


def candidate_vlc_dirs(environ=None) -> dict:
    """{"64": carpeta, "32": carpeta} de las instalaciones tipicas de VLC en
    Windows (las que existan o no; quien llama comprueba)."""
    environ = os.environ if environ is None else environ
    dirs = {}
    pf = environ.get("ProgramW6432") or environ.get("ProgramFiles")
    pf86 = environ.get("ProgramFiles(x86)")
    if pf:
        dirs["64"] = os.path.join(pf, "VideoLAN", "VLC")
    if pf86 and pf86 != pf:
        dirs["32"] = os.path.join(pf86, "VideoLAN", "VLC")
    return dirs


def find_installed_vlc(environ=None, exists=os.path.isfile) -> dict:
    """{"64": True/False, "32": True/False} segun donde haya un libvlc.dll."""
    return {bits: exists(os.path.join(folder, "libvlc.dll"))
            for bits, folder in candidate_vlc_dirs(environ).items()}


def missing_vlc_message(found=None, bits=None, platform=None) -> str:
    """Texto para el usuario cuando python-vlc no pudo cargar libvlc."""
    platform = platform or sys.platform
    bits = bits or python_bits()
    found = found if found is not None else (find_installed_vlc() if platform.startswith("win") else {})
    if platform.startswith("win") and found.get("32") and not found.get("64") and bits == 64:
        return (
            "Tienes instalado VLC de 32 bits, pero este programa es de 64 bits y necesita "
            "VLC de 64 bits.\n\n"
            f"Desinstala VLC e instala la versión de 64 bits desde {VLC_DOWNLOAD_URL}\n"
            "(en la página de descarga, elige \"Windows 64bit\")."
        )
    if platform.startswith("win") and found.get("64"):
        return (
            "VLC media player está instalado, pero su librería (libvlc.dll) no se pudo cargar.\n\n"
            f"Reinstala VLC 3.0 de 64 bits desde {VLC_DOWNLOAD_URL} y vuelve a abrir esta aplicación."
        )
    return (
        "No se encontró la librería de VLC (libvlc).\n\n"
        f"Instala VLC media player 3.0 desde {VLC_DOWNLOAD_URL}\n"
        f"(usa la versión de {bits} bits, como este programa) y vuelve a abrir esta aplicación."
    )


def parse_vlc_version(text) -> tuple:
    """"3.0.23 Vetinari" -> (3, 0, 23); () si no se reconoce."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    match = re.match(r"\s*(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not match:
        return ()
    return tuple(int(g or 0) for g in match.groups())


def version_warning(text):
    """Aviso si la version de libVLC es mas vieja que la soportada, o None."""
    version = parse_vlc_version(text)
    if version and version < MIN_VLC_VERSION:
        shown = ".".join(str(v) for v in version)
        return (f"Tu VLC ({shown}) es anterior a la 3.0: algunas funciones pueden no andar. "
                f"Actualízalo desde {VLC_DOWNLOAD_URL}")
    return None


def configure_bundled_vlc(base_dir, environ=None, exists=os.path.isfile) -> bool:
    """Si el paquete trae su propio libVLC (<base>/vlc/libvlc.dll, ver
    ReproductorMultimediaPro.spec con BUNDLE_VLC=1), apunta python-vlc a el
    con PYTHON_VLC_LIB_PATH / PYTHON_VLC_MODULE_PATH. Si no, no toca nada y
    se usa el VLC instalado en el sistema.

    Se comprueba que el archivo exista ANTES de fijar la variable: si
    PYTHON_VLC_LIB_PATH apunta a algo que no carga, python-vlc hace
    sys.exit(1) sin ningun mensaje. Una variable ya fijada por el usuario se
    respeta. Lo llama el runtime hook de PyInstaller (packaging/)."""
    environ = os.environ if environ is None else environ
    if not base_dir or "PYTHON_VLC_LIB_PATH" in environ:
        return False
    vlc_dir = os.path.join(base_dir, "vlc")
    lib = os.path.join(vlc_dir, "libvlc.dll")
    if not exists(lib):
        return False
    environ["PYTHON_VLC_LIB_PATH"] = lib
    environ["PYTHON_VLC_MODULE_PATH"] = os.path.join(vlc_dir, "plugins")
    return True
