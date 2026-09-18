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
carpeta...** (agrega recursivamente todo lo soportado dentro), o **Abrir
URL...** (streams HTTP(S)/RTSP/RTMP/MMS/UDP). Arrastrar y soltar archivos o
carpetas sobre la ventana también funciona.

## Controles

| Acción | Cómo |
|---|---|
| Reproducir / Pausar | Botón central o tecla `Espacio` |
| Detener | Botón de stop |
| Siguiente / Anterior | Botones o `Ctrl+→` / `Ctrl+←` |
| Buscar (seek) | Arrastrar la barra de progreso, o `→`/`←` para ±5s |
| Volumen | Slider, o `↑`/`↓` |
| Silenciar | Botón, o tecla `M` |
| Velocidad de reproducción | Combo (0.5x a 2.0x) |
| Pantalla completa | Doble clic sobre el video, botón, o tecla `F` |
| Salir de pantalla completa | `Esc` |
| Captura de fotograma | Menú Video → Capturar fotograma... |
| Zoom de video | Menú Video → Zoom (Ajustar a ventana/50%/100%/150%/200%) |
| Siempre visible (encima de otras ventanas) | Menú Video → "Siempre visible..." (checkbox) |
| Repetición A-B (bucle de un tramo) | Botón "A-B" — ver [docs/workflows/ab-loop/workflow.md](../ab-loop/workflow.md) |

Ninguno de los controles de la barra roba el foco de teclado
(`Qt.FocusPolicy.NoFocus`), así que los atajos de arriba funcionan sin
importar en qué botón se haya hecho clic antes — ver la entrada
correspondiente en `docs/PROJECT_STATUS.md` → "Recently Fixed".

Al reabrir un archivo local ya visto, la reproducción retoma
automáticamente donde había quedado — ver
[docs/workflows/resume-playback/workflow.md](../resume-playback/workflow.md).

## Manejo de errores

Si un archivo no se puede decodificar (códec no soportado, archivo
corrupto), la barra de estado muestra "No se pudo reproducir: `<archivo>`"
durante 5 segundos y la reproducción avanza automáticamente a la siguiente
pista de la playlist, igual que al terminar una pista normalmente.

## Validación

- Verificado con un video sintético generado con OpenCV (círculo animado,
  MP4) y un tono senoidal (WAV) generado con el módulo `wave` de la
  librería estándar: reproducción, pausa, barra de progreso y transición
  automática de una pista a otra funcionan tanto ejecutando desde el
  código fuente como desde el `.exe` empaquetado.
- `tests/test_backend.py` cubre el caso de una ruta con `/` (ver
  "Recently Fixed" en `docs/PROJECT_STATUS.md`), que antes dejaba la
  reproducción colgada para siempre sin ningún error.
