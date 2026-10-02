"""Verifica la logica de 'accion al terminar la lista' (apagar/hibernar/
reiniciar/salir) SIN ejecutar nunca un apagado/reinicio real: subprocess.run
se reemplaza por un doble que solo registra la llamada. Se omite si no hay
VLC instalado."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc  # noqa: F401
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten estas pruebas.", allow_module_level=True)

from PySide6.QtWidgets import QApplication

from player import main_window as main_window_module
from player.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def fake_subprocess_run(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main_window_module.subprocess, "run",
        lambda cmd, **kwargs: calls.append(cmd),
    )
    return calls


def test_default_action_is_none_and_does_nothing(qapp, fake_subprocess_run):
    window = MainWindow()
    try:
        assert window.on_finish_action == "none"
        window._handle_playlist_finished()
        assert fake_subprocess_run == []
    finally:
        window.close()


def test_exit_action_closes_the_window_without_touching_the_system(qapp, fake_subprocess_run):
    window = MainWindow()
    window.show()
    assert window.isVisible()
    window.on_finish_action = "exit"
    window._handle_playlist_finished()
    assert fake_subprocess_run == []
    assert not window.isVisible()


windows_only = pytest.mark.skipif(not sys.platform.startswith("win"), reason="shutdown.exe es de Windows")


@windows_only
@pytest.mark.parametrize("action, command", [
    ("shutdown", ["shutdown", "/s", "/t", "0"]),
    ("hibernate", ["shutdown", "/h"]),
    ("restart", ["shutdown", "/r", "/t", "0"]),
])
def test_power_actions_wait_for_an_in_app_countdown(qapp, fake_subprocess_run, action, command):
    # Antes: hibernar era inmediato y apagar/reiniciar solo se cancelaban con
    # "shutdown /a" en una consola. Ahora nada se ejecuta hasta que termina
    # una cuenta regresiva propia, cancelable.
    window = MainWindow()
    try:
        window.on_finish_action = action
        window._handle_playlist_finished()
        dialog = window._power_dialog
        assert dialog is not None and dialog.isVisible()
        assert fake_subprocess_run == []
        assert dialog.btn_cancel.isDefault()
        assert "60 s" in dialog.label.text()
        # La accion se consume: no se repite al terminar otra lista.
        assert window.on_finish_action == "none"
        for _ in range(59):
            dialog.tick()
        assert fake_subprocess_run == []
        assert "1 s" in dialog.label.text()
        dialog.tick()
        assert fake_subprocess_run == [command]
    finally:
        window.close()


@windows_only
def test_cancelling_the_countdown_runs_nothing(qapp, fake_subprocess_run):
    window = MainWindow()
    try:
        window.on_finish_action = "shutdown"
        window._handle_playlist_finished()
        dialog = window._power_dialog
        dialog.btn_cancel.click()
        for _ in range(70):
            dialog.tick()
        assert fake_subprocess_run == []
        assert window._power_dialog is None
        assert "cancelada" in window.statusBar().currentMessage()
    finally:
        window.close()


@windows_only
def test_shutdown_now_button_skips_the_wait(qapp, fake_subprocess_run):
    window = MainWindow()
    try:
        window.on_finish_action = "restart"
        window._handle_playlist_finished()
        window._power_dialog.btn_now.click()
        assert fake_subprocess_run == [["shutdown", "/r", "/t", "0"]]
    finally:
        window.close()
