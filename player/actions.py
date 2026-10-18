"""Registro de acciones de la ventana principal.

Cada comando del reproductor es un QAction con un id estable (su
objectName), texto, atajo, tooltip y slot. El mismo QAction alimenta los
menus, el menu contextual del video, los botones de la barra
(QToolButton.setDefaultAction) y la tabla de Ayuda -> Atajos de teclado,
asi que texto, atajo y estado (marcado/no marcado) tienen una sola fuente.

Los atajos que no son de un menu (flechas, teclas multimedia, Esc) son
QShortcut registrados aqui con su descripcion, para que la ayuda los
muestre igual.

Los atajos de las acciones se pueden cambiar (4.11, player/shortcuts_dialog.py):
el registro recuerda el predeterminado de cada una, y overrides() / apply_overrides()
llevan solo lo cambiado a settings.json (como texto portable, "" = sin atajo)."""

from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu

NATIVE = QKeySequence.SequenceFormat.NativeText


class ActionRegistry:
    def __init__(self, owner):
        self._owner = owner
        self._actions = {}  # id -> QAction, en orden de registro
        self._defaults = {}  # id -> QKeySequence predeterminado (vacio = sin atajo)
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
        self._defaults[action_id] = QKeySequence(action.shortcut())
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

    # -- atajos editables (4.11) -------------------------------------------------
    def default_shortcut(self, action_id) -> QKeySequence:
        return QKeySequence(self._defaults[action_id])

    def is_customized(self, action_id) -> bool:
        return self._actions[action_id].shortcut() != self._defaults[action_id]

    def set_shortcut(self, action_id, sequence) -> None:
        action = self._actions[action_id]
        action.setShortcut(QKeySequence(sequence))
        if not action.shortcut().isEmpty() and action not in self._owner.actions():
            self._owner.addAction(action)  # ver register_shortcuts_on_owner()

    def conflict(self, sequence, except_id=None):
        """El texto de lo que ya usa `sequence` (otra accion o un atajo fijo), o None."""
        sequence = QKeySequence(sequence)
        if sequence.isEmpty():
            return None
        for action_id, action in self._actions.items():
            if action_id != except_id and action.shortcut() == sequence:
                return action.text().replace("&", "")
        for description, fixed in self.extra_shortcuts:
            if fixed == sequence:
                return description
        return None

    def overrides(self) -> dict:
        """{id: atajo} de las acciones cuyo atajo difiere del predeterminado
        ("" = quitado), en formato portable (lo que se guarda en settings.json)."""
        return {
            action_id: action.shortcut().toString(QKeySequence.SequenceFormat.PortableText)
            for action_id, action in self._actions.items()
            if action.shortcut() != self._defaults[action_id]
        }

    def apply_overrides(self, overrides) -> list:
        """Aplica los atajos guardados. Se ignoran ids que ya no existen, textos que
        no son un atajo valido y los que chocan con otro (se devuelven sus ids)."""
        skipped = []
        for action_id, text in (overrides or {}).items():
            if action_id not in self._actions or not isinstance(text, str):
                skipped.append(action_id)
                continue
            sequence = QKeySequence(text, QKeySequence.SequenceFormat.PortableText)
            # Unparsable text gives a sequence that prints as "" but isn't isEmpty() (it holds an
            # invalid key), so the printed form is what tells a real shortcut from garbage.
            if text and not sequence.toString(QKeySequence.SequenceFormat.PortableText):
                skipped.append(action_id)
                continue
            if self.conflict(sequence, action_id):
                skipped.append(action_id)
                continue
            self.set_shortcut(action_id, sequence)
        return skipped

    def reset_shortcuts(self) -> None:
        for action_id, action in self._actions.items():
            action.setShortcut(QKeySequence(self._defaults[action_id]))
        self.register_shortcuts_on_owner()

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
