# Reproducción de Audio y Video

## Goal

Reproducir cualquier archivo de audio o video local, o un stream de red,
con la calidad nativa del archivo (sin recompresión), usando el motor de
decodificación de libVLC.

## Uso

```bash
python run.py                              # abre el reproductor vacío
python run.py cancion.mp3 pelicula.mkv     # los agrega a la playlist y reproduce el primero
```

También: menú **Archivo → Abrir archivos...** (multi-selección), **Abrir
carpeta...** (agrega recursivamente todo lo soportado dentro, en orden
natural; se recorre en segundo plano con el progreso en la barra de estado
y se puede cancelar con Archivo → "Cancelar escaneo de carpeta"), o
**Abrir URL...** (`Ctrl+U`: cualquier esquema que libVLC abra —
HTTP(S), RTSP, RTMP, SRT, UDP, MMS...). Arrastrar y soltar archivos,
carpetas o listas `.m3u` sobre la ventana también funciona.

En un stream de red con duración conocida (un video por HTTP, no una
radio en vivo), una franja translúcida sobre la barra de progreso muestra
lo que libVLC ya tiene almacenado delante de la posición actual. libVLC no
expone qué parte del archivo ya se descargó: la franja es lo que sabe, el
llenado de su caché de red (`:network-caching`, ajustable en Abrir URL)
según los eventos `Buffering`, así que mide como mucho el tamaño de esa
caché (1 s por defecto) y vuelve a crecer desde la posición tras una
búsqueda.

## Controles

| Acción | Cómo |
|---|---|
| Reproducir / Pausar | Botón central o tecla `Espacio` |
| Detener | Botón de stop o tecla `S` |
| Siguiente / Anterior | Botones o `Ctrl+→` / `Ctrl+←` |
| Buscar (seek) | Clic o arrastre en la barra de progreso; `→`/`←` ±5 s, `Mayús` ±1 s, `Alt` ±30 s, `Ctrl+Alt` ±60 s; `Ctrl+G` ir a tiempo |
| Volumen | Slider (hasta 150 %), `↑`/`↓` o la rueda sobre el video |
| Silenciar | Botón, o tecla `M` |
| Velocidad de reproducción | Botón "1,0×" con su menú (0,25× a 4×), o `[` / `]` / `=` |
| Pantalla completa | Doble clic sobre el video, botón, o tecla `F` |
| Salir de pantalla completa | `Esc` |
| Captura de fotograma | Menú Video → Capturar fotograma..., o `Ctrl+Shift+S` (captura rápida a `Imágenes\Reproductor Multimedia Pro`) |
| Avanzar un fotograma (en pausa) | Tecla `.` |
| Zoom de video | Menú Video → Zoom (Ajustar a ventana/50%/100%/150%/200%) |
| Siempre visible (encima de otras ventanas) | Menú Video → "Siempre visible..." (checkbox) |
| Repetición A-B (bucle de un tramo) | Botón "Bucle A-B" o `Ctrl+Shift+A` / `B` / `L` — ver [docs/workflows/ab-loop/workflow.md](../ab-loop/workflow.md) |

La lista completa, generada de los atajos reales, está en Ayuda → Atajos
de teclado (`F1`).

Ninguno de los controles de la barra roba el foco de teclado
(`Qt.FocusPolicy.NoFocus`), así que los atajos de arriba funcionan sin
importar en qué botón se haya hecho clic antes — ver la entrada
correspondiente en `docs/PROJECT_STATUS.md` → "Recently Fixed".

Al reabrir un archivo local ya visto, la reproducción retoma
automáticamente donde había quedado — ver
[docs/workflows/resume-playback/workflow.md](../resume-playback/workflow.md).

## Manejo de errores

Si un archivo no se puede decodificar (códec no soportado, archivo
corrupto o inexistente), se avisa "No se pudo reproducir: `<archivo>`" y
la reproducción avanza automáticamente a la siguiente pista de la
playlist (también con Repetir: Uno). Si una vuelta completa de la lista
falla seguida, se detiene en vez de reintentar para siempre.

## Validación

- Verificado con un video sintético generado con OpenCV (círculo animado,
  MP4) y un tono senoidal (WAV) generado con el módulo `wave` de la
  librería estándar: reproducción, pausa, barra de progreso y transición
  automática de una pista a otra funcionan tanto ejecutando desde el
  código fuente como desde el `.exe` empaquetado.
- `tests/test_backend.py` cubre el caso de una ruta con `/` (ver
  "Recently Fixed" en `docs/PROJECT_STATUS.md`), que antes dejaba la
  reproducción colgada para siempre sin ningún error.
