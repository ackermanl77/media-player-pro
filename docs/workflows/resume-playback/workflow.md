# Recordar Posición de Reproducción

Inspirado en BS.Player: reabrir un archivo ya visto retoma donde quedó, en
vez de empezar desde cero.

## Goal

No perder el lugar donde quedaste en un video o audio largo entre una
sesión y la siguiente, sin intervención manual.

## Comportamiento

- Al cambiar de pista, cerrar la app, o cuando una pista se detiene, se
  guarda la posición actual del archivo que se estaba reproduciendo.
- Al volver a abrir ese mismo archivo (mismo path absoluto), se reanuda
  automáticamente desde ahí y aparece un mensaje breve en la barra de
  estado: "Reanudado desde `MM:SS`".
- **No se guarda** si la posición está a menos de 3 segundos del inicio
  (no vale la pena "reanudar" casi desde cero), ni si está a más del 97%
  del largo total (se considera visto por completo: la próxima vez
  arranca desde el principio).
- Si un archivo termina de forma natural (llega al final y la playlist
  avanza a la siguiente pista), su posición guardada se borra.
- Solo aplica a archivos locales — un stream por URL nunca guarda ni
  reanuda posición (no tiene sentido "reanudar" una transmisión en vivo).

## Dónde vive

`~/.reproductor_multimedia_pro/positions.json` — un diccionario plano
`{"ruta_absoluta": posicion_en_ms}`. Se puede borrar sin riesgo para
resetear todo el historial de posiciones.

## Cómo funciona por dentro

`player/resume.py` es un módulo puro (sin VLC ni Qt): `save_position()`,
`get_saved_position_ms()`, `clear_position()`. `MainWindow` lo llama desde
`play_index()` (guarda la posición de la pista saliente, consulta la de
la entrante), desde `update_ui()` (al detectar `vlc.State.Ended`, antes de
avanzar), y desde `closeEvent()`.

## Validación

`tests/test_resume.py` (8 tests, sin VLC/Qt) cubre los umbrales de
inicio/fin, persistencia entre llamadas separadas, y un archivo
`positions.json` corrupto tratado como vacío en vez de hacer crashear la
app. Verificado también en vivo contra un video real: reproducir hasta el
segundo 7 de un video de 12s, guardar, y confirmar que reabrirlo reanuda
después del segundo 6.
