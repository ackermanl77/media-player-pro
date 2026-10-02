import logging
import os
import subprocess
import sys

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, theme
from .backend import FINISHED_STATES, MediaInfoProbe, PlaybackState, VLCPlayer, libvlc_version
from .bookmarks import add_bookmark, get_bookmarks
from .bookmarks_dialog import BookmarksDialog
from .equalizer_dialog import EqualizerDialog  # noqa: F401 -- reexportado (pruebas)
from .formats import (
    build_open_filter,
    format_rate,
    format_time,
    is_audio_file,
    is_url,
    normalize_path,
    parse_time_input,
    path_key,
    snapshot_file_name,
)
from .inputs import expand_inputs, filter_dropped, natural_sort_key, read_playlist_file, scan_folder
from .logs import current_log_dir
from .m3u import format_m3u
from .playlist_order import PlaylistOrder, playback_failed
from .power import POWER_ACTIONS, PowerCountdownDialog, run_power_action
from .preview import (
    CAPTURE_POLL_MS,
    CAPTURE_TIMEOUT_MS,
    IDLE_RELEASE_MS,
    ThumbnailCache,
    new_snapshot_path,
    remove_quietly,
)
from .recent_files import add_recent_file, clear_recent_files, get_recent_files
from .resume import clear_position, get_saved_position_ms, save_position
from .settings import (
    MAX_RATE,
    MAX_VOLUME,
    MIN_RATE,
    RATE_STEP,
    REPEAT_MODES,
    SPEEDS,
    Session,
    Settings,
    clamp_rate,
    load_session,
    load_settings,
    save_session,
    save_settings,
)
from .subtitle_dialog import OnlineSubtitleDialog, wait_for_subtitle_jobs
from .url_dialog import OpenUrlDialog
from .widgets import (  # noqa: F401 -- osd_rect/floating_controls_rect/playlist_owns_key reexportados
    MARKER_BOOKMARK,
    MARKER_CHAPTER,
    MARKER_LOOP,
    FullscreenController,
    OverlayWindow,
    PlaylistWidget,
    PositionSlider,
    VideoFrame,
    floating_controls_rect,
    osd_rect,
    playlist_owns_key,
)

log = logging.getLogger(__name__)

DEFAULT_WINDOW_SIZE = (1150, 720)
SESSION_SAVE_DELAY_MS = 1000
UI_TICK_MS = 500          # etiquetas y barra; las transiciones llegan por eventos
AB_LOOP_TICK_MS = 50      # mientras hay un tramo A-B activo
STREAM_STALL_TIMEOUT_MS = 15_000
STREAM_VISUALIZER_DELAY_MS = 1500
METADATA_BATCH = 4
REPEAT_LABELS = {"none": "No repetir", "all": "Repetir todo", "one": "Repetir uno"}
AUDIO_DELAY_STEP_MS = 50
FULLSCREEN_CONTROLLER_MAX_WIDTH = 960
FULLSCREEN_CONTROLLER_MARGIN = 24
ITEM_ID_ROLE = Qt.ItemDataRole.UserRole + 1


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


