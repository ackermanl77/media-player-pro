"""Extensiones de audio/video soportadas (todo lo que libVLC es capaz de decodificar)."""

import os
import re
import urllib.parse
import urllib.request

AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".oga", ".m4a", ".wma", ".opus",
    ".ape", ".aiff", ".aif", ".alac", ".dsf", ".dff", ".mid", ".midi",
    ".amr", ".ac3", ".dts", ".mka", ".tak", ".tta", ".wv", ".spx", ".caf",
    ".au", ".ra",
}

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mpg",
    ".mpeg", ".m4v", ".3gp", ".3g2", ".ts", ".m2ts", ".mts", ".vob",
    ".ogv", ".rm", ".rmvb", ".asf", ".divx", ".f4v", ".mxf", ".mpe",
    ".mp2", ".mpv", ".qt", ".webm",
}

ALL_EXTS = AUDIO_EXTS | VIDEO_EXTS

STREAM_SCHEMES = ("http://", "https://", "rtsp://", "rtmp://", "rtmpe://", "mms://", "udp://")


def is_url(path: str) -> bool:
    return path.lower().startswith(STREAM_SCHEMES)


# Cualquier "esquema://" de 2+ letras (http, ftp, dvd, smb...). Exige al
# menos dos letras para no confundir una letra de unidad ("C:\...") con un
# esquema de URL.
_URI_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]+://")


def has_uri_scheme(path: str) -> bool:
    return bool(_URI_SCHEME_RE.match(path))


def file_uri_to_path(uri: str) -> str:
    r"""Convierte "file:///C:/Musica/a%20b.mp3" en "C:\Musica\a b.mp3" (o
    "/home/x/a b.mp3" fuera de Windows). Un host distinto de localhost se
    trata como ruta UNC ("file://servidor/share/x" -> "\\servidor\share\x")."""
    parsed = urllib.parse.urlparse(uri)
    local = urllib.request.url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        local = os.sep * 2 + parsed.netloc + os.sep + local.lstrip("\\/")
    return local


def normalize_path(path: str) -> str:
    r"""Forma canonica de una entrada de la playlist: las rutas locales pasan
    a absolutas con separadores nativos (QFileDialog da "C:/...", open_folder
    mezclaba "C:/dir\sub\f.mkv", la linea de comandos da "C:\..." o rutas
    relativas); un "file://" se convierte en ruta local; cualquier otra URL
    se deja intacta. Conserva mayusculas/minusculas (es lo que se muestra al
    usuario) -- para comparar/usar como clave, ver path_key()."""
    if path.lower().startswith("file:"):
        path = file_uri_to_path(path)
    elif has_uri_scheme(path):
        return path
    return os.path.abspath(path)


def path_key(path: str) -> str:
    r"""Clave estable para guardar datos por archivo (posiciones, marcadores,
    recientes): normalize_path() + os.path.normcase(), asi "C:/X/a.mkv",
    "c:\x\A.MKV" y "C:\X\a.mkv" son el mismo archivo en Windows (en Linux
    normcase no toca nada, igual que el sistema de archivos). Las URLs se
    devuelven sin cambios."""
    normalized = normalize_path(path)
    if has_uri_scheme(normalized):
        return normalized
    return os.path.normcase(normalized)


def is_audio_file(path: str) -> bool:
    """True solo para archivos locales cuya extensión es de audio puro (no
    video, no streams: para esos la presencia de video no se puede saber por
    extensión, así que se dejan sin visualizador)."""
    if is_url(path):
        return False
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


def _pattern(exts):
    return " ".join(f"*{e}" for e in sorted(exts))


def build_open_filter() -> str:
    return (
        f"Todos los medios soportados ({_pattern(ALL_EXTS)});;"
        f"Archivos de audio ({_pattern(AUDIO_EXTS)});;"
        f"Archivos de video ({_pattern(VIDEO_EXTS)});;"
        f"Todos los archivos (*.*)"
    )


def format_time(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_seconds = ms // 1000
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
