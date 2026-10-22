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
2. Python 3.10+ (probado con 3.12 y 3.14)
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
- Reproducción de streams de red: cualquier esquema que libVLC sepa abrir
  (HTTP(S), RTSP/RTSPS, RTMP(S), SRT, RTP, UDP, MMS/MMSH, FTP, SMB...).
  "Abrir URL" toma la dirección del portapapeles si parece una URL y permite
  ajustar la **caché de red** y **RTSP por TCP** (se recuerdan). Muestra
  "Almacenando en búfer… N %", una franja translúcida en la barra con lo
  ya almacenado delante de la posición (streams con duración; es el llenado
  de la caché de red de libVLC), "EN VIVO" en streams sin duración (y
  desactiva la barra de búsqueda), el título que anuncia una radio por
  internet, reconecta streams HTTP cortados, y si un stream no responde en
  15 s ofrece Reintentar / Saltar / Seguir esperando. Una URL de solo audio
  activa el visualizador una vez abierta.
- Lista de reproducción con arrastrar y soltar (archivos, carpetas completas
  en orden natural —"Pista 2" antes que "Pista 10"— y listas `.m3u`/`.m3u8`,
  también desde la línea de comandos), **reordenable arrastrando**, con
  **buscador** (Ctrl+F; Enter reproduce la primera coincidencia), el
  elemento en reproducción marcado con ▶ en negrita, duración y etiquetas
  ("Artista — Título") leídas en segundo plano, y el total en el título del
  panel. Menú contextual: Mostrar en el Explorador, Copiar ruta, Ordenar por
  nombre/ruta, Quitar entradas no disponibles. Quitar el elemento que suena
  y pulsar Siguiente sigue con el que ocupó su lugar. Guardar/cargar como
  `.m3u8`/`.m3u` (rutas relativas a la carpeta de la lista, UTF-8 o
  ANSI/cp1252, `file:///`; se guarda de forma atómica, con una copia
  `.bak` de la anterior). Selección múltiple para quitar varios.
- **Abrir carpeta** la recorre en segundo plano: la ventana sigue
  respondiendo, la barra de estado muestra "Escaneando carpeta… N archivos
  encontrados" y Archivo → "Cancelar escaneo de carpeta" la detiene
  (lo encontrado hasta ese momento se agrega igual). Lo mismo con las
  carpetas arrastradas, pasadas por línea de comandos o reenviadas por otra
  instancia (un segundo escaneo espera a que termine el primero).
- **Una sola ventana**: abrir un archivo con el programa ya abierto lo manda
  a esa ventana (Archivo → "Permitir varias ventanas" o `--new-window` para
  desactivarlo; `--enqueue` solo lo agrega a la lista).
- Control de posición (clic en la barra salta ahí, con cualquier estilo),
  volumen (hasta 150 %, también con la rueda sobre el video), mute,
  velocidad de reproducción (0,25×–4×, botón "1,0×" con su menú y teclas
  `[` `]` `=`), aleatorio (cada pista una vez por vuelta; "Anterior" sigue el
  historial real) y repetir (ninguno/todo/uno). Un archivo que no se puede
  reproducir se salta (también con Repetir uno); tras una vuelta completa
  sin nada reproducible, se detiene.
- Selección de pista de audio y de subtítulos, carga de subtítulos externos
  (`.srt`, `.ass`, `.ssa`, `.sub`, `.vtt`). La pista de audio y la de
  subtítulos elegidas se **recuerdan por archivo** y se vuelven a elegir
  al reabrirlo.
- Ecualizador gráfico de 10 bandas más preamplificador (−20 a +20 dB, en
  **pasos de 0,1 dB**: cada banda tiene su slider y un campo numérico) con
  los presets de VLC (en español: Plano, Clásica, Rock, Pop, ...).
- **Audio → Efectos**: **Modo nocturno** (compresor: sube lo bajo y baja
  lo fuerte), **Ampliar estéreo** y **Auriculares: sonido envolvente
  virtual**, combinables, y **Tono** de −6 a +6 semitonos sin cambiar la
  velocidad (se recuerdan). **Video → Filtros**: Enfocar, Reducir ruido,
  Suavizar bandas de color y Quitar bloques (posprocesado), también
  combinables. Son los filtros que trae libVLC.
