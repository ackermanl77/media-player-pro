"""Extensiones de audio/video soportadas (todo lo que libVLC es capaz de decodificar)."""

import os

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
