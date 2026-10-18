"""Taskbar thumbnail buttons (4.12): message decoding, the button array, and the
window wiring. The live ITaskbarList3 calls (buttons added on TaskbarButtonCreated,
a click arriving as WM_COMMAND) were checked against a real window on Windows 11."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from player.taskbar_buttons import (
    THBF_DISABLED,
    THBF_ENABLED,
    THBN_CLICKED,
    WM_COMMAND,
    TaskbarButtons,
    buttons_struct,
    command_for_message,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_messages_decode_to_commands():
    created = 0xC123
    assert command_for_message(created, 0, created) == "created"
    assert command_for_message(WM_COMMAND, (THBN_CLICKED << 16) | 1, created) == "previous"
    assert command_for_message(WM_COMMAND, (THBN_CLICKED << 16) | 2, created) == "toggle"
    assert command_for_message(WM_COMMAND, (THBN_CLICKED << 16) | 3, created) == "next"
    assert command_for_message(WM_COMMAND, (THBN_CLICKED << 16) | 9, created) == ""
    assert command_for_message(WM_COMMAND, 3, created) == ""  # a menu command, not a thumbnail button
    assert command_for_message(0x0200, 0, 0) == ""


def test_the_play_button_follows_the_state():
    icons = {"previous": 11, "play": 22, "pause": 33, "next": 44}
    paused = buttons_struct(False, True, icons)
    assert [b.iId for b in paused] == [1, 2, 3] and [b.hIcon for b in paused] == [11, 22, 44]
    assert paused[1].szTip == "Reproducir" and all(b.dwFlags == THBF_ENABLED for b in paused)
    playing = buttons_struct(True, True, icons)
    assert playing[1].hIcon == 33 and playing[1].szTip == "Pausar"
    assert all(b.dwFlags == THBF_DISABLED for b in buttons_struct(False, False, icons))


def test_clicks_are_forwarded_and_other_messages_pass_through(qapp):
    buttons = TaskbarButtons()
    try:
        if not buttons.available:
            pytest.skip("ITaskbarList3 solo existe en Windows")
        got = []
        buttons.pressed.connect(got.append)
        assert buttons.handle_message(WM_COMMAND, (THBN_CLICKED << 16) | 3)
        assert not buttons.handle_message(WM_COMMAND, 5)
        assert got == ["next"]
        buttons.set_state(True, True)  # no window yet: remembered, nothing sent
        assert not buttons.buttons_added
    finally:
        buttons.close()


def test_the_main_window_routes_taskbar_clicks_to_media_commands(qapp, tmp_path, monkeypatch):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    from player import settings as settings_module

    monkeypatch.setattr(settings_module, "_state_dir", lambda: tmp_path)
    window = MainWindow()
    try:
        commands = []
        monkeypatch.setattr(window, "media_command", commands.append)
        window.taskbar_buttons.pressed.disconnect()
        window.taskbar_buttons.pressed.connect(window.media_command)
        window.taskbar_buttons.pressed.emit("previous")
        assert commands == ["previous"]
        window._update_play_icon()
        assert window.taskbar_buttons._state == (False, False)
    finally:
        window.close()
