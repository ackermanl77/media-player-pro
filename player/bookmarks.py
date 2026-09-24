"""Marcadores nombrados por archivo, al estilo BS.Player: varios puntos
guardados por archivo (no solo la ultima posicion, ver player/resume.py).
Modulo puro, sin VLC ni Qt."""

from pathlib import Path

from .formats import path_key
from .jsonstore import load_json, save_json


def bookmarks_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "bookmarks.json"


def _valid_entry(entry) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and isinstance(entry.get("position_ms"), int)
        and not isinstance(entry.get("position_ms"), bool)
    )


def _load_all() -> dict:
    """{clave -> [marcadores]}. Descarta entradas con tipos invalidos y
    migra claves viejas (ruta tal cual llegaba) a path_key(), fusionando
    las listas si dos grafias distintas eran el mismo archivo."""
    raw = load_json(bookmarks_file(), dict, {})
    data = {}
    for key, entries in raw.items():
        if not isinstance(key, str) or not isinstance(entries, list):
            continue
        valid = [e for e in entries if _valid_entry(e)]
        if valid:
            merged = data.setdefault(path_key(key), [])
            merged.extend(valid)
            merged.sort(key=lambda b: b["position_ms"])
    return data


def _save_all(data: dict) -> None:
    save_json(bookmarks_file(), data)


def get_bookmarks(path: str) -> list:
    """Lista de {"name", "position_ms"} para ese archivo, ordenada por
    posicion. El indice en esta lista es estable mientras no se llame a
    add/remove/rename entre medio -- son las operaciones que usa la UI."""
    return _load_all().get(path_key(path), [])


def add_bookmark(path: str, name: str, position_ms: int) -> None:
    data = _load_all()
    entries = data.setdefault(path_key(path), [])
    entries.append({"name": name, "position_ms": int(position_ms)})
    entries.sort(key=lambda b: b["position_ms"])
    _save_all(data)


def remove_bookmark(path: str, index: int) -> None:
    data = _load_all()
    key = path_key(path)
    entries = data.get(key, [])
    if not 0 <= index < len(entries):
        return
    del entries[index]
    if entries:
        data[key] = entries
    else:
        data.pop(key, None)
    _save_all(data)


def rename_bookmark(path: str, index: int, new_name: str) -> None:
    data = _load_all()
    entries = data.get(path_key(path), [])
    if not 0 <= index < len(entries):
        return
    entries[index]["name"] = new_name
    _save_all(data)
