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
VLC media player 3.0 de 64 bits instalado en la máquina (o, con un build
BUNDLE_VLC=1, el libVLC recortado dentro del paquete)
```

`MainWindow` (`player/main_window.py`) arma la ventana (barra de
controles, menús, dock de la playlist) y traduce cada acción del usuario en
llamadas a un único `VLCPlayer`; no importa `vlc` (lee el estado como
`backend.PlaybackState`). Delega en módulos propios:

- `player/actions.py::ActionRegistry`: cada comando es un `QAction` con id,
  texto, atajo y slot; el mismo objeto alimenta los menús, el menú
  contextual del video, los botones (`setDefaultAction`), el controlador
  de pantalla completa y Ayuda → Atajos de teclado.
- `player/playlist_model.py` (`PlaylistModel` / `PlaylistFilterProxy` /
  `PlaylistView`, modelo/vista de Qt) y `player/playlist_controller.py`
  (`PlaylistController`: modelo + filtro + `PlaylistOrder`, fila actual y
  de la sesión, metadatos en segundo plano, título del panel).
- `player/preview_controller.py::PreviewController`: miniatura al pasar el
  mouse por la barra (debounce, caché, captura).
- `player/fullscreen.py::FullscreenMode`: entrar/salir de pantalla
  completa, controlador flotante, temporizador de inactividad y cursor.
- `player/widgets.py` (área de video, barra con marcadores y franja de lo
  almacenado, ventanas superpuestas, controlador de pantalla completa),
  `equalizer_dialog.py`, `power.py`, `theme.py`, `url_dialog.py`,
  `single_instance.py`, `inputs.py`, `vlc_check.py`.
- `player/folder_scan.py::FolderScanWorker`: recorre "Abrir carpeta" en un
  `QThread` (lotes ordenados de `inputs.scan_folder_batches()`, cancelable).

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
| Posición y pistas de audio/subtítulos recordadas por archivo | `player/resume.py` (`positions.json`) |
| Escaneo de carpetas en segundo plano | `player/folder_scan.py::FolderScanWorker`, `player/inputs.py` |
| Expandir carpetas/`.m3u` de la línea de comandos y de lo arrastrado | `player/inputs.py::expand_inputs` |
| Acción al terminar la lista (cuenta regresiva, apagar/hibernar/reiniciar) | `player/power.py` |
| Diálogo del ecualizador (pasos de 0,1 dB) | `player/equalizer_dialog.py` |
| Una sola ventana (`QLocalServer`, `--new-window`, `--enqueue`) | `player/single_instance.py` |
| Diagnóstico de VLC ausente / de 32 bits al arrancar | `player/vlc_check.py` |
| Marcadores nombrados por archivo | `player/bookmarks.py`, `player/bookmarks_dialog.py` |
| Lista de archivos/URLs abiertos recientemente | `player/recent_files.py` |
| Orden de reproducción (secuencial/aleatorio) y detección de fallo | `player/playlist_order.py` |
| Lista: modelo, filtro del buscador y vista reordenable | `player/playlist_model.py` |
| Lista: agregar/quitar/mover/ordenar, sesión y metadatos en segundo plano | `player/playlist_controller.py::PlaylistController` |
| Acciones con nombre (menús, menú contextual, botones, ayuda de atajos) | `player/actions.py::ActionRegistry` |
| Miniatura de vista previa sobre la barra | `player/preview_controller.py::PreviewController` |
| Pantalla completa (controlador flotante, inactividad, cursor) | `player/fullscreen.py::FullscreenMode` |
| Lectura/escritura de `.m3u` | `player/m3u.py` |
| JSON atómico con `.bak` para el estado del usuario | `player/jsonstore.py` |
| Configuración persistente del usuario (API keys) | `player/config.py` |
| Ajustes y sesión (playlist) entre ejecuciones | `player/settings.py` (`settings.json`, `session.json`) |
| Log rotativo, excepthooks y `faulthandler` | `player/logs.py` (configurado desde `run.py`) |
| Cliente de la API REST de OpenSubtitles | `player/opensubtitles.py` |
| Diálogo de búsqueda/descarga de subtítulos online | `player/subtitle_dialog.py::OnlineSubtitleDialog` |
| Ícono de la app (ventana + `.exe`) | `player/assets/icon.png`, `player/assets/icon.ico` |
| Número de versión (única fuente) | `player.__version__` |
| Receta de PyInstaller para el ejecutable de Windows | `ReproductorMultimediaPro.spec` |
| Runtime hook que elige el libVLC empaquetado (`BUNDLE_VLC=1`) | `packaging/rthook_bundled_vlc.py` |
| Instalador por usuario (Inno Setup 6) | `installer/ReproductorMultimediaPro.iss` |
| Licencias de VLC y enlace a su código fuente | `licenses/` |
| Build automático tras el CI en verde | `.github/workflows/build-exe.yml` |
| Recurso de versión del `.exe` (Propiedades → Detalles) | `packaging/version_resource.py` |
| Release con etiqueta `v*` (CI, build, zip, instalador, GitHub Release) | `.github/workflows/release.yml` |

## Release

```text
dist/ReproductorMultimediaPro/ReproductorMultimediaPro.exe   (carpeta onedir)
dist/installer/ReproductorMultimediaPro-<version>-setup.exe  (Inno Setup, por usuario)
```

Se genera con `pyinstaller --noconfirm ReproductorMultimediaPro.spec` (y
`iscc /DAppVersion=<version> installer\ReproductorMultimediaPro.iss` para el
instalador), manualmente o automáticamente tras cada push a
`main`/`master` con el CI en verde vía `.github/workflows/build-exe.yml`
(queda como artifact descargable en la ejecución correspondiente de GitHub
Actions; la última, del 2026-10-03, pasó). Ver
[docs/workflows/packaging/workflow.md](workflows/packaging/workflow.md).
Al subir una etiqueta `v<version>` (igual a `player.__version__`, hoy
`0.2.0`), `.github/workflows/release.yml` corre el CI completo y luego
construye la carpeta onedir, el `.zip`, el instalador y `SHA256SUMS.txt`, y
los publica como GitHub Release. Ese workflow todavía no corrió: el único
Release es `v0.1.0` (2026-09-19), anterior, con el antiguo `.exe` de un solo
archivo, y `v0.2.0` se etiqueta cuando GitHub Actions vuelva a poder subir
artifacts (el almacenamiento gratis del mes se agotó el 2026-10-07 y se
renueva el 1 de noviembre).

**Firma de código:** `python packaging/sign_and_package.py` (después de
PyInstaller, con `CODESIGN_THUMBPRINT` = huella SHA-1 de un certificado de
firma del almacén de Windows) firma el `.exe` con signtool y compila el
instalador pasándole a Inno Setup la herramienta "codesign", así quedan
firmados también el instalador y su desinstalador (sello de tiempo de
`CODESIGN_TIMESTAMP_URL`, por defecto DigiCert). Verificado el 2026-10-07
con un certificado autofirmado de prueba (build real: `.exe`, desinstalador
e instalador firmados y sellados); hasta usar un certificado de confianza,
SmartScreen sigue avisando. El CI no firma.

No empaqueta VLC por defecto: la máquina que ejecute el `.exe` necesita VLC
3.0 de 64 bits instalado aparte (`BUNDLE_VLC=1` lo incluye recortado, con
sus licencias; ver README). Verificado con builds locales (2026-10-01/02):
onedir de 77,9 MB que arranca con el VLC del sistema, variante
`BUNDLE_VLC=1` de 182,5 MB que usa solo el libVLC incluido, recurso de
versión del `.exe`, y el instalador compilado con instalación y
desinstalación silenciosas (sin restos en el registro). Falta una prueba
manual interactiva del instalado ("Abrir con", reproducir).

## Recently Added

- **Passthrough de audio (2026-10-17, 3.16).** Audio → Passthrough: Desactivado / AC3 y DTS / Todos
  los formatos. Opción de instancia como la mejora por GPU (`passthrough_instance_args()`:
  `--mmdevice-passthrough=1|2` en Windows, `--spdif` en otros sistemas; un grupo propio en
  `create_instance_with_fallback`, que se descarta con aviso si libVLC lo rechaza); se aplica con
  `reload_preserving_state()` y se guarda en `Settings.audio_passthrough`. Comprobado que libVLC
  3.0.23 crea la instancia con cada valor; si el dispositivo no lo admite, libVLC decodifica como
  siempre (falta probarlo con un receptor real). Pruebas: `tests/test_passthrough.py`.

- **Controles multimedia del sistema (2026-10-17, 4.12).** `player/media_controls.py` registra el
  reproductor en los SMTC de Windows a través de un `Windows.Media.Playback.MediaPlayer` propio que
  no reproduce nada (pywinrt, `requirements.txt` solo en Windows; sin él, `available` es False):
  teclas multimedia con la ventana sin foco, título y estado en el panel multimedia y la pantalla
  de bloqueo. Botones y teclas de la ventana pasan por `MainWindow.media_command()`, que cuenta una
  vez la misma pulsación llegada por los dos caminos (400 ms). Verificado con el administrador de
  sesiones de Windows (`GlobalSystemMediaTransportControlsSessionManager`): la sesión aparece con
  su título, pasa de Playing a Paused y desaparece al cerrar. Pruebas: `tests/test_media_controls.py`.
  Pendiente: los botones de la miniatura de la barra de tareas (ITaskbarList3).

- **Atajos editables (2026-10-17, 4.11).** Ayuda → Atajos de teclado (`player/shortcuts_dialog.py`)
  reasigna, quita o restaura el atajo de cualquier acción del registro (también las que no tenían
  uno); los fijos (QShortcut) se muestran en gris. `ActionRegistry` recuerda el predeterminado de
  cada acción (`default_shortcut`, `is_customized`, `conflict`, `overrides`, `apply_overrides`,
  `reset_shortcuts`); `Settings.shortcuts` guarda solo lo cambiado, en texto portable, y al
  arrancar se descartan ids que ya no existen, textos ilegibles y choques. Pruebas:
  `tests/test_shortcuts.py` (incluye guardar y reabrir la ventana real).

- **Funciones de VLC que faltaban (informe 4.10, 2026-10-11).** Audio → Dispositivo de salida (lista de
  libVLC, se recuerda; uno desconectado se muestra como tal) y Normalizar volumen (normvol). Video →
  Relación de aspecto y Recortar (teclas `A`/`C` las recorren, con OSD), Desentrelazado (se recuerda;
  volver a "Automático" recrea el reproductor, porque libVLC 3 no tiene API para pedirlo de nuevo),
  Ajustes de video (`Ctrl+E`, filtro adjust en vivo, se recuerdan) e Información del medio (`Ctrl+I`).
  Todo ese estado del MediaPlayer se reaplica al recrearlo, como el zoom. Dos cosas de libVLC 3.0.23
  medidas al hacerlo, resueltas en `player/vlc_internals.py` (ctypes): `MediaTrack` de python-vlc
  declara audio/video/subtitle como campos seguidos en vez de una union y leer el bitrate de una pista
  cuelga el proceso; y `--audio-filter` en la Instance se ignora (el reproductor crea su variable sin
  heredar) y `set_equalizer` la pisa con "equalizer". El normalizador fija la cadena con
  `var_SetChecked` de libvlccore en el reproductor y en su salida de audio ya creada (como hace libVLC
  con el ecualizador): medido con la salida capturada, baja una senoide fuerte a menos de un tercio,
  en vivo, y sigue activo despues de mover el ecualizador. Si esos simbolos faltan, la opcion queda
  desactivada con el motivo.
- **Autodiagnostico del .exe (informe 8.5).** `ReproductorMultimediaPro.exe --self-test
  [--self-test-output=ARCHIVO]` (`player/self_test.py`) comprueba version, Qt, la traduccion, libVLC
  reproduciendo un WAV generado (y leyendo sus pistas) y la ventana principal en offscreen, sin tocar
  los ajustes del usuario; codigo 0 si todo paso. `release.yml` instala VLC con choco y lo corre sobre
  el `.exe` construido antes de comprimir. Verificado con un build local (2026-10-11): las seis
  comprobaciones pasan.

- **Restos P3 del informe (2026-10-07).** Bucle A-B: `Alt+Shift+←/→` y `Ctrl+Shift+←/→` mueven A y B
  de a 0,1 s (sin cruzarse ni salir del archivo) y "Bucle entre marcadores" repite el tramo entre los
  marcadores que rodean la posición (3.9). El ecualizador pasa a "Personalizado" al mover una banda
  o el preamp a mano (3.10). Los desfases de audio y subtítulos se recuerdan por archivo en
  `positions.json` y se aplican al empezar a reproducir (3.13). Los mensajes del OSD también van a la
  barra de estado y, con Qt 6.8+, como aviso accesible para lectores de pantalla (4.8). Las carpetas
  soltadas, pasadas por línea de comandos o reenviadas por otra instancia se recorren en el mismo
  `QThread` que "Abrir carpeta" (`expand_inputs_batches()`), en cola si ya hay un escaneo (5.5). Una
  prueba fija que los marcadores de la barra solo se reconstruyen al invalidarse (5.4). Firma de código
  con `packaging/sign_and_package.py` (ver Release).

- **Tanda P3 del informe (2026-10-03).** "Abrir carpeta" se recorre en un
  `QThread` (`player/folder_scan.py`): lotes en el mismo orden natural que
  `scan_folder()`, progreso en la barra de estado y Archivo → "Cancelar
  escaneo de carpeta" (agrega lo encontrado hasta ahí); las señales de fin
  y cancelación van a métodos de `MainWindow` para que Qt las encole al
  hilo de la UI. La pista de audio y la de subtítulos se recuerdan por
  archivo (`positions.json`, junto a la posición) y se restauran al
  reproducirlo. Ecualizador en pasos de 0,1 dB, con un campo numérico por
  banda y para el preamp. Atajos del bucle A-B: `Ctrl+Shift+A` / `B` / `L`.
  Las listas `.m3u8` se guardan de forma atómica (temporal + fsync +
  reemplazo, con `.bak` al que cae la carga). `licenses/` (GPL/LGPL de VLC
  y el enlace al código fuente de VLC 3.0.23) viaja con el build
  `BUNDLE_VLC=1` y con el instalador. Cubierto por
  `tests/test_folder_scan.py`, `test_resume.py`, `test_equalizer.py`,
  `test_inputs.py` y `test_persistence.py`.

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
  inmediato al no admitir retraso (la tanda P2 lo reemplazó por una
  cuenta regresiva propia de 60 s, cancelable, para las tres acciones:
  `player/power.py`). Como con cualquier acción que apaga o
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

```powershell
python -m pip install -r requirements-dev.txt
$env:QT_QPA_PLATFORM="offscreen"; python -m pytest -q
```

**2026-10-11, Windows 11, Python 3.14, libVLC 3.0.23: 344 passed** (≈65 s; 335 el 2026-10-07, 319 el
2026-10-03).
En GitHub Actions, `.github/workflows/ci.yml` corre `compileall` y la suite
con `--timeout=120` en `ubuntu-latest` (Python 3.12, bajo `xvfb-run`) y en
`windows-latest` (Python 3.12 y 3.14, VLC instalado con `choco`); la última
ejecución (2026-10-03) pasó en los tres jobs. Corre `pytest` tú mismo antes
de confiar en un número de tests: la suite sigue creciendo.

`tests/test_formats.py`, `test_resume.py`, `test_bookmarks.py`,
`test_inputs.py`, `test_playlist_order.py`, `test_settings.py` y
`test_opensubtitles.py` no dependen de VLC ni de Qt (este último tampoco
toca la red real: mockea `requests`). Las pruebas que importan `vlc`
(`test_backend.py`, `test_visualizer.py`, `test_app_smoke.py`,
`test_on_finish_action.py`, ...) son pruebas reales contra libVLC, no
mocks, y se **omiten automáticamente** (no fallan) si no hay VLC instalado.
Detalle por archivo en
[docs/workflows/testing-ci/workflow.md](workflows/testing-ci/workflow.md).

## Known Issues

- **Falta verificar a mano con un video real**: que el OSD y el
  controlador de pantalla completa se ven *encima* del video, la rueda y el
  clic derecho sobre el video (dependen de que la ventana hija de libVLC
  quede deshabilitada), varios monitores/DPI, y que RTX Video Super
  Resolution / RTX Video HDR realmente se activan (requieren la GPU y el
  panel de NVIDIA; la plataforma `offscreen` de las pruebas no renderiza
  libVLC).
- **El workflow de release nunca se ejecutó** (no se subió ninguna
  etiqueta desde que existe) y el instalado no se probó a mano ("Abrir
  con", reproducir); ver Release.
- **`main_window.py` sigue siendo grande** (~2.400 líneas, el informe
  apuntaba a ~400): ya están separados todos los módulos que listaba el
  informe (acciones, lista modelo/vista + controlador, vista previa,
  pantalla completa, widgets, ecualizador, energía, tema, escaneo de
  carpetas...), pero `MainWindow` todavía arma los menús y cablea
  transporte, pistas, subtítulos, A-B, marcadores y ajustes.
- **Arrastrar para reordenar la lista no tiene prueba automática del
  gesto en sí** (Qt `offscreen` sin mouse simulado): se prueba el mismo
  camino que usa `dropEvent`; verificar a mano arrastrar una y varias
  filas, con y sin texto en el buscador.
- **La franja de lo almacenado de un stream es aproximada**: libVLC no
  expone qué bytes ya bajó; se dibuja el llenado de su caché de red
  (`:network-caching`, 1 s por defecto) delante de la posición, así que
  nunca muestra más que ese tamaño. Falta verla con un stream real.

## Recently Fixed

- **Tanda "importantes" del informe (2026-10-02).** La lista de
  reproducción pasó de `QListWidget` a modelo/vista (`PlaylistModel` +
  `PlaylistFilterProxy` + `PlaylistView`, con `PlaylistController`
  uniendo modelo, filtro y `PlaylistOrder`), conservando arrastrar para
  reordenar, buscador, marcador ▶, quitar la actual, duraciones y
  etiquetas en segundo plano, total, menú contextual, aleatorio/repetir,
  sesión y `.m3u8`; el menú contextual de la lista ahora se ubica en las
  coordenadas del área visible (antes usaba las del widget, unos píxeles
  corridas). Nuevos módulos `actions.py` (`ActionRegistry`),
  `preview_controller.py` y `fullscreen.py` (refactor sin cambios de
  comportamiento). Franja de lo almacenado en la barra para streams de
  red. Versión única: `pyproject.toml` la toma de `player.__version__`
  (y declara `packages = ["player"]`: con `packaging/` e `installer/` en
  la raíz, el build de setuptools fallaba por "multiple top-level
  packages"), el `.exe` lleva recurso de versión y hay un workflow de
  release por etiqueta.

- **Tanda P2 del informe de mejoras (2026-09-30).** URLs: cualquier
  `esquema://` salvo `file:` es una URL (antes rtsps/srt/rtp/ftp/smb llegaban
  a `media_new_path` como `srt:\host`). Transiciones por **eventos de
  libVLC** (`PlayerEvents`, con número de generación para descartar eventos
  del archivo anterior); `main_window.py` ya no importa `vlc`; el tick bajó a
  500 ms y el tramo A-B usa un temporizador propio de 50 ms. `vlc.Instance`
  = `None` (opción desconocida) ya no rompe la reproducción: se reintenta sin
  la mejora por GPU / el visualizador y se avisa. Streams: `--http-reconnect`,
  diálogo de URL con caché/RTSP-TCP, búfer, "EN VIVO", título ICY, watchdog
  de 15 s, visualizador para URLs de solo audio. Una sola ventana
  (`QLocalServer`), `expand_inputs` para carpetas/.m3u, capítulos, desfase de
  audio, ciclo de vida de los hilos de subtítulos (no se cargan en otro
  video, errores siempre informados, sin destruir hilos en marcha al cerrar),
  atajos y menús nuevos, lista reordenable con buscador y metadatos, tema,
  traducción `qtbase_es`, RTX VSR/HDR, vista previa liviana con caché,
  cuenta regresiva para apagar/hibernar/reiniciar, reanudar vía
  `:start-time`, controlador de pantalla completa propio. Detalle y estado
  por punto en el informe (`..\improvement_reports\media_player_pro.md`, fuera del repositorio).