class MainWindow(QMainWindow):
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
        # Fila de la sesion restaurada que estaba sonando al cerrar: se
        # selecciona pero no se reproduce sola; Reproducir la retoma (y
        # resume.py la posicion). -1 = ninguna.
        self._session_row = -1
        self.current_index = -1
        self.dragging_slider = False
        self.repeat_mode = "none"  # none | one | all
        self.order = PlaylistOrder()
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
        self._dock_was_visible = True
        self.equalizer_dialog = None
        self.bookmarks_dialog = None
        self.loop_point_a = None
        self.loop_point_b = None
        self.on_finish_action = "none"
        self._power_dialog = None
        # Datos por entrada de la lista (claves = path_key): duracion
        # conocida, (artista, titulo) y titulo ICY de las radios.
        self._known_durations = {}
        self._known_tags = {}
        self._icy_titles = {}
        self._next_item_id = 0
        self._row_ids = []
        # Subtitulos descargados para un archivo que ya no era el actual:
        # se cargan la proxima vez que se abra (ver _on_online_subtitle_ready).
        self._pending_subtitles = {}
        self._stream_visualizer_gen = -1
        self._stall_time_ms = 0
        self._stall_box = None

        # Duraciones y etiquetas en segundo plano (ver _probe_next_metadata).
        self._metadata_queue = []
        self._metadata_probe = MediaInfoProbe(self._on_metadata_parsed)
        self._metadata_timer = QTimer(self)
        self._metadata_timer.setSingleShot(True)
        self._metadata_timer.setInterval(200)
        self._metadata_timer.timeout.connect(self._probe_next_metadata)

        # Vista previa en miniatura al pasar el mouse por la barra de
        # progreso (ver _on_slider_hovered / _show_hover_preview).
        self._preview_popup = None
        self._preview_video_widget = None
        self._pending_hover_fraction = None
        self._pending_hover_pos = None
        self._preview_hover_timer = QTimer(self)
        self._preview_hover_timer.setSingleShot(True)
        self._preview_hover_timer.setInterval(300)  # debounce: espera a que el mouse se detenga
        self._preview_hover_timer.timeout.connect(self._show_hover_preview)
        self._preview_snapshot_path = new_snapshot_path()
        self._thumbnail_cache = ThumbnailCache()
        self._capture_attempts = 0
        self._capture_request = None  # (ruta, fraccion) que se esta capturando
        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(CAPTURE_POLL_MS)
        self._capture_timer.timeout.connect(self._poll_hover_snapshot)
        self._preview_idle_timer = QTimer(self)
        self._preview_idle_timer.setSingleShot(True)
        self._preview_idle_timer.setInterval(IDLE_RELEASE_MS)
        self._preview_idle_timer.timeout.connect(self.player.release_preview_player)

        # OSD (on-screen display) transitoria sobre el video -- ver _show_osd.
        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.setInterval(1500)

        # Controlador de pantalla completa -- ver _on_fullscreen_mouse_activity.
        self._fullscreen_idle_timer = QTimer(self)
        self._fullscreen_idle_timer.setSingleShot(True)
        self._fullscreen_idle_timer.setInterval(2500)
        self._fullscreen_idle_timer.timeout.connect(self._hide_floating_controls)
        self._status_bar_was_visible = True

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

        self._extra_shortcuts = []  # (descripcion, QKeySequence) de los QShortcut
        self._build_actions()
        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._register_shortcut_actions()
        self._refresh_icons()

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
        self.video_frame.mouseMoved.connect(self._on_fullscreen_mouse_activity)

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
        return s

    def save_settings_now(self) -> bool:
        self.settings = self.current_settings()
        return save_settings(self.settings)

    def _open_dir(self) -> str:
        """Carpeta inicial de los dialogos de abrir/guardar: la ultima usada
        si todavia existe."""
        folder = self.settings.last_open_dir
        return folder if folder and os.path.isdir(folder) else ""

    def _remember_dir(self, path: str):
        if path:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            if folder:
                self.settings.last_open_dir = folder

    # -- sesion (playlist) -----------------------------------------------
    def playlist_entries(self) -> list:
        return [
            self.playlist_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.playlist_widget.count())
        ]

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
            self.playlist_widget.setCurrentRow(session.current_index)
        # Recien restaurada, la sesion en disco ya es identica.
        self._session_save_timer.stop()

    # ------------------------------------------------------------ acciones
    def _action(self, text, slot=None, shortcut=None, checkable=False, tooltip=None, name=None):
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        if tooltip:
            action.setToolTip(tooltip)
        if slot is not None:
            action.triggered.connect(slot)
        if name:
            action.setObjectName(name)
        return action

    def _build_actions(self):
        """Acciones compartidas por menus, botones (setDefaultAction), menu
        contextual del video y controlador de pantalla completa: una sola
        fuente para texto, atajo y estado (marcado/no marcado)."""
        A = self._action
        self.act_play_pause = A("Reproducir/Pausar", self.toggle_play_pause, "Space",
                                tooltip="Reproducir/Pausar (Espacio)", name="play_pause")
        self.act_stop = A("Detener", self.stop, "S", tooltip="Detener (S)", name="stop")
        self.act_next = A("Pista siguiente", lambda: self.play_next(auto=False), "Ctrl+Right",
                          tooltip="Pista siguiente (Ctrl+Derecha)", name="next")
        self.act_prev = A("Pista anterior", self.play_previous, "Ctrl+Left",
                          tooltip="Pista anterior (Ctrl+Izquierda)", name="previous")
        self.act_mute = A("Silenciar", self.toggle_mute, "M", checkable=True, tooltip="Silenciar (M)", name="mute")
        self.act_fullscreen = A("Pantalla completa", self.toggle_fullscreen, "F",
                                tooltip="Pantalla completa (F)", name="fullscreen")
        self.act_shuffle = A("Aleatorio", None, checkable=True,
                             tooltip="Reproducir la lista en orden aleatorio", name="shuffle")
        self.act_shuffle.toggled.connect(self._on_shuffle_toggled)
        self.act_repeat_cycle = A("Cambiar modo de repetición", self._cycle_repeat_mode,
                                  tooltip="Cicla entre No repetir / Repetir todo / Repetir uno", name="repeat")
        self.act_ab_loop = A("Bucle A-B", self._on_ab_loop_clicked, name="ab_loop",
                             tooltip="Marca un punto A, luego un punto B: repite en bucle solo ese tramo. "
                                     "Un tercer clic lo desactiva.")

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

        self.controls_bar = self._build_controls_bar()
        self._enable_mouse_tracking_recursive(self.controls_bar)
        central_layout.addWidget(self.controls_bar)

        # Controlador de pantalla completa: ventana superpuesta propia con
        # un diseno dedicado (ver FullscreenController).
        self._controls_overlay = OverlayWindow(self)
        self.fullscreen_controller = FullscreenController(
            [("previous", self.act_prev), ("play", self.act_play_pause), ("stop", self.act_stop),
             ("next", self.act_next), (None, None), ("mute", self.act_mute), (None, None),
             ("fullscreen", self.act_fullscreen)],
            self._controls_overlay,
        )
        self._controls_overlay.layout().addWidget(self.fullscreen_controller)
        fs_slider = self.fullscreen_controller.slider
        fs_slider.sliderPressed.connect(self._on_slider_pressed)
        fs_slider.sliderReleased.connect(lambda: self._on_slider_released(fs_slider))
        fs_slider.hovered.connect(self._on_slider_hovered)
        fs_slider.hoverEnded.connect(self._on_slider_hover_ended)

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

        self.position_slider.hovered.connect(self._on_slider_hovered)
        self.position_slider.hoverEnded.connect(self._on_slider_hover_ended)

        # Playlist dock: buscador arriba, lista reordenable debajo.
        self.playlist_widget = PlaylistWidget()
        # itemActivated cubre doble clic Y Enter/Return sobre el item enfocado.
        self.playlist_widget.itemActivated.connect(
            lambda item: self.play_index(self.playlist_widget.row(item))
        )
        self.playlist_widget.reordered.connect(self._sync_after_reorder)
        self.playlist_widget.installEventFilter(self)
        QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self.playlist_widget,
            activated=self.remove_selected_from_playlist,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        self.playlist_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(self.show_playlist_context_menu)
        self.playlist_widget.setAccessibleName("Lista de reproducción")

        self.playlist_filter = QLineEdit()
        self.playlist_filter.setPlaceholderText("Buscar en la lista (Ctrl+F)")
        self.playlist_filter.setClearButtonEnabled(True)
        self.playlist_filter.setAccessibleName("Buscar en la lista")
        self.playlist_filter.textChanged.connect(self._apply_playlist_filter)
        self.playlist_filter.returnPressed.connect(self._play_first_filtered)
        self.playlist_filter.installEventFilter(self)

        dock_body = QWidget()
        dock_layout = QVBoxLayout(dock_body)
        dock_layout.setContentsMargins(4, 4, 4, 4)
        dock_layout.setSpacing(4)
        dock_layout.addWidget(self.playlist_filter)
        dock_layout.addWidget(self.playlist_widget, stretch=1)

        self.playlist_dock = QDockWidget("Lista de reproducción", self)
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

    def _build_menu(self):
        menubar = self.menuBar()
        A = self._action

        # -- Archivo --
        menu_file = menubar.addMenu("&Archivo")
        menu_file.addAction(A("Abrir archivos...", self.open_files, QKeySequence.StandardKey.Open))
        menu_file.addAction(A("Abrir carpeta...", self.open_folder))
        menu_file.addAction(A("Abrir URL...", self.open_url, "Ctrl+U"))
        self.menu_recent_files = menu_file.addMenu("Abrir reciente")
        self.menu_recent_files.aboutToShow.connect(self._populate_recent_files_menu)
        menu_file.addSeparator()
        menu_file.addAction(A("Guardar lista (.m3u8)...", self.save_playlist))
        menu_file.addAction(A("Cargar lista...", self.load_playlist))

        self.act_restore_session = A(
            "Recordar la lista al cerrar", checkable=True,
            tooltip="Al volver a abrir el programa, restaura la lista de reproducción y el elemento actual",
        )
        self.act_restore_session.setChecked(True)
        self.act_restore_session.toggled.connect(lambda _checked: self._schedule_session_save())
        menu_file.addAction(self.act_restore_session)
        self.act_allow_multiple_windows = A(
            "Permitir varias ventanas", checkable=True,
            tooltip="Si está desmarcado, abrir un archivo con el programa ya abierto lo agrega a esa ventana",
        )
        menu_file.addAction(self.act_allow_multiple_windows)
        menu_file.addSeparator()
        menu_file.addAction(A("Salir", self.close, QKeySequence.StandardKey.Quit))

        # -- Reproducción --
        menu_playback = menubar.addMenu("&Reproducción")
        for action in (self.act_play_pause, self.act_stop, self.act_next, self.act_prev):
            menu_playback.addAction(action)
        act_next_frame = A("Avanzar un fotograma", self.step_frame, ".",
                           tooltip="Avanza un solo fotograma (el video debe estar en pausa)")
        menu_playback.addAction(act_next_frame)
        menu_playback.addAction(A("Ir a tiempo...", self.jump_to_time, "Ctrl+G"))
        menu_playback.addAction(A("Volver al inicio", lambda: self._seek_to(0), "Home"))
        menu_playback.addSeparator()

        self.menu_speed = menu_playback.addMenu("Velocidad")
        self.speed_group = QActionGroup(self)
        self.speed_group.setExclusive(True)
        for value in SPEEDS:
            action = QAction(format_rate(value), self, checkable=True)
            action.setData(value)
            action.triggered.connect(lambda _checked, v=value: self._set_rate(v))
            self.speed_group.addAction(action)
            self.menu_speed.addAction(action)
        self.menu_speed.addSeparator()
        self.menu_speed.addAction(A("Más lenta", lambda: self._nudge_rate(-RATE_STEP), "["))
        self.menu_speed.addAction(A("Más rápida", lambda: self._nudge_rate(RATE_STEP), "]"))
        self.menu_speed.addAction(A("Velocidad normal", lambda: self._set_rate(1.0), "="))
        self.speed_button.setMenu(self.menu_speed)

        menu_playback.addAction(self.act_shuffle)
        self.menu_repeat = menu_playback.addMenu("Repetir")
        self.repeat_group = QActionGroup(self)
        self.repeat_group.setExclusive(True)
        for mode in REPEAT_MODES:
            action = QAction(REPEAT_LABELS[mode], self, checkable=True)
            action.setData(mode)
            action.triggered.connect(lambda _checked, m=mode: self._set_repeat_mode(m))
            self.repeat_group.addAction(action)
            self.menu_repeat.addAction(action)
        menu_playback.addAction(self.act_ab_loop)

        self.menu_chapters = menu_playback.addMenu("Capítulos")
        self.menu_chapters.aboutToShow.connect(self._populate_chapters_menu)
        self.act_prev_chapter = A("Capítulo anterior", self.previous_chapter, "PgUp")
        self.act_next_chapter = A("Capítulo siguiente", self.next_chapter, "PgDown")
        menu_playback.addAction(self.act_prev_chapter)
        menu_playback.addAction(self.act_next_chapter)

        menu_playback.addSeparator()

        self.menu_on_finish = menu_playback.addMenu("Al terminar la lista")
        self.on_finish_group = QActionGroup(self.menu_on_finish)
        self.on_finish_group.setExclusive(True)
        on_finish_options = [("Nada", "none"), ("Salir del programa", "exit")]
        if sys.platform.startswith("win"):
            # Apagar/Hibernar/Reiniciar usan shutdown.exe, especifico de Windows.
            on_finish_options += [
                ("Apagar el equipo", "shutdown"),
                ("Hibernar", "hibernate"),
                ("Reiniciar", "restart"),
            ]
        for label, key in on_finish_options:
            action = QAction(label, self.menu_on_finish, checkable=True)
            action.setData(key)
            action.setChecked(key == "none")
            action.triggered.connect(lambda _checked, k=key: setattr(self, "on_finish_action", k))
            self.on_finish_group.addAction(action)
            self.menu_on_finish.addAction(action)

        menu_playback.addSeparator()
        menu_playback.addAction(A("Agregar marcador aquí", self.quick_add_bookmark, "B"))
        menu_playback.addAction(A("Ver marcadores...", self.show_bookmarks))

        # -- Audio --  (A&udio: "&Archivo" ya usa Alt+A)
        menu_audio = menubar.addMenu("A&udio")
        menu_audio.addAction(self.act_mute)
        menu_audio.addAction(A("Ecualizador...", self.open_equalizer))
        self.act_visualizer = A("Visualizador de audio (espectro)", checkable=True)
        self.act_visualizer.setChecked(True)
        menu_audio.addAction(self.act_visualizer)
        self.menu_audio_tracks = menu_audio.addMenu("Pista de audio")
        self.menu_audio_tracks.aboutToShow.connect(self._populate_audio_track_menu)
        menu_audio.addSeparator()
        menu_audio.addAction(A("Adelantar audio 50 ms", lambda: self._adjust_audio_delay(-AUDIO_DELAY_STEP_MS), "J"))
        menu_audio.addAction(A("Retrasar audio 50 ms", lambda: self._adjust_audio_delay(AUDIO_DELAY_STEP_MS), "K"))
        menu_audio.addAction(A("Restablecer sincronía de audio", lambda: self._set_audio_delay(0)))

        # -- Video --
        menu_video = menubar.addMenu("&Video")
        menu_video.addAction(self.act_fullscreen)
        menu_video.addAction(A("Capturar fotograma...", self.take_snapshot))
        menu_video.addAction(A("Captura rápida", self.quick_snapshot, "Ctrl+Shift+S",
                               tooltip="Guarda una captura en Imágenes\\Reproductor Multimedia Pro"))
        menu_video.addSeparator()

        self.menu_subtitle_tracks = menu_video.addMenu("Pista de subtítulos")
        self.menu_subtitle_tracks.aboutToShow.connect(self._populate_subtitle_track_menu)
        menu_video.addAction(A("Cargar subtítulo externo...", self.load_subtitle_file))
        menu_video.addAction(A("Buscar subtítulos online...", self.search_subtitles_online))
        menu_video.addAction(A("Adelantar subtítulos 50 ms", lambda: self._adjust_subtitle_delay(-50), "G"))
        menu_video.addAction(A("Retrasar subtítulos 50 ms", lambda: self._adjust_subtitle_delay(50), "H"))
        menu_video.addAction(A("Restablecer sincronía de subtítulos", lambda: self._set_subtitle_delay(0)))

        self.menu_sub_size = menu_video.addMenu("Tamaño de subtítulos")
        sub_size_group = QActionGroup(self.menu_sub_size)
        sub_size_group.setExclusive(True)
        for label, scale in (("Pequeño", 75), ("Normal", 100), ("Grande", 150), ("Muy grande", 200)):
            action = QAction(label, self.menu_sub_size, checkable=True)
            action.setData(scale)
            action.setChecked(scale == 100)
            action.triggered.connect(lambda _checked, s=scale: self._on_subtitle_scale_changed(s))
            sub_size_group.addAction(action)
            self.menu_sub_size.addAction(action)

        menu_video.addSeparator()

        self.menu_zoom = menu_video.addMenu("Zoom")
        zoom_group = QActionGroup(self.menu_zoom)
        zoom_group.setExclusive(True)
        for label, factor in (
            ("Ajustar a ventana", 0.0), ("50%", 0.5), ("100%", 1.0), ("150%", 1.5), ("200%", 2.0),
        ):
            action = QAction(label, self.menu_zoom, checkable=True)
            action.setData(factor)
            action.setChecked(factor == 0.0)
            action.triggered.connect(lambda _checked, f=factor: self.player.set_video_scale(f))
            zoom_group.addAction(action)
            self.menu_zoom.addAction(action)

        self.menu_gpu = None
        if sys.platform.startswith("win"):
            self._build_gpu_menu(menu_video)

        # -- Ver --
        menu_view = menubar.addMenu("&Ver")
        act_toggle_playlist = self.playlist_dock.toggleViewAction()
        act_toggle_playlist.setText("Mostrar lista de reproducción")
        menu_view.addAction(act_toggle_playlist)
        self.act_remaining_time = A("Mostrar tiempo restante", lambda _c=False: self.update_ui(), checkable=True,
                                    tooltip="En vez de la duración total (también con clic sobre ella)")
        menu_view.addAction(self.act_remaining_time)
        self.act_always_on_top = A("Siempre visible (encima de otras ventanas)", checkable=True)
        self.act_always_on_top.toggled.connect(self._on_always_on_top_toggled)
        menu_view.addAction(self.act_always_on_top)
        self.menu_theme = menu_view.addMenu("Tema")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        for key, label in theme.THEME_LABELS.items():
            action = QAction(label, self, checkable=True)
            action.setData(key)
            action.setChecked(key == "system")
            action.triggered.connect(lambda _checked, k=key: self._apply_theme(k))
            self.theme_group.addAction(action)
            self.menu_theme.addAction(action)

        # -- Ayuda --
        menu_help = menubar.addMenu("A&yuda")
        menu_help.addAction(A("Atajos de teclado...", self.show_shortcuts_help, "F1"))
        menu_help.addAction(A("Abrir carpeta de registros", self.open_log_folder,
                              tooltip="Registro de errores del programa (útil para reportar un problema)"))
        menu_help.addAction(A("Acerca de...", self.show_about))

        # Menu contextual del video: las mismas acciones y submenus.
        self.video_context_menu = QMenu(self)
        for item in (self.act_play_pause, self.act_stop, self.act_prev, self.act_next, None,
                     self.act_fullscreen, None, self.menu_speed, self.menu_chapters, self.menu_audio_tracks,
                     self.menu_subtitle_tracks, self.menu_zoom, None, self.act_always_on_top):
            if item is None:
                self.video_context_menu.addSeparator()
            elif isinstance(item, QMenu):
                self.video_context_menu.addMenu(item)
            else:
                self.video_context_menu.addAction(item)

    def _build_gpu_menu(self, menu_video):
        self.menu_gpu = menu_video.addMenu("Mejora por GPU")
        self.act_gpu_upscale = self._action(
            "Superresolución (RTX Video / Intel)", checkable=True,
            tooltip="Solo actúa cuando el video se agranda (ventana más grande que el video). Requiere "
                    "\"RTX Video Enhancement\" activado en el Panel de control de NVIDIA y la salida Direct3D11.",
        )
        self.act_gpu_hdr = self._action(
            "HDR a partir de SDR (RTX Video HDR)", checkable=True,
            tooltip="Requiere HDR activado en la configuración de pantalla de Windows y una GPU compatible.",
        )
        self.menu_gpu.setToolTipsVisible(True)
        for action in (self.act_gpu_upscale, self.act_gpu_hdr):
            action.toggled.connect(lambda _checked: self._on_gpu_options_changed())
            self.menu_gpu.addAction(action)
        self.menu_gpu.addSeparator()
        self.menu_hw_decoding = self.menu_gpu.addMenu("Decodificación por hardware")
        self.hw_decoding_group = QActionGroup(self)
        self.hw_decoding_group.setExclusive(True)
        for label, key in (("Automática", "any"), ("D3D11VA", "d3d11va"), ("DXVA2", "dxva2"), ("Desactivada", "none")):
            action = QAction(label, self, checkable=True)
            action.setData(key)
            action.setChecked(key == "any")
            action.triggered.connect(lambda _checked: self._on_gpu_options_changed())
            self.hw_decoding_group.addAction(action)
            self.menu_hw_decoding.addAction(action)

    def _register_shortcut_actions(self):
        """Casi todos los atajos viven en QActions de los menus. Qt solo
        activa el atajo de un QAction si alguno de sus widgets asociados
        esta visible, y en pantalla completa la barra de menus se oculta:
        agregarlos tambien a la propia ventana los mantiene activos siempre;
        es el mismo QAction, asi que no se duplica ni se vuelve ambiguo."""
        for action in self.findChildren(QAction):
            if not action.shortcut().isEmpty() and action not in self.actions():
                self.addAction(action)

    def _add_shortcut(self, key, description, slot):
        sequence = QKeySequence(key)
        QShortcut(sequence, self, activated=slot)
        self._extra_shortcuts.append((description, sequence))

    def _build_shortcuts(self):
        S = self._add_shortcut
        S(Qt.Key.Key_Escape, "Salir de pantalla completa", self._exit_fullscreen)
        S(Qt.Key.Key_Right, "Adelantar 5 s", lambda: self._seek_relative(5000))
        S(Qt.Key.Key_Left, "Retroceder 5 s", lambda: self._seek_relative(-5000))
        S("Shift+Right", "Adelantar 1 s", lambda: self._seek_relative(1000))
        S("Shift+Left", "Retroceder 1 s", lambda: self._seek_relative(-1000))
        S("Alt+Right", "Adelantar 30 s", lambda: self._seek_relative(30_000))
        S("Alt+Left", "Retroceder 30 s", lambda: self._seek_relative(-30_000))
        S("Ctrl+Alt+Right", "Adelantar 60 s", lambda: self._seek_relative(60_000))
        S("Ctrl+Alt+Left", "Retroceder 60 s", lambda: self._seek_relative(-60_000))
        S(Qt.Key.Key_Up, "Subir volumen", lambda: self._nudge_volume(5))
        S(Qt.Key.Key_Down, "Bajar volumen", lambda: self._nudge_volume(-5))
        # Teclas multimedia del teclado (Windows las manda como WM_APPCOMMAND
        # a la ventana activa).
        S(Qt.Key.Key_MediaTogglePlayPause, "Tecla multimedia Reproducir/Pausar", self.toggle_play_pause)
        S(Qt.Key.Key_MediaPlay, "Tecla multimedia Reproducir", self._media_key_play)
        S(Qt.Key.Key_MediaPause, "Tecla multimedia Pausa", self._media_key_pause)
        S(Qt.Key.Key_MediaStop, "Tecla multimedia Detener", self.stop)
        S(Qt.Key.Key_MediaNext, "Tecla multimedia Siguiente", lambda: self.play_next(auto=False))
        S(Qt.Key.Key_MediaPrevious, "Tecla multimedia Anterior", self.play_previous)

    def shortcut_rows(self) -> list:
        """(descripcion, atajo) de todo lo que tiene atajo de teclado, tal
        como esta registrado (para Ayuda -> Atajos de teclado)."""
        rows = []
        for action in self.actions():
            if not action.shortcut().isEmpty():
                text = action.text().replace("&", "")
                rows.append((text, action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)))
        for description, sequence in self._extra_shortcuts:
            rows.append((description, sequence.toString(QKeySequence.SequenceFormat.NativeText)))
        rows.append(("Buscar en la lista (con la lista enfocada)", QKeySequence(QKeySequence.StandardKey.Find)
                     .toString(QKeySequence.SequenceFormat.NativeText)))
        rows.append(("Quitar de la lista (con la lista enfocada)", "Supr"))
        rows.append(("Volumen / buscar ±5 s", "Rueda / Ctrl+Rueda sobre el video"))
        rows.append(("Pantalla completa", "Doble clic sobre el video"))
        return rows

    def show_shortcuts_help(self):
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle("Atajos de teclado")
        dialog.resize(520, 560)
        layout = QVBoxLayout(dialog)
        rows = self.shortcut_rows()
        table = QTableWidget(len(rows), 2, dialog)
        table.setHorizontalHeaderLabels(["Acción", "Atajo"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, (text, keys) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(text))
            table.setItem(row, 1, QTableWidgetItem(keys))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)
        close = QPushButton("Cerrar")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.shortcuts_dialog = dialog
        dialog.show()

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
        self._maybe_schedule_stream_visualizer(gen)

    def _on_buffering(self, gen: int, percent: float):
        if not self._is_current_gen(gen):
            return
        path = self._current_path_or_none()
        if path is None or not is_url(path):
            return  # los archivos locales tambien "almacenan", sin interes
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

    def _on_chapter_changed(self, gen: int, chapter: int):
        if not self._is_current_gen(gen):
            return
        chapters = self._current_chapters()
        if 0 <= chapter < len(chapters) and chapters[chapter][2]:
            self._show_osd(f"Capítulo: {chapters[chapter][2]}")

    def _on_tracks_changed(self, gen: int):
        if self._is_current_gen(gen):
            self._chapters_cache = None
            self._maybe_schedule_stream_visualizer(gen)

    def _on_meta_changed(self, gen: int):
        if not self._is_current_gen(gen):
            return
        path = self._current_path_or_none()
        if path is None or not is_url(path):
            return
        title = self.player.now_playing()
        if title and self._icy_titles.get(path) != title:
            self._icy_titles[path] = title
            self._refresh_item(self.current_index)
            self.setWindowTitle(f"Reproductor Multimedia Pro — {title}")

    def _on_snapshot_taken(self, filename: str):
        if getattr(self, "_quick_snapshot_pending", None):
            self._quick_snapshot_pending = None
            self._show_osd("Captura guardada")
            self.statusBar().showMessage(f"Captura guardada: {filename}", 5000)

    def _update_play_icon(self):
        playing = self.player.media_player is not None and self.player.is_playing()
        self._set_action_icon(self.act_play_pause, "pause" if playing else "play")

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

    def _show_stall_prompt(self, path: str):
        if self._stall_box is not None:
            return
        box = QMessageBox(QMessageBox.Icon.Warning, "Stream sin respuesta",
                          f"No responde: {self._display_name(path)}", parent=self)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        retry = box.addButton("Reintentar", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Saltar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Seguir esperando", QMessageBox.ButtonRole.RejectRole)
        row = self.current_index

        def _done(_result):
            clicked = box.clickedButton()
            self._stall_box = None
            if self.current_index != row:
                return
            if clicked is retry:
                self.play_index(row)
            elif clicked is skip:
                self.play_next(auto=False)
            else:
                self._stall_time_ms = self.player.get_time_ms()
                self._stall_timer.start()

        box.finished.connect(_done)
        self._stall_box = box
        box.open()
        self.statusBar().showMessage(f"No responde: {self._display_name(path)}")

    # ------------------------------------------------------------ playlist
    def _display_name(self, path: str) -> str:
        if is_url(path):
            return f"🌐 {path}"
        prefix = "🎵" if is_audio_file(path) else "🎬"
        return f"{prefix} {os.path.basename(path)}"

    def _entry_label(self, path: str) -> str:
        """Texto de una entrada: "Artista — Titulo" si el archivo trae
        etiquetas, el titulo ICY para una radio, si no el nombre."""
        if is_url(path):
            title = self._icy_titles.get(path)
            return f"🌐 {title}" if title else f"🌐 {path}"
        tags = self._known_tags.get(path_key(path))
        if tags:
            artist, title = tags
            prefix = "🎵" if is_audio_file(path) else "🎬"
            return f"{prefix} {artist} — {title}" if artist else f"{prefix} {title}"
        return self._display_name(path)

    def _refresh_item(self, row: int):
        item = self.playlist_widget.item(row)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        text = self._entry_label(path)
        duration = self._known_durations.get(path_key(path))
        if duration:
            text = f"{text} — {format_time(duration)}"
        if row == self.current_index:
            text = f"▶ {text}"
        item.setText(text)
        item.setToolTip(path)
        font = item.font()
        if font.bold() != (row == self.current_index):
            font.setBold(row == self.current_index)
            item.setFont(font)

    def _refresh_all_items(self):
        for row in range(self.playlist_widget.count()):
            self._refresh_item(row)
        self._update_dock_title()

    def _set_current_index(self, index: int):
        """Cambia la fila actual y mueve el marcador ▶ (independiente de la
        seleccion: antes la fila en reproduccion solo se veia como
        seleccionada, y se perdia al hacer clic en otra)."""
        old, self.current_index = self.current_index, index
        if old != index:
            self._refresh_item(old)
        self._refresh_item(index)

    def _update_dock_title(self):
        count = self.playlist_widget.count()
        if count == 0:
            self.playlist_dock.setWindowTitle("Lista de reproducción")
            return
        total = sum(self._known_durations.get(path_key(p), 0) for p in self.playlist_entries())
        suffix = f" — {format_time(total)}" if total else ""
        noun = "elemento" if count == 1 else "elementos"
        self.playlist_dock.setWindowTitle(f"Lista de reproducción ({count} {noun}){suffix}")

    def add_files_to_playlist(self, paths):
        """Unico punto de entrada a la playlist (dialogos, carpetas, arrastrar
        y soltar, linea de comandos, recientes, .m3u, otra instancia):
        normaliza aqui cada ruta local una sola vez (ver
        formats.normalize_path)."""
        paths = [normalize_path(p) for p in paths]
        for p in paths:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setData(ITEM_ID_ROLE, self._next_item_id)
            self._row_ids.append(self._next_item_id)
            self._next_item_id += 1
            self.playlist_widget.addItem(item)
            self._refresh_item(self.playlist_widget.count() - 1)
            if not is_url(p) and path_key(p) not in self._known_durations:
                self._metadata_queue.append(p)
        self.order.append(len(paths))
        if paths:
            self._schedule_session_save()
            self._apply_playlist_filter(self.playlist_filter.text())
            self._update_dock_title()
            if self._metadata_queue and not self._metadata_timer.isActive():
                self._metadata_timer.start()

    def open_paths(self, paths, play: bool = True) -> int:
        """Agrega lo que el usuario "abrio" (carpetas y .m3u expandidos) y,
        con play=True o si no suena nada, reproduce lo primero agregado.
        Devuelve cuantas entradas se agregaron."""
        entries = expand_inputs(paths)
        if not entries:
            return 0
        start_index = self.playlist_widget.count()
        self.add_files_to_playlist(entries)
        if play or self.current_index == -1:
            self.play_index(start_index)
        return len(entries)

    def handle_instance_message(self, action: str, paths):
        """Mensaje de otra instancia (ver single_instance.py)."""
        added = self.open_paths(paths, play=action == "open")
        if action == "enqueue" and added:
            noun = "elemento agregado" if added == 1 else "elementos agregados"
            self.statusBar().showMessage(f"{added} {noun} a la lista", 4000)
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # -- metadatos en segundo plano ------------------------------------------
    def _probe_next_metadata(self):
        while self._metadata_queue and self._metadata_probe.pending_count() < METADATA_BATCH:
            path = self._metadata_queue.pop(0)
            if path_key(path) in self._known_durations or not os.path.isfile(path):
                continue
            self._metadata_probe.probe(path)
        if self._metadata_queue:
            self._metadata_timer.start()

    def _on_metadata_parsed(self, path: str, duration_ms: int, title: str, artist: str):
        key = path_key(path)
        if duration_ms > 0:
            self._known_durations.setdefault(key, duration_ms)
        stem = os.path.splitext(os.path.basename(path))[0]
        # libVLC usa el nombre del archivo como "titulo" si no hay etiqueta.
        if title and title not in (stem, os.path.basename(path)):
            self._known_tags[key] = (artist, title)
        for row in range(self.playlist_widget.count()):
            if path_key(self.playlist_widget.item(row).data(Qt.ItemDataRole.UserRole)) == key:
                self._refresh_item(row)
        self._update_dock_title()
        if self._metadata_queue and not self._metadata_timer.isActive():
            self._metadata_timer.start()

    # -- buscador y reordenar ----------------------------------------------
    def _focus_playlist_filter(self):
        self.playlist_dock.show()
        self.playlist_filter.setFocus()
        self.playlist_filter.selectAll()

    def _apply_playlist_filter(self, text: str):
        needle = text.strip().casefold()
        for row in range(self.playlist_widget.count()):
            item = self.playlist_widget.item(row)
            haystack = f"{item.text()} {item.data(Qt.ItemDataRole.UserRole)}".casefold()
            item.setHidden(bool(needle) and needle not in haystack)

    def _play_first_filtered(self):
        for row in range(self.playlist_widget.count()):
            if not self.playlist_widget.item(row).isHidden():
                self.play_index(row)
                return

    def _sync_after_reorder(self):
        """La lista cambio de orden (arrastre o "Ordenar"): se reconstruye
        el orden a partir de los ids estables de cada fila, y se actualizan
        el aleatorio, la fila actual y la de la sesion."""
        new_ids = [self.playlist_widget.item(r).data(ITEM_ID_ROLE) for r in range(self.playlist_widget.count())]
        if new_ids == self._row_ids:
            return
        old_row = {item_id: row for row, item_id in enumerate(self._row_ids)}
        new_order = [old_row[i] for i in new_ids]
        self.order.reorder(new_order)
        remap = {old: new for new, old in enumerate(new_order)}
        if self.current_index != -1:
            self.current_index = remap[self.current_index]
        if self._session_row != -1:
            self._session_row = remap[self._session_row]
        self._row_ids = new_ids
        self._refresh_all_items()
        self._schedule_session_save()

    def sort_playlist(self, by: str = "name"):
        def key(item):
            path = item.data(Qt.ItemDataRole.UserRole)
            return natural_sort_key(os.path.basename(path) if by == "name" and not is_url(path) else path)

        items = [self.playlist_widget.takeItem(0) for _ in range(self.playlist_widget.count())]
        items.sort(key=key)
        for item in items:
            self.playlist_widget.addItem(item)
        self._sync_after_reorder()

    def remove_unavailable(self) -> int:
        rows = [
            r for r, p in enumerate(self.playlist_entries())
            if not is_url(p) and not os.path.exists(p)
        ]
        self.remove_rows(rows)
        if rows:
            noun = "entrada no disponible quitada" if len(rows) == 1 else "entradas no disponibles quitadas"
            self.statusBar().showMessage(f"{len(rows)} {noun}", 4000)
        return len(rows)

    # -- abrir ---------------------------------------------------------------
    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Abrir archivos multimedia", self._open_dir(), build_open_filter()
        )
        if not paths:
            return
        self._remember_dir(paths[0])
        start_index = self.playlist_widget.count()
        self.add_files_to_playlist(expand_inputs(paths))
        if self.current_index == -1:
            self.play_index(start_index)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Abrir carpeta", self._open_dir())
        if not folder:
            return
        self._remember_dir(folder)
        found = scan_folder(folder)
        if not found:
            QMessageBox.information(self, "Abrir carpeta", "No se encontraron archivos multimedia soportados.")
            return
        start_index = self.playlist_widget.count()
        self.add_files_to_playlist(found)
        if self.current_index == -1:
            self.play_index(start_index)

    def open_url(self):
        dialog = OpenUrlDialog(self.player.network_caching_ms, self.player.rtsp_tcp, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.player.network_caching_ms = dialog.network_caching_ms()
        self.player.rtsp_tcp = dialog.rtsp_tcp()
        self.add_files_to_playlist([dialog.url()])
        self.play_index(self.playlist_widget.count() - 1)

    def open_recent_file(self, path: str):
        if not is_url(path) and not os.path.exists(path):
            QMessageBox.warning(self, "Archivo reciente", f"No se encontró el archivo:\n{path}")
            return
        start_index = self.playlist_widget.count()
        self.add_files_to_playlist([path])
        self.play_index(start_index)

    def _populate_recent_files_menu(self):
        self.menu_recent_files.clear()
        recent = get_recent_files()
        if not recent:
            empty_action = QAction("(vacío)", self.menu_recent_files)
            empty_action.setEnabled(False)
            self.menu_recent_files.addAction(empty_action)
            return
        for path in recent:
            action = QAction(self._display_name(path), self.menu_recent_files)
            action.triggered.connect(lambda _checked, p=path: self.open_recent_file(p))
            self.menu_recent_files.addAction(action)
        self.menu_recent_files.addSeparator()
        act_clear = QAction("Limpiar lista", self.menu_recent_files)
        act_clear.triggered.connect(clear_recent_files)
        self.menu_recent_files.addAction(act_clear)

    def save_playlist(self):
        if self.playlist_widget.count() == 0:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar lista de reproducción", os.path.join(self._open_dir(), "playlist.m3u8"),
            "Playlist M3U8 (*.m3u8);;Playlist M3U (*.m3u)",
        )
        if not path:
            return
        self._remember_dir(path)
        if not path.lower().endswith((".m3u", ".m3u8")):
            path += ".m3u8"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(format_m3u(self.playlist_entries()))
        except OSError as exc:
            QMessageBox.warning(self, "Guardar lista", f"No se pudo guardar la lista:\n{exc}")

    def load_playlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar lista de reproducción", self._open_dir(), "Playlist (*.m3u *.m3u8);;Todos los archivos (*.*)"
        )
        if not path:
            return
        self._remember_dir(path)
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Cargar lista", f"No se pudo leer la lista:\n{path}")
            return
        entries = read_playlist_file(path)
        if entries:
            start_index = self.playlist_widget.count()
            self.add_files_to_playlist(entries)
            if self.current_index == -1:
                self.play_index(start_index)

    def show_playlist_context_menu(self, pos):
        item = self.playlist_widget.itemAt(pos)
        path = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        menu = QMenu(self)
        act_play = menu.addAction("Reproducir")
        act_remove = menu.addAction("Quitar de la lista")
        menu.addSeparator()
        act_show = menu.addAction("Mostrar en el Explorador" if sys.platform.startswith("win") else "Abrir carpeta")
        act_copy = menu.addAction("Copiar ruta")
        menu.addSeparator()
        menu_sort = menu.addMenu("Ordenar")
        act_sort_name = menu_sort.addAction("Por nombre")
        act_sort_path = menu_sort.addAction("Por ruta")
        act_unavailable = menu.addAction("Quitar entradas no disponibles")
        act_clear = menu.addAction("Vaciar lista")
        for action in (act_play, act_remove, act_copy):
            action.setEnabled(item is not None)
        act_show.setEnabled(path is not None and not is_url(path))
        if item is not None and len(self.playlist_widget.selectedItems()) > 1 and item.isSelected():
            act_remove.setText("Quitar seleccionados de la lista")
        chosen = menu.exec(self.playlist_widget.mapToGlobal(pos))
        if chosen == act_play and item is not None:
            self.play_index(self.playlist_widget.row(item))
        elif chosen == act_remove and item is not None:
            # Clic derecho sobre un item seleccionado quita toda la seleccion;
            # sobre uno no seleccionado, solo ese (como el Explorador).
            if item.isSelected():
                self.remove_selected_from_playlist()
            else:
                self.remove_rows([self.playlist_widget.row(item)])
        elif chosen == act_show and path is not None:
            self.show_in_file_manager(path)
        elif chosen == act_copy and path is not None:
            QGuiApplication.clipboard().setText(path)
        elif chosen == act_sort_name:
            self.sort_playlist("name")
        elif chosen == act_sort_path:
            self.sort_playlist("path")
        elif chosen == act_unavailable:
            self.remove_unavailable()
        elif chosen == act_clear:
            self.clear_playlist()

    def show_in_file_manager(self, path: str):
        if sys.platform.startswith("win") and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def remove_selected_from_playlist(self):
        self.remove_rows([self.playlist_widget.row(i) for i in self.playlist_widget.selectedItems()])

    def remove_rows(self, rows):
        rows = sorted({r for r in rows if 0 <= r < self.playlist_widget.count()})
        if not rows:
            return
        if self.current_index in rows:
            # Guardar ANTES de detener: tras stop() libVLC reporta -1 de
            # tiempo/largo y save_position no guardaria nada.
            self._save_current_position()
            self.player.stop()
            self.player.stop_preview()
            self.current_index = -1
        else:
            self.current_index -= sum(1 for r in rows if r < self.current_index)
        if self._session_row in rows:
            self._session_row = -1
        elif self._session_row != -1:
            self._session_row -= sum(1 for r in rows if r < self._session_row)
        for r in reversed(rows):
            self.playlist_widget.takeItem(r)
            del self._row_ids[r]
        # Si se quito la actual, PlaylistOrder recuerda su fila: Siguiente/
        # Reproducir siguen con la que tomo su lugar (antes volvian a la 1.a).
        self.order.remove(rows)
        self._schedule_session_save()
        self._update_dock_title()

    def clear_playlist(self):
        self._save_current_position()
        self.playlist_widget.clear()
        self._row_ids = []
        self.current_index = -1
        self._session_row = -1
        self.player.stop()
        self.player.stop_preview()
        self.order.reset(0)
        self._schedule_session_save()
        self._update_dock_title()

    # ------------------------------------------------------------ transport
    def play_index(self, index: int, user: bool = True):
        """user=False solo cuando la llama el avance automatico (fin de
        pista o fallo); cualquier eleccion del usuario reinicia el conteo
        de fallos seguidos."""
        item = self.playlist_widget.item(index)
        if item is None:
            return
        self._save_current_position()
        if user:
            self._consecutive_failures = 0
        path = item.data(Qt.ItemDataRole.UserRole)
        self._set_current_index(index)
        self._session_row = -1
        self._schedule_session_save()
        self.order.jump_to(index)
        self._max_time_seen_ms = 0
        self._bookmarks_cache = None
        self._chapters_cache = None
        self._stall_timer.stop()
        if self.player.preview_current_path() not in (None, path):
            self.player.stop_preview()
        self.playlist_widget.setCurrentRow(index)
        self._advancing = False
        self._clear_ab_loop()
        if self.bookmarks_dialog is not None:
            self.bookmarks_dialog.close()
            self.bookmarks_dialog = None
        # La posicion guardada va como :start-time del Media (ver
        # VLCPlayer.load): arranca directo ahi.
        saved_ms = 0 if is_url(path) else (get_saved_position_ms(path) or 0)
        self.player.load(path, enable_visualizer=self.act_visualizer.isChecked(), start_ms=saved_ms)
        pending_sub = self._pending_subtitles.pop(path_key(path), None)
        if pending_sub and os.path.exists(pending_sub):
            self.player.add_subtitle_before_play(pending_sub)
        self.player.attach_video_output(self.video_frame)
        self.player.play()
        self.player.set_rate(self._rate)
        self.setWindowTitle(f"Reproductor Multimedia Pro — {self._display_name(path)}")
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
        save_position(path, self.player.get_time_ms(), self.player.get_length_ms())

    def _current_path_or_none(self):
        item = self.playlist_widget.item(self.current_index) if self.current_index != -1 else None
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def toggle_play_pause(self):
        if self.current_index == -1:
            if self._session_row != -1:
                # Elemento que estaba sonando al cerrar (sesion restaurada).
                self.play_index(self._session_row)
                return
            if self.playlist_widget.count() > 0:
                first = self.order.advance(repeat_all=False)
                self.play_index(first if first is not None else 0)
            return
        if self.player.is_idle():
            # Tras Detener, fin de la lista o un fallo, pause() de libVLC no
            # hace nada: hay que volver a arrancar la pista actual.
            self.play_index(self.current_index)
            return
        self.player.toggle_pause()

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
        count = self.playlist_widget.count()
        if count == 0:
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
            self.loop_point_a = self.player.get_time_ms()
            self.act_ab_loop.setToolTip(f"A: {format_time(self.loop_point_a)} — clic para marcar B")
            self._show_osd(f"Punto A: {format_time(self.loop_point_a)}")
        elif self.loop_point_b is None:
            candidate_b = self.player.get_time_ms()
            if candidate_b <= self.loop_point_a:
                self.statusBar().showMessage("El punto B debe ser posterior al punto A", 3000)
                return
            self.loop_point_b = candidate_b
            text = f"A-B: {format_time(self.loop_point_a)}-{format_time(self.loop_point_b)}"
            self.act_ab_loop.setToolTip(f"{text} — clic para desactivar")
            self.act_ab_loop.setCheckable(True)
            self.act_ab_loop.setChecked(True)
            self._ab_timer.start()
            self._show_osd(text)
        else:
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
        markers = self._position_markers(length_ms)
        self.position_slider.set_markers(markers)
        self.fullscreen_controller.slider.set_markers(markers)

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

    def show_bookmarks(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            QMessageBox.information(self, "Marcadores", "Esta función solo funciona con archivos locales.")
            return
        if self.bookmarks_dialog is not None:
            self.bookmarks_dialog.close()
        self.bookmarks_dialog = BookmarksDialog(self.player, path, self)
        self.bookmarks_dialog.bookmarks_changed.connect(self._invalidate_bookmarks_cache)
        self.bookmarks_dialog.show()

    # -- capitulos -------------------------------------------------------------
    def _populate_chapters_menu(self):
        self.menu_chapters.clear()
        chapters = self._current_chapters()
        if not chapters:
            empty = QAction("(sin capítulos)", self.menu_chapters)
            empty.setEnabled(False)
            self.menu_chapters.addAction(empty)
            return
        current = self.player.get_chapter()
        group = QActionGroup(self.menu_chapters)
        group.setExclusive(True)
        for i, (start, _duration, name) in enumerate(chapters):
            label = f"{i + 1}. {name or 'Capítulo ' + str(i + 1)} ({format_time(start)})"
            action = QAction(label, self.menu_chapters, checkable=True)
            action.setChecked(i == current)
            action.triggered.connect(lambda _checked, idx=i: self.player.set_chapter(idx))
            group.addAction(action)
            self.menu_chapters.addAction(action)

    def next_chapter(self):
        if self.current_index != -1 and self._current_chapters():
            self.player.next_chapter()

    def previous_chapter(self):
        if self.current_index != -1 and self._current_chapters():
            self.player.previous_chapter()

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

    def jump_to_time(self):
        if self.current_index == -1:
            return
        length = self.player.get_length_ms()
        text, ok = QInputDialog.getText(
            self, "Ir a tiempo",
            "Tiempo (h:mm:ss, mm:ss, segundos o porcentaje, p. ej. 40%):",
            text=format_time(self.player.get_time_ms()),
        )
        if not ok:
            return
        target = parse_time_input(text, length)
        if target is None:
            self.statusBar().showMessage(f"Tiempo no válido: {text}", 4000)
            return
        self._seek_to(target)

    def _nudge_volume(self, delta: int):
        self.volume_slider.setValue(max(0, min(MAX_VOLUME, self.volume_slider.value() + delta)))
        self._show_osd(f"Volumen: {self.volume_slider.value()}%")

    def _on_video_wheel(self, steps: int, modifiers):
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self._seek_relative(5000 * steps)
        else:
            self._nudge_volume(5 * steps)

    def _show_video_context_menu(self, global_pos: QPoint):
        self.video_context_menu.popup(global_pos)

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

    def _video_frame_global_rect(self) -> QRect:
        return QRect(self.video_frame.mapToGlobal(QPoint(0, 0)), self.video_frame.size())

    def _reposition_overlays(self):
        frame = self._video_frame_global_rect()
        hint = self._osd_label.sizeHint()
        self._osd_overlay.setGeometry(osd_rect(frame, hint.width(), hint.height()))
        if self._controls_are_floating():
            self._controls_overlay.setGeometry(floating_controls_rect(
                frame, self.fullscreen_controller.sizeHint().height(),
                margin=FULLSCREEN_CONTROLLER_MARGIN, max_width=FULLSCREEN_CONTROLLER_MAX_WIDTH,
            ))

    def _hide_overlays(self):
        self._osd_overlay.hide()
        self._controls_overlay.hide()

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

    # ------------------------------------------------------- vista previa
    # Buscar-y-capturar en el reproductor secundario no es instantáneo: la
    # búsqueda es asíncrona y libVLC necesita decodificar hasta ese punto.
    # Por eso: (1) el hover se debounce (~300 ms quieto sobre la barra), (2)
    # se sirve desde la cache si esa zona ya se capturo, y (3) si no, se
    # sondea la captura cada 40 ms (hasta 400 ms) en vez de esperar un
    # tiempo fijo y mostrar un fotograma viejo con el tiempo nuevo.
    def _on_slider_hovered(self, fraction: float, global_pos: QPoint):
        if self.current_index == -1 or self.player.get_length_ms() <= 0:
            return
        self._pending_hover_fraction = fraction
        self._pending_hover_pos = global_pos
        self._preview_idle_timer.stop()
        self._preview_hover_timer.start()

    def _on_slider_hover_ended(self):
        self._preview_hover_timer.stop()
        self._capture_timer.stop()
        self._hide_hover_preview()
        if not self.player.is_preview_warmed_up():
            # Todavia no salio ningun fotograma, asi que no se puede pausar
            # sin romper su vout (ver VLCPlayer.load_preview_media): se
            # detiene para que no siga decodificando todo el archivo en
            # segundo plano hasta el proximo hover.
            self.player.stop_preview()
        if self.player.has_preview_player():
            # Sin hovers por un rato, se libera (archivo y decodificador).
            self._preview_idle_timer.start()

    def _ensure_preview_popup(self):
        if self._preview_popup is not None:
            return
        self._preview_popup = QWidget(None, Qt.WindowType.ToolTip)
        self._preview_popup.setStyleSheet(theme.PREVIEW_POPUP_STYLE)
        popup_layout = QVBoxLayout(self._preview_popup)
        popup_layout.setContentsMargins(2, 2, 2, 2)
        popup_layout.setSpacing(2)
        self._preview_thumbnail_label = QLabel()
        self._preview_thumbnail_label.setFixedSize(160, 90)
        self._preview_thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        popup_layout.addWidget(self._preview_thumbnail_label)
        self._preview_time_label = QLabel()
        self._preview_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_time_label.setStyleSheet(theme.PREVIEW_TIME_STYLE)
        popup_layout.addWidget(self._preview_time_label)

    def _show_hover_preview(self):
        path = self._current_path_or_none()
        if path is None or self._pending_hover_fraction is None or self._pending_hover_pos is None:
            return
        fraction = self._pending_hover_fraction
        self._ensure_preview_popup()
        time_ms = int(fraction * self.player.get_length_ms())
        chapter = self.chapter_name_at(time_ms)
        self._preview_time_label.setText(f"{format_time(time_ms)} — {chapter}" if chapter else format_time(time_ms))

        thumbnails = self.player.preview_supported(path)
        self._preview_thumbnail_label.setVisible(thumbnails)
        if thumbnails:
            cached = self._thumbnail_cache.get(path, fraction)
            if cached is not None:
                self._preview_thumbnail_label.setPixmap(cached)
            else:
                # Sin fotograma viejo (de otra posicion u otro archivo).
                self._preview_thumbnail_label.clear()
                self._request_hover_snapshot(path, fraction)

        self._preview_popup.adjustSize()
        self._preview_popup.move(
            self._pending_hover_pos.x() - self._preview_popup.width() // 2,
            self._pending_hover_pos.y() - self._preview_popup.height() - 20,
        )
        self._preview_popup.show()

    def _request_hover_snapshot(self, path: str, fraction: float):
        if self.player.preview_current_path() != path:
            if not self.player.load_preview_media(path):
                return
        self.player.seek_preview(fraction)
        remove_quietly(self._preview_snapshot_path)
        self._capture_request = (path, fraction)
        self._capture_attempts = 0
        self._capture_timer.start()

    def _poll_hover_snapshot(self):
        self._capture_attempts += 1
        if self._capture_attempts * CAPTURE_POLL_MS > CAPTURE_TIMEOUT_MS:
            self._capture_timer.stop()
            return
        if self._capture_request is None or self._preview_popup is None or not self._preview_popup.isVisible():
            self._capture_timer.stop()
            return
        if not os.path.exists(self._preview_snapshot_path):
            dpr = self.devicePixelRatioF()
            self.player.take_preview_snapshot(self._preview_snapshot_path, width=int(160 * dpr), height=int(90 * dpr))
        if os.path.exists(self._preview_snapshot_path) and os.path.getsize(self._preview_snapshot_path) > 0:
            pixmap = QPixmap(self._preview_snapshot_path)
            if pixmap.isNull():
                return  # todavia escribiendose
            pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            path, fraction = self._capture_request
            self._thumbnail_cache.put(path, fraction, pixmap)
            self._preview_thumbnail_label.setPixmap(pixmap)
            self._capture_timer.stop()
            self._capture_request = None

    def _hide_hover_preview(self):
        if self._preview_popup is not None:
            self._preview_popup.hide()

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
            if path is not None and path_key(path) not in self._known_durations:
                self._known_durations[path_key(path)] = length
                self._refresh_item(self.current_index)
                self._update_dock_title()

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
            if self._consecutive_failures >= self.playlist_widget.count():
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
    def _populate_audio_track_menu(self):
        self.menu_audio_tracks.clear()
        current = self.player.get_current_audio_track()
        group = QActionGroup(self.menu_audio_tracks)
        group.setExclusive(True)
        for track_id, name in self.player.audio_tracks():
            label = name.decode("utf-8", errors="ignore") if isinstance(name, bytes) else str(name)
            action = QAction(label, self.menu_audio_tracks, checkable=True)
            action.setChecked(track_id == current)
            action.triggered.connect(lambda _checked, tid=track_id: self.player.set_audio_track(tid))
            group.addAction(action)
            self.menu_audio_tracks.addAction(action)

    def _populate_subtitle_track_menu(self):
        self.menu_subtitle_tracks.clear()
        current = self.player.get_current_subtitle_track()
        group = QActionGroup(self.menu_subtitle_tracks)
        group.setExclusive(True)
        for track_id, name in self.player.subtitle_tracks():
            label = name.decode("utf-8", errors="ignore") if isinstance(name, bytes) else str(name)
            action = QAction(label, self.menu_subtitle_tracks, checkable=True)
            action.setChecked(track_id == current)
            action.triggered.connect(lambda _checked, tid=track_id: self.player.set_subtitle_track(tid))
            group.addAction(action)
            self.menu_subtitle_tracks.addAction(action)

    def load_subtitle_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar subtítulo", self._open_dir(),
            "Subtítulos (*.srt *.ass *.ssa *.sub *.vtt);;Todos los archivos (*.*)",
        )
        if path:
            self._remember_dir(path)
            self.player.load_subtitle_file(path)

    def search_subtitles_online(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            QMessageBox.information(
                self, "Buscar subtítulos online", "Esta función solo funciona con archivos locales."
            )
            return
        dialog = OnlineSubtitleDialog(path, self)
        dialog.subtitle_ready.connect(self._on_online_subtitle_ready)
        dialog.status_message.connect(lambda text: self.statusBar().showMessage(text, 6000))
        self.subtitle_dialog = dialog
        dialog.open()

    def _on_online_subtitle_ready(self, video_path: str, subtitle_path: str):
        """Solo se carga en el video que origino la busqueda. Si mientras
        tanto se abrio otro, se guarda para cuando se vuelva a abrir ese."""
        current = self._current_path_or_none()
        if current is not None and path_key(current) == path_key(video_path):
            self.player.load_subtitle_file(subtitle_path)
        else:
            self._pending_subtitles[path_key(video_path)] = subtitle_path
            self.statusBar().showMessage(
                f"Subtítulo descargado para {os.path.basename(video_path)}: se usará al abrirlo", 6000
            )

    def _adjust_subtitle_delay(self, delta_ms: int):
        self._set_subtitle_delay(self.player.get_subtitle_delay_ms() + delta_ms)

    def _set_subtitle_delay(self, delay_ms: int):
        self.player.set_subtitle_delay_ms(delay_ms)
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
        if "visualizer" in dropped:
            messages.append("el visualizador de audio")
        if messages:
            text = f"Tu versión de VLC ({libvlc_version()}) no admite {' ni '.join(messages)}; se desactivó."
            log.warning(text)
            self.statusBar().showMessage(text, 8000)

    def take_snapshot(self):
        if self.current_index == -1:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar captura", os.path.join(self._open_dir(), "captura.png"), "Imagen PNG (*.png)"
        )
        if path:
            self._remember_dir(path)
            if not self.player.take_snapshot(path):
                self._show_osd("No hay video para capturar")

    def snapshot_dir(self) -> str:
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        return os.path.join(pictures or os.path.expanduser("~"), "Reproductor Multimedia Pro")

    def quick_snapshot(self):
        """Captura sin dialogo en Imagenes\\Reproductor Multimedia Pro."""
        path = self._current_path_or_none()
        if path is None:
            return None
        folder = self.snapshot_dir()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            self.statusBar().showMessage(f"No se pudo crear {folder}: {exc}", 5000)
            return None
        target = os.path.join(folder, snapshot_file_name(path, self.player.get_time_ms()))
        if not self.player.take_snapshot(target):
            self._show_osd("No hay video para capturar")
            return None
        self._quick_snapshot_pending = target
        return target

    # ------------------------------------------------------------ equalizer
    def open_equalizer(self):
        if self.equalizer_dialog is None:
            self.equalizer_dialog = EqualizerDialog(self.player, self, initial=self.settings.equalizer)
        self.equalizer_dialog.show()
        self.equalizer_dialog.raise_()
        self.equalizer_dialog.activateWindow()

    # ------------------------------------------------------------ tema
    def _apply_theme(self, key: str):
        theme.apply_theme(QApplication.instance(), key)
        self._refresh_icons()

    # ------------------------------------------------------------ fullscreen
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._dock_was_visible = self.playlist_dock.isVisible()
            self._status_bar_was_visible = not self.statusBar().isHidden()
            self.playlist_dock.setVisible(False)
            self.menuBar().setVisible(False)
            self.statusBar().setVisible(False)
            self._float_controls_bar()
            self.showFullScreen()
            self._set_action_icon(self.act_fullscreen, "fullscreen_exit")
            self.update_ui()
            self._on_fullscreen_mouse_activity()

    def _exit_fullscreen(self):
        if not self.isFullScreen():
            return
        self._fullscreen_idle_timer.stop()
        self._unfloat_controls_bar()
        self.video_frame.unsetCursor()
        self.showNormal()
        self.playlist_dock.setVisible(self._dock_was_visible)
        self.menuBar().setVisible(True)
        self.statusBar().setVisible(self._status_bar_was_visible)
        self._set_action_icon(self.act_fullscreen, "fullscreen")

    # -- controlador de pantalla completa ----------------------------------
    def _float_controls_bar(self):
        """En pantalla completa la barra normal se oculta y aparece el
        controlador dedicado, en su ventana superpuesta (_controls_overlay;
        ver OverlayWindow: un hijo de video_frame quedaria debajo de la
        ventana de video de libVLC), solo cuando hay actividad de mouse."""
        self.controls_bar.hide()
        self._fullscreen_active = True
        self._controls_overlay.hide()

    def _unfloat_controls_bar(self):
        self._fullscreen_active = False
        self._controls_overlay.hide()
        self.controls_bar.show()

    def _controls_are_floating(self) -> bool:
        return getattr(self, "_fullscreen_active", False)

    def _reposition_floating_controls(self):
        if self._controls_are_floating():
            self._reposition_overlays()

    def _show_floating_controls(self):
        if not self._controls_are_floating():
            return
        self._reposition_floating_controls()
        if self._overlays_allowed():
            self._controls_overlay.show()

    def _hide_floating_controls(self):
        if self._controls_are_floating():
            self._controls_overlay.hide()
            # Sin actividad en pantalla completa tambien se oculta el cursor
            # sobre el video (se restaura con el siguiente movimiento).
            self.video_frame.setCursor(Qt.CursorShape.BlankCursor)

    def _on_fullscreen_mouse_activity(self):
        if not self.isFullScreen():
            return
        self.video_frame.unsetCursor()
        self._show_floating_controls()
        self._fullscreen_idle_timer.start()

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and obj is self.playlist_widget
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
            self._on_fullscreen_mouse_activity()
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
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        dropped = []
        for url in event.mimeData().urls():
            dropped.append(url.toLocalFile() if url.isLocalFile() else url.toString())
        entries = filter_dropped([d for d in dropped if d])
        if entries:
            start_index = self.playlist_widget.count()
            self.add_files_to_playlist(entries)
            if self.current_index == -1:
                self.play_index(start_index)
        event.acceptProposedAction()

    # ------------------------------------------------------------ misc
    def show_about(self):
        QMessageBox.about(
            self,
            "Acerca de Reproductor Multimedia Pro",
            f"Reproductor Multimedia Pro v{__version__}\n\n"
            "Reproductor de música y video de alta calidad.\n\n"
            f"Motor de decodificación: libVLC {libvlc_version()} (python-vlc)\n"
            "Interfaz: PySide6\n\n"
            "Soporta prácticamente todos los formatos de audio y video "
            "conocidos por VLC, incluyendo formatos poco comunes.",
        )

    def open_log_folder(self):
        folder = current_log_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event):
        if getattr(self, "_closed", False):
            super().closeEvent(event)
            return
        self._closed = True
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
        for timer in (self._ab_timer, self._capture_timer, self._stall_timer, self._metadata_timer,
                      self._preview_idle_timer):
            timer.stop()
        # Los hilos de subtitulos que sigan en marcha no deben destruirse
        # corriendo (error fatal de Qt): se espera un poco a que terminen.
        wait_for_subtitle_jobs(3000)
        self._metadata_probe.close()
        # Liberar libVLC (vout y salida de audio) antes de que Qt destruya
        # los widgets nativos donde dibuja.
        self.player.close()
        remove_quietly(self._preview_snapshot_path)
        if self._preview_popup is not None:
            self._preview_popup.close()
        self._hide_overlays()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            try:
                app.applicationStateChanged.disconnect(self._on_application_state_changed)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)
