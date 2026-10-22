import logging
import os
import subprocess
import sys
import time

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QAccessible, QDesktopServices, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:  # Qt 6.8+: avisos para lectores de pantalla (requirements admite 6.6)
    from PySide6.QtGui import QAccessibleAnnouncementEvent
except ImportError:  # pragma: no cover - depende de la version de Qt
    QAccessibleAnnouncementEvent = None

from . import theme
from .actions import ActionRegistry
from .backend import FINISHED_STATES, MediaInfoProbe, PlaybackState, VLCPlayer, libvlc_version
from .bookmarks import add_bookmark, get_bookmarks
from .equalizer_dialog import EqualizerDialog  # noqa: F401 -- reexportado (pruebas)
from .formats import format_rate, format_time, is_audio_file, is_url, path_key
from .fullscreen import FullscreenMode
from .logs import current_log_dir  # noqa: F401 -- reexportado (pruebas)
from .playlist_controller import PlaylistController
from .playlist_model import PlaylistView, display_name
from .playlist_order import playback_failed
from .power import POWER_ACTIONS, PowerCountdownDialog, run_power_action
from .preview_controller import PreviewController
from .recent_files import add_recent_file
from .resume import (
    clear_position,
    get_saved_delays,
    get_saved_position_ms,
    get_saved_track_selection,
    save_delays,
    save_position,
    save_track_selection,
)
from .settings import (
    MAX_RATE,
    MAX_VOLUME,
    MIN_RATE,
    REPEAT_MODES,
    Session,
    Settings,
    clamp_rate,
    load_session,
    load_settings,
    save_session,
    save_settings,
)
from .stats_overlay import StatsOverlay
from .subtitle_cues import adjacent_cue_time, load_cue_starts
from .subtitle_dialog import wait_for_subtitle_jobs
from .video_options import (
    ASPECT_RATIOS,
    CROP_RATIOS,
    DEINTERLACE_LABELS,
    ROTATIONS,
    choice_label,
    next_choice,
)
from .widgets import (  # noqa: F401 -- osd_rect/floating_controls_rect/playlist_owns_key reexportados
    MARKER_BOOKMARK,
    MARKER_CHAPTER,
    MARKER_LOOP,
    OverlayWindow,
    PositionSlider,
    VideoFrame,
    floating_controls_rect,
    osd_rect,
    playlist_owns_key,
)
from .window_dialogs import DialogsMixin
from .window_effects import EffectsMixin
from .window_sources import SourcesMixin
from .window_inputs import InputsMixin
from .window_menus import AB_NUDGE_MS, REPEAT_LABELS, MenusMixin

log = logging.getLogger(__name__)

DEFAULT_WINDOW_SIZE = (1150, 720)
SESSION_SAVE_DELAY_MS = 1000
UI_TICK_MS = 500          # etiquetas y barra; las transiciones llegan por eventos
AB_LOOP_TICK_MS = 50      # mientras hay un tramo A-B activo
OSD_TIMEOUT_MS = 1500
STREAM_STALL_TIMEOUT_MS = 15_000
STREAM_VISUALIZER_DELAY_MS = 1500


_FILTER_EDIT_KEYS_WITH_CTRL = frozenset({
    Qt.Key.Key_A, Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_X, Qt.Key.Key_Z, Qt.Key.Key_Y,
    Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
})


def filter_owns_key(event) -> bool:
    """True si la tecla (ShortcutOverride) es de edicion de texto para el
    buscador de la lista y no un atajo del reproductor."""
    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    if mods & Qt.KeyboardModifier.AltModifier:
        return False
    if mods & Qt.KeyboardModifier.ControlModifier:
        return event.key() in _FILTER_EDIT_KEYS_WITH_CTRL
    return event.key() != Qt.Key.Key_F1 and not (
        Qt.Key.Key_MediaPlay <= event.key() <= Qt.Key.Key_MediaLast
    )


