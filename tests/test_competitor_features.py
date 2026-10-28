"""The 2026-10-21 competitor rows: audio effects (3.17), network and disc
sources (3.18), convert and record (3.19) and video filters (4.17)."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from player import converter, sources
from player.settings import load_settings, save_settings
from player.video_options import AUDIO_EFFECT_VALUES, PITCH_STEPS, VIDEO_FILTER_VALUES, format_pitch

ASSET = os.path.join(os.path.dirname(__file__), "assets", "chapters.mkv")

try:
    import vlc  # noqa: F401
except OSError:
    vlc = None


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _backend():
    if vlc is None:
        pytest.skip("VLC (libvlc) no esta instalado")
    from player import backend

    return backend


# ---- 3.17 / 4.17: instance options and the filter chain ----


def test_rotation_and_video_filters_share_one_video_filter_option():
    backend = _backend()
    assert backend.video_filter_instance_args("", ()) == []
    assert backend.video_filter_instance_args("90", ()) == backend.rotation_instance_args("90")
    assert backend.video_filter_instance_args("", ("hqdn3d", "sharpen")) == ["--video-filter=sharpen:hqdn3d"]
    assert backend.video_filter_instance_args("hflip", ("postproc", "nope")) == [
        "--video-filter=transform:postproc", "--transform-type=hflip", "--postproc-q=6"]
    assert set(VIDEO_FILTER_VALUES) == {"sharpen", "hqdn3d", "gradfun", "postproc"}


def test_audio_effects_build_the_chain_and_their_instance_options():
    backend = _backend()
    assert backend.audio_filter_chain(False, False) == ""
    assert backend.audio_filter_chain(True, True, ("stereo_widen", "compressor"), -2) == (
        "equalizer:normvol:compressor:stereo_widen:scaletempo_pitch")
    assert backend.audio_effect_instance_args((), 0) == []
    assert backend.audio_effect_instance_args((), 2.5) == ["--pitch-shift=2.5"]
    assert backend.audio_effect_instance_args(("compressor",), 0) == backend.NIGHT_MODE_ARGS
    assert format_pitch(0) == "Original" and format_pitch(-1) == "−1 semitono" and format_pitch(3) == "+3 semitonos"
    assert 0 in PITCH_STEPS


def test_libvlc_accepts_every_new_option(qapp):
    backend = _backend()
    for args in (backend.video_filter_instance_args("90", VIDEO_FILTER_VALUES),
                 backend.audio_effect_instance_args(AUDIO_EFFECT_VALUES, 3)):
        instance = vlc.Instance(["--quiet", *args])
        assert instance is not None, args
        instance.release()


def test_effects_change_the_live_chain_and_pitch_needs_a_new_instance(qapp, monkeypatch):
    backend = _backend()
    chains = []
    monkeypatch.setattr(backend.vlc_internals, "set_audio_filters", lambda player, chain: chains.append(chain) or True)
    monkeypatch.setattr(backend.vlc_internals, "audio_filters_supported", lambda: True)
    player = backend.VLCPlayer()
    try:
        assert player.set_audio_effects(("stereo_widen",)) is False, "live: no reload"
        assert chains[-1] == "stereo_widen"
        assert player.set_audio_effects(("compressor", "stereo_widen")) is True, "night mode has instance options"
        assert player.set_pitch(2) is True and player._needs_new_instance(False)
        assert player.set_pitch(2) is False
        assert player.set_pitch(40) is True and player.get_pitch() == 12.0
        player.set_video_filters(("gradfun", "bogus"))
        assert player.get_video_filters() == ("gradfun",)
    finally:
        player.close()


def test_effects_and_filters_survive_a_restart(tmp_path):
    from player.settings import Settings

    s = Settings()
    s.audio_effects, s.pitch, s.video_filters = ["stereo_widen", "bogus"], 2.5, ["postproc"]
    save_settings(s)
    loaded = load_settings()
    assert (loaded.audio_effects, loaded.pitch, loaded.video_filters) == (["stereo_widen"], 2.5, ["postproc"])


# ---- 3.18: sources ----


def test_disc_mrls():
    assert sources.disc_mrl("dvd", "d:") == "dvd:///D:/"
    assert sources.disc_mrl("bluray", "E:\\") == "bluray:///E:/"
    assert sources.disc_mrl("cdda", "D:", title=3) == "cdda:///D:/#3"
    assert sources.disc_mrl("dvd", "/dev/sr0") == "dvd:///dev/sr0"
    with pytest.raises(ValueError):
        sources.disc_mrl("vhs", "D:")
    assert sources.optical_drives("win32", drive_type=lambda root: 5 if root in ("E:\\", "F:\\") else 3) == ["E:", "F:"]
    assert sources.optical_drives("linux") == []


def test_share_urls_never_carry_the_password():
    url = sources.share_url("smb", "\\\\nas\\videos", "pelis\\Mi película.mkv", user="ana@casa")
    assert url == "smb://ana%40casa@nas/videos/pelis/Mi%20pel%C3%ADcula.mkv"
    assert sources.share_url("sftp", "box", "/x", port=2222) == "sftp://box:2222/x"
    assert sources.share_url("nfs", "nas", port=2049) == "nfs://nas/"
    options = sources.share_media_options("smb", "ana", "s3cr:t@", "CASA")
    assert options == [":smb-user=ana", ":smb-pwd=s3cr:t@", ":smb-domain=CASA"]
    assert sources.share_media_options("nfs", "ana", "x") == []
    assert sources.share_root("SMB://Ana@NAS/videos/a.mkv") == "smb://ana@nas"
    with pytest.raises(ValueError):
        sources.share_url("smb", "")


def test_share_credentials_reach_only_that_servers_media(qapp):
    backend = _backend()
    player = backend.VLCPlayer()
    try:
        player.set_share_credentials("smb://ana@nas/videos/", [":smb-pwd=x"])
        assert player._share_options("smb://ana@nas/videos/other/b.mkv") == [":smb-pwd=x"]
        assert player._share_options("smb://other/videos/b.mkv") == []
    finally:
        player.close()


def test_the_disc_and_share_dialogs_build_their_addresses(qapp):
    from player.sources_dialog import OpenDiscDialog, OpenShareDialog

    disc = OpenDiscDialog(drives=["E:"])
    disc.kind_combo.setCurrentIndex(1)
    assert disc.mrl() == "bluray:///E:/"
    share = OpenShareDialog()
    share.host_edit.setText("nas")
    share.path_edit.setText("music")
    share.user_edit.setText("ana")
    share.password_edit.setText("pw")
    assert share.url() == "smb://ana@nas/music"
    assert ":smb-pwd=pw" in share.media_options()


# ---- 3.19: convert and record ----


def test_sout_chains_and_output_names(tmp_path):
    mp3 = converter.PROFILES_BY_KEY["mp3"]
    chain = converter.transcode_sout(mp3, "C:\\Music\\it's.mp3")
    assert chain.startswith("#transcode{vcodec=none,acodec=mp3") and "dst='C:/Music/it''s.mp3'" in chain
    assert converter.record_sout("D:\\r.ts") == "#duplicate{dst=display,dst=std{access=file,mux=ts,dst='D:/r.ts'}}"
    source = tmp_path / "clip.mkv"
    source.write_bytes(b"x")
    (tmp_path / "clip.mp3").write_bytes(b"x")
    assert converter.default_output_path(str(source), mp3) == str(tmp_path / "clip (2).mp3")
    assert converter.recording_path("D:\\rec", "Live: news?", now=0).endswith(".ts")


def test_a_real_conversion_to_mp3(qapp, tmp_path):
    _backend()
    output = str(tmp_path / "out.mp3")
    job = converter.ConvertJob(ASSET, output, converter.PROFILES_BY_KEY["mp3"])
    results = []
    job.finished.connect(lambda ok, message: results.append((ok, message)))
    assert job.start()
    deadline = time.time() + 30
    while not results and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.05)
    assert results and results[0][0], results
    assert os.path.getsize(output) > 1000


@pytest.mark.parametrize("failure", ["startup", "runtime", "cancel"])
@pytest.mark.parametrize("destination_exists", [False, True])
def test_failed_conversion_cleans_only_its_output(qapp, tmp_path, failure, destination_exists):
    output = tmp_path / "out.mp3"
    if destination_exists:
        output.write_bytes(b"existing output")

    class FakeMedia:
        def add_option(self, option):
            pass

    class FakePlayer:
        state = converter.vlc.State.Playing

        def set_media(self, media):
            pass

        def play(self):
            if not output.exists():
                output.write_bytes(b"partial output")
            return -1 if failure == "startup" else 0

        def get_state(self):
            return self.state

        def stop(self):
            pass

        def release(self):
            pass

    class FakeInstance:
        def __init__(self):
            self.player = FakePlayer()

        def media_new(self, source):
            return FakeMedia()

        def media_new_path(self, source):
            return FakeMedia()

        def media_player_new(self):
            return self.player

        def release(self):
            pass

    instance = FakeInstance()
    job = converter.ConvertJob(
        str(tmp_path / "input.mp4"),
        str(output),
        converter.PROFILES_BY_KEY["mp3"],
        instance_factory=lambda: instance,
    )
    results = []
    job.finished.connect(lambda ok, message: results.append((ok, message)))

    started = job.start()
    assert started is (failure != "startup")
    if failure == "runtime":
        instance.player.state = converter.vlc.State.Error
        job._poll()
    elif failure == "cancel":
        job.cancel()

    assert results and not results[0][0]
    if destination_exists:
        assert output.read_bytes() == b"existing output"
    else:
        assert not output.exists()


def test_recording_adds_a_duplicate_sout_to_the_next_media(qapp):
    backend = _backend()
    player = backend.VLCPlayer()
    try:
        player._create_instance(visualizer=False)
        added = []

        class FakeMedia:
            def add_option(self, option):
                added.append(option)

        player.set_recording("C:\\rec\\x.ts")
        player._add_record_options(FakeMedia())
        assert added == [":sout=" + converter.record_sout("C:\\rec\\x.ts"), ":sout-keep"]
        player.set_recording(None)
        added.clear()
        player._add_record_options(FakeMedia())
        assert added == []
    finally:
        player.close()


# ---- the window ----


def test_the_menus_offer_the_new_sources_effects_and_filters(qapp):
    _backend()
    from player.main_window import MainWindow

    window = MainWindow()
    try:
        for action_id in ("open_disc", "open_share", "browse_network", "convert", "record"):
            assert action_id in window.action_registry
        assert window.action_registry["open_disc"].shortcut().toString() == "Ctrl+D"
        assert window.action_registry["record"].isCheckable()
        assert set(window.audio_effect_actions) == set(AUDIO_EFFECT_VALUES)
        assert set(window.video_filter_actions) == set(VIDEO_FILTER_VALUES)
        window.video_filter_actions["sharpen"].setChecked(True)
        assert window.player.get_video_filters() == ("sharpen",)
        assert window.current_settings().video_filters == ["sharpen"]
        window.toggle_recording(True)  # nothing playing: refused
        assert not window.act_record.isChecked() and window.player.recording_path() is None
    finally:
        window.close()
