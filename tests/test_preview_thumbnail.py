"""Vista previa de la barra de progreso: reproductor secundario liviano
(VLCPlayer.load_preview_media/seek_preview/take_preview_snapshot), cache de
miniaturas y captura sin espera fija en MainWindow.

tests/assets/chapters.mkv es un video de prueba generado con ffmpeg
(testsrc 160x90, 10 fps, tono de 440 Hz, 6 s, 3 capitulos de 2 s:
"Intro", "Medio", "Final"). La captura real usa una ventana Win32 propia
creada OCULTA (nunca se muestra, no se simula entrada). Se omite si no hay
VLC instalado."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten las pruebas de vista previa.", allow_module_level=True)

from PySide6.QtCore import QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from player import backend as backend_module
from player import preview as preview_module
from player.backend import PREVIEW_MEDIA_OPTIONS, PREVIEW_VLC_ARGS, VLCPlayer
from player.preview import ThumbnailCache, bucket_for

VIDEO = str(Path(__file__).parent / "assets" / "chapters.mkv")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _headless_player(monkeypatch) -> VLCPlayer:
    monkeypatch.setattr(backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy"])
    return VLCPlayer()


def _wait_until(predicate, timeout_s: float = 8.0, interval_s: float = 0.1) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


# ------------------------------------------------------------- backend
def test_preview_current_path_is_none_before_loading(monkeypatch):
    player = _headless_player(monkeypatch)
    assert player.preview_current_path() is None


def test_seek_preview_and_take_preview_snapshot_are_no_ops_before_loading(tmp_path, monkeypatch):
    player = _headless_player(monkeypatch)
    player.seek_preview(0.5)  # no debe lanzar aunque no haya preview player aun
    assert player.take_preview_snapshot(str(tmp_path / "preview.png")) is False


@pytest.mark.parametrize("path", ["C:/musica/tema.mp3", "D:/a/b.flac", "https://example.com/v.mp4",
                                  "rtsp://camara/live", "smb://nas/peli.mkv"])
def test_no_preview_player_for_audio_or_urls(monkeypatch, path):
    # Antes: con audio el reproductor de vista previa decodificaba sin fin
    # (sin fotogramas que capturar); con URLs abria una segunda conexion.
    player = _headless_player(monkeypatch)
    assert not player.preview_supported(path)
    assert player.load_preview_media(path) is False
    assert not player.has_preview_player()


def test_preview_player_has_its_own_lean_instance(monkeypatch):
    created = []
    original = backend_module.create_instance_with_fallback

    def spy(base, groups, *rest):
        created.append(list(base) + [x for _n, g in groups for x in g])
        return original(base, groups, *rest)

    monkeypatch.setattr(backend_module, "create_instance_with_fallback", spy)
    player = _headless_player(monkeypatch)
    preview = player._ensure_preview_player()
    assert created[-1] == PREVIEW_VLC_ARGS  # sin audio, sin subtitulos, sin GPU/visualizador
    assert {":no-audio", ":no-spu", ":input-fast-seek"} <= set(PREVIEW_MEDIA_OPTIONS)
    # Recrear la principal (visualizador, tamano de subtitulos) no la toca.
    player._create_instance(visualizer=True)
    assert player._preview_player is preview
    player.close()


def test_release_preview_player_clears_state(monkeypatch):
    player = _headless_player(monkeypatch)
    try:
        assert player.load_preview_media(VIDEO) is True
        assert player.preview_current_path() == VIDEO
        player.release_preview_player()
        assert player.preview_current_path() is None
        assert not player.has_preview_player() and player._preview_instance is None
        player.seek_preview(0.2)  # tras liberar, no debe lanzar
    finally:
        player.close()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="usa una ventana Win32 oculta")
def test_preview_snapshot_of_a_real_video(monkeypatch, tmp_path):
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = [
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
    ]
    user32.DestroyWindow.argtypes = [wt.HWND]
    host = user32.CreateWindowExW(0, "STATIC", "preview", 0x00CF0000 | 0x02000000, 0, 0, 160, 90,
                                  None, None, None, None)  # sin WS_VISIBLE

    class _Host:
        def winId(self):
            return host

    player = _headless_player(monkeypatch)
    player.attach_preview_output(_Host())
    snapshot = str(tmp_path / "preview.png")
    try:
        assert player.load_preview_media(VIDEO)
        player.seek_preview(0.5)

        def _written():
            player.take_preview_snapshot(snapshot, width=160, height=90)
            return os.path.exists(snapshot) and os.path.getsize(snapshot) > 0

        if not _wait_until(_written, timeout_s=10.0):
            pytest.skip("libVLC no genero salida de video en este equipo")
        assert player.is_preview_warmed_up()
    finally:
        player.close()
        user32.DestroyWindow(host)


# ------------------------------------------------------------- cache
def test_thumbnail_cache_buckets_and_evicts_least_recently_used():
    cache = ThumbnailCache(capacity=2)
    assert bucket_for(0.5) == 100 and bucket_for(-1) == 0 and bucket_for(2) == 200
    cache.put("C:/v/a.mkv", 0.501, "A")
    # Misma cubeta (0,5 %) y mismo archivo aunque cambie la forma de la ruta.
    assert cache.get(os.path.normpath("C:/v/a.mkv"), 0.499) == "A"
    assert cache.get("C:/v/a.mkv", 0.6) is None
    cache.put("C:/v/a.mkv", 0.2, "B")
    cache.get("C:/v/a.mkv", 0.5)  # "A" pasa a ser la mas reciente
    cache.put("C:/v/b.mkv", 0.2, "C")
    assert len(cache) == 2
    assert cache.get("C:/v/a.mkv", 0.2) is None  # "B" fue la desalojada
    assert cache.get("C:/v/a.mkv", 0.5) == "A"


def test_snapshot_temp_files_are_per_process_and_unique():
    a, b = preview_module.new_snapshot_path(), preview_module.new_snapshot_path()
    try:
        assert a != b
        assert os.path.basename(a).startswith("rmp_preview_")
    finally:
        preview_module.remove_quietly(a)
        preview_module.remove_quietly(b)
    preview_module.remove_quietly(a)  # borrar dos veces no lanza


# ------------------------------------------------------------- ventana
@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )
    from player.main_window import MainWindow

    w = MainWindow()
    yield w
    w.close()


def test_hover_over_an_audio_track_shows_only_the_time(window):
    window.add_files_to_playlist(["C:/fake/song.mp3"])
    window.current_index = 0
    window.player.get_length_ms = lambda: 60_000
    window.preview.pending_fraction = 0.5
    window.preview.pending_pos = QPoint(100, 100)
    window.preview.show_preview()
    try:
        assert window.preview.time_label.text() == "00:30"
        assert window.preview.thumbnail_label.isHidden()
        assert not window.player.has_preview_player()
        assert not window.preview.capture_timer.isActive()
    finally:
        window.preview.hide()


def test_hover_serves_cached_thumbnails_without_seeking(window):
    window.add_files_to_playlist([VIDEO])
    window.current_index = 0
    window.player.get_length_ms = lambda: 6_000
    pixmap = QPixmap(160, 90)
    window.preview.cache.put(VIDEO, 0.25, pixmap)
    seeks = []
    window.player.seek_preview = lambda f: seeks.append(f)
    window.preview.pending_fraction = 0.251
    window.preview.pending_pos = QPoint(100, 100)
    window.preview.show_preview()
    try:
        assert seeks == []
        assert not window.preview.capture_timer.isActive()
        assert not window.preview.thumbnail_label.pixmap().isNull()
    finally:
        window.preview.hide()


def test_cache_miss_clears_the_old_frame_and_polls_for_the_new_one(window):
    window.add_files_to_playlist([VIDEO])
    window.current_index = 0
    window.player.get_length_ms = lambda: 6_000
    window.preview.ensure_popup()
    window.preview.thumbnail_label.setPixmap(QPixmap(160, 90))  # fotograma "viejo"
    seeks = []
    window.player.load_preview_media = lambda p: True
    window.player.preview_current_path = lambda: VIDEO
    window.player.seek_preview = lambda f: seeks.append(f)
    window.preview.pending_fraction = 0.75
    window.preview.pending_pos = QPoint(100, 100)
    window.preview.show_preview()
    try:
        assert seeks == [0.75]
        assert window.preview.thumbnail_label.pixmap().isNull()  # sin fotograma viejo
        assert window.preview.capture_timer.isActive()
        assert window.preview.capture_timer.interval() == preview_module.CAPTURE_POLL_MS
        # Se rinde a los ~400 ms en vez de esperar para siempre.
        window.player.take_preview_snapshot = lambda *a, **k: False
        for _ in range(preview_module.CAPTURE_TIMEOUT_MS // preview_module.CAPTURE_POLL_MS + 1):
            window.preview.poll_snapshot()
        assert not window.preview.capture_timer.isActive()
    finally:
        window.preview.hide()


def test_preview_player_is_released_after_idle(window):
    window.player._preview_player = object()  # "hay un reproductor de vista previa"
    window.player.is_preview_warmed_up = lambda: True
    released = []
    window.player.release_preview_player = lambda: released.append(True)
    window.preview.on_hover_ended()
    assert window.preview.idle_timer.isActive()
    assert window.preview.idle_timer.interval() == preview_module.IDLE_RELEASE_MS
    window.player._preview_player = None
    window.preview.idle_timer.stop()
