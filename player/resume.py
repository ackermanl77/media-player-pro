"""Recuerda la posicion de reproduccion de cada archivo local entre sesiones,
al estilo BS.Player. No depende de VLC ni de Qt."""

from pathlib import Path

from .formats import path_key
from .jsonstore import load_json, save_json

# Por debajo de esto, no vale la pena "reanudar" -- prácticamente el inicio.
RESUME_THRESHOLD_START_MS = 3_000

# Por encima de esta fraccion del largo total, se considera "ya lo vi
# completo": la proxima vez empieza de nuevo en vez de reanudar 2 segundos
# antes del final.
RESUME_THRESHOLD_END_FRACTION = 0.97

# Tope de archivos recordados: sin el, positions.json crece para siempre
# (una entrada por cada archivo alguna vez abierto a medias). Se descartan
# los guardados hace mas tiempo.
MAX_SAVED_POSITIONS = 1000


def positions_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "positions.json"


def _load_all() -> dict:
    """{clave -> ms}, en orden de guardado (el mas reciente al final).
    Descarta entradas con tipos invalidos y migra claves viejas (guardadas
    con la ruta tal cual llegaba, antes de path_key()) a su forma
    normalizada."""
    raw = load_json(positions_file(), dict, {})
    data = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool):
            data[path_key(key)] = value
    return data


def _save_all(data: dict) -> None:
    overflow = len(data) - MAX_SAVED_POSITIONS
    if overflow > 0:
        for key in list(data)[:overflow]:
            del data[key]
    save_json(positions_file(), data)


def get_saved_position_ms(path: str):
    return _load_all().get(path_key(path))


def save_position(path: str, position_ms: int, length_ms: int) -> None:
    if length_ms <= 0:
        return
    if position_ms < RESUME_THRESHOLD_START_MS or position_ms >= length_ms * RESUME_THRESHOLD_END_FRACTION:
        clear_position(path)
        return
    data = _load_all()
    key = path_key(path)
    data.pop(key, None)  # re-insertar al final: pasa a ser la mas reciente
    data[key] = int(position_ms)
    _save_all(data)


def clear_position(path: str) -> None:
    data = _load_all()
    key = path_key(path)
    if key in data:
        del data[key]
        _save_all(data)
