"""Registro de acciones de la ventana principal.

Cada comando del reproductor es un QAction con un id estable (su
objectName), texto, atajo, tooltip y slot. El mismo QAction alimenta los
menus, el menu contextual del video, los botones de la barra
(QToolButton.setDefaultAction) y la tabla de Ayuda -> Atajos de teclado,
asi que texto, atajo y estado (marcado/no marcado) tienen una sola fuente.

Los atajos que no son de un menu (flechas, teclas multimedia, Esc) son
QShortcut registrados aqui con su descripcion, para que la ayuda los
muestre igual."""

from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu

NATIVE = QKeySequence.SequenceFormat.NativeText


class ActionRegistry:
    def __init__(self, owner):
        self._owner = owner
        self._actions = {}  # id -> QAction, en orden de registro
        self.extra_shortcuts = []  # (descripcion, QKeySequence) de los QShortcut
        # Filas fijas de la ayuda (raton, atajos que dependen del foco).
        self.static_rows = []

    # -- acciones ------------------------------------------------------------
    def add(self, action_id, text, slot=None, shortcut=None, checkable=False, tooltip=None) -> QAction:
        if action_id in self._actions:
            raise ValueError(f"accion repetida: {action_id}")
        action = QAction(text, self._owner)
        action.setObjectName(action_id)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        if tooltip:
            action.setToolTip(tooltip)
        if slot is not None:
            action.triggered.connect(slot)
        self._actions[action_id] = action
        return action

    def __getitem__(self, action_id) -> QAction:
        return self._actions[action_id]

    def __contains__(self, action_id) -> bool:
        return action_id in self._actions

    def get(self, action_id):
        return self._actions.get(action_id)

    def ids(self) -> list:
        return list(self._actions)

    def actions(self) -> list:
        return list(self._actions.values())

    # -- menus -----------------------------------------------------------------
    def populate(self, menu: QMenu, items):
        """Agrega a `menu` una lista de ids de accion, QAction, QMenu (como
        submenu) o None (separador)."""
        for item in items:
            if item is None:
                menu.addSeparator()
            elif isinstance(item, QMenu):
                menu.addMenu(item)
            elif isinstance(item, QAction):
                menu.addAction(item)
            else:
                menu.addAction(self._actions[item])
        return menu

    # -- atajos ----------------------------------------------------------------
    def add_shortcut(self, key, description, slot) -> QShortcut:
        sequence = QKeySequence(key)
        shortcut = QShortcut(sequence, self._owner, activated=slot)
        self.extra_shortcuts.append((description, sequence))
        return shortcut

    def register_shortcuts_on_owner(self):
        """Qt solo activa el atajo de un QAction si alguno de sus widgets
        asociados esta visible, y en pantalla completa la barra de menus se
        oculta: agregar las acciones con atajo tambien a la propia ventana
        las mantiene activas siempre (es el mismo QAction, no se duplica ni
        se vuelve ambiguo)."""
        owned = set(self._owner.actions())
        for action in self._actions.values():
            if not action.shortcut().isEmpty() and action not in owned:
                self._owner.addAction(action)

    def shortcut_rows(self) -> list:
        """(descripcion, atajo) de todo lo que tiene atajo, tal como esta
        registrado: acciones, QShortcut y las filas fijas."""
        rows = [
            (action.text().replace("&", ""), action.shortcut().toString(NATIVE))
            for action in self._actions.values()
            if not action.shortcut().isEmpty()
        ]
        rows += [(description, sequence.toString(NATIVE)) for description, sequence in self.extra_shortcuts]
        rows += list(self.static_rows)
        return rows
