"""Tiempos de las lineas de un subtitulo externo (4.15): Alt+Arriba/Abajo
saltan al inicio de la linea anterior/siguiente.

libVLC 3 no expone los tiempos de las pistas SPU, asi que se leen del propio
archivo: SRT, WebVTT y ASS/SSA (los formatos de texto con tiempos absolutos;
MicroDVD .sub cuenta fotogramas y necesitaria los fps, y no se soporta).
Modulo puro, sin VLC ni Qt."""

import os
import re
from bisect import bisect_left, bisect_right

from .m3u import decode_playlist_bytes

MAX_SUBTITLE_BYTES = 20 * 1024 * 1024
# "Anterior" dentro del primer segundo de una linea va a la linea previa;
# despues, vuelve al inicio de la actual (como "Pista anterior").
PREVIOUS_GRACE_MS = 1000
# Un salto deja la reproduccion justo en el inicio: "siguiente" no debe
# volver a elegir la linea en la que acaba de caer.
NEXT_MIN_AHEAD_MS = 50

# 00:01:02,345 / 00:01:02.345 / 01:02.345 (WebVTT sin horas)
_TIMESTAMP = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
_ARROW_LINE = re.compile(rf"^\s*{_TIMESTAMP}\s*-->\s*{_TIMESTAMP}")
# Dialogue: 0,0:00:01.23,0:00:03.45,Default,... (ASS) o Marked=0,... (SSA)
_ASS_DIALOGUE = re.compile(r"^\s*Dialogue:\s*[^,]*,\s*(\d+):(\d{2}):(\d{2})[.:](\d{1,3})\s*,"
                           r"\s*(\d+):(\d{2}):(\d{2})[.:](\d{1,3})")

SUPPORTED_EXTENSIONS = (".srt", ".vtt", ".ass", ".ssa")


def _ms(hours, minutes, seconds, fraction) -> int:
    # "5" son 500 ms, "05" 50 ms y "005" 5 ms (ASS usa centesimas).
    frac_ms = int(fraction.ljust(3, "0")[:3])
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + frac_ms


def parse_cues(text: str, extension: str) -> list:
    """[(inicio_ms, fin_ms)] ordenados por inicio, sin inicios repetidos
    (varias lineas a la vez -- p. ej. dos hablantes en ASS -- son un solo
    destino de salto)."""
    extension = extension.lower()
    cues = []
    if extension in (".ass", ".ssa"):
        for line in text.splitlines():
            match = _ASS_DIALOGUE.match(line)
            if match:
                g = match.groups()
                cues.append((_ms(*g[0:4]), _ms(*g[4:8])))
    elif extension in (".srt", ".vtt"):
        for line in text.splitlines():
            match = _ARROW_LINE.match(line)
            if match:
                g = match.groups()
                cues.append((_ms(*g[0:4]), _ms(*g[4:8])))
    seen = set()
    unique = []
    for start, end in sorted(cues):
        if start not in seen:
            seen.add(start)
            unique.append((start, end))
    return unique


def load_cue_starts(path: str) -> list:
    """Inicios (ms) de las lineas del archivo, o [] si no es un formato
    soportado, es demasiado grande o no se puede leer."""
    extension = os.path.splitext(path)[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        return []
    try:
        if os.path.getsize(path) > MAX_SUBTITLE_BYTES:
            return []
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    return [start for start, _end in parse_cues(decode_playlist_bytes(data), extension)]


def adjacent_cue_time(starts: list, time_ms: int, direction: int, delay_ms: int = 0):
    """Tiempo del video al que saltar para la linea anterior (direction < 0)
    o siguiente (> 0), o None si no hay. `delay_ms` es el retardo de
    subtitulos actual: una linea que empieza en t se ve en t + delay_ms."""
    shown = [start + delay_ms for start in starts]
    if direction > 0:
        index = bisect_right(shown, time_ms + NEXT_MIN_AHEAD_MS - 1)
        return shown[index] if index < len(shown) else None
    index = bisect_left(shown, time_ms - PREVIOUS_GRACE_MS) - 1
    # Con un retardo negativo la primera linea puede "verse" antes de 0:00.
    return max(0, shown[index]) if index >= 0 else None
