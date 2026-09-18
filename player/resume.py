"""Recuerda la posicion de reproduccion de cada archivo local entre sesiones,
al estilo BS.Player. No depende de VLC ni de Qt."""

import json
from pathlib import Path

# Por debajo de esto, no vale la pena "reanudar" -- prácticamente el inicio.
RESUME_THRESHOLD_START_MS = 3_000

# Por encima de esta fraccion del largo total, se considera "ya lo vi
# completo": la proxima vez empieza de nuevo en vez de reanudar 2 segundos
# antes del final.
RESUME_THRESHOLD_END_FRACTION = 0.97


def positions_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "positions.json"


def _load_all() -> dict:
    path = positions_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_all(data: dict) -> None:
    path = positions_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def get_saved_position_ms(path: str):
    return _load_all().get(path)


def save_position(path: str, position_ms: int, length_ms: int) -> None:
    if length_ms <= 0:
        return
    if position_ms < RESUME_THRESHOLD_START_MS or position_ms >= length_ms * RESUME_THRESHOLD_END_FRACTION:
        clear_position(path)
        return
    data = _load_all()
    data[path] = position_ms
    _save_all(data)


def clear_position(path: str) -> None:
    data = _load_all()
    if path in data:
        del data[path]
        _save_all(data)
