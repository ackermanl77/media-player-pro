# Lista de Reproducción

## Goal

Organizar varios archivos o un stream en una cola reproducible, con
aleatorio/repetir, y poder guardar/recuperar esa cola como un archivo
`.m3u` estándar.

## Uso

- **Agregar contenido**: Archivo → Abrir archivos/carpeta/URL, arrastrar y
  soltar sobre la ventana, la línea de comandos, "Abrir reciente" o un
  `.m3u`/`.m3u8`. Si no sonaba nada, el primer elemento agregado se
  reproduce. "Abrir carpeta" se recorre en segundo plano
  (`player/folder_scan.py`): la barra de estado cuenta lo encontrado y
  Archivo → "Cancelar escaneo de carpeta" lo detiene y agrega lo
  encontrado hasta ese momento; las carpetas arrastradas o pasadas por
  línea de comandos se expanden al momento. Cada fila muestra un ícono según su tipo (🎵 audio, 🎬 video,
  🌐 stream/URL); la duración y las etiquetas ("Artista — Título") se leen
  en segundo plano (`MediaInfoProbe`, de a 4 archivos) y el título del
  panel muestra la cantidad y el total. Una radio muestra el título ICY
  que anuncia.
- **Elemento en reproducción**: marcado con ▶ y en negrita, independiente
  de la selección (hacer clic en otra fila no lo pierde).
- **Reproducir un elemento**: doble clic o Enter sobre él en el panel
  "Lista de reproducción" (dock a la derecha, Ver → Mostrar lista).
- **Reordenar**: arrastrar una o varias filas seleccionadas a otra
  posición (también con el buscador activo: se suelta antes/después de la
  fila visible bajo el mouse). El aleatorio, la fila que suena y la de la
  sesión siguen apuntando a las mismas pistas.
- **Buscar**: Ctrl+F con la lista enfocada (o el campo de arriba) filtra
  por texto o ruta; Enter reproduce la primera coincidencia, Esc borra el
  texto.
- **Menú contextual** (clic derecho): Reproducir, Quitar de la lista
  (todos los seleccionados si se hizo clic sobre la selección), Mostrar en
  el Explorador, Copiar ruta, Ordenar por nombre/ruta (orden natural),
  Quitar entradas no disponibles, Vaciar lista.
- **Guardar / cargar**: Archivo → "Guardar lista (.m3u8)..." / "Cargar
  lista...". `.m3u8` UTF-8 con cabecera `#EXTM3U` y rutas relativas a la
  carpeta de la lista cuando se puede; al cargar se aceptan también
  ANSI/cp1252 y `file:///`. El guardado es atómico (temporal + fsync +
  reemplazo) y deja la versión anterior como `.bak`, a la que recurre la
  carga si la lista quedó dañada.
