"""Rutas normalizadas como clave, escritura atomica con .bak, validacion de
tipos y lectura de .m3u. Modulos puros: sin VLC ni Qt."""
import json
import os
import sys

import pytest

from player import bookmarks, config, jsonstore, recent_files, resume
from player.formats import normalize_path, path_key
from player.m3u import decode_playlist_bytes, format_m3u, parse_m3u


@pytest.fixture
def home(monkeypatch, tmp_path):
    for module in (resume, bookmarks, recent_files, config):
        monkeypatch.setattr(module.Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


# ------------------------------------------------------------ rutas
def test_normalize_path_makes_local_paths_absolute_and_native(tmp_path):
    mixed = str(tmp_path).replace("\\", "/") + "/dir\\sub/f.mkv".replace("\\", os.sep)
    assert normalize_path(mixed) == os.path.join(str(tmp_path), "dir", "sub", "f.mkv")


def test_normalize_path_leaves_urls_untouched():
    for url in ("http://example.com/a b.mp3", "rtsp://x/live", "ftp://host/f.mp3"):
        assert normalize_path(url) == url
        assert path_key(url) == url


def test_normalize_path_converts_file_uris(tmp_path):
    target = tmp_path / "canción 1.mp3"
    assert normalize_path(target.as_uri()) == str(target)


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="normcase solo pliega mayusculas en Windows")
def test_path_key_treats_slash_and_case_variants_as_the_same_file():
    assert path_key("C:/Videos/Peli.MKV") == path_key(r"c:\videos\peli.mkv") == path_key(r"C:\Videos\sub\..\Peli.mkv")


def test_resume_and_bookmarks_find_data_saved_under_another_spelling(home, tmp_path):
    native = str(tmp_path / "Peli.mkv")
    forward = native.replace("\\", "/")
    resume.save_position(forward, 60_000, 600_000)
    assert resume.get_saved_position_ms(native) == 60_000
    bookmarks.add_bookmark(forward, "Intro", 1000)
    assert [b["name"] for b in bookmarks.get_bookmarks(native)] == ["Intro"]


def test_old_unnormalized_keys_are_migrated_on_load(home, tmp_path):
    native = str(tmp_path / "a.mkv")
    resume.positions_file().parent.mkdir(parents=True, exist_ok=True)
    resume.positions_file().write_text(json.dumps({native.replace("\\", "/"): 42_000}), encoding="utf-8")
    assert resume.get_saved_position_ms(native) == 42_000


def test_recent_files_dedupe_slash_variants(home, tmp_path):
    native = str(tmp_path / "a.mkv")
    recent_files.add_recent_file(native.replace("\\", "/"))
    recent_files.add_recent_file(native)
    assert recent_files.get_recent_files() == [native]


# ------------------------------------------------------ JSON robusto
@pytest.mark.parametrize("module, file_fn, getter", [
    (resume, "positions_file", lambda: resume.get_saved_position_ms("x.mp4")),
    (bookmarks, "bookmarks_file", lambda: bookmarks.get_bookmarks("x.mp4")),
    (config, "config_file", config.get_opensubtitles_api_key),
])
def test_a_json_list_instead_of_a_dict_does_not_crash(home, module, file_fn, getter):
    path = getattr(module, file_fn)()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert getter() in (None, [])


def test_entries_with_invalid_types_are_dropped(home):
    resume.positions_file().parent.mkdir(parents=True, exist_ok=True)
    resume.positions_file().write_text(json.dumps({"a.mp4": "oops", "b.mp4": 5000}), encoding="utf-8")
    assert resume.get_saved_position_ms("a.mp4") is None
    assert resume.get_saved_position_ms("b.mp4") == 5000
    bookmarks.bookmarks_file().write_text(
        json.dumps({"v.mp4": [{"name": "ok", "position_ms": 1}, {"name": 3}], "w.mp4": {"x": 1}}), encoding="utf-8"
    )
    assert bookmarks.get_bookmarks("v.mp4") == [{"name": "ok", "position_ms": 1}]


def test_save_is_atomic_and_keeps_a_backup(home):
    resume.save_position("a.mp4", 60_000, 600_000)
    resume.save_position("b.mp4", 70_000, 600_000)
    path = resume.positions_file()
    backup = jsonstore.backup_path(path)
    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8")) == {path_key("a.mp4"): 60_000}
    # Sin temporales huerfanos en la carpeta.
    assert sorted(p.name for p in path.parent.iterdir()) == ["positions.json", "positions.json.bak"]


def test_a_truncated_main_file_falls_back_to_the_backup(home):
    resume.save_position("a.mp4", 60_000, 600_000)
    resume.save_position("b.mp4", 70_000, 600_000)
    resume.positions_file().write_text('{"trunc', encoding="utf-8")  # corte a mitad de escritura
    assert resume.get_saved_position_ms("a.mp4") == 60_000


def test_a_corrupt_main_file_does_not_overwrite_a_good_backup(home):
    resume.save_position("a.mp4", 60_000, 600_000)
    resume.save_position("b.mp4", 70_000, 600_000)
    resume.positions_file().write_text("garbage", encoding="utf-8")
    resume.save_position("c.mp4", 80_000, 600_000)
    backup = json.loads(jsonstore.backup_path(resume.positions_file()).read_text(encoding="utf-8"))
    assert path_key("a.mp4") in backup


def test_save_json_reports_failure_instead_of_raising(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    assert jsonstore.save_json(blocker / "data.json", {"a": 1}) is False


def test_positions_file_is_capped_dropping_the_oldest(home, monkeypatch):
    monkeypatch.setattr(resume, "MAX_SAVED_POSITIONS", 3)
    for name in ("a", "b", "c", "d"):
        resume.save_position(f"{name}.mp4", 60_000, 600_000)
    resume.save_position("b.mp4", 61_000, 600_000)  # refresca b
    resume.save_position("e.mp4", 60_000, 600_000)
    assert resume.get_saved_position_ms("a.mp4") is None
    assert resume.get_saved_position_ms("c.mp4") is None
    assert resume.get_saved_position_ms("b.mp4") == 61_000
    assert len(json.loads(resume.positions_file().read_text(encoding="utf-8"))) == 3


# ------------------------------------------------------------------ M3U
def test_m3u_relative_entries_resolve_against_the_playlist_folder(tmp_path):
    playlist = tmp_path / "listas" / "mix.m3u"
    entries = parse_m3u(b"#EXTM3U\n#EXTINF:1,x\ncancion.mp3\n../otra/b.mkv\n", str(playlist))
    assert entries == [
        str(tmp_path / "listas" / "cancion.mp3"),
        str(tmp_path / "otra" / "b.mkv"),
    ]


def test_m3u_decodes_utf8_with_bom_and_falls_back_to_cp1252():
    assert decode_playlist_bytes("\ufeffcanción.mp3".encode("utf-8")) == "canción.mp3"
    assert decode_playlist_bytes("canción.mp3".encode("cp1252")) == "canción.mp3"


def test_m3u_converts_file_uris_and_keeps_urls(tmp_path):
    target = tmp_path / "a b.mp3"
    data = f"{target.as_uri()}\nhttp://example.com/radio\n".encode("utf-8")
    assert parse_m3u(data, str(tmp_path / "x.m3u")) == [str(target), "http://example.com/radio"]


def test_m3u_round_trip(tmp_path):
    entries = [str(tmp_path / "ñ.mp3"), "http://example.com/s"]
    data = format_m3u(entries).encode("utf-8")
    assert parse_m3u(data, str(tmp_path / "x.m3u")) == entries
