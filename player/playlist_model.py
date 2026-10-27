"""Modelo de la lista de reproduccion (model/view de Qt).

`PlaylistModel` (QAbstractListModel) guarda las entradas (ruta + id
estable por fila) y lo que se sabe de cada una (duracion, etiquetas,
titulo ICY de las radios), y arma el texto, la negrita y el marcador ▶ de
la fila que suena -- independiente de la seleccion. `PlaylistFilterProxy`
filtra por texto para el buscador, y `PlaylistView` (QListView) es la
vista: reordenar arrastrando (InternalMove) emite `rowsDropped`, y el
controlador (ver playlist_controller.py) aplica el movimiento al modelo y
al orden de reproduccion.

Los datos por ruta se indexan con formats.path_key, asi que dos filas con
el mismo archivo comparten duracion y etiquetas."""

import os

from PySide6.QtCore import QAbstractListModel, QItemSelectionModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QListView

from .formats import format_time, is_audio_file, is_url, path_key

PATH_ROLE = Qt.ItemDataRole.UserRole
ITEM_ID_ROLE = Qt.ItemDataRole.UserRole + 1
DURATION_ROLE = Qt.ItemDataRole.UserRole + 2
SEARCH_ROLE = Qt.ItemDataRole.UserRole + 3
NOW_PLAYING_ROLE = Qt.ItemDataRole.UserRole + 4

NOW_PLAYING_MARK = "▶"


def display_name(path: str) -> str:
    """Nombre corto de una entrada (barra de estado, titulo, recientes)."""
    if is_url(path):
        return f"🌐 {path}"
    prefix = "🎵" if is_audio_file(path) else "🎬"
    return f"{prefix} {os.path.basename(path)}"


class PlaylistModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths = []
        self._ids = []
        self._next_id = 0
        self._current_row = -1
        # Datos por entrada (claves = path_key / la URL tal cual).
        self._durations = {}
        self._tags = {}
        self._icy_titles = {}

    # -- QAbstractListModel ----------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._paths)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._paths):
            return None
        row = index.row()
        path = self._paths[row]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.row_text(row)
        if role == PATH_ROLE:
            return path
        if role == Qt.ItemDataRole.ToolTipRole:
            # La fila puede mostrar el titulo de las etiquetas ("Prueba"): primero el nombre del
            # archivo, luego su carpeta.
            return path if is_url(path) else f"{os.path.basename(path)}\n{os.path.dirname(path)}"
        if role == ITEM_ID_ROLE:
            return self._ids[row]
        if role == DURATION_ROLE:
            return self.duration_of(path)
        if role == NOW_PLAYING_ROLE:
            return row == self._current_row
        if role == SEARCH_ROLE:
            return f"{self.row_text(row)} {path}".casefold()
        if role == Qt.ItemDataRole.FontRole and row == self._current_row:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.AccessibleDescriptionRole and row == self._current_row:
            return "En reproducción"
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.isValid():
            # Sin ItemIsDropEnabled en las filas: solo se suelta ENTRE filas.
            return base | Qt.ItemFlag.ItemIsDragEnabled
        return base | Qt.ItemFlag.ItemIsDropEnabled

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    # -- lectura -----------------------------------------------------------
    def paths(self) -> list:
        return list(self._paths)

    def path(self, row: int):
        return self._paths[row] if 0 <= row < len(self._paths) else None

    def item_id(self, row: int):
        return self._ids[row] if 0 <= row < len(self._ids) else None

    def ids(self) -> list:
        return list(self._ids)

    @property
    def current_row(self) -> int:
        return self._current_row

    def duration_of(self, path: str) -> int:
        return self._durations.get(path_key(path), 0)

    def has_duration(self, path: str) -> bool:
        return path_key(path) in self._durations

    def total_duration_ms(self) -> int:
        return sum(self.duration_of(p) for p in self._paths)

    def entry_label(self, path: str) -> str:
        """Texto de una entrada: "Artista — Titulo" si el archivo trae
        etiquetas, el titulo ICY para una radio, si no el nombre."""
        if is_url(path):
            title = self._icy_titles.get(path)
            return f"🌐 {title}" if title else f"🌐 {path}"
        tags = self._tags.get(path_key(path))
        if tags:
            artist, title = tags
            prefix = "🎵" if is_audio_file(path) else "🎬"
            return f"{prefix} {artist} — {title}" if artist else f"{prefix} {title}"
        return display_name(path)

    def row_text(self, row: int) -> str:
        path = self._paths[row]
        text = self.entry_label(path)
        duration = self.duration_of(path)
        if duration:
            text = f"{text} — {format_time(duration)}"
        if row == self._current_row:
            text = f"{NOW_PLAYING_MARK} {text}"
        return text

    # -- cambios -----------------------------------------------------------
    def _emit_row_changed(self, row: int):
        if 0 <= row < len(self._paths):
            index = self.index(row)
            self.dataChanged.emit(index, index)

    def _emit_rows_with_key(self, key: str):
        for row, p in enumerate(self._paths):
            if path_key(p) == key:
                self._emit_row_changed(row)

    def append_paths(self, paths) -> int:
        paths = list(paths)
        if not paths:
            return 0
        first = len(self._paths)
        self.beginInsertRows(QModelIndex(), first, first + len(paths) - 1)
        for p in paths:
            self._paths.append(p)
            self._ids.append(self._next_id)
            self._next_id += 1
        self.endInsertRows()
        return len(paths)

    def remove_rows(self, rows) -> list:
        """Quita estas filas (indices validos, sin repetir). Devuelve las
        quitadas en orden ascendente. Si la actual estaba, queda en -1."""
        rows = sorted({r for r in rows if 0 <= r < len(self._paths)})
        if not rows:
            return []
        if self._current_row in rows:
            self._current_row = -1
        elif self._current_row != -1:
            self._current_row -= sum(1 for r in rows if r < self._current_row)
        # Bloques contiguos, de abajo hacia arriba.
        blocks = []
        for r in rows:
            if blocks and blocks[-1][1] == r - 1:
                blocks[-1][1] = r
            else:
                blocks.append([r, r])
        for start, end in reversed(blocks):
            self.beginRemoveRows(QModelIndex(), start, end)
            del self._paths[start:end + 1]
            del self._ids[start:end + 1]
            self.endRemoveRows()
        return rows

    def clear(self):
        self.beginResetModel()
        self._paths = []
        self._ids = []
        self._current_row = -1
        self.endResetModel()

    def reorder(self, new_order):
        """new_order[i] = fila VIEJA que pasa a la posicion i (la misma
        convencion que PlaylistOrder.reorder). Conserva la seleccion y los
        indices persistentes (layoutChanged + changePersistentIndexList)."""
        new_order = list(new_order)
        if sorted(new_order) != list(range(len(self._paths))):
            raise ValueError("new_order no es una permutacion de la lista")
        if new_order == list(range(len(self._paths))):
            return
        remap = {old: new for new, old in enumerate(new_order)}
        self.layoutAboutToBeChanged.emit()
        old_persistent = self.persistentIndexList()
        self._paths = [self._paths[i] for i in new_order]
        self._ids = [self._ids[i] for i in new_order]
        if self._current_row != -1:
            self._current_row = remap[self._current_row]
        self.changePersistentIndexList(
            old_persistent,
            [self.index(remap[i.row()]) if i.isValid() else QModelIndex() for i in old_persistent],
        )
        self.layoutChanged.emit()

    def set_current_row(self, row: int):
        old, self._current_row = self._current_row, row
        if old != row:
            self._emit_row_changed(old)
        self._emit_row_changed(row)

    def set_duration(self, path: str, duration_ms: int, overwrite: bool = False) -> bool:
        key = path_key(path)
        if duration_ms <= 0 or (key in self._durations and not overwrite):
            return False
        self._durations[key] = duration_ms
        self._emit_rows_with_key(key)
        return True

    def set_tags(self, path: str, artist: str, title: str):
        key = path_key(path)
        self._tags[key] = (artist, title)
        self._emit_rows_with_key(key)

    def icy_title(self, url: str):
        return self._icy_titles.get(url)

    def set_icy_title(self, url: str, title: str) -> bool:
        if not title or self._icy_titles.get(url) == title:
            return False
        self._icy_titles[url] = title
        for row, p in enumerate(self._paths):
            if p == url:
                self._emit_row_changed(row)
        return True


