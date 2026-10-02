"""Configuracion persistente del usuario (API keys, etc.). Modulo puro,
sin VLC ni Qt. Vive en el home del usuario -- nunca en el repositorio, para
no arriesgar subir un secreto a git por accidente."""

from pathlib import Path

from .jsonstore import load_json, save_json


def config_file() -> Path:
    return Path.home() / ".reproductor_multimedia_pro" / "config.json"


def _load() -> dict:
    return load_json(config_file(), dict, {})


def _save(data: dict) -> None:
    save_json(config_file(), data)


def get_opensubtitles_api_key():
    key = _load().get("opensubtitles_api_key")
    return key if isinstance(key, str) else None


def set_opensubtitles_api_key(key: str) -> None:
    data = _load()
    data["opensubtitles_api_key"] = key
    _save(data)


def get_subtitle_languages() -> str:
    """Idiomas para buscar subtitulos online ("es,en" por defecto)."""
    from .opensubtitles import DEFAULT_LANGUAGES, normalize_languages

    return normalize_languages(_load().get("subtitle_languages")) or DEFAULT_LANGUAGES


def set_subtitle_languages(languages: str) -> str:
    """Guarda los idiomas (normalizados); devuelve lo que quedo guardado."""
    from .opensubtitles import DEFAULT_LANGUAGES, normalize_languages

    value = normalize_languages(languages) or DEFAULT_LANGUAGES
    data = _load()
    data["subtitle_languages"] = value
    _save(data)
    return value
