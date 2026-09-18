# Repetición A-B

Inspirado en BS.Player: repetir en bucle solo un tramo del archivo actual
(útil para estudiar un pasaje musical o una frase en otro idioma).

## Uso

Botón **"A-B"** en la barra de controles, cicla en tres clics:

1. Primer clic: marca el punto A en el tiempo actual de reproducción — el
   botón muestra `A: MM:SS`.
2. Segundo clic: marca el punto B (debe ser posterior a A) — el botón
   muestra `A-B: MM:SS-MM:SS` y el tramo empieza a repetirse en bucle.
3. Tercer clic: limpia A y B, vuelve a reproducción normal.

Si se intenta marcar B en un punto anterior o igual a A, se ignora y
aparece un aviso en la barra de estado.

Cambiar de pista (siguiente/anterior/doble clic en la playlist) limpia
automáticamente cualquier A-B activo — los puntos de un archivo no tienen
sentido en otro.

## Cómo funciona por dentro

`MainWindow.loop_point_a`/`loop_point_b` (en ms, o `None`). `update_ui()`
(el mismo timer de 250 ms que ya actualiza la barra de progreso) comprueba
en cada tick si la posición actual pasó de `loop_point_b`; si es así,
llama a `player.set_time_ms(loop_point_a)`. No requiere nada especial del
backend de VLC — solo `set_time_ms`, que ya existía.

## Validación

Verificado en vivo contra un video real de 12s: marcar A en ~0.4s y B en
~1.4s, forzar el tiempo por encima de B, y confirmar que `update_ui()`
efectivamente hace volver la reproducción a A en el siguiente tick.
