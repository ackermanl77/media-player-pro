# Historial de cambios

Los cambios importantes de Reproductor Multimedia Pro. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones,
[Semantic Versioning](https://semver.org/lang/es/).

## [Sin publicar]

### Agregado
- Efectos de audio y tono, filtros de video, abrir discos, carpetas compartidas y servidores
  UPnP/DLNA, convertir y grabar.
- Línea de subtítulo anterior/siguiente, superposición de estadísticas, botones de miniatura
  de la barra de tareas, rotar y voltear el video.
- Videos de páginas web con yt-dlp (opcional), reproducir en Chromecast, passthrough de audio
  a un receptor, controles multimedia de Windows y atajos de teclado editables.
- Comprobación de versión nueva una vez por arranque, contra los GitHub Releases del proyecto (update.json).
- Auditoría de dependencias (`pip-audit`) en CI y Dependabot.
- Licencia MIT, `SECURITY.md` y una sección de privacidad en el README.

### Cambiado
- Tema Sistema legible con Windows en modo oscuro, y un ícono nuevo.
- Botones de transporte alcanzables con el teclado.

### Corregido
- Conversiones y descargas de subtítulos más robustas.

## [0.2.0] - 2026-10-06

### Agregado
- Firma de código del .exe, el instalador y el desinstalador.
- Mover los puntos A-B y repetir entre marcadores; retrasos de audio y subtítulos recordados
  por archivo; mensajes en pantalla repetidos en la barra de estado y para lectores de
  pantalla; escaneo de carpetas en segundo plano.
- Build en carpeta con instalador de Inno Setup y VLC incluido opcional, con sus licencias.
- Releases desde etiquetas de Git, con la versión estampada en el .exe.

### Cambiado
- La lista de reproducción pasó a modelo/vista de Qt; el backend y la ventana principal se
  reorganizaron.

## [0.1.0] - 2026-09-18

- Primera versión: reproducción de audio y video con libVLC, lista de reproducción,
  ecualizador, subtítulos (también desde OpenSubtitles), pantalla completa y miniaturas al
  pasar sobre la barra.
