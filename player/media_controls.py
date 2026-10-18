"""Controles multimedia del sistema de Windows (SMTC, 4.12).

Con esto las teclas multimedia del teclado (y los auriculares Bluetooth)
manejan el reproductor aunque su ventana no tenga el foco, y Windows muestra
el titulo y los botones en el panel multimedia de la barra de tareas
(Win+A / control de volumen) y en la pantalla de bloqueo.

Una app de escritorio (Win32) no puede pedir los SMTC de "su vista"; se usan
los de un Windows.Media.Playback.MediaPlayer propio que no reproduce nada (su
CommandManager desactivado), via pywinrt (requirements.txt, solo Windows). Sin
esos paquetes, o fuera de Windows, available es False y nada cambia.

Los botones llegan en un hilo de WinRT: se reenvian a Qt con la senal
`pressed(str)` ("play", "pause", "toggle", "stop", "next", "previous"), que
Qt entrega en el hilo de la ventana."""

import logging

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

PLAYING, PAUSED, STOPPED, CLOSED = "playing", "paused", "stopped", "closed"


class SystemMediaControls(QObject):
    pressed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = None
        self._controls = None
        self._token = None
        self._buttons = {}
        self._statuses = {}
        try:
            from winrt.windows.media import (
                MediaPlaybackStatus,
                MediaPlaybackType,
                SystemMediaTransportControlsButton as Button,
            )
            from winrt.windows.media.playback import MediaPlayer

            player = MediaPlayer()
            player.command_manager.is_enabled = False  # it plays nothing; we drive its SMTC
            controls = player.system_media_transport_controls
            controls.is_enabled = True
            for flag in ("is_play_enabled", "is_pause_enabled", "is_stop_enabled", "is_next_enabled", "is_previous_enabled"):
                setattr(controls, flag, True)
            self._token = controls.add_button_pressed(self._on_button)
        except Exception:  # noqa: BLE001 - sin pywinrt, fuera de Windows o sin el servicio
            log.info("Controles multimedia del sistema no disponibles", exc_info=True)
            return
        self._player, self._controls = player, controls
        self._types = MediaPlaybackType
        self._buttons = {
            Button.PLAY: "play", Button.PAUSE: "pause", Button.STOP: "stop",
            Button.NEXT: "next", Button.PREVIOUS: "previous",
        }
        self._statuses = {
            PLAYING: MediaPlaybackStatus.PLAYING, PAUSED: MediaPlaybackStatus.PAUSED,
            STOPPED: MediaPlaybackStatus.STOPPED, CLOSED: MediaPlaybackStatus.CLOSED,
        }
        self.set_status(CLOSED)

    @property
    def available(self) -> bool:
        return self._controls is not None

    def _on_button(self, _sender, args) -> None:
        command = self._buttons.get(args.button)
        if command:
            self.pressed.emit(command)

    def set_status(self, status: str) -> None:
        if self._controls is None:
            return
        try:
            self._controls.playback_status = self._statuses[status]
        except Exception:  # noqa: BLE001
            log.debug("SMTC: no se pudo fijar el estado", exc_info=True)

    def set_media(self, title: str, subtitle: str = "", video: bool = True) -> None:
        """Lo que muestran el panel multimedia y la pantalla de bloqueo."""
        if self._controls is None:
            return
        try:
            updater = self._controls.display_updater
            updater.clear_all()
            if video:
                updater.type = self._types.VIDEO
                updater.video_properties.title = title[:256]
                updater.video_properties.subtitle = subtitle[:256]
            else:
                updater.type = self._types.MUSIC
                updater.music_properties.title = title[:256]
                updater.music_properties.artist = subtitle[:256]
            updater.update()
        except Exception:  # noqa: BLE001
            log.debug("SMTC: no se pudo actualizar el titulo", exc_info=True)

    def close(self) -> None:
        if self._controls is None:
            return
        try:
            if self._token is not None:
                self._controls.remove_button_pressed(self._token)
            self._controls.display_updater.clear_all()
            self._controls.playback_status = self._statuses[CLOSED]
            self._controls.is_enabled = False
        except Exception:  # noqa: BLE001
            pass
        self._controls = self._player = None
