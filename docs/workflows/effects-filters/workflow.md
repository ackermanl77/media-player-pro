# Efectos de audio, tono y filtros de video

## Goal

Ajustar cómo suena y cómo se ve lo que se reproduce con los filtros que ya
trae libVLC: un compresor para escuchar de noche, un estéreo más ancho,
sonido envolvente virtual para auriculares, el tono sin cambiar la
velocidad, y filtros de nitidez, ruido, bandas y bloques para video de baja
calidad.

## Uso

**Audio → Efectos** (casillas, combinables):

- **Modo nocturno (compresor)**: sube lo bajo y baja lo fuerte, para
  diálogos que se entienden sin que las explosiones despierten a nadie.
- **Ampliar estéreo**: separa más los canales izquierdo y derecho.
- **Auriculares: sonido envolvente virtual**: mezcla un audio multicanal
  para auriculares.
- **Tono**: de −6 a +6 semitonos ("Original" = sin cambio). La velocidad
  no cambia.

**Video → Filtros** (casillas, combinables): **Enfocar**, **Reducir
ruido**, **Suavizar bandas de color** y **Quitar bloques (posprocesado)**.

Todo se recuerda entre sesiones. Ampliar estéreo y el sonido envolvente se
aplican en vivo; el modo nocturno, el tono y los filtros de video recargan
el archivo en el mismo punto (pausado o reproduciendo, igual que antes).

## Cómo funciona por dentro

`player/window_effects.py::EffectsMixin` arma los menús con las listas de
`player/video_options.py` (`AUDIO_EFFECTS`, `PITCH_STEPS`, `VIDEO_FILTERS`).
En `VLCPlayer` (`player/backend.py`):

- `set_audio_effects()` fija la cadena `audio-filter` del reproductor en
  vivo (`audio_filter_chain()`, junto con el normalizador). El compresor
  necesita además parámetros de instancia (`NIGHT_MODE_ARGS`: ratio 6,
  umbral −24 dB) y el tono es la opción de instancia `--pitch-shift` del
  módulo `scaletempo_pitch` (`audio_effect_instance_args()`): esos dos
  recrean el `Instance` conservando el estado. Si libVLC rechaza esas
  opciones, el grupo "audio_effects" se descarta y el reproductor sigue.
- `set_video_filters()` usa la misma opción `--video-filter` que la
  rotación (`video_filter_instance_args()`: libVLC solo lee la última, así
  que van juntas), con `postproc` en calidad 6.

Se guardan en `settings.json` como `audio_effects`, `pitch` y
`video_filters`.

## Validación

`tests/test_competitor_features.py`:

- `test_libvlc_accepts_every_new_option`: un libVLC real acepta cada opción.
- `test_audio_effects_build_the_chain_and_their_instance_options` y
  `test_rotation_and_video_filters_share_one_video_filter_option`: la
  cadena y las opciones que se arman.
- `test_effects_change_the_live_chain_and_pitch_needs_a_new_instance`: qué
  se aplica en vivo y qué recrea el `Instance`.
- `test_effects_and_filters_survive_a_restart` y
  `test_the_menus_offer_the_new_sources_effects_and_filters`: persistencia
  y menús.

No se comprobó de oído ni a la vista con medios reales cuánto cambia cada
filtro: eso depende de los módulos de libVLC.
