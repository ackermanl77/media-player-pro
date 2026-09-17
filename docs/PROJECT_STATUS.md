# Project Status

## Architecture

```text
run.py / run.pyw (entry points)
        |
        v
player.main_window.MainWindow (PySide6 QMainWindow)
        |  crea y controla
        v
player.backend.VLCPlayer (envoltorio delgado sobre python-vlc)
        |
        v
libVLC (ctypes, vía python-vlc) -- decodifica y reproduce audio/video
        |
        v
VLC media player (debe estar instalado aparte en la máquina; no se empaqueta)
```

`MainWindow` (`player/main_window.py`) construye toda la interfaz (barra de
controles, menús, dock de la playlist) y traduce cada acción del usuario en
llamadas a un único `VLCPlayer`. No conoce nada de libVLC directamente más
allá de `vlc.State` para leer el estado de reproducción.

`VLCPlayer` (`player/backend.py`) es la única clase que toca `python-vlc`.
Mantiene su propio `vlc.Instance`/`vlc.MediaPlayer`, y los **recrea** cuando
cambia si hace falta o no el visualizador de audio — `audio-visual` y
`effect-list` son opciones de instancia en libVLC, no de un `Media`
individual, así que no hay otra forma de activarlas/desactivarlas en
caliente. Al recrear la instancia, `_create_instance()` reaplica volumen,
mute, velocidad y ecualizador para que el cambio sea transparente para quien
llama.

`player/formats.py` no depende de VLC ni de Qt: son funciones puras
(listas de extensiones soportadas, `is_url`, `is_audio_file`,
`format_time`, el filtro de `QFileDialog`), lo que permite probarlas sin
tener VLC instalado.

## Primary Entry Points

| Propósito | Entry point |
|---|---|
| Abrir la aplicación (opcionalmente con archivos como argumentos) | `run.py` |
| Igual, sin ventana de consola en Windows | `run.pyw` (doble clic, o `pythonw run.py`) |
| Ventana principal y todo el cableado de la UI | `player/main_window.py::MainWindow` |
| Envoltorio sobre libVLC (transporte, volumen, pistas, ecualizador, visualizador) | `player/backend.py::VLCPlayer` |
| Formatos soportados y helpers puros (tiempo, rutas, filtros de diálogo) | `player/formats.py` |
| Receta de PyInstaller para el ejecutable de Windows | `ReproductorMultimediaPro.spec` |

## Release

```text
dist/ReproductorMultimediaPro.exe
```

Se genera con `pyinstaller ReproductorMultimediaPro.spec` (ver
[docs/workflows/packaging/workflow.md](workflows/packaging/workflow.md)).
No empaqueta VLC: la máquina que ejecute el `.exe` necesita tener VLC media
player instalado aparte, igual que al correr desde el código fuente.

## Verification

```bash
python -m pytest -q
```

`tests/test_formats.py` no depende de VLC ni de Qt. El resto de la suite
(`test_backend.py`, `test_visualizer.py`, `test_app_smoke.py`) importa
`vlc` de verdad y se **omite automáticamente** (no falla) si no hay VLC
instalado en la máquina — son pruebas de humo reales contra libVLC, no
mocks. Corre `pytest` tú mismo antes de confiar en un número de tests
pasados; no hay una cifra fija documentada aquí porque la suite sigue
creciendo.

## Known Issues

- **No hay persistencia de ajustes entre sesiones.** Volumen, tamaño de
  ventana, última carpeta abierta, etc. se resetean cada vez que se abre la
  app. No implementado todavía (candidato: `QSettings`).
- **El visualizador de audio solo se activa para archivos locales cuya
  extensión es de audio puro** (`player.formats.is_audio_file`). Un stream
  de audio por URL (p. ej. una radio por HTTP) no dispara el visualizador,
  porque no hay forma de saber por la URL si el contenido es audio o video
  antes de reproducirlo.
- **El `.exe` empaquetado no incluye VLC.** Si se distribuye a otra
  máquina, esa máquina necesita instalar VLC (arquitectura de 32/64 bits
  coincidente con la del build) para que `libvlc.dll` se encuentre en
  tiempo de ejecución.

## Recently Fixed

- **Espacio y las flechas de teclado a veces no respondían.** Los botones
  de transporte y los sliders de la barra de controles (`player/main_window.py`)
  tenían el foco de teclado por defecto de Qt; si el usuario hacía clic en,
  por ejemplo, "Detener" y luego pulsaba Espacio, Qt volvía a activar ese
  mismo botón en vez de disparar el atajo global de Reproducir/Pausa.
  **Arreglado**: todos los controles de la barra (`btn_prev`, `btn_play`,
  `btn_stop`, `btn_next`, `btn_mute`, los dos sliders, el combo de
  velocidad, `btn_shuffle`, `btn_repeat`, `btn_fullscreen`) reciben ahora
  `setFocusPolicy(Qt.FocusPolicy.NoFocus)`, así nunca compiten con los
  atajos de teclado a nivel de ventana.

- **Un archivo que VLC no podía decodificar dejaba la app "colgada" sin
  ningún aviso.** `update_ui()` solo comprobaba `vlc.State.Ended` para
  avanzar de pista; si el estado pasaba a `vlc.State.Error` (códec no
  soportado, archivo corrupto), no pasaba nada — ni mensaje, ni avance a
  la siguiente canción. **Arreglado**: se agregó una rama para
  `vlc.State.Error` que muestra el nombre del archivo fallido en la barra
  de estado durante 5 segundos y avanza automáticamente a la siguiente
  pista, igual que al terminar una pista normalmente.