- **Tanda P1 del informe de mejoras (2026-09-30).**
  (1) **Presets del ecualizador**: `vlc.AudioEqualizer(indice)` toma el
  entero como puntero C; elegir un preset daba *access violation* y rompía
  cada cambio de banda y cada recreación del `Instance`. Ahora
  `libvlc_audio_equalizer_new_from_preset()` (índice inválido → `False`) y
  el ecualizador anterior se libera (`tests/test_equalizer.py`).
  (2) **La ventana de video de libVLC se quedaba con el mouse y el
  teclado**: `disable_vlc_input()` (`video_set_mouse_input/key_input(False)`)
  en cada `MediaPlayer` creado, principal y de vista previa; verificado con
  una ventana Win32 oculta que la ventana hija de libVLC queda
  deshabilitada (`tests/test_video_input.py`). Doble clic, movimiento del
  mouse en pantalla completa y atajos tras un clic en el video llegan a Qt.
  (3) **OSD y controles flotantes pintados debajo del video**: ahora viven
  en ventanas superpuestas propias (`OverlayWindow`: top-level, sin marco,
  translúcidas, sin foco, dueña la ventana principal) que siguen a
  `video_frame`; se ocultan al minimizar o cambiar de aplicación. El cursor
  se oculta sin actividad en pantalla completa.
  (4) **Atajos en pantalla completa**: los `QAction` de los menús se
  registran también en la ventana (Espacio, F, M... seguían muertos con la
  barra de menús oculta); la barra de estado se oculta y sus mensajes van
  al OSD. (5) **Ajustes y sesión** persistentes (`player/settings.py`).
  (6) **Registro de errores** para el `.exe` sin consola (`player/logs.py`).
  (7) `VLCPlayer.is_muted()` devuelve el estado propio (libVLC da -1 tras
  `stop()` y el botón de silencio no hacía nada). (8) CI en Windows
  (3.12 y 3.14) y el build del `.exe` espera a que el CI pase.
  `tests/conftest.py` aísla `Path.home()` y `%LOCALAPPDATA%` para toda la
  suite (`tests/test_window_state.py`, `test_settings.py`, `test_logs.py`).

