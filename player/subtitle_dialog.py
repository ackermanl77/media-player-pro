"""Dialogo para buscar y descargar subtitulos desde OpenSubtitles. Toda
llamada de red corre en un QThread para no congelar la interfaz.

Ciclo de vida de los hilos (antes: un resultado tardio se cargaba en el
video que estuviera sonando en ese momento, un error inesperado dejaba el
dialogo en "Buscando..." para siempre, y cerrar la app durante una busqueda
destruia un QThread en marcha -- error fatal de Qt):
- los hilos NO son hijos del dialogo: viven en _RUNNING hasta terminar, asi
  que cerrar el dialogo nunca destruye un hilo en marcha;
- al cerrar el dialogo se desconectan sus senales y se pide la
  interrupcion: un resultado tardio se descarta;
- subtitle_ready lleva el video que origino la descarga; MainWindow lo
  carga solo si sigue siendo el actual (si no, lo guarda para cuando se
  vuelva a abrir ese archivo);
- run() atrapa cualquier excepcion y emite failed;
- MainWindow.closeEvent espera (con limite) a los hilos que queden
  (wait_for_subtitle_jobs)."""

import logging
import os
import re
import tempfile

from PySide6.QtCore import QDeadlineTimer, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .config import (
    get_opensubtitles_api_key,
    get_subtitle_languages,
    set_opensubtitles_api_key,
    set_subtitle_languages,
)
from .opensubtitles import (
    compute_opensubtitles_hash,
    download_subtitle_file,
    search_by_hash,
    search_by_query,
    subtitle_extension,
)

log = logging.getLogger(__name__)

# Hilos en marcha (de cualquier dialogo, abierto o ya cerrado) y ya
# terminados pendientes de soltar (ver _track).
_RUNNING = set()
_FINISHED = []


def _clean_query_from_filename(path: str) -> str:
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[._]", " ", name).strip()


def plural(n: int, singular: str, plural_form: str) -> str:
    return f"{n} {singular if n == 1 else plural_form}"


def destination_path(video_path: str, language: str, file_name: str, writable=None) -> str:
    """<video>.<idioma><ext del resultado> junto al video; si la carpeta no
    se puede escribir, un temporal."""
    ext = subtitle_extension(file_name)
    base, _ext = os.path.splitext(video_path)
    directory = os.path.dirname(base) or "."
    writable = writable if writable is not None else os.access(directory, os.W_OK)
    if writable:
        return f"{base}.{language}{ext}"
    fd, path = tempfile.mkstemp(suffix=f".{language}{ext}")
    os.close(fd)
    return path


def _track(thread: QThread):
    """Arranca el hilo y lo mantiene referenciado hasta que termine. Los
    QThread son objetos de Python (PySide los destruye al soltar la ultima
    referencia): nada de deleteLater(), que los liberaria dos veces. Uno
    terminado pasa a _FINISHED y se suelta en la proxima llamada -- nunca
    dentro del manejador de su propia senal finished."""
    _FINISHED.clear()
    _RUNNING.add(thread)

    def _done():
        _RUNNING.discard(thread)
        _FINISHED.append(thread)

    # Con QueuedConnection el manejador corre en el hilo de la UI (donde
    # vive el objeto QThread), no en el hilo que termina.
    thread.finished.connect(_done, Qt.ConnectionType.QueuedConnection)
    thread.start()


def running_subtitle_jobs() -> int:
    return sum(1 for t in _RUNNING if t.isRunning())


def wait_for_subtitle_jobs(timeout_ms: int = 3000) -> bool:
    """Al cerrar la app: pide la interrupcion y espera a que terminen los
    hilos (como mucho timeout_ms en total). True si no queda ninguno."""
    deadline = QDeadlineTimer(timeout_ms)
    for thread in list(_RUNNING):
        thread.requestInterruption()
    for thread in list(_RUNNING):
        if thread.isRunning():
            thread.wait(deadline)
    return running_subtitle_jobs() == 0


class _SearchThread(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, api_key: str, video_path: str, languages: str):
        super().__init__()
        self.api_key = api_key
        self.video_path = video_path
        self.languages = languages

    def run(self):
        try:
            results = []
            file_hash = compute_opensubtitles_hash(self.video_path)
            if file_hash and not self.isInterruptionRequested():
                results = search_by_hash(self.api_key, file_hash, self.languages)
            if not results and not self.isInterruptionRequested():
                results = search_by_query(self.api_key, _clean_query_from_filename(self.video_path), self.languages)
        except Exception as e:  # noqa: BLE001 -- OSError del hash, JSON invalido, etc.
            log.warning("Busqueda de subtitulos fallida: %s", e)
            self.failed.emit(str(e) or type(e).__name__)
            return
        self.succeeded.emit(results)


class _DownloadThread(QThread):
    succeeded = Signal(object)  # opensubtitles.DownloadResult
    failed = Signal(str)

    def __init__(self, api_key: str, file_id: int, dest_path: str):
        super().__init__()
        self.api_key = api_key
        self.file_id = file_id
        self.dest_path = dest_path

    def run(self):
        try:
            result = download_subtitle_file(self.api_key, self.file_id, self.dest_path)
        except Exception as e:  # noqa: BLE001
            log.warning("Descarga de subtitulo fallida: %s", e)
            self.failed.emit(str(e) or type(e).__name__)
            return
        self.succeeded.emit(result)


