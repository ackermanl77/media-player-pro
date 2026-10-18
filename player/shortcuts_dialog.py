"""Ayuda -> Atajos de teclado: la tabla de atajos, ahora editable (4.11).

Cada accion del registro (player/actions.py) se puede reasignar, quitar o
volver a su atajo predeterminado; los cambios se aplican al instante y la
ventana los guarda en settings.json (Settings.shortcuts: solo lo que difiere
del predeterminado). Los atajos fijos (QShortcut: flechas, teclas
multimedia...) y las filas de raton se muestran, pero no se editan. Un
atajo que ya usa otra accion o uno fijo no se asigna: se avisa cual."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .actions import NATIVE


class ShortcutsDialog(QDialog):
    def __init__(self, registry, on_changed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atajos de teclado")
        self.resize(560, 620)
        self._registry = registry
        self._on_changed = on_changed or (lambda: None)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Elige una acción, pulsa la combinación nueva y luego «Asignar». "
            "Los atajos en gris son fijos."
        ))
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Acción", "Atajo"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAccessibleName("Atajos de teclado")
        self.table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self.table)

        editor_row = QHBoxLayout()
        self.key_edit = QKeySequenceEdit(self)
        self.key_edit.setMaximumSequenceLength(1)
        self.key_edit.setAccessibleName("Atajo nuevo")
        editor_row.addWidget(self.key_edit, 1)
        self.assign_button = QPushButton("Asignar")
        self.assign_button.clicked.connect(self.assign)
        self.clear_button = QPushButton("Quitar")
        self.clear_button.clicked.connect(self.clear)
        self.default_button = QPushButton("Predeterminado")
        self.default_button.clicked.connect(self.restore_default)
        for button in (self.assign_button, self.clear_button, self.default_button):
            editor_row.addWidget(button)
        layout.addLayout(editor_row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        bottom = QHBoxLayout()
        self.reset_all_button = QPushButton("Restaurar todos")
        self.reset_all_button.clicked.connect(self.restore_all)
        bottom.addWidget(self.reset_all_button)
        bottom.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.refresh()

    # -- tabla -------------------------------------------------------------------
    def refresh(self, select_id=None) -> None:
        registry = self._registry
        rows = [(action_id, registry[action_id].text().replace("&", ""), registry[action_id].shortcut())
                for action_id in registry.ids()]
        fixed = [(None, description, sequence) for description, sequence in registry.extra_shortcuts]
        static = [(None, description, keys) for description, keys in registry.static_rows]
        self.table.setRowCount(len(rows) + len(fixed) + len(static))
        for row, (action_id, text, keys) in enumerate(rows + fixed + static):
            name = QTableWidgetItem(text)
            shown = keys.toString(NATIVE) if isinstance(keys, QKeySequence) else str(keys)
            if action_id is not None and registry.is_customized(action_id):
                shown += "  •"
            key_item = QTableWidgetItem(shown)
            for item in (name, key_item):
                item.setData(Qt.ItemDataRole.UserRole, action_id)
                if action_id is None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, key_item)
            if action_id is not None and action_id == select_id:
                self.table.selectRow(row)
        self._on_selection()

    def selected_id(self):
        items = self.table.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def select(self, action_id) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == action_id:
                self.table.selectRow(row)
                return

    def _on_selection(self) -> None:
        action_id = self.selected_id()
        enabled = action_id is not None
        for widget in (self.key_edit, self.assign_button, self.clear_button, self.default_button):
            widget.setEnabled(enabled)
        if enabled:
            self.key_edit.setKeySequence(self._registry[action_id].shortcut())

    # -- cambios -------------------------------------------------------------------
    def _apply(self, action_id, sequence: QKeySequence) -> bool:
        conflict = self._registry.conflict(sequence, action_id)
        if conflict:
            self.status.setText(f"«{sequence.toString(NATIVE)}» ya es el atajo de «{conflict}».")
            return False
        self._registry.set_shortcut(action_id, sequence)
        self.status.setText("")
        self._on_changed()
        self.refresh(select_id=action_id)
        return True

    def assign(self) -> bool:
        action_id = self.selected_id()
        if action_id is None:
            return False
        return self._apply(action_id, self.key_edit.keySequence())

    def clear(self) -> bool:
        action_id = self.selected_id()
        return action_id is not None and self._apply(action_id, QKeySequence())

    def restore_default(self) -> bool:
        action_id = self.selected_id()
        return action_id is not None and self._apply(action_id, self._registry.default_shortcut(action_id))

    def restore_all(self) -> None:
        self._registry.reset_shortcuts()
        self.status.setText("Todos los atajos volvieron a los predeterminados.")
        self._on_changed()
        self.refresh()
