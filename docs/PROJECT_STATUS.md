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
| Posiciones de reproducción recordadas entre sesiones | `player/resume.py` |
| Marcadores nombrados por archivo | `player/bookmarks.py`, `player/bookmarks_dialog.py` |
| Lista de archivos/URLs abiertos recientemente | `player/recent_files.py` |
| Configuración persistente del usuario (API keys) | `player/config.py` |
| Cliente de la API REST de OpenSubtitles | `player/opensubtitles.py` |
| Diálogo de búsqueda/descarga de subtítulos online | `player/subtitle_dialog.py::OnlineSubtitleDialog` |
| Ícono de la app (ventana + `.exe`) | `player/assets/icon.png`, `player/assets/icon.ico` |
| Número de versión | `player.__version__` |
| Receta de PyInstaller para el ejecutable de Windows | `ReproductorMultimediaPro.spec` |

## Release

```text
dist/ReproductorMultimediaPro.exe
```

Se genera con `pyinstaller ReproductorMultimediaPro.spec`, manualmente o
automáticamente en cada push a `main`/`master` vía
`.github/workflows/build-exe.yml` (queda como artifact descargable en la
ejecución correspondiente de GitHub Actions). Ver
[docs/workflows/packaging/workflow.md](workflows/packaging/workflow.md).
No empaqueta VLC: la máquina que ejecute el `.exe` necesita tener VLC media
player instalado aparte, igual que al correr desde el código fuente.

## Recently Added

- **Cuatro funciones inspiradas en BS.Player**: recordar posición de
  reproducción entre sesiones, repetición A-B (loop de un tramo), sincronía
  y tamaño de subtítulos ajustables, y zoom de video + modo "siempre
  visible". El pedido original fue "revisa este instalador de BS.Player
  (`bsplayer279.setup.exe`) y agrega sus funciones acá" — **no se ejecutó
  el instalador** (aunque su firma digital resultó válida, de "AB Team
  d.o.o.", consistente con BS.Player real): correr un instalador de
  terceros sin poder supervisar interactivamente sus diálogos nativos de
  Windows no es algo para automatizar. En su lugar, se identificaron las
  funciones de BS.Player equivalentes y se implementaron directamente
  contra libVLC:
  - **Recordar posición** (`player/resume.py`, módulo puro sin VLC/Qt):
    guarda la posición de cada archivo local en
    `~/.reproductor_multimedia_pro/positions.json` al cambiar de pista o
    cerrar la app, y la restaura al reabrir el mismo archivo — con
    umbrales para no "reanudar" casi desde el inicio ni casi desde el
    final. Ver [docs/workflows/resume-playback/workflow.md](workflows/resume-playback/workflow.md).
  - **Repetición A-B**: un botón que cicla Marcar A → Marcar B (bucle
    activo) → Limpiar, comprobado en el mismo timer de 250 ms que ya
    actualizaba la barra de progreso. Ver
    [docs/workflows/ab-loop/workflow.md](workflows/ab-loop/workflow.md).
  - **Sincronía de subtítulos** (`video_set_spu_delay`, atajos `G`/`H`,
    ±50 ms, efecto inmediato) y **tamaño de subtítulos** (`--sub-text-scale`
    — de nuevo una opción de *instancia*, no de `Media`, así que cambiarla
    recarga el archivo actual internamente preservando posición y estado
    de pausa, igual que el visualizador de audio). Ver
    [docs/workflows/audio-tracks-subtitles/workflow.md](workflows/audio-tracks-subtitles/workflow.md).
  - **Zoom de video** (`video_set_scale`, en vivo, sin recrear nada) y
    **"Siempre visible"** (`Qt.WindowType.WindowStaysOnTopHint`).

  Las cuatro se verificaron en vivo contra un video sintético real (12s,
  generado con OpenCV): zoom, siempre-visible y delay de subtítulos sin
  excepciones; A-B efectivamente vuelve al punto A al cruzar B; el cambio
  de tamaño de subtítulos recarga y sigue en `State.Playing` sin
  colgarse; y recordar posición confirmado guardando en el segundo 7 de
  un video de 12s y comprobando que reabrirlo reanuda después del
  segundo 6. `tests/test_resume.py` (8 tests) cubre `player/resume.py`
  sin necesitar VLC ni Qt.

- **Quinta función inspirada en BS.Player: "acción al terminar la
  lista".** Al revisar `C:\Program Files (x86)\Webteh\BSPlayer` (instalado
  por el usuario) se encontró en `doc/cmdline.txt` el flag real `-sdown`
  ("Shutdown when movie is finished") y `changes.txt` confirmando que las
  funciones ya implementadas coinciden con BS.Player real. Se agregó un
  submenú Reproducción → "Al terminar la lista": Nada (por defecto), Salir
  del programa, y en Windows también Apagar el equipo / Hibernar /
  Reiniciar. Se dispara solo cuando la playlist termina de verdad (no en
  modo "Repetir: Todo"). Apagar/Reiniciar usan `shutdown /s|/r /t 60` (60s
  de margen, cancelable con `shutdown /a`); Hibernar (`shutdown /h`) es
  inmediato al no admitir retraso. Como con cualquier acción que apaga o
  reinicia la máquina, **nunca se ejecuta un `shutdown` real durante las
  pruebas**: `tests/test_on_finish_action.py` (5 tests) parchea
  `subprocess.run` para verificar el comando exacto que se arma en cada
  caso. Verificado además en vivo end-to-end con una playlist real de una
  sola pista de 5s y `on_finish_action="exit"`: la app se cierra sola
  justo cuando el video termina, confirmando que el disparo llega desde
  `update_ui()` → fin de playlist, no solo desde una llamada directa al
  método. Ver [docs/workflows/playlist/workflow.md](workflows/playlist/workflow.md).