class PlaylistFilterProxy(QSortFilterProxyModel):
    """Filtro del buscador: muestra las filas cuyo texto o ruta contienen
    el texto buscado (sin distinguir mayusculas). No ordena: el orden es el
    de la lista."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._needle = ""

    def needle(self) -> str:
        return self._needle

    def set_needle(self, text: str):
        needle = (text or "").strip().casefold()
        if needle == self._needle:
            return
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.9
            self.beginFilterChange()
            self._needle = needle
            self.endFilterChange()
        else:
            self._needle = needle
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._needle:
            return True
        index = self.sourceModel().index(source_row, 0, source_parent)
        return self._needle in (index.data(SEARCH_ROLE) or "")


class PlaylistView(QListView):
    """Vista de la lista: seleccion multiple y reordenar arrastrando. En
    vez de dejar que Qt mueva los datos (con un proxy de filtro en medio,
    y sin depender de que version de Qt use moveRows o mime data), el
    soltar se traduce a filas del modelo fuente y se emite rowsDropped
    (filas fuente arrastradas, fila fuente de destino estilo list.insert
    antes de quitar las arrastradas)."""

    rowsDropped = Signal(list, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    # -- filas fuente <-> vista ------------------------------------------
    def _proxy(self):
        model = self.model()
        return model if isinstance(model, QSortFilterProxyModel) else None

    def to_source_row(self, view_index) -> int:
        if not view_index.isValid():
            return -1
        proxy = self._proxy()
        return proxy.mapToSource(view_index).row() if proxy is not None else view_index.row()

    def view_index_for_source_row(self, row: int):
        proxy = self._proxy()
        if proxy is None:
            return self.model().index(row, 0)
        return proxy.mapFromSource(proxy.sourceModel().index(row, 0))

    def source_row_at(self, pos) -> int:
        return self.to_source_row(self.indexAt(pos))

    def selected_source_rows(self) -> list:
        return sorted({self.to_source_row(i) for i in self.selectionModel().selectedIndexes()} - {-1})

    def current_source_row(self) -> int:
        return self.to_source_row(self.currentIndex())

    def set_current_source_row(self, row: int):
        index = self.view_index_for_source_row(row)
        if index.isValid():
            self.setCurrentIndex(index)

    def set_source_rows_selected(self, rows):
        selection = self.selectionModel()
        selection.clearSelection()
        for row in rows:
            index = self.view_index_for_source_row(row)
            if index.isValid():
                selection.select(index, QItemSelectionModel.SelectionFlag.Select)

    def drop_target_row(self, pos) -> int:
        """Fila fuente antes de la que se insertaria lo arrastrado si se
        suelta en `pos` (coordenadas del viewport)."""
        index = self.indexAt(pos)
        source_count = self._source_count()
        if not index.isValid():
            return source_count
        rect = self.visualRect(index)
        row = self.to_source_row(index)
        return row if pos.y() < rect.center().y() else row + 1

    def _source_count(self) -> int:
        proxy = self._proxy()
        model = proxy.sourceModel() if proxy is not None else self.model()
        return model.rowCount()

    def handle_internal_drop(self, pos) -> bool:
        rows = self.selected_source_rows()
        if not rows:
            return False
        self.rowsDropped.emit(rows, self.drop_target_row(pos))
        return True

    def dropEvent(self, event):
        if event.source() is self:
            self.handle_internal_drop(event.position().toPoint())
            # CopyAction: QAbstractItemView::startDrag no borra nada despues
            # (el movimiento ya lo hizo el controlador).
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.stopAutoScroll()
            self.setState(QAbstractItemView.State.NoState)
            self.viewport().update()
            return
        super().dropEvent(event)


def moved_order(count: int, rows, target: int) -> list:
    """Nuevo orden (new_order[i] = fila vieja en la posicion i) tras mover
    las filas `rows` (en su orden relativo) para que queden antes de la
    fila `target` (indice previo al movimiento; count = al final)."""
    moving = sorted({r for r in rows if 0 <= r < count})
    target = max(0, min(count, target))
    moving_set = set(moving)
    rest = [r for r in range(count) if r not in moving_set]
    insert_at = sum(1 for r in rest if r < target)
    return rest[:insert_at] + moving + rest[insert_at:]


__all__ = [
    "DURATION_ROLE",
    "ITEM_ID_ROLE",
    "NOW_PLAYING_MARK",
    "NOW_PLAYING_ROLE",
    "PATH_ROLE",
    "PlaylistFilterProxy",
    "PlaylistModel",
    "PlaylistView",
    "SEARCH_ROLE",
    "display_name",
    "moved_order",
]
