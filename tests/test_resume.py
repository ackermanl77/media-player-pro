from player import resume


def _use_tmp_home(monkeypatch, tmp_path):
    monkeypatch.setattr(resume.Path, "home", staticmethod(lambda: tmp_path))


def test_save_and_get_a_normal_position(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    resume.save_position("video.mp4", 60_000, 600_000)
    assert resume.get_saved_position_ms("video.mp4") == 60_000


def test_get_saved_position_for_unknown_path_is_none(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    assert resume.get_saved_position_ms("never-opened.mp4") is None


def test_position_near_the_start_is_not_saved(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    resume.save_position("video.mp4", 500, 600_000)
    assert resume.get_saved_position_ms("video.mp4") is None


def test_position_near_the_end_is_not_saved(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    resume.save_position("video.mp4", 590_000, 600_000)
    assert resume.get_saved_position_ms("video.mp4") is None


def test_saving_near_the_end_clears_a_previous_saved_position(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    resume.save_position("video.mp4", 60_000, 600_000)
    resume.save_position("video.mp4", 590_000, 600_000)
    assert resume.get_saved_position_ms("video.mp4") is None


def test_clear_position_removes_only_that_path(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    resume.save_position("a.mp4", 60_000, 600_000)
    resume.save_position("b.mp4", 90_000, 600_000)
    resume.clear_position("a.mp4")
    assert resume.get_saved_position_ms("a.mp4") is None
    assert resume.get_saved_position_ms("b.mp4") == 90_000


def test_positions_persist_across_separate_calls(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    resume.save_position("a.mp4", 60_000, 600_000)
    # Simula un segundo arranque de la app leyendo el mismo archivo en disco.
    assert resume.get_saved_position_ms("a.mp4") == 60_000


def test_corrupted_positions_file_is_treated_as_empty(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    resume.positions_file().parent.mkdir(parents=True, exist_ok=True)
    resume.positions_file().write_text("not valid json", encoding="utf-8")
    assert resume.get_saved_position_ms("video.mp4") is None
