# Tests y CI

## Goal

Detectar regresiones en la lógica de reproducción y en la interfaz sin
depender únicamente de pruebas manuales, tanto en desarrollo local como en
GitHub Actions.

## Correr los tests localmente

```bash
pip install -r requirements-dev.txt   # pytest y pytest-timeout (ya no estan en requirements.txt)
python -m pytest -q
```

Resultado actual (2026-10-22, Windows 11, Python 3.14, libVLC 3.0.23):
**406 passed, 1 skipped** y una falla intermitente conocida
(`test_visualizer.py::test_visualizer_enabled_produces_a_video_output_for_audio`,
ver Known Issues en `docs/PROJECT_STATUS.md`). Las pruebas que construyen ventanas fijan ellas mismas
`QT_QPA_PLATFORM=offscreen`.

El CI agrega `--timeout=120` (pytest-timeout): una prueba colgada en libVLC
falla en vez de trabar el job.

- `tests/test_formats.py`, `test_inputs.py`, `test_vlc_check.py`,
  `test_playlist_order.py`, `test_settings.py`: funciones puras, sin VLC ni Qt.
- `tests/test_p2_features.py`: eventos de libVLC, capítulos (con
  `tests/assets/chapters.mkv`, un video de 6 s y 30 KB generado con ffmpeg),
  desfase de audio, streams (servidor HTTP local), atajos, lista, tema,
  franja de lo almacenado de un stream.
- `tests/test_playlist_model.py`: modelo/vista de la lista y su
  controlador (`player/playlist_model.py`, `player/playlist_controller.py`)
  sin VLC; el analizador de metadatos se reemplaza por uno falso.
- `tests/test_actions.py`: el registro de acciones (`player/actions.py`)
  y que menús, menú contextual, botones y la ayuda de atajos usan los
  mismos `QAction`.
- `tests/test_version.py`: la versión única (`player.__version__`), el
  recurso de versión del `.exe` (`packaging/version_resource.py`; la parte
  que arma el objeto de PyInstaller se omite si no está instalado),
  `pyproject.toml` y el workflow de release.
- `tests/test_single_instance.py`: la segunda instancia es un proceso real
  que le pasa sus archivos a la primera por `QLocalServer`.
- `tests/test_subtitle_lifecycle.py`: hilos de subtítulos sin red.
- `tests/test_folder_scan.py`: escaneo de carpetas en segundo plano
  (`player/folder_scan.py`): lotes en el orden de `scan_folder()`,
  cancelación y señales entregadas en el hilo de la UI.
- `tests/test_competitor_features.py`: efectos de audio, tono y filtros de
  video, discos, recursos compartidos, convertir (una conversión real a
  MP3) y grabar (3.17-3.19, 4.17).
- `tests/test_resume.py`, `test_bookmarks.py`, `test_recent_files.py`,
  `test_persistence.py`, `test_opensubtitles.py`: módulos puros (posición
  y pistas por archivo, marcadores, recientes, JSON atómico y `.m3u8`,
  cliente de OpenSubtitles con `requests` simulado).
- `tests/test_equalizer.py` (presets, pasos de 0,1 dB, diálogo),
  `test_playback_fixes.py`, `test_preview_thumbnail.py`,
  `test_on_finish_action.py` (sin ejecutar nunca `shutdown`),
  `test_window_state.py`, `test_logs.py`: contra VLC/Qt reales.
- `tests/test_backend.py`, `tests/test_visualizer.py`: contra un VLC real
  (usan `player.backend.VLCPlayer` de verdad, no mocks). Se **omiten**
  automáticamente (no fallan) si `import vlc` lanza `OSError` — es decir,
  si VLC no está instalado en la máquina.
- `tests/test_app_smoke.py`: construye la `MainWindow` real con la
  plataforma Qt `QT_QPA_PLATFORM=offscreen` (no necesita pantalla). También
  se omite si no hay VLC.

