"""Controles multimedia del sistema (SMTC, 4.12): botones -> comandos, sin pywinrt, y la
ventana (teclas multimedia que llegan dos veces se cuentan una)."""
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from player import media_controls
from player.media_controls import SystemMediaControls


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_without_pywinrt_everything_is_a_quiet_no_op(qapp, monkeypatch):
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def no_winrt(name, *args, **kwargs):
        if name.startswith("winrt"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_winrt)
    controls = SystemMediaControls()
    assert not controls.available
    controls.set_status("playing")
    controls.set_media("x")
    controls.close()


def test_buttons_become_commands_on_the_qt_side(qapp):
    winrt_media = pytest.importorskip("winrt.windows.media")
    controls = SystemMediaControls()
    if not controls.available:
        pytest.skip("SMTC no disponible en esta sesion de Windows")
    got = []
    controls.pressed.connect(got.append)
    Button = winrt_media.SystemMediaTransportControlsButton
    for button in (Button.PLAY, Button.PAUSE, Button.NEXT, Button.PREVIOUS, Button.STOP, Button.CHANNEL_UP):
        controls._on_button(None, types.SimpleNamespace(button=button))
    qapp.processEvents()
    assert got == ["play", "pause", "next", "previous", "stop"]  # unknown buttons are ignored
    for status in (media_controls.PLAYING, media_controls.PAUSED, media_controls.STOPPED, media_controls.CLOSED):
        controls.set_status(status)
    controls.set_media("Película", "Reproductor", video=True)
    controls.set_media("Canción", "Artista", video=False)
    controls.close()
    controls.close()  # idempotent
    assert not controls.available


def test_the_window_counts_a_doubled_media_key_once(qapp, monkeypatch):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    window = MainWindow()
    try:
        calls = []
        monkeypatch.setattr(window, "toggle_play_pause", lambda: calls.append("toggle"))
        monkeypatch.setattr(window, "_media_key_pause", lambda: calls.append("pause"))
        monkeypatch.setattr(window, "play_next", lambda auto: calls.append(("next", auto)))
        clock = [100.0]
        monkeypatch.setattr("player.main_window.time.monotonic", lambda: clock[0])
        assert window.media_command("toggle")
        clock[0] += 0.1
        assert not window.media_command("pause")  # the same press again, through SMTC
        clock[0] += 0.05
        assert window.media_command("next")  # another key is not a duplicate
        clock[0] += 1.0
        assert window.media_command("pause")
        assert calls == ["toggle", ("next", False), "pause"]
        # SMTC button presses reach the same handler.
        clock[0] += 1.0
        window.system_media.pressed.emit("toggle")
        qapp.processEvents()
        assert calls[-1] == "toggle"
    finally:
        window.close()
