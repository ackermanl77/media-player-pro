"""Expansion de entradas (carpetas, .m3u, URLs) y orden natural."""
import os

from player.inputs import expand_inputs, filter_dropped, natural_sort_key, scan_folder


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return str(path)


def test_natural_sort_is_case_insensitive_and_numeric():
    names = ["Pista 10.mp3", "pista 2.mp3", "Pista 1.mp3", "b.mp3", "A.mp3"]
    assert sorted(names, key=natural_sort_key) == ["A.mp3", "b.mp3", "Pista 1.mp3", "pista 2.mp3", "Pista 10.mp3"]


def test_scan_folder_recurses_and_keeps_only_media(tmp_path):
    _touch(tmp_path / "Track 10.flac")
    _touch(tmp_path / "Track 2.flac")
    _touch(tmp_path / "notas.txt")
    _touch(tmp_path / "sub" / "video.MKV")
    found = scan_folder(str(tmp_path))
    assert [os.path.relpath(p, tmp_path) for p in found] == [
        os.path.join("sub", "video.MKV"), "Track 2.flac", "Track 10.flac",
    ]


def test_expand_inputs_handles_folders_playlists_urls_and_files(tmp_path):
    a = _touch(tmp_path / "musica" / "a.mp3")
    b = _touch(tmp_path / "otra" / "b.ogg")
    playlist = tmp_path / "lista.m3u8"
    playlist.write_text("#EXTM3U\notra/b.ogg\nhttp://radio/stream\n", encoding="utf-8")
    result = expand_inputs([str(tmp_path / "musica"), str(playlist), "srt://host:9000", "", str(tmp_path / "x.dat")])
    assert result == [a, b, "http://radio/stream", "srt://host:9000", str(tmp_path / "x.dat")]


def test_dropped_files_skip_non_media_but_expand_folders_and_lists(tmp_path):
    media = _touch(tmp_path / "v.mp4")
    other = _touch(tmp_path / "leeme.txt")
    playlist = tmp_path / "l.m3u"
    playlist.write_text(media + "\n", encoding="utf-8")
    assert filter_dropped([media, other, str(playlist), "https://x/y"]) == [media, media, "https://x/y"]
