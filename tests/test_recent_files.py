from player import recent_files


def _use_tmp_home(monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files.Path, "home", staticmethod(lambda: tmp_path))


def test_get_recent_files_is_empty_initially(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    assert recent_files.get_recent_files() == []


def test_add_recent_file_and_get_it_back(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.add_recent_file("video.mp4")
    assert recent_files.get_recent_files() == ["video.mp4"]


def test_most_recently_added_file_comes_first(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.add_recent_file("a.mp4")
    recent_files.add_recent_file("b.mp4")
    recent_files.add_recent_file("c.mp4")
    assert recent_files.get_recent_files() == ["c.mp4", "b.mp4", "a.mp4"]


def test_reopening_a_file_moves_it_to_the_front_without_duplicating(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.add_recent_file("a.mp4")
    recent_files.add_recent_file("b.mp4")
    recent_files.add_recent_file("a.mp4")
    assert recent_files.get_recent_files() == ["a.mp4", "b.mp4"]


def test_list_is_capped_at_max_recent_files(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    for i in range(recent_files.MAX_RECENT_FILES + 5):
        recent_files.add_recent_file(f"file{i}.mp4")
    result = recent_files.get_recent_files()
    assert len(result) == recent_files.MAX_RECENT_FILES
    # Las mas recientes se conservan; las mas viejas se descartan.
    newest = recent_files.MAX_RECENT_FILES + 4
    assert result[0] == f"file{newest}.mp4"
    assert f"file0.mp4" not in result
    assert f"file4.mp4" not in result


def test_add_recent_file_with_empty_path_is_a_no_op(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.add_recent_file("")
    assert recent_files.get_recent_files() == []


def test_clear_recent_files_empties_the_list(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.add_recent_file("a.mp4")
    recent_files.add_recent_file("b.mp4")
    recent_files.clear_recent_files()
    assert recent_files.get_recent_files() == []


def test_recent_files_persist_across_separate_calls(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.add_recent_file("video.mp4")
    assert recent_files.get_recent_files() == ["video.mp4"]


def test_corrupted_recent_files_file_is_treated_as_empty(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.recent_files_file().parent.mkdir(parents=True, exist_ok=True)
    recent_files.recent_files_file().write_text("not valid json", encoding="utf-8")
    assert recent_files.get_recent_files() == []


def test_non_list_json_content_is_treated_as_empty(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    recent_files.recent_files_file().parent.mkdir(parents=True, exist_ok=True)
    recent_files.recent_files_file().write_text('{"not": "a list"}', encoding="utf-8")
    assert recent_files.get_recent_files() == []
