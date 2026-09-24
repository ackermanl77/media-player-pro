"""Regresiones de transporte/playlist contra libVLC real y Qt "offscreen"
(sin simular teclas ni mouse: se llama a los mismos metodos/slots que
dispararia la UI). Se omite si no hay VLC instalado."""
import os
import sys
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten estas pruebas.", allow_module_level=True)

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from player import backend as backend_module
from player import bookmarks, main_window as main_window_module, recent_files, resume
from player.backend import VLCPlayer
from player.main_window import MainWindow, playlist_owns_key


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def headless(monkeypatch, tmp_path):
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )
    for module in (resume, bookmarks, recent_files):
        monkeypatch.setattr(module.Path, "home", staticmethod(lambda: tmp_path / "home"))
    return tmp_path


@pytest.fixture
def window(qapp, headless):
    w = MainWindow()
    w.act_visualizer.setChecked(False)
    yield w
    w.close()


def _wav(path, seconds):
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\x00\x00" * int(8000 * seconds))
    return str(path)


def _pump_until(window, predicate, timeout_s=8.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        window.update_ui()
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _state(window):
    return window.player.get_state()


# ------------------------------------------------ 1. Play tras Detener/fin
def test_play_after_stop_restarts_playback(window, headless):
    window.add_files_to_playlist([_wav(headless / "a.wav", 4)])
    window.play_index(0)
    assert _pump_until(window, lambda: _state(window) == vlc.State.Playing)
    window.stop()
    assert _pump_until(window, lambda: _state(window) == vlc.State.Stopped)
    window.toggle_play_pause()
    assert _pump_until(window, lambda: _state(window) == vlc.State.Playing)


def test_play_after_the_playlist_ended_restarts_the_current_track(window, headless):
    window.add_files_to_playlist([_wav(headless / "short.wav", 0.6)])
    window.play_index(0)
    assert _pump_until(window, lambda: window.player.is_idle() and _state(window) != vlc.State.NothingSpecial)
    window.toggle_play_pause()
    assert _pump_until(window, lambda: _state(window) in (vlc.State.Playing, vlc.State.Ended)
                       and window.player.get_length_ms() > 0)


# ------------------------------------------- 2. archivo roto no hace bucle
@pytest.mark.parametrize("repeat_mode", ["one", "all"])
def test_broken_files_stop_after_one_full_pass(window, headless, repeat_mode):
    window.add_files_to_playlist([str(headless / "missing1.mp3"), str(headless / "missing2.mp3")])
    window.repeat_mode = repeat_mode
    calls = []
    original = window.play_index
    window.play_index = lambda index, user=True: (calls.append(index), original(index, user))
    window.play_index(0)
    time.sleep(4.0)  # tiempo de sobra para decenas de reintentos con el bug viejo
    for _ in range(40):
        window.update_ui()
        time.sleep(0.1)
    assert calls == [0, 1]
    assert window.player.is_idle()
    assert "Ningún elemento" in window.statusBar().currentMessage()


def test_a_broken_track_is_skipped_even_with_repeat_one(window, headless):
    good = _wav(headless / "good.wav", 4)
    window.add_files_to_playlist([str(headless / "missing.mp3"), good])
    window.repeat_mode = "one"
    window.play_index(0)
    assert _pump_until(window, lambda: window.current_index == 1 and _state(window) == vlc.State.Playing)


# ------------------------------------------------- 3. aleatorio termina
def test_shuffle_with_repeat_none_ends_the_playlist(window):
    window.add_files_to_playlist([f"C:/fake/{i}.mp3" for i in range(4)])
    window.btn_shuffle.setChecked(True)
    played = []
    window.play_index = lambda index, user=True: (played.append(index), setattr(window, "current_index", index),
                                                  window.order.jump_to(index))
    for _ in range(10):
        window.play_next(auto=True)
    assert sorted(played) == [0, 1, 2, 3]


# --------------------------------------------- 5. Detener guarda posicion
def test_stop_saves_the_resume_position(window, headless):
    path = _wav(headless / "long.wav", 20)
    window.add_files_to_playlist([path])
    window.play_index(0)
    assert _pump_until(window, lambda: _state(window) == vlc.State.Playing)
    window.player.set_time_ms(8000)
    assert _pump_until(window, lambda: window.player.get_time_ms() >= 7000)
    window.stop()
    assert (resume.get_saved_position_ms(path) or 0) >= 7000


def test_removing_the_current_track_saves_its_position(window, headless):
    path = _wav(headless / "long2.wav", 20)
    window.add_files_to_playlist([path])
    window.play_index(0)
    assert _pump_until(window, lambda: _state(window) == vlc.State.Playing)
    window.player.set_time_ms(8000)
    assert _pump_until(window, lambda: window.player.get_time_ms() >= 7000)
    window.remove_rows([0])
    assert window.current_index == -1
    assert (resume.get_saved_position_ms(path) or 0) >= 7000


# ------------------------------------------ 6. marcadores cacheados
def test_bookmarks_are_read_once_per_track_not_every_tick(window, monkeypatch):
    reads = []
    monkeypatch.setattr(main_window_module, "get_bookmarks", lambda p: reads.append(p) or [])
    window.add_files_to_playlist(["C:/fake/video.mkv"])
    window.current_index = 0
    window.player.get_length_ms = lambda: 60_000
    for _ in range(10):
        window.update_ui()
    assert len(reads) == 1
    window._invalidate_bookmarks_cache()  # lo que hacen agregar/quitar/renombrar
    window.update_ui()
    assert len(reads) == 2


# -------------------------------------- 7. teclado y quitar varios
def test_arrow_keys_go_to_a_focused_playlist_not_to_the_volume_shortcut(window):
    up = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    assert window.eventFilter(window.playlist_widget, up) is True
    assert up.isAccepted()
    # Fuera de la playlist, el atajo de volumen sigue funcionando.
    up2 = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    assert window.eventFilter(window.video_frame, up2) is False
    # Ctrl+Flecha y Espacio siguen siendo atajos globales.
    ctrl = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert not playlist_owns_key(ctrl)
    space = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    assert not playlist_owns_key(space)


def test_enter_on_the_playlist_plays_the_item(window):
    played = []
    window.play_index = lambda index, user=True: played.append(index)
    window.add_files_to_playlist(["C:/fake/a.mp3", "C:/fake/b.mp3"])
    window.playlist_widget.itemActivated.emit(window.playlist_widget.item(1))
    assert played == [1]


def test_delete_removes_every_selected_row_and_keeps_current_in_sync(window):
    window.add_files_to_playlist([f"C:/fake/{n}.mp3" for n in "abcde"])
    window.current_index = 3
    window.order.jump_to(3)
    window.playlist_widget.item(0).setSelected(True)
    window.playlist_widget.item(2).setSelected(True)
    window.remove_selected_from_playlist()
    names = [window.playlist_widget.item(i).text() for i in range(window.playlist_widget.count())]
    assert [n.split()[-1] for n in names] == ["b.mp3", "d.mp3", "e.mp3"]
    assert window.current_index == 1
    assert window.order.current == 1 and window.order.count == 3


# --------------------------------------------- 4. rutas normalizadas
def test_playlist_entries_are_normalized_on_entry(window, headless):
    raw = str(headless).replace("\\", "/") + "/dir/f.mkv"
    window.add_files_to_playlist([raw, "http://example.com/s"])
    assert window.playlist_widget.item(0).data(Qt.ItemDataRole.UserRole) == os.path.join(str(headless), "dir", "f.mkv")
    assert window.playlist_widget.item(1).data(Qt.ItemDataRole.UserRole) == "http://example.com/s"


# ------------------------------------------ 10. recrear el Instance
def test_changing_subtitle_size_does_not_go_through_play_index(window):
    window.add_files_to_playlist(["C:/fake/video.mkv"])
    window.current_index = 0
    window.loop_point_a, window.loop_point_b = 1000, 5000
    reloads = []
    window.play_index = lambda *a, **k: pytest.fail("no debe reabrir la pista")
    window.player.reload_preserving_state = lambda: reloads.append(True) or True
    window._on_subtitle_scale_changed(150)
    assert reloads == [True]
    assert (window.loop_point_a, window.loop_point_b) == (1000, 5000)


def _headless_player(monkeypatch):
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )
    return VLCPlayer()


