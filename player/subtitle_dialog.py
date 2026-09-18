"""Dialogo para buscar y descargar subtitulos desde OpenSubtitles. Toda
llamada de red corre en un QThread para no congelar la interfaz."""

import os
import re
import tempfile

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .config import get_opensubtitles_api_key, set_opensubtitles_api_key
from .opensubtitles import (
    OpenSubtitlesError,
    compute_opensubtitles_hash,
    download_subtitle,
    search_by_hash,
    search_by_query,
)


def _clean_query_from_filename(path: str) -> str:
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[._]", " ", name).strip()


class _SearchThread(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, api_key: str, video_path: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.video_path = video_path

    def run(self):
        try:
            results = []
            file_hash = compute_opensubtitles_hash(self.video_path)
            if file_hash:
                results = search_by_hash(self.api_key, file_hash)
            if not results:
                results = search_by_query(self.api_key, _clean_query_from_filename(self.video_path))
        except OpenSubtitlesError as e:
            self.failed.emit(str(e))
            return
        self.succeeded.emit(results)


class _DownloadThread(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str, file_id: int, dest_path: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.file_id = file_id
        self.dest_path = dest_path

    def run(self):
        try:
            path = download_subtitle(self.api_key, self.file_id, self.dest_path)
        except OpenSubtitlesError as e:
            self.failed.emit(str(e))
            return
        self.succeeded.emit(path)


class OnlineSubtitleDialog(QDialog):
    subtitle_ready = Signal(str)  # ruta local del subtitulo descargado

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.results = []
        self._search_thread = None
        self._download_thread = None

        self.setWindowTitle("Buscar subtítulos online (OpenSubtitles)")
        self.resize(560, 360)

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Buscando...")
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, stretch=1)
        self.list_widget.itemSelectionChanged.connect(
            lambda: self.btn_download.setEnabled(bool(self.list_widget.selectedItems()))
        )

        buttons = QHBoxLayout()
        self.btn_download = QPushButton("Descargar y usar")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download_clicked)
        buttons.addWidget(self.btn_download)
        btn_cancel = QPushButton("Cerrar")
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)

        self._start_search()

    def _start_search(self):
        api_key = get_opensubtitles_api_key()
        if not api_key:
            entered, ok = QInputDialog.getText(
                self,
                "API key de OpenSubtitles",
                "Necesitas una API key gratuita de opensubtitles.com para buscar subtítulos:",
            )
            if not ok or not entered.strip():
                self.status_label.setText("Se necesita una API key para buscar subtítulos.")
                return
            api_key = entered.strip()
            set_opensubtitles_api_key(api_key)

        self._search_thread = _SearchThread(api_key, self.video_path, self)
        self._search_thread.succeeded.connect(self._on_search_succeeded)
        self._search_thread.failed.connect(self._on_search_failed)
        self._search_thread.start()

    def _on_search_succeeded(self, results):
        self.results = results
        self.list_widget.clear()
        if not results:
            self.status_label.setText("Sin resultados para este archivo.")
            return
        self.status_label.setText(f"{len(results)} resultado(s):")
        for r in results:
            item = QListWidgetItem(f"[{r['language']}] {r['release']} — {r['download_count']} descargas")
            self.list_widget.addItem(item)

    def _on_search_failed(self, message: str):
        self.status_label.setText(f"Error al buscar: {message}")

    def _on_download_clicked(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.results):
            return
        chosen = self.results[row]
        api_key = get_opensubtitles_api_key()
        dest_path = self._destination_path(chosen["language"])

        self.btn_download.setEnabled(False)
        self.status_label.setText("Descargando...")
        self._download_thread = _DownloadThread(api_key, chosen["file_id"], dest_path, self)
        self._download_thread.succeeded.connect(self._on_download_succeeded)
        self._download_thread.failed.connect(self._on_download_failed)
        self._download_thread.start()

    def _destination_path(self, language: str) -> str:
        base, _ext = os.path.splitext(self.video_path)
        directory = os.path.dirname(base) or "."
        if os.access(directory, os.W_OK):
            return f"{base}.{language}.srt"
        fd, path = tempfile.mkstemp(suffix=f".{language}.srt")
        os.close(fd)
        return path

    def _on_download_succeeded(self, path: str):
        self.status_label.setText(f"Subtítulo guardado en: {path}")
        self.subtitle_ready.emit(path)
        self.accept()

    def _on_download_failed(self, message: str):
        self.btn_download.setEnabled(True)
        self.status_label.setText(f"Error al descargar: {message}")
