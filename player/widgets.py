"""Widgets propios de la ventana principal (antes todos dentro de
main_window.py): el area de video, la barra de progreso con marcadores,
las ventanas superpuestas, el controlador de pantalla completa y la lista
de reproduccion reordenable."""

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QStylePainter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme


class VideoFrame(QFrame):
    """Area de video. Recibe el mouse aunque libVLC dibuje encima porque
    su ventana hija queda deshabilitada (backend.disable_vlc_input)."""

    doubleClicked = Signal()
    mouseMoved = Signal()
    # pasos de rueda (+ arriba, - abajo), modificadores
    wheelScrolled = Signal(int, object)
    contextMenuRequested = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wheel_remainder = 0

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        self.mouseMoved.emit()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        # angleDelta en octavos de grado: 120 = un "clic" de rueda. Los
        # touchpads mandan fracciones; se acumulan.
        self._wheel_remainder += event.angleDelta().y()
        steps = int(self._wheel_remainder / 120)
        if steps:
            self._wheel_remainder -= steps * 120
            self.wheelScrolled.emit(steps, event.modifiers())
        event.accept()

    def contextMenuEvent(self, event):
        self.contextMenuRequested.emit(event.globalPos())
        event.accept()


class OverlayWindow(QWidget):
    """Ventana propia (top-level, sin marco, translucida) que se dibuja
    ENCIMA del video. Un widget hijo normal de video_frame no sirve: Qt lo
    pinta en la superficie de video_frame, y libVLC tapa esa superficie
    entera con su propia ventana de video -- el OSD y los controles
    flotantes solo se veian sin video (audio sin visualizador). Es el mismo
    enfoque que usa la interfaz Qt de VLC para su controlador de pantalla
    completa.

    Es una ventana "Tool" con la ventana principal como duena, asi que
    Windows la mantiene siempre por encima de ella (sin WindowStaysOnTop
    sobre otras apps) y no aparece en la barra de tareas; no acepta foco,
    asi que hacer clic en sus botones no le quita el teclado (los atajos)
    a la ventana principal. MainWindow la posiciona sobre video_frame (ver
    MainWindow._reposition_overlays)."""

    def __init__(self, owner: QWidget, transparent_for_mouse: bool = False):
        super().__init__(
            owner,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if transparent_for_mouse:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)


