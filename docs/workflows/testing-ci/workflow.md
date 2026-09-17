# Tests y CI

## Goal

Detectar regresiones en la lógica de reproducción y en la interfaz sin
depender únicamente de pruebas manuales, tanto en desarrollo local como en
GitHub Actions.

## Correr los tests localmente

```bash
python -m pytest -q
```

- `tests/test_formats.py`: funciones puras, sin VLC ni Qt.
- `tests/test_backend.py`, `tests/test_visualizer.py`: contra un VLC real
  (usan `player.backend.VLCPlayer` de verdad, no mocks). Se **omiten**
  automáticamente (no fallan) si `import vlc` lanza `OSError` — es decir,
  si VLC no está instalado en la máquina.
- `tests/test_app_smoke.py`: construye la `MainWindow` real con la
  plataforma Qt `QT_QPA_PLATFORM=offscreen` (no necesita pantalla). También
  se omite si no hay VLC.

## CI (GitHub Actions)

`.github/workflows/ci.yml` corre en `ubuntu-latest` en cada push/PR a
`main`/`master`. Tres cosas que este runner necesita y que un entorno de
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