`tests/conftest.py` (autouse) redirige `Path.home()` y `%LOCALAPPDATA%` a
carpetas temporales en todas las pruebas: construir/cerrar `MainWindow`
lee y escribe `settings.json`/`session.json`, y ninguna prueba debe tocar
el estado real del usuario. `tests/test_video_input.py` crea una ventana
Win32 **oculta** (nunca se muestra, sin entrada simulada) para comprobar que
la ventana de video de libVLC queda deshabilitada; solo corre en Windows.

## CI (GitHub Actions)

`.github/workflows/ci.yml` tiene dos jobs en cada push/PR a
`main`/`master`: `test-windows` (`windows-latest`, Python 3.12 y 3.14, VLC
instalado con `choco`, Qt `offscreen`) y `test` en `ubuntu-latest`.
Ambos corren `python -m compileall -q player run.py` y luego la suite con
`--timeout=120`. `.github/workflows/build-exe.yml` ya no corre en cada
push: se dispara con `workflow_run` cuando "CI" termina con éxito para un
push (o a mano con `workflow_dispatch`), y construye exactamente el commit
probado. Los tres jobs del CI y el build pasaron en GitHub el 2026-10-03
(antes, el job de Ubuntu fallaba en pruebas de rutas `C:/...`, que en
Linux son relativas, y en dos pruebas de opciones de GPU exclusivas de
Windows, que ahora se omiten fuera de Windows).

`.github/workflows/release.yml` se dispara al subir una etiqueta `v*`:
llama a `ci.yml` entero (`workflow_call`) y solo si pasa construye,
comprime y publica el Release (ver
[docs/workflows/packaging/workflow.md](../packaging/workflow.md)). No se
ejecutó todavía en GitHub (no se subió ninguna etiqueta desde que existe).

El job de Ubuntu (Python 3.12) necesita tres cosas que un entorno de
escritorio normal no:

1. **`vlc-plugin-visualization`** además de `vlc`: el filtro "visual" que
   usa el visualizador vive en un paquete separado que es una dependencia
   *Recommends* de `vlc`, no una dependencia dura — este runner no instala
   Recommends por defecto.
2. **`xvfb`** (`xvfb-run --auto-servernum python -m pytest -q`): sin un
   display X real, el módulo de video que VLC autoselecciona no tiene
   dónde salir.
3. **`--aout=adummy`** forzado en los tests que usan VLC directamente
   (`tests/test_backend.py`, `tests/test_visualizer.py`): el runner no
   tiene tarjeta de sonido, así que VLC falla al intentar abrir el
   dispositivo ALSA "default" — sin un audio output que funcione, el
   filtro de video del visualizador (que cuelga de la cadena de audio)
   nunca llega a correr, aunque el problema no tenga nada que ver con
   video en sí.

El relato completo de cómo se diagnosticaron estas tres causas (más una
cuarta, un bug en el propio test) está en la entrada correspondiente de
"Recently Fixed" en [`docs/PROJECT_STATUS.md`](../../PROJECT_STATUS.md) —
vale la pena leerlo antes de tocar `_headless_player()` en
`tests/test_visualizer.py`/`test_backend.py`, porque varias de esas
decisiones (por qué `BASE_VLC_ARGS` se parchea con `monkeypatch` en vez de
sobreescribir `player.instance` directamente, por qué el WAV de prueba
dura 8 segundos) no son obvias sin ese contexto.

## Qué NO está cubierto

- No hay verificación automatizada de que el audio suene "bien" (volumen,
  ecualizador) — eso depende de `python-vlc`/libVLC, no de código de este
  proyecto.
- No hay pruebas contra el `.exe` empaquetado; ver
  [docs/workflows/packaging/workflow.md](../packaging/workflow.md) para la
  verificación manual recomendada después de cada build.
- No se probó en vivo la selección de pistas de audio/subtítulos contra un
  archivo MKV real con múltiples pistas — ver
  [docs/workflows/audio-tracks-subtitles/workflow.md](../audio-tracks-subtitles/workflow.md).
