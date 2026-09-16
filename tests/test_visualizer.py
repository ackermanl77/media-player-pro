"""Verifica que el filtro de visualizador de audio realmente produce una
salida de video para archivos de solo audio (si no, video_frame se queda en
negro). Se omite si no hay VLC instalado."""
import math
import struct
import time
import wave

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten las pruebas del visualizador.", allow_module_level=True)

from player.backend import VLCPlayer


def _make_test_wav(path: str, duration: float = 2.0, freq: float = 440.0, rate: int = 44100) -> None:
    n_samples = int(duration * rate)
    with wave.open(path, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        frames = bytearray()
        for i in range(n_samples):
            value = int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", value)
        f.writeframes(bytes(frames))


def _headless_player() -> VLCPlayer:
    player = VLCPlayer()
    # Salida "dummy": no necesitamos pantalla para comprobar que VLC generó
    # un video, solo que reporte sus metadatos (tamaño, has_vout).
    player.instance = vlc.Instance(["--vout=vdummy", "--aout=adummy", "--quiet"])
    player.media_player = player.instance.media_player_new()
    return player


def _wait_until(predicate, timeout_s: float = 6.0, interval_s: float = 0.2) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def test_visualizer_enabled_produces_a_video_output_for_audio(tmp_path):
    wav_path = str(tmp_path / "tone.wav")
    _make_test_wav(wav_path)

    player = _headless_player()
    player.load(wav_path, enable_visualizer=True)
    player.play()
    try:
        # Con el modulo de salida "vdummy" el tamaño reportado es (0, 0)
        # aunque la salida de video este activa, asi que se comprueba
        # has_vout() en lugar de has_video() (que ademas exige tamaño > 0).
        assert _wait_until(player.has_active_video_output), "el visualizador no genero salida de video"
    finally:
        player.stop()


def test_visualizer_disabled_stays_without_video_output(tmp_path):
    wav_path = str(tmp_path / "tone.wav")
    _make_test_wav(wav_path)

    player = _headless_player()
    player.load(wav_path, enable_visualizer=False)
    player.play()
    try:
        # Le damos tiempo de sobra: sin el filtro, un wav nunca deberia
        # generar video.
        assert not _wait_until(player.has_active_video_output, timeout_s=3.0)
    finally:
        player.stop()
