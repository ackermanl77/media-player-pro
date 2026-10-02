"""Expansion de lo que el usuario "abre" (linea de comandos, arrastrar y
soltar, Abrir carpeta, otra instancia via single_instance, Cargar lista) a
la lista plana de entradas de la playlist. Modulo puro, sin VLC ni Qt.

Antes cada punto de entrada hacia lo suyo: Abrir carpeta y arrastrar y
soltar copiaban el mismo os.walk (uno ordenaba con sort() sensible a
mayusculas, el otro no ordenaba), la linea de comandos agregaba una carpeta
como si fuera un archivo, y un .m3u pasado por linea de comandos o soltado
en la ventana se agregaba como un medio (que despues "fallaba") o se
ignoraba."""

import os
import re

from .formats import ALL_EXTS, is_playlist_file, is_url, normalize_path
from .m3u import parse_m3u

_DIGITS = re.compile(r"(\d+)")


def natural_sort_key(path: str):
    """Orden "natural" sin distinguir mayusculas: "Pista 2" antes que
    "Pista 10", "b.mp3" junto a "B.mp3". Compara la ruta completa, asi los
    archivos de una subcarpeta quedan juntos."""
    parts = _DIGITS.split(path.casefold())
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts]


def is_media_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in ALL_EXTS


def scan_folder(folder: str, should_stop=None) -> list:
    """Todos los medios soportados dentro de `folder` (recursivo), en orden
    natural. `should_stop()` permite cancelar un recorrido largo."""
    found = []
    for root, dirs, files in os.walk(folder):
        if should_stop is not None and should_stop():
            break
        dirs.sort(key=natural_sort_key)
        for f in files:
            if is_media_file(f):
                found.append(os.path.join(root, f))
    found.sort(key=natural_sort_key)
    return found


def read_playlist_file(path: str) -> list:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    return parse_m3u(data, path)


def expand_inputs(paths, should_stop=None) -> list:
    """Carpetas -> sus medios (orden natural); .m3u/.m3u8 -> sus entradas;
    URLs -> tal cual; archivos -> normalizados (cualquier extension: un
    archivo elegido a mano se respeta aunque no este en ALL_EXTS, como
    hacia Abrir archivos). Entradas vacias se descartan."""
    result = []
    for raw in paths:
        if not raw or not raw.strip():
            continue
        if should_stop is not None and should_stop():
            break
        if is_url(raw):
            result.append(raw.strip())
            continue
        local = normalize_path(raw)
        if os.path.isdir(local):
            result.extend(scan_folder(local, should_stop))
        elif is_playlist_file(local):
            result.extend(read_playlist_file(local))
        else:
            result.append(local)
    return result


def filter_dropped(paths) -> list:
    """Lo soltado sobre la ventana: igual que expand_inputs pero un archivo
    suelto solo cuenta si es un medio o una lista (soltar un .txt o un .exe
    por error no debe agregarlo)."""
    keep = []
    for p in paths:
        if is_url(p) or os.path.isdir(p) or is_playlist_file(p) or is_media_file(p):
            keep.append(p)
    return expand_inputs(keep)
