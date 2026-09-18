# Pistas de Audio y Subtítulos

## Goal

Elegir entre varias pistas de audio o de subtítulos embebidas (típico en
archivos MKV con doblajes/idiomas múltiples), y cargar un subtítulo
externo cuando el video no trae uno embebido.

## Uso

- **Menú Audio → "Pistas de audio"**: submenú generado dinámicamente
  (`aboutToShow`) a partir de `VLCPlayer.audio_tracks()`, con la pista
  activa marcada. Elegir una la cambia al instante.
- **Menú Video → "Subtítulos"**: mismo mecanismo, vía
  `VLCPlayer.subtitle_tracks()`. Incluye la opción de desactivarlos.
- **Menú Video → "Cargar subtítulo externo..."**: abre un diálogo para
  elegir un archivo `.srt`/`.ass`/`.ssa`/`.sub`/`.vtt` y lo carga sobre el
  video actual (`video_set_subtitle_file`).

Ambos submenús solo tienen sentido mientras hay un archivo cargado con más
de una pista disponible; si el archivo actual solo trae una pista de audio
y no tiene subtítulos, los submenús aparecen prácticamente vacíos (solo la
opción "Disable" que libVLC siempre reporta).

## Sincronía de subtítulos (inspirado en BS.Player)

**Menú Video → "Adelantar/Retrasar subtítulos 50 ms"** (atajos `G`/`H`) o
**"Restablecer sincronía..."**. Ajusta `video_set_spu_delay()` en vivo —
efecto inmediato, no requiere recargar nada. Útil cuando un subtítulo
descargado por separado no está perfectamente alineado con el audio.

## Tamaño de subtítulos

**Menú Video → "Tamaño de subtítulos"** (Pequeño 75% / Normal 100% /
Grande 150% / Muy grande 200%). A diferencia del delay, `--sub-text-scale`
es una opción de **instancia** de libVLC (mismo caso que el visualizador de
audio — ver `docs/PROJECT_STATUS.md` → "Architecture"), así que cambiarlo
recarga el archivo actual internamente (`VLCPlayer.load()` recrea el
`Instance`); `MainWindow._on_subtitle_scale_changed()` preserva la
posición de reproducción y si estaba en pausa, para que el cambio se vea
transparente. No incluye color ni tipografía — deliberadamente fuera de
alcance para mantener la superficie de la función acotada.

## Validación

Verificado por inspección de código y por
`tests/test_app_smoke.py::test_playlist_and_ui_wiring_smoke`, que ejercita
`_populate_audio_track_menu()`/`_populate_subtitle_track_menu()` sin
errores. No se probó en vivo contra un MKV real con múltiples pistas
durante el desarrollo de esta función — si vas a depender de esto con un
archivo específico, confírmalo primero con ese archivo.

La sincronía de subtítulos y el cambio de tamaño sí se verificaron en vivo
contra un video real: ajustar el delay ±50 ms y confirmar el valor
reportado por `get_subtitle_delay_ms()`; cambiar el tamaño a 150% y
confirmar que la reproducción sigue en `State.Playing` justo después del
recorte/recarga interno (sin quedarse colgada, el mismo tipo de fallo que
motivó la reescritura del visualizador — ver "Architecture" en
`docs/PROJECT_STATUS.md`).
