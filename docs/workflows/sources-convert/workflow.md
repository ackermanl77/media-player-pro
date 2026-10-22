# Discos, recursos compartidos, red local, convertir y grabar

## Goal

Abrir lo que no es un archivo local (un DVD, Blu-ray o CD de audio, una
carpeta de un NAS, un servidor DLNA de la casa), convertir un archivo a
otro formato o extraer su audio, y grabar lo que se está reproduciendo.

## Uso

Menú **Archivo**:

- **Abrir disco (DVD, Blu-ray, CD)...** (`Ctrl+D`): elegir la unidad, el
  tipo de disco y, si se quiere, el título por el que empezar ("Desde el
  principio (o el menú)" por defecto). Un DVD se abre con sus menús.
- **Abrir carpeta compartida (SMB, NFS, SFTP, FTP)...**: protocolo,
  servidor, carpeta, usuario y contraseña. También acepta una ruta
  `\\nas\carpeta`. La contraseña solo se usa mientras el programa está
  abierto: no se guarda ni aparece en la lista, la sesión o los recientes.
- **Explorar la red local (UPnP/DLNA)...**: muestra los servidores
  multimedia que se anuncian en la red; abrir uno muestra sus carpetas, y
  los archivos elegidos se agregan a la lista.
- **Convertir / extraer audio...** (`Ctrl+R`): un archivo de origen, un
  perfil — Video MP4 (H.264 + AAC), Video MKV (H.265 + AAC, más pequeño),
  Solo audio MP3 (192 kbps), Solo audio Ogg Vorbis o Solo audio FLAC (sin
  pérdida) — y el archivo de destino. Corre en segundo plano con barra de
  progreso y Cancelar, sin cortar lo que suena.

Menú **Reproducción → Grabar** (`Shift+R`): guarda lo que se reproduce
(típicamente un stream en vivo) en un `.ts`, sin recodificar, en
`Videos\Reproductor Multimedia Pro\<título> <fecha>.ts`. Se detiene al
volver a pulsarlo o al cambiar de pista; la barra de estado dice dónde
quedó.

## Cómo funciona por dentro

- `player/sources.py`: `disc_mrl()` (`dvd://`, `bluray://`, `cdda://`),
  `optical_drives()` (unidades de CD/DVD con `GetDriveTypeW`),
  `share_url()` (la URL **sin** contraseña) y `share_media_options()` (las
  credenciales como opciones del `Media`: `:smb-pwd=`…).
  `VLCPlayer.set_share_credentials()` las tiene solo en memoria y las
  aplica a los `Media` de ese servidor.
- `player/sources_dialog.py`: `OpenDiscDialog`, `OpenShareDialog` y
  `NetworkBrowserDialog`, que usa el media discoverer `upnp` de libVLC y
  lee su lista con un `QTimer`.
- `player/converter.py`: `PROFILES`, `transcode_sout()` (la cadena
  `#transcode{...}:std{...}`) y `ConvertJob`, que convierte en un
  `vlc.Instance` aparte; `record_sout()` arma
  `#duplicate{dst=display,dst=std{access=file,mux=ts,...}}`, que
  `VLCPlayer.set_recording()` agrega al próximo `Media` (recarga lo que
  suena en el mismo punto).
- `player/window_sources.py::SourcesMixin` cablea los menús y diálogos.

## Validación

`tests/test_competitor_features.py`:

- `test_disc_mrls`, `test_share_urls_never_carry_the_password`,
  `test_share_credentials_reach_only_that_servers_media` y
  `test_the_disc_and_share_dialogs_build_their_addresses`.
- `test_sout_chains_and_output_names` y `test_a_real_conversion_to_mp3`
  (una conversión real con libVLC de `tests/assets/chapters.mkv`).
- `test_recording_adds_a_duplicate_sout_to_the_next_media`.

Falta probarlo a mano con un disco real, un recurso SMB/NFS/SFTP real, un
servidor DLNA de la red (en la red de prueba no había ninguno) y la
grabación de un stream en vivo.
