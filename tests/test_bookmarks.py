from player import bookmarks


def _use_tmp_home(monkeypatch, tmp_path):
    monkeypatch.setattr(bookmarks.Path, "home", staticmethod(lambda: tmp_path))


def test_get_bookmarks_for_unknown_path_is_empty(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    assert bookmarks.get_bookmarks("video.mp4") == []


def test_add_bookmark_and_get_it_back(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("video.mp4", "Intro", 5000)
    result = bookmarks.get_bookmarks("video.mp4")
    assert result == [{"name": "Intro", "position_ms": 5000}]


def test_bookmarks_are_kept_sorted_by_position(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("video.mp4", "Segunda escena", 60000)
    bookmarks.add_bookmark("video.mp4", "Intro", 1000)
    bookmarks.add_bookmark("video.mp4", "Final", 120000)
    names = [b["name"] for b in bookmarks.get_bookmarks("video.mp4")]
    assert names == ["Intro", "Segunda escena", "Final"]


def test_bookmarks_are_scoped_per_file(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("a.mp4", "En a", 1000)
    bookmarks.add_bookmark("b.mp4", "En b", 2000)
    assert [b["name"] for b in bookmarks.get_bookmarks("a.mp4")] == ["En a"]
    assert [b["name"] for b in bookmarks.get_bookmarks("b.mp4")] == ["En b"]


def test_remove_bookmark_by_index(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("video.mp4", "Intro", 1000)
    bookmarks.add_bookmark("video.mp4", "Final", 120000)
    bookmarks.remove_bookmark("video.mp4", 0)
    result = bookmarks.get_bookmarks("video.mp4")
    assert result == [{"name": "Final", "position_ms": 120000}]


def test_remove_last_bookmark_clears_the_file_entry(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("video.mp4", "Único", 1000)
    bookmarks.remove_bookmark("video.mp4", 0)
    assert bookmarks.get_bookmarks("video.mp4") == []
    assert bookmarks._load_all() == {}


def test_remove_bookmark_with_out_of_range_index_is_a_no_op(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("video.mp4", "Intro", 1000)
    bookmarks.remove_bookmark("video.mp4", 5)
    assert len(bookmarks.get_bookmarks("video.mp4")) == 1


def test_rename_bookmark_by_index(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("video.mp4", "Intro", 1000)
    bookmarks.rename_bookmark("video.mp4", 0, "Apertura")
    assert bookmarks.get_bookmarks("video.mp4")[0]["name"] == "Apertura"


def test_bookmarks_persist_across_separate_calls(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.add_bookmark("video.mp4", "Intro", 1000)
    assert bookmarks.get_bookmarks("video.mp4") == [{"name": "Intro", "position_ms": 1000}]


def test_corrupted_bookmarks_file_is_treated_as_empty(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    bookmarks.bookmarks_file().parent.mkdir(parents=True, exist_ok=True)
    bookmarks.bookmarks_file().write_text("not valid json", encoding="utf-8")
    assert bookmarks.get_bookmarks("video.mp4") == []
