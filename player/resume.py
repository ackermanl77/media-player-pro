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
    """{clave -> {position_ms?, audio_track?, subtitle_track?}}, en orden de
    guardado (el mas reciente al final). Acepta el formato viejo
    {clave -> ms} y lo migra en memoria al nuevo esquema por archivo."""
    raw = load_json(positions_file(), dict, {})
    data = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        entry = _normalize_entry(value)
        if entry:
            data[path_key(key)] = entry
    return data


def _save_all(data: dict) -> None:
    overflow = len(data) - MAX_SAVED_POSITIONS
    if overflow > 0:
        for key in list(data)[:overflow]:
            del data[key]
    save_json(positions_file(), data)


def get_saved_position_ms(path: str):
    entry = _load_all().get(path_key(path), {})
    return entry.get("position_ms")


def get_saved_track_selection(path: str) -> tuple[int | None, int | None]:
    entry = _load_all().get(path_key(path), {})
    return entry.get("audio_track"), entry.get("subtitle_track")


def save_track_selection(path: str, audio_track: int | None, subtitle_track: int | None) -> None:
    _save_entry_fields(path, audio_track=audio_track, subtitle_track=subtitle_track)


def save_position(path: str, position_ms: int, length_ms: int) -> None:
    if length_ms <= 0:
        return
    if position_ms < RESUME_THRESHOLD_START_MS or position_ms >= length_ms * RESUME_THRESHOLD_END_FRACTION:
        clear_position(path)
        return
    _save_entry_fields(path, position_ms=int(position_ms))


def clear_position(path: str) -> None:
    data = _load_all()
    key = path_key(path)
    if key in data and "position_ms" in data[key]:
        data[key] = dict(data[key])
        del data[key]["position_ms"]
        if not data[key]:
            del data[key]
        _save_all(data)


def _normalize_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _normalize_entry(value) -> dict:
    if (position_ms := _normalize_int(value)) is not None:
        return {"position_ms": position_ms}
    if not isinstance(value, dict):
        return {}
    entry = {}
    for field in ("position_ms", "audio_track", "subtitle_track"):
        normalized = _normalize_int(value.get(field))
        if normalized is not None:
            entry[field] = normalized
    return entry


def _save_entry_fields(path: str, **fields) -> None:
    data = _load_all()
    key = path_key(path)
    entry = dict(data.get(key, {}))
    for field, value in fields.items():
        normalized = _normalize_int(value)
        if normalized is None:
            entry.pop(field, None)
        else:
            entry[field] = normalized
    data.pop(key, None)  # reinsertar al final: la entrada vuelve a ser la mas reciente
    if entry:
        data[key] = entry
    _save_all(data)
