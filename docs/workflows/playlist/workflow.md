# Lista de Reproducción

## Goal

Organizar varios archivos o un stream en una cola reproducible, con
aleatorio/repetir, y poder guardar/recuperar esa cola como un archivo
`.m3u` estándar.

## Uso

- **Agregar contenido**: Archivo → Abrir archivos/carpeta/URL, o arrastrar
  y soltar sobre la ventana. Si la playlist estaba vacía, el primer
  elemento agregado se reproduce automáticamente.
- **Reproducir un elemento específico**: doble clic sobre él en el panel
  "Lista de reproducción" (dock a la derecha, se puede ocultar/mostrar
  desde el menú Ver).
- **Menú contextual** (clic derecho sobre un elemento): Reproducir, Quitar
  de la lista, Vaciar lista.
- **Guardar / cargar**: Archivo → "Guardar lista (.m3u)..." / "Cargar
  lista...". El formato es un `.m3u` plano (una ruta o URL por línea, con
  cabecera `#EXTM3U`), compatible con otros reproductores.
- **Aleatorio**: botón "Aleatorio" en la barra de controles — al pasar a
  la siguiente pista automáticamente, elige una pista distinta a la actual
  al azar en vez de la siguiente en orden.
- **Repetir**: botón "Repetir", cicla entre No / Todo / Uno cada vez que se
  hace clic.

## Acción al terminar la lista

Menú **Reproducción → "Al terminar la lista"**: Nada (por defecto), Salir
del programa, o —solo en Windows— Apagar el equipo / Hibernar / Reiniciar
(inspirado en el flag `-sdown` de BS.Player). Se dispara únicamente cuando
la lista termina de forma natural, sin repetir (`repeat_mode == "all"` la
desactiva de hecho, ya que la lista nunca "termina" en ese modo).
Apagar/Reiniciar usan `shutdown /s|/r /t 60` (60 segundos de margen,
cancelable desde una consola con `shutdown /a`, con el aviso nativo de
Windows); Hibernar (`shutdown /h`) no admite retraso, es inmediato. Esta
opción siempre queda desactivada por defecto — solo actúa si se elige
explícitamente en el menú.

## Comportamiento de "Anterior"

Si ya pasaron más de 3 segundos de la pista actual, "Anterior" reinicia
esa misma pista en vez de saltar a la de antes (comportamiento estándar de
reproductores de música).

## Validación

Verificado manualmente: agregar dos archivos (uno de audio, uno de video)
por línea de comandos y confirmar que, al terminar el primero, la
reproducción avanza automáticamente al segundo (título de la ventana
actualizado); ejercitado también en
`tests/test_app_smoke.py::test_playlist_and_ui_wiring_smoke`.

`tests/test_on_finish_action.py` (5 tests) parchea `subprocess.run` para
verificar que cada acción arma exactamente el comando de Windows esperado
(`shutdown /s /t 60`, `/h`, `/r /t 60`) **sin ejecutar nunca un apagado o
reinicio real** durante la suite. Verificado además en vivo end-to-end:
una playlist de una sola pista de 5s con `on_finish_action = "exit"`
cierra la aplicación exactamente cuando el video termina (medido por
cuándo retorna `app.exec()`), confirmando que el disparo real
(`update_ui` → `State.Ended` → fin de playlist) llega hasta
`_handle_playlist_finished()` y no solo la llamada directa al método.