class OnlineSubtitleDialog(QDialog):
    # (video que origino la descarga, ruta local del subtitulo descargado)
    subtitle_ready = Signal(str, str)
    # Resumen para la barra de estado de la ventana principal (el dialogo se
    # cierra apenas termina la descarga).
    status_message = Signal(str)

    def __init__(self, video_path: str, parent=None, auto_search: bool = True):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.video_path = video_path
        self.results = []
        self._search_thread = None
        self._download_thread = None
        self._closed = False

        self.setWindowTitle("Buscar subtítulos online (OpenSubtitles)")
        self.resize(560, 380)

        layout = QVBoxLayout(self)
        languages_row = QHBoxLayout()
        languages_row.addWidget(QLabel("Idiomas:"))
        self.languages_edit = QLineEdit(get_subtitle_languages())
        self.languages_edit.setToolTip("Códigos ISO separados por comas, p. ej. es,en,pt-br")
        self.languages_edit.returnPressed.connect(self._start_search)
        languages_row.addWidget(self.languages_edit, stretch=1)
        self.btn_search = QPushButton("Buscar")
        self.btn_search.clicked.connect(self._start_search)
        languages_row.addWidget(self.btn_search)
        layout.addLayout(languages_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, stretch=1)
        self.list_widget.itemSelectionChanged.connect(
            lambda: self.btn_download.setEnabled(bool(self.list_widget.selectedItems()))
        )

        self.quota_label = QLabel("")
        layout.addWidget(self.quota_label)

        buttons = QHBoxLayout()
        self.btn_download = QPushButton("Descargar y usar")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download_clicked)
        buttons.addWidget(self.btn_download)
        btn_cancel = QPushButton("Cerrar")
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)

        if auto_search:
            self._start_search()

    # -- ciclo de vida --------------------------------------------------
    def _detach_threads(self):
        """Desconecta los hilos de este dialogo y les pide que paren: lo
        que terminen despues ya no llega a ningun lado."""
        self._closed = True
        for thread in (self._search_thread, self._download_thread):
            if thread is None:
                continue
            for signal in (thread.succeeded, thread.failed):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            thread.requestInterruption()
        self._search_thread = None
        self._download_thread = None

    def done(self, result):
        self._detach_threads()
        super().done(result)

    def closeEvent(self, event):
        self._detach_threads()
        super().closeEvent(event)

    # -- busqueda ---------------------------------------------------------
    def _api_key(self):
        api_key = get_opensubtitles_api_key()
        if api_key:
            return api_key
        entered, ok = QInputDialog.getText(
            self,
            "API key de OpenSubtitles",
            "Necesitas una API key gratuita de opensubtitles.com para buscar subtítulos:",
        )
        if not ok or not entered.strip():
            return None
        set_opensubtitles_api_key(entered.strip())
        return entered.strip()

    def _start_search(self):
        if self._closed or (self._search_thread is not None and self._search_thread.isRunning()):
            return
        api_key = self._api_key()
        if not api_key:
            self.status_label.setText("Se necesita una API key para buscar subtítulos.")
            return
        languages = set_subtitle_languages(self.languages_edit.text())
        self.languages_edit.setText(languages)
        self.status_label.setText("Buscando...")
        self.list_widget.clear()
        self.btn_search.setEnabled(False)
        thread = _SearchThread(api_key, self.video_path, languages)
        thread.succeeded.connect(self._on_search_succeeded)
        thread.failed.connect(self._on_search_failed)
        self._search_thread = thread
        _track(thread)

    def _on_search_succeeded(self, results):
        self.btn_search.setEnabled(True)
        self.results = results
        self.list_widget.clear()
        if not results:
            self.status_label.setText("Sin resultados para este archivo.")
            return
        self.status_label.setText(f"{plural(len(results), 'resultado', 'resultados')}:")
        for r in results:
            downloads = plural(r["download_count"], "descarga", "descargas")
            self.list_widget.addItem(QListWidgetItem(f"[{r['language']}] {r['release']} — {downloads}"))

    def _on_search_failed(self, message: str):
        self.btn_search.setEnabled(True)
        self.status_label.setText(f"Error al buscar: {message}")

    # -- descarga ---------------------------------------------------------
    def _confirm_overwrite(self, path: str) -> bool:
        answer = QMessageBox.question(
            self, "Subtítulo existente",
            f"Ya existe:\n{path}\n\n¿Reemplazarlo?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_download_clicked(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.results):
            return
        chosen = self.results[row]
        api_key = get_opensubtitles_api_key()
        if not api_key:
            return
        dest_path = destination_path(self.video_path, chosen["language"], chosen.get("file_name", ""))
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0 and not self._confirm_overwrite(dest_path):
            return

        self.btn_download.setEnabled(False)
        self.status_label.setText("Descargando...")
        thread = _DownloadThread(api_key, chosen["file_id"], dest_path)
        thread.succeeded.connect(self._on_download_succeeded)
        thread.failed.connect(self._on_download_failed)
        self._download_thread = thread
        _track(thread)

    def _on_download_succeeded(self, result):
        if self._closed:
            return
        quota = ""
        if result.remaining is not None:
            reset = f" (se renueva: {result.reset_time})" if result.reset_time else ""
            quota = f"Descargas restantes hoy: {result.remaining}{reset}"
            self.quota_label.setText(quota)
        self.status_label.setText(f"Subtítulo guardado en: {result.path}")
        self.status_message.emit(f"Subtítulo descargado: {os.path.basename(result.path)}" + (f". {quota}" if quota else ""))
        self.subtitle_ready.emit(self.video_path, result.path)
        self.accept()

    def _on_download_failed(self, message: str):
        self.btn_download.setEnabled(True)
        self.status_label.setText(f"Error al descargar: {message}")
