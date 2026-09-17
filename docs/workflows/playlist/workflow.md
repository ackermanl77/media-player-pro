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
