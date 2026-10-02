"""MainWindow: pantalla completa (atajos, barra de estado, superpuestas,
cursor) y persistencia de ajustes/sesion entre ejecuciones. Qt "offscreen"
y libVLC real con salidas dummy; sin simular teclado ni mouse (se llaman los
mismos metodos/slots que dispararia la interaccion). Path.home() apunta a
una carpeta temporal (tests/conftest.py). Se omite si no hay VLC."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc  # noqa: F401
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten estas pruebas.", allow_module_level=True)

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication

from player import backend as backend_module
from player import main_window as main_window_module
from player import settings as settings_module
from player.main_window import MainWindow, floating_controls_rect, osd_rect


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def make_window(qapp, monkeypatch):
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )
    windows = []

    def make():
        w = MainWindow()
        windows.append(w)
        return w

    yield make
    for w in windows:
        w.close()


# ---------------------------------------------------- pantalla completa
def _shortcut_actions(window):
    return [a for a in window.findChildren(QAction) if not a.shortcut().isEmpty()]


def test_every_menu_shortcut_stays_active_with_the_menu_bar_hidden(make_window):
    window = make_window()
    actions = _shortcut_actions(window)
    shortcuts = {a.shortcut().toString() for a in actions}
    assert {"Space", "F", "M", ".", "B", "G", "H", "Ctrl+O", "Ctrl+U", "Ctrl+Right", "Ctrl+Left"} <= shortcuts
    window.show()
    window.toggle_fullscreen()
    try:
        assert window.menuBar().isHidden()
        # Registrados en la propia ventana (visible): Qt los sigue
        # resolviendo aunque la barra de menus este oculta.
        for action in actions:
            assert action in window.actions(), action.text()
    finally:
        window._exit_fullscreen()


def test_fullscreen_hides_and_restores_the_status_bar(make_window):
    window = make_window()
    window.show()
    assert not window.statusBar().isHidden()
    window.toggle_fullscreen()
    try:
        assert window.statusBar().isHidden()
    finally:
        window._exit_fullscreen()
    assert not window.statusBar().isHidden()
    assert not window.menuBar().isHidden()


def test_status_messages_go_to_the_osd_while_fullscreen(make_window):
    window = make_window()
    window.show()
    window.statusBar().showMessage("fuera de pantalla completa")
    assert window._osd_label.isHidden()
    window.toggle_fullscreen()
    try:
        window.statusBar().showMessage("Reproduciendo: ðŸŽ¬ video.mkv")
        assert not window._osd_label.isHidden()
        assert window._osd_label.text() == "Reproduciendo: ðŸŽ¬ video.mkv"
    finally:
        window._exit_fullscreen()


def test_osd_and_controls_live_in_top_level_windows_above_the_video(make_window):
    window = make_window()
    window.show()
    for overlay in (window._osd_overlay, window.fullscreen.overlay):
        # No es hijo de video_frame (cuya superficie tapa libVLC) sino una
        # ventana propia, duena la ventana principal.
        assert overlay.isWindow()
        assert overlay.parentWidget() is window
        assert overlay.windowFlags() & Qt.WindowType.Tool
        assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert window._osd_label.parentWidget() is window._osd_overlay
    assert window._osd_overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    window._show_osd("+5s")
    assert window._osd_overlay.isVisible()
    frame = window._video_frame_global_rect()
    assert frame.contains(window._osd_overlay.geometry().center())
    window._osd_timer.timeout.emit()
    assert window._osd_overlay.isHidden() and window._osd_label.isHidden()


def test_osd_overlay_is_not_shown_while_the_window_is_hidden(make_window):
    window = make_window()  # nunca se muestra
    window._show_osd("Volumen: 50%")
    assert not window._osd_label.isHidden()  # el estado del mensaje si cambia
    assert window._osd_overlay.isHidden()    # pero no aparece una ventana suelta


def test_overlays_hide_when_the_app_is_deactivated_or_minimized(make_window):
    window = make_window()
    window.show()
    window.toggle_fullscreen()
    try:
        window._show_osd("x")
        assert window.fullscreen.overlay.isVisible() and window._osd_overlay.isVisible()
        window._on_application_state_changed(Qt.ApplicationState.ApplicationInactive)
        assert window.fullscreen.overlay.isHidden() and window._osd_overlay.isHidden()
        window.fullscreen.on_mouse_activity()
        assert window.fullscreen.overlay.isVisible()
        window.showMinimized()
        window.changeEvent(QEvent(QEvent.Type.WindowStateChange))
        assert window.fullscreen.overlay.isHidden()
    finally:
        window.showNormal()
        window._exit_fullscreen()


def test_cursor_hides_when_idle_in_fullscreen_and_comes_back_on_activity(make_window):
    window = make_window()
    window.show()
    window.toggle_fullscreen()
    try:
        window.fullscreen.idle_timer.timeout.emit()
        assert window.video_frame.cursor().shape() == Qt.CursorShape.BlankCursor
        window.fullscreen.on_mouse_activity()
        assert window.video_frame.cursor().shape() != Qt.CursorShape.BlankCursor
        window.fullscreen.idle_timer.timeout.emit()
    finally:
        window._exit_fullscreen()
    assert window.video_frame.cursor().shape() != Qt.CursorShape.BlankCursor


def test_overlay_geometry_helpers():
    frame = QRect(100, 50, 800, 450)
    osd = osd_rect(frame, 200, 40)
    assert osd == QRect(400, 74, 200, 40)
    assert osd_rect(frame, 2000, 40).width() == 800  # nunca mas ancho que el video
    assert floating_controls_rect(frame, 90) == QRect(100, 410, 800, 90)
    assert floating_controls_rect(QRect(0, 0, 300, 50), 90).height() == 50


# ------------------------------------------------ ajustes y sesion
def test_settings_survive_a_restart(make_window):
    window = make_window()
    window.resize(700, 450)
    window.volume_slider.setValue(35)
    window.toggle_mute()
    window._set_rate(1.5)
    window._cycle_repeat_mode()  # none -> all
    window.act_shuffle.setChecked(True)
    window.act_visualizer.setChecked(False)
    next(a for a in window.menu_sub_size.actions() if a.data() == 150).trigger()
    next(a for a in window.menu_zoom.actions() if a.data() == 2.0).trigger()
    window.open_equalizer()
    window.equalizer_dialog.enable_checkbox.setChecked(True)
    dialog = window.equalizer_dialog
    dialog.preset_combo.setCurrentIndex(dialog.preset_combo.findData(13))
    rock = window.player.get_equalizer_values()
    window.playlist_dock.setVisible(False)
    window.settings.last_open_dir = str(settings_module.settings_file().parent)
    window.close()

    saved = settings_module.load_settings()
    assert saved.volume == 35 and saved.muted is True and saved.rate == 1.5
    assert saved.repeat_mode == "all" and saved.shuffle is True and saved.visualizer is False
    assert saved.subtitle_scale == 150 and saved.video_scale == 2.0
    assert saved.equalizer.enabled and saved.equalizer.preset == 13
    assert saved.geometry and saved.window_state

    again = make_window()
    assert (again.width(), again.height()) == (700, 450)  # la pantalla offscreen mide 800x600
    assert again.volume_slider.value() == 35 and again.player._volume == 35
    assert again.player.is_muted() is True
    assert again.rate() == 1.5 and again.player._rate == 1.5 and again.speed_button.text() == "1,5×"
    assert again.repeat_mode == "all" and again.act_repeat_cycle.text() == "Repetir todo"
    assert next(a for a in again.repeat_group.actions() if a.isChecked()).data() == "all"
    assert again.act_shuffle.isChecked() and again.btn_shuffle.isChecked() and again.order.shuffle
    assert not again.act_visualizer.isChecked()
    assert again.player._subtitle_scale == 150
    assert again.player.get_video_scale() == 2.0
    # EQ aplicado al backend ANTES de abrir nada (lo recoge _create_instance).
    preamp, bands = again.player.get_equalizer_values()
    assert preamp == pytest.approx(rock[0]) and bands == pytest.approx(rock[1])
    again.open_equalizer()
    assert again.equalizer_dialog.enable_checkbox.isChecked()
    assert again.equalizer_dialog.preset_combo.currentData() == 13
    assert again.playlist_dock.isHidden()
    assert again._open_dir() == str(settings_module.settings_file().parent)


def test_power_action_is_not_restored(make_window):
    window = make_window()
    window.on_finish_action = "shutdown"
    window.close()
    assert make_window().on_finish_action == "none"


def test_closing_in_fullscreen_saves_the_normal_window(make_window):
    window = make_window()
    window.resize(640, 400)
    window.show()
    window.toggle_fullscreen()
    window.close()
    again = make_window()
    assert not again.isFullScreen()
    # (El ancho exacto tras showNormal() no es fiable en la plataforma offscreen.)
    assert again.height() == 400
    assert not again.playlist_dock.isHidden()


def test_playlist_and_current_item_are_restored_without_autoplay(make_window, monkeypatch):
    window = make_window()
    window.add_files_to_playlist(["C:/fake/a.mp3", "C:/fake/b.mkv", "https://example.com/radio"])
    assert window._session_save_timer.isActive()  # guardado con debounce
    window.current_index = 1  # "sonando" (sin decodificar nada de verdad)
    window.close()

    again = make_window()
    assert again.playlist_entries() == [os.path.normpath("C:/fake/a.mp3"), os.path.normpath("C:/fake/b.mkv"),
                                        "https://example.com/radio"]
    assert again.current_index == -1 and again.player.is_idle()  # no arranca solo
    assert again.playlist_view.current_source_row() == 1
    played = []
    monkeypatch.setattr(again, "play_index", lambda index, user=True: played.append(index))
    again.toggle_play_pause()
    assert played == [1]  # Reproducir retoma el elemento que sonaba


def test_restored_row_follows_removals(make_window):
    settings_module.save_session(settings_module.Session(entries=["a.mp3", "b.mp3", "c.mp3"], current_index=2))
    window = make_window()
    assert window._session_row == 2
    window.remove_rows([0])
    assert window._session_row == 1
    window.remove_rows([1])
    assert window._session_row == -1


def test_session_is_written_after_the_debounce(make_window):
    window = make_window()
    window.add_files_to_playlist(["C:/fake/x.mp3"])
    assert settings_module.load_session().entries == []
    window._session_save_timer.timeout.emit()  # lo que haria el timer tras 1 s
    assert settings_module.load_session().entries == [os.path.normpath("C:/fake/x.mp3")]


def test_turning_off_restore_session_clears_it(make_window):
    window = make_window()
    window.add_files_to_playlist(["C:/fake/x.mp3"])
    window.act_restore_session.setChecked(False)
    window.close()
    assert settings_module.load_session().entries == []
    again = make_window()
    assert again.playlist.count() == 0
    assert not again.act_restore_session.isChecked()


def test_open_log_folder_opens_the_log_directory(make_window, monkeypatch):
    opened = []
    monkeypatch.setattr(main_window_module.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    window = make_window()
    window.open_log_folder()
    assert len(opened) == 1
    local = opened[0].toLocalFile()
    assert os.path.normcase(os.path.normpath(local)) == os.path.normcase(str(main_window_module.current_log_dir()))
    assert os.path.isdir(local)


def test_command_line_files_are_appended_after_the_restored_session():
    import run

    assert run.split_args(["--debug", "a.mp3", "b.mkv"]) == (True, ["a.mp3", "b.mkv"])
    assert run.split_args(["a.mp3"]) == (False, ["a.mp3"])
