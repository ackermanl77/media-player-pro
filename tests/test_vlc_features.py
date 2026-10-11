"""Roadmap 4.10: dispositivo de salida, aspecto/recorte, desentrelazado,
ajustes de video, normalizar volumen e informacion del medio. Las partes de
libVLC se prueban contra libVLC real (salida de audio capturada con
audio_set_callbacks para medir el nivel); se omiten si no hay VLC."""
import array
import ctypes
import math
import os
import shutil
import subprocess
import sys
import time
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from player.media_info_dialog import (
    describe_track,
    format_duration,
    format_size,
    media_info_sections,
    media_info_text,
)
from player.settings import VideoAdjustSettings, settings_from_dict
from player.video_adjust_dialog import from_slider, to_slider
from player.video_options import ASPECT_RATIOS, CROP_RATIOS, choice_label, next_choice


# -- puro ---------------------------------------------------------------------
def test_a_and_c_cycle_through_the_choices_and_wrap():
    assert next_choice(ASPECT_RATIOS, "") == "16:9"
    assert next_choice(ASPECT_RATIOS, ASPECT_RATIOS[-1][1]) == ""
    assert next_choice(CROP_RATIOS, "no-such") == ""
    assert choice_label(CROP_RATIOS, "235:100") == "2,35:1"


def test_adjust_sliders_put_every_neutral_value_on_a_step():
    for name, value in (("brightness", 1.0), ("contrast", 1.0), ("saturation", 1.0), ("hue", 0.0), ("gamma", 1.0)):
        assert from_slider(name, to_slider(name, value)) == value
    assert from_slider("gamma", 0) == 0.01 and from_slider("gamma", 300) == 10.0
    assert from_slider("hue", 0) == -180.0


def test_new_settings_are_validated_and_round_trip():
    s = settings_from_dict({
        "deinterlace": "yadif2x", "audio_device": "{0.0.0}.{abc}", "normalize_volume": True,
        "video_adjust": {"enabled": True, "brightness": 1.4, "gamma": 99, "hue": "x"},
    })
    assert s.deinterlace == "yadif2x" and s.audio_device == "{0.0.0}.{abc}" and s.normalize_volume
    assert s.video_adjust == VideoAdjustSettings(enabled=True, brightness=1.4, gamma=10.0)
    bad = settings_from_dict({"deinterlace": "warp", "video_adjust": [], "audio_device": 5, "normalize_volume": 1})
    assert bad.deinterlace == "auto" and bad.video_adjust == VideoAdjustSettings()
    assert bad.audio_device == "" and bad.normalize_volume is False


def test_media_info_sections_describe_every_track(tmp_path):
    path = tmp_path / "clip.mkv"
    path.write_bytes(b"x" * 2048)
    details = {
        "path": str(path), "duration_ms": 3_725_000, "meta": {"title": "Clip", "artist": "Yo"},
        "tracks": [
            {"type": "video", "codec": "H264 - MPEG-4 AVC (part 10)", "width": 1920, "height": 1080,
             "fps": 23.976, "bitrate": 0, "language": "", "description": ""},
            {"type": "audio", "codec": "MPEG AAC Audio", "channels": 6, "rate": 48000, "bitrate": 384000,
             "language": "spa", "description": "Castellano"},
            {"type": "text", "codec": "Text subtitles with various tags", "encoding": "UTF-8", "bitrate": 0,
             "language": "eng", "description": ""},
        ],
    }
    sections = dict(media_info_sections(details))
    general = dict(sections["General"])
    assert general["Archivo"] == "clip.mkv" and general["Tamaño"] == "2,0 KB" and general["Duración"] == "1:02:05"
    assert dict(sections["Etiquetas"]) == {"Título": "Clip", "Artista": "Yo"}
    assert dict(sections["Video 1"])["Resolución"] == "1920 × 1080"
    assert dict(sections["Video 1"])["Cuadros por segundo"] == "23,976"
    audio = dict(sections["Audio 1"])
    assert audio["Canales"] == "6 (5.1)" and audio["Frecuencia de muestreo"] == "48000 Hz"
    assert audio["Tasa de bits"] == "384 kb/s" and audio["Idioma"] == "spa"
    assert dict(sections["Subtítulos 1"])["Codificación"] == "UTF-8"
    assert "Audio 1\n  Códec: MPEG AAC Audio" in media_info_text(media_info_sections(details))
    assert format_duration(59_999) == "0:59" and format_size(5 * 1024 ** 3) == "5,0 GB"
    assert describe_track({"type": "other", "fourcc": "abcd"}) == [("Códec", "abcd")]