def osd_rect(frame_rect: QRect, osd_width: int, osd_height: int, top_margin: int = 24) -> QRect:
    """Rectangulo (en coordenadas globales) del OSD: centrado arriba del
    area de video, sin salirse de ella."""
    width = min(osd_width, frame_rect.width())
    x = frame_rect.x() + max(0, (frame_rect.width() - width) // 2)
    return QRect(x, frame_rect.y() + top_margin, width, osd_height)


def floating_controls_rect(frame_rect: QRect, bar_height: int, margin: int = 0, max_width: int = 0) -> QRect:
    """Rectangulo (global) de los controles flotantes: pegados abajo del
    video, a todo el ancho (o centrados y como mucho max_width), con
    `margin` px de separacion de los bordes."""
    height = min(bar_height, frame_rect.height())
    width = max(0, frame_rect.width() - 2 * margin)
    if max_width:
        width = min(width, max_width)
    x = frame_rect.x() + (frame_rect.width() - width) // 2
    y = frame_rect.y() + frame_rect.height() - height - margin
    return QRect(x, max(frame_rect.y(), y), width, height)


# Teclas que, con la playlist enfocada, son para navegarla y no los atajos
# globales de la ventana (subir/bajar volumen). Izquierda/Derecha siguen
# buscando +-5s: en una lista vertical no hacen nada util.
PLAYLIST_NAVIGATION_KEYS = frozenset({Qt.Key.Key_Up, Qt.Key.Key_Down})


def playlist_owns_key(event) -> bool:
    """True si este QKeyEvent (tipicamente un ShortcutOverride) debe llegarle
    al QListWidget de la playlist en vez de disparar un QShortcut de ventana.
    Solo las flechas sin modificadores: Ctrl+Flecha sigue siendo
    Anterior/Siguiente pista."""
    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    return event.key() in PLAYLIST_NAVIGATION_KEYS and mods == Qt.KeyboardModifier.NoModifier


MARKER_LOOP = "loop"
MARKER_BOOKMARK = "bookmark"
MARKER_CHAPTER = "chapter"
_MARKER_COLORS = {
    MARKER_LOOP: theme.LOOP_MARKER_COLOR,
    MARKER_BOOKMARK: theme.BOOKMARK_MARKER_COLOR,
    MARKER_CHAPTER: theme.CHAPTER_MARKER_COLOR,
}


class PositionSlider(QSlider):
    """QSlider que además dibuja marcadores (tramo A-B, marcadores
    nombrados, capitulos) sobre la barra, con forma distinta por tipo (no
    solo color): A/B = corchete, marcador = punto, capitulo = raya. Emite
    hovered(fraccion, posicion_global) mientras el mouse se mueve encima
    (miniatura de vista previa). Para streams de red, ademas, una franja
    translucida sobre la ranura muestra el tramo ya almacenado delante de
    la posicion (set_buffered_range).

    Un clic izquierdo fuera del tirador salta ahi y sigue como arrastre,
    con cualquier estilo: con windowsvista/Fusion un clic solo avanzaba una
    "pagina", que el siguiente tick revertia (no buscaba)."""

    hovered = Signal(float, QPoint)
    hoverEnded = Signal()

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._markers = []  # lista de (fraccion 0..1, tipo)
        self._buffered = None  # (inicio, fin) en fracciones 0..1, o None
        self.setMouseTracking(True)

    def markers(self) -> list:
        return list(self._markers)

    def set_markers(self, markers):
        markers = list(markers)
        if markers == self._markers:
            return  # sin repintar 4 veces por segundo si nada cambio
        self._markers = markers
        self.update()

    def buffered_range(self):
        return self._buffered

    def set_buffered_range(self, start=None, end=None):
        """Tramo almacenado (fracciones 0..1); None/None lo oculta."""
        if start is None or end is None:
            buffered = None
        else:
            start, end = max(0.0, min(1.0, start)), max(0.0, min(1.0, end))
            buffered = (round(start, 4), round(end, 4)) if end > start else None
        if buffered == self._buffered:
            return
        self._buffered = buffered
        self.update()

    def _x_for(self, fraction: float) -> int:
        handle_width = self.style().pixelMetric(QStyle.PixelMetric.PM_SliderLength, None, self)
        usable_width = max(0, self.width() - handle_width)
        return handle_width // 2 + int(max(0.0, min(1.0, fraction)) * usable_width)

    def buffered_rect(self) -> QRect:
        """Rectangulo de la franja de lo almacenado (vacio si no hay)."""
        if self._buffered is None:
            return QRect()
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        height = max(4, min(groove.height(), 6))
        x0, x1 = self._x_for(self._buffered[0]), self._x_for(self._buffered[1])
        return QRect(x0, groove.center().y() - height // 2 + 1, max(1, x1 - x0), height)

    def _paint_with_buffered_range(self):
        """Ranura, franja de lo almacenado y tirador, en ese orden (la
        franja queda debajo del tirador)."""
        painter = QStylePainter(self)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        option.subControls = QStyle.SubControl.SC_SliderGroove
        painter.drawComplexControl(QStyle.ComplexControl.CC_Slider, option)
        painter.fillRect(self.buffered_rect(), theme.BUFFERED_RANGE_COLOR)
        option.subControls = QStyle.SubControl.SC_SliderHandle
        painter.drawComplexControl(QStyle.ComplexControl.CC_Slider, option)
        painter.end()

    def _fraction_at(self, x: int) -> float:
        handle_width = self.style().pixelMetric(QStyle.PixelMetric.PM_SliderLength, None, self)
        usable_width = max(1, self.width() - handle_width)
        return max(0.0, min(1.0, (x - handle_width / 2) / usable_width))

    def _on_handle(self, pos) -> bool:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        control = self.style().hitTestComplexControl(QStyle.ComplexControl.CC_Slider, option, pos, self)
        return control == QStyle.SubControl.SC_SliderHandle

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._on_handle(event.position().toPoint()):
            fraction = self._fraction_at(int(event.position().x()))
            self.setValue(self.minimum() + round(fraction * (self.maximum() - self.minimum())))
            # Ahora el tirador esta bajo el cursor: el press de Qt empieza un
            # arrastre normal (sliderPressed/Released -> MainWindow busca).
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        fraction = self._fraction_at(int(event.position().x()))
        self.hovered.emit(fraction, event.globalPosition().toPoint())

    def leaveEvent(self, event):
        self.hoverEnded.emit()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if self._buffered is None or not self.isEnabled():
            super().paintEvent(event)
        else:
            self._paint_with_buffered_range()
        if not self._markers:
            return
        bottom = self.height() - 1
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for fraction, kind in self._markers:
            x = self._x_for(fraction)
            color = _MARKER_COLORS.get(kind, theme.BOOKMARK_MARKER_COLOR)
            pen = QPen(color)
            if kind == MARKER_BOOKMARK:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QPoint(x, bottom - 3), 3, 3)
            elif kind == MARKER_LOOP:
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawLine(x, bottom - 8, x, bottom)
                painter.drawLine(x - 2, bottom - 8, x + 2, bottom - 8)
                painter.drawLine(x - 2, bottom, x + 2, bottom)
            else:  # capitulo
                pen.setWidth(1)
                painter.setPen(pen)
                painter.drawLine(x, 1, x, bottom)
        painter.end()


class PlaylistWidget(QListWidget):
    """Lista de reproduccion reordenable arrastrando. Tras soltar emite
    reordered(): MainWindow recalcula el orden a partir de los ids estables
    de cada fila (ver MainWindow._sync_after_reorder), sin depender de que
    señales de modelo emite Qt para un movimiento interno."""

    reordered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.reordered.emit()


class FullscreenController(QWidget):
    """Controlador propio de pantalla completa (antes se reparentaba la
    barra de controles normal): titulo, tiempos, una barra de busqueda mas
    grande y solo los botones que importan en pantalla completa. Los
    botones usan los mismos QAction que los menus (setDefaultAction), asi
    que no hay estado duplicado que sincronizar."""

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.setObjectName("fullscreenController")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.FULLSCREEN_CONTROLLER_STYLE)
        self.setMouseTracking(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(6)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size: 12pt; font-weight: 600;")
        layout.addWidget(self.title_label)

        seek_row = QHBoxLayout()
        self.time_label = QLabel("00:00")
        self.slider = PositionSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setMinimumHeight(28)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setAccessibleName("Posición")
        self.total_label = QLabel("00:00")
        seek_row.addWidget(self.time_label)
        seek_row.addWidget(self.slider, stretch=1)
        seek_row.addWidget(self.total_label)
        layout.addLayout(seek_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.buttons = {}
        for key, action in actions:
            if action is None:
                buttons.addSpacing(18)
                continue
            button = QToolButton()
            button.setDefaultAction(action)
            button.setIconSize(button.iconSize() * 1.4)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setMouseTracking(True)
            buttons.addWidget(button)
            self.buttons[key] = button
        buttons.addStretch(1)
        layout.addLayout(buttons)
        for child in self.findChildren(QWidget):
            child.setMouseTracking(True)

    def event(self, event):
        if event.type() == QEvent.Type.Leave:
            self.slider.hoverEnded.emit()
        return super().event(event)
