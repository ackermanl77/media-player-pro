from player.formats import (
    ALL_EXTS,
    AUDIO_EXTS,
    VIDEO_EXTS,
    build_open_filter,
    format_time,
    is_url,
)


def test_format_time_under_a_minute():
    assert format_time(45_000) == "00:45"


def test_format_time_minutes_and_seconds():
    assert format_time(125_000) == "02:05"


def test_format_time_includes_hours_when_an_hour_or_longer():
    assert format_time(3_725_000) == "1:02:05"


def test_format_time_clamps_negative_values_to_zero():
    assert format_time(-500) == "00:00"


def test_is_url_recognizes_streaming_schemes_case_insensitively():
    assert is_url("http://example.com/stream.mp3")
    assert is_url("RTSP://example.com/live")


def test_is_url_rejects_local_paths():
    assert not is_url("C:/Users/me/song.mp3")
    assert not is_url("/home/me/video.mkv")


def test_all_exts_is_the_disjoint_union_of_audio_and_video():
    assert ALL_EXTS == AUDIO_EXTS | VIDEO_EXTS
    assert AUDIO_EXTS.isdisjoint(VIDEO_EXTS)


def test_build_open_filter_lists_every_supported_extension():
    filt = build_open_filter()
    for ext in ALL_EXTS:
        assert f"*{ext}" in filt
    assert "Todos los archivos (*.*)" in filt


# --------------------------------------------------- esquemas de URL (3.2)
import pytest  # noqa: E402

from player.formats import (  # noqa: E402
    format_rate,
    is_audio_file,
    is_playlist_file,
    looks_like_url,
    parse_time_input,
    snapshot_file_name,
)


@pytest.mark.parametrize("url", [
    "rtsps://cam/x", "srt://host:9000", "rtp://@239.0.0.1:5004", "ftp://h/a.mp4", "smb://nas/v.mkv",
    "mmsh://h/s", "rtmps://h/live", "HTTP://EXAMPLE.COM/a", "udp://@:1234", "dvb-t://frequency=0",
])
def test_any_scheme_except_file_is_a_url(url):
    assert is_url(url)


@pytest.mark.parametrize("path", ["file:///C:/a.mp3", r"C:\a.mp3", "C:/a.mp3", "a.mp3", r"\\nas\v.mkv"])
def test_file_uris_and_paths_are_not_urls(path):
    assert not is_url(path)


def test_a_remote_mp3_is_not_a_local_audio_file():
    # Antes: "ftp://h/song.mp3" contaba como audio local (visualizador,
    # posiciones guardadas, marcadores).
    assert not is_audio_file("ftp://h/song.mp3")
    assert is_audio_file("C:/m/song.mp3")


def test_playlist_files_and_clipboard_urls():
    assert is_playlist_file("C:/listas/a.M3U8") and not is_playlist_file("http://h/a.m3u")
    assert looks_like_url("  https://example.com/radio  ")
    assert not looks_like_url("https://") and not looks_like_url("hola") and not looks_like_url("a\nhttp://b")


@pytest.mark.parametrize("text, length, expected", [
    ("1:02:03", 0, 3_723_000), ("12:34", 0, 754_000), ("95", 0, 95_000), ("12:34,5", 0, 754_500),
    ("40%", 100_000, 40_000), ("99:00", 60_000, 60_000), (" 0:05 ", 0, 5_000),
])
def test_parse_time_input(text, length, expected):
    assert parse_time_input(text, length) == expected


@pytest.mark.parametrize("text", ["", "abc", "1:75", "1:60:00", "50%", "-3", "120%"])
def test_parse_time_input_rejects_invalid(text):
    assert parse_time_input(text, 0 if text == "50%" else 10_000) is None


def test_snapshot_file_name_and_rate_format():
    assert snapshot_file_name("C:/v/Mi peli.mkv", 3_723_456) == "Mi peli_01-02-03.456.png"
    assert snapshot_file_name("rtsp://camara:554/x", 0) == "camara_554_00-00-00.000.png"
    assert format_rate(1.0) == "1,0×" and format_rate(1.25) == "1,25×" and format_rate(0.5) == "0,5×"