- **Sesión**: la lista y el elemento que sonaba se guardan al cerrar (y
  1 s después de cada cambio) y se restauran al abrir; ese elemento queda
  seleccionado y Reproducir lo retoma (Archivo → "Recordar la lista al
  cerrar").
- **Aleatorio**: baraja la lista una vez (sin reemplazo: cada pista suena
  una sola vez por vuelta, ver `player/playlist_order.py::PlaylistOrder`).
  Con Repetir: No la reproducción termina al agotar la vuelta (y dispara
  "Al terminar la lista"); con Repetir: Todo se baraja una vuelta nueva sin
  repetir de inmediato la última. "Anterior" recorre el historial real de
  lo que sonó. Agregar pistas las intercala entre las pendientes; quitar
  pistas las saca del orden.
- **Quitar el elemento que suena**: se detiene, y Siguiente/Reproducir
  siguen con el que ocupó su lugar (no vuelven al primero).
- **Teclado en la lista**: con la lista enfocada, flecha arriba/abajo
  mueven la selección (no el volumen), Enter reproduce, Supr quita todos
  los seleccionados.
- **Archivos que no se pueden reproducir** se saltan con un aviso en la
  barra de estado, incluso con Repetir: Uno; si falla una vuelta completa
  seguida, se detiene en vez de reintentar para siempre.
- **Repetir**: botón de repetir (o Reproducción → Repetir), cicla entre
  No / Todo / Uno.

## Estructura del código

Modelo/vista de Qt:

- `player/playlist_model.py`: `PlaylistModel` (`QAbstractListModel`: ruta
  e id estable por fila, duración/etiquetas/título ICY, texto con ▶ y
  negrita de la fila actual), `PlaylistFilterProxy` (filtro del buscador)
  y `PlaylistView` (`QListView` con `InternalMove`; al soltar emite
  `rowsDropped(filas, destino)` en filas del modelo fuente, en vez de dejar
  que Qt mueva los datos a través del proxy).
- `player/playlist_controller.py`: `PlaylistController` une modelo, filtro
  y `PlaylistOrder` (agregar/quitar/mover/ordenar/vaciar, fila actual y
  de la sesión), lee los metadatos en segundo plano y arma el título del
  panel. Emite `contentsChanged` (MainWindow guarda la sesión con
  debounce) y `summaryChanged` (título del dock).
- `MainWindow` solo abre archivos, muestra diálogos y el menú contextual,
  y detiene lo que suena antes de quitarlo.

## Acción al terminar la lista

Menú **Reproducción → "Al terminar la lista"**: Nada (por defecto), Salir
del programa, o —solo en Windows— Apagar el equipo / Hibernar / Reiniciar
(inspirado en el flag `-sdown` de BS.Player). Se dispara únicamente cuando
la lista termina de forma natural, sin repetir (`repeat_mode == "all"` la
desactiva de hecho, ya que la lista nunca "termina" en ese modo).
Apagar/Hibernar/Reiniciar muestran primero una **cuenta regresiva de 60 s**
en un diálogo encima de todo (`player/power.py`), con "Cancelar" como
botón por defecto y un botón para hacerlo ya; al terminar ejecuta
`shutdown /s /t 0`, `shutdown /h` o `shutdown /r /t 0`. La elección nunca
se guarda entre sesiones y vuelve a "Nada" después de usarse.

## Comportamiento de "Anterior"

Si ya pasaron más de 3 segundos de la pista actual, "Anterior" reinicia
esa misma pista en vez de saltar a la de antes (comportamiento estándar de
reproductores de música).

## Validación

`tests/test_playlist_model.py` (sin VLC) cubre el modelo, el filtro, el
arrastre traducido a filas fuente (también con el buscador activo),
ordenar, quitar (fila actual, de la sesión, aleatorio) y los metadatos en
segundo plano con un analizador falso. `tests/test_p2_features.py` y
`tests/test_playback_fixes.py` lo ejercitan sobre la ventana real
(arrastre, buscador, duraciones reales leídas de `.wav`, Enter/Supr en la
lista, quitar la fila que suena). **El arrastre con el mouse en sí no se
puede simular en las pruebas** (Qt `offscreen`, sin eventos de mouse
sintéticos): se prueba el mismo camino que usa `dropEvent`
(`PlaylistView.handle_internal_drop`); verificarlo a mano en la app.

Verificado manualmente (antes del cambio a modelo/vista): agregar dos
archivos (uno de audio, uno de video)
por línea de comandos y confirmar que, al terminar el primero, la
reproducción avanza automáticamente al segundo (título de la ventana
actualizado); ejercitado también en
`tests/test_app_smoke.py::test_playlist_and_ui_wiring_smoke`.

`tests/test_on_finish_action.py` parchea `subprocess.run` para verificar
que cada acción espera la cuenta regresiva y arma exactamente el comando
de Windows esperado (`shutdown /s /t 0`, `/h`, `/r /t 0`), que cancelar no
ejecuta nada y que "ahora" se salta la espera, **sin ejecutar nunca un
apagado o reinicio real** durante la suite. `tests/test_folder_scan.py`
cubre el escaneo en segundo plano (orden de los lotes, cancelación) y
`tests/test_inputs.py`/`test_persistence.py` el guardado atómico con
`.bak`. Verificado además en vivo end-to-end:
una playlist de una sola pista de 5s con `on_finish_action = "exit"`
cierra la aplicación exactamente cuando el video termina (medido por
cuándo retorna `app.exec()`), confirmando que el disparo real (fin de la
pista → fin de playlist) llega hasta `_handle_playlist_finished()` y no
solo la llamada directa al método (verificado antes del paso a eventos de
libVLC).
