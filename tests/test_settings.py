"""player/settings.py: modulo puro, sin VLC ni Qt. Path.home() ya apunta a
una carpeta temporal (tests/conftest.py)."""
import json
from dataclasses import asdict

from player import settings as st


def test_defaults_when_nothing_was_saved():
    s = st.load_settings()
    assert s == st.Settings()
    assert s.volume == 80 and s.rate == 1.0 and s.visualizer is True and s.restore_session is True
    assert st.load_session() == st.Session()


def test_settings_round_trip():
    s = st.Settings(
        volume=35, muted=True, rate=1.5, repeat_mode="one", shuffle=True, visualizer=False,
        subtitle_scale=150, video_scale=2.0, always_on_top=True, restore_session=False,
        equalizer=st.EqualizerSettings(enabled=True, preset=13, preamp=5.5, bands=[float(i) for i in range(10)]),
        geometry="AAEC", window_state="AwQF", last_open_dir="C:\\Videos",
    )
    assert st.save_settings(s)
    assert st.load_settings() == s


def test_invalid_fields_fall_back_to_defaults_one_by_one():
    st.settings_file().parent.mkdir(parents=True, exist_ok=True)
    st.settings_file().write_text(json.dumps({
        "volume": 999,              # se recorta al maximo
        "muted": "si",              # tipo invalido
        "rate": "rapido",           # tipo invalido
        "repeat_mode": "siempre",
        "shuffle": 1,               # int, no bool
        "subtitle_scale": 101,
        "video_scale": True,        # bool no cuenta como numero
        "equalizer": {"enabled": True, "preset": 2.5, "preamp": 99, "bands": [0, 1]},
        "geometry": 12,
        "last_open_dir": "D:\\Musica",
        "on_finish_action": "shutdown",  # nunca se lee
    }), encoding="utf-8")
    s = st.load_settings()
    d = st.Settings()
    assert s.volume == st.MAX_VOLUME
    assert (s.muted, s.rate, s.repeat_mode, s.shuffle) == (d.muted, d.rate, d.repeat_mode, d.shuffle)
    assert (s.subtitle_scale, s.video_scale, s.geometry) == (d.subtitle_scale, d.video_scale, d.geometry)
    assert s.equalizer.enabled is True
    assert s.equalizer.preset == -1
    assert s.equalizer.preamp == st.EQ_MAX_DB
    assert s.equalizer.bands == [0.0] * st.EQ_BAND_COUNT  # largo equivocado -> default
    assert s.last_open_dir == "D:\\Musica"
    assert not hasattr(s, "on_finish_action")


def test_power_actions_are_never_persisted():
    assert "on_finish_action" not in asdict(st.Settings())


def test_corrupt_file_uses_defaults():
    st.settings_file().parent.mkdir(parents=True, exist_ok=True)
    st.settings_file().write_text("{no es json", encoding="utf-8")
    assert st.load_settings() == st.Settings()


def test_session_round_trip_and_validation():
    assert st.save_session(st.Session(entries=["C:\\a.mp3", "http://x/y"], current_index=1))
    assert st.load_session() == st.Session(entries=["C:\\a.mp3", "http://x/y"], current_index=1)

    st.session_file().write_text(json.dumps({"entries": ["a", 3, "", None, "b"], "current_index": 5}),
                                 encoding="utf-8")
    session = st.load_session()
    assert session.entries == ["a", "b"]
    assert session.current_index == -1  # fuera de rango

    assert st.clear_session()
    assert st.load_session() == st.Session()


def test_session_entries_are_capped(monkeypatch):
    monkeypatch.setattr(st, "MAX_SESSION_ENTRIES", 3)
    session = st.session_from_dict({"entries": ["a", "b", "c", "d"], "current_index": 3})
    assert session.entries == ["a", "b", "c"]
    assert session.current_index == -1


def test_new_preferences_round_trip_and_validate():
    s = st.Settings(rate=2.3, theme="dark", gpu_upscale=True, gpu_hdr=True, hw_decoding="d3d11va",
                    network_caching_ms=3000, rtsp_tcp=True, allow_multiple_windows=True, show_remaining_time=True)
    assert st.save_settings(s)
    loaded = st.load_settings()
    assert asdict(loaded) == asdict(s)
    bad = st.settings_from_dict({"rate": 9, "theme": "rosa", "hw_decoding": "cuda", "network_caching_ms": -5,
                                 "gpu_hdr": "si"})
    assert bad.rate == st.MAX_RATE and bad.theme == "system" and bad.hw_decoding == "any"
    assert bad.network_caching_ms == st.MIN_NETWORK_CACHING_MS and bad.gpu_hdr is False


def test_clamp_rate_rounds_and_bounds():
    assert st.clamp_rate(1.0 + 0.1 + 0.1) == 1.2
    assert st.clamp_rate(0.01) == st.MIN_RATE and st.clamp_rate(10) == st.MAX_RATE
    assert st.clamp_rate(True) == 1.0 and st.clamp_rate(float("nan")) == 1.0
