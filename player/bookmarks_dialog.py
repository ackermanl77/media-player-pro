"""Dialogo de marcadores nombrados por archivo (BS.Player-style)."""

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .bookmarks import add_bookmark, get_bookmarks, remove_bookmark, rename_bookmark
from .formats import format_time


class BookmarksDialog(QDialog):
    def __init__(self, player, video_path: str, parent=None):
        super().__init__(parent)
        self.player = player
        self.video_path = video_path

        self.setWindowTitle("Marcadores")
        self.resize(420, 320)

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._go_to_selected)
        layout.addWidget(self.list_widget, stretch=1)

        buttons = QHBoxLayout()
        btn_add = QPushButton("Agregar aquí")
        btn_add.clicked.connect(self._add_bookmark)
        buttons.addWidget(btn_add)

        btn_goto = QPushButton("Ir a")
        btn_goto.clicked.connect(self._go_to_selected)
        buttons.addWidget(btn_goto)

        btn_rename = QPushButton("Renombrar")
        btn_rename.clicked.connect(self._rename_selected)
        buttons.addWidget(btn_rename)

        btn_remove = QPushButton("Eliminar")
        btn_remove.clicked.connect(self._remove_selected)
        buttons.addWidget(btn_remove)

        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)

        layout.addLayout(buttons)

        self._reload()

    def _reload(self):
        self.list_widget.clear()
        for b in get_bookmarks(self.video_path):
            item = QListWidgetItem(f"{b['name']} — {format_time(b['position_ms'])}")
            self.list_widget.addItem(item)

    def _add_bookmark(self):
        position_ms = self.player.get_time_ms()
        default_name = f"Marcador {format_time(position_ms)}"
        name, ok = QInputDialog.getText(self, "Nuevo marcador", "Nombre:", text=default_name)
        if ok and name.strip():
            add_bookmark(self.video_path, name.strip(), position_ms)
            self._reload()

    def _go_to_selected(self):
        row = self.list_widget.currentRow()
        bookmarks = get_bookmarks(self.video_path)
        if 0 <= row < len(bookmarks):
            self.player.set_time_ms(bookmarks[row]["position_ms"])

    def _rename_selected(self):
        row = self.list_widget.currentRow()
        bookmarks = get_bookmarks(self.video_path)
        if not 0 <= row < len(bookmarks):
            return
        new_name, ok = QInputDialog.getText(self, "Renombrar marcador", "Nombre:", text=bookmarks[row]["name"])
        if ok and new_name.strip():
            rename_bookmark(self.video_path, row, new_name.strip())
            self._reload()

    def _remove_selected(self):
        row = self.list_widget.currentRow()
        bookmarks = get_bookmarks(self.video_path)
        if not 0 <= row < len(bookmarks):
            return
        reply = QMessageBox.question(self, "Eliminar marcador", f"¿Eliminar \"{bookmarks[row]['name']}\"?")
        if reply == QMessageBox.StandardButton.Yes:
            remove_bookmark(self.video_path, row)
            self._reload()
