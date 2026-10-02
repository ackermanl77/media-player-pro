import logging
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QObject, Qt, QTranslator, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from player import __version__
from player.logs import install_exception_hooks, setup_logging

log = logging.getLogger("player.run")

OWN_FLAGS = ("--debug", "--new-window", "--enqueue")


class _ErrorReporter(QObject):
    """Lleva el aviso de error al hilo de la UI: install_exception_hooks
    puede llamar a notify() desde cualquier hilo (threading.excepthook), y
    una senal de Qt conectada a un objeto del hilo principal se encola sola."""

    report = Signal(str)

    def __init__(self, log_dir):
        super().__init__()
        self._log_dir = log_dir
        self._boxes = []
        self.report.connect(self._show)

    def _show(self, summary: str):
        where = f"\n\nDetalles en el registro:\n{self._log_dir}" if self._log_dir else ""
        box = QMessageBox(QMessageBox.Icon.Warning, "Algo salió mal",
                          f"Ocurrió un error inesperado:\n{summary}{where}")
        box.setModal(False)  # no bloquea la reproduccion
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.show()
        self._boxes.append(box)
        box.finished.connect(lambda _r, b=box: self._boxes.remove(b) if b in self._boxes else None)


def split_args(argv):
    """(debug, archivos) de la linea de comandos. Opciones propias:
    --debug (log detallado), --new-window (no reusar una ventana abierta)
    y --enqueue (agregar a la lista sin reproducir); ver parse_args."""
    opts = parse_args(argv)
    return opts["debug"], opts["files"]


def parse_args(argv) -> dict:
    return {
        "debug": "--debug" in argv,
        "new_window": "--new-window" in argv,
        "enqueue": "--enqueue" in argv,
        "files": [a for a in argv if a not in OWN_FLAGS],
    }


def install_spanish_translator(app) -> bool:
    """Botones estandar de Qt (Si/No, Aceptar/Cancelar de QInputDialog...)
    en espanol: sin esto salian en ingles. PyInstaller incluye
    translations/qtbase_es.qm junto con PySide6."""
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.Spanish), "qtbase", "_", path):
        app.installTranslator(translator)
        app._qt_translator = translator  # que no lo recolecte el GC
        return True
    log.info("No se encontro qtbase_es.qm en %s", path)
    return False


def main():
    opts = parse_args(sys.argv[1:])
    log_dir = setup_logging(debug=opts["debug"])
    app = QApplication(sys.argv)
    app.setApplicationName("Reproductor Multimedia Pro")
    install_spanish_translator(app)

    reporter = _ErrorReporter(log_dir)
    install_exception_hooks(notify=reporter.report.emit)
    log.info("Reproductor Multimedia Pro v%s, Python %s", __version__, sys.version.split()[0])

    from player.settings import load_settings
    from player.single_instance import InstanceServer, send_to_running_instance

    # Una sola ventana (salvo "Permitir varias ventanas" o --new-window): si
    # ya hay una abierta, se le mandan los archivos y este proceso termina
    # sin cargar libVLC.
    single = not opts["new_window"] and not load_settings().allow_multiple_windows
    action = "enqueue" if opts["enqueue"] else "open"
    if single and send_to_running_instance(opts["files"], action):
        log.info("Archivos enviados a la ventana ya abierta (%s)", action)
        sys.exit(0)

    from player.vlc_check import missing_vlc_message, version_warning

    try:
        from player.main_window import MainWindow
    except OSError:
        # python-vlc no pudo cargar libvlc: VLC media player no está
        # instalado en el sistema, o es de 32 bits con este Python de 64
        # (o al reves). Sin este mensaje, la app terminaba con un traceback
        # de ctypes ininteligible para el usuario.
        log.exception("No se pudo cargar libvlc")
        QMessageBox.critical(None, "VLC no encontrado", missing_vlc_message())
        sys.exit(1)

    import vlc

    from player.backend import VLCInitError

    version = vlc.libvlc_get_version().decode("utf-8", "replace")
    log.info("libVLC %s, python-vlc %s", version, getattr(vlc, "__version__", "?"))

    # MainWindow restaura sola el tamaño/posicion y la lista de la sesion
    # anterior (ver player/settings.py).
    try:
        window = MainWindow()
    except VLCInitError:
        log.exception("libVLC no pudo inicializarse")
        QMessageBox.critical(
            None, "VLC no se pudo iniciar",
            f"La librería de VLC ({version}) no pudo inicializarse.\n\n{missing_vlc_message()}",
        )
        sys.exit(1)
    window.show()
    warning = version_warning(version)
    if warning:
        window.statusBar().showMessage(warning, 15000)

    server = None
    if single:
        server = InstanceServer(app)
        if server.start():
            server.messageReceived.connect(window.handle_instance_message)

    if opts["files"]:
        # Se agregan al final de la lista restaurada (carpetas y .m3u
        # expandidos) y suena el primero de ellos (no el primero de la lista).
        window.open_paths(opts["files"], play=not opts["enqueue"])

    exit_code = app.exec()
    if server is not None:
        server.close()
    log.info("Cierre normal (codigo %s)", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
