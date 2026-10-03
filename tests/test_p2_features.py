"""Regresiones de los puntos P2 del informe de mejoras contra libVLC real y
Qt "offscreen" (sin simular teclado ni mouse del sistema: se llaman los
mismos metodos/slots que dispararia la UI). Se omite si no hay VLC."""
import functools
import http.server
import os
import sys
import threading
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten estas pruebas.", allow_module_level=True)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from player import backend as backend_module
from player import main_window as main_window_module
from player.backend import (
    PlaybackState,
    VLCInitError,
    VLCPlayer,
    create_instance_with_fallback,
    gpu_instance_args,
)

VIDEO = str(Path(__file__).parent / "assets" / "chapters.mkv")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def headless(monkeypatch):
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )


@pytest.fixture
def window(qapp, headless):
    w = main_window_module.MainWindow()
    w.act_visualizer.setChecked(False)
    yield w
    w.close()


def _wav(path, seconds, rate=8000):
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x00\x00" * int(rate * seconds))
    return str(path)


def _pump(predicate, timeout_s=8.0):
    """Solo el bucle de eventos (sin update_ui): lo que avance tiene que
    llegar por eventos de libVLC."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


# ------------------------------------------------- 3.4 eventos de libVLC
def test_the_ui_no_longer_imports_vlc():
    assert not hasattr(main_window_module, "vlc")


def test_end_of_track_advances_through_libvlc_events_without_polling(window, tmp_path):
    window.timer.stop()  # nada de sondeo: solo eventos
    window.add_files_to_playlist([_wav(tmp_path / "a.wav", 0.5), _wav(tmp_path / "b.wav", 3)])
    window.play_index(0)
    assert _pump(lambda: window.current_index == 1 and window.player.playback_state() == PlaybackState.PLAYING)


def test_a_stale_end_event_from_the_previous_file_is_ignored(window):
    window.add_files_to_playlist(["C:/fake/a.mp3", "C:/fake/b.mp3"])
    window.current_index = 0
    window.player.playback_state = lambda: PlaybackState.ENDED
    advanced = []
    window.play_next = lambda **k: advanced.append(k)
    window._on_track_finished_event(window.player.generation - 1)
    assert advanced == []
    window._on_track_finished_event(window.player.generation)
    window._on_track_finished_event(window.player.generation)  # EndReached + Error del mismo archivo
    assert len(advanced) == 1


# -------------------------------------------- 6.2 / 5.1 opciones de instancia
def test_instance_fallback_drops_optional_groups_in_order():
    calls = []

    def factory(args):
        calls.append(list(args))
        return None if any(a.startswith("--d3d11") or a == "--bad" for a in args) else "inst"

    inst, dropped = create_instance_with_fallback(["--quiet"], [("gpu", ["--d3d11-upscale-mode=super"]),
                                                                ("visualizer", ["--audio-visual=visual"])], factory)
    assert (inst, dropped) == ("inst", ["gpu"])
    assert calls[-1] == ["--quiet", "--audio-visual=visual"]
    with pytest.raises(VLCInitError):
        create_instance_with_fallback(["--bad"], [], factory)


@pytest.mark.skipif(sys.platform != "win32", reason="GPU video options (d3d11va, RTX VSR/HDR) are Windows-only libVLC features")
def test_unknown_gpu_option_degrades_instead_of_breaking_playback(window, monkeypatch, tmp_path):
    monkeypatch.setattr(backend_module, "gpu_instance_args", lambda *a: ["--opcion-que-no-existe"])
    window.act_gpu_upscale.setChecked(True) if window.menu_gpu is not None else window.player.set_gpu_options(
        True, False)
    window.add_files_to_playlist([_wav(tmp_path / "a.wav", 3)])
    window.play_index(0)
    assert window.player.instance is not None
    assert window.player.gpu_options() == (False, False, "any")
    if window.menu_gpu is not None:
        assert not window.act_gpu_upscale.isChecked()
    assert "no admite la mejora por GPU" in window.statusBar().currentMessage()
    assert _pump(lambda: window.player.playback_state() == PlaybackState.PLAYING)


@pytest.mark.skipif(sys.platform != "win32", reason="GPU video options (d3d11va, RTX VSR/HDR) are Windows-only libVLC features")
def test_gpu_flags_are_accepted_by_the_installed_libvlc_and_trigger_recreation(headless):
    assert gpu_instance_args(True, True, "d3d11va") == [
        "--avcodec-hw=d3d11va", "--d3d11-upscale-mode=super", "--d3d11-hdr-mode=generate"]
    assert gpu_instance_args(False, False, "any") == []
    player = VLCPlayer()
    try:
        old = player.instance
        player.set_gpu_options(True, True)
        assert player._needs_new_instance(False)
        player.load(VIDEO)
        assert player.instance is not old and player.take_dropped_options() == []
        assert player._instance_gpu_args == gpu_instance_args(True, True, "any")
    finally:
        player.close()


# ------------------------------------------------------- 3.8 desfase de audio
def test_audio_delay_shortcuts_and_reload_keep_it(window, tmp_path):
    window.add_files_to_playlist([_wav(tmp_path / "long.wav", 20)])
    window.play_index(0)
    assert _pump(lambda: window.player.playback_state() == PlaybackState.PLAYING)
    keys = {a.shortcut().toString(): a for a in window.actions()}
    keys["K"].trigger()
    keys["K"].trigger()
    keys["J"].trigger()
    assert window.player.get_audio_delay_ms() == 50
    assert window._osd_label.text() == "Audio: +50 ms"
    assert window.player.reload_preserving_state() is True
    assert _pump(lambda: window.player.apply_pending_restore() or window.player._pending_restore is None)
    assert window.player.get_audio_delay_ms() == 50


# -------------------------------------------------------------- 3.7 capitulos
def test_chapters_menu_markers_and_navigation(window):
    window.add_files_to_playlist([VIDEO])
    window.play_index(0)
    assert _pump(lambda: window.player.get_length_ms() > 0 and len(window._current_chapters()) == 3)
    assert [c[2] for c in window._current_chapters()] == ["Intro", "Medio", "Final"]
    window._populate_chapters_menu()
    assert [a.text().split(" (")[0] for a in window.menu_chapters.actions()] == ["1. Intro", "2. Medio", "3. Final"]
    window.update_ui()
    kinds = [k for _f, k in window.position_slider.markers()]
    assert kinds.count("chapter") == 2  # el primero empieza en 0
    assert window.chapter_name_at(2500) == "Medio"
    keys = {a.shortcut().toString(): a for a in window.actions()}
    assert "PgDown" in keys and "PgUp" in keys
    keys["PgDown"].trigger()
    assert _pump(lambda: window.player.get_chapter() == 1)


# ------------------------------------------------- 3.2 / 3.5 streams de red
class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def test_audio_only_http_stream_enables_the_visualizer(window, tmp_path):
    _wav(tmp_path / "radio.wav", 20, rate=22050)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                             functools.partial(_QuietHandler, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/radio.wav"
        window.act_visualizer.setChecked(True)
        window.add_files_to_playlist([url])
        window.play_index(0)
        assert not window.player.visualizer_active()  # una URL no se sabe por la extension
        assert _pump(lambda: window.player.visualizer_active(), timeout_s=12)
        assert _pump(lambda: window.player.playback_state() == PlaybackState.PLAYING)
    finally:
        window.player.stop()
        server.shutdown()


def test_urls_get_network_options_and_are_never_mangled(headless, monkeypatch):
    added = []
    monkeypatch.setattr(vlc.Media, "add_option", lambda self, opt: added.append(opt))
    player = VLCPlayer()
    try:
        opened = []
        original = player.instance.media_new
        player.instance.media_new = lambda url: (opened.append(url), original(url))[1]
        player.network_caching_ms = 2500
        player.rtsp_tcp = True
        for url in ("srt://host:9000", "rtsps://cam/x", "smb://nas/v.mkv"):
            player._new_media(url)
        assert opened == ["srt://host:9000", "rtsps://cam/x", "smb://nas/v.mkv"]
        assert added.count(":network-caching=2500") == 3 and added.count(":rtsp-tcp") == 1
        assert "--http-reconnect" in backend_module.BASE_VLC_ARGS
    finally:
        player.close()


def test_buffering_live_label_and_stall_prompt(window, monkeypatch):
    window.add_files_to_playlist(["http://radio.example/stream"])
    window.current_index = 0
    gen = window.player.generation
    window._on_buffering(gen, 45.0)
    assert window.statusBar().currentMessage() == "Almacenando en búfer… 45 %"
    assert window._stall_timer.isActive()
    window._on_buffering(gen, 100.0)
    assert not window._stall_timer.isActive()
    # En vivo: sin largo pero reproduciendose.
    window.player.is_live_stream = lambda: True
    window.update_ui()
    assert window.label_time_total.text() == "EN VIVO" and not window.position_slider.isEnabled()
    # Watchdog: sigue abriendo tras 15 s -> Reintentar / Saltar.
    window.player.playback_state = lambda: PlaybackState.OPENING
    window._on_stream_stalled()
    assert window._stall_box is not None
    assert {b.text() for b in window._stall_box.buttons()} >= {"Reintentar", "Saltar"}
    window._stall_box.close()


def test_open_url_dialog_prefills_from_the_clipboard_and_validates(qapp):
    from player.url_dialog import OpenUrlDialog

    dialog = OpenUrlDialog(1500, True, clipboard_text=" rtsp://cam/live ")
    assert dialog.url() == "rtsp://cam/live" and dialog.network_caching_ms() == 1500 and dialog.rtsp_tcp()
    dialog.url_edit.setText("hola")
    dialog._on_accept()
    assert dialog.result() != dialog.DialogCode.Accepted and dialog.error_label.text()
    assert OpenUrlDialog(1000, False, clipboard_text="no es url").url() == ""


# --------------------------------------------- 4.4 / 4.6 atajos, menus, mouse
def test_new_shortcuts_and_menus_exist(window):
    keys = {a.shortcut().toString() for a in window.actions()}
    assert {"S", "J", "K", "[", "]", "=", "Ctrl+G", "Ctrl+Shift+S", "PgUp", "PgDown", "Home", "F1"} <= keys
    extra = {seq.toString() for _d, seq in window.action_registry.extra_shortcuts}
    assert {"Shift+Right", "Alt+Left", "Ctrl+Alt+Right"} <= extra
    assert len(window.action_registry.extra_shortcuts) >= 17  # incluye las 6 teclas multimedia
    menus = [a.text() for a in window.menuBar().actions()]
    assert "A&udio" in menus and "&Archivo" in menus  # Alt+A ya no es ambiguo
    rows = window.shortcut_rows()
    assert ("Detener", "S") in rows and any(r[0] == "Adelantar 30 s" for r in rows)
    context = [a.text() for a in window.video_context_menu.actions()]
    assert "Reproducir/Pausar" in context and "Velocidad" in context and "Capítulos" in context


def test_speed_keys_clamp_and_show_the_rate(window):
    for _ in range(3):
        window._nudge_rate(0.1)
    assert window.rate() == 1.3 and window.speed_button.text() == "1,3×"
    assert window._osd_label.text() == "Velocidad: 1,3×"
    for _ in range(50):
        window._nudge_rate(-0.1)
    assert window.rate() == 0.25
    window._set_rate(1.0)
    assert next(a for a in window.speed_group.actions() if a.isChecked()).data() == 1.0


def test_jump_to_time_wheel_and_remaining_time(window, monkeypatch):
    window.add_files_to_playlist(["C:/fake/v.mkv"])
    window.current_index = 0
    seeks = []
    window.player.set_time_ms = seeks.append
    window.player.get_length_ms = lambda: 100_000
    window.player.get_time_ms = lambda: 10_000
    monkeypatch.setattr(main_window_module.QInputDialog, "getText", lambda *a, **k: ("25%", True))
    window.jump_to_time()
    assert seeks == [25_000]
    window._on_video_wheel(2, Qt.KeyboardModifier.ControlModifier)
    assert seeks[-1] == 20_000
    volume = window.volume_slider.value()
    window._on_video_wheel(-1, Qt.KeyboardModifier.NoModifier)
    assert window.volume_slider.value() == volume - 5
    window.player.get_position = lambda: 0.1
    window._toggle_remaining_time()
    window.update_ui()
    assert window.label_time_total.text() == "-01:30"


def test_quick_snapshot_writes_to_pictures_or_reports_no_video(window, monkeypatch, tmp_path):
    monkeypatch.setattr(window, "snapshot_dir", lambda: str(tmp_path / "capturas"))
    window.add_files_to_playlist(["C:/fake/v.mkv"])
    window.current_index = 0
    window.player.get_time_ms = lambda: 61_500
    assert window.quick_snapshot() is None  # sin video: libVLC devuelve -1
    assert window._osd_label.text() == "No hay video para capturar"
    taken = []
    window.player.take_snapshot = lambda path, *a: taken.append(path) or True
    target = window.quick_snapshot()
    assert target == str(tmp_path / "capturas" / "v_00-01-01.500.png") and taken == [target]
    window._on_snapshot_taken(target)
    assert window._osd_label.text() == "Captura guardada"


def test_left_click_on_the_seek_bar_jumps_there_with_any_style(window):
    slider = window.position_slider
    slider.setStyle(QStyleFactory.create("Fusion"))
    slider.resize(400, 24)
    slider.setValue(0)
    pos = QPointF(300, 12)
    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, slider.mapToGlobal(pos.toPoint()).toPointF(),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    slider.mousePressEvent(press)
    assert abs(slider.value() - round(slider._fraction_at(300) * 1000)) <= 1
    assert slider.isSliderDown()  # sigue como arrastre: al soltar, MainWindow busca


# ------------------------------------------------------------ 4.5 lista
def test_drag_reorder_keeps_the_playing_row_and_shuffle_in_sync(window):
    window.add_files_to_playlist([f"C:/fake/{n}.mp3" for n in "abcd"])
    window._set_current_index(1)
    window.order.jump_to(1)
    window.playlist_view.rowsDropped.emit([1], 4)  # lo que emite soltar "b" al final
    assert window.current_index == 3 and window.order.current == 3
    model = window.playlist.model
    assert [os.path.basename(p) for p in window.playlist_entries()] == ["a.mp3", "c.mp3", "d.mp3", "b.mp3"]
    assert model.index(3).data().startswith("▶") and model.index(3).data(Qt.ItemDataRole.FontRole).bold()
    assert not model.index(1).data().startswith("▶") and model.index(1).data(Qt.ItemDataRole.FontRole) is None


def test_removing_the_playing_row_then_next_plays_the_row_that_took_its_place(window):
    window.add_files_to_playlist([f"C:/fake/{n}.mp3" for n in "abcd"])
    window.current_index = 1
    window.order.jump_to(1)
    played = []
    window.play_index = lambda index, user=True: played.append(index)
    window.remove_rows([1])
    window.play_next(auto=False)
    assert played == [1]  # "c.mp3", no la primera de la lista


def test_filter_sort_and_remove_unavailable(window, tmp_path):
    real = _wav(tmp_path / "Pista 10.wav", 1)
    window.add_files_to_playlist(["C:/fake/Pista 2.mp3", real, "C:/fake/otra.mp3"])
    window.playlist_filter.setText("pista")
    assert window.playlist.visible_rows() == [0, 1]
    played = []
    window.play_index = lambda index, user=True: played.append(index)
    window._play_first_filtered()
    assert played == [0]
    window.playlist_filter.clear()
    window.sort_playlist("name")
    names = [os.path.basename(p) for p in window.playlist_entries()]
    assert names == ["otra.mp3", "Pista 2.mp3", "Pista 10.wav"]
    assert window.remove_unavailable() == 2
    assert window.playlist_entries() == [real]


def test_durations_are_read_in_the_background_and_totalled(window, tmp_path):
    a, b = _wav(tmp_path / "a.wav", 2), _wav(tmp_path / "b.wav", 3)
    window.add_files_to_playlist([a, b])
    model = window.playlist.model
    assert _pump(lambda: model.index(1).data().endswith("00:03"), timeout_s=10)
    assert model.index(0).data().endswith("00:02")
    assert window.playlist_dock.windowTitle() == "Lista de reproducción (2 elementos) — 00:05"


def test_open_paths_and_instance_messages_expand_folders(window, tmp_path):
    (tmp_path / "d").mkdir()
    _wav(tmp_path / "d" / "x.wav", 1)
    played = []
    window.play_index = lambda index, user=True: played.append(index)
    window.handle_instance_message("enqueue", [str(tmp_path / "d")])
    assert window.playlist_entries() == [str(tmp_path / "d" / "x.wav")]
    assert played == [0]  # no sonaba nada: arranca igual
    window.current_index = 0
    window.handle_instance_message("enqueue", ["https://x/radio"])
    assert played == [0] and window.playlist.count() == 2
    window.handle_instance_message("open", ["https://x/otra"])
    assert played == [0, 2]


# ------------------------------------------------- 3.11 subtitulos del video correcto
def test_a_subtitle_for_another_video_waits_for_that_video(window, tmp_path):
    video = _wav(tmp_path / "v.wav", 2)
    sub = tmp_path / "v.es.srt"
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nhola\n", encoding="utf-8")
    window.add_files_to_playlist(["C:/fake/actual.mkv", video])
    window.current_index = 0
    loaded = []
    window.player.load_subtitle_file = loaded.append
    window._on_online_subtitle_ready(video, str(sub))
    assert loaded == []  # no se carga en el video que suena ahora
    attached = []
    window.player.add_subtitle_before_play = attached.append
    window.play_index(1)
    assert attached == [str(sub)]


# ------------------------------------------------------------ 4.7 tema
def test_dark_theme_palette_icons_and_persistence(window, qapp):
    try:
        window._apply_theme("dark")
        assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#1e1e1e"
        assert qapp.style().name().lower() == "fusion"
        assert not window.act_play_pause.icon().isNull() and not window.act_shuffle.icon().isNull()
        next(a for a in window.theme_group.actions() if a.data() == "dark").setChecked(True)
        assert window.current_settings().theme == "dark"
    finally:
        window._apply_theme("system")


def test_spanish_qt_translator_is_installed(qapp):
    import run

    assert run.install_spanish_translator(qapp) is True
    assert run.parse_args(["--new-window", "--enqueue", "a.mp3"]) == {
        "debug": False, "new_window": True, "enqueue": True, "files": ["a.mp3"]}


def test_about_reports_the_real_libvlc_version():
    assert backend_module.libvlc_version()[0].isdigit()


def test_play_index_resumes_via_start_time(window, tmp_path):
    from player import resume

    path = _wav(tmp_path / "largo.wav", 30)
    resume.save_position(path, 12_000, 30_000)
    starts = []
    original = window.player.load
    window.player.load = lambda p, enable_visualizer=False, start_ms=0: (starts.append(start_ms),
                                                                          original(p, enable_visualizer, start_ms))[1]
    window.add_files_to_playlist([path])
    window.play_index(0)
    assert starts == [12_000]
    assert window._osd_label.text().startswith("Reanudado en 00:12")
    assert _pump(lambda: window.player.get_time_ms() >= 11_000)


def test_closing_twice_and_late_events_are_harmless(qapp, headless):
    w = main_window_module.MainWindow()
    gen = w.player.generation
    w.close()
    w.player.events.endReached.emit(gen)  # bloqueado tras cerrar
    w.close()
    assert w.player.media_player is None


def test_position_markers_only_repaint_on_change(window):
    updates = []
    window.position_slider.update = lambda *a: updates.append(1)
    window.position_slider.set_markers([(0.5, "bookmark")])
    window.position_slider.set_markers([(0.5, "bookmark")])
    assert len(updates) == 1


def test_mute_from_stopped_state_toggles_and_shows_osd(window):
    window.toggle_mute()
    assert window.player.is_muted() and window.act_mute.isChecked()
    assert window._osd_label.text() == "Silencio: sí"
    window.toggle_mute()
    assert not window.player.is_muted()


# ------------------------------------------- 4.7 tramo almacenado de streams
def test_buffered_range_is_clamped_and_painted_under_the_handle(window):
    slider = window.position_slider
    slider.resize(400, 24)
    slider.set_buffered_range(-0.5, 0.25)
    assert slider.buffered_range() == (0.0, 0.25)
    rect = slider.buffered_rect()
    assert not rect.isEmpty() and rect.left() >= 0 and rect.right() < slider.width()
    assert not slider.grab().isNull()  # pinta ranura + franja + tirador sin fallar
    slider.set_buffered_range(0.6, 0.4)  # vacio: se oculta
    assert slider.buffered_range() is None and slider.buffered_rect().isEmpty()
    slider.set_buffered_range(0.1, 0.2)
    slider.set_buffered_range(None, None)
    assert slider.buffered_range() is None


def test_buffered_range_follows_the_network_cache_of_a_seekable_stream(window):
    window.add_files_to_playlist(["https://example.com/video.mp4", "C:/fake/local.mkv"])
    window.current_index = 0
    window.player.network_caching_ms = 2000
    window.player.get_length_ms = lambda: 20_000
    window.player.get_time_ms = lambda: 5_000
    window.player.get_position = lambda: 0.25
    window.player.is_live_stream = lambda: False
    window._on_buffering(window.player.generation, 50.0)
    window.update_ui()
    expected = (0.25, 0.3)  # 5 s + 50 % de 2 s, sobre 20 s
    assert window.position_slider.buffered_range() == expected
    assert window.fullscreen_controller.slider.buffered_range() == expected
    window._on_buffering(window.player.generation, 100.0)
    window.update_ui()
    assert window.position_slider.buffered_range() == (0.25, 0.35)
    # Un archivo local no muestra franja.
    window.current_index = 1
    window.update_ui()
    assert window.position_slider.buffered_range() is None
    # Un stream en vivo tampoco (la barra esta deshabilitada).
    window.current_index = 0
    window.player.is_live_stream = lambda: True
    window.update_ui()
    assert window.position_slider.buffered_range() is None
    window._stall_timer.stop()
