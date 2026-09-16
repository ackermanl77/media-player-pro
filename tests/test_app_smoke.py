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

from player.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_main_window_builds_without_error(qapp):
    window = MainWindow()
    try:
        assert window.windowTitle() == "Reproductor Multimedia Pro"
        assert window.playlist_widget.count() == 0
    finally:
        window.close()


def test_playlist_and_ui_wiring_smoke(qapp):
    window = MainWindow()
    try:
        window.add_files_to_playlist(["C:/fake/song.mp3", "https://example.com/stream.mp3"])
        assert window.playlist_widget.count() == 2

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
