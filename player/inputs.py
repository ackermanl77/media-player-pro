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


def scan_folder_batches(folder: str, batch_size: int = 200, should_stop=None):
    """Igual que scan_folder(), pero produce lotes ordenados de hasta
    `batch_size` entradas para una UI que quiera mostrar progreso sin
    bloquear el hilo principal."""
    if batch_size <= 0:
        raise ValueError("batch_size debe ser > 0")

    def stopped() -> bool:
        return should_stop is not None and bool(should_stop())

    def walk(directory):
        # Recorrido en profundidad con archivos y subcarpetas de cada nivel
        # ordenados juntos: asi el orden total es el mismo que el sort() de
        # scan_folder() sobre la ruta completa. Una subcarpeta se ordena como
        # "nombre\" (el prefijo de sus archivos), no como "nombre".
        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except OSError:
            return  # como os.walk: una carpeta ilegible se salta
        items = []
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                items.append((natural_sort_key(entry.path + os.sep), True, entry.path))
            elif is_media_file(entry.name):
                items.append((natural_sort_key(entry.path), False, entry.path))
        items.sort(key=lambda item: item[0])
        for _key, is_dir, path in items:
            if is_dir:
                yield from walk(path)
            else:
                yield path

    batch = []
    for path in walk(folder):
        if stopped():
            break
        batch.append(path)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:  # tambien al cancelar: lo encontrado hasta ahi no se pierde
        yield batch


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


def needs_scan(paths) -> bool:
    """True si alguna entrada es una carpeta local: recorrerla puede tardar,
    asi que la UI la expande en segundo plano (ver expand_inputs_batches)."""
    return any(raw and raw.strip() and not is_url(raw) and os.path.isdir(normalize_path(raw)) for raw in paths)


def expand_inputs_batches(paths, batch_size: int = 200, should_stop=None):
    """Lo mismo que expand_inputs(), en el mismo orden, pero en lotes de hasta
    `batch_size` entradas (las carpetas via scan_folder_batches) para
    recorrerlo fuera del hilo de la UI con progreso y cancelacion."""
    if batch_size <= 0:
        raise ValueError("batch_size debe ser > 0")
    pending = []

    def full_batches():
        nonlocal pending
        while len(pending) >= batch_size:
            yield pending[:batch_size]
            pending = pending[batch_size:]

    for raw in paths:
        if not raw or not raw.strip():
            continue
        if should_stop is not None and should_stop():
            break
        if is_url(raw):
            pending.append(raw.strip())
        else:
            local = normalize_path(raw)
            if os.path.isdir(local):
                for found in scan_folder_batches(local, batch_size, should_stop):
                    pending.extend(found)
                    yield from full_batches()
            elif is_playlist_file(local):
                pending.extend(read_playlist_file(local))
            else:
                pending.append(local)
        yield from full_batches()
    if pending:  # tambien al cancelar: lo encontrado hasta ahi no se pierde
        yield pending


def dropped_inputs(paths) -> list:
    """Lo soltado que cuenta, sin expandir: URLs, carpetas, listas y medios
    (soltar un .txt o un .exe por error no debe agregarlo)."""
    return [p for p in paths if is_url(p) or os.path.isdir(p) or is_playlist_file(p) or is_media_file(p)]


def filter_dropped(paths) -> list:
    """Lo soltado sobre la ventana: igual que expand_inputs pero un archivo
    suelto solo cuenta si es un medio o una lista (soltar un .txt o un .exe
    por error no debe agregarlo)."""
    return expand_inputs(dropped_inputs(paths))
