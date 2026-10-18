"""Reproducir en un Chromecast (3.14): descubrimiento de "renderers" de libVLC 3.

libVLC busca dispositivos en la red local (modulo microdns_renderer: Chromecast y
compatibles) y avisa con RendererDiscovererItemAdded/Deleted; un item se asigna a
un MediaPlayer con libvlc_media_player_set_renderer() ANTES de reproducir, y
entonces el video sale por ese dispositivo (libVLC transcodifica lo que el
dispositivo no admite).

python-vlc 3.0.21203 declara el evento sin campos, asi que el puntero al item --
el primer campo de la union del evento en libVLC -- se lee aqui con ctypes, y el
item se retiene (hold) mientras este en la lista. Los eventos llegan en un hilo
de libVLC: se reenvian a Qt con senales.
"""

import ctypes
import logging
from dataclasses import dataclass

import vlc
from PySide6.QtCore import QObject, Signal

from .vlc_internals import _libvlc_function, _text

log = logging.getLogger(__name__)

DISCOVERY_SERVICE = "microdns_renderer"


@dataclass(frozen=True)
class Renderer:
    key: int  # el puntero al libvlc_renderer_item_t (retenido)
    name: str
    kind: str  # "chromecast", ...
    can_video: bool


def _functions():
    return {
        "hold": _libvlc_function("libvlc_renderer_item_hold", ctypes.c_void_p, [ctypes.c_void_p]),
        "release": _libvlc_function("libvlc_renderer_item_release", None, [ctypes.c_void_p]),
        "name": _libvlc_function("libvlc_renderer_item_name", ctypes.c_char_p, [ctypes.c_void_p]),
        "type": _libvlc_function("libvlc_renderer_item_type", ctypes.c_char_p, [ctypes.c_void_p]),
        "flags": _libvlc_function("libvlc_renderer_item_flags", ctypes.c_int, [ctypes.c_void_p]),
    }


def event_item_pointer(event) -> int:
    """El libvlc_renderer_item_t* de un evento RendererDiscovererItemAdded/Deleted."""
    return ctypes.cast(ctypes.addressof(event.u), ctypes.POINTER(ctypes.c_void_p))[0] or 0


def set_player_renderer(media_player, renderer) -> bool:
    """Asigna (o quita, con None) el renderer de un MediaPlayer de python-vlc."""
    func = _libvlc_function("libvlc_media_player_set_renderer", ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p])
    handle = media_player._as_parameter_
    handle = handle.value if isinstance(handle, ctypes.c_void_p) else int(handle)
    return func(handle, renderer.key if renderer is not None else None) == 0


class RendererDiscovery(QObject):
    """Busca renderers mientras esta activa; `changed` cuando la lista cambia."""

    changed = Signal()
    _added = Signal(int)
    _deleted = Signal(int)

    def __init__(self, parent=None, instance_factory=None):
        super().__init__(parent)
        self._factory = instance_factory or (lambda: vlc.Instance(["--quiet"]))
        self._instance = None
        self._discoverer = None
        self._renderers: dict = {}  # puntero -> Renderer
        self._fn = None
        self._added.connect(self._on_added)
        self._deleted.connect(self._on_deleted)

    @property
    def running(self) -> bool:
        return self._discoverer is not None

    def renderers(self) -> list:
        return sorted(self._renderers.values(), key=lambda r: r.name.casefold())

    def start(self) -> bool:
        if self._discoverer is not None:
            return True
        try:
            self._fn = self._fn or _functions()
            self._instance = self._instance or self._factory()
            discoverer = self._instance.renderer_discoverer_new(DISCOVERY_SERVICE) if self._instance else None
            if discoverer is None:
                return False
            events = discoverer.event_manager()
            events.event_attach(vlc.EventType.RendererDiscovererItemAdded, self._libvlc_added)
            events.event_attach(vlc.EventType.RendererDiscovererItemDeleted, self._libvlc_deleted)
            if discoverer.start() != 0:
                discoverer.release()
                return False
        except Exception:  # noqa: BLE001 - sin el modulo de descubrimiento o sin red
            log.warning("No se pudo buscar dispositivos para reproducir", exc_info=True)
            return False
        self._discoverer = discoverer
        return True

    def stop(self) -> None:
        """Deja de buscar; los dispositivos ya encontrados siguen en la lista."""
        if self._discoverer is None:
            return
        try:
            self._discoverer.stop()
            self._discoverer.release()
        except Exception:  # noqa: BLE001
            pass
        self._discoverer = None

    def close(self) -> None:
        self.stop()
        if self._fn is not None:
            for key in list(self._renderers):
                self._fn["release"](key)
        self._renderers.clear()
        if self._instance is not None:
            self._instance.release()
            self._instance = None

    # -- eventos (hilo de libVLC -> hilo de Qt) ------------------------------------
    def _libvlc_added(self, event) -> None:
        pointer = event_item_pointer(event)
        if pointer:
            self._fn["hold"](pointer)  # retenido aqui, antes de que libVLC lo pueda liberar
            self._added.emit(pointer)

    def _libvlc_deleted(self, event) -> None:
        pointer = event_item_pointer(event)
        if pointer:
            self._deleted.emit(pointer)

    def _on_added(self, pointer: int) -> None:
        if pointer in self._renderers:
            self._fn["release"](pointer)  # ya estaba: una sola retencion por item
            return
        fn = self._fn
        flags = fn["flags"](pointer)
        self._renderers[pointer] = Renderer(pointer, _text(fn["name"](pointer)) or "Dispositivo",
                                            _text(fn["type"](pointer)), bool(flags & 0x0002))
        self.changed.emit()

    def _on_deleted(self, pointer: int) -> None:
        renderer = self._renderers.pop(pointer, None)
        if renderer is not None:
            self._fn["release"](pointer)
            self.changed.emit()
