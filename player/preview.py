"""Cache de miniaturas de la vista previa de la barra de progreso. Modulo
puro (sin Qt ni VLC): guarda cualquier valor (MainWindow guarda QPixmap).

Antes cada hover volvia a buscar en el reproductor de vista previa,
escribia un PNG a una ruta fija compartida entre instancias y lo releia,
sin cachear nada. Ahora la misma zona (cubeta de 0,5 %) de un mismo
archivo se sirve al instante."""

import os
import tempfile
from collections import OrderedDict

from .formats import path_key

BUCKETS = 200  # 0,5 % de la duracion por cubeta
DEFAULT_CAPACITY = 300  # ~17 MB a 160x90x4 B (mas en HiDPI)
CAPTURE_POLL_MS = 40
CAPTURE_TIMEOUT_MS = 400
IDLE_RELEASE_MS = 30_000


def bucket_for(fraction: float, buckets: int = BUCKETS) -> int:
    return int(round(max(0.0, min(1.0, fraction)) * buckets))


def bucket_fraction(bucket: int, buckets: int = BUCKETS) -> float:
    return bucket / buckets


class ThumbnailCache:
    def __init__(self, capacity: int = DEFAULT_CAPACITY):
        self.capacity = capacity
        self._items = OrderedDict()

    def __len__(self):
        return len(self._items)

    @staticmethod
    def key(path: str, fraction: float):
        return (path_key(path), bucket_for(fraction))

    def get(self, path: str, fraction: float):
        k = self.key(path, fraction)
        value = self._items.get(k)
        if value is not None:
            self._items.move_to_end(k)
        return value

    def put(self, path: str, fraction: float, value):
        k = self.key(path, fraction)
        self._items[k] = value
        self._items.move_to_end(k)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def clear(self):
        self._items.clear()


def new_snapshot_path() -> str:
    """Archivo temporal propio de este proceso (dos instancias abiertas ya
    no se pisan la miniatura). Quien lo pide lo borra al cerrar."""
    fd, path = tempfile.mkstemp(prefix="rmp_preview_", suffix=".png")
    os.close(fd)
    return path


def remove_quietly(path: str):
    try:
        os.remove(path)
    except OSError:
        pass
