"""Modo pantalla completa (antes dentro de MainWindow).

Al entrar se ocultan la lista, la barra de menus, la de estado y la barra
de controles normal, y aparece el controlador dedicado
(widgets.FullscreenController) en su propia ventana superpuesta (ver
widgets.OverlayWindow: un hijo de video_frame quedaria debajo de la ventana
de video de libVLC), solo mientras hay actividad de mouse. Sin actividad
por IDLE_HIDE_MS se ocultan el controlador y el cursor sobre el video. Al
salir se restaura lo que estaba visible antes."""

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from .widgets import FullscreenController, OverlayWindow, floating_controls_rect

IDLE_HIDE_MS = 2500
CONTROLLER_MAX_WIDTH = 960
CONTROLLER_MARGIN = 24


class FullscreenMode(QObject):
    """`window`: la QMainWindow. `dock`, `controls_bar` y `video_frame`:
    lo que se oculta/restaura y el area de video. `actions`: botones del
    controlador ((clave, QAction) o (None, None) = espacio).
    `reposition_overlays()`: la ventana ubica sus superpuestas (OSD y este
    controlador, ver reposition). `overlays_allowed()`: False con la
    ventana oculta o minimizada."""

    entered = Signal()
    exited = Signal()

    def __init__(self, window, dock, controls_bar, video_frame, actions, reposition_overlays, overlays_allowed,
                 parent=None):
        super().__init__(parent or window)
        self.window = window
        self._reposition_overlays = reposition_overlays
        self._overlays_allowed = overlays_allowed
        self.dock = dock
        self.controls_bar = controls_bar
        self.video_frame = video_frame
        self.overlay = OverlayWindow(window)
        self.controller = FullscreenController(actions, self.overlay)
        self.overlay.layout().addWidget(self.controller)

        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(IDLE_HIDE_MS)
        self.idle_timer.timeout.connect(self.hide_controls)

        self._floating = False
        self._dock_was_visible = True
        self._status_bar_was_visible = True

    @property
    def floating(self) -> bool:
        """True mientras la barra normal esta reemplazada por el controlador."""
        return self._floating

    def toggle(self):
        if self.window.isFullScreen():
            self.exit()
        else:
            self.enter()

    def enter(self):
        if self.window.isFullScreen():
            return
        window = self.window
        self._dock_was_visible = self.dock.isVisible()
        self._status_bar_was_visible = not window.statusBar().isHidden()
        self.dock.setVisible(False)
        window.menuBar().setVisible(False)
        window.statusBar().setVisible(False)
        self.controls_bar.hide()
        self._floating = True
        self.overlay.hide()
        window.showFullScreen()
        self.entered.emit()
        self.on_mouse_activity()

    def exit(self):
        if not self.window.isFullScreen():
            return
        window = self.window
        self.idle_timer.stop()
        self._floating = False
        self.overlay.hide()
        self.controls_bar.show()
        self.video_frame.unsetCursor()
        window.showNormal()
        self.dock.setVisible(self._dock_was_visible)
        window.menuBar().setVisible(True)
        window.statusBar().setVisible(self._status_bar_was_visible)
        self.exited.emit()

    # -- controlador flotante ------------------------------------------------
    def reposition(self, frame_rect):
        """Ubica el controlador sobre `frame_rect` (area de video, en
        coordenadas globales), pegado abajo y centrado."""
        if self._floating:
            self.overlay.setGeometry(floating_controls_rect(
                frame_rect, self.controller.sizeHint().height(),
                margin=CONTROLLER_MARGIN, max_width=CONTROLLER_MAX_WIDTH,
            ))

    def show_controls(self):
        if not self._floating:
            return
        self._reposition_overlays()
        if self._overlays_allowed():
            self.overlay.show()

    def hide_controls(self):
        if self._floating:
            self.overlay.hide()
            # Sin actividad en pantalla completa tambien se oculta el cursor
            # sobre el video (se restaura con el siguiente movimiento).
            self.video_frame.setCursor(Qt.CursorShape.BlankCursor)

    def on_mouse_activity(self):
        if not self.window.isFullScreen():
            return
        self.video_frame.unsetCursor()
        self.show_controls()
        self.idle_timer.start()
