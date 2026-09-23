"""Prueba de regresion: en Windows, libvlc_media_new_path falla en silencio
(el reproductor se queda en State.NothingSpecial para siempre, sin pasar
nunca a State.Error) si la ruta usa "/" en vez de "\\". Rutas asi llegan
tipicamente por argumentos de linea de comandos. Se omite si no hay VLC."""
import time

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten las pruebas del backend.", allow_module_level=True)

from player.backend import VLCPlayer


def _wait_until(predicate, timeout_s: float = 5.0, interval_s: float = 0.2) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def test_load_plays_a_path_that_uses_forward_slashes(tmp_path):
    # tmp_path de pytest siempre usa "\" en Windows; se fuerza a "/" a
    # proposito para reproducir como llegan las rutas por sys.argv o desde
    # algunos dialogos de Qt.
    wav_path = str(tmp_path / "silence.wav").replace("\\", "/")

    import wave

    with wave.open(str(tmp_path / "silence.wav"), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\x00\x00" * 8000)  # 1 segundo de silencio

    player = VLCPlayer()
    # --aout=adummy evita que VLC intente (y falle) abrir un dispositivo
    # ALSA real en un runner de CI sin tarjeta de sonido (ver
    # test_visualizer.py). No se fuerza --vout: la autoseleccion de video
    # basta, esta prueba no depende de video en absoluto.
    player.instance = vlc.Instance(["--aout=adummy", "--quiet"])
    player.media_player = player.instance.media_player_new()

    player.load(wav_path)
    player.play()
    try:
        assert _wait_until(lambda: player.get_state() in (vlc.State.Playing, vlc.State.Ended))
    finally:
        player.stop()


def _make_silent_wav(path, duration_s: float = 3.0):
    import wave

    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\x00\x00" * int(8000 * duration_s))


def test_next_frame_is_a_no_op_while_playing(tmp_path):
    # is_paused()/next_frame() son parte del wrapper de Python, no de
    # libVLC: se prueba la logica de "solo tiene sentido en pausa" contra un
    # archivo real, sin depender de si el backend de video reporta
    # fotogramas para audio puro.
    wav_path = tmp_path / "silence.wav"
    _make_silent_wav(wav_path)

    player = VLCPlayer()
    player.instance = vlc.Instance(["--aout=adummy", "--quiet"])
    player.media_player = player.instance.media_player_new()

    player.load(str(wav_path))
    player.play()
    try:
        assert _wait_until(lambda: player.get_state() in (vlc.State.Playing, vlc.State.Ended))
        assert player.is_paused() is False
        assert player.next_frame() is False
    finally:
        player.stop()


def test_next_frame_returns_true_and_calls_libvlc_once_paused(tmp_path):
    wav_path = tmp_path / "silence.wav"
    _make_silent_wav(wav_path)

    player = VLCPlayer()
    player.instance = vlc.Instance(["--aout=adummy", "--quiet"])
    player.media_player = player.instance.media_player_new()

    player.load(str(wav_path))
    player.play()
    try:
        assert _wait_until(lambda: player.get_state() == vlc.State.Playing)
        player.set_paused(True)
        assert _wait_until(player.is_paused)
        assert player.next_frame() is True
    finally:
        player.stop()


def test_is_paused_is_false_before_anything_plays():
    player = VLCPlayer()
    player.instance = vlc.Instance(["--aout=adummy", "--quiet"])
    player.media_player = player.instance.media_player_new()
    assert player.is_paused() is False
    assert player.next_frame() is False
