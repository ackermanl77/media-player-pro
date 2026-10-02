"""Controlador de la lista de reproduccion (antes repartido por MainWindow).

Une el modelo (playlist_model.PlaylistModel), el filtro del buscador
(PlaylistFilterProxy) y el orden de reproduccion (playlist_order.
PlaylistOrder), y mantiene ambos sincronizados al agregar, quitar, mover u
ordenar. Tambien lee duraciones y etiquetas en segundo plano
(backend.MediaInfoProbe) y arma el titulo del dock con el total.

No toca el reproductor: MainWindow decide que suena y le avisa la fila
actual (current_index); antes de quitar la fila que suena, MainWindow
guarda la posicion y detiene la reproduccion."""

import os

from PySide6.QtCore import QObject, QTimer, Signal

from .formats import format_time, is_url, normalize_path
from .inputs import natural_sort_key
from .playlist_model import PlaylistFilterProxy, PlaylistModel, display_name, moved_order
from .playlist_order import PlaylistOrder

METADATA_BATCH = 4
METADATA_DELAY_MS = 200
DOCK_TITLE = "Lista de reproducción"


class PlaylistController(QObject):
    # Cambiaron las entradas o su orden (agregar/quitar/mover/vaciar): la
    # sesion se vuelve a guardar.
    contentsChanged = Signal()
    # Titulo del dock ("Lista de reproduccion (3 elementos) — 12:34").
    summaryChanged = Signal(str)

    def __init__(self, probe_factory=None, parent=None):
        super().__init__(parent)
        self.model = PlaylistModel(self)
        self.proxy = PlaylistFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.order = PlaylistOrder()
        # Fila de la sesion restaurada que estaba sonando al cerrar: se
        # selecciona pero no se reproduce sola; Reproducir la retoma.
        self.session_row = -1

        # Duraciones y etiquetas en segundo plano (ver _probe_next_metadata).
        if probe_factory is None:
            from .backend import MediaInfoProbe

            probe_factory = MediaInfoProbe
        self._metadata_queue = []
        self._metadata_probe = probe_factory(self._on_metadata_parsed)
        self._metadata_timer = QTimer(self)
        self._metadata_timer.setSingleShot(True)
        self._metadata_timer.setInterval(METADATA_DELAY_MS)
        self._metadata_timer.timeout.connect(self._probe_next_metadata)

    # -- lectura -----------------------------------------------------------
    def count(self) -> int:
        return self.model.rowCount()

    def entries(self) -> list:
        return self.model.paths()

    def path(self, row: int):
        return self.model.path(row)

    @property
    def current_index(self) -> int:
        return self.model.current_row

    @current_index.setter
    def current_index(self, row: int):
        self.model.set_current_row(row)

    def current_path(self):
        return self.model.path(self.current_index) if self.current_index != -1 else None

    def entry_label(self, path: str) -> str:
        return self.model.entry_label(path)

    @staticmethod
    def display_name(path: str) -> str:
        return display_name(path)

    def dock_title(self) -> str:
        count = self.count()
        if count == 0:
            return DOCK_TITLE
        total = self.model.total_duration_ms()
        suffix = f" — {format_time(total)}" if total else ""
        noun = "elemento" if count == 1 else "elementos"
        return f"{DOCK_TITLE} ({count} {noun}){suffix}"

    def _emit_summary(self):
        self.summaryChanged.emit(self.dock_title())

    # -- agregar / quitar ----------------------------------------------------
    def add(self, paths) -> int:
        """Unico punto de entrada a la lista: normaliza cada ruta local una
        sola vez (ver formats.normalize_path). Devuelve la fila de la
        primera entrada agregada."""
        start = self.count()
        paths = [normalize_path(p) for p in paths]
        if not paths:
            return start
        self.model.append_paths(paths)
        self.order.append(len(paths))
        for p in paths:
            if not is_url(p) and not self.model.has_duration(p):
                self._metadata_queue.append(p)
        if self._metadata_queue and not self._metadata_timer.isActive():
            self._metadata_timer.start()
        self.contentsChanged.emit()
        self._emit_summary()
        return start

    def remove_rows(self, rows) -> list:
        """Quita estas filas. Si se quito la actual, PlaylistOrder recuerda
        su fila: Siguiente/Reproducir siguen con la que tomo su lugar."""
        removed = self.model.remove_rows(rows)
        if not removed:
            return []
        if self.session_row in removed:
            self.session_row = -1
        elif self.session_row != -1:
            self.session_row -= sum(1 for r in removed if r < self.session_row)
        self.order.remove(removed)
        self.contentsChanged.emit()
        self._emit_summary()
        return removed

    def clear(self):
        self.model.clear()
        self.session_row = -1
        self.order.reset(0)
        self._metadata_queue = []
        self.contentsChanged.emit()
        self._emit_summary()

    def unavailable_rows(self) -> list:
        return [r for r, p in enumerate(self.entries()) if not is_url(p) and not os.path.exists(p)]

    # -- reordenar -----------------------------------------------------------
    def reorder(self, new_order):
        """new_order[i] = fila vieja en la posicion i. Actualiza modelo,
        aleatorio, fila actual y fila de la sesion."""
        new_order = list(new_order)
        if new_order == list(range(self.count())):
            return
        remap = {old: new for new, old in enumerate(new_order)}
        self.model.reorder(new_order)
        self.order.reorder(new_order)
        if self.session_row != -1:
            self.session_row = remap[self.session_row]
        self.contentsChanged.emit()

    def move_rows(self, rows, target: int):
        """Arrastre: las filas `rows` quedan antes de la fila `target`."""
        self.reorder(moved_order(self.count(), rows, target))

    def sort(self, by: str = "name"):
        entries = self.entries()

        def key(row):
            path = entries[row]
            return natural_sort_key(os.path.basename(path) if by == "name" and not is_url(path) else path)

        self.reorder(sorted(range(len(entries)), key=key))

    # -- buscador ------------------------------------------------------------
    def set_filter(self, text: str):
        self.proxy.set_needle(text)

    def visible_rows(self) -> list:
        return [self.proxy.mapToSource(self.proxy.index(r, 0)).row() for r in range(self.proxy.rowCount())]

    def first_visible_row(self) -> int:
        return self.proxy.mapToSource(self.proxy.index(0, 0)).row() if self.proxy.rowCount() else -1

    # -- datos por entrada -----------------------------------------------------
    def note_duration(self, path: str, duration_ms: int):
        """Largo visto al reproducir (si el analisis previo no lo dio)."""
        if self.model.set_duration(path, duration_ms):
            self._emit_summary()

    def set_icy_title(self, url: str, title: str) -> bool:
        return self.model.set_icy_title(url, title)

    def _probe_next_metadata(self):
        while self._metadata_queue and self._metadata_probe.pending_count() < METADATA_BATCH:
            path = self._metadata_queue.pop(0)
            if self.model.has_duration(path) or not os.path.isfile(path):
                continue
            self._metadata_probe.probe(path)
        if self._metadata_queue:
            self._metadata_timer.start()

    def _on_metadata_parsed(self, path: str, duration_ms: int, title: str, artist: str):
        self.model.set_duration(path, duration_ms)
        stem = os.path.splitext(os.path.basename(path))[0]
        # libVLC usa el nombre del archivo como "titulo" si no hay etiqueta.
        if title and title not in (stem, os.path.basename(path)):
            self.model.set_tags(path, artist, title)
        self._emit_summary()
        if self._metadata_queue and not self._metadata_timer.isActive():
            self._metadata_timer.start()

    def close(self):
        self._metadata_timer.stop()
        self._metadata_queue = []
        self._metadata_probe.close()
