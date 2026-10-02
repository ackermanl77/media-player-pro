"""Registro de errores para el .exe sin consola. Modulo sin Qt ni VLC.

El ejecutable se empaqueta con console=False: ahi sys.stderr es None, asi
que una excepcion dentro de un slot de Qt (o de un hilo) no se imprimia en
ningun lado y el usuario solo veia que "algo no hizo nada". Este modulo:

- escribe un log rotativo (5 archivos x 1 MB) en
  %LOCALAPPDATA%\\ReproductorMultimediaPro\\logs\\app.log;
- reemplaza sys.excepthook y threading.excepthook para registrar el
  traceback completo y avisar al usuario (a traves de un callback que pone
  run.py, como mucho una vez por minuto -- ver ErrorNotifier);
- activa faulthandler hacia crash.log en la misma carpeta, para los
  cuelgues nativos (libVLC y ctypes corren dentro del mismo proceso).

PySide6 entrega las excepciones no atrapadas en slots a sys.excepthook
(via PyErr_Print), asi que el hook cubre tambien esas.
"""

import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

LOG_FILE_NAME = "app.log"
CRASH_FILE_NAME = "crash.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 4  # app.log + 4 rotados = 5 archivos
NOTIFY_INTERVAL_S = 60.0

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(threadName)s] %(message)s"

_state = {"dir": None, "handlers": [], "crash_file": None}


def default_log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ReproductorMultimediaPro" / "logs"
    # Fuera de Windows (o si falta la variable): junto al resto del estado.
    return Path.home() / ".reproductor_multimedia_pro" / "logs"


def current_log_dir() -> Path:
    """Carpeta en uso (la de setup_logging) o, si no se configuro, la por
    defecto -- es la que abre "Ayuda -> Abrir carpeta de registros"."""
    return _state["dir"] or default_log_dir()


def setup_logging(directory=None, debug: bool = False, enable_faulthandler: bool = True):
    """Configura el logger raiz. Devuelve la carpeta de logs, o None si no
    se pudo crear (sin permisos, disco lleno): en ese caso sigue funcionando
    sin log a archivo -- no poder registrar nunca debe impedir abrir la app."""
    shutdown_logging()
    directory = Path(directory) if directory is not None else default_log_dir()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)
    handlers = []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            directory / LOG_FILE_NAME, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8",
        )
        handlers.append(file_handler)
    except OSError:
        directory = None
    # Con console=False (el .exe) sys.stderr es None: un StreamHandler ahi
    # fallaria en cada registro.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)
    _state["handlers"] = handlers
    _state["dir"] = directory

    if enable_faulthandler and directory is not None:
        try:
            crash_file = open(directory / CRASH_FILE_NAME, "a", encoding="utf-8")
            faulthandler.enable(file=crash_file)
            _state["crash_file"] = crash_file  # debe seguir abierto mientras viva el proceso
        except (OSError, RuntimeError, ValueError):
            pass
    return directory


def shutdown_logging():
    """Quita y cierra lo que agrego setup_logging (usado por las pruebas y
    por una segunda llamada a setup_logging)."""
    root = logging.getLogger()
    for handler in _state["handlers"]:
        root.removeHandler(handler)
        handler.close()
    _state["handlers"] = []
    crash_file = _state["crash_file"]
    if crash_file is not None:
        try:
            faulthandler.disable()
        except RuntimeError:
            pass
        crash_file.close()
        _state["crash_file"] = None
    _state["dir"] = None


class ErrorNotifier:
    """Limita los avisos al usuario: el primer error se avisa, los
    siguientes dentro de `interval_s` solo se registran (un error que se
    repite en cada tick de 250 ms no debe abrir cuatro ventanas por
    segundo). `clock` es inyectable para las pruebas."""

    def __init__(self, notify, interval_s: float = NOTIFY_INTERVAL_S, clock=time.monotonic):
        self._notify = notify
        self._interval_s = interval_s
        self._clock = clock
        self._last = None

    def __call__(self, summary: str) -> bool:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval_s:
            return False
        self._last = now
        try:
            self._notify(summary)
        except Exception:  # el aviso nunca debe tapar el error original
            logging.getLogger(__name__).exception("No se pudo mostrar el aviso de error")
        return True


def install_exception_hooks(notify=None, interval_s: float = NOTIFY_INTERVAL_S):
    """Reemplaza sys.excepthook y threading.excepthook. `notify(resumen)`
    (opcional) se llama como mucho una vez cada `interval_s`; puede llamarse
    desde cualquier hilo, asi que quien lo provee tiene que encargarse de
    volver al hilo de la UI (run.py usa una senal de Qt)."""
    log = logging.getLogger("player.errors")
    notifier = ErrorNotifier(notify, interval_s) if notify is not None else None
    previous_hook = sys.excepthook

    def excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc_value, exc_tb)
            return
        log.error("Excepcion no atrapada", exc_info=(exc_type, exc_value, exc_tb))
        if notifier is not None:
            notifier(f"{exc_type.__name__}: {exc_value}")

    def thread_excepthook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "?"
        log.error("Excepcion no atrapada en el hilo %s", name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if notifier is not None:
            notifier(f"{args.exc_type.__name__}: {args.exc_value}")

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    return notifier
