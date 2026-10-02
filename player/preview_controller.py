"""Miniatura de vista previa al pasar el mouse por la barra de progreso
(antes dentro de MainWindow).

Buscar-y-capturar en el reproductor secundario no es instantaneo: la
busqueda es asincrona y libVLC necesita decodificar hasta ese punto. Por
eso: (1) el hover se debounce (~300 ms quieto sobre la barra), (2) se
sirve desde la cache (preview.ThumbnailCache) si esa zona ya se capturo, y
(3) si no, se sondea la captura cada CAPTURE_POLL_MS (hasta
CAPTURE_TIMEOUT_MS) en vez de esperar un tiempo fijo y mostrar un
fotograma viejo con el tiempo nuevo. Sin hovers por IDLE_RELEASE_MS se
libera el reproductor secundario."""

import os

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from . import theme
from .formats import format_time
from .preview import (
    CAPTURE_POLL_MS,
    CAPTURE_TIMEOUT_MS,
    IDLE_RELEASE_MS,
    ThumbnailCache,
    new_snapshot_path,
    remove_quietly,
)

HOVER_DEBOUNCE_MS = 300
THUMBNAIL_SIZE = (160, 90)


class PreviewController(QObject):
    """`player`: el VLCPlayer (su reproductor secundario de vista previa).
    `current_path()`: ruta que suena o None. `chapter_name_at(ms)`: nombre
    del capitulo en ese tiempo. `device_pixel_ratio()`: escala de la
    pantalla para capturar a resolucion nativa."""

    def __init__(self, player, current_path, chapter_name_at, device_pixel_ratio, parent=None):
        super().__init__(parent)
        self.player = player
        self._current_path = current_path
        self._chapter_name_at = chapter_name_at
        self._device_pixel_ratio = device_pixel_ratio

        self.popup = None
        self.thumbnail_label = None
        self.time_label = None
        self.pending_fraction = None
        self.pending_pos = None

        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(HOVER_DEBOUNCE_MS)  # espera a que el mouse se detenga
        self.hover_timer.timeout.connect(self.show_preview)

        self.snapshot_path = new_snapshot_path()
        self.cache = ThumbnailCache()
        self._capture_attempts = 0
        self._capture_request = None  # (ruta, fraccion) que se esta capturando
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(CAPTURE_POLL_MS)
        self.capture_timer.timeout.connect(self.poll_snapshot)

        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(IDLE_RELEASE_MS)
        self.idle_timer.timeout.connect(self.player.release_preview_player)

    # -- senales de la barra ------------------------------------------------
    def on_hovered(self, fraction: float, global_pos):
        if self._current_path() is None or self.player.get_length_ms() <= 0:
            return
        self.pending_fraction = fraction
        self.pending_pos = global_pos
        self.idle_timer.stop()
        self.hover_timer.start()

    def on_hover_ended(self):
        self.hover_timer.stop()
        self.capture_timer.stop()
        self.hide()
        if not self.player.is_preview_warmed_up():
            # Todavia no salio ningun fotograma, asi que no se puede pausar
            # sin romper su vout (ver VLCPlayer.load_preview_media): se
            # detiene para que no siga decodificando todo el archivo en
            # segundo plano hasta el proximo hover.
            self.player.stop_preview()
        if self.player.has_preview_player():
            # Sin hovers por un rato, se libera (archivo y decodificador).
            self.idle_timer.start()

    # -- ventana emergente --------------------------------------------------
    def ensure_popup(self):
        if self.popup is not None:
            return
        self.popup = QWidget(None, Qt.WindowType.ToolTip)
        self.popup.setStyleSheet(theme.PREVIEW_POPUP_STYLE)
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(*THUMBNAIL_SIZE)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.thumbnail_label)
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(theme.PREVIEW_TIME_STYLE)
        layout.addWidget(self.time_label)

    def show_preview(self):
        path = self._current_path()
        if path is None or self.pending_fraction is None or self.pending_pos is None:
            return
        fraction = self.pending_fraction
        self.ensure_popup()
        time_ms = int(fraction * self.player.get_length_ms())
        chapter = self._chapter_name_at(time_ms)
        self.time_label.setText(f"{format_time(time_ms)} — {chapter}" if chapter else format_time(time_ms))

        thumbnails = self.player.preview_supported(path)
        self.thumbnail_label.setVisible(thumbnails)
        if thumbnails:
            cached = self.cache.get(path, fraction)
            if cached is not None:
                self.thumbnail_label.setPixmap(cached)
            else:
                # Sin fotograma viejo (de otra posicion u otro archivo).
                self.thumbnail_label.clear()
                self.request_snapshot(path, fraction)

        self.popup.adjustSize()
        self.popup.move(
            self.pending_pos.x() - self.popup.width() // 2,
            self.pending_pos.y() - self.popup.height() - 20,
        )
        self.popup.show()

    def hide(self):
        if self.popup is not None:
            self.popup.hide()

    # -- captura --------------------------------------------------------------
    def request_snapshot(self, path: str, fraction: float):
        if self.player.preview_current_path() != path:
            if not self.player.load_preview_media(path):
                return
        self.player.seek_preview(fraction)
        remove_quietly(self.snapshot_path)
        self._capture_request = (path, fraction)
        self._capture_attempts = 0
        self.capture_timer.start()

    def poll_snapshot(self):
        self._capture_attempts += 1
        if self._capture_attempts * CAPTURE_POLL_MS > CAPTURE_TIMEOUT_MS:
            self.capture_timer.stop()
            return
        if self._capture_request is None or self.popup is None or not self.popup.isVisible():
            self.capture_timer.stop()
            return
        dpr = self._device_pixel_ratio()
        if not os.path.exists(self.snapshot_path):
            width, height = THUMBNAIL_SIZE
            self.player.take_preview_snapshot(self.snapshot_path, width=int(width * dpr), height=int(height * dpr))
        if os.path.exists(self.snapshot_path) and os.path.getsize(self.snapshot_path) > 0:
            pixmap = QPixmap(self.snapshot_path)
            if pixmap.isNull():
                return  # todavia escribiendose
            pixmap.setDevicePixelRatio(dpr)
            path, fraction = self._capture_request
            self.cache.put(path, fraction, pixmap)
            self.thumbnail_label.setPixmap(pixmap)
            self.capture_timer.stop()
            self._capture_request = None

    def stop_timers(self):
        for timer in (self.hover_timer, self.capture_timer, self.idle_timer):
            timer.stop()

    def close(self):
        self.stop_timers()
        remove_quietly(self.snapshot_path)
        if self.popup is not None:
            self.popup.close()
