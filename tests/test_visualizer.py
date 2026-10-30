"""Verifica que el filtro de visualizador de audio realmente produce una
salida de video para archivos de solo audio (si no, video_frame se queda en
negro). Se omite si no hay VLC instalado."""
import math
import os
import struct
import threading
import wave

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten las pruebas del visualizador.", allow_module_level=True)

from player import backend as backend_module
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


def _headless_player(monkeypatch) -> VLCPlayer:
    # --aout=adummy: en un runner de CI sin tarjeta de sonido real, VLC
    # intenta abrir el dispositivo ALSA "default", falla, y el decoder de
    # audio muere sin darle nunca la oportunidad de correr al filtro
    # "visual" (que cuelga de esa misma cadena de audio) -- el video_frame
    # se queda en negro aunque el filtro funcione perfectamente bien. No se
    # fuerza --vout: la seleccion automatica de video ya tiene un display X
    # real a donde salir gracias a xvfb en CI.
    #
    # Se parchea BASE_VLC_ARGS (en vez de sobreescribir player.instance a
    # mano) porque VLCPlayer.load() puede recrear su Instance internamente
    # (ver backend._create_instance) cuando cambia si hace falta o no el
    # visualizador -- sobreescribir la instancia directamente se pierde en
    # cuanto eso pasa.
    monkeypatch.setattr(backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy"])
    return VLCPlayer()


def _watch_video_output(player: VLCPlayer):
    ready = threading.Event()
    event_manager = player.media_player.event_manager()

    def on_video_output_changed(event):
        if int(event.u.new_count) > 0:
            ready.set()

    if event_manager.event_attach(vlc.EventType.MediaPlayerVout, on_video_output_changed) != 0:
        raise RuntimeError("no se pudo observar la salida de video de libVLC")
    return ready, event_manager, on_video_output_changed


@pytest.mark.xfail(
    os.environ.get("CI") == "true", strict=False,
    reason="Known intermittent failure (docs/PROJECT_STATUS.md, Known Issues): the visualizer's video "
           "output sometimes appears too late. Keep this until repeated CI runs confirm the event-based "
           "readiness check is stable.",
)
def test_visualizer_enabled_produces_a_video_output_for_audio(tmp_path, monkeypatch):
    wav_path = str(tmp_path / "tone.wav")
    # Duracion generosa: bajo Xvfb con render por software, inicializar el
    # contexto GL/EGL para el video generado por el filtro puede tardar
    # ~2 segundos por si solo (una vez, al primer video output). Un wav
    # corto puede terminar y desmontar el pipeline antes de que el vout
    # llegue a existir, dando un falso negativo.
    _make_test_wav(wav_path, duration=8.0)
    player = _headless_player(monkeypatch)
    player.load(wav_path, enable_visualizer=True)
    ready, event_manager, _callback = _watch_video_output(player)
    try:
        player.play()
        assert ready.wait(12.0) and player.has_active_video_output(), "el visualizador no genero salida de video"
    finally:
        event_manager.event_detach(vlc.EventType.MediaPlayerVout)
        player.stop()


def test_visualizer_disabled_stays_without_video_output(tmp_path, monkeypatch):
    wav_path = str(tmp_path / "tone.wav")
    _make_test_wav(wav_path)

    player = _headless_player(monkeypatch)
    player.load(wav_path, enable_visualizer=False)
    ready, event_manager, _callback = _watch_video_output(player)
    try:
        player.play()
        assert not ready.wait(3.0) and not player.has_active_video_output()
    finally:
        event_manager.event_detach(vlc.EventType.MediaPlayerVout)
        player.stop()
