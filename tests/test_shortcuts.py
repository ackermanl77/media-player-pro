"""Atajos de teclado editables (4.11): el registro, settings.json y el dialogo."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QWidget

from player.actions import ActionRegistry
from player.settings import Settings, settings_from_dict
from player.shortcuts_dialog import ShortcutsDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _registry():
    owner = QWidget()
    registry = ActionRegistry(owner)
    registry.add("play", "Reproducir", None, "Space")
    registry.add("mute", "&Silenciar", None, "M")
    registry.add("normalize", "Normalizar volumen")  # sin atajo predeterminado
    registry.add_shortcut("Right", "Adelantar 10 s", lambda: None)
    registry.register_shortcuts_on_owner()
    return owner, registry


def test_overrides_round_trip_only_what_changed(qapp):
    owner, registry = _registry()
    assert registry.overrides() == {}
    registry.set_shortcut("normalize", QKeySequence("Ctrl+Shift+N"))
    registry.set_shortcut("mute", QKeySequence())
    assert registry.overrides() == {"normalize": "Ctrl+Shift+N", "mute": ""}
    assert registry["normalize"] in owner.actions()  # active even with the menu bar hidden
    assert registry.is_customized("mute") and not registry.is_customized("play")
    _owner2, fresh = _registry()
    assert fresh.apply_overrides(registry.overrides()) == []
    assert fresh["normalize"].shortcut() == QKeySequence("Ctrl+Shift+N") and fresh["mute"].shortcut().isEmpty()
    fresh.reset_shortcuts()
    assert fresh.overrides() == {} and fresh["mute"].shortcut() == QKeySequence("M")


def test_conflicts_and_bad_saved_entries_are_refused(qapp):
    _owner, registry = _registry()
    assert registry.conflict(QKeySequence("Space"), "mute") == "Reproducir"
    assert registry.conflict(QKeySequence("Right"), "mute") == "Adelantar 10 s"  # a fixed QShortcut
    assert registry.conflict(QKeySequence("Space"), "play") is None and registry.conflict(QKeySequence()) is None
    skipped = registry.apply_overrides({"gone": "F2", "mute": "Space", "play": "not a key ++", "normalize": 5})
    assert sorted(skipped) == ["gone", "mute", "normalize", "play"]
    assert registry["mute"].shortcut() == QKeySequence("M") and registry["play"].shortcut() == QKeySequence("Space")


def test_settings_keep_only_sane_shortcut_entries():
    raw = {"shortcuts": {"mute": "Ctrl+M", "play": "", "bad key": "F1", "x": 3, "y" * 80: "F2"}}
    assert settings_from_dict(raw).shortcuts == {"mute": "Ctrl+M", "play": ""}
    assert settings_from_dict({"shortcuts": ["no"]}).shortcuts == {} and Settings().shortcuts == {}


def test_the_dialog_assigns_clears_restores_and_warns(qapp):
    _owner, registry = _registry()
    changes = []
    dialog = ShortcutsDialog(registry, on_changed=lambda: changes.append(registry.overrides()))
    assert dialog.table.rowCount() == 4  # three actions + the fixed one
    dialog.select("mute")
    dialog.key_edit.setKeySequence(QKeySequence("Ctrl+Alt+M"))
    assert dialog.assign() and registry["mute"].shortcut() == QKeySequence("Ctrl+Alt+M")
    assert changes[-1] == {"mute": "Ctrl+Alt+M"}
    dialog.select("mute")
    dialog.key_edit.setKeySequence(QKeySequence("Space"))
    assert not dialog.assign() and "Reproducir" in dialog.status.text()  # conflict: nothing changed
    assert registry["mute"].shortcut() == QKeySequence("Ctrl+Alt+M")
    dialog.select("mute")
    assert dialog.restore_default() and registry["mute"].shortcut() == QKeySequence("M")
    dialog.select("play")
    assert dialog.clear() and registry["play"].shortcut().isEmpty()
    dialog.restore_all()
    assert registry.overrides() == {} and changes[-1] == {}
    fixed_row = dialog.table.item(3, 0)
    assert fixed_row.text() == "Adelantar 10 s" and dialog.select("nothing") is None


def test_the_main_window_saves_and_restores_changed_shortcuts(qapp, tmp_path, monkeypatch):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    from player import settings as settings_module

    monkeypatch.setattr(settings_module, "_state_dir", lambda: tmp_path)
    window = MainWindow()
    try:
        window.show_shortcuts_help()
        dialog = window.shortcuts_dialog
        dialog.select("stop")
        dialog.key_edit.setKeySequence(QKeySequence("Ctrl+Alt+S"))
        assert dialog.assign()
        assert settings_module.load_settings().shortcuts == {"stop": "Ctrl+Alt+S"}  # saved right away
        dialog.close()
    finally:
        window.close()
    again = MainWindow()
    try:
        assert again.action_registry["stop"].shortcut() == QKeySequence("Ctrl+Alt+S")
    finally:
        again.close()
