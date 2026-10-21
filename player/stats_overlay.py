"""Superposicion de estadisticas de reproduccion (4.14, tecla I): un recuadro
sobre el video con el codec, la resolucion y los fps de la pista de video,
el formato de audio, las tasas de bits y los fotogramas perdidos, que se
actualiza cada segundo -- para diagnosticar tirones, como las estadisticas
de mpv.

libVLC 3 no dice si la decodificacion por hardware realmente se activo (solo
el modo pedido), asi que se muestra el modo configurado y se rotula asi."""

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QLabel

from . import theme
from .widgets import OverlayWindow

REFRESH_MS = 1000
MARGIN_PX = 16


def _number(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _bitrate(kbps: float) -> str:
    if kbps >= 1000:
        return f"{_number(kbps / 1000)} Mb/s"
    return f"{_number(kbps, 0)} kb/s"


def _selected(tracks: list, kind: str, track_id: int):
    """La pista elegida de ese tipo; si libVLC no la informa (id -1 con una
    sola pista, o un id que no aparece), la primera del tipo."""
    of_kind = [t for t in tracks if t.get("type") == kind]
    for track in of_kind:
        if track.get("id") == track_id:
            return track
    return of_kind[0] if of_kind and track_id != -1 else None


def stats_lines(info, hw_label: str) -> list:
    """Lineas de texto del recuadro a partir de VLCPlayer.playback_stats()."""
    if info is None:
        return ["Sin medio cargado"]
    tracks = info.get("tracks") or []
    lines = []
    video = _selected(tracks, "video", info.get("video_track", -1))
    if video:
        parts = [video.get("codec") or video.get("fourcc") or "?"]
        if video.get("width") and video.get("height"):
            parts.append(f"{video['width']}×{video['height']}")
        if video.get("fps"):
            parts.append(f"{_number(video['fps'], 3).rstrip('0').rstrip(',')} fps")
        lines.append("Video: " + " · ".join(parts))
    audio = _selected(tracks, "audio", info.get("audio_track", -1))
    if audio:
        parts = [audio.get("codec") or audio.get("fourcc") or "?"]
        if audio.get("channels"):
            parts.append(f"{audio['channels']} canal{'es' if audio['channels'] != 1 else ''}")
        if audio.get("rate"):
            parts.append(f"{audio['rate']} Hz")
        lines.append("Audio: " + " · ".join(parts))
    stats = info.get("stats")
    if stats is None:
        lines.append("Estadísticas: todavía no disponibles")
    else:
        # libVLC da las tasas en bytes por microsegundo, como la interfaz de
        # VLC (que las multiplica por 8000 para mostrarlas en kb/s).
        lines.append(f"Entrada: {_bitrate(stats['input_bitrate'] * 8000)} · "
                     f"Demux: {_bitrate(stats['demux_bitrate'] * 8000)}")
        if video:
            lines.append(f"Fotogramas: {stats['displayed_pictures']} mostrados · "
                         f"{stats['lost_pictures']} perdidos · {stats['decoded_video']} decodificados")
        if audio:
            lines.append(f"Búferes de audio: {stats['played_abuffers']} reproducidos · "
                         f"{stats['lost_abuffers']} perdidos")
        if stats["demux_corrupted"] or stats["demux_discontinuity"]:
            lines.append(f"Errores del demultiplexor: {stats['demux_corrupted']} corruptos · "
                         f"{stats['demux_discontinuity']} discontinuidades")
    if video:
        lines.append(f"Decodificación por hardware (configurada): {hw_label}")
    return lines


def stats_rect(frame_rect: QRect, width: int, height: int, margin: int = MARGIN_PX) -> QRect:
    """Rectangulo global del recuadro: arriba a la izquierda del video, sin
    salirse de el."""
    width = min(width, max(0, frame_rect.width() - 2 * margin))
    height = min(height, max(0, frame_rect.height() - 2 * margin))
    return QRect(frame_rect.topLeft() + QPoint(margin, margin), QRect(0, 0, width, height).size())


class StatsOverlay:
    """El recuadro y su temporizador. `player` es el VLCPlayer; `hw_label` da
    el texto del modo de decodificacion configurado; `frame_rect` el
    rectangulo global del video; `allowed` si la ventana permite mostrar
    superpuestas (no minimizada, etc.)."""

    def __init__(self, owner, player, hw_label, frame_rect, allowed):
        self._player = player
        self._hw_label = hw_label
        self._frame_rect = frame_rect
        self._allowed = allowed
        self.enabled = False
        self.window = OverlayWindow(owner, transparent_for_mouse=True)
        self.label = QLabel(self.window)
        self.label.setStyleSheet(theme.STATS_OVERLAY_STYLE)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.window.layout().addWidget(self.label)
        self.timer = QTimer(owner)
        self.timer.setInterval(REFRESH_MS)
        self.timer.timeout.connect(self.refresh)

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        if self.enabled:
            self.refresh()
            self.timer.start()
        else:
            self.timer.stop()
            self.window.hide()

    def refresh(self):
        if not self.enabled:
            return
        try:
            info = self._player.playback_stats()
        except OSError:  # libVLC liberando el medio a mitad de la lectura
            info = None
        self.label.setText("\n".join(stats_lines(info, self._hw_label())))
        self.reposition()
        if self._allowed():
            self.window.show()

    def reposition(self):
        if not self.enabled:
            return
        hint = self.label.sizeHint()
        self.window.setGeometry(stats_rect(self._frame_rect(), hint.width(), hint.height()))

    def hide(self):
        """Oculta la ventana (minimizada, otra aplicacion activa) sin
        desactivarla: el proximo refresco la vuelve a mostrar."""
        self.window.hide()
