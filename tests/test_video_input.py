"""La ventana de video de libVLC no debe quedarse con el mouse ni el teclado.

Regresion: libVLC crea dentro de nuestro widget una ventana hija HABILITADA
("VLC (Direct3D11 output)") que lo cubre entero; el doble clic, el
movimiento del mouse (controles flotantes en pantalla completa) y el foco de
teclado iban a esa ventana y nunca llegaban a Qt. Con
video_set_mouse_input/key_input(False) queda deshabilitada y Windows le pasa
la entrada al padre.

La prueba de Windows usa una ventana Win32 propia, creada OCULTA (nunca se
muestra, no se simula ninguna entrada) y libVLC real con el visualizador de
espectro sobre un WAV, para tener una salida de video de verdad sin un
archivo de video. Se omite si no hay VLC."""
import math
import struct
import sys
import time
import wave

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten estas pruebas.", allow_module_level=True)

from player import backend as backend_module
from player.backend import VLCPlayer


def _tone_wav(path, seconds=8.0, rate=22050):
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(rate * seconds))
    )
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(frames)
    return str(path)


def test_every_media_player_is_created_with_vlc_input_disabled(monkeypatch):
    """Multiplataforma (corre tambien en el CI de Linux): el reproductor
    principal -- tambien al recrear el Instance -- y el de vista previa."""
    calls = []
    for name in ("video_set_mouse_input", "video_set_key_input"):
        original = getattr(vlc.MediaPlayer, name)
        monkeypatch.setattr(
            vlc.MediaPlayer, name,
            lambda self, on, _n=name, _o=original: (calls.append((id(self), _n, on)), _o(self, on))[1],
        )
    monkeypatch.setattr(backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy"])
    player = VLCPlayer()
    try:
        main_id = id(player.media_player)
        assert (main_id, "video_set_mouse_input", False) in calls
        assert (main_id, "video_set_key_input", False) in calls

        player._create_instance(visualizer=True)  # recreacion (audio <-> video, subtitulos)
        new_id = id(player.media_player)
        assert (new_id, "video_set_mouse_input", False) in calls
        assert (new_id, "video_set_key_input", False) in calls

        preview = player._ensure_preview_player()
        assert (id(preview), "video_set_mouse_input", False) in calls
        assert (id(preview), "video_set_key_input", False) in calls
    finally:
        player._release_instance()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="ventanas hijas Win32")
def test_libvlc_video_child_window_is_disabled_on_windows(monkeypatch, tmp_path):
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = [
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
    ]
    user32.GetParent.restype = wt.HWND
    user32.GetParent.argtypes = [wt.HWND]
    user32.IsWindowEnabled.argtypes = [wt.HWND]
    user32.DestroyWindow.argtypes = [wt.HWND]
    enum_proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumChildWindows.argtypes = [wt.HWND, enum_proc, wt.LPARAM]

    ws_overlappedwindow, ws_clipchildren = 0x00CF0000, 0x02000000
    # Sin WS_VISIBLE: la ventana existe pero nunca aparece en pantalla.
    host = user32.CreateWindowExW(0, "STATIC", "prueba", ws_overlappedwindow | ws_clipchildren,
                                  0, 0, 640, 360, None, None, None, None)
    assert host

    def direct_children():
        found = []

        def callback(hwnd, _lparam):
            if user32.GetParent(hwnd) == host:
                found.append((hwnd, bool(user32.IsWindowEnabled(hwnd))))
            return True

        user32.EnumChildWindows(host, enum_proc(callback), 0)
        return found

    class _Host:  # lo unico que VLCPlayer usa de un widget: winId()
        def winId(self):
            return host

    monkeypatch.setattr(backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy"])
    player = VLCPlayer()
    try:
        player.attach_video_output(_Host())
        player.load(_tone_wav(tmp_path / "tono.wav"), enable_visualizer=True)  # recrea el Instance
        player.play()
        deadline = time.time() + 10
        children = []
        while time.time() < deadline and not children:
            time.sleep(0.2)
            children = direct_children() if player.has_active_video_output() else []
        if not children:
            pytest.skip("libVLC no creo una ventana de video en este equipo (sin salida de video)")
        assert all(not enabled for _hwnd, enabled in children), children
    finally:
        player.stop()
        player._release_instance()
        user32.DestroyWindow(host)
