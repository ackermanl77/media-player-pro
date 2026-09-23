"""Lista de archivos/URLs abiertos recientemente (mas reciente primero,
deduplicada, con tope), al estilo BS.Player. Modulo puro, mismo patron que
player/resume.py y player/bookmarks.py: sin VLC ni Qt."""

import json
from pathlib import Path

MAX_RECENT_FILES = 20


def recent_files_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "recent_files.json"


def _load_all() -> list:
    path = recent_files_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save_all(paths: list) -> None:
    path = recent_files_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(paths), encoding="utf-8")


def get_recent_files() -> list:
    """Lista de rutas/URLs, mas reciente primero."""
    return _load_all()


def add_recent_file(path: str) -> None:
    """Agrega (o mueve al frente, si ya estaba) una entrada. Se recorta a
    MAX_RECENT_FILES, descartando las mas viejas."""
    if not path:
        return
    paths = _load_all()
    if path in paths:
        paths.remove(path)
    paths.insert(0, path)
    del paths[MAX_RECENT_FILES:]
    _save_all(paths)


def clear_recent_files() -> None:
    _save_all([])