- **Normalizar volumen** (Audio): baja solo los pasajes muy fuertes, en
  vivo y junto con el ecualizador. **Dispositivo de salida** (Audio): elegir
  por qué altavoces/auriculares suena (se recuerda).
- **Imagen** (Video): **Relación de aspecto** (`A` la cambia), **Recortar**
  (`C`; 16:9, 4:3, 2,35:1...), **Desentrelazado** (Automático, Desactivado,
  Blend, Bob, Lineal, X, Yadif, Yadif 2x; se recuerda) y **Ajustes de video**
  (`Ctrl+E`: brillo, contraste, saturación, tono y gamma, en vivo; se recuerdan).
- **Información del medio** (`Ctrl+I`): archivo, tamaño, duración, etiquetas
  y cada pista (códec, resolución, cuadros/s, canales, frecuencia, bitrate,
  idioma), con un botón para copiarla.
- **Capítulos** de MKV/MP4: menú Reproducción → Capítulos, `RePág`/`AvPág`,
  rayas azules en la barra y el nombre del capítulo en la vista previa.
- **Sincronía de audio** (A/V): `J`/`K` ±50 ms, con OSD.
- Captura de fotograma de video a PNG ("Capturar fotograma..." con diálogo,
  o **Captura rápida** `Ctrl+Shift+S` a `Imágenes\Reproductor Multimedia Pro`).
- **Mejora por GPU** (Windows, menú Video): Superresolución (RTX Video /
  Intel) y HDR a partir de SDR (RTX Video HDR), más el modo de
  decodificación por hardware. Desactivados por defecto; si tu VLC no los
  admite, se desmarcan solos con un aviso.
- Tema **Sistema / Oscuro / Claro** (menú Ver) e iconos propios.
- Menú contextual sobre el video (clic derecho) y **Ayuda → Atajos de
  teclado** (`F1`), generado de los atajos reales y **editable**: elige una
  acción, pulsa la combinación nueva y «Asignar»; también «Quitar»,
  «Predeterminado» y «Restaurar todos». Un atajo que ya usa otra acción no se
  asigna (se avisa cuál). Se guardan en `settings.json`.
- **Discos y red** (menú Archivo): **Abrir disco** (`Ctrl+D`: DVD, Blu-ray
  con sus menús, o CD de audio, de una unidad; se puede elegir título), **Abrir carpeta
  compartida** (SMB, NFS, SFTP o FTP; la contraseña solo se usa mientras el
  programa está abierto, nunca se guarda) y **Explorar la red local**
  (servidores UPnP/DLNA: carpetas y archivos que se agregan a la lista).
- **Convertir / extraer audio** (`Ctrl+R`, menú Archivo): recodifica un
  archivo a MP4 (H.264), MKV (H.265), MP3, Ogg o FLAC en segundo plano, con
  progreso, sin cortar lo que suena. **Grabar** (`Shift+R`, menú
  Reproducción): guarda lo que se reproduce (un stream en vivo, por ejemplo)
  en un `.ts`, sin recodificar, en `Videos\Reproductor Multimedia Pro`.
