"""Lectura/escritura robusta de los JSON de estado del usuario (posiciones,
marcadores, recientes, config). Modulo puro, sin VLC ni Qt.

- Escritura atomica: se escribe a un archivo temporal en la misma carpeta y
  se reemplaza con os.replace(), asi un cierre/corte a mitad de escritura
  nunca deja un JSON truncado.
- Copia .bak: antes de reemplazar, el contenido anterior (valido) se copia
  a "<archivo>.bak"; si el principal esta corrupto o tiene un tipo
  inesperado, load_json() recurre a la copia.
- Validacion de tipo: un JSON valido pero del tipo equivocado (p. ej. una
  lista donde se esperaba un dict) se trata igual que uno corrupto.
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def _read(path: Path, expected_type):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, expected_type) else None


def load_json(path: Path, expected_type, default):
    """Devuelve el contenido de `path` si es JSON valido de tipo
    `expected_type`; si no, el de su .bak; si tampoco, `default`."""
    for candidate in (path, backup_path(path)):
        if candidate.exists():
            data = _read(candidate, expected_type)
            if data is not None:
                return data
    return default


def save_json(path: Path, data) -> bool:
    """Escribe `data` de forma atomica. Devuelve False (sin lanzar) si no se
    pudo escribir -- perder una posicion guardada no debe tumbar la UI."""
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        if path.exists() and _read(path, object) is not None:
            shutil.copyfile(path, backup_path(path))
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


def _replace_with_retry(src: str, dst: Path, attempts: int = 5):
    # En Windows os.replace() falla con PermissionError si otro proceso
    # (antivirus, indexador, OneDrive) tiene el destino abierto un instante.
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)
