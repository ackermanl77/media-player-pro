# Marcadores Nombrados por Archivo

Inspirado en BS.Player (su "edit bookmark window"): varios puntos con
nombre por archivo, a diferencia de
[recordar posición](../resume-playback/workflow.md), que solo guarda un
único punto automático (dónde quedaste la última vez).

## Uso

- **Agregar uno rápido**: tecla `B`, o menú Reproducción → "Agregar
  marcador aquí". Pide un nombre (sugiere "Marcador MM:SS" por defecto) y
  lo guarda en la posición actual.
- **Administrarlos**: menú Reproducción → "Ver marcadores...". Abre un
  diálogo no modal con la lista de marcadores del archivo actual
  (ordenados por posición), y botones: Agregar aquí, Ir a (o doble clic),
  Renombrar, Eliminar.

Solo funciona con archivos locales — un stream por URL no puede tener
marcadores. El diálogo está atado al archivo que estaba cargado cuando se
abrió: cambiar de pista lo cierra automáticamente (los marcadores de un
archivo no tienen sentido mostrados sobre otro).

Cada marcador del archivo actual aparece como una línea dorada sobre la
barra de progreso (recalculadas en cada tick de `update_ui()`, ver
[docs/workflows/ab-loop/workflow.md](../ab-loop/workflow.md) para el
mecanismo de dibujo, compartido con los puntos A/B), sin necesidad de
abrir el diálogo para saber dónde están.

## Dónde viven

`~/.reproductor_multimedia_pro/bookmarks.json` — `{"ruta_absoluta":
[{"name": ..., "position_ms": ...}, ...]}`. Se puede borrar sin riesgo
para resetear todos los marcadores.

## Cómo funciona por dentro

`player/bookmarks.py` es un módulo puro (sin VLC ni Qt):
`get_bookmarks()`, `add_bookmark()` (mantiene la lista ordenada por
posición en cada inserción), `remove_bookmark()`/`rename_bookmark()` (por
índice, sobre la lista ya ordenada que devuelve `get_bookmarks()`).
`player/bookmarks_dialog.py::BookmarksDialog` es la UI, sin lógica de
almacenamiento propia.

## Validación

`tests/test_bookmarks.py` (10 tests, sin VLC/Qt) cubre el orden por
posición, el aislamiento entre archivos distintos, eliminar el último
marcador de un archivo (limpia la entrada por completo en vez de dejar
una lista vacía), un índice fuera de rango como no-op, y un
`bookmarks.json` corrupto tratado como vacío.

Verificado en vivo contra la app real y un video real: agregar dos
marcadores (uno rápido con `quick_add_bookmark()`, otro desde el propio
diálogo), "Ir a" saltó exactamente a la posición guardada (3000 ms),
renombrar y eliminar reflejados correctamente en el diálogo, y confirmar
que `bookmarks_dialog` se limpia (`None`) al pasar por `play_index()` —
el mismo camino que se ejecuta al cambiar de pista.
