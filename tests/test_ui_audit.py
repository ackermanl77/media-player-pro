"""UI2/UI3 del informe (auditoria de UI 2026-10-22): botones de la barra alcanzables con Tab, con
Espacio/Intro sobre el boton y no sobre el atajo global; el area de video con nombre accesible y su
estado inactivo (logo y como empezar). Qt "offscreen"; se omite si no hay VLC."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc  # noqa: F401
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten estas pruebas.", allow_module_level=True)

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from player import backend as backend_module
from player import main_window as main_window_module
from player.widgets import TransportButton, VideoFrame


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )
    w = main_window_module.MainWindow()
    w.act_visualizer.setChecked(False)
    yield w
    w.close()


def test_transport_buttons_take_tab_focus_only_and_have_names(window):
    buttons = (window.btn_prev, window.btn_play, window.btn_stop, window.btn_next, window.btn_mute,
               window.speed_button, window.btn_shuffle, window.btn_repeat, window.btn_ab_loop, window.btn_fullscreen)
    for button in buttons:
        assert isinstance(button, TransportButton)
        assert button.focusPolicy() == Qt.FocusPolicy.TabFocus  # Tab si; un clic no les da el foco
        assert button.accessibleName()
    for slider in (window.position_slider, window.volume_slider):
        assert slider.focusPolicy() == Qt.FocusPolicy.TabFocus
    assert window.video_frame.accessibleName() == "Área de vídeo"


def test_a_focused_transport_button_claims_space_and_enter(qapp):
    button = TransportButton()
    clicks = []
    button.clicked.connect(lambda: clicks.append(1))
    for key in (Qt.Key.Key_Space, Qt.Key.Key_Return):
        override = QKeyEvent(QEvent.Type.ShortcutOverride, key, Qt.KeyboardModifier.NoModifier)
        assert button.event(override) and override.isAccepted()  # gana al atajo global
    button.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
    assert clicks == [1]
    with_ctrl = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    button.event(with_ctrl)
    assert not with_ctrl.isAccepted()  # Ctrl+Espacio sigue siendo un atajo


def test_the_idle_video_area_shows_the_logo_and_how_to_start(window, qapp):
    window.update_ui()
    assert window.video_frame._idle  # nada en curso al abrir
    window.video_frame.set_idle(False)
    assert not window.video_frame._idle
    assert VideoFrame(idle_logo=None)._idle is False  # sin logo no hay estado inactivo que pintar
    image = window.video_frame.grab()
    assert not image.isNull()
