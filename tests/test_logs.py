"""player/logs.py (sin VLC): log rotativo, excepthooks y limite de avisos.
Cada prueba restaura sys.excepthook/threading.excepthook y los handlers del
logger raiz; faulthandler se reemplaza por un espia para no pisar el que
activa el propio pytest."""
import logging
import sys
import threading

import pytest

from player import logs


@pytest.fixture
def clean_logging(monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    enabled = []
    monkeypatch.setattr(logs.faulthandler, "enable", lambda file=None, **k: enabled.append(file))
    monkeypatch.setattr(logs.faulthandler, "disable", lambda: None)
    level = logging.getLogger().level
    yield enabled
    logs.shutdown_logging()
    logging.getLogger().setLevel(level)


def _read_log(directory):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (directory / logs.LOG_FILE_NAME).read_text(encoding="utf-8")


def test_default_log_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert logs.default_log_dir() == tmp_path / "ReproductorMultimediaPro" / "logs"


def test_setup_logging_writes_a_rotating_file_and_enables_faulthandler(clean_logging, tmp_path):
    directory = logs.setup_logging(tmp_path / "logs")
    assert directory == tmp_path / "logs"
    assert logs.current_log_dir() == directory
    logging.getLogger("player.test").info("hola registro")
    assert "hola registro" in _read_log(directory)
    rotating = [h for h in logging.getLogger().handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert rotating and rotating[0].maxBytes == logs.LOG_MAX_BYTES and rotating[0].backupCount == 4
    assert len(clean_logging) == 1 and clean_logging[0].name.endswith(logs.CRASH_FILE_NAME)


def test_setup_logging_survives_a_windowed_exe_without_stderr(clean_logging, tmp_path, monkeypatch):
    # console=False: sys.stderr es None en el .exe.
    monkeypatch.setattr(sys, "stderr", None)
    directory = logs.setup_logging(tmp_path / "logs")
    logging.getLogger("player.test").warning("sin consola")
    assert "sin consola" in _read_log(directory)


def test_setup_logging_without_a_writable_dir_does_not_raise(clean_logging, tmp_path):
    blocker = tmp_path / "archivo"
    blocker.write_text("x")
    assert logs.setup_logging(blocker / "logs") is None  # mkdir falla: la app sigue


def test_excepthook_logs_the_traceback_and_notifies(clean_logging, tmp_path):
    directory = logs.setup_logging(tmp_path / "logs")
    notices = []
    logs.install_exception_hooks(notify=notices.append)
    try:
        raise ValueError("boom del slot")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    text = _read_log(directory)
    assert "Excepcion no atrapada" in text and "boom del slot" in text and "Traceback" in text
    assert notices == ["ValueError: boom del slot"]


def test_thread_exceptions_are_logged(clean_logging, tmp_path):
    directory = logs.setup_logging(tmp_path / "logs")
    notices = []
    logs.install_exception_hooks(notify=notices.append)

    def worker():
        raise KeyError("file_id")

    t = threading.Thread(target=worker, name="SubtitulosThread")
    t.start()
    t.join()
    text = _read_log(directory)
    assert "SubtitulosThread" in text and "KeyError" in text
    assert notices and notices[0].startswith("KeyError")


def test_exceptions_in_qt_slots_reach_the_hook(clean_logging, tmp_path):
    # PySide6 entrega las excepciones de un slot a sys.excepthook: es lo que
    # hace que el hook cubra los errores de la UI en el .exe sin consola.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    # QApplication (no QCoreApplication): la instancia es unica por proceso
    # y las pruebas de interfaz que corran despues la reutilizan.
    QApplication.instance() or QApplication(sys.argv)

    class Emitter(QObject):
        fired = Signal()

    seen = []
    logs.setup_logging(tmp_path / "logs")
    logs.install_exception_hooks(notify=seen.append)
    emitter = Emitter()

    def slot():
        raise RuntimeError("fallo en un slot")

    emitter.fired.connect(slot)
    emitter.fired.emit()
    assert seen == ["RuntimeError: fallo en un slot"]


def test_error_notifier_rate_limits_to_one_notice_per_interval():
    now = [100.0]
    shown = []
    notifier = logs.ErrorNotifier(shown.append, interval_s=60, clock=lambda: now[0])
    assert notifier("a") is True
    now[0] += 10
    assert notifier("b") is False
    now[0] += 51
    assert notifier("c") is True
    assert shown == ["a", "c"]


def test_a_failing_notifier_does_not_raise():
    def broken(_summary):
        raise RuntimeError("sin UI")

    assert logs.ErrorNotifier(broken)("x") is True
