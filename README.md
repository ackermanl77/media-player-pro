# Reproductor Multimedia Pro

Reproductor de música y video de alta calidad escrito en Python. Usa **libVLC**
(el mismo motor de decodificación de VLC) a través de `python-vlc`, por lo que
reproduce prácticamente cualquier formato de audio o video existente —comunes
y poco comunes— sin recomprimir ni degradar la señal, con aceleración por
hardware cuando el sistema la soporta.

## Requisitos

1. **VLC media player** instalado en el sistema (aporta `libvlc.dll` / `libvlc.so`).
   Descárgalo de https://www.videolan.org/vlc/ — en Windows, instala la versión
   de **64 bits** si usas Python de 64 bits (lo más habitual).
2. Python 3.9+
3. Dependencias de Python:

```bash
pip install -r requirements.txt
```

4. **Opcional** — para buscar/descargar subtítulos online: una API key
   gratuita de [opensubtitles.com](https://www.opensubtitles.com/en/consumers)
   (creas tu propia cuenta, no es necesaria para el resto de la app). La
   primera vez que uses "Buscar subtítulos online..." te la pedirá y la
   guarda en `~/.reproductor_multimedia_pro/config.json` (nunca en el
   repositorio ni en ningún archivo del proyecto).

## Ejecutar

```bash
python run.py
```

En Windows, si prefieres que no aparezca la ventana de consola detrás del
reproductor, haz doble clic en `run.pyw` (o ejecútalo con `pythonw run.py`).

## Funciones

- Reproduce audio y video en un mismo reproductor, con la calidad nativa del
  archivo (sin recodificar).
- Formatos de audio: MP3, WAV, FLAC, AAC, OGG/Opus, M4A, WMA, APE, ALAC, AIFF,
  DSD (DSF/DFF), MIDI, AMR, AC3, DTS, TAK, TTA, WavPack y más.
- Formatos de video: MP4, MKV, AVI, MOV, WMV, FLV, WebM, MPEG-TS/M2TS, VOB,
  OGV, RM/RMVB, 3GP, ASF, MXF y más — incluyendo pistas de audio y subtítulos
  múltiples embebidas (típico de MKV).
- Reproducción de streams de red: HTTP(S), RTSP, RTMP, MMS, UDP.
- Lista de reproducción con arrastrar y soltar (archivos o carpetas completas),
  guardar/cargar como `.m3u`.
- Control de posición, volumen (hasta 150 %), mute, velocidad de reproducción
  (0.5x–2x), aleatorio y repetir (ninguno/todo/uno).
- Selección de pista de audio y de subtítulos, carga de subtítulos externos
  (`.srt`, `.ass`, `.ssa`, `.sub`, `.vtt`).
- Ecualizador gráfico de 10 bandas con presets de VLC (Clásica, Rock, Pop, ...).
- Captura de fotograma de video a PNG.
- Pantalla completa (doble clic sobre el video o tecla `F`).
- **Recuerda la posición de reproducción** de cada archivo local entre
  sesiones (al estilo BS.Player): reabrir un video/audio ya visto retoma
  donde quedó.
- **Repetición A-B**: marca un punto A y un punto B para poner en bucle
  solo ese tramo.
- **Sincronía de subtítulos** ajustable en vivo (±50 ms, tecla `G`/`H`) y
  **tamaño de subtítulos** (Pequeño/Normal/Grande/Muy grande).
- **Zoom de video** (Ajustar a ventana/50%/100%/150%/200%) y modo
  **"Siempre visible"** (encima de otras ventanas).
- **Acción al terminar la lista** (menú Reproducción): Nada, Salir del
  programa, o en Windows también Apagar el equipo / Hibernar / Reiniciar
  — como el `-sdown` de BS.Player. Apagar/Reiniciar dan 60s antes de
  ejecutarse (cancelable con `shutdown /a`); Hibernar es inmediato.
- **Búsqueda y descarga de subtítulos online** (menú Video → "Buscar
  subtítulos online..."), vía la API de OpenSubtitles — requiere tu
  propia API key gratuita, ver [Requisitos](#requisitos) más abajo.

## Atajos de teclado

| Tecla            | Acción                     |
|------------------|----------------------------|
| Espacio          | Reproducir / Pausar        |
| F                | Pantalla completa          |
| Esc              | Salir de pantalla completa |
| Ctrl+O           | Abrir archivos             |
| Ctrl+U           | Abrir URL                  |
| Ctrl+Flecha der. | Siguiente pista            |
| Ctrl+Flecha izq. | Pista anterior             |
| Flecha der./izq. | Adelantar/retroceder 5 s   |
| Flecha arr./abajo| Subir/bajar volumen        |
| M                | Silenciar                  |
| G                | Adelantar subtítulos 50 ms |
| H                | Retrasar subtítulos 50 ms  |

## Desarrollo

Ejecutar las pruebas:

```bash
python -m pytest -q
```

`tests/test_formats.py` no depende de VLC ni de Qt. `tests/test_app_smoke.py`
construye la ventana real (con la plataforma Qt `offscreen`, sin necesitar
pantalla) y se omite automáticamente si no hay VLC instalado.

Generar un ejecutable de Windows con PyInstaller (VLC debe seguir instalado
por separado en la máquina destino; no se empaqueta):

```bash
pip install -r requirements-build.txt
pyinstaller ReproductorMultimediaPro.spec
```

## Documentación

Para arquitectura, entry points, estado de la release, problemas
conocidos e historial detallado de bugs encontrados y arreglados, ver
[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md). Guías por función (cómo
usar cada cosa y cómo se verificó) en
[docs/workflows/](docs/workflows/README.md).

## Notas

- Si al iniciar aparece un error indicando que no se encuentra `libvlc`,
  confirma que VLC está instalado y que su arquitectura (32/64 bits) coincide
  con la de tu intérprete de Python.
- El motor libVLC gestiona automáticamente los códecs; no es necesario
  instalar codecs adicionales para formatos poco comunes.