def test_recreating_the_instance_releases_old_objects_and_keeps_zoom(monkeypatch):
    player = _headless_player(monkeypatch)
    player.set_video_scale(2.0)
    player._ensure_preview_player()
    released = []
    for name, obj in (("mp", player.media_player), ("preview", player._preview_player), ("instance", player.instance)):
        original = obj.release
        monkeypatch.setattr(obj, "release", lambda n=name, o=original: (released.append(n), o()))
    player._create_instance(visualizer=False)
    assert sorted(released) == ["instance", "mp", "preview"]
    assert player.media_player.video_get_scale() == pytest.approx(2.0)


def test_reload_preserving_state_keeps_position_pause_delay_and_external_subs(monkeypatch, tmp_path):
    player = _headless_player(monkeypatch)
    wav = _wav(tmp_path / "long.wav", 20)
    srt = tmp_path / "ext.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:20,000\nhola\n", encoding="utf-8")
    player.load(wav)
    player.play()
    try:
        deadline = time.time() + 8
        while player.get_state() != vlc.State.Playing and time.time() < deadline:
            time.sleep(0.05)
        player.load_subtitle_file(str(srt))
        player.set_time_ms(9000)
        time.sleep(0.5)
        player.set_subtitle_delay_ms(300)
        delay_before = player.get_subtitle_delay_ms()
        player.set_paused(True)
        time.sleep(0.3)

        player.set_subtitle_scale(150)
        assert player.reload_preserving_state() is True
        assert player._instance_subtitle_scale == 150
        deadline = time.time() + 8
        while not player.apply_pending_restore() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.4)
        assert player.get_time_ms() >= 8500
        assert player.get_subtitle_delay_ms() == delay_before
        assert player.get_state() == vlc.State.Paused
        assert player._external_subtitles == [str(srt)]
    finally:
        player.stop()


def test_reload_preserving_state_is_a_no_op_when_stopped(monkeypatch):
    player = _headless_player(monkeypatch)
    assert player.reload_preserving_state() is False
