"""4.14: superposicion de estadisticas de reproduccion (tecla I)."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect

from player.stats_overlay import stats_lines, stats_rect

VIDEO = str(Path(__file__).parent / "assets" / "chapters.mkv")

TRACKS = [
    {"type": "video", "id": 0, "codec": "H264 - MPEG-4 AVC (part 10)", "fourcc": "h264",
     "width": 1920, "height": 1080, "fps": 23.976},
    {"type": "audio", "id": 1, "codec": "MPEG AAC Audio", "fourcc": "mp4a", "channels": 2, "rate": 48000},
    {"type": "audio", "id": 2, "codec": "A52 Audio", "fourcc": "a52 ", "channels": 6, "rate": 48000},
]
STATS = {
    "input_bitrate": 0.65, "demux_bitrate": 0.6, "displayed_pictures": 1200, "lost_pictures": 3,
    "decoded_video": 1205, "played_abuffers": 900, "lost_abuffers": 0,
    "demux_corrupted": 0, "demux_discontinuity": 0,
}


def test_lines_describe_the_selected_tracks_rates_and_frames():
    info = {"stats": STATS, "tracks": TRACKS, "video_track": 0, "audio_track": 2}
    assert stats_lines(info, "D3D11VA") == [
        "Video: H264 - MPEG-4 AVC (part 10) · 1920×1080 · 23,976 fps",
        "Audio: A52 Audio · 6 canales · 48000 Hz",
        "Entrada: 5,2 Mb/s · Demux: 4,8 Mb/s",
        "Fotogramas: 1200 mostrados · 3 perdidos · 1205 decodificados",
        "Búferes de audio: 900 reproducidos · 0 perdidos",
        "Decodificación por hardware (configurada): D3D11VA",
    ]


def test_audio_only_media_skips_video_lines_and_shows_demux_errors():
    stats = dict(STATS, input_bitrate=0.04, demux_bitrate=0.04, demux_corrupted=2, demux_discontinuity=1)
    info = {"stats": stats, "tracks": TRACKS[1:2], "video_track": -1, "audio_track": 1}
    lines = stats_lines(info, "Automática")
    assert lines == [
        "Audio: MPEG AAC Audio · 2 canales · 48000 Hz",
        "Entrada: 320 kb/s · Demux: 320 kb/s",
        "Búferes de audio: 900 reproducidos · 0 perdidos",
        "Errores del demultiplexor: 2 corruptos · 1 discontinuidades",
    ]


def test_nothing_loaded_or_no_counters_yet():
    assert stats_lines(None, "x") == ["Sin medio cargado"]
    info = {"stats": None, "tracks": [], "video_track": -1, "audio_track": -1}
    assert stats_lines(info, "x") == ["Estadísticas: todavía no disponibles"]


def test_a_whole_fps_has_no_decimals():
    info = {"stats": None, "tracks": [dict(TRACKS[0], fps=25.0)], "video_track": 0, "audio_track": -1}
    assert stats_lines(info, "x")[0].endswith("· 25 fps")


def test_the_box_sits_top_left_inside_the_video():
    frame = QRect(100, 50, 400, 300)
    assert stats_rect(frame, 200, 120) == QRect(116, 66, 200, 120)
    assert stats_rect(frame, 900, 900).size().width() == 400 - 32


# ------------------------------------------------- con libVLC real
try:
    import vlc  # noqa: F401
except OSError:
    vlc = None


@pytest.fixture
def window(monkeypatch):
    if vlc is None:
        pytest.skip("VLC (libvlc) no esta instalado")
    from PySide6.QtWidgets import QApplication

    from player import backend as backend_module
    from player import main_window as main_window_module

    QApplication.instance() or QApplication(sys.argv)
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )
    w = main_window_module.MainWindow()
    w.act_visualizer.setChecked(False)
    yield w
    w.act_stats_overlay.setChecked(False)
    w.close()


def _pump(predicate, timeout_s=8.0):
    from PySide6.QtWidgets import QApplication

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_the_i_key_shows_live_counters_of_the_playing_file(window):
    keys = {a.shortcut().toString(): a for a in window.actions()}
    assert keys["I"] is window.act_stats_overlay
    window.add_files_to_playlist([VIDEO])
    window.play_index(0)
    assert _pump(lambda: window.player.get_time_ms() > 300)
    keys["I"].trigger()
    assert window.stats_overlay.timer.isActive()
    assert _pump(lambda: "Fotogramas:" in window.stats_overlay.label.text())
    text = window.stats_overlay.label.text()
    assert text.startswith("Video: ")
    assert "Decodificación por hardware (configurada): Automática" in text
    keys["I"].trigger()
    assert not window.stats_overlay.timer.isActive()
    assert not window.stats_overlay.window.isVisible()
