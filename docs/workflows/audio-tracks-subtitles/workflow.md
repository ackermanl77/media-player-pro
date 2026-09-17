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

## Validación

Verificado por inspección de código y por
`tests/test_app_smoke.py::test_playlist_and_ui_wiring_smoke`, que ejercita
`_populate_audio_track_menu()`/`_populate_subtitle_track_menu()` sin
errores. No se probó en vivo contra un MKV real con múltiples pistas
durante el desarrollo de esta función — si vas a depender de esto con un
archivo específico, confírmalo primero con ese archivo.
