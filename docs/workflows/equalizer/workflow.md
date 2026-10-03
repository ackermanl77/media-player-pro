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
2. Elegir un preset del combo, o ajustar a mano el preamp y las 10
   bandas (rango -20 dB a +20 dB cada una, en **pasos de 0,1 dB**). Cada
   banda tiene un slider, un campo numérico debajo (escribir un valor o
   usar sus flechas mueve el slider) y una etiqueta arriba (`+6,0 dB`,
   `-3,5 dB`, ...) que se actualiza en vivo mientras se arrastra, o al
   aplicar un preset. Mover una banda después de elegir un preset no
   cambia el combo a "Personalizado" (sigue mostrando el preset).

El diálogo es un singleton por ventana (`MainWindow.equalizer_dialog`):
abrirlo dos veces reusa la misma instancia en vez de crear una nueva, así
que el estado configurado persiste mientras la app siga abierta.

## Cómo funciona por dentro

`VLCPlayer.get_equalizer()`/`apply_equalizer_preset()`/
`set_equalizer_preamp()`/`set_equalizer_band()` envuelven
`vlc.AudioEqualizer` y `media_player.set_equalizer()`. Los presets se crean
con `vlc.libvlc_audio_equalizer_new_from_preset(i)` — **nunca** con
`vlc.AudioEqualizer(i)`, que en python-vlc toma el entero como un puntero C
y termina en *access violation* —, y cada ecualizador reemplazado se libera.

El estado (activado, preset, preamp y las 10 bandas con sus valores exactos)
se guarda al cerrar en `~/.reproductor_multimedia_pro/settings.json` y se
aplica al reproductor al iniciar, antes de abrir nada; el diálogo, que se
crea recién la primera vez que se abre, muestra lo restaurado. A diferencia del
visualizador, el ecualizador **sí** es una propiedad del `MediaPlayer` en
sí (no de la `Instance`), así que no necesita ninguna recreación especial
al cambiar de pista.

## Validación

`tests/test_equalizer.py` aplica cada preset contra libVLC real y compara
preamp y bandas con los de libVLC, cambia bandas y recrea el `Instance`
después (lo que antes fallaba), y prueba el diálogo y la restauración.
`tests/test_app_smoke.py::test_equalizer_dialog_builds_without_error`
construye el diálogo real contra un VLC real (sin pantalla, plataforma Qt
`offscreen`) y confirma que no lanza excepciones. No se verificó
auditivamente que cada banda modifique el sonido de forma audible — la
correctitud de esa parte descansa en `vlc.AudioEqualizer`, no en código de
este proyecto.

`tests/test_equalizer.py` también comprueba los pasos de 0,1 dB: los
campos numéricos y los sliders se mueven juntos y el valor llega exacto a
libVLC (antes los sliders eran de dB enteros y redondeaban los presets,
que usan pasos de 0,8 dB).
