# -*- mode: python ; coding: utf-8 -*-
#
# Genera la app de Windows con PyInstaller en modo "onedir":
# dist/ReproductorMultimediaPro/ReproductorMultimediaPro.exe + _internal/.
# Antes era un unico .exe ("onefile") que en CADA arranque extraia ~124 MB
# a %TEMP%\_MEI... (y los borraba al salir); onedir arranca directo y es lo
# que empaqueta el instalador (installer/ReproductorMultimediaPro.iss).
#
# libVLC: por defecto NO se incluye; la app usa el VLC instalado en el
# equipo (ver README.md). Con la variable de entorno BUNDLE_VLC=1 se copia
# libvlc.dll + libvlccore.dll + un plugins/ recortado desde VLC_DIR (por
# defecto C:\Program Files\VideoLAN\VLC) a <app>\_internal\vlc\, y el runtime
# hook packaging/rthook_bundled_vlc.py hace que python-vlc lo use (con
# respaldo al VLC del sistema si no esta). Antes de distribuirlo asi, ver las
# obligaciones de la LGPL en README.md.

import os

from PyInstaller.utils.hooks import collect_submodules
from PySide6.QtCore import QLibraryInfo

hiddenimports = ["player.backend", "player.main_window", "player.formats"]
hiddenimports += collect_submodules("player")

# player/main_window.py busca los iconos en <MEIPASS>/assets/... cuando esta
# empaquetado (ver _icon_path en ese archivo) -- deben quedar en esa carpeta
# dentro del bundle, no junto al resto del paquete "player".
datas = [
    ("player/assets/icon.png", "assets"),
    ("player/assets/icon.ico", "assets"),
]

# Botones estandar de Qt en espanol (run.install_spanish_translator).
_translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
for _qm in ("qtbase_es.qm",):
    if os.path.exists(os.path.join(_translations, _qm)):
        datas.append((os.path.join(_translations, _qm), "PySide6/translations"))

# -- libVLC opcional --------------------------------------------------------
# Categorias de plugins de VLC que un reproductor embebido no necesita.
VLC_PLUGIN_DIRS_EXCLUDED = {
    "gui", "lua", "services_discovery", "stream_out", "access_output", "control", "keystore",
    "visualization_qt",
}
binaries = []
if os.environ.get("BUNDLE_VLC") == "1":
    vlc_dir = os.environ.get("VLC_DIR", r"C:\Program Files\VideoLAN\VLC")
    for dll in ("libvlc.dll", "libvlccore.dll"):
        binaries.append((os.path.join(vlc_dir, dll), "vlc"))
    plugins_root = os.path.join(vlc_dir, "plugins")
    for category in sorted(os.listdir(plugins_root)):
        src = os.path.join(plugins_root, category)
        if category in VLC_PLUGIN_DIRS_EXCLUDED or not os.path.isdir(src):
            continue
        for name in os.listdir(src):
            if name.endswith(".dll"):
                binaries.append((os.path.join(src, name), os.path.join("vlc", "plugins", category)))
    # plugins.dat (cache de plugins): sin el, libVLC escanea cada DLL al
    # arrancar. Lo genera scripts/build (vlc-cache-gen) tras el build; si ya
    # existe uno correspondiente a este recorte, se incluye.
    cache = os.environ.get("VLC_PLUGINS_CACHE")
    if cache and os.path.exists(cache):
        datas.append((cache, os.path.join("vlc", "plugins")))

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["packaging/rthook_bundled_vlc.py"],
    # La app usa QtCore/QtGui/QtWidgets/QtSvg (iconos) y QtNetwork (una sola
    # ventana, player/single_instance.py). Nada de Qml/Quick/Pdf/OpenGL.
    excludes=[
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtWebEngineCore",
        "PySide6.QtMultimedia", "tkinter", "unittest", "pytest", "numpy",
    ],
    noarchive=False,
)

# Ademas de los modulos, PyInstaller arrastra DLLs de Qt grandes que nunca se
# cargan (~40 MB): opengl32sw.dll (OpenGL por software), Quick/Qml/Pdf, y
# formatos de imagen que no se usan.
_DROP_PREFIXES = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard")
_DROP_IMAGEFORMATS = ("qgif", "qicns", "qtga", "qtiff", "qwbmp", "qwebp", "qpdf")


def _keep_binary(entry):
    name = os.path.basename(entry[0]).lower()
    if name.startswith(_DROP_PREFIXES):
        return False
    if "imageformats" in entry[0].replace("\\", "/").lower() and name.startswith(_DROP_IMAGEFORMATS):
        return False
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ReproductorMultimediaPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="player/assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ReproductorMultimediaPro",
)