# -- libVLC real --------------------------------------------------------------
try:
    import vlc
except OSError:
    vlc = None
needs_vlc = pytest.mark.skipif(vlc is None, reason="VLC (libvlc) no esta instalado")


def _sine_wav(path, seconds=8.0, amplitude=0.9, rate=44100, channels=2):
    frames = array.array("h")
    for i in range(int(rate * seconds)):
        sample = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * i / rate))
        frames.extend([sample] * channels)
    with wave.open(str(path), "w") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(frames.tobytes())
    return str(path)


@pytest.fixture
def player(monkeypatch):
    from player import backend as backend_module

    monkeypatch.setattr(backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--vout=dummy"])
    p = backend_module.VLCPlayer()
    yield p
    p.close()


class _LevelMeter:
    """Captura la salida de audio del reproductor (en vez de mandarla a la
    tarjeta) y guarda el pico de cada bloque."""

    def __init__(self, media_player):
        self.peaks = []

        @vlc.CallbackDecorators.AudioPlayCb
        def play(_opaque, samples, count, _pts):
            data = array.array("h", ctypes.string_at(samples, count * 4))
            self.peaks.append(max((abs(x) for x in data), default=0))

        self._callback = play  # que no lo recolecte el GC
        media_player.audio_set_callbacks(play, None, None, None, None, None)
        media_player.audio_set_format("S16N", 44100, 2)

    def level_after(self, seconds):
        start = len(self.peaks)
        time.sleep(seconds)
        recent = self.peaks[start:][-8:]
        return max(recent) if recent else 0


def _wait_playing(p, timeout=5.0):
    from player.backend import PlaybackState

    deadline = time.time() + timeout
    while time.time() < deadline and p.playback_state() != PlaybackState.PLAYING:
        time.sleep(0.05)
    assert p.playback_state() == PlaybackState.PLAYING


@needs_vlc
def test_normalizer_lowers_loud_audio_live_and_survives_the_equalizer(player, tmp_path):
    if not player.volume_normalization_supported():
        pytest.skip("esta version de libVLC no permite fijar filtros de audio")
    # Un nivel maximo muy bajo, para que el efecto sea inequivoco en una senal de prueba.
    player._release_main()
    player.instance = vlc.Instance(["--quiet", "--vout=dummy", "--norm-max-level=0.01"])
    player.media_player = player.instance.media_player_new()
    meter = _LevelMeter(player.media_player)
    player.load(_sine_wav(tmp_path / "loud.wav"))
    player.play()
    _wait_playing(player)
    plain = meter.level_after(0.8)
    assert plain > 1000
    assert player.set_volume_normalization(True)
    normalized = meter.level_after(0.8)
    assert normalized < plain / 3, (plain, normalized)
    # Cambiar el ecualizador (que pisa la cadena de filtros) no lo apaga.
    player.set_equalizer_values(0.0, [0.0] * 10)
    with_eq = meter.level_after(0.8)
    player.set_volume_normalization(False)
    eq_only = meter.level_after(0.8)
    assert with_eq < eq_only / 3, (with_eq, eq_only)
    assert player.is_volume_normalized() is False


@needs_vlc
def test_media_details_read_the_real_tracks_and_tags(player, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("hace falta ffmpeg para generar un video de prueba")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac",
         "-metadata", "title=Prueba", str(clip)],
        check=True,
    )
    player._release_main()
    player.instance = vlc.Instance(["--quiet", "--vout=dummy", "--aout=adummy"])
    player.media_player = player.instance.media_player_new()
    player.load(str(clip))
    details = player.media_details()
    assert details["meta"]["title"] == "Prueba" and abs(details["duration_ms"] - 2000) < 200
    video = next(t for t in details["tracks"] if t["type"] == "video")
    audio = next(t for t in details["tracks"] if t["type"] == "audio")
    assert (video["width"], video["height"], video["fps"]) == (320, 240, 25.0)
    assert video["codec"].startswith("H264")
    assert audio["channels"] == 1 and audio["rate"] == 44100 and audio["codec"] == "MPEG AAC Audio"


