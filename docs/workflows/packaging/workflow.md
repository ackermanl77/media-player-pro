# Empaquetado (PyInstaller + Inno Setup)

## Goal

Generar la app de Windows (carpeta "onedir") que no necesite tener Python
instalado, y un instalador por usuario (sin permisos de administrador) que
la registre en "Abrir con" de Windows.

Antes era un `.exe` de un solo archivo ("onefile"): en cada arranque el
bootloader extraía ~124 MB a `%TEMP%\_MEI...` y los borraba al salir (y
quedaban restos tras un cierre forzado). Onedir arranca directo.

> **Estado:** el cambio a onedir, el recorte de módulos Qt, el instalador y
> la opción `BUNDLE_VLC` están escritos pero **todavía no se construyeron ni
> probaron** (solo se validó la sintaxis). Hacer un build y la verificación
> de abajo antes de distribuir.

## Build automático (CI)

`.github/workflows/build-exe.yml` construye la carpeta y el instalador en
`windows-latest` después de cada push a `main`/`master`, solo si el
workflow "CI" pasó para ese commit (o manualmente: Actions → "Build Windows
EXE" → "Run workflow"). Instala las dependencias con `constraints.txt`
(versiones fijas). El *artifact* `ReproductorMultimediaPro-windows` trae el
instalador (`dist/installer/*.exe`) y la carpeta de la app; dura 30 días.

## Build manual

```bash
pip install -r requirements-build.txt -c constraints.txt
pyinstaller --noconfirm ReproductorMultimediaPro.spec
iscc /DAppVersion=0.1.0 installer\ReproductorMultimediaPro.iss
```

Resultado:

```text
dist/ReproductorMultimediaPro/ReproductorMultimediaPro.exe   (+ _internal/)
dist/installer/ReproductorMultimediaPro-0.1.0-setup.exe
```

`ReproductorMultimediaPro.spec` construye desde `run.py`, con
`console=False` y el ícono propio (`player/assets/icon.ico`). Declara
`datas` para `player/assets/icon.png`/`icon.ico` (que
`player/main_window.py::_icon_path()` busca en `sys._MEIPASS/assets/`) y
`qtbase_es.qm` (botones estándar de Qt en español). Excluye los módulos de
Qt que la app no usa (Qml, Quick, Pdf, OpenGL...) y filtra sus DLLs grandes
(`opengl32sw.dll`, `Qt6Quick*`, `Qt6Qml*`, `Qt6Pdf*`) y los formatos de
imagen innecesarios. **Conserva QtNetwork** (una sola ventana) y **QtSvg**
(iconos).

### libVLC

Por defecto **no se incluye**: la máquina destino necesita VLC 3.0 de 64
bits instalado (si falta o es de 32 bits, `run.py` lo explica con
`player/vlc_check.py`). Con `BUNDLE_VLC=1` (y `VLC_DIR` si VLC no está en
`C:\Program Files\VideoLAN\VLC`) el spec copia `libvlc.dll`,
`libvlccore.dll` y `plugins/` sin las categorías que un reproductor
embebido no usa (gui, lua, stream_out, ...) a `_internal\vlc\`. El runtime
hook `packaging/rthook_bundled_vlc.py` apunta python-vlc ahí
(`PYTHON_VLC_LIB_PATH`/`PYTHON_VLC_MODULE_PATH`) solo si el archivo existe —
si no, se usa el VLC del sistema. Para no escanear cada plugin al arrancar,
generar `plugins.dat` con `vlc-cache-gen.exe` sobre ese `plugins/` y pasarlo
con `VLC_PLUGINS_CACHE`. Distribuir libVLC obliga a cumplir su LGPL
(incluir su licencia y un enlace al código fuente de VLC).

## Instalador

`installer/ReproductorMultimediaPro.iss` instala en
`%LOCALAPPDATA%\Programs\ReproductorMultimediaPro` (sin admin), con acceso
en el menú Inicio, desinstalador, y registra la app como "capacidad" de
Windows para audio/video/.m3u (aparece en "Abrir con" y en Aplicaciones
predeterminadas, sin adueñarse de ninguna extensión), con un verbo extra
"Agregar a la lista de Reproductor Multimedia Pro" (`--enqueue`).

## Verificar

No hay una suite automatizada contra el paquete en sí. Después de cada
build:

```bash
dist/ReproductorMultimediaPro/ReproductorMultimediaPro.exe ruta/a/un/audio.mp3 ruta/a/un/video.mp4
```

1. Abre sin errores, con su ícono, y los botones de diálogos en español.
2. Reproduce el primer archivo y al terminar avanza al segundo.
3. Con la ventana abierta, abrir otro archivo con el `.exe` lo agrega a esa
   ventana (no abre otra).
4. Instalar con el setup, abrir un `.mkv` con "Abrir con" y desinstalar.

## Distribución

`build/` y `dist/` están en `.gitignore`. Para distribuir, compartir el
instalador (o la carpeta completa), junto con la indicación de instalar VLC
media player 3.0 de 64 bits si no se construyó con `BUNDLE_VLC=1`.
