"""Pruebas de humo de la interfaz: construyen la ventana real (VLC + PySide6)
con la plataforma Qt "offscreen" para detectar errores de API/enum sin
necesitar una pantalla. Se omiten si no hay VLC (libvlc) instalado."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc  # noqa: F401
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten las pruebas de interfaz.", allow_module_level=True)

from PySide6.QtWidgets import QApplication

from player import main_window as main_window_module
from player.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_main_window_builds_without_error(qapp):
    window = MainWindow()
    try:
        assert window.windowTitle() == "Reproductor Multimedia Pro"
        assert window.playlist.count() == 0
    finally:
        window.close()


def test_playlist_and_ui_wiring_smoke(qapp):
    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/song.mp3", "https://example.com/stream.mp3"])
        assert window.playlist.count() == 2

        # Ejercitan los mismos caminos de codigo que fallaron antes por usar
        # una API de python-vlc/PySide6 equivocada (ver historial del proyecto).
        window._populate_audio_track_menu()
        window._populate_subtitle_track_menu()
        window._cycle_repeat_mode()
        window.update_ui()
    finally:
        window.close()


def test_equalizer_dialog_builds_without_error(qapp):
    window = MainWindow()
    try:
        window.open_equalizer()
        assert window.equalizer_dialog is not None
    finally:
        window.close()


def test_step_frame_shows_a_hint_when_nothing_is_playing(qapp):
    # Sin nada cargado (current_index == -1) no debe tocar libVLC ni fallar.
    window = MainWindow()
    try:
        window.step_frame()
    finally:
        window.close()


def test_step_frame_is_a_no_op_and_shows_a_hint_when_not_paused(qapp):
    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/song.mp3"])
        window.current_index = 0  # simula una pista "actual" sin reproducirla de verdad
        window.step_frame()
        assert "pausa" in window.statusBar().currentMessage().lower()
    finally:
        window.close()


def test_recent_files_menu_populates_and_offers_a_clear_action(qapp, monkeypatch, tmp_path):
    from player import recent_files as recent_files_module

    monkeypatch.setattr(recent_files_module.Path, "home", staticmethod(lambda: tmp_path))
    window = MainWindow()
    try:
        # Vacia: un solo item deshabilitado, ningun "Limpiar lista".
        window._populate_recent_files_menu()
        actions = window.menu_recent_files.actions()
        assert len(actions) == 1
        assert not actions[0].isEnabled()

        recent_files_module.add_recent_file("C:/fake/song.mp3")
        recent_files_module.add_recent_file("https://example.com/stream.mp3")
        window._populate_recent_files_menu()
        actions = window.menu_recent_files.actions()
        # 2 archivos + separador + "Limpiar lista"
        labels = [a.text() for a in actions if not a.isSeparator()]
        assert any("song.mp3" in label for label in labels)
        assert any("example.com" in label for label in labels)
        assert "Limpiar lista" in labels
    finally:
        window.close()


def test_open_recent_file_warns_about_a_missing_local_file(qapp, monkeypatch, tmp_path):
    from player import recent_files as recent_files_module

    monkeypatch.setattr(recent_files_module.Path, "home", staticmethod(lambda: tmp_path))
    window = MainWindow()
    try:
        monkeypatch.setattr(main_window_module.QMessageBox, "warning", lambda *a, **k: None)
        window.open_recent_file("C:/definitely/not/a/real/file.mp4")
        # No debe haberse agregado a la playlist ni intentado reproducir.
        assert window.playlist.count() == 0
        assert window.current_index == -1
    finally:
        window.close()


def test_hover_preview_wiring_does_not_crash_without_a_loaded_track(qapp):
    from PySide6.QtCore import QPoint

    window = MainWindow()
    try:
        # Sin pista actual, el hover debe ser un no-op silencioso.
        window.preview.on_hovered(0.5, QPoint(100, 100))
        assert not window.preview.hover_timer.isActive()
        window.preview.on_hover_ended()
    finally:
        window.close()


def test_hover_preview_debounce_timer_starts_once_a_track_is_current(qapp):
    from PySide6.QtCore import QPoint

    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/song.mp3"])
        window.current_index = 0
        # Simula que ya hay un largo conocido, como update_ui() lo haria.
        monkeypatch_length = window.player.get_length_ms
        window.player.get_length_ms = lambda: 60000
        try:
            window.preview.on_hovered(0.3, QPoint(50, 50))
            assert window.preview.hover_timer.isActive()
            assert window.preview.pending_fraction == 0.3
        finally:
            window.player.get_length_ms = monkeypatch_length
        window.preview.on_hover_ended()
        assert not window.preview.hover_timer.isActive()
    finally:
        window.close()


def test_hover_preview_popup_shows_a_formatted_timestamp(qapp):
    from PySide6.QtCore import QPoint

    from player.formats import format_time

    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/song.mp3"])
        window.current_index = 0
        window.player.get_length_ms = lambda: 60000
        window.preview.pending_fraction = 0.5
        window.preview.pending_pos = QPoint(100, 100)
        window.preview.show_preview()
        try:
            assert window.preview.popup is not None
            assert window.preview.popup.isVisible()
            assert window.preview.time_label.text() == format_time(30000)
        finally:
            window.preview.hide()
    finally:
        window.close()


# ------------------------------------------------------------------ OSD
def test_show_osd_displays_text_and_hides_after_the_timer_fires(qapp):
    # La ventana nunca se muestra en estas pruebas (plataforma "offscreen"),
    # asi que isVisible() del label dependeria de la visibilidad del propio
    # QMainWindow; isHidden() en cambio refleja el ultimo show()/hide()
    # explicito del widget, que es lo que _show_osd/el timer controlan.
    window = MainWindow()
    try:
        window._show_osd("+5s")
        assert not window._osd_label.isHidden()
        assert window._osd_label.text() == "+5s"
        assert window._osd_timer.isActive()

        # Simula el disparo del timer sin esperar 1.5s reales.
        window._osd_timer.timeout.emit()
        assert window._osd_label.isHidden()
    finally:
        window.close()


def test_seek_relative_shows_signed_seconds_on_the_osd(qapp):
    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/song.mp3"])
        window.current_index = 0
        window._seek_relative(5000)
        assert window._osd_label.text() == "+5s"
        window._seek_relative(-5000)
        assert window._osd_label.text() == "-5s"
    finally:
        window.close()


def test_seek_relative_without_a_current_track_does_not_touch_the_osd(qapp):
    window = MainWindow()
    try:
        window._osd_label.hide()
        window._seek_relative(5000)
        assert window._osd_label.isHidden()
    finally:
        window.close()


def test_nudge_volume_shows_the_resulting_percentage_on_the_osd(qapp):
    window = MainWindow()
    try:
        window.volume_slider.setValue(80)
        window._nudge_volume(5)
        assert window._osd_label.text() == "Volumen: 85%"
        assert window.volume_slider.value() == 85
    finally:
        window.close()


def test_step_frame_shows_osd_on_a_successful_frame_advance(qapp):
    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/song.mp3"])
        window.current_index = 0
        # No hay media real cargada; se simula el estado en pausa y un
        # avance exitoso para probar el cableado de step_frame -> OSD sin
        # depender de decodificar un archivo de verdad.
        window.player.is_paused = lambda: True
        window.player.next_frame = lambda: True
        window.step_frame()
        assert not window._osd_label.isHidden()
        assert window._osd_label.text() == "Fotograma siguiente"
    finally:
        window.close()


# ---------------------------------------------------- fullscreen controls
def test_fullscreen_uses_a_dedicated_controller_in_its_own_overlay_window(qapp):
    # Ni hijo de video_frame (quedaba debajo de la ventana de video de
    # libVLC) ni la barra normal reparentada: un controlador propio (titulo,
    # tiempos, barra grande, pocos botones) en una ventana superpuesta.
    window = MainWindow()
    try:
        controller = window.fullscreen_controller
        assert controller.parentWidget() is window.fullscreen.overlay
        window.toggle_fullscreen()
        try:
            assert window.fullscreen.overlay.isWindow()
            assert window.controls_bar.isHidden()
            assert controller.isVisibleTo(window.fullscreen.overlay)
            assert window.fullscreen.idle_timer.isActive()
            # Mismos QAction que los menus: sin estado duplicado.
            assert controller.buttons["play"].defaultAction() is window.act_play_pause
            assert controller.buttons["fullscreen"].defaultAction() is window.act_fullscreen
            assert set(controller.buttons) == {"previous", "play", "stop", "next", "mute", "fullscreen"}
        finally:
            window._exit_fullscreen()
        assert not window.controls_bar.isHidden()
        assert window.fullscreen.overlay.isHidden()
        assert not window.fullscreen.idle_timer.isActive()
    finally:
        window.close()


def test_fullscreen_controller_shows_title_times_and_position(qapp):
    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/pelicula.mkv"])
        window.current_index = 0
        window.player.get_length_ms = lambda: 120_000
        window.player.get_time_ms = lambda: 30_000
        window.player.get_position = lambda: 0.25
        window.toggle_fullscreen()
        try:
            window.update_ui()
            c = window.fullscreen_controller
            assert c.title_label.text().endswith("pelicula.mkv")
            assert (c.time_label.text(), c.total_label.text()) == ("00:30", "02:00")
            assert c.slider.value() == 250
        finally:
            window._exit_fullscreen()
    finally:
        window.close()


def test_fullscreen_idle_timeout_hides_the_floating_controller(qapp):
    window = MainWindow()
    try:
        window.show()
        window.toggle_fullscreen()
        try:
            assert window.fullscreen.overlay.isVisible()
            window.fullscreen.idle_timer.timeout.emit()
            assert not window.fullscreen.overlay.isVisible()
            # Nueva actividad de mouse vuelve a mostrarlo.
            window.fullscreen.on_mouse_activity()
            assert window.fullscreen.overlay.isVisible()
        finally:
            window._exit_fullscreen()
    finally:
        window.close()


def test_fullscreen_mouse_activity_is_a_no_op_outside_fullscreen(qapp):
    window = MainWindow()
    try:
        window.fullscreen.on_mouse_activity()
        assert not window.fullscreen.idle_timer.isActive()
    finally:
        window.close()


def test_event_filter_only_reacts_to_mouse_move_while_fullscreen(qapp):
    from PySide6.QtCore import QEvent

    window = MainWindow()
    try:
        move_event = QEvent(QEvent.Type.MouseMove)
        window.eventFilter(window.video_frame, move_event)
        assert not window.fullscreen.idle_timer.isActive()

        window.show()
        window.toggle_fullscreen()
        try:
            window.fullscreen.hide_controls()
            assert not window.fullscreen.overlay.isVisible()
            move_event2 = QEvent(QEvent.Type.MouseMove)
            window.eventFilter(window.video_frame, move_event2)
            assert window.fullscreen.overlay.isVisible()
        finally:
            window._exit_fullscreen()
    finally:
        window.close()
