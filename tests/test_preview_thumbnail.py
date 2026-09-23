"""Prueba el reproductor secundario dedicado a la miniatura de vista previa
de la barra de progreso (VLCPlayer.load_preview_media/seek_preview/
take_preview_snapshot). Sigue el mismo enfoque que test_visualizer.py: usa
el filtro de visualizador (--audio-visual=visual) sobre un WAV para obtener
una salida de video real y verificable sin necesitar un archivo de video de
verdad ni un widget de Qt. Se omite si no hay VLC instalado."""
import math
import struct
import time
import wave

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten las pruebas de vista previa.", allow_module_level=True)

from player import backend as backend_module
from player.backend import VLCPlayer


def _make_test_wav(path: str, duration: float = 8.0, freq: float = 440.0, rate: int = 44100) -> None:
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


def _headless_player(monkeypatch) -> VLCPlayer:
    # Mismo motivo que test_visualizer.py: evita que VLC intente abrir un
    # dispositivo de audio real en un runner sin tarjeta de sonido.
    monkeypatch.setattr(backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy"])
    return VLCPlayer()


def _wait_until(predicate, timeout_s: float = 8.0, interval_s: float = 0.2) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def test_preview_current_path_is_none_before_loading():
    player = VLCPlayer()
    assert player.preview_current_path() is None


def test_seek_preview_and_take_preview_snapshot_are_no_ops_before_loading(tmp_path):
    player = VLCPlayer()
    snapshot_path = str(tmp_path / "preview.png")
    player.seek_preview(0.5)  # no debe lanzar aunque no haya preview player aun
    assert player.take_preview_snapshot(snapshot_path) is False


def test_preview_player_reuses_visualizer_video_output_and_snapshots(tmp_path, monkeypatch):
    wav_path = str(tmp_path / "tone.wav")
    _make_test_wav(wav_path)

    player = _headless_player(monkeypatch)
    # Cargar el archivo principal con el visualizador activo recrea la
    # Instance con --audio-visual: el reproductor de vista previa (misma
    # Instance) la hereda, igual que cualquier otro media_player nuevo.
    player.load(wav_path, enable_visualizer=True)
    player.play()
    try:
        assert _wait_until(player.has_active_video_output, timeout_s=12.0), "el visualizador no genero salida de video"

        player.load_preview_media(wav_path)
        assert player.preview_current_path() == wav_path
        player.seek_preview(0.5)

        import os

        snapshot_path = str(tmp_path / "preview.png")

        def _snapshot_written():
            # video_take_snapshot() puede devolver 0 (aceptado) antes de que
            # el hilo de video termine de escribir el archivo en disco --
            # hace falta reintentar tanto la captura como la comprobacion
            # del archivo hasta que el PNG exista de verdad.
            player.take_preview_snapshot(snapshot_path, width=160, height=90)
            return os.path.exists(snapshot_path) and os.path.getsize(snapshot_path) > 0

        assert _wait_until(_snapshot_written, timeout_s=10.0), "no se pudo capturar la miniatura de vista previa"
    finally:
        player.release_preview_player()
        player.stop()


def test_release_preview_player_clears_state(tmp_path, monkeypatch):
    wav_path = str(tmp_path / "tone.wav")
    _make_test_wav(wav_path, duration=2.0)

    player = _headless_player(monkeypatch)
    player.load(wav_path)
    player.play()
    try:
        player.load_preview_media(wav_path)
        assert player.preview_current_path() == wav_path
        player.release_preview_player()
        assert player.preview_current_path() is None
        # Tras liberar, las llamadas subsiguientes no deben lanzar.
        player.seek_preview(0.2)
    finally:
        player.stop()


def test_recreating_the_instance_resets_preview_player(tmp_path, monkeypatch):
    # Cambiar el visualizador recrea la Instance (ver backend._create_instance);
    # el reproductor de vista previa vivia en la Instance vieja y debe
    # descartarse, no quedar apuntando a una Instance liberada.
    wav_path = str(tmp_path / "tone.wav")
    _make_test_wav(wav_path, duration=2.0)

    player = _headless_player(monkeypatch)
    player.load(wav_path, enable_visualizer=False)
    player.play()
    try:
        player.load_preview_media(wav_path)
        assert player.preview_current_path() == wav_path

        # Forzar la recreacion de instancia igual que un cambio de escala de
        # subtitulos o de visualizador lo haria.
        player._create_instance(visualizer=False)
        assert player.preview_current_path() is None
    finally:
        player.stop()
