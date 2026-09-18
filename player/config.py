"""Configuracion persistente del usuario (API keys, etc.). Modulo puro,
sin VLC ni Qt. Vive en el home del usuario -- nunca en el repositorio, para
no arriesgar subir un secreto a git por accidente."""

import json
from pathlib import Path


def config_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "config.json"


def _load() -> dict:
    path = config_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def get_opensubtitles_api_key():
    return _load().get("opensubtitles_api_key")


def set_opensubtitles_api_key(key: str) -> None:
    data = _load()
    data["opensubtitles_api_key"] = key
    _save(data)
