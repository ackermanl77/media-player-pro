# Empaquetado (PyInstaller + Inno Setup)

## Goal

Generar la app de Windows (carpeta "onedir") que no necesite tener Python
instalado, y un instalador por usuario (sin permisos de administrador) que
la registre en "Abrir con" de Windows.

Antes era un `.exe` de un solo archivo ("onefile"): en cada arranque el
bootloader extraía ~124 MB a `%TEMP%\_MEI...` y los borraba al salir (y
quedaban restos tras un cierre forzado). Onedir arranca directo.

> **Estado (2026-10-03):** build onedir local verificado (2026-10-01,
> Python 3.14, versiones de `constraints.txt`): 77,9 MB / 201 archivos,
> arranca y carga el VLC del sistema; el recorte de Qt ahorra ~40 MB
> (118,0 MB sin él). La variante `BUNDLE_VLC=1` (+ `plugins.dat`) pesa
> 182,5 MB y arranca usando solo el libVLC incluido. El instalador se
> compiló y se probó la instalación y desinstalación silenciosas (la
> desinstalación ya no deja la clave vacía `HKCU\Software\ReproductorMultimediaPro`).
> `build-exe.yml` construyó carpeta e instalador en GitHub (2026-10-03).
> **Falta:** la verificación manual interactiva de abajo (reproducir desde
> el instalado, "Abrir con").

## Versión

La única fuente es `player/__init__.py` (`__version__`). De ahí la toman:

- `pyproject.toml` (`dynamic = ["version"]`, `[tool.setuptools.dynamic]`);
- el recurso de versión del `.exe` (Propiedades → Detalles: nombre,
  versión de archivo/producto, compañía, nombre original), que el spec
  arma con `packaging/version_resource.py::build_version_info()`;
- el instalador (`iscc /DAppVersion=...`, los workflows lo leen de
  `player.__version__`) y el cliente de OpenSubtitles (`USER_AGENT`).

Para publicar una versión: subir `__version__`, commit, y luego
`git tag v<version>` + `git push origin v<version>`.

> **Estado (2026-10-03):** el recurso de versión se verificó con un build
> local (PyInstaller 6.22, Python 3.14): `ProductVersion`/`FileVersion`
> 0.1.0, "Reproductor Multimedia Pro", idioma español. El workflow de
> release no se ejecutó todavía en GitHub (el Release `v0.1.0` existente,
> del 2026-09-19, es anterior a él y trae el antiguo `.exe` onefile).

## Release (etiqueta `v*`)

`.github/workflows/release.yml`, al subir una etiqueta `v<version>`:

1. corre el workflow CI completo (Ubuntu + Windows 3.12/3.14) como
   `workflow_call`; si falla, no se construye nada;
2. comprueba que la etiqueta sea `v` + `player.__version__`;
3. construye la carpeta onedir con el spec (mismas dependencias fijas de
   `constraints.txt`) y comprueba la versión del `.exe` construido;
4. la comprime en `ReproductorMultimediaPro-<version>-windows-x64.zip`,
   arma el instalador con Inno Setup y escribe `SHA256SUMS.txt`;
5. crea el GitHub Release de esa etiqueta con los tres archivos (notas
   generadas por GitHub).

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
generar `plugins.dat` **después** del build, sobre la carpeta ya copiada:
`"C:\Program Files\VideoLAN\VLC\vlc-cache-gen.exe" dist\ReproductorMultimediaPro\_internal\vlc\plugins`
(un `plugins.dat` generado antes no sirve: PyInstaller no conserva la fecha
de los DLL y libVLC descarta las entradas que no coinciden; Inno Setup sí
las conserva al instalar). Distribuir libVLC obliga a cumplir su LGPL: el
spec con `BUNDLE_VLC=1` copia `licenses/` (`THIRD_PARTY_NOTICES.txt` con el
enlace al código fuente de VLC 3.0.23, `VLC-COPYING.txt` y
`VLC-COPYING.LIB.txt`) a `_internal\licenses\`. Si se empaqueta otra versión
de VLC, actualizar el enlace del tarball en `THIRD_PARTY_NOTICES.txt`.

## Instalador

`installer/ReproductorMultimediaPro.iss` instala en
`%LOCALAPPDATA%\Programs\ReproductorMultimediaPro` (sin admin), con acceso
en el menú Inicio, desinstalador, y registra la app como "capacidad" de
Windows para audio/video/.m3u (aparece en "Abrir con" y en Aplicaciones
predeterminadas, sin adueñarse de ninguna extensión), con un verbo extra
"Agregar a la lista de Reproductor Multimedia Pro" (`--enqueue`). Copia
también `licenses/` a `{app}\licenses`, y al desinstalar borra sus claves
del registro (incluida la clave padre de `Capabilities` si quedó vacía).

## Firma de código

`packaging/sign_and_package.py` reemplaza el `iscc` del build manual cuando
se quiere firmar:

```bat
set CODESIGN_THUMBPRINT=<huella SHA-1 del certificado>
pyinstaller --noconfirm ReproductorMultimediaPro.spec
python packaging/sign_and_package.py          # --no-installer: solo el .exe
```

Firma `dist/ReproductorMultimediaPro/ReproductorMultimediaPro.exe` con
signtool (Windows SDK: `PATH` o el `Windows Kits\10\bin` más nuevo), SHA-256
y sello RFC 3161 de `CODESIGN_TIMESTAMP_URL` (por defecto DigiCert), y
compila el instalador con `/DSign` y la herramienta "codesign": el
`#ifdef Sign` del `.iss` activa `SignTool=codesign` y `SignedUninstaller=yes`,
así Inno firma el instalador y el desinstalador. La versión sale de
`player/__init__.py`. Probado el 2026-10-07 con un certificado autofirmado
(`tests/test_sign_script.py` cubre los comandos).

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
