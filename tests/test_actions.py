"""Registro de acciones (player/actions.py): una sola fuente para menus,
menu contextual, botones y la ayuda de atajos. Qt "offscreen", sin VLC
para el registro en si; las pruebas sobre MainWindow se omiten sin VLC."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from player.actions import ActionRegistry


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_registry_builds_actions_menus_and_the_shortcut_table(qapp):
    owner = QWidget()
    registry = ActionRegistry(owner)
    fired = []
    play = registry.add("play", "Reproducir", lambda: fired.append("play"), "Space", tooltip="Reproducir")
    registry.add("open", "&Abrir...", None, QKeySequence.StandardKey.Open)
    registry.add("about", "Acerca de...")
    with pytest.raises(ValueError):
        registry.add("play", "Otra")
    assert registry["play"] is play and play.objectName() == "play" and "about" in registry
    assert registry.ids() == ["play", "open", "about"]

    submenu = QMenu("Sub")
    extra = QAction("Suelta", owner)
    menu = registry.populate(QMenu(), ["play", None, submenu, extra, "about"])
    items = menu.actions()
    assert items[0] is play and items[1].isSeparator() and items[2].menu() is submenu
    assert items[3] is extra and items[4] is registry["about"]

    registry.add_shortcut("Shift+Right", "Adelantar 1 s", lambda: None)
    registry.static_rows = [("Pantalla completa", "Doble clic")]
    registry.register_shortcuts_on_owner()
    registry.register_shortcuts_on_owner()  # idempotente
    assert owner.actions().count(play) == 1 and registry["about"] not in owner.actions()
    rows = registry.shortcut_rows()
    assert rows[0] == ("Reproducir", QKeySequence("Space").toString(QKeySequence.SequenceFormat.NativeText))
    assert rows[1][0] == "Abrir..."  # sin el "&" del mnemonico
    assert ("Adelantar 1 s", QKeySequence("Shift+Right").toString(QKeySequence.SequenceFormat.NativeText)) in rows
    assert rows[-1] == ("Pantalla completa", "Doble clic")
    play.trigger()
    assert fired == ["play"]


def test_main_window_menus_and_context_menu_use_the_registered_actions(qapp):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    window = MainWindow()
    try:
        registry = window.action_registry
        # Toda accion con atajo de los menus esta en el registro (y por eso
        # en la ayuda y activa en pantalla completa).
        def walk(menu):
            for action in menu.actions():
                if action.menu() is not None:
                    yield from walk(action.menu())
                else:
                    yield action

        menu_actions = [a for m in window.menuBar().actions() for a in walk(m.menu())]
        registered = set(registry.actions())
        for action in menu_actions:
            if not action.shortcut().isEmpty():
                assert action in registered, action.text()
                assert action in window.actions(), action.text()
        context = [a for a in window.video_context_menu.actions() if not a.isSeparator() and a.menu() is None]
        assert set(context) <= registered
        assert window.btn_play.defaultAction() is registry["play_pause"]
        assert window.fullscreen_controller.buttons["play"].defaultAction() is registry["play_pause"]
        texts = {text for text, _keys in window.shortcut_rows()}
        assert {"Detener", "Abrir archivos...", "Captura rápida", "Atajos de teclado..."} <= texts
    finally:
        window.close()