- **Si VLC no estaba instalado, la app moría con un traceback de ctypes
  ininteligible.** `import vlc` falla con un `OSError`/`FileNotFoundError`
  crudo cuando `libvlc.dll` no se encuentra. **Arreglado**: `run.py` mueve
  el `import` de `MainWindow` dentro de `main()`, después de crear la
  `QApplication`, y atrapa el `OSError` para mostrar un `QMessageBox` claro
  pidiendo instalar VLC, en vez de un stack trace de ctypes.

- **`python run.py` siempre abría una ventana de consola detrás del
  reproductor en Windows.** **Arreglado**: se agregó `run.pyw` (mismo
  `main()`, solo reexportado) para que hacer doble clic, o ejecutarlo con
  `pythonw`, no abra consola.

- **Reproducir un archivo de solo audio dejaba `video_frame` en negro.**
  VLC trae un filtro de visualización ("visual") que genera un espectro y
  lo manda por la misma salida de video que un archivo real usaría.
  **Arreglado**: se agregó un toggle "Visualizador de audio (espectro)" en
  el menú Audio (activado por defecto). Como `audio-visual`/`effect-list`
  son opciones de *instancia* de libVLC (no de `Media`), activarlas o
  desactivarlas en caliente requirió que `VLCPlayer` pudiera recrear su
  `vlc.Instance` al cambiar entre reproducir audio y video, preservando
  volumen/mute/velocidad/ecualizador a través del cambio (ver
  "Architecture" arriba). Ver
  [docs/workflows/visualizer/workflow.md](workflows/visualizer/workflow.md).

- **Bug real y más serio, encontrado mientras se probaba el visualizador,
  sin relación con él: `libvlc_media_new_path()` falla en silencio en
  Windows si la ruta usa `/` en vez de `\`.** El reproductor se quedaba
  para siempre en `vlc.State.NothingSpecial` — nunca pasaba a
  `State.Playing` ni a `State.Error`, así que ni siquiera el manejo de
  errores de arriba lo detectaba. Reproducido de forma consistente
  comparando una ruta literal (`C:\...`, funcionaba) contra la misma ruta
  recibida por `sys.argv` (`C:/...`, se colgaba) — así llegan las rutas
  típicamente por línea de comandos, y potencialmente desde algunos
  diálogos de Qt. **Arreglado**: `VLCPlayer.load()` ahora normaliza toda
  ruta local con `os.path.normpath()` antes de pasarla a
  `media_new_path()`. Cubierto por
  `tests/test_backend.py::test_load_plays_a_path_that_uses_forward_slashes`.

- **El CI en GitHub Actions (Ubuntu) tardó varias iteraciones en pasar
  para el test del visualizador, con tres causas distintas superpuestas.**
  (1) El runner no tiene tarjeta de sonido real: VLC intentaba abrir el
  dispositivo ALSA "default", fallaba, y el decodificador de audio moría
  sin darle nunca la oportunidad de correr al filtro "visual" (que cuelga
  de esa misma cadena de audio) — nada que ver con nombres de módulo
  ("adummy"/"vdummy" sí existen y están bien en el VLC de los repos de
  Ubuntu, `vlc-plugin-visualization` es una dependencia *Recommends* que
  este runner no instala por defecto y hubo que pedir explícitamente).
  (2) Bajo `xvfb` con renderizado por software, inicializar el contexto
  GL/EGL para el video generado por el filtro tarda ~2 segundos por sí
  solo la primera vez; el WAV de prueba original (2s) terminaba y
  desmontaba el pipeline casi al mismo tiempo que el `vout` llegaba a
  existir. (3) Una vez resueltos (1) y (2) seguía fallando: el propio test
  sobreescribía `player.instance` a mano para forzar `--aout=adummy`, pero
  `VLCPlayer.load()` puede recrear esa instancia internamente (ver arriba)
  — como el override manual nunca actualizaba `player._visualizer_on`,
  `load()` veía un cambio de estado y recreaba la instancia desde
  `BASE_VLC_ARGS`, descartando el `adummy` sin que el test se enterara.
  **Arreglado**: instalar `vlc-plugin-visualization` y `xvfb` en el
  workflow, correr los tests con `xvfb-run`, alargar el audio de prueba a
  8s, y parchear `BASE_VLC_ARGS` (con `monkeypatch`) en vez de
  sobreescribir la instancia directamente. Ver
  [docs/workflows/testing-ci/workflow.md](workflows/testing-ci/workflow.md).

- **`python` resolvía a un intérprete distinto del que tenía `python-vlc`
  y `PySide6` instalados.** La máquina tiene varios Python instalados
  (`C:\Python314` en el PATH de *Sistema*, y otro bajo
  `AppData\Local\Python\...` en el PATH de *Usuario*); en Windows las
  entradas de Sistema siempre resuelven antes que las de Usuario, así que
  reordenar el PATH de usuario no habría cambiado nada, y editar el PATH
  de Sistema requiere permisos de administrador y afecta a todo el equipo.
  **Arreglado sin tocar el PATH**: se instalaron `python-vlc` y `PySide6`
  también en `C:\Python314` (el intérprete que ya ganaba la resolución),
  para que `python run.py` funcione sin importar el orden del PATH.

- **Primer build real del `.exe` con PyInstaller, verificado end-to-end.**
  No existía ningún ejecutable construido hasta este punto. Tras generarlo
  (`pyinstaller ReproductorMultimediaPro.spec`), se verificó lanzándolo con
  los mismos archivos de prueba (audio + video, rutas con `/`) usados para
  el fix de rutas: reprodujo el audio pese a la ruta con `/` y pasó
  automáticamente al video al terminar, confirmando que el ejecutable
  empaquetado incluye tanto el fix de normalización de rutas como la
  lógica de recreación de instancia del visualizador.
