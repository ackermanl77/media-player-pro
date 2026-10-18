"""Paginas de video con yt-dlp (3.15), sin red: el resultado de yt-dlp se simula.
(Probado a mano con yt-dlp real y una pagina de archive.org: se resolvio, se
reprodujo y libVLC informo la duracion real.)"""
import json
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from player import web_video
from player.web_video import WebStream, WebVideoError, is_page_url, media_options

SPLIT = {
    "title": "Concierto", "http_headers": {"User-Agent": "UA/1"},
    "requested_formats": [
        {"url": "https://cdn.example/v.mp4", "vcodec": "avc1", "acodec": "none", "http_headers": {"User-Agent": "UA/1", "Referer": "https://site/"}},
        {"url": "https://cdn.example/a.m4a", "vcodec": "none", "acodec": "mp4a"},
    ],
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_only_video_pages_on_known_sites_are_sent_to_yt_dlp():
    assert is_page_url("https://www.youtube.com/watch?v=abc") and is_page_url("https://youtu.be/abc")
    assert is_page_url("https://m.twitch.tv/somebody") and is_page_url("https://vimeo.com/1")
    assert not is_page_url("http://radio.example:8000/live")  # an Internet radio stream stays direct
    assert not is_page_url("https://notyoutube.com/x") and not is_page_url("rtsp://youtube.com/x")
    assert not is_page_url("C:\\videos\\a.mp4")


def test_split_and_single_results_and_playlists():
    split = web_video._from_info("p", SPLIT)
    assert (split.video_url, split.audio_url, split.title) == ("https://cdn.example/v.mp4", "https://cdn.example/a.m4a", "Concierto")
    assert media_options(split) == [":input-slave=https://cdn.example/a.m4a", ":http-user-agent=UA/1", ":http-referrer=https://site/"]
    swapped = web_video._from_info("p", {"requested_formats": SPLIT["requested_formats"][::-1]})
    assert swapped.video_url.endswith("v.mp4") and swapped.audio_url.endswith("a.m4a")  # audio-first order fixed
    single = web_video._from_info("p", {"url": "https://cdn.example/both.mp4", "title": "T"})
    assert single.audio_url is None and media_options(single) == []
    playlist = web_video._from_info("p", {"_type": "playlist", "entries": [None, {"url": "https://x/1.mp4"}]})
    assert playlist.video_url == "https://x/1.mp4"
    with pytest.raises(WebVideoError):
        web_video._from_info("p", {"title": "no streams"})


def test_the_yt_dlp_program_is_used_when_the_module_is_not_installed(monkeypatch):
    monkeypatch.setattr(web_video, "_module_available", lambda: False)
    monkeypatch.setattr(web_video, "_executable", lambda: "C:\\tools\\yt-dlp.exe")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(SPLIT), stderr="")

    monkeypatch.setattr(web_video.subprocess, "run", fake_run)
    stream = web_video.resolve("https://youtu.be/abc")
    assert stream.page_url == "https://youtu.be/abc" and stream.audio_url.endswith("a.m4a")
    assert calls[0][:2] == ["C:\\tools\\yt-dlp.exe", "-J"] and calls[0][-1] == "https://youtu.be/abc"
    monkeypatch.setattr(web_video.subprocess, "run",
                        lambda args, **kw: subprocess.CompletedProcess(args, 1, stdout="", stderr="x\nERROR: Video unavailable"))
    with pytest.raises(WebVideoError, match="Video unavailable"):
        web_video.resolve("https://youtu.be/gone")
    monkeypatch.setattr(web_video, "_executable", lambda: None)
    assert not web_video.available()
    with pytest.raises(WebVideoError, match="no está instalado"):
        web_video.resolve("https://youtu.be/abc")


def test_the_backend_plays_the_resolved_streams_for_the_page_url(qapp):
    try:
        import vlc
        from player.backend import VLCPlayer
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    player = VLCPlayer()
    try:
        player._create_instance(visualizer=False)
        stream = WebStream("https://youtu.be/abc", "https://cdn.example/v.mp4", "https://cdn.example/a.m4a", "Concierto")
        player.set_web_stream(stream)
        media = player._new_media("https://youtu.be/abc")
        assert media.get_mrl() == "https://cdn.example/v.mp4" and media.get_meta(vlc.Meta.Title) == "Concierto"
        player.forget_web_stream("https://youtu.be/abc")
        assert player._new_media("https://youtu.be/abc").get_mrl().startswith("https://youtu.be/abc")
    finally:
        player.close()


def test_the_window_resolves_then_plays_and_reports_failures(qapp, monkeypatch, tmp_path):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    from player import settings as settings_module

    monkeypatch.setattr(settings_module, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(web_video, "available", lambda: True)
    outcome = {}

    class FakeWorker:
        def __init__(self, page_url, on_done, on_failed):
            self.page_url, self.on_done, self.on_failed = page_url, on_done, on_failed

        def start(self):
            if outcome.get("fail"):
                self.on_failed("yt-dlp no pudo abrir la página: ERROR: Private video")
            else:
                self.on_done(WebStream(self.page_url, "https://cdn.example/v.mp4", None, "Mi video"))

        def wait(self, ms=0):
            return True

    monkeypatch.setattr(web_video, "ResolveWorker", FakeWorker)
    window = MainWindow()
    try:
        window.player.media_player.audio_set_mute(True)
        loads = []
        monkeypatch.setattr(window.player, "load", lambda path, **kw: loads.append(path))
        monkeypatch.setattr(window.player, "play", lambda: None)
        window.playlist.add(["https://youtu.be/abc"])
        window.play_index(0)
        assert loads == ["https://youtu.be/abc"] and window.player.web_stream("https://youtu.be/abc").title == "Mi video"
        window.play_index(0)  # still fresh: no new resolution, plays at once
        assert loads == ["https://youtu.be/abc"] * 2
        outcome["fail"] = True
        window.playlist.add(["https://youtu.be/private"])
        window.play_index(1)
        assert loads == ["https://youtu.be/abc"] * 2  # nothing loaded
        assert "Private video" in window.statusBar().currentMessage()
    finally:
        window.close()
