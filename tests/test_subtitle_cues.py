"""4.15: saltar a la linea anterior/siguiente de un subtitulo externo."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from player.subtitle_cues import adjacent_cue_time, load_cue_starts, parse_cues

SRT = """1
00:00:01,000 --> 00:00:02,500
Hola

2
00:00:04,200 --> 00:00:06,000
¿Qué tal?

3
01:00:00,005 --> 01:00:01,000
Una hora despues
"""

VTT = """WEBVTT

00:01.500 --> 00:03.000
sin horas

00:00:05.000 --> 00:00:07.000 align:start
con horas y ajustes
"""

ASS = """[Script Info]
Title: prueba

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:02.50,0:00:04.00,Default,,0,0,0,,primero
Dialogue: 0,0:00:02.50,0:00:04.00,Default,,0,0,0,,dos hablantes a la vez
Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,no es una linea
Dialogue: 0,0:00:10.05,0:00:12.00,Default,,0,0,0,,{\\i1}tercero
"""


def test_srt_cues_keep_hours_and_milliseconds():
    assert parse_cues(SRT, ".srt") == [(1000, 2500), (4200, 6000), (3_600_005, 3_601_000)]


def test_vtt_accepts_timestamps_without_hours_and_cue_settings():
    assert parse_cues(VTT, ".VTT") == [(1500, 3000), (5000, 7000)]


def test_ass_reads_dialogue_centiseconds_and_merges_simultaneous_lines():
    assert parse_cues(ASS, ".ass") == [(2500, 4000), (10_050, 12_000)]


def test_unsupported_formats_have_no_cues(tmp_path):
    sub = tmp_path / "pelicula.sub"
    sub.write_text("{100}{200}MicroDVD cuenta fotogramas", encoding="utf-8")
    assert load_cue_starts(str(sub)) == []
    assert load_cue_starts(str(tmp_path / "no_existe.srt")) == []


def test_files_are_decoded_like_playlists(tmp_path):
    utf8 = tmp_path / "utf8.srt"
    utf8.write_bytes(b"\xef\xbb\xbf" + SRT.encode("utf-8"))
    ansi = tmp_path / "ansi.srt"
    ansi.write_bytes(SRT.encode("cp1252"))
    assert load_cue_starts(str(utf8)) == load_cue_starts(str(ansi)) == [1000, 4200, 3_600_005]


def test_next_skips_the_line_it_just_landed_on():
    starts = [1000, 4200, 9000]
    assert adjacent_cue_time(starts, 0, 1) == 1000
    assert adjacent_cue_time(starts, 1000, 1) == 4200
    assert adjacent_cue_time(starts, 9000, 1) is None


def test_previous_restarts_the_current_line_after_its_first_second():
    starts = [1000, 4200, 9000]
    assert adjacent_cue_time(starts, 6000, -1) == 4200   # dentro de la linea 2: a su inicio
    assert adjacent_cue_time(starts, 4500, -1) == 1000   # recien empezada: a la anterior
    assert adjacent_cue_time(starts, 1500, -1) is None


def test_the_subtitle_delay_moves_the_targets():
    starts = [1000, 4200]
    assert adjacent_cue_time(starts, 0, 1, delay_ms=500) == 1500
    assert adjacent_cue_time(starts, 6000, -1, delay_ms=-300) == 3900
    assert adjacent_cue_time(starts, 500, -1, delay_ms=-2000) == 0  # nunca antes de 0:00


# ------------------------------------------------------------ en la ventana
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
    w.close()


def _fake_playback(window, monkeypatch, subtitles, time_ms, track=2, delay_ms=0):
    """Solo el estado que lee seek_subtitle_line: sin reproducir nada."""
    seeks = []
    monkeypatch.setattr(window.player, "external_subtitles", lambda: list(subtitles))
    monkeypatch.setattr(window.player, "get_current_subtitle_track", lambda: track)
    monkeypatch.setattr(window.player, "get_time_ms", lambda: time_ms)
    monkeypatch.setattr(window.player, "get_subtitle_delay_ms", lambda: delay_ms)
    monkeypatch.setattr(window.player, "set_time_ms", seeks.append)
    monkeypatch.setattr(type(window), "current_index", property(lambda self: 0))
    return seeks


def test_alt_down_and_alt_up_jump_between_lines_of_the_last_loaded_subtitle(window, monkeypatch, tmp_path):
    first = tmp_path / "es.srt"
    first.write_text("1\n00:00:30,000 --> 00:00:31,000\nno es este\n", encoding="utf-8")
    last = tmp_path / "en.srt"
    last.write_text(SRT, encoding="utf-8")
    # 3,5 s: dentro de la primera linea (se ve en 1,1 s) y despues de su primer segundo.
    seeks = _fake_playback(window, monkeypatch, [str(first), str(last)], time_ms=3500, delay_ms=100)
    keys = {a.shortcut().toString(): a for a in window.actions()}
    keys["Alt+Down"].trigger()
    keys["Alt+Up"].trigger()
    assert seeks == [4300, 1100]


def test_without_an_active_external_subtitle_it_only_explains(window, monkeypatch, tmp_path):
    sub = tmp_path / "s.srt"
    sub.write_text(SRT, encoding="utf-8")
    seeks = _fake_playback(window, monkeypatch, [], time_ms=0)
    window.seek_subtitle_line(1)
    assert window._osd_label.text() == "Solo con un subtítulo externo activo"
    seeks = _fake_playback(window, monkeypatch, [str(sub)], time_ms=0, track=-1)
    window.seek_subtitle_line(1)
    assert seeks == []


def test_a_changed_subtitle_file_is_read_again(window, monkeypatch, tmp_path):
    sub = tmp_path / "s.srt"
    sub.write_text(SRT, encoding="utf-8")
    seeks = _fake_playback(window, monkeypatch, [str(sub)], time_ms=0)
    window.seek_subtitle_line(1)
    sub.write_text("1\n00:00:00,700 --> 00:00:01,000\nnueva version\n", encoding="utf-8")
    os.utime(sub, (os.path.getatime(sub), os.path.getmtime(sub) + 5))
    window.seek_subtitle_line(1)
    assert seeks == [1000, 700]
    assert Path(sub).exists()
