"""Expansion de entradas (carpetas, .m3u, URLs) y orden natural."""
import os

from player.inputs import expand_inputs, filter_dropped, natural_sort_key, scan_folder, scan_folder_batches


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


def test_scan_folder_batches_yield_sorted_chunks(tmp_path):
    paths = [
        _touch(tmp_path / "Track 10.flac"),
        _touch(tmp_path / "Track 2.flac"),
        _touch(tmp_path / "sub" / "video.MKV"),
    ]
    batches = list(scan_folder_batches(str(tmp_path), batch_size=2))
    assert batches == [
        [paths[2], paths[1]],
        [paths[0]],
    ]


def test_scan_folder_batches_match_scan_folder_order(tmp_path):
    # Casos donde ordenar carpeta por carpeta difiere de ordenar la ruta
    # completa: "a" vs "a b.mp3", "Disc 1" vs "Disc 10.mp3", mayusculas.
    for name in ("a b.mp3", "a/x.mp3", "Disc 10.mp3", "Disc 1/02.ogg", "Disc 1/1.ogg",
                 "Z/inner/deep.mp4", "b.MP3", "B/c.flac", "notes.txt"):
        _touch(tmp_path / name)
    flat = [path for batch in scan_folder_batches(str(tmp_path), batch_size=3) for path in batch]
    assert flat == scan_folder(str(tmp_path))
    assert len(flat) == 8


def test_scan_folder_batches_honor_cancellation(tmp_path):
    a = _touch(tmp_path / "a.mp3")
    _touch(tmp_path / "b.mp3")
    calls = {"count": 0}

    def should_stop():
        calls["count"] += 1
        return calls["count"] > 1

    assert list(scan_folder_batches(str(tmp_path), batch_size=1, should_stop=should_stop)) == [[a]]


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