@needs_vlc
def test_video_state_and_device_survive_recreating_the_player(player):
    player.set_aspect_ratio("16:9")
    player.set_crop("235:100")
    assert player.set_deinterlace("yadif") is False
    player.set_video_adjust(VideoAdjustSettings(enabled=True, brightness=1.5))
    player._create_instance(visualizer=False)
    mp = player.media_player
    assert mp.video_get_aspect_ratio() == "16:9" and mp.video_get_crop_geometry() == "235:100"
    assert mp.video_get_adjust_float(vlc.VideoAdjustOption.Brightness) == pytest.approx(1.5)
    # Volver al automatico necesita un reproductor nuevo; el nuevo ya no fija ningun modo.
    assert player.set_deinterlace("auto") is True
    player._create_instance(visualizer=False)
    assert player.set_deinterlace("auto") is False
    player.set_aspect_ratio("")
    assert player.media_player.video_get_aspect_ratio() is None
    devices = player.audio_output_devices()
    assert all(isinstance(d, str) and isinstance(n, str) for d, n in devices)


@needs_vlc
def test_window_menus_shortcuts_and_saved_settings(qapp_window):
    window = qapp_window
    assert [a.data() for a in window.menu_aspect.actions()] == [v for _l, v in ASPECT_RATIOS]
    window._cycle_choice(ASPECT_RATIOS, window._set_aspect_ratio, window.player.get_aspect_ratio())
    assert window.player.get_aspect_ratio() == "16:9"
    assert next(a for a in window.menu_aspect.actions() if a.isChecked()).data() == "16:9"
    window._set_crop("4:3")
    window._set_deinterlace("bob")
    assert next(a for a in window.menu_deinterlace.actions() if a.isChecked()).data() == "bob"
    window.open_video_adjust()
    window.video_adjust_dialog.sliders["contrast"].setValue(225)
    assert window.player.get_video_adjust().enabled and window.player.get_video_adjust().contrast == 1.5
    window._populate_audio_device_menu()
    assert window.menu_audio_device.actions()
    assert window.show_media_info() is None  # nada abierto
    settings = window.current_settings()
    assert settings.deinterlace == "bob" and settings.video_adjust.contrast == 1.5
    texts = {text for text, _keys in window.shortcut_rows()}
    assert {"Siguiente relación de aspecto", "Siguiente recorte", "Ajustes de video...",
            "Información del medio..."} <= texts


@pytest.fixture
def qapp_window():
    from PySide6.QtWidgets import QApplication

    from player.main_window import MainWindow

    _app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    yield window
    window.close()


@needs_vlc
def test_self_test_reports_every_check_and_leaves_the_user_folders_alone(tmp_path, monkeypatch):
    from player import self_test

    home_before = os.environ.get("USERPROFILE")
    out = tmp_path / "self-test.txt"
    assert self_test.wants_self_test(["--self-test", f"--self-test-output={out}"])
    assert self_test.output_path([f"--self-test-output={out}"]) == str(out)
    assert self_test.main(["--self-test", f"--self-test-output={out}"]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert [line.split()[1].rstrip(":") for line in lines[:-1]] == [
        "version", "qt", "traduccion", "libvlc", "reproduccion", "ventana"]
    assert lines[-1] == "RESULTADO: todo bien"
    assert os.environ.get("USERPROFILE") == home_before
    # Una comprobacion que falla da codigo 1 y "FALLA".
    monkeypatch.setattr(self_test, "run_checks", lambda _workdir: [("libvlc", False, "OSError: no")])
    assert self_test.main([f"--self-test-output={out}"]) == 1
    assert out.read_text(encoding="utf-8").startswith("FALLA libvlc: OSError: no")
