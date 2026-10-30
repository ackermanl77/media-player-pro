"""Pasada de interfaz (2026-10-29): teclas de VLC para pistas, zoom y desentrelazado (UI4, UI7) y el
aviso de la lista vacia (UI5)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from player.video_options import ZOOM_LEVELS, next_choice, next_track


def test_next_track_cycles_and_wraps():
    tracks = [(-1, b"Desactivar"), (2, b"Pista 1 - [es]"), (3, b"Pista 2 - [en]")]
    assert next_track(tracks, -1) == (2, b"Pista 1 - [es]")
    assert next_track(tracks, 3) == (-1, b"Desactivar")
    assert next_track(tracks, 99) == (-1, b"Desactivar")  # desconocida: empieza por la primera
    assert next_track([(-1, b"Desactivar")], -1) is None
    assert next_track([], -1) is None


def test_zoom_levels_cycle_from_fit_to_200_and_back():
    assert next_choice(ZOOM_LEVELS, 0.0) == 0.5
    assert next_choice(ZOOM_LEVELS, 2.0) == 0.0


try:
    import vlc  # noqa: F401
    _VLC = True
except OSError:
    _VLC = False


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


@pytest.mark.skipif(not _VLC, reason="VLC (libvlc) no esta instalado")
def test_vlc_keys_are_registered_and_listed(qapp):
    from player.main_window import MainWindow

    window = MainWindow()
    try:
        from PySide6.QtGui import QKeySequence

        rows = dict(window.shortcut_rows())
        # Shown in the UI's language once the Spanish Qt translation is installed ("Mayúsculas+B").
        native = {keys: QKeySequence(keys).toString(QKeySequence.SequenceFormat.NativeText) for keys in ("V", "Shift+B", "Z", "D")}
        assert rows["Siguiente pista de subtítulos"] == native["V"]
        assert rows["Siguiente pista de audio"] == native["Shift+B"]
        assert rows["Siguiente zoom"] == native["Z"]
        assert rows["Desentrelazado sí / no"] == native["D"]
        window._set_zoom(1.5)
        assert window.player.get_video_scale() == 1.5
        assert [a.isChecked() for a in window.menu_zoom.actions()] == [f == 1.5 for _label, f in ZOOM_LEVELS]
    finally:
        window.close()


@pytest.mark.skipif(not _VLC, reason="VLC (libvlc) no esta instalado")
def test_playlist_says_when_it_is_empty_or_nothing_matches(qapp):
    from player.main_window import MainWindow
    from player.playlist_model import PlaylistView

    window = MainWindow()
    try:
        view = window.playlist_view
        assert view.empty_text() == PlaylistView.EMPTY_TEXT
        window.add_files_to_playlist(["C:/fake/song.mp3"])
        assert view.empty_text() == ""
        window.playlist.proxy.set_needle("no existe")
        assert view.empty_text() == PlaylistView.NO_MATCH_TEXT
    finally:
        window.close()
