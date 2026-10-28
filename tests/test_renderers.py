"""Reproducir en un Chromecast (3.14): descubrimiento, retencion de items y el menu.
No hay un Chromecast en la red de pruebas: los items se simulan; el descubrimiento y
set_renderer corren contra libVLC real."""
import ctypes
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

try:
    import vlc
except (ImportError, OSError):  # python-vlc without libvlc raises OSError on import
    pytest.skip("VLC (libvlc) no esta instalado", allow_module_level=True)

from player.renderers import (  # noqa: E402
    DISCOVERY_SERVICE,
    Renderer,
    RendererDiscovery,
    event_item_pointer,
    set_player_renderer,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_the_item_pointer_is_read_from_the_event_union():
    event = vlc.Event()
    ctypes.cast(ctypes.addressof(event.u), ctypes.POINTER(ctypes.c_void_p))[0] = 0xDEADBEEF
    assert event_item_pointer(event) == 0xDEADBEEF
    assert event_item_pointer(vlc.Event()) == 0


class _FakeLibvlc:
    def __init__(self):
        self.holds, self.releases = [], []
        self.items = {11: (b"Sala", b"chromecast", 0x3), 22: (b"Altavoz", b"chromecast", 0x1)}

    def table(self):
        return {
            "hold": self.holds.append, "release": self.releases.append,
            "name": lambda p: self.items[p][0], "type": lambda p: self.items[p][1], "flags": lambda p: self.items[p][2],
        }


def test_items_are_held_once_listed_and_released(qapp):
    fake = _FakeLibvlc()
    discovery = RendererDiscovery()
    discovery._fn = fake.table()
    changes = []
    discovery.changed.connect(lambda: changes.append(len(discovery.renderers())))
    for pointer in (11, 22, 11):  # 11 announced twice
        fake.holds.append(pointer)  # what _libvlc_added does before emitting
        discovery._on_added(pointer)
    assert [r.name for r in discovery.renderers()] == ["Altavoz", "Sala"]
    assert discovery.renderers()[1] == Renderer(11, "Sala", "chromecast", True)
    assert not discovery.renderers()[0].can_video  # audio-only device
    assert fake.releases == [11]  # the duplicate's extra hold was given back
    discovery._on_deleted(22)
    discovery._on_deleted(99)  # unknown: ignored
    assert [r.name for r in discovery.renderers()] == ["Sala"] and fake.releases == [11, 22]
    discovery.close()
    assert fake.releases == [11, 22, 11] and discovery.renderers() == []
    assert changes == [1, 2, 1]


def test_discovery_runs_against_real_libvlc_and_renderers_can_be_unset(qapp):
    # Chromecast discovery is libVLC's microdns_renderer module: Windows' VLC has it, some Linux
    # VLC packages (CI's Ubuntu runner) don't. Without it there is nothing real to test here.
    probe = vlc.Instance(["--quiet"])
    try:
        module = probe.renderer_discoverer_new(DISCOVERY_SERVICE)
        if module is None:
            pytest.skip(f"this libVLC has no {DISCOVERY_SERVICE} module")
        module.release()
    finally:
        probe.release()
    discovery = RendererDiscovery()
    try:
        assert discovery.start() and discovery.running and discovery.start()  # idempotent
        discovery.stop()
        assert not discovery.running
    finally:
        discovery.close()
    instance = vlc.Instance(["--quiet"])
    try:
        player = instance.media_player_new()
        assert set_player_renderer(player, None)  # back to this PC
        player.release()
    finally:
        instance.release()


def test_the_menu_casts_and_reloads_from_the_same_point(qapp, monkeypatch):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    window = MainWindow()
    try:
        window._populate_renderer_menu()
        texts = [a.text() for a in window.menu_renderers.actions() if not a.isSeparator()]
        assert texts[0] == "Esta PC" and window.menu_renderers.actions()[0].isChecked()
        tv = Renderer(1234, "Tele del salón", "chromecast", True)
        monkeypatch.setattr(window.renderer_discovery, "renderers", lambda: [tv])
        reloads = []
        monkeypatch.setattr(window.player, "reload_preserving_state", lambda *a, **k: reloads.append(1))
        window.current_index = 0
        window.cast_to(tv)
        assert window.player.get_renderer() is tv and reloads == [1]
        checked = [a.text() for a in window.menu_renderers.actions() if a.isChecked()]
        assert checked == ["Tele del salón"]
        window.cast_to(Renderer(1234, "Tele del salón", "chromecast", True))  # same device: no reload
        assert reloads == [1]
        window.cast_to(None)
        assert window.player.get_renderer() is None and reloads == [1, 1]
        window.current_index = -1
    finally:
        window.close()


def test_the_backend_assigns_the_renderer_with_every_file(qapp, monkeypatch, tmp_path):
    from player import renderers
    from player.backend import VLCPlayer

    assigned = []
    monkeypatch.setattr(renderers, "set_player_renderer", lambda mp, r: assigned.append(r) or True)
    player = VLCPlayer()
    try:
        player._create_instance(visualizer=False)
        sample = tmp_path / "silence.wav"
        import wave

        with wave.open(str(sample), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000), w.writeframes(b"\x00\x00" * 800)
        player._set_media(player._new_media(str(sample)))
        assert assigned == []  # no renderer: untouched
        tv = Renderer(1, "TV", "chromecast", True)
        player.set_renderer(tv)
        player._set_media(player._new_media(str(sample)))
        assert assigned == [tv]
    finally:
        player.close()
