"""Marcadores nombrados por archivo, al estilo BS.Player: varios puntos
guardados por archivo (no solo la ultima posicion, ver player/resume.py).
Modulo puro, sin VLC ni Qt."""

import json
from pathlib import Path


def bookmarks_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "bookmarks.json"


def _load_all() -> dict:
    path = bookmarks_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_all(data: dict) -> None:
    path = bookmarks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def get_bookmarks(path: str) -> list:
    """Lista de {"name", "position_ms"} para ese archivo, ordenada por
    posicion. El indice en esta lista es estable mientras no se llame a
    add/remove/rename entre medio -- son las operaciones que usa la UI."""
    return _load_all().get(path, [])


def add_bookmark(path: str, name: str, position_ms: int) -> None:
    data = _load_all()
    entries = data.setdefault(path, [])
    entries.append({"name": name, "position_ms": position_ms})
    entries.sort(key=lambda b: b["position_ms"])
    _save_all(data)


def remove_bookmark(path: str, index: int) -> None:
    data = _load_all()
    entries = data.get(path, [])
    if not 0 <= index < len(entries):
        return
    del entries[index]
    if entries:
        data[path] = entries
    else:
        data.pop(path, None)
    _save_all(data)


def rename_bookmark(path: str, index: int, new_name: str) -> None:
    data = _load_all()
    entries = data.get(path, [])
    if not 0 <= index < len(entries):
        return
    entries[index]["name"] = new_name
    _save_all(data)
