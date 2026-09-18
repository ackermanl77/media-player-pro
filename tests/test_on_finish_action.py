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


def test_shutdown_action_calls_shutdown_with_a_delay(qapp, fake_subprocess_run):
    window = MainWindow()
    try:
        window.on_finish_action = "shutdown"
        window._handle_playlist_finished()
        assert fake_subprocess_run == [["shutdown", "/s", "/t", "60"]]
    finally:
        window.close()


def test_hibernate_action_calls_shutdown_h(qapp, fake_subprocess_run):
    window = MainWindow()
    try:
        window.on_finish_action = "hibernate"
        window._handle_playlist_finished()
        assert fake_subprocess_run == [["shutdown", "/h"]]
    finally:
        window.close()


def test_restart_action_calls_shutdown_with_a_delay(qapp, fake_subprocess_run):
    window = MainWindow()
    try:
        window.on_finish_action = "restart"
        window._handle_playlist_finished()
        assert fake_subprocess_run == [["shutdown", "/r", "/t", "60"]]
    finally:
        window.close()