- **Sexta función inspirada en BS.Player: búsqueda y descarga de
  subtítulos online, vía la API de OpenSubtitles.** De las dos funciones
  de mayor alcance identificadas (esta y "marcadores nombrados múltiples
  por archivo"), el usuario eligió esta primero y proporcionó su propia
  API key de opensubtitles.com (guardada localmente vía `player/config.py`
  en `~/.reproductor_multimedia_pro/config.json` — **nunca en el
  repositorio**). Piezas nuevas:
  - `player/opensubtitles.py`: cliente minimo de la API REST
    (`api.opensubtitles.com/v1`), sin dependencia de VLC/Qt. Incluye el
    algoritmo de hash de OpenSubtitles (el mismo que usa BS.Player y
    muchos otros reproductores: tamaño + suma de bloques de 8 bytes de
    los primeros/últimos 64KB, solo aplica a archivos ≥128KB) para
    búsqueda exacta, con fallback a búsqueda por texto (nombre del
    archivo limpio) cuando el hash no encuentra nada.
  - `player/subtitle_dialog.py::OnlineSubtitleDialog`: la UI — busca y
    descarga en `QThread`s separados para no congelar la interfaz durante
    las llamadas de red.
  - Nueva dependencia: `requests` (agregada a `requirements.txt` y
    `pyproject.toml`).

  `tests/test_opensubtitles.py` (9 tests) prueba el algoritmo de hash con
  vectores construidos a mano y el cliente HTTP con `requests.get`/`.post`
  reemplazados — la suite automatizada **nunca golpea la API real**.
  Verificado además en vivo, dos veces: primero el cliente en aislado
  (búsqueda por texto "The Matrix 1999" devolvió 50 resultados reales,
  descargar el primero produjo un `.srt` válido), y después el diálogo
  real completo end-to-end (`OnlineSubtitleDialog` contra un archivo de
  video real, hilo de búsqueda → selección → hilo de descarga → el
  archivo descargado llega hasta `VLCPlayer.load_subtitle_file()`). Ver
  [docs/workflows/online-subtitles/workflow.md](workflows/online-subtitles/workflow.md).

- **Séptima función inspirada en BS.Player: marcadores nombrados
  múltiples por archivo** (la segunda de las dos funciones de mayor
  alcance que se habían dejado pendientes). A diferencia de "recordar
  posición" (un único punto automático), esto guarda varios puntos con
  nombre por archivo. `player/bookmarks.py` (módulo puro, mismo patrón
  que `resume.py`) mantiene la lista siempre ordenada por posición en
  `~/.reproductor_multimedia_pro/bookmarks.json`;
  `player/bookmarks_dialog.py::BookmarksDialog` es la UI (agregar/ir
  a/renombrar/eliminar), cerrada automáticamente al cambiar de pista
  porque queda atada al archivo con el que se abrió. Atajo `B` para
  agregar uno rápido en la posición actual. `tests/test_bookmarks.py`
  (10 tests, sin VLC/Qt) cubre el ordenamiento, el aislamiento entre
  archivos, y los casos borde de eliminar el último marcador de un
  archivo o un índice fuera de rango. Verificado además en vivo contra
  la app real: agregar, "ir a" (saltó exactamente a la posición
  guardada), renombrar, eliminar, y confirmar que el diálogo se cierra
  al pasar por `play_index()`. Ver
  [docs/workflows/bookmarks/workflow.md](workflows/bookmarks/workflow.md).

- **Pasada de pulido de UI**, tras una revisión enfocada en la interfaz
  (`main_window.py` había crecido bastante con las 7 funciones anteriores).
  Cinco arreglos rápidos: (1) **ícono propio de la app** —
  `player/assets/icon.{png,ico}` (generado con Pillow como paso de build
  puntual, sin agregar Pillow como dependencia del proyecto), usado como
  ícono de ventana en runtime (`QIcon`, vía el nuevo helper `_icon_path()`
  que resuelve la ruta tanto corriendo desde el código fuente como
  empaquetado con `sys._MEIPASS`) y como ícono del propio `.exe` (parámetro
  `icon=` en `ReproductorMultimediaPro.spec`, que ahora también declara
  `datas` para empaquetar ambos archivos). (2) Porcentaje de volumen
  visible junto al slider. (3) Tooltips en todos los controles de la barra
  que no los tenían. (4) Separadores agrupando los menús "Reproducción" y
  "Video", que se habían vuelto largos y planos. (5) Número de versión
  (`player.__version__`, nuevo) en "Acerca de".

  Más tres mejoras de mayor alcance: **marcadores visuales en la barra de
  progreso** — `PositionSlider` (subclase de `QSlider` que pinta líneas de
  color sobre la barra en `paintEvent`) muestra el punto A/B (naranja) y
  los marcadores nombrados (dorado) del archivo actual, recalculados en
  cada tick de `update_ui()`; **valores en dB en el ecualizador** —
  `EqualizerDialog` ahora tiene una etiqueta por slider (preamp + cada
  banda) que se actualiza en vivo al arrastrar, y también al aplicar un
  preset; **íconos y duración por pista en la playlist** — `_display_name()`
  antepone 🎵/🎬/🌐 según el tipo, y cada ítem gana su duración
  (`MM:SS`) la primera vez que esa pista efectivamente se reproduce y VLC
  reporta su largo (no se pre-calcula toda la playlist por adelantado,
  para no bloquear la interfaz analizando archivos que quizás nunca se
  reproduzcan).

  Verificado en vivo contra la app real y un video real de 12s: ícono de
  ventana no vacío, cero botones sin tooltip, el label de volumen sigue al
  slider, el ítem de playlist pasa de solo-ícono a "ícono — duración"
  después de reproducir, marcar A/B más un marcador nombrado produce
  exactamente 3 marcadores en las fracciones y colores esperados, y mover
  un slider del ecualizador actualiza su etiqueta al valor exacto. También
  se generó un build real de PyInstaller con el `.spec` actualizado
  (confirmado en el log: "Copying icon to EXE") y se lanzó el `.exe`
  resultante para confirmar que los assets empaquetados se cargan sin
  error fuera del entorno de desarrollo.

- **Tres funciones nuevas: avance fotograma a fotograma, archivos recientes,
  y miniatura de vista previa al pasar el mouse por la barra de progreso.**
  - **Avance fotograma a fotograma**: `VLCPlayer.next_frame()` envuelve
    `libvlc_media_player_next_frame()`, pero solo actua si
    `VLCPlayer.is_paused()` (si no, devuelve `False` sin tocar libVLC,
    porque el siguiente refresco de video pisaria de inmediato el
    fotograma adelantado). Atajo "." y entrada "Avanzar un fotograma" en
    el menú Reproducción (`MainWindow.step_frame()`), que muestra un aviso
    en la barra de estado si se llama sin pausar primero.
  - **Archivos recientes** (`player/recent_files.py`, mismo patrón que
    `resume.py`/`bookmarks.py`: JSON puro en
    `~/.reproductor_multimedia_pro/recent_files.json`): lista de hasta 20
    rutas/URLs, más reciente primero, reabrir una existente la mueve al
    frente en vez de duplicarla. `MainWindow` registra cada pista
    efectivamente reproducida (`play_index()`) y expone un submenú
    "Archivo → Abrir reciente" (poblado bajo demanda vía `aboutToShow`,
    mismo patrón que los submenús de pistas de audio/subtítulos) con
    "Limpiar lista".
  - **Miniatura de vista previa en la barra de progreso**: al pasar el
    mouse sobre `PositionSlider` (que ahora emite `hovered`/`hoverEnded`),
    tras un debounce de 300 ms aparece un popup con un fotograma de esa
    posición. libVLC no ofrece forma de capturar un fotograma en frío sin
    decodificar hasta ahí, así que se usa un segundo `vlc.MediaPlayer`
    (mismo `Instance`, mismo archivo, silenciado y enganchado a un widget
    invisible fuera de pantalla) enteramente separado del reproductor
    principal -- la búsqueda real ocurre ahí, nunca en lo que el usuario
    está viendo/escuchando (`VLCPlayer.load_preview_media()`/
    `seek_preview()`/`take_preview_snapshot()`). Se encontró (y evitó) un
    comportamiento real de libVLC probado contra el binario: pausar el
    reproductor de vista previa inmediatamente después de `play()`, antes
    de que llegue el primer fotograma a la salida de video, lo deja
    "vacío" para siempre -- `video_take_snapshot()` sigue devolviendo
    éxito pero nunca vuelve a escribir un archivo. La solución: se deja
    reproduciendo (silenciado) hasta que la primera captura efectivamente
    produce un archivo, y solo entonces se pausa (pausar *después* del
    primer fotograma sí es seguro y deja capturas siguientes funcionando
    con el reproductor en pausa, sin seguir gastando CPU de fondo).
  - `tests/test_backend.py` (3 pruebas nuevas) cubre `next_frame()`/
    `is_paused()`; `tests/test_preview_thumbnail.py` (6 pruebas) cubre el
    reproductor de vista previa reutilizando el mismo truco que
    `test_visualizer.py` (visualizador de espectro sobre un WAV) para
    tener salida de video real y verificable sin un archivo de video de
    verdad; `tests/test_recent_files.py` (10 pruebas) cubre
    `recent_files.py` sin VLC/Qt; `tests/test_app_smoke.py` gana 6 pruebas
    de humo para el cableado de las tres funciones en `MainWindow`. Las
    interacciones reales de mouse (hover) y teclado no se pueden ejercitar
    con la plataforma Qt "offscreen" (igual que el resto de
    `components`/interacciones de mouse del proyecto): se verifican
    llamando directamente a los métodos internos que esa interacción real
    termina invocando (`_on_slider_hovered`, `step_frame`, etc.), no
    simulando el movimiento del mouse en sí.

- **Pasada de revisión de UI**, tras una revisión enfocada en feedback
  visual y en el uso del mouse en pantalla completa. Tres arreglos:
  - **OSD (overlay en pantalla) reutilizable**: un `QLabel` semitransparente
    flotando sobre `video_frame` (`_show_osd()` en `main_window.py`), con un
    único `QTimer` de ~1.5s que lo oculta. Cableado a los tres sitios que
    antes no daban ninguna señal visual de éxito: `step_frame()`
    ("Fotograma siguiente"), `_seek_relative()` ("+5s"/"-5s") y
    `_nudge_volume()` ("Volumen: NN%").
  - **Controles flotantes en pantalla completa**: en vez de que
    `toggle_fullscreen()` oculte `controls_bar` por completo, ahora la
    reparenta como overlay sobre `video_frame` (`_float_controls_bar()`/
    `_unfloat_controls_bar()`, reutilizando los mismos widgets en vez de
    duplicar cada botón) y la muestra/oculta según actividad de mouse: un
    filtro de eventos a nivel de aplicación (`eventFilter()`, instalado en
    `__init__` y removido en `closeEvent`) detecta `QEvent.MouseMove` en
    cualquier widget mientras la ventana está en pantalla completa y
    reinicia un `QTimer` de inactividad de ~2.5s (`_fullscreen_idle_timer`)
    que la vuelve a ocultar.
  - **Timestamp en la miniatura de vista previa**: el popup de
    `_show_hover_preview()` pasó de ser un solo `QLabel` con el pixmap a un
    `QWidget` con un `QVBoxLayout` que agrega un segundo `QLabel` debajo,
    con `format_time()` sobre la posición (fracción × duración) que
    representa el punto bajo el mouse — antes solo se veía el fotograma,
    sin saber a qué instante correspondía.
  - `tests/test_app_smoke.py` gana 12 pruebas nuevas. Igual que con la
    vista previa, la interacción real de mouse en pantalla completa no se
    puede ejercitar con la plataforma "offscreen": se verifica llamando
    directamente a los métodos de estado (`_on_fullscreen_mouse_activity`,
    `_show_floating_controls`/`_hide_floating_controls`, `eventFilter()`
    con un `QEvent.MouseMove` sintético) en vez de simular el movimiento en
    sí. Las pruebas de visibilidad del OSD/controles usan `isHidden()` en
    vez de `isVisible()`, porque la ventana nunca se muestra en estas
    pruebas y `isVisible()` de un widget hijo depende de la visibilidad de
    sus ancestros, no solo de su propio último `show()`/`hide()`.

## Verification

```bash
python -m pytest -q
```

`tests/test_formats.py`, `test_resume.py`, `test_bookmarks.py` y
`test_opensubtitles.py` no dependen de VLC ni de Qt (este último tampoco
toca la red real: mockea `requests`). El resto de la suite (`test_backend.py`, `test_visualizer.py`,
`test_app_smoke.py`, `test_on_finish_action.py`) importa `vlc` de verdad y
se **omite automáticamente** (no falla) si no hay VLC instalado en la
máquina — son pruebas de humo reales contra libVLC, no mocks. Corre
`pytest` tú mismo antes de confiar en un número de tests
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