def _icon_path(filename: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", filename)


class _ClickableLabel(QLabel):
    def __init__(self, text, on_click, parent=None):
        super().__init__(text, parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class MainWindow(MenusMixin, DialogsMixin, InputsMixin, EffectsMixin, SourcesMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reproductor Multimedia Pro")
        self.setWindowIcon(QIcon(_icon_path("icon.png")))

        self.player = VLCPlayer()
        # Ajustes guardados de la sesion anterior (ver player/settings.py):
        # se aplican al final de __init__, antes de cualquier load(), para
        # que _create_instance ya arranque con volumen/velocidad/EQ.
        self.settings = load_settings()
        self._restored_geometry = False
        # Lista de reproduccion: modelo, filtro, orden (aleatorio/repetir),
        # fila actual y de la sesion, duraciones y etiquetas en segundo
        # plano (ver playlist_controller.py).
        self.playlist = PlaylistController(probe_factory=MediaInfoProbe, parent=self)
        self.dragging_slider = False
        self.repeat_mode = "none"  # none | one | all
        self._rate = 1.0
        self._advancing = False
        # Generacion (VLCPlayer.generation) cuyo fin ya se proceso: un
        # EndReached y un EncounteredError del mismo archivo no avanzan dos
        # veces.
        self._finished_gen = -1
        # Fallos seguidos (archivo roto/inexistente): al completar una vuelta
        # entera sin que nada se pueda reproducir, se detiene en vez de
        # reintentar para siempre (ver _handle_track_finished).
        self._consecutive_failures = 0
        self._max_time_seen_ms = 0
        # Marcadores de la pista actual: (ruta, lista). Leer bookmarks.json
        # en cada tick era innecesario (ver _current_bookmarks).
        self._bookmarks_cache = None
        self._chapters_cache = None  # (generacion, [(inicio, duracion, nombre)])
        self.equalizer_dialog = None
        self.video_adjust_dialog = None
        self.bookmarks_dialog = None
        self.loop_point_a = None
        self.loop_point_b = None
        self._position_markers_dirty = True
        self._position_markers_length_ms = 0
        self.on_finish_action = "none"
        self._power_dialog = None
        # Subtitulos descargados para un archivo que ya no era el actual:
        # se cargan la proxima vez que se abra (ver _on_online_subtitle_ready).
        self._pending_subtitles = {}
        self._subtitle_cue_cache = {}  # ruta -> (mtime, inicios de linea), ver seek_subtitle_line
        self._pending_track_restore = None
        self._pending_delay_restore = None  # (generacion, audio_ms, subtitulos_ms)
        self._stream_visualizer_gen = -1
        self._stall_time_ms = 0
        self._stall_box = None
        # Llenado (0-100 %) de la cache de red de libVLC, del ultimo evento
        # Buffering del stream actual (ver _buffered_fractions).
        self._buffer_fill = 0.0
        self._folder_scan_thread = None
        self._folder_scan_worker = None
        self._input_scan_done = None  # on_done(encontrados, cancelado) del escaneo en curso
        self._input_scan_queue = []   # (entradas, on_done, estado) esperando su turno
        self._folder_scan_entries = []

        # Vista previa en miniatura al pasar el mouse por la barra de
        # progreso (ver preview_controller.py).
        self._preview_video_widget = None
        self.preview = PreviewController(
            self.player, self._current_path_or_none, lambda ms: self.chapter_name_at(ms),
            lambda: self.devicePixelRatioF(), parent=self,
        )

        # OSD (on-screen display) transitoria sobre el video -- ver _show_osd.
        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.setInterval(OSD_TIMEOUT_MS)

        # Guardado de la playlist con debounce (ver _schedule_session_save).
        self._session_save_timer = QTimer(self)
        self._session_save_timer.setSingleShot(True)
        self._session_save_timer.setInterval(SESSION_SAVE_DELAY_MS)
        self._session_save_timer.timeout.connect(self.save_session_now)

        # Stream que no arranca o se queda sin datos (ver _on_stream_stalled).
        self._stall_timer = QTimer(self)
        self._stall_timer.setSingleShot(True)
        self._stall_timer.setInterval(STREAM_STALL_TIMEOUT_MS)
        self._stall_timer.timeout.connect(self._on_stream_stalled)

        # Tramo A-B: chequeo frecuente solo mientras esta activo.
        self._ab_timer = QTimer(self)
        self._ab_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._ab_timer.setInterval(AB_LOOP_TICK_MS)
        self._ab_timer.timeout.connect(self._check_ab_loop)

        self.setAcceptDrops(True)

        self.action_registry = ActionRegistry(self)
        self._build_actions()
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        # Atajos cambiados por el usuario (4.11), sobre los predeterminados ya registrados.
        self.action_registry.apply_overrides(self.settings.shortcuts)
        self.action_registry.register_shortcuts_on_owner()
        # Teclas multimedia con la ventana sin foco y el panel multimedia de Windows (4.12).
        from .media_controls import SystemMediaControls

        self.system_media = SystemMediaControls(self)
        self.system_media.pressed.connect(self.media_command)
        # Anterior / Reproducir-Pausar / Siguiente bajo la miniatura de la barra de tareas (4.12).
        from .taskbar_buttons import TaskbarButtons

        self.taskbar_buttons = TaskbarButtons(lambda name: theme.make_icon(name, theme.taskbar_icon_color()), self)
        if self.taskbar_buttons.available:
            self.taskbar_buttons.attach(int(self.winId()))
        self.taskbar_buttons.pressed.connect(self.media_command)
        self._refresh_icons()
        self.playlist.contentsChanged.connect(self._schedule_session_save)
        self.playlist.summaryChanged.connect(self.playlist_dock.setWindowTitle)

        self._osd_label.hide()
        self._osd_timer.timeout.connect(self._hide_osd)
        # En pantalla completa la barra de estado esta oculta: sus mensajes
        # ("Reproduciendo: ...", "No se pudo reproducir: ...") van al OSD.
        self.statusBar().messageChanged.connect(self._on_status_message)
        QApplication.instance().applicationStateChanged.connect(self._on_application_state_changed)

        # Escucha movimientos de mouse en toda la app (no solo en video_frame)
        # para que mover el mouse sobre los propios controles flotantes
        # tambien cuente como actividad y no los oculte mientras se usan.
        QApplication.instance().installEventFilter(self)
        self.video_frame.mouseMoved.connect(self.fullscreen.on_mouse_activity)

        self._connect_player_events()

        self._apply_settings(self.settings)
        if self.settings.restore_session:
            self._restore_session(load_session())
        if not self._restored_geometry:
            self.resize(*DEFAULT_WINDOW_SIZE)

        self.timer = QTimer(self)
        self.timer.setInterval(UI_TICK_MS)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

    # ------------------------------------------------------------ ajustes
    def _apply_settings(self, s: Settings):
        """Aplica los ajustes guardados a los widgets y al backend. Se llama
        una sola vez, al final de __init__ y antes de cualquier load()."""
        self.volume_slider.setValue(s.volume)
        self.player.set_volume(s.volume)
        self._set_muted(s.muted)
        self._set_rate(s.rate, announce=False)
        self._set_repeat_mode(s.repeat_mode)
        self.act_shuffle.setChecked(s.shuffle)
        self.act_visualizer.setChecked(s.visualizer)
        for action in self.menu_sub_size.actions():
            if action.data() == s.subtitle_scale:
                action.setChecked(True)
                self.player.set_subtitle_scale(s.subtitle_scale)
        for action in self.menu_zoom.actions():
            if action.data() == s.video_scale:
                action.setChecked(True)
                self.player.set_video_scale(s.video_scale)
        if s.always_on_top:
            # Sin pasar por _on_always_on_top_toggled: esa llama show(), y la
            # ventana todavia no se debe mostrar (lo hace run.py).
            self.act_always_on_top.blockSignals(True)
            self.act_always_on_top.setChecked(True)
            self.act_always_on_top.blockSignals(False)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.act_restore_session.setChecked(s.restore_session)
        self.act_allow_multiple_windows.setChecked(s.allow_multiple_windows)
        self.act_remaining_time.setChecked(s.show_remaining_time)
        for action in self.theme_group.actions():
            if action.data() == s.theme:
                action.setChecked(True)
        self._apply_theme(s.theme)
        self.player.network_caching_ms = s.network_caching_ms
        self.player.rtsp_tcp = s.rtsp_tcp
        if self.menu_gpu is not None:
            for action, value in ((self.act_gpu_upscale, s.gpu_upscale), (self.act_gpu_hdr, s.gpu_hdr)):
                action.blockSignals(True)
                action.setChecked(value)
                action.blockSignals(False)
            for action in self.hw_decoding_group.actions():
                action.setChecked(action.data() == s.hw_decoding)
            self.player.set_gpu_options(s.gpu_upscale, s.gpu_hdr, s.hw_decoding)
        eq = s.equalizer
        if eq.enabled:
            self.player.set_equalizer_values(eq.preamp, eq.bands)
        self._set_deinterlace(s.deinterlace, announce=False)
        self.player.set_video_adjust(s.video_adjust)
        if s.audio_device:
            self.player.set_audio_device(s.audio_device)
        if s.normalize_volume and self.act_normalize_volume.isEnabled():
            self.act_normalize_volume.setChecked(True)
        self._set_audio_passthrough(s.audio_passthrough, announce=False)
        self._restore_audio_effects(s.audio_effects, s.pitch)
        self._restore_video_filters(s.video_filters)
        if s.geometry:
            self._restored_geometry = self.restoreGeometry(QByteArray.fromBase64(s.geometry.encode("ascii")))
        if s.window_state:
            self.restoreState(QByteArray.fromBase64(s.window_state.encode("ascii")))

    def current_settings(self) -> Settings:
        """Ajustes actuales, tal como se guardarian al cerrar."""
        s = Settings()
        s.volume = self.volume_slider.value()
        s.muted = self.player.is_muted()
        s.rate = self._rate
        s.repeat_mode = self.repeat_mode
        s.shuffle = self.act_shuffle.isChecked()
        s.visualizer = self.act_visualizer.isChecked()
        s.subtitle_scale = next(
            (a.data() for a in self.menu_sub_size.actions() if a.isChecked()), self.settings.subtitle_scale
        )
        s.video_scale = self.player.get_video_scale()
        s.always_on_top = self.act_always_on_top.isChecked()
        s.restore_session = self.act_restore_session.isChecked()
        s.allow_multiple_windows = self.act_allow_multiple_windows.isChecked()
        s.show_remaining_time = self.act_remaining_time.isChecked()
        s.theme = next((a.data() for a in self.theme_group.actions() if a.isChecked()), "system")
        s.network_caching_ms = self.player.network_caching_ms
        s.rtsp_tcp = self.player.rtsp_tcp
        s.gpu_upscale, s.gpu_hdr, s.hw_decoding = self.player.gpu_options()
        if self.equalizer_dialog is not None:
            s.equalizer = self.equalizer_dialog.state()
        else:
            # El dialogo nunca se abrio: el EQ sigue como se restauro.
            s.equalizer = self.settings.equalizer
        s.geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        s.window_state = bytes(self.saveState().toBase64()).decode("ascii")
        s.last_open_dir = self.settings.last_open_dir
        s.deinterlace = self.player.get_deinterlace()
        s.video_adjust = self.player.get_video_adjust()
        s.audio_device = self.player.get_audio_device()
        s.normalize_volume = self.player.is_volume_normalized()
        s.shortcuts = self.action_registry.overrides()
        s.audio_passthrough = self.player.get_audio_passthrough()
        s.audio_effects = list(self.player.get_audio_effects())
        s.pitch = self.player.get_pitch()
        s.video_filters = list(self.player.get_video_filters())
        return s

    def save_settings_now(self) -> bool:
        self.settings = self.current_settings()
        return save_settings(self.settings)

    # -- lista: atajos al controlador -------------------------------------
    @property
    def current_index(self) -> int:
        """Fila de la lista que suena (-1 = ninguna)."""
        return self.playlist.current_index

    @current_index.setter
    def current_index(self, row: int):
        self.playlist.current_index = row

    @property
    def order(self):
        return self.playlist.order

    @property
    def _session_row(self) -> int:
        """Fila de la sesion restaurada que estaba sonando al cerrar: se
        selecciona pero no se reproduce sola; Reproducir la retoma (y
        resume.py la posicion). -1 = ninguna."""
        return self.playlist.session_row

    @_session_row.setter
    def _session_row(self, row: int):
        self.playlist.session_row = row

    # -- sesion (playlist) -----------------------------------------------
    def playlist_entries(self) -> list:
        return self.playlist.entries()

    def current_session(self) -> Session:
        current = self.current_index if self.current_index != -1 else self._session_row
        return Session(entries=self.playlist_entries(), current_index=current)

    def _schedule_session_save(self):
        self._session_save_timer.start()

    def save_session_now(self) -> bool:
        self._session_save_timer.stop()
        if not self.act_restore_session.isChecked():
            # Si el usuario no quiere que se restaure, tampoco se guarda (y
            # se borra lo que hubiera de antes).
            return save_session(Session())
        return save_session(self.current_session())

    def _restore_session(self, session: Session):
        if not session.entries:
            return
        self.add_files_to_playlist(session.entries)
        if session.current_index != -1:
            self._session_row = session.current_index
            self.playlist_view.set_current_source_row(session.current_index)
        # Recien restaurada, la sesion en disco ya es identica.
        self._session_save_timer.stop()

    # ------------------------------------------------------------ acciones
    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        self.video_frame = VideoFrame()
        self.video_frame.setAutoFillBackground(True)
        palette = self.video_frame.palette()
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.black)
        self.video_frame.setPalette(palette)
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.video_frame.setMouseTracking(True)
        self.video_frame.doubleClicked.connect(self.toggle_fullscreen)
        self.video_frame.wheelScrolled.connect(self._on_video_wheel)
        self.video_frame.contextMenuRequested.connect(self._show_video_context_menu)
        central_layout.addWidget(self.video_frame, stretch=1)

        # OSD (ver _show_osd): ventana propia sobre el video (ver
        # OverlayWindow), oculta salvo cuando hay un mensaje transitorio.
        # Transparente al mouse: nunca tapa un doble clic sobre el video.
        self._osd_overlay = OverlayWindow(self, transparent_for_mouse=True)
        self._osd_label = QLabel(self._osd_overlay)
        self._osd_label.setStyleSheet(theme.OSD_STYLE)
        self._osd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._osd_overlay.layout().addWidget(self._osd_label)
        # Estadisticas de reproduccion (4.14, tecla I): otra superpuesta, arriba a la izquierda.
        self.stats_overlay = StatsOverlay(
            self, self.player, self._hw_decoding_label, self._video_frame_global_rect, self._overlays_allowed)

        self.controls_bar = self._build_controls_bar()
        self._enable_mouse_tracking_recursive(self.controls_bar)
        central_layout.addWidget(self.controls_bar)

        self.setCentralWidget(central)

        # Widget invisible dedicado solo a darle a libVLC una ventana nativa
        # para el reproductor secundario de miniaturas de vista previa (ver
        # VLCPlayer.attach_preview_output). Nunca se muestra: crear su
        # winId() nativo alcanza para que libVLC pueda dibujar en él.
        self._preview_video_widget = VideoFrame(self)
        self._preview_video_widget.setFixedSize(160, 90)
        self._preview_video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self._preview_video_widget.move(-1000, -1000)
        self.player.attach_preview_output(self._preview_video_widget)

        self.position_slider.hovered.connect(self.preview.on_hovered)
        self.position_slider.hoverEnded.connect(self.preview.on_hover_ended)

        # Playlist dock: buscador arriba, lista reordenable debajo (vista
        # sobre el filtro del controlador, ver playlist_model.py).
        self.playlist_view = PlaylistView()
        self.playlist_view.setModel(self.playlist.proxy)
        # activated cubre doble clic Y Enter/Return sobre la fila enfocada.
        self.playlist_view.activated.connect(lambda index: self.play_index(self.playlist_view.to_source_row(index)))
        self.playlist_view.rowsDropped.connect(self.playlist.move_rows)
        self.playlist_view.installEventFilter(self)
        QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self.playlist_view,
            activated=self.remove_selected_from_playlist,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        self.playlist_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_view.customContextMenuRequested.connect(self.show_playlist_context_menu)
        self.playlist_view.setAccessibleName("Lista de reproducción")

        self.playlist_filter = QLineEdit()
        self.playlist_filter.setPlaceholderText("Buscar en la lista (Ctrl+F)")
        self.playlist_filter.setClearButtonEnabled(True)
        self.playlist_filter.setAccessibleName("Buscar en la lista")
        self.playlist_filter.textChanged.connect(self.playlist.set_filter)
        self.playlist_filter.returnPressed.connect(self._play_first_filtered)
        self.playlist_filter.installEventFilter(self)

        dock_body = QWidget()
        dock_layout = QVBoxLayout(dock_body)
        dock_layout.setContentsMargins(4, 4, 4, 4)
        dock_layout.setSpacing(4)
        dock_layout.addWidget(self.playlist_filter)
        dock_layout.addWidget(self.playlist_view, stretch=1)

        self.playlist_dock = QDockWidget(self.playlist.dock_title(), self)
        # saveState()/restoreState() identifican los docks por objectName.
        self.playlist_dock.setObjectName("playlist_dock")
        self.playlist_dock.setWidget(dock_body)
        self.playlist_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)
        QShortcut(QKeySequence.StandardKey.Find, dock_body, activated=self._focus_playlist_filter,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        # Pantalla completa: controlador dedicado en su ventana superpuesta
        # (ver fullscreen.py).
        self.fullscreen = FullscreenMode(
            self, self.playlist_dock, self.controls_bar, self.video_frame,
            [("previous", self.act_prev), ("play", self.act_play_pause), ("stop", self.act_stop),
             ("next", self.act_next), (None, None), ("mute", self.act_mute), (None, None),
             ("fullscreen", self.act_fullscreen)],
            reposition_overlays=self._reposition_overlays, overlays_allowed=self._overlays_allowed,
        )
        self.fullscreen.entered.connect(self._on_fullscreen_entered)
        self.fullscreen.exited.connect(lambda: self._set_action_icon(self.act_fullscreen, "fullscreen"))
        self.fullscreen_controller = self.fullscreen.controller
        fs_slider = self.fullscreen_controller.slider
        fs_slider.sliderPressed.connect(self._on_slider_pressed)
        fs_slider.sliderReleased.connect(lambda: self._on_slider_released(fs_slider))
        fs_slider.hovered.connect(self.preview.on_hovered)
        fs_slider.hoverEnded.connect(self.preview.on_hover_ended)

        self.statusBar().showMessage("Listo")

    def _enable_mouse_tracking_recursive(self, widget: QWidget):
        """Sin esto, un QWidget solo genera mouseMoveEvent con algun boton
        del mouse presionado."""
        widget.setMouseTracking(True)
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)

    def _tool_button(self, action, accessible_name):
        button = QToolButton()
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setAccessibleName(accessible_name)
        return button

    def _build_controls_bar(self) -> QWidget:
        bar = QWidget()
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 8)

        seek_row = QHBoxLayout()
        self.label_time_current = QLabel("00:00")
        self.position_slider = PositionSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setMinimumHeight(24)
        self.position_slider.setAccessibleName("Posición")
        self.position_slider.setToolTip(
            "Clic o arrastre para buscar. Corchetes naranjas: tramo A-B; puntos dorados: marcadores; "
            "rayas azules: capítulos."
        )
        self.label_time_total = _ClickableLabel("00:00", self._toggle_remaining_time)
        self.label_time_total.setToolTip("Clic: alternar duración / tiempo restante")
        seek_row.addWidget(self.label_time_current)
        seek_row.addWidget(self.position_slider, stretch=1)
        seek_row.addWidget(self.label_time_total)
        layout.addLayout(seek_row)

        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(lambda: self._on_slider_released(self.position_slider))

        buttons_row = QHBoxLayout()
        self.btn_prev = self._tool_button(self.act_prev, "Pista anterior")
        self.btn_play = self._tool_button(self.act_play_pause, "Reproducir o pausar")
        self.btn_stop = self._tool_button(self.act_stop, "Detener")
        self.btn_next = self._tool_button(self.act_next, "Pista siguiente")
        for b in (self.btn_prev, self.btn_play, self.btn_stop, self.btn_next):
            buttons_row.addWidget(b)

        buttons_row.addSpacing(16)

        self.btn_mute = self._tool_button(self.act_mute, "Silenciar")
        buttons_row.addWidget(self.btn_mute)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, MAX_VOLUME)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setToolTip("Volumen (flechas arriba/abajo o rueda del mouse sobre el video)")
        self.volume_slider.setAccessibleName("Volumen")
        self.volume_slider.valueChanged.connect(self.player.set_volume)
        buttons_row.addWidget(self.volume_slider)

        self.label_volume_percent = QLabel("80%")
        self.label_volume_percent.setFixedWidth(40)
        self.volume_slider.valueChanged.connect(lambda v: self.label_volume_percent.setText(f"{v}%"))
        buttons_row.addWidget(self.label_volume_percent)

        buttons_row.addSpacing(16)

        # Velocidad: boton compacto "1,0×" con su menu (mismo submenu que
        # Reproduccion -> Velocidad; se arma en _build_menu).
        self.speed_button = QToolButton()
        self.speed_button.setText(format_rate(1.0))
        self.speed_button.setToolTip("Velocidad de reproducción ([ más lenta, ] más rápida, = normal)")
        self.speed_button.setAccessibleName("Velocidad de reproducción")
        self.speed_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.speed_button.setAutoRaise(True)
        buttons_row.addWidget(self.speed_button)

        buttons_row.addStretch(1)

        self.btn_shuffle = self._tool_button(self.act_shuffle, "Aleatorio")
        buttons_row.addWidget(self.btn_shuffle)
        self.btn_repeat = self._tool_button(self.act_repeat_cycle, "Modo de repetición")
        buttons_row.addWidget(self.btn_repeat)
        self.btn_ab_loop = self._tool_button(self.act_ab_loop, "Bucle A-B")
        buttons_row.addWidget(self.btn_ab_loop)
        self.btn_fullscreen = self._tool_button(self.act_fullscreen, "Pantalla completa")
        buttons_row.addWidget(self.btn_fullscreen)

        layout.addLayout(buttons_row)

        # Ninguno de estos controles debe quedarse con el foco de teclado:
        # si lo tuvieran, pulsar Espacio o las flechas activaría el propio
        # widget en vez de disparar los atajos globales. Todos tienen su
        # equivalente en un menu y/o atajo.
        for w in (
            self.btn_prev, self.btn_play, self.btn_stop, self.btn_next,
            self.btn_mute, self.position_slider, self.volume_slider,
            self.speed_button, self.btn_shuffle, self.btn_repeat, self.btn_ab_loop,
            self.btn_fullscreen,
        ):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        return bar

    def _refresh_icons(self):
        """Iconos SVG tenidos con el color de texto del tema actual (el
        controlador de pantalla completa usa los mismos QAction, sobre un
        fondo siempre oscuro)."""
        color = theme.icon_color(self)
        playing = self.player.is_playing() if self.player.media_player is not None else False
        icons = {
            self.act_prev: "previous", self.act_next: "next", self.act_stop: "stop",
            self.act_play_pause: "pause" if playing else "play",
            self.act_mute: "muted" if self.player.is_muted() else "volume",
            self.act_fullscreen: "fullscreen_exit" if self.isFullScreen() else "fullscreen",
            self.act_shuffle: "shuffle",
            self.act_repeat_cycle: "repeat_one" if self.repeat_mode == "one" else "repeat",
            self.act_ab_loop: "ab_loop",
        }
        for action, name in icons.items():
            action.setIcon(theme.make_icon(name, color))
        self._icon_names = icons

    def _set_action_icon(self, action, name):
        if getattr(self, "_icon_names", {}).get(action) == name:
            return
        action.setIcon(theme.make_icon(name, theme.icon_color(self)))
        self._icon_names[action] = name

    # ------------------------------------------------------------ eventos de libVLC
    def _connect_player_events(self):
        ev = self.player.events
        ev.endReached.connect(self._on_track_finished_event)
        ev.errorOccurred.connect(self._on_track_finished_event)
        ev.opening.connect(self._on_opening)
        ev.playing.connect(self._on_playing)
        ev.paused.connect(lambda _gen: self._update_play_icon())
        ev.stopped.connect(lambda _gen: self._update_play_icon())
        ev.buffering.connect(self._on_buffering)
        ev.lengthChanged.connect(self._on_length_changed)
        ev.chapterChanged.connect(self._on_chapter_changed)
        ev.tracksChanged.connect(self._on_tracks_changed)
        ev.metaChanged.connect(self._on_meta_changed)
        ev.snapshotTaken.connect(self._on_snapshot_taken)

    def _is_current_gen(self, gen: int) -> bool:
        return gen == self.player.generation and self.current_index != -1

    def _on_track_finished_event(self, gen: int, attempt: int = 0):
        """EndReached / EncounteredError (encolados desde el hilo de libVLC).
        Un EncounteredError puede llegar antes de que el estado pase a
        Ended/Error: se vuelve a mirar unas veces antes de decidir."""
        if not self._is_current_gen(gen) or gen == self._finished_gen or self._advancing:
            return
        state = self.player.playback_state()
        if state not in FINISHED_STATES:
            if attempt < 20:
                QTimer.singleShot(100, lambda: self._on_track_finished_event(gen, attempt + 1))
            return
        self._finished_gen = gen
        self._stall_timer.stop()
        self._advancing = True
        try:
            self._handle_track_finished(state)
        finally:
            self._advancing = False

    def _on_opening(self, gen: int):
        if not self._is_current_gen(gen):
            return
        path = self._current_path_or_none()
        if path is not None and is_url(path):
            self._stall_time_ms = 0
            self._stall_timer.start()

    def _on_playing(self, gen: int):
        self._update_play_icon()
        if not self._is_current_gen(gen):
            return
        path = self._current_path_or_none()
        if path is not None:
            self.statusBar().showMessage(f"Reproduciendo: {self._display_name(path)}")
        self._chapters_cache = None
        self._restore_saved_tracks()
        self._restore_saved_delays()
        self._maybe_schedule_stream_visualizer(gen)

    def _on_buffering(self, gen: int, percent: float):
        if not self._is_current_gen(gen):
            return
        path = self._current_path_or_none()
        if path is None or not is_url(path):
            return  # los archivos locales tambien "almacenan", sin interes
        self._buffer_fill = max(0.0, min(100.0, percent))
        if percent < 100:
            self.statusBar().showMessage(f"Almacenando en búfer… {int(percent)} %")
            if not self._stall_timer.isActive():
                self._stall_time_ms = self.player.get_time_ms()
                self._stall_timer.start()
        else:
            self._stall_timer.stop()
            self.statusBar().showMessage(f"Reproduciendo: {self._display_name(path)}")

    def _on_length_changed(self, gen: int, _length_ms: int):
        if self._is_current_gen(gen):
            self._chapters_cache = None
            self._invalidate_position_markers()

    def _on_chapter_changed(self, gen: int, chapter: int):
        if not self._is_current_gen(gen):
            return
        chapters = self._current_chapters()
        if 0 <= chapter < len(chapters) and chapters[chapter][2]:
            self._show_osd(f"Capítulo: {chapters[chapter][2]}")

    def _on_tracks_changed(self, gen: int):
        if self._is_current_gen(gen):
            self._chapters_cache = None
            self._invalidate_position_markers()
            self._restore_saved_tracks()
            self._maybe_schedule_stream_visualizer(gen)

    def _on_meta_changed(self, gen: int):
        if not self._is_current_gen(gen):
            return
        path = self._current_path_or_none()
        if path is None or not is_url(path):
            return
        title = self.player.now_playing()
        if self.playlist.set_icy_title(path, title):
            self.setWindowTitle(f"Reproductor Multimedia Pro — {title}")
            if getattr(self, "system_media", None) is not None:
                self.system_media.set_media(title, self._display_name(path), video=False)

    def _on_snapshot_taken(self, filename: str):
        if getattr(self, "_quick_snapshot_pending", None):
            self._quick_snapshot_pending = None
            self._show_osd("Captura guardada")
            self.statusBar().showMessage(f"Captura guardada: {filename}", 5000)

    def _update_play_icon(self):
        playing = self.player.media_player is not None and self.player.is_playing()
        self._set_action_icon(self.act_play_pause, "pause" if playing else "play")
        self._update_system_media_status(playing)
        if getattr(self, "taskbar_buttons", None) is not None:
            self.taskbar_buttons.set_state(playing, self.current_index != -1)

    def nativeEvent(self, event_type, message):
        """Mensajes de Windows para los botones de la miniatura de la barra de tareas (4.12)."""
        buttons = getattr(self, "taskbar_buttons", None)
        if buttons is not None and buttons.available and event_type == b"windows_generic_MSG":
            import ctypes.wintypes

            msg = ctypes.wintypes.MSG.from_address(int(message))
            if buttons.handle_message(msg.message, msg.wParam or 0):
                return True, 0
        return super().nativeEvent(event_type, message)

    def _update_system_media_status(self, playing: bool) -> None:
        controls = getattr(self, "system_media", None)
        if controls is None or not controls.available:
            return
        if playing:
            controls.set_status("playing")
        elif self.current_index != -1 and self.player.is_paused():
            controls.set_status("paused")
        elif self.current_index != -1:
            controls.set_status("stopped")
        else:
            controls.set_status("closed")

    # -- streams de red ----------------------------------------------------
    def _maybe_schedule_stream_visualizer(self, gen: int):
        """Para una URL no se sabe por la extension si es solo audio: una vez
        abierta, si no trae video y el visualizador esta activado, se
        reconecta con el visualizador (una sola vez por apertura)."""
        path = self._current_path_or_none()
        if (path is None or not is_url(path) or not self.act_visualizer.isChecked()
                or self.player.visualizer_active() or self._stream_visualizer_gen == gen):
            return
        self._stream_visualizer_gen = gen
        QTimer.singleShot(STREAM_VISUALIZER_DELAY_MS, lambda: self._maybe_enable_stream_visualizer(gen))

    def _maybe_enable_stream_visualizer(self, gen: int):
        if not self._is_current_gen(gen) or not self.act_visualizer.isChecked():
            return
        if self.player.is_audio_only_stream() and self.player.enable_stream_visualizer():
            self._stream_visualizer_gen = self.player.generation
            log.info("Stream de solo audio: visualizador activado")

    def _on_stream_stalled(self):
        path = self._current_path_or_none()
        if path is None or not is_url(path):
            return
        state = self.player.playback_state()
        waiting = state in (PlaybackState.OPENING, PlaybackState.BUFFERING) or (
            state == PlaybackState.PLAYING and self.player.get_time_ms() <= self._stall_time_ms
        )
        if not waiting:
            return
        self._show_stall_prompt(path)

    # ------------------------------------------------------------ playlist
    # Modelo, filtro, orden y metadatos viven en self.playlist
    # (PlaylistController); aqui queda lo que toca la ventana: abrir,
    # dialogos, menu contextual y detener lo que suena antes de quitarlo.
    def _display_name(self, path: str) -> str:
        return display_name(path)

    def _entry_label(self, path: str) -> str:
        return self.playlist.entry_label(path)

    def _set_current_index(self, index: int):
        """Cambia la fila actual y mueve el marcador ▶ (independiente de la
        seleccion)."""
        self.playlist.current_index = index

    def add_files_to_playlist(self, paths):
        """Unico punto de entrada a la playlist (dialogos, carpetas, arrastrar
        y soltar, linea de comandos, recientes, .m3u, otra instancia); ver
        PlaylistController.add."""
        self.playlist.add(paths)

    # -- buscador y reordenar ----------------------------------------------
    def _focus_playlist_filter(self):
        self.playlist_dock.show()
        self.playlist_filter.setFocus()
        self.playlist_filter.selectAll()

    def _play_first_filtered(self):
        row = self.playlist.first_visible_row()
        if row != -1:
            self.play_index(row)

    def sort_playlist(self, by: str = "name"):
        self.playlist.sort(by)

    def remove_unavailable(self) -> int:
        rows = self.playlist.unavailable_rows()
        self.remove_rows(rows)
        if rows:
            noun = "entrada no disponible quitada" if len(rows) == 1 else "entradas no disponibles quitadas"
            self.statusBar().showMessage(f"{len(rows)} {noun}", 4000)
        return len(rows)

    # -- abrir ---------------------------------------------------------------
    def open_recent_file(self, path: str):
        if not is_url(path) and not os.path.exists(path):
            QMessageBox.warning(self, "Archivo reciente", f"No se encontró el archivo:\n{path}")
            return
        self.play_index(self.playlist.add([path]))

    def show_in_file_manager(self, path: str):
        if sys.platform.startswith("win") and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def remove_selected_from_playlist(self):
        self.remove_rows(self.playlist_view.selected_source_rows())

    def remove_rows(self, rows):
        rows = sorted({r for r in rows if 0 <= r < self.playlist.count()})
        if not rows:
            return
        if self.current_index in rows:
            # Guardar ANTES de detener: tras stop() libVLC reporta -1 de
            # tiempo/largo y save_position no guardaria nada.
            self._save_current_position()
            self.player.stop()
            self.player.stop_preview()
            self._invalidate_position_markers(clear=True)
        self.playlist.remove_rows(rows)

    def clear_playlist(self):
        self._save_current_position()
        self.player.stop()
        self.player.stop_preview()
        self._invalidate_position_markers(clear=True)
        self.playlist.clear()

    # ------------------------------------------------------------ transport
    def play_index(self, index: int, user: bool = True):
        """user=False solo cuando la llama el avance automatico (fin de
        pista o fallo); cualquier eleccion del usuario reinicia el conteo
        de fallos seguidos."""
        path = self.playlist.path(index)
        if path is None:
            return
        self._save_current_position()
        self._stop_recording_quietly()
        if user:
            self._consecutive_failures = 0
        self._set_current_index(index)
        self._session_row = -1
        self._schedule_session_save()
        self.order.jump_to(index)
        self._max_time_seen_ms = 0
        self._bookmarks_cache = None
        self._chapters_cache = None
        self._invalidate_position_markers(clear=True)
        self._stall_timer.stop()
        self._buffer_fill = 0.0
        if self.player.preview_current_path() not in (None, path):
            self.player.stop_preview()
        self.playlist_view.set_current_source_row(index)
        self._advancing = False
        self._clear_ab_loop()
        if self.bookmarks_dialog is not None:
            self.bookmarks_dialog.close()
            self.bookmarks_dialog = None
        if self._needs_web_resolution(path):
            # La pagina de un video (YouTube...): yt-dlp la resuelve en un hilo y
            # despues se vuelve a llamar aqui (3.15).
            self._resolve_web_video(index, path, user)
            return
        # La posicion guardada va como :start-time del Media (ver
        # VLCPlayer.load): arranca directo ahi.
        saved_ms = 0 if is_url(path) else (get_saved_position_ms(path) or 0)
        audio_track, subtitle_track = ((None, None) if is_url(path) else get_saved_track_selection(path))
        self.player.load(path, enable_visualizer=self.act_visualizer.isChecked(), start_ms=saved_ms)
        self._pending_track_restore = None
        # libVLC vuelve los desfases a 0 con cada Media: los guardados para
        # este archivo se aplican cuando empieza a reproducir (_on_playing).
        delays = (0, 0) if is_url(path) else get_saved_delays(path)
        self._pending_delay_restore = (self.player.generation, *delays) if any(delays) else None
        if audio_track is not None or subtitle_track is not None:
            self._pending_track_restore = {
                "generation": self.player.generation,
                "audio_track": audio_track,
                "subtitle_track": subtitle_track,
            }
        pending_sub = self._pending_subtitles.pop(path_key(path), None)
        if pending_sub and os.path.exists(pending_sub):
            self.player.add_subtitle_before_play(pending_sub)
        self.player.attach_video_output(self.video_frame)
        self.player.play()
        self.player.set_rate(self._rate)
        self.setWindowTitle(f"Reproductor Multimedia Pro — {self._display_name(path)}")
        if getattr(self, "system_media", None) is not None:
            self.system_media.set_media(self._display_name(path), "Reproductor Multimedia Pro",
                                        video=not (is_audio_file(path) or is_url(path)))
        verb = "Abriendo" if is_url(path) else "Reproduciendo"
        self.statusBar().showMessage(f"{verb}: {self._display_name(path)}")
        if saved_ms:
            self._show_osd(f"Reanudado en {format_time(saved_ms)} — Inicio para empezar desde el principio")
            self.statusBar().showMessage(f"Reanudado desde {format_time(saved_ms)}", 4000)
        # Despues de los mensajes de arriba, para que el aviso no se pise.
        self._report_dropped_options()
        add_recent_file(path)

    def _save_current_position(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            return
        save_track_selection(path, self.player.get_current_audio_track(), self.player.get_current_subtitle_track())
        save_position(path, self.player.get_time_ms(), self.player.get_length_ms())
        self._persist_current_delays()

    def _current_path_or_none(self):
        return self.playlist.current_path()

    def toggle_play_pause(self):
        if self.current_index == -1:
            if self._session_row != -1:
                # Elemento que estaba sonando al cerrar (sesion restaurada).
                self.play_index(self._session_row)
                return
            if self.playlist.count() > 0:
                first = self.order.advance(repeat_all=False)
                self.play_index(first if first is not None else 0)
            return
        if self.player.is_idle():
            # Tras Detener, fin de la lista o un fallo, pause() de libVLC no
            # hace nada: hay que volver a arrancar la pista actual.
            self.play_index(self.current_index)
            return
        self.player.toggle_pause()

    # Una pulsacion de tecla multimedia que llega dos veces (por la ventana y
    # por SMTC) en menos de esto se cuenta una vez; play/pause/toggle son un grupo.
    MEDIA_COMMAND_DEDUP_S = 0.4

    def media_command(self, command: str) -> bool:
        """Teclas multimedia, botones del panel multimedia de Windows (SMTC) y
        auriculares. False si se descarto por repetida."""
        group = "playback" if command in ("play", "pause", "toggle") else command
        now = time.monotonic()
        last_group, last_at = getattr(self, "_last_media_command", ("", -1e9))
        if group == last_group and now - last_at < self.MEDIA_COMMAND_DEDUP_S:
            return False
        self._last_media_command = (group, now)
        handlers = {
            "toggle": self.toggle_play_pause, "play": self._media_key_play, "pause": self._media_key_pause,
            "stop": self.stop, "next": lambda: self.play_next(auto=False), "previous": self.play_previous,
        }
        handler = handlers.get(command)
        if handler is not None:
            handler()
        return handler is not None

    def _media_key_play(self):
        if self.current_index == -1 or self.player.is_idle() or self.player.is_paused():
            self.toggle_play_pause()

    def _media_key_pause(self):
        if self.player.is_playing():
            self.player.set_paused(True)

    def stop(self):
        # Guardar antes: despues de stop() get_time()/get_length() valen -1.
        self._save_current_position()
        self._stall_timer.stop()
        self.player.stop()
        self.player.stop_preview()
        self._update_play_icon()

    def step_frame(self):
        if self.current_index == -1:
            return
        if not self.player.is_paused():
            self.statusBar().showMessage("Pausa el video para avanzar fotograma a fotograma", 3000)
            return
        if self.player.next_frame():
            self._show_osd("Fotograma siguiente")

    def play_next(self, auto: bool, after_failure: bool = False):
        """auto: la pista termino sola (no fue el boton Siguiente).
        after_failure: la pista actual no se pudo reproducir -- en ese caso
        se ignora Repetir: Uno (si no, reintentaria el mismo archivo roto
        para siempre)."""
        if self.playlist.count() == 0:
            return
        if self.repeat_mode == "one" and auto and not after_failure and self.current_index != -1:
            self.play_index(self.current_index, user=False)
            return
        next_index = self.order.advance(repeat_all=self.repeat_mode == "all")
        if next_index is None:
            if auto:
                self.player.stop()
                self.player.stop_preview()
                self._handle_playlist_finished()
            return
        self.play_index(next_index, user=not auto)

    def _handle_playlist_finished(self):
        action = self.on_finish_action
        if action == "none":
            return
        if action == "exit":
            self.close()
            return
        if action in POWER_ACTIONS:
            self._start_power_countdown(action)

    def _start_power_countdown(self, action: str):
        """Cuenta regresiva cancelable (ver power.py). La accion elegida se
        consume: vuelve a "Nada" se cumpla o se cancele."""
        self._set_on_finish_action("none")
        if self._power_dialog is not None:
            return
        dialog = PowerCountdownDialog(action, parent=self)
        dialog.fired.connect(run_power_action)
        dialog.cancelled.connect(lambda: self.statusBar().showMessage("Acción al terminar la lista cancelada", 4000))
        dialog.finished.connect(lambda _r: setattr(self, "_power_dialog", None))
        self._power_dialog = dialog
        dialog.show()
        dialog.raise_()

    def _set_on_finish_action(self, key: str):
        self.on_finish_action = key
        for action in self.on_finish_group.actions():
            action.setChecked(action.data() == key)

    def play_previous(self):
        if self.current_index == -1:
            return
        if self.player.get_time_ms() > 3000:
            self.player.set_time_ms(0)
            return
        prev_index = self.order.back(repeat_all=self.repeat_mode == "all")
        if prev_index is None:
            self.player.set_time_ms(0)
            return
        self.play_index(prev_index)

    @property
    def shuffle(self) -> bool:
        return self.order.shuffle

    def _on_shuffle_toggled(self, checked: bool):
        self.order.set_shuffle(checked)

    def _cycle_repeat_mode(self):
        idx = REPEAT_MODES.index(self.repeat_mode)
        self._set_repeat_mode(REPEAT_MODES[(idx + 1) % len(REPEAT_MODES)])

    def _set_repeat_mode(self, mode: str):
        self.repeat_mode = mode if mode in REPEAT_MODES else "none"
        label = REPEAT_LABELS[self.repeat_mode]
        self.act_repeat_cycle.setText(label)
        self.act_repeat_cycle.setToolTip(f"{label} (clic para cambiar)")
        self.act_repeat_cycle.setCheckable(True)
        self.act_repeat_cycle.setChecked(self.repeat_mode != "none")
        for action in self.repeat_group.actions():
            action.setChecked(action.data() == self.repeat_mode)
        if hasattr(self, "_icon_names"):
            self._set_action_icon(self.act_repeat_cycle, "repeat_one" if self.repeat_mode == "one" else "repeat")

    # -- velocidad -----------------------------------------------------------
    def _set_rate(self, rate: float, announce: bool = True):
        self._rate = clamp_rate(rate)
        self.player.set_rate(self._rate)
        self.speed_button.setText(format_rate(self._rate))
        for action in self.speed_group.actions():
            action.setChecked(abs(action.data() - self._rate) < 1e-6)
        if announce:
            self._show_osd(f"Velocidad: {format_rate(self._rate)}")

    def _nudge_rate(self, delta: float):
        self._set_rate(max(MIN_RATE, min(MAX_RATE, self._rate + delta)))

    def rate(self) -> float:
        return self._rate

    # -- tramo A-B -----------------------------------------------------------
    def _on_ab_loop_clicked(self):
        if self.current_index == -1:
            return
        if self.loop_point_a is None:
            self._set_ab_point_a()
        elif self.loop_point_b is None:
            self._set_ab_point_b()
        else:
            self._clear_ab_loop_with_feedback()

    def _set_ab_point_a(self):
        if self.current_index == -1:
            return
        self.loop_point_a = self.player.get_time_ms()
        self.loop_point_b = None
        self._ab_timer.stop()
        self.act_ab_loop.setChecked(False)
        self.act_ab_loop.setCheckable(False)
        self.act_ab_loop.setToolTip(f"A: {format_time(self.loop_point_a)} — clic para marcar B")
        self._invalidate_position_markers()
        self._show_osd(f"Punto A: {format_time(self.loop_point_a)}")

    def _set_ab_point_b(self):
        if self.current_index == -1 or self.loop_point_a is None:
            return
        candidate_b = self.player.get_time_ms()
        if candidate_b <= self.loop_point_a:
            self.statusBar().showMessage("El punto B debe ser posterior al punto A", 3000)
            return
        self._apply_ab_loop(self.loop_point_a, candidate_b)

    def _apply_ab_loop(self, a_ms: int, b_ms: int):
        """Activa el tramo A-B [a_ms, b_ms] (b_ms > a_ms) y lo anuncia."""
        self.loop_point_a, self.loop_point_b = a_ms, b_ms
        text = f"A-B: {format_time(a_ms)}-{format_time(b_ms)}"
        self.act_ab_loop.setToolTip(f"{text} — clic para desactivar")
        self.act_ab_loop.setCheckable(True)
        self.act_ab_loop.setChecked(True)
        self._ab_timer.start()
        self._invalidate_position_markers()
        self._show_osd(text)

    def _nudge_ab_point(self, which: str, delta_ms: int):
        """Mueve el punto A o B delta_ms, sin cruzarlos (quedan al menos
        AB_NUDGE_MS separados) ni salir del archivo."""
        if self.current_index == -1:
            return
        a, b = self.loop_point_a, self.loop_point_b
        length = self.player.get_length_ms()
        if which == "a" and a is not None:
            upper = b - AB_NUDGE_MS if b is not None else (length if length > 0 else a + delta_ms)
            new_a = max(0, min(a + delta_ms, upper))
            if b is None:
                self.loop_point_a = new_a
                self.act_ab_loop.setToolTip(f"A: {format_time(new_a)} — clic para marcar B")
                self._invalidate_position_markers()
                self._show_osd(f"Punto A: {format_time(new_a)}")
            else:
                self._apply_ab_loop(new_a, b)
        elif which == "b" and a is not None and b is not None:
            new_b = max(a + AB_NUDGE_MS, b + delta_ms)
            if length > 0:
                new_b = min(new_b, length)
            self._apply_ab_loop(a, new_b)

    def _loop_between_bookmarks(self):
        """Tramo A-B entre el marcador anterior y el siguiente a la posicion
        actual; sin marcador a un lado, el inicio o el final del archivo."""
        if self.current_index == -1:
            return
        now = self.player.get_time_ms()
        length = self.player.get_length_ms()
        marks = sorted(b["position_ms"] for b in self._current_bookmarks())
        a = max((m for m in marks if m <= now), default=0)
        b = min((m for m in marks if m > now), default=length if length > 0 else None)
        if b is None or b - a < AB_NUDGE_MS:
            self.statusBar().showMessage("No hay un tramo entre marcadores en esta posición", 3000)
            return
        self._apply_ab_loop(a, b)

    def _clear_ab_loop_with_feedback(self):
        if self.loop_point_a is None and self.loop_point_b is None:
            return
        self._clear_ab_loop()
        self._show_osd("Bucle A-B desactivado")

    def _clear_ab_loop(self):
        self.loop_point_a = None
        self.loop_point_b = None
        self._ab_timer.stop()
        self.act_ab_loop.setChecked(False)
        self.act_ab_loop.setCheckable(False)
        self.act_ab_loop.setToolTip(
            "Marca un punto A, luego un punto B: repite en bucle solo ese tramo. Un tercer clic lo desactiva."
        )
        self._invalidate_position_markers()

    def _check_ab_loop(self):
        if self.loop_point_b is not None and self.player.get_time_ms() >= self.loop_point_b:
            self.player.set_time_ms(self.loop_point_a)

    # -- marcadores de la barra ---------------------------------------------
    def _position_markers(self, length_ms: int) -> list:
        markers = []
        if self.loop_point_a is not None:
            markers.append((self.loop_point_a / length_ms, MARKER_LOOP))
        if self.loop_point_b is not None:
            markers.append((self.loop_point_b / length_ms, MARKER_LOOP))
        for b in self._current_bookmarks():
            markers.append((b["position_ms"] / length_ms, MARKER_BOOKMARK))
        for start, _duration, _name in self._current_chapters()[1:]:
            markers.append((start / length_ms, MARKER_CHAPTER))
        return markers

    def _refresh_position_markers(self, length_ms: int):
        if not self._position_markers_dirty and self._position_markers_length_ms == length_ms:
            return
        markers = self._position_markers(length_ms)
        self.position_slider.set_markers(markers)
        self.fullscreen_controller.slider.set_markers(markers)
        self._position_markers_dirty = False
        self._position_markers_length_ms = length_ms

    def _invalidate_position_markers(self, clear: bool = False):
        self._position_markers_dirty = True
        if clear:
            self._position_markers_length_ms = 0
            self.position_slider.set_markers([])
            self.fullscreen_controller.slider.set_markers([])

    def _current_bookmarks(self) -> list:
        """Marcadores de la pista actual, leidos de disco una vez por pista
        (se invalida al cambiar de pista o al agregar/quitar/renombrar, ver
        _invalidate_bookmarks_cache) en vez de en cada tick de update_ui."""
        path = self._current_path_or_none()
        if path is None or is_url(path):
            return []
        if self._bookmarks_cache is None or self._bookmarks_cache[0] != path:
            self._bookmarks_cache = (path, get_bookmarks(path))
        return self._bookmarks_cache[1]

    def _invalidate_bookmarks_cache(self):
        self._bookmarks_cache = None
        self._invalidate_position_markers()

    def _current_chapters(self) -> list:
        """Capitulos del archivo actual; se vuelven a pedir a libVLC cuando
        llega un evento de largo/pistas/Playing (ver _chapters_cache)."""
        if self.current_index == -1:
            return []
        gen = self.player.generation
        if self._chapters_cache is None or self._chapters_cache[0] != gen:
            self._chapters_cache = (gen, self.player.chapters())
        return self._chapters_cache[1]

    def chapter_name_at(self, time_ms: int) -> str:
        name = ""
        for start, _duration, chapter_name in self._current_chapters():
            if start <= time_ms:
                name = chapter_name
        return name

    def quick_add_bookmark(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            return
        position_ms = self.player.get_time_ms()
        default_name = f"Marcador {format_time(position_ms)}"
        name, ok = QInputDialog.getText(self, "Nuevo marcador", "Nombre:", text=default_name)
        if ok and name.strip():
            add_bookmark(path, name.strip(), position_ms)
            self._invalidate_bookmarks_cache()
            self.statusBar().showMessage(f'Marcador "{name.strip()}" agregado en {format_time(position_ms)}', 3000)

    # -- capitulos -------------------------------------------------------------
    def next_chapter(self):
        if self.current_index != -1 and self._current_chapters():
            self.player.next_chapter()

    def previous_chapter(self):
        if self.current_index != -1 and self._current_chapters():
            self.player.previous_chapter()

    def seek_subtitle_line(self, direction: int):
        """Alt+Arriba/Abajo (4.15): al inicio de la linea anterior/siguiente
        del subtitulo externo seleccionado (el ultimo cargado), teniendo en
        cuenta el retardo de subtitulos. Las pistas incrustadas no sirven:
        libVLC 3 no da sus tiempos."""
        if self.current_index == -1:
            return
        externals = self.player.external_subtitles()
        if not externals or self.player.get_current_subtitle_track() == -1:
            self._show_osd("Solo con un subtítulo externo activo")
            return
        starts = self._subtitle_cue_starts(externals[-1])
        if not starts:
            self._show_osd("No se pudieron leer las líneas del subtítulo")
            return
        target = adjacent_cue_time(starts, self.player.get_time_ms(), direction,
                                   self.player.get_subtitle_delay_ms())
        if target is None:
            self._show_osd("No hay más líneas" if direction > 0 else "Es la primera línea")
            return
        self._seek_to(target)

    def _subtitle_cue_starts(self, path: str) -> list:
        """Inicios de linea de `path`, leidos una vez por archivo (se vuelve
        a leer si cambia en disco, p. ej. al descargar otra version)."""
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return []
        cached = self._subtitle_cue_cache.get(path)
        if cached is None or cached[0] != stamp:
            cached = (stamp, load_cue_starts(path))
            self._subtitle_cue_cache[path] = cached
        return cached[1]

    # ------------------------------------------------------------ sliders
    def _on_slider_pressed(self):
        self.dragging_slider = True

    def _on_slider_released(self, slider=None):
        slider = slider or self.position_slider
        self.dragging_slider = False
        if not self.player.is_seekable() and self.player.is_live_stream():
            return
        pos = slider.value() / 1000.0
        self.player.set_position(pos)

    def _seek_relative(self, delta_ms: int):
        if self.current_index == -1:
            return
        new_time = max(0, self.player.get_time_ms() + delta_ms)
        length = self.player.get_length_ms()
        if length > 0:
            new_time = min(new_time, length)
        self.player.set_time_ms(new_time)
        seconds = delta_ms / 1000
        seconds_str = str(int(seconds)) if seconds == int(seconds) else f"{seconds:g}"
        sign = "+" if delta_ms >= 0 else ""
        self._show_osd(f"{sign}{seconds_str}s")

    def _seek_to(self, time_ms: int):
        if self.current_index == -1:
            return
        self.player.set_time_ms(time_ms)
        self._show_osd(format_time(time_ms))

    def _nudge_volume(self, delta: int):
        self.volume_slider.setValue(max(0, min(MAX_VOLUME, self.volume_slider.value() + delta)))
        self._show_osd(f"Volumen: {self.volume_slider.value()}%")

    def _on_video_wheel(self, steps: int, modifiers):
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._seek_relative(5000 * steps)
        else:
            self._nudge_volume(5 * steps)

    def _toggle_remaining_time(self):
        self.act_remaining_time.trigger()

    # ------------------------------------------------------------------ OSD
    def _show_osd(self, text: str):
        """Muestra un mensaje breve y semitransparente sobre el video (p. ej.
        "+5s", "Volumen: 65%") que se oculta solo tras ~1.5s."""
        self._osd_label.setText(text)
        self._osd_label.show()
        self._osd_timer.start()
        self._reposition_overlays()
        if self._overlays_allowed():
            self._osd_overlay.show()
        # El OSD es una ventana superpuesta que los lectores de pantalla no
        # leen: el mismo texto va a la barra de estado (si no tiene ya un
        # mensaje, que suele ser la version mas detallada) y como aviso
        # accesible.
        if not self.statusBar().currentMessage():
            self.statusBar().showMessage(text, OSD_TIMEOUT_MS)
        self._announce(text)

    def _announce(self, text: str):
        """Aviso "polite" para lectores de pantalla (Qt 6.8+); no hace nada
        sin tecnologia de asistencia activa."""
        if QAccessibleAnnouncementEvent is None or not QAccessible.isActive():
            return
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self, text))

    def _hide_osd(self):
        self._osd_label.hide()
        self._osd_overlay.hide()

    def _on_status_message(self, text: str):
        if text and self.isFullScreen():
            self._show_osd(text)

    # -- ventanas superpuestas (OSD y controles flotantes) ------------------
    def _overlays_allowed(self) -> bool:
        """Las superpuestas son ventanas propias: con la principal oculta o
        minimizada no deben aparecer solas sobre el escritorio."""
        return self.isVisible() and not self.isMinimized()

    def _hw_decoding_label(self) -> str:
        checked = self.hw_decoding_group.checkedAction() if hasattr(self, "hw_decoding_group") else None
        return checked.text() if checked else "Automática"

    def _video_frame_global_rect(self) -> QRect:
        return QRect(self.video_frame.mapToGlobal(QPoint(0, 0)), self.video_frame.size())

    def _reposition_overlays(self):
        frame = self._video_frame_global_rect()
        hint = self._osd_label.sizeHint()
        self._osd_overlay.setGeometry(osd_rect(frame, hint.width(), hint.height()))
        if hasattr(self, "stats_overlay"):
            self.stats_overlay.reposition()
        if hasattr(self, "fullscreen"):
            self.fullscreen.reposition(frame)

    def _hide_overlays(self):
        self._osd_overlay.hide()
        self.stats_overlay.hide()
        self.fullscreen.overlay.hide()

    def _on_application_state_changed(self, state):
        # Al pasar a otra aplicacion (Alt+Tab) las superpuestas no deben
        # quedar flotando; al volver, la proxima actividad las muestra.
        if state != Qt.ApplicationState.ApplicationActive:
            self._hide_overlays()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self._hide_overlays()
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_icon_names"):
            self._refresh_icons()
        super().changeEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._reposition_overlays()

    def toggle_mute(self):
        self._set_muted(not self.player.is_muted())
        self._show_osd("Silencio: sí" if self.player.is_muted() else "Silencio: no")

    def _set_muted(self, muted: bool):
        self.player.set_muted(muted)
        self.act_mute.setChecked(muted)
        if hasattr(self, "_icon_names"):
            self._set_action_icon(self.act_mute, "muted" if muted else "volume")

    # ------------------------------------------------------------ update loop
    def update_ui(self):
        """Refresco periodico de etiquetas y barra. Las transiciones (fin de
        pista, error, Playing, buffering) llegan por eventos de libVLC (ver
        _connect_player_events)."""
        length = self.player.get_length_ms()
        time_ms = self.player.get_time_ms()
        live = self.player.is_live_stream()
        sliders = (self.position_slider, self.fullscreen_controller.slider)
        for slider in sliders:
            slider.setEnabled(not live)
        if live:
            self._set_time_labels(format_time(time_ms), theme.LIVE_LABEL)
        elif length > 0 and not self.dragging_slider:
            pos = self.player.get_position()
            for slider in sliders:
                slider.blockSignals(True)
                slider.setValue(int(pos * 1000))
                slider.blockSignals(False)
            if self.act_remaining_time.isChecked():
                total = f"-{format_time(max(0, length - time_ms))}"
            else:
                total = format_time(length)
            self._set_time_labels(format_time(time_ms), total)
            self._refresh_position_markers(length)
            self.position_slider.setAccessibleDescription(f"{format_time(time_ms)} de {format_time(length)}")

            path = self._current_path_or_none()
            if path is not None:
                self.playlist.note_duration(path, length)

        buffered = None if live else self._buffered_fractions(length, time_ms)
        for slider in sliders:
            slider.set_buffered_range(*(buffered or (None, None)))

        self._update_play_icon()
        self._check_ab_loop()
        self.player.apply_pending_restore()

        state = self.player.playback_state()
        if state == PlaybackState.PLAYING:
            self._max_time_seen_ms = max(self._max_time_seen_ms, time_ms)
            if time_ms > 0 or length > 0:
                self._consecutive_failures = 0
            if self._stall_timer.isActive() and time_ms > self._stall_time_ms:
                self._stall_timer.stop()
        if self.isFullScreen():
            path = self._current_path_or_none()
            self.fullscreen_controller.title_label.setText(self._entry_label(path) if path else "")

    def _buffered_fractions(self, length_ms: int, time_ms: int):
        """(inicio, fin) del tramo almacenado de un stream de red con
        duracion conocida, en fracciones de la barra; None si no aplica.
        libVLC no expone que bytes ya bajo: lo que si sabe es cuanto de su
        cache de red (:network-caching) esta lleno, y ese es el tramo que
        tiene listo delante de la posicion actual."""
        path = self._current_path_or_none()
        if path is None or not is_url(path) or length_ms <= 0:
            return None
        ahead_ms = self.player.network_caching_ms * self._buffer_fill / 100.0
        if ahead_ms <= 0:
            return None
        return time_ms / length_ms, min(1.0, (time_ms + ahead_ms) / length_ms)

    def _set_time_labels(self, current: str, total: str):
        self.label_time_current.setText(current)
        self.label_time_total.setText(total)
        self.fullscreen_controller.time_label.setText(current)
        self.fullscreen_controller.total_label.setText(total)

    def _handle_track_finished(self, state):
        failed = playback_failed(
            error_seen=self.player.error_seen(),
            state_is_error=state == PlaybackState.ERROR,
            state_is_ended=state == PlaybackState.ENDED,
            length_ms=self.player.get_length_ms(),
            max_time_ms=self._max_time_seen_ms,
        )
        path = self._current_path_or_none()
        if failed:
            self._consecutive_failures += 1
            name = self._display_name(path) if path is not None else "?"
            log.warning("No se pudo reproducir: %s (estado %s)", path, state)
            if self._consecutive_failures >= self.playlist.count():
                # Una vuelta completa sin poder reproducir nada: detenerse en
                # vez de reintentar en bucle (y reescribir recientes cada vez).
                self.player.stop()
                self.player.stop_preview()
                self._consecutive_failures = 0
                self.statusBar().showMessage(
                    f"No se pudo reproducir: {name}. Ningún elemento de la lista se pudo reproducir; detenido.", 0
                )
                return
            self.statusBar().showMessage(f"No se pudo reproducir: {name}", 5000)
            self.play_next(auto=True, after_failure=True)
            return
        # Se vio/escuchó completo: la próxima vez que se abra, empieza de
        # nuevo en vez de "reanudar" a un segundo del final.
        if path is not None and not is_url(path):
            clear_position(path)
        self.play_next(auto=True)

    # ------------------------------------------------------------ tracks
    def _select_audio_track(self, track_id: int):
        self.player.set_audio_track(track_id)
        self._persist_current_track_selection()

    def _select_subtitle_track(self, track_id: int):
        self.player.set_subtitle_track(track_id)
        self._persist_current_track_selection()

    def _persist_current_track_selection(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            return
        save_track_selection(path, self.player.get_current_audio_track(), self.player.get_current_subtitle_track())

    def _restore_saved_tracks(self):
        pending = self._pending_track_restore
        if pending is None or pending.get("generation") != self.player.generation:
            return
        audio_track = pending.get("audio_track")
        subtitle_track = pending.get("subtitle_track")
        audio_ids = {track_id for track_id, _name in self.player.audio_tracks()}
        subtitle_ids = {track_id for track_id, _name in self.player.subtitle_tracks()}
        if audio_track is not None and (audio_track < 0 or audio_track in audio_ids):
            if self.player.get_current_audio_track() != audio_track:
                self.player.set_audio_track(audio_track)
        if subtitle_track is not None and (subtitle_track < 0 or subtitle_track in subtitle_ids):
            if self.player.get_current_subtitle_track() != subtitle_track:
                self.player.set_subtitle_track(subtitle_track)
        self._pending_track_restore = None

    def _restore_saved_delays(self):
        """Aplica una vez los desfases guardados para el archivo que se acaba
        de abrir (ver play_index)."""
        pending = self._pending_delay_restore
        if pending is None or pending[0] != self.player.generation:
            return
        self._pending_delay_restore = None
        _gen, audio_ms, subtitle_ms = pending
        if audio_ms:
            self.player.set_audio_delay_ms(audio_ms)
        if subtitle_ms:
            self.player.set_subtitle_delay_ms(subtitle_ms)
        parts = [f"audio {audio_ms:+d} ms" if audio_ms else "", f"subtítulos {subtitle_ms:+d} ms" if subtitle_ms else ""]
        self.statusBar().showMessage("Sincronía guardada para este archivo: " + ", ".join(p for p in parts if p), 4000)

    def _persist_current_delays(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            return
        if self._pending_delay_restore is not None:
            return  # todavia no se aplicaron: no pisar lo guardado con los 0 de libVLC
        save_delays(path, self.player.get_audio_delay_ms(), self.player.get_subtitle_delay_ms())

    def _adjust_subtitle_delay(self, delta_ms: int):
        self._set_subtitle_delay(self.player.get_subtitle_delay_ms() + delta_ms)

    def _set_subtitle_delay(self, delay_ms: int):
        self.player.set_subtitle_delay_ms(delay_ms)
        self._persist_current_delays()
        sign = "+" if delay_ms >= 0 else ""
        self.statusBar().showMessage(f"Sincronía de subtítulos: {sign}{delay_ms} ms", 3000)
        self._show_osd(f"Subtítulos: {sign}{delay_ms} ms")

    def _adjust_audio_delay(self, delta_ms: int):
        if self.current_index == -1:
            return
        self._set_audio_delay(self.player.get_audio_delay_ms() + delta_ms)

    def _set_audio_delay(self, delay_ms: int):
        if self.current_index == -1:
            return
        self.player.set_audio_delay_ms(delay_ms)
        self._persist_current_delays()
        sign = "+" if delay_ms >= 0 else ""
        self._show_osd(f"Audio: {sign}{delay_ms} ms")
        self.statusBar().showMessage(f"Sincronía de audio: {sign}{delay_ms} ms", 3000)

    def _on_subtitle_scale_changed(self, scale: int):
        self.player.set_subtitle_scale(scale)
        if self.current_index == -1:
            return
        # --sub-text-scale es de instancia: para verlo aplicado ya mismo hay
        # que recrear el Instance y recargar el archivo actual. Se hace con
        # VLCPlayer.reload_preserving_state() y NO con play_index(): esta
        # ultima es "abrir pista" (borra el tramo A-B, cierra el dialogo de
        # marcadores, descarta subtitulos externos, pistas elegidas y el
        # desfase, reescribe recientes). Si esta detenido, no hace nada: la
        # proxima carga ya recrea el Instance con el tamano nuevo.
        self.player.reload_preserving_state()

    # -- paginas de video con yt-dlp (3.15) -----------------------------------------
    # Las URL de los streams caducan: una resolucion vale este tiempo.
    WEB_STREAM_MAX_AGE_S = 3 * 3600

    def _needs_web_resolution(self, path: str) -> bool:
        from . import web_video

        if not (is_url(path) and web_video.is_page_url(path) and web_video.available()):
            return False
        resolved_at = getattr(self, "_web_resolved_at", {}).get(path)
        fresh = (self.player.web_stream(path) is not None and resolved_at is not None
                 and time.monotonic() - resolved_at < self.WEB_STREAM_MAX_AGE_S)
        return not fresh

    def _resolve_web_video(self, index: int, path: str, user: bool) -> None:
        from .web_video import ResolveWorker

        self._stall_timer.stop()
        self.player.stop()
        self.statusBar().showMessage(f"Obteniendo el video de {self._display_name(path)}…")
        self._show_osd("Obteniendo el video…")

        def done(stream, _index=index, _path=path, _user=user):
            self._web_workers.discard(worker)
            self.player.set_web_stream(stream)
            self._web_resolved_at = {**getattr(self, "_web_resolved_at", {}), _path: time.monotonic()}
            if stream.title:
                self.playlist.set_icy_title(_path, stream.title)
            if self.current_index == _index and self.playlist.path(_index) == _path:
                self.play_index(_index, user=_user)

        def failed(message, _index=index, _path=path):
            self._web_workers.discard(worker)
            if self.current_index != _index or self.playlist.path(_index) != _path:
                return
            self.statusBar().showMessage(message, 8000)
            self._show_osd("No se pudo abrir el video")
            self.player.forget_web_stream(_path)

        worker = ResolveWorker(path, done, failed)
        self._web_workers = getattr(self, "_web_workers", set())
        self._web_workers.add(worker)
        worker.start()

    # -- reproducir en otro dispositivo (3.14) ------------------------------------
    def cast_to(self, renderer):
        """Envia la reproduccion a `renderer` (None = esta PC), siguiendo desde el mismo punto."""
        if renderer is self.player.get_renderer() or (
                renderer is not None and self.player.get_renderer() is not None
                and renderer.key == self.player.get_renderer().key):
            return
        self.player.set_renderer(renderer)
        if self.current_index != -1:
            self.player.reload_preserving_state()
        self._populate_renderer_menu()
        self._show_osd(f"Reproduciendo en {renderer.name}" if renderer is not None else "Reproduciendo en esta PC")

    def _set_audio_passthrough(self, mode: str, announce: bool = True):
        for action in self.passthrough_group.actions():
            action.setChecked(action.data() == mode)
        if mode == self.player.get_audio_passthrough():
            return
        self.player.set_audio_passthrough(mode)
        if self.current_index != -1:
            self.player.reload_preserving_state()
        self._report_dropped_options()
        if announce:
            self._show_osd("Passthrough: " + {"off": "desactivado", "ac3_dts": "AC3 y DTS", "all": "todos los formatos"}[mode])

    # -- mejora por GPU ------------------------------------------------------
    def _on_gpu_options_changed(self):
        hw = next((a.data() for a in self.hw_decoding_group.actions() if a.isChecked()), "any")
        self.player.set_gpu_options(self.act_gpu_upscale.isChecked(), self.act_gpu_hdr.isChecked(), hw)
        if self.current_index != -1:
            # Opciones de instancia: igual que el tamano de subtitulos.
            self.player.reload_preserving_state()
        self._report_dropped_options()

    def _report_dropped_options(self):
        """Si libVLC rechazo opciones al recrear el Instance (ver
        backend.create_instance_with_fallback), avisar y desmarcar."""
        dropped = self.player.take_dropped_options()
        if not dropped:
            return
        messages = []
        if "gpu" in dropped and self.menu_gpu is not None:
            for action in (self.act_gpu_upscale, self.act_gpu_hdr):
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)
            for action in self.hw_decoding_group.actions():
                action.setChecked(action.data() == "any")
            messages.append("la mejora por GPU")
        if "passthrough" in dropped:
            for action in self.passthrough_group.actions():
                action.setChecked(action.data() == "off")
            messages.append("el passthrough de audio")
        if "rotation" in dropped:
            self._check_menu_value(self.menu_rotation, "")
            messages.append("la rotación y los filtros de video")
        messages += self._uncheck_dropped_effects(dropped)
        if "visualizer" in dropped:
            messages.append("el visualizador de audio")
        if messages:
            text = f"Tu versión de VLC ({libvlc_version()}) no admite {' ni '.join(messages)}; se desactivó."
            log.warning(text)
            self.statusBar().showMessage(text, 8000)

    # ------------------------------------------------------------ equalizer
    # ------------------------------------------------------------ imagen y sonido
    def _set_aspect_ratio(self, ratio: str):
        self.player.set_aspect_ratio(ratio)
        self._check_menu_value(self.menu_aspect, ratio)
        self._show_osd(f"Aspecto: {choice_label(ASPECT_RATIOS, ratio)}")

    def _set_crop(self, ratio: str):
        self.player.set_crop(ratio)
        self._check_menu_value(self.menu_crop, ratio)
        self._show_osd(f"Recorte: {choice_label(CROP_RATIOS, ratio)}")

    def _set_rotation(self, rotation: str, announce: bool = True):
        """Video > Rotar / voltear (4.13): opcion de instancia, como el passthrough."""
        self._check_menu_value(self.menu_rotation, rotation)
        if rotation == self.player.get_rotation():
            return
        self.player.set_rotation(rotation)
        if self.current_index != -1:
            self.player.reload_preserving_state()
        self._report_dropped_options()
        if announce:
            self._show_osd(f"Rotación: {choice_label(ROTATIONS, rotation)}")

    def _cycle_choice(self, choices, setter, current):
        setter(next_choice(choices, current))

    def _set_deinterlace(self, mode: str, announce: bool = True):
        needs_reload = self.player.set_deinterlace(mode)
        self._check_menu_value(self.menu_deinterlace, self.player.get_deinterlace())
        if needs_reload and self.current_index != -1:
            # Volver al automatico: solo con un reproductor nuevo (ver backend).
            self.player.reload_preserving_state()
        if announce:
            self._show_osd(f"Desentrelazado: {choice_label(DEINTERLACE_LABELS, self.player.get_deinterlace())}")

    def _on_normalize_toggled(self, checked: bool):
        if not self.player.set_volume_normalization(checked) and checked:
            self.act_normalize_volume.blockSignals(True)
            self.act_normalize_volume.setChecked(False)
            self.act_normalize_volume.blockSignals(False)
            self.statusBar().showMessage("No se pudo activar el normalizador de volumen", 5000)

    # ------------------------------------------------------------ tema
    def _apply_theme(self, key: str):
        theme.apply_theme(QApplication.instance(), key)
        self._refresh_icons()

    # ------------------------------------------------------------ fullscreen
    def toggle_fullscreen(self):
        self.fullscreen.toggle()

    def _exit_fullscreen(self):
        self.fullscreen.exit()

    def _on_fullscreen_entered(self):
        self._set_action_icon(self.act_fullscreen, "fullscreen_exit")
        self.update_ui()

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and obj is getattr(self, "playlist_view", None)
            and playlist_owns_key(event)
        ):
            # Aceptar el ShortcutOverride hace que Qt entregue la tecla al
            # widget enfocado en vez de disparar el QShortcut de ventana
            # (flecha arriba/abajo = volumen): con la playlist enfocada las
            # flechas mueven la seleccion.
            event.accept()
            return True
        if (
            obj is getattr(self, "playlist_filter", None)
            and event.type() == QEvent.Type.ShortcutOverride
            and filter_owns_key(event)
        ):
            # Escribir en el buscador: letras, Espacio, flechas, Supr,
            # Inicio, Ctrl+C/V... son del campo de texto, no atajos del
            # reproductor (Ctrl+Flecha, Ctrl+O, F1... siguen siendo atajos).
            if event.key() == Qt.Key.Key_Escape and self.playlist_filter.text():
                self.playlist_filter.clear()
            event.accept()
            return True
        if event.type() == QEvent.Type.MouseMove and self.isFullScreen():
            self.fullscreen.on_mouse_activity()
        if obj is self.video_frame and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            # Cambia el area de video sin que se mueva/redimensione la
            # ventana (p. ej. al mostrar/ocultar la lista).
            self._reposition_overlays()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_overlays()

    def _on_always_on_top_toggled(self, checked: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    # ------------------------------------------------------------ drag & drop
    # ------------------------------------------------------------ misc
    def closeEvent(self, event):
        if getattr(self, "_closed", False):
            super().closeEvent(event)
            return
        self._closed = True
        if getattr(self, "system_media", None) is not None:
            self.system_media.close()
        if getattr(self, "taskbar_buttons", None) is not None:
            self.taskbar_buttons.close()
        if getattr(self, "renderer_discovery", None) is not None:
            self.renderer_discovery.close()
        for worker in list(getattr(self, "_web_workers", ())):
            worker.wait(2000)
        # Salir de pantalla completa antes de guardar: saveGeometry()/
        # saveState() en pantalla completa guardarian esa ventana (y el dock
        # oculto), y la proxima vez arrancaria asi.
        self._exit_fullscreen()
        self._save_current_position()
        self.save_settings_now()
        self.save_session_now()
        self.timer.stop()
        # Eventos de libVLC que lleguen encolados ya no deben tocar nada.
        self.player.events.blockSignals(True)
        for timer in (self._ab_timer, self._stall_timer):
            timer.stop()
        self.cancel_folder_scan()
        if self._folder_scan_thread is not None:
            self._folder_scan_thread.quit()
            self._folder_scan_thread.wait(3000)
        self.preview.stop_timers()
        # Los hilos de subtitulos que sigan en marcha no deben destruirse
        # corriendo (error fatal de Qt): se espera un poco a que terminen.
        wait_for_subtitle_jobs(3000)
        self.playlist.close()
        # Liberar libVLC (vout y salida de audio) antes de que Qt destruya
        # los widgets nativos donde dibuja.
        self.player.close()
        self.preview.close()
        self._hide_overlays()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            try:
                app.applicationStateChanged.disconnect(self._on_application_state_changed)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)
