# Repetición A-B

Inspirado en BS.Player: repetir en bucle solo un tramo del archivo actual
(útil para estudiar un pasaje musical o una frase en otro idioma).

## Uso

Botón **"Bucle A-B"** en la barra de controles (o Reproducción → "Bucle
A-B"), cicla en tres clics:

1. Primer clic: marca el punto A en el tiempo actual de reproducción — el
   OSD muestra `Punto A: MM:SS` y el tooltip del botón lo recuerda.
2. Segundo clic: marca el punto B (debe ser posterior a A) — el OSD
   muestra `A-B: MM:SS-MM:SS`, el botón queda marcado y el tramo empieza a
   repetirse en bucle.
3. Tercer clic: limpia A y B, vuelve a reproducción normal.

También con atajos (y entradas propias en el menú Reproducción):
`Ctrl+Shift+A` marca (o vuelve a marcar) el punto A, `Ctrl+Shift+B` el
punto B y `Ctrl+Shift+L` limpia el bucle.

Si se intenta marcar B en un punto anterior o igual a A, se ignora y
aparece un aviso en la barra de estado.

Cambiar de pista (siguiente/anterior/doble clic en la playlist) limpia
automáticamente cualquier A-B activo — los puntos de un archivo no tienen
sentido en otro.

Mientras A y/o B están marcados, aparecen como líneas naranjas sobre la
barra de progreso (ver "marcadores visuales" más abajo), así no hay que
recordar de memoria dónde quedaron.

## Cómo funciona por dentro

`MainWindow.loop_point_a`/`loop_point_b` (en ms, o `None`). Mientras hay
un bucle activo corre un temporizador propio de precisión de 50 ms
(`_ab_timer`, `AB_LOOP_TICK_MS`; antes era el tick de 250 ms de
`update_ui()`), que comprueba si la posición pasó de `loop_point_b` y, si
es así, llama a `player.set_time_ms(loop_point_a)`. Fuera del bucle el
temporizador está detenido.

`PositionSlider` (subclase de `QSlider` en `player/widgets.py`) pinta los
puntos A/B como líneas naranjas en `paintEvent()`, a partir de las
fracciones `loop_point_a/length` y `loop_point_b/length`; los marcadores
se recalculan cuando cambian (pista, bucle, marcadores, capítulos)
(junto con los marcadores nombrados — ver
[docs/workflows/bookmarks/workflow.md](../bookmarks/workflow.md)).

## Validación

Verificado en vivo contra un video real de 12s: marcar A en ~0.4s y B en
~1.4s, forzar el tiempo por encima de B, y confirmar que `update_ui()`
efectivamente hace volver la reproducción a A en el siguiente tick.
También: marcar A y B más un marcador nombrado y confirmar que
`position_slider._markers` termina con exactamente 3 entradas, en las
fracciones y el color (naranja para A/B) esperados.
