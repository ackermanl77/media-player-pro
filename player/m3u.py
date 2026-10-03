"""Lectura/escritura de listas .m3u/.m3u8. Modulo puro, sin VLC ni Qt."""

import os
import shutil
import tempfile
import time
from pathlib import Path

from .formats import has_uri_scheme, normalize_path


def decode_playlist_bytes(data: bytes) -> str:
    """UTF-8 (con o sin BOM) primero -- .m3u8 siempre lo es y la mayoria de
    los .m3u modernos tambien. Si no es UTF-8 valido, cp1252 (lo que
    escriben Winamp/foobar/el propio Windows para .m3u "ANSI"), y latin-1
    como ultimo recurso (nunca falla). A diferencia de errors="ignore", no
    se pierden en silencio letras acentuadas de las rutas."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_m3u(data: bytes, playlist_path: str) -> list:
    """Entradas de la lista, ya normalizadas: las rutas relativas se
    resuelven contra la carpeta del propio .m3u (no contra el directorio de
    trabajo del proceso), los "file:///" pasan a ruta local y cualquier otra
    URL se deja tal cual."""
    base_dir = os.path.dirname(os.path.abspath(playlist_path))
    entries = []
    for line in decode_playlist_bytes(data).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.lower().startswith("file:") and not has_uri_scheme(line):
            if not os.path.isabs(line):
                line = os.path.join(base_dir, line)
        entries.append(normalize_path(line))
    return entries


def format_m3u(entries) -> str:
    return "#EXTM3U\n" + "".join(f"{e}\n" for e in entries)


def playlist_backup_path(path: str | os.PathLike[str]) -> Path:
    path = Path(path)
    return path.with_name(path.name + ".bak")


def load_playlist(path: str | os.PathLike[str]) -> list:
    for candidate in (Path(path), playlist_backup_path(path)):
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        try:
            return parse_m3u(data, str(candidate))
        except ValueError:
            continue
    return []


def save_playlist(path: str | os.PathLike[str], entries) -> bool:
    text = format_m3u(entries)
    path = Path(path)
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copyfile(path, playlist_backup_path(path))
        _replace_with_retry(tmp_name, path)
        tmp_name = None
        return True
    except OSError:
        return False
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _replace_with_retry(src: str, dst: Path, attempts: int = 5) -> None:
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)
