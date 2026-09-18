# Búsqueda y Descarga de Subtítulos Online

Inspirado en BS.Player (que integraba opensubtitles.org/getsubtitles.com
directamente en el reproductor).

## Requisito: API key propia

Esta función usa la [API REST de OpenSubtitles](https://opensubtitles.com/en/consumers)
(`api.opensubtitles.com`). **Necesitas tu propia API key gratuita** — la
app no trae ninguna incluida ni la puede generar por ti (crear la cuenta
en opensubtitles.com es algo que solo tú puedes hacer). La primera vez que
uses **Video → "Buscar subtítulos online..."** sin una key configurada, se
te pedirá con un diálogo y se guarda en
`~/.reproductor_multimedia_pro/config.json` (fuera del repositorio, nunca
se sube a git).

## Uso

**Menú Video → "Buscar subtítulos online..."**. Solo funciona con
archivos locales (no con streams por URL). Al abrir el diálogo:

1. Busca automáticamente por el hash del archivo (el mismo algoritmo que
   usa BS.Player y muchos otros reproductores: tamaño + suma de los
   primeros/últimos 64KB) — solo funciona en archivos de 128KB o más.
2. Si el hash no da resultados (archivo chico, o simplemente no hay match
   exacto), busca por el nombre del archivo (limpio de puntos/guiones
   bajos) como texto libre.
3. Los resultados se listan ordenados por número de descargas — normalmente
   una buena señal de calidad/precisión de sincronía.
4. Selecciona uno y "Descargar y usar": se guarda junto al video (mismo
   nombre + `.<idioma>.srt`) o, si esa carpeta no es escribible, en una
   carpeta temporal — y se carga inmediatamente sobre el video actual.

Toda llamada de red corre en un `QThread` separado, así que la interfaz no
se congela mientras busca o descarga.

## Privacidad

Al buscar, se envía a OpenSubtitles: el hash calculado del archivo (no el
archivo en sí) y/o el nombre del archivo como texto de búsqueda. Al
descargar, se hace una petición HTTP normal al enlace que devuelve la API.
No se envía nada más (ni la ruta completa, ni metadatos del sistema).

## Validación

`tests/test_opensubtitles.py` (9 tests) cubre el algoritmo de hash con
vectores construidos a mano (un archivo de ceros, un archivo con bytes
conocidos en los bordes, un archivo demasiado chico) y el parseo de
respuestas/manejo de errores de red con `requests.get`/`.post`
reemplazados — **nunca golpea la API real** durante la suite automatizada.

Verificado además en vivo, de punta a punta, contra la API real de
OpenSubtitles (con una API key real): búsqueda por texto ("The Matrix
1999") devolvió 50 resultados reales; descargar el primero produjo un
`.srt` válido con contenido real; y lo mismo repetido a través del
diálogo real (`OnlineSubtitleDialog`, no solo el cliente de
`player/opensubtitles.py` en aislado) confirmó que el archivo descargado
se guarda junto al video y llega hasta `VLCPlayer.load_subtitle_file()`.
