# Recordar Posición de Reproducción

Inspirado en BS.Player: reabrir un archivo ya visto retoma donde quedó, en
vez de empezar desde cero.

## Goal

No perder el lugar donde quedaste en un video o audio largo entre una
sesión y la siguiente, sin intervención manual.

## Comportamiento

- Al cambiar de pista, cerrar la app, o cuando una pista se detiene, se
  guarda la posición actual del archivo que se estaba reproduciendo.
- Al volver a abrir ese mismo archivo (misma ruta normalizada), se
  reanuda automáticamente desde ahí: el OSD muestra "Reanudado en `MM:SS`
  — Inicio para empezar desde el principio" (tecla `Inicio`) y la barra
  de estado "Reanudado desde `MM:SS`".
- También se recuerdan, por archivo, la **pista de audio** y la **pista de
  subtítulos** elegidas, y se vuelven a seleccionar al reproducirlo.
- **No se guarda** si la posición está a menos de 3 segundos del inicio
  (no vale la pena "reanudar" casi desde cero), ni si está a más del 97%
  del largo total (se considera visto por completo: la próxima vez
  arranca desde el principio).
- Si un archivo termina de forma natural (llega al final y la playlist
  avanza a la siguiente pista), su posición guardada se borra.
- Solo aplica a archivos locales — un stream por URL nunca guarda ni
  reanuda posición (no tiene sentido "reanudar" una transmisión en vivo).

## Dónde vive

`~/.reproductor_multimedia_pro/positions.json` — `{"ruta normalizada":
{"position_ms": ..., "audio_track": ..., "subtitle_track": ...}}` (cada
campo es opcional; el formato viejo `{"ruta": ms}` se migra al leerlo).
Guarda como mucho 1000 archivos (se descartan los más antiguos). Se
escribe de forma atómica con copia `.bak` (`player/jsonstore.py`) y se
puede borrar sin riesgo para resetear todo el historial.

## Cómo funciona por dentro

`player/resume.py` es un módulo puro (sin VLC ni Qt): `save_position()`,
`get_saved_position_ms()`, `clear_position()`,
`save_track_selection()`/`get_saved_track_selection()`. `MainWindow` lo
llama al cambiar de pista (guarda la posición y las pistas de la saliente,
consulta las de la entrante), al detener o quitar el elemento, al terminar
una pista y al cerrar. La posición guardada se pasa como `:start-time` del
`Media` (no con un `set_time` después de `play()`, que libVLC podía
ignorar antes de abrir el archivo).

## Validación

`tests/test_resume.py` (12 tests, sin VLC/Qt) cubre los umbrales de
inicio/fin, persistencia entre llamadas separadas, las pistas por archivo,
la migración del formato viejo y un archivo `positions.json` corrupto
tratado como vacío en vez de hacer crashear la app. Verificado también en vivo contra un video real: reproducir hasta el
segundo 7 de un video de 12s, guardar, y confirmar que reabrirlo reanuda
después del segundo 6.
