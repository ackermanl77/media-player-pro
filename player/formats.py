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

PLAYLIST_EXTS = {".m3u", ".m3u8"}

# Solo para el texto de ayuda de "Abrir URL": is_url() acepta cualquier
# esquema que libVLC sepa abrir (rtsps, srt, rtp, ftp, smb, mmsh...).
STREAM_SCHEMES = ("http://", "https://", "rtsp://", "rtmp://", "rtmpe://", "mms://", "udp://")


# Cualquier "esquema://" de 2+ letras (http, ftp, dvd, smb...). Exige al
# menos dos letras para no confundir una letra de unidad ("C:\...") con un
# esquema de URL.
_URI_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]+://")


def has_uri_scheme(path: str) -> bool:
    return bool(_URI_SCHEME_RE.match(path))


def is_url(path: str) -> bool:
    """True para cualquier "esquema://" salvo file: (que es una ruta local).
    Antes solo se reconocian 7 esquemas fijos: rtsps://, srt://, rtp://,
    ftp://, smb://, mmsh://... se mandaban a media_new_path (libVLC recibia
    "srt:\\host:9000"), y "ftp://h/x.mp3" contaba como archivo de audio
    local (visualizador, posiciones, marcadores)."""
    return has_uri_scheme(path) and not path.lower().startswith("file:")


def is_playlist_file(path: str) -> bool:
    return not is_url(path) and os.path.splitext(path)[1].lower() in PLAYLIST_EXTS


def looks_like_url(text: str) -> bool:
    """Para precargar "Abrir URL" desde el portapapeles: una sola linea con
    esquema://algo."""
    text = text.strip()
    return bool(text) and "\n" not in text and is_url(text) and len(text) > len(text.split("://", 1)[0]) + 3


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


_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:[.,]\d+)?)$")


def parse_time_input(text: str, length_ms: int = 0):
    """"Ir a tiempo": "1:02:03", "12:34", "95" (segundos), "12:34.5" o
    "40%" (de la duracion). Devuelve ms (recortado a la duracion si se
    conoce) o None si el texto no es valido."""
    text = (text or "").strip().replace(" ", "")
    if not text:
        return None
    if text.endswith("%"):
        try:
            percent = float(text[:-1].replace(",", "."))
        except ValueError:
            return None
        if length_ms <= 0 or not 0 <= percent <= 100:
            return None
        return int(length_ms * percent / 100)
    match = _TIME_RE.match(text)
    if match:
        hours, minutes, seconds = match.groups()
        if hours is not None and int(minutes) >= 60:
            return None
        if float(seconds.replace(",", ".")) >= 60:
            return None
        total = int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds.replace(",", "."))
    else:
        try:
            total = float(text.replace(",", "."))
        except ValueError:
            return None
        if total < 0:
            return None
    ms = int(round(total * 1000))
    if length_ms > 0:
        ms = min(ms, length_ms)
    return ms


def snapshot_file_name(media_path: str, time_ms: int) -> str:
    """<nombre>_<hh-mm-ss.mmm>.png para la captura rapida."""
    if is_url(media_path):
        stem = urllib.parse.urlparse(media_path).netloc or "stream"
    else:
        stem = os.path.splitext(os.path.basename(media_path))[0] or "captura"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or "captura"
    time_ms = max(0, int(time_ms))
    seconds, millis = divmod(time_ms, 1000)
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{stem}_{hours:02d}-{minutes:02d}-{seconds:02d}.{millis:03d}.png"


def format_rate(rate: float) -> str:
    """1.0 -> "1,0×", 1.25 -> "1,25×"."""
    text = f"{rate:.2f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return text.replace(".", ",") + "×"