- **Videos de páginas web** (YouTube, Vimeo, Twitch, archive.org…): con
  [yt-dlp](https://github.com/yt-dlp/yt-dlp) instalado (`winget install
  yt-dlp` o `pip install yt-dlp`; no se incluye con el programa), «Abrir URL»
  con la página de un video lo reproduce hasta 1080p, con su título en la
  lista. Sin yt-dlp, esas URL van directo a VLC como antes.
- **Reproducción → Reproducir en**: busca Chromecast (y compatibles) en la
  red local y envía la reproducción a uno, siguiendo desde el mismo punto;
  «Esta PC» la trae de vuelta.
- **Audio → Passthrough**: envía el audio comprimido sin decodificar (AC3 y
  DTS, o también E-AC3, TrueHD y DTS-HD) a un receptor o barra de sonido por
  HDMI/S/PDIF, si el dispositivo de salida lo admite.
- **Video → Rotar / voltear**: gira el video 90° a la derecha o a la
  izquierda o 180°, o lo voltea horizontal o verticalmente (por ejemplo, un
  video de celular grabado de costado). Se aplica a los archivos siguientes
  hasta volver a «Sin rotar».
- **Teclas multimedia y panel multimedia de Windows**: las teclas
  Reproducir/Pausa, Siguiente, Anterior y Detener (y los botones de
  auriculares Bluetooth) manejan el reproductor aunque su ventana no tenga el
  foco, y Windows muestra el título y los botones en el panel multimedia
  (junto al volumen) y en la pantalla de bloqueo. Al pasar el mouse por el
  botón del programa en la barra de tareas, la vista previa tiene los botones
  Anterior, Reproducir/Pausar y Siguiente.
- Pantalla completa (doble clic sobre el video o tecla `F`). En pantalla
  completa siguen funcionando todos los atajos de los menús, la barra de
  estado se oculta (sus mensajes aparecen en el OSD), un controlador propio
  (título, tiempos, barra grande y los botones principales) y el OSD se ven
  encima del video, y el cursor se oculta tras ~2,5 s sin mover el mouse.
- **Lectores de pantalla**: los mensajes del OSD (que es una ventana
  superpuesta que no leen) también van a la barra de estado y se envían como
  aviso accesible (Qt 6.8+), así NVDA/Narrador anuncian volumen, saltos,
  sincronía, A-B, etc.
- Vista previa en miniatura al pasar el mouse por la barra (solo videos
  locales; en audio y streams muestra solo el tiempo), con caché.
- **Recuerda los ajustes y la lista entre sesiones**: volumen, silencio,
  velocidad, repetir/aleatorio, visualizador, tamaño de subtítulos, zoom,
  "Siempre visible", ecualizador (activado, preset y valores), tamaño y
  posición de la ventana, el panel de la lista y la última carpeta usada
  (`~/.reproductor_multimedia_pro/settings.json`). La lista de reproducción
  y el elemento actual se restauran al abrir, **sin reproducir solos**
  (Reproducir retoma ese elemento, en la posición guardada); se puede
  desactivar en Archivo → "Recordar la lista al cerrar"
  (`session.json`). "Al terminar la lista" (apagar/hibernar/reiniciar)
  nunca se recuerda. Archivos pasados por línea de comandos se agregan al
  final de la lista restaurada y suena el primero de ellos.
- **Registro de errores**: `%LOCALAPPDATA%\ReproductorMultimediaPro\logs\app.log`
  (rotativo, 5 × 1 MB) más `crash.log` para cierres nativos; un error
  inesperado muestra un aviso no bloqueante (como mucho uno por minuto).
  Ayuda → "Abrir carpeta de registros". `python run.py --debug` registra
  con más detalle.
- **Recuerda la posición de reproducción** de cada archivo local entre
  sesiones (al estilo BS.Player): reabrir un video/audio ya visto retoma
  donde quedó (también al pulsar Detener o quitarlo de la lista).
  Reproducir tras Detener o tras terminar la lista vuelve a arrancar la
  pista actual.
- **Repetición A-B**: marca un punto A y un punto B para poner en bucle
  solo ese tramo — con el botón A-B (cicla A → B → desactivar), el menú
  Reproducción o los atajos `Ctrl+Shift+A` (punto A), `Ctrl+Shift+B`
  (punto B) y `Ctrl+Shift+L` (limpiar); `Alt+Shift+←/→` y
  `Ctrl+Shift+←/→` mueven A y B de a 0,1 s, y "Bucle entre marcadores"
  repite el tramo entre los marcadores que rodean la posición.
- **Sincronía de subtítulos** ajustable en vivo (±50 ms, tecla `G`/`H`) y
  **tamaño de subtítulos** (Pequeño/Normal/Grande/Muy grande). `Alt+↑` /
  `Alt+↓` saltan al inicio de la línea anterior / siguiente de un subtítulo
  externo (para repetir una frase).
- **Estadísticas de reproducción** (tecla `I`, menú Video): códec,
  resolución, tasa de bits y fotogramas perdidos sobre el video.
- **Zoom de video** (Ajustar a ventana/50%/100%/150%/200%) y modo
  **"Siempre visible"** (encima de otras ventanas).
- **Acción al terminar la lista** (menú Reproducción): Nada, Salir del
  programa, o en Windows también Apagar el equipo / Hibernar / Reiniciar
  — como el `-sdown` de BS.Player. Las tres muestran una **cuenta regresiva
  de 60 s** encima de todo, con "Cancelar" como botón por defecto; la
  acción elegida vuelve a "Nada" después.
- **Búsqueda y descarga de subtítulos online** (menú Video → "Buscar
  subtítulos online..."), vía la API de OpenSubtitles — requiere tu
  propia API key gratuita, ver [Requisitos](#requisitos) más abajo. Idiomas
  configurables (se recuerdan), conserva la extensión del subtítulo, pregunta
  antes de reemplazar uno existente y muestra las descargas restantes del
  día. Un subtítulo que termina de bajar cuando ya suena otro archivo se
  guarda para cuando se vuelva a abrir el original.
- **Marcadores nombrados por archivo** (menú Reproducción): guarda varios
  puntos con nombre por archivo (no solo uno automático), para saltar
  directo a una escena — tecla `B` para agregar uno rápido en la posición
  actual, "Ver marcadores..." para administrarlos (ir a / renombrar /
  eliminar).

## Atajos de teclado

La lista completa está en Ayuda → Atajos de teclado (`F1`).

| Tecla            | Acción                     |
|------------------|----------------------------|
| Espacio          | Reproducir / Pausar        |
| S                | Detener                    |
| F / doble clic   | Pantalla completa          |
| Esc              | Salir de pantalla completa |
| Ctrl+O / Ctrl+U  | Abrir archivos / Abrir URL |
| Ctrl+D           | Abrir disco                |
| Ctrl+R / Shift+R | Convertir / Grabar         |
| Ctrl+Flecha der./izq. | Pista siguiente / anterior |
| Flecha der./izq. | Adelantar/retroceder 5 s   |
| Mayús+Flecha     | ±1 s                       |
| Alt+Flecha       | ±30 s                      |
| Ctrl+Alt+Flecha  | ±60 s                      |
| Inicio           | Volver al inicio           |
| Ctrl+G           | Ir a tiempo (`h:mm:ss`, `mm:ss`, segundos o `%`) |
| RePág / AvPág    | Capítulo anterior / siguiente |
| `[` / `]` / `=`  | Más lenta / más rápida / velocidad normal |
| Flecha arr./abajo| Subir/bajar volumen (con la lista enfocada: moverse por la lista) |
| Rueda / Ctrl+Rueda sobre el video | Volumen / buscar ±5 s |
| Teclas multimedia | Reproducir/Pausar, Detener, Siguiente, Anterior |
| Enter (en la lista) | Reproducir el elemento  |
| Supr (en la lista)  | Quitar los seleccionados |
| Ctrl+F (en la lista) | Buscar en la lista      |
| M                | Silenciar                  |
| J / K            | Adelantar / retrasar audio 50 ms |
| G / H            | Adelantar / retrasar subtítulos 50 ms |
| Alt+Arriba / Alt+Abajo | Línea de subtítulo anterior / siguiente |
| I                | Estadísticas de reproducción |
| B                | Agregar marcador aquí      |
| Ctrl+Shift+A / B / L | Marcar punto A / punto B / limpiar bucle A-B |
| .                | Avanzar un fotograma (en pausa) |
| Ctrl+Shift+S     | Captura rápida             |
| A / C            | Siguiente relación de aspecto / recorte |
| Ctrl+E / Ctrl+I  | Ajustes de video / Información del medio |
| F1               | Atajos de teclado          |

## Desarrollo

Ejecutar las pruebas:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

`tests/conftest.py` redirige `Path.home()` y `%LOCALAPPDATA%` a carpetas
temporales para todas las pruebas: la suite nunca toca tus ajustes reales.
Última corrida (2026-10-22, Windows 11, Python 3.14, libVLC 3.0.23): 406
passed, 1 skipped; `tests/test_visualizer.py::test_visualizer_enabled_produces_a_video_output_for_audio`
falla de forma intermitente en esta máquina (ver docs/PROJECT_STATUS.md).
`tests/test_formats.py` no depende de VLC ni de Qt. `tests/test_app_smoke.py`
construye la ventana real (con la plataforma Qt `offscreen`, sin necesitar
pantalla) y se omite automáticamente si no hay VLC instalado.

Generar la app de Windows con PyInstaller (carpeta "onedir":
`dist/ReproductorMultimediaPro/ReproductorMultimediaPro.exe`; ya no un único
.exe que se descomprimía en cada arranque) y su instalador por usuario con
Inno Setup 6 (`dist/installer/`, sin permisos de administrador; registra el
programa en "Abrir con" con el verbo "Agregar a la lista"):

```bash
pip install -r requirements-build.txt -c constraints.txt
pyinstaller --noconfirm ReproductorMultimediaPro.spec
iscc /DAppVersion=0.1.0 installer\ReproductorMultimediaPro.iss
```

Para firmar (Authenticode) el `.exe`, el instalador y su desinstalador, en
lugar del `iscc` de arriba: `set CODESIGN_THUMBPRINT=<huella SHA-1>` (un
certificado de firma de código del almacén de Windows) y
`python packaging/sign_and_package.py`. Usa signtool del Windows SDK y sella
con `CODESIGN_TIMESTAMP_URL` (por defecto DigiCert).

VLC no se incluye por defecto: la máquina destino necesita VLC 3.0 de 64
bits instalado (si falta, o es de 32 bits, la app lo explica al arrancar).
Opcionalmente, `BUNDLE_VLC=1` (y `VLC_DIR` si VLC no está en la ruta
estándar) copia libVLC y un `plugins/` recortado dentro del paquete; la app
lo usa si está y si no cae al VLC del sistema. Las licencias (GPL/LGPL de
VLC) y el enlace al código fuente de la versión incluida están en
[licenses/](licenses/THIRD_PARTY_NOTICES.txt); el build con `BUNDLE_VLC=1` las
copia a `_internal\licenses\` y el instalador siempre las instala en
`licenses\` junto al `.exe`. Si cambias la versión
de VLC que empaquetas, actualiza el enlace del tarball en ese archivo.

La versión vive solo en `player/__init__.py` (`__version__`):
`pyproject.toml`, el recurso de versión del `.exe` (Propiedades → Detalles,
generado por `packaging/version_resource.py`) y el instalador la toman de
ahí. Para publicar: subir `__version__`, y luego `git tag v<versión>` +
`git push origin v<versión>`; `.github/workflows/release.yml` corre todas
las pruebas, construye la carpeta, la comprime en un `.zip`, arma el
instalador y los adjunta (con `SHA256SUMS.txt`) a un GitHub Release.

`requirements.txt` solo tiene lo necesario para ejecutar; `pytest` está en
`requirements-dev.txt` y PyInstaller en `requirements-build.txt`.
`constraints.txt` fija las versiones probadas para builds reproducibles.

## Documentación

Para arquitectura, entry points, estado de la release, problemas
conocidos e historial detallado de bugs encontrados y arreglados, ver
[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md). Guías por función (cómo
usar cada cosa y cómo se verificó) en
[docs/workflows/](docs/workflows/README.md).

## Notas

- Si al iniciar aparece un error indicando que no se encuentra `libvlc`, el
  mensaje dice si falta VLC o si está instalado el de 32 bits; instala VLC 3.0
  de la misma arquitectura (64 bits) que el programa.
- El motor libVLC gestiona automáticamente los códecs; no es necesario
  instalar codecs adicionales para formatos poco comunes.
