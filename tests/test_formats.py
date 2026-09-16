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