- **Tanda de 10 bugs de transporte/playlist/persistencia (revisión contra
  libVLC 3.0.23).** (1) Reproducir tras Detener o fin de lista no hacía
  nada (`pause()` es no-op en Stopped/Ended): ahora rearranca la pista
  actual (`VLCPlayer.is_idle()`). (2) Un archivo roto con Repetir: Uno se
  recargaba cada 250 ms para siempre — y **en libVLC 3.0.23 un archivo
  inexistente o corrupto termina en `State.Ended`, no en `State.Error`**,
  así que la rama de error casi nunca corría: se detecta con
  `playlist_order.playback_failed()` (evento `MediaPlayerEncounteredError`
  o Ended sin largo ni avance), se ignora Repetir: Uno y se detiene tras
  una vuelta de fallos seguidos. (3) Aleatorio muestreaba con reemplazo,
  nunca terminaba y "Anterior" lo ignoraba: nuevo `PlaylistOrder`. (4)
  Claves por ruta sin normalizar: `formats.normalize_path()` al entrar a
  la playlist y `path_key()` (normcase+abspath) en resume/bookmarks/
  recientes, con migración de claves viejas al leer. (5) Detener/quitar de
  la lista perdía la posición (tras `stop()` el tiempo es -1): se guarda
  antes. (6) `bookmarks.json` se leía 4 veces por segundo: caché por
  pista. (7) Flechas arriba/abajo con la lista enfocada cambiaban el
  volumen: `ShortcutOverride` aceptado para la lista; Enter reproduce,
  Supr/menú quitan la selección múltiple. (8) JSON escrito sin atomicidad:
  `player/jsonstore.py` (temporal + `os.replace`, `.bak`, validación de
  tipos; `positions.json` con tope de 1000). (9) `.m3u`: rutas relativas a
  la carpeta de la lista, UTF-8→cp1252 en vez de `errors="ignore"`,
  `file:///`, errores de E/S con aviso (`player/m3u.py`). (10) Recrear el
  `vlc.Instance` no liberaba el viejo (ni el reproductor de vista previa,
  que además seguía decodificando): `_release_instance()`; se reaplica el
  zoom; cambiar el tamaño de subtítulos usa
  `VLCPlayer.reload_preserving_state()` en vez de `play_index()`
  (conserva posición, pausa, pistas, subtítulos externos, desfase, A-B y
  marcadores). Cubierto por `tests/test_playlist_order.py`,
  `tests/test_persistence.py` y `tests/test_playback_fixes.py`.

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
