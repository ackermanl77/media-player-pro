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
    # No se fuerza --vout/--aout: "vdummy"/"adummy" no se resuelven igual en
    # todas las builds de VLC (ver test_visualizer.py). Esta prueba no
    # depende de video en absoluto, asi que la autoseleccion de VLC basta.
    player.instance = vlc.Instance(["--quiet"])
    player.media_player = player.instance.media_player_new()

    player.load(wav_path)
    player.play()
    try:
        assert _wait_until(lambda: player.get_state() in (vlc.State.Playing, vlc.State.Ended))
    finally:
        player.stop()
