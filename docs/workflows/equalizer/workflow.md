# Ecualizador

## Goal

Ajustar el balance de frecuencias del audio con un ecualizador gráfico de
10 bandas, con los presets que trae VLC (Clásica, Rock, Pop, ...) o de
forma manual.

## Uso

Menú **Audio → Ecualizador...** abre un diálogo no modal (se puede dejar
abierto mientras se sigue usando el reproductor).

1. Marcar "Activar ecualizador" para habilitarlo (desactivado por
   defecto — sin tocarlo, el audio suena sin procesar).
2. Elegir un preset del combo, o mover manualmente el slider de preamp y
   los 10 sliders de banda (rango -20 dB a +20 dB cada uno).

El diálogo es un singleton por ventana (`MainWindow.equalizer_dialog`):
abrirlo dos veces reusa la misma instancia en vez de crear una nueva, así
que el estado configurado persiste mientras la app siga abierta.

## Cómo funciona por dentro

`VLCPlayer.get_equalizer()`/`apply_equalizer_preset()`/
`set_equalizer_preamp()`/`set_equalizer_band()` envuelven directamente
`vlc.AudioEqualizer` y `media_player.set_equalizer()`. A diferencia del
visualizador, el ecualizador **sí** es una propiedad del `MediaPlayer` en
sí (no de la `Instance`), así que no necesita ninguna recreación especial
al cambiar de pista.

## Validación

`tests/test_app_smoke.py::test_equalizer_dialog_builds_without_error`
construye el diálogo real contra un VLC real (sin pantalla, plataforma Qt
`offscreen`) y confirma que no lanza excepciones. No se verificó
auditivamente que cada banda modifique el sonido de forma audible — la
correctitud de esa parte descansa en `vlc.AudioEqualizer`, no en código de
este proyecto.
