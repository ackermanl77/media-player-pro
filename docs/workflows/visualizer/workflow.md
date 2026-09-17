# Visualizador de Audio

## Goal

Mostrar un espectro animado en lugar de una pantalla negra al reproducir
un archivo de solo audio.

## Uso

Menú **Audio → "Visualizador de audio (espectro)"** (activado por defecto,
checkbox). Se activa automáticamente para cualquier archivo local cuya
extensión esté en `player.formats.AUDIO_EXTS` — no para streams por URL
(ver "Known Issues" en `docs/PROJECT_STATUS.md`) ni, por supuesto, para
archivos de video reales, que siempre muestran su propio video.

El cambio de estado del toggle se aplica a partir de la **siguiente** pista
que se cargue, no a la que esté sonando en ese momento.

## Cómo funciona por dentro

libVLC expone esto como un filtro de audio llamado `visual`
(`--audio-visual=visual --effect-list=spectrum`), pero estas son opciones
de **instancia** de libVLC, no de un `Media` individual —
`libvlc_media_add_option()` las ignora en silencio si se intentan pasar
así. Por eso `VLCPlayer` (`player/backend.py`) recrea su `vlc.Instance`
completa cada vez que cambia si la próxima pista necesita o no el
visualizador (`_create_instance()`), reaplicando volumen, mute, velocidad
y ecualizador para que el cambio sea transparente. Ver "Architecture" en
`docs/PROJECT_STATUS.md`.

## Validación

`tests/test_visualizer.py` reproduce un WAV generado con la librería
estándar (`wave`) usando el mismo `VLCPlayer` de la app, con
`enable_visualizer=True`/`False`, y comprueba con `has_active_video_output()`
que la salida de video del filtro efectivamente aparece (o no aparece)
según el toggle. Requiere VLC real instalado; se omite si no lo hay.
En CI (Ubuntu, sin tarjeta de sonido ni pantalla real) corre bajo `xvfb`
con `--aout=adummy` — ver
[docs/workflows/testing-ci/workflow.md](../testing-ci/workflow.md) para el
detalle de por qué hizo falta.
