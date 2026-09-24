"""Lista de archivos/URLs abiertos recientemente (mas reciente primero,
deduplicada, con tope), al estilo BS.Player. Modulo puro, mismo patron que
player/resume.py y player/bookmarks.py: sin VLC ni Qt."""

from pathlib import Path

from .formats import path_key
from .jsonstore import load_json, save_json

MAX_RECENT_FILES = 20


def recent_files_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "recent_files.json"


def _dedupe(paths: list) -> list:
    r"""Quita entradas no-string y duplicados por path_key() (la misma ruta
    escrita como "C:/x" y "C:\x" es un solo archivo), conservando la
    primera aparicion -- la mas reciente."""
    seen = set()
    result = []
    for p in paths:
        if not isinstance(p, str) or not p:
            continue
        key = path_key(p)
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def _load_all() -> list:
    return _dedupe(load_json(recent_files_file(), list, []))


def _save_all(paths: list) -> None:
    save_json(recent_files_file(), paths)


def get_recent_files() -> list:
    """Lista de rutas/URLs, mas reciente primero."""
    return _load_all()


def add_recent_file(path: str) -> None:
    """Agrega (o mueve al frente, si ya estaba -- comparando por path_key())
    una entrada. Se recorta a MAX_RECENT_FILES, descartando las mas viejas."""
    if not path:
        return
    paths = _dedupe([path] + _load_all())
    del paths[MAX_RECENT_FILES:]
    _save_all(paths)


def clear_recent_files() -> None:
    _save_all([])
