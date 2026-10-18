import logging
import os
import subprocess
import sys
from functools import partial

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QStandardPaths, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import (
    QAccessible,
    QAction,
    QActionGroup,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPalette,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
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

from . import __version__, theme
from .actions import ActionRegistry
from .backend import FINISHED_STATES, MediaInfoProbe, PlaybackState, VLCPlayer, libvlc_version
from .bookmarks import add_bookmark, get_bookmarks
from .bookmarks_dialog import BookmarksDialog
from .equalizer_dialog import EqualizerDialog  # noqa: F401 -- reexportado (pruebas)
from .folder_scan import FolderScanWorker
from .formats import (
    build_open_filter,
    format_rate,
    format_time,
    is_url,
    parse_time_input,
    path_key,
    snapshot_file_name,
)
from .fullscreen import FullscreenMode
from .inputs import dropped_inputs, expand_inputs, needs_scan, read_playlist_file
from .logs import current_log_dir
from .media_info_dialog import MediaInfoDialog
from .m3u import load_playlist as load_m3u_playlist
from .m3u import save_playlist as save_m3u_playlist
from .playlist_controller import PlaylistController
from .playlist_model import PlaylistView, display_name
from .playlist_order import playback_failed
from .power import POWER_ACTIONS, PowerCountdownDialog, run_power_action
from .preview_controller import PreviewController
from .recent_files import add_recent_file, clear_recent_files, get_recent_files
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
from .video_adjust_dialog import VideoAdjustDialog
from .video_options import ASPECT_RATIOS, CROP_RATIOS, DEINTERLACE_LABELS, choice_label, next_choice
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

log = logging.getLogger(__name__)

DEFAULT_WINDOW_SIZE = (1150, 720)
SESSION_SAVE_DELAY_MS = 1000
UI_TICK_MS = 500          # etiquetas y barra; las transiciones llegan por eventos
AB_LOOP_TICK_MS = 50      # mientras hay un tramo A-B activo
AB_NUDGE_MS = 100         # paso para mover los puntos A/B
OSD_TIMEOUT_MS = 1500
STREAM_STALL_TIMEOUT_MS = 15_000
STREAM_VISUALIZER_DELAY_MS = 1500
REPEAT_LABELS = {"none": "No repetir", "all": "Repetir todo", "one": "Repetir uno"}
AUDIO_DELAY_STEP_MS = 50


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
    def _build_actions(self):
        """Todas las acciones con nombre (ver actions.ActionRegistry):
        menus, botones (setDefaultAction), menu contextual del video,
        controlador de pantalla completa y la ayuda de atajos usan los
        mismos QAction -- una sola fuente para texto, atajo y estado."""
        A = self.action_registry.add
        # Transporte (barra, menus y pantalla completa).
        self.act_play_pause = A("play_pause", "Reproducir/Pausar", self.toggle_play_pause, "Space",
                                tooltip="Reproducir/Pausar (Espacio)")
        self.act_stop = A("stop", "Detener", self.stop, "S", tooltip="Detener (S)")
        self.act_next = A("next", "Pista siguiente", lambda: self.play_next(auto=False), "Ctrl+Right",
                          tooltip="Pista siguiente (Ctrl+Derecha)")
        self.act_prev = A("previous", "Pista anterior", self.play_previous, "Ctrl+Left",
                          tooltip="Pista anterior (Ctrl+Izquierda)")
        self.act_mute = A("mute", "Silenciar", self.toggle_mute, "M", checkable=True, tooltip="Silenciar (M)")
        self.act_fullscreen = A("fullscreen", "Pantalla completa", self.toggle_fullscreen, "F",
                                tooltip="Pantalla completa (F)")
        self.act_shuffle = A("shuffle", "Aleatorio", None, checkable=True,
                             tooltip="Reproducir la lista en orden aleatorio")
        self.act_shuffle.toggled.connect(self._on_shuffle_toggled)
        self.act_repeat_cycle = A("repeat", "Cambiar modo de repetición", self._cycle_repeat_mode,
                                  tooltip="Cicla entre No repetir / Repetir todo / Repetir uno")
        self.act_ab_loop = A("ab_loop", "Bucle A-B", self._on_ab_loop_clicked,
                             tooltip="Marca un punto A, luego un punto B: repite en bucle solo ese tramo. "
                                     "Un tercer clic lo desactiva.")
        self.act_ab_set_a = A("ab_set_a", "Marcar punto A", self._set_ab_point_a, "Ctrl+Shift+A")
        self.act_ab_set_b = A("ab_set_b", "Marcar punto B", self._set_ab_point_b, "Ctrl+Shift+B")
        self.act_ab_clear = A("ab_clear", "Limpiar bucle A-B", self._clear_ab_loop_with_feedback, "Ctrl+Shift+L")
        A("ab_a_earlier", "Mover punto A 0,1 s antes", lambda: self._nudge_ab_point("a", -AB_NUDGE_MS), "Alt+Shift+Left")
        A("ab_a_later", "Mover punto A 0,1 s después", lambda: self._nudge_ab_point("a", AB_NUDGE_MS), "Alt+Shift+Right")
        A("ab_b_earlier", "Mover punto B 0,1 s antes", lambda: self._nudge_ab_point("b", -AB_NUDGE_MS), "Ctrl+Shift+Left")
        A("ab_b_later", "Mover punto B 0,1 s después", lambda: self._nudge_ab_point("b", AB_NUDGE_MS), "Ctrl+Shift+Right")
        A("ab_bookmarks", "Bucle entre marcadores", self._loop_between_bookmarks,
          tooltip="Repite el tramo entre el marcador anterior y el siguiente a la posición actual "
                  "(o el inicio/final del archivo si no hay)")

        # Archivo.
        A("open_files", "Abrir archivos...", self.open_files, QKeySequence.StandardKey.Open)
        A("open_folder", "Abrir carpeta...", self.open_folder)
        self.act_cancel_folder_scan = A("cancel_folder_scan", "Cancelar escaneo de carpeta", self.cancel_folder_scan)
        self.act_cancel_folder_scan.setEnabled(False)
        A("open_url", "Abrir URL...", self.open_url, "Ctrl+U")
        A("save_playlist", "Guardar lista (.m3u8)...", self.save_playlist)
        A("load_playlist", "Cargar lista...", self.load_playlist)
        self.act_restore_session = A(
            "restore_session", "Recordar la lista al cerrar", checkable=True,
            tooltip="Al volver a abrir el programa, restaura la lista de reproducción y el elemento actual",
        )
        self.act_restore_session.setChecked(True)
        self.act_restore_session.toggled.connect(lambda _checked: self._schedule_session_save())
        self.act_allow_multiple_windows = A(
            "allow_multiple_windows", "Permitir varias ventanas", checkable=True,
            tooltip="Si está desmarcado, abrir un archivo con el programa ya abierto lo agrega a esa ventana",
        )
        A("quit", "Salir", self.close, QKeySequence.StandardKey.Quit)

        # Reproduccion.
        A("next_frame", "Avanzar un fotograma", self.step_frame, ".",
          tooltip="Avanza un solo fotograma (el video debe estar en pausa)")
        A("jump_to_time", "Ir a tiempo...", self.jump_to_time, "Ctrl+G")
        A("seek_start", "Volver al inicio", lambda: self._seek_to(0), "Home")
        A("slower", "Más lenta", lambda: self._nudge_rate(-RATE_STEP), "[")
        A("faster", "Más rápida", lambda: self._nudge_rate(RATE_STEP), "]")
        A("normal_speed", "Velocidad normal", lambda: self._set_rate(1.0), "=")
        self.act_prev_chapter = A("previous_chapter", "Capítulo anterior", self.previous_chapter, "PgUp")
        self.act_next_chapter = A("next_chapter", "Capítulo siguiente", self.next_chapter, "PgDown")
        A("add_bookmark", "Agregar marcador aquí", self.quick_add_bookmark, "B")
        A("show_bookmarks", "Ver marcadores...", self.show_bookmarks)

        # Audio.
        A("equalizer", "Ecualizador...", self.open_equalizer)
        self.act_visualizer = A("visualizer", "Visualizador de audio (espectro)", checkable=True)
        self.act_visualizer.setChecked(True)
        A("audio_earlier", "Adelantar audio 50 ms", lambda: self._adjust_audio_delay(-AUDIO_DELAY_STEP_MS), "J")
        A("audio_later", "Retrasar audio 50 ms", lambda: self._adjust_audio_delay(AUDIO_DELAY_STEP_MS), "K")
        A("audio_sync_reset", "Restablecer sincronía de audio", lambda: self._set_audio_delay(0))
        self.act_normalize_volume = A(
            "normalize_volume", "Normalizar volumen", checkable=True,
            tooltip="Baja automáticamente los pasajes muy fuertes (normalizador de VLC)",
        )
        self.act_normalize_volume.toggled.connect(self._on_normalize_toggled)

        # Video.
        A("snapshot", "Capturar fotograma...", self.take_snapshot)
        A("quick_snapshot", "Captura rápida", self.quick_snapshot, "Ctrl+Shift+S",
          tooltip="Guarda una captura en Imágenes\\Reproductor Multimedia Pro")
        A("load_subtitle", "Cargar subtítulo externo...", self.load_subtitle_file)
        A("search_subtitles", "Buscar subtítulos online...", self.search_subtitles_online)
        A("subtitles_earlier", "Adelantar subtítulos 50 ms", lambda: self._adjust_subtitle_delay(-50), "G")
        A("subtitles_later", "Retrasar subtítulos 50 ms", lambda: self._adjust_subtitle_delay(50), "H")
        A("subtitle_sync_reset", "Restablecer sincronía de subtítulos", lambda: self._set_subtitle_delay(0))
        A("video_adjust", "Ajustes de video...", self.open_video_adjust, "Ctrl+E",
          tooltip="Brillo, contraste, saturación, tono y gamma")
        A("media_info", "Información del medio...", self.show_media_info, "Ctrl+I",
          tooltip="Códecs, resolución, cuadros por segundo, canales, bitrate y etiquetas")

        # Ver.
        self.act_remaining_time = A("remaining_time", "Mostrar tiempo restante", lambda _c=False: self.update_ui(),
                                    checkable=True,
                                    tooltip="En vez de la duración total (también con clic sobre ella)")
        self.act_always_on_top = A("always_on_top", "Siempre visible (encima de otras ventanas)", checkable=True)
        self.act_always_on_top.toggled.connect(self._on_always_on_top_toggled)

        # Ayuda.
        A("shortcuts_help", "Atajos de teclado...", self.show_shortcuts_help, "F1")
        A("open_log_folder", "Abrir carpeta de registros", self.open_log_folder,
          tooltip="Registro de errores del programa (útil para reportar un problema)")
        A("about", "Acerca de...", self.show_about)

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

    def _build_menu(self):
        menubar = self.menuBar()
        R = self.action_registry

        # -- Archivo --
        menu_file = menubar.addMenu("&Archivo")
        self.menu_recent_files = QMenu("Abrir reciente", menu_file)
        self.menu_recent_files.aboutToShow.connect(self._populate_recent_files_menu)
        R.populate(menu_file, [
            "open_files", "open_folder", "open_url", self.menu_recent_files, None,
            "save_playlist", "load_playlist", "cancel_folder_scan", "restore_session",
            "allow_multiple_windows", None, "quit",
        ])

        # -- Reproducción --
        menu_playback = menubar.addMenu("&Reproducción")
        R.populate(menu_playback, [
            "play_pause", "stop", "next", "previous", "next_frame", "jump_to_time", "seek_start", None,
        ])

        self.menu_speed = menu_playback.addMenu("Velocidad")
        self.speed_group = QActionGroup(self)
        self.speed_group.setExclusive(True)
        for value in SPEEDS:
            action = QAction(format_rate(value), self, checkable=True)
            action.setData(value)
            action.triggered.connect(lambda _checked, v=value: self._set_rate(v))
            self.speed_group.addAction(action)
            self.menu_speed.addAction(action)
        R.populate(self.menu_speed, [None, "slower", "faster", "normal_speed"])
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
        R.populate(menu_playback, ["ab_loop", "ab_set_a", "ab_set_b", "ab_clear", "ab_a_earlier", "ab_a_later",
                                  "ab_b_earlier", "ab_b_later", "ab_bookmarks"])

        self.menu_chapters = menu_playback.addMenu("Capítulos")
        self.menu_chapters.aboutToShow.connect(self._populate_chapters_menu)
        R.populate(menu_playback, ["previous_chapter", "next_chapter", None])

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

        R.populate(menu_playback, [None, "add_bookmark", "show_bookmarks"])

        # -- Audio --  (A&udio: "&Archivo" ya usa Alt+A)
        menu_audio = menubar.addMenu("A&udio")
        self.menu_audio_tracks = QMenu("Pista de audio", menu_audio)
        self.menu_audio_tracks.aboutToShow.connect(self._populate_audio_track_menu)
        self.menu_audio_device = QMenu("Dispositivo de salida", menu_audio)
        self.menu_audio_device.aboutToShow.connect(self._populate_audio_device_menu)
        R.populate(menu_audio, [
            "mute", "equalizer", "visualizer", "normalize_volume", self.menu_audio_tracks, self.menu_audio_device,
            None, "audio_earlier", "audio_later", "audio_sync_reset",
        ])
        if not self.player.volume_normalization_supported():
            self.act_normalize_volume.setEnabled(False)
            self.act_normalize_volume.setToolTip(
                f"No disponible con esta versión de VLC ({libvlc_version()})")

        # -- Video --
        menu_video = menubar.addMenu("&Video")
        self.menu_subtitle_tracks = QMenu("Pista de subtítulos", menu_video)
        self.menu_subtitle_tracks.aboutToShow.connect(self._populate_subtitle_track_menu)
        R.populate(menu_video, [
            "fullscreen", "snapshot", "quick_snapshot", None,
            self.menu_subtitle_tracks, "load_subtitle", "search_subtitles",
            "subtitles_earlier", "subtitles_later", "subtitle_sync_reset",
        ])

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

        self.menu_aspect = self._choice_menu(
            menu_video, "Relación de aspecto", ASPECT_RATIOS, "", self._set_aspect_ratio)
        self.menu_crop = self._choice_menu(menu_video, "Recortar", CROP_RATIOS, "", self._set_crop)
        self.menu_deinterlace = self._choice_menu(
            menu_video, "Desentrelazado", DEINTERLACE_LABELS, "auto", self._set_deinterlace)
        R.populate(menu_video, ["video_adjust", None, "media_info"])

        self.menu_gpu = None
        if sys.platform.startswith("win"):
            self._build_gpu_menu(menu_video)

        # -- Ver --
        menu_view = menubar.addMenu("&Ver")
        act_toggle_playlist = self.playlist_dock.toggleViewAction()
        act_toggle_playlist.setText("Mostrar lista de reproducción")
        R.populate(menu_view, [act_toggle_playlist, "remaining_time", "always_on_top"])
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
        R.populate(menu_help, ["shortcuts_help", "open_log_folder", "about"])

        # Menu contextual del video: las mismas acciones y submenus.
        self.video_context_menu = R.populate(QMenu(self), [
            "play_pause", "stop", "previous", "next", None, "fullscreen", None,
            self.menu_speed, self.menu_chapters, self.menu_audio_tracks, self.menu_subtitle_tracks,
            self.menu_zoom, self.menu_aspect, self.menu_crop, None, "media_info", "always_on_top",
        ])

    def _choice_menu(self, parent_menu, title, choices, default, on_choose):
        """Submenu de opciones exclusivas: choices = [(etiqueta, valor)]."""
        menu = parent_menu.addMenu(title)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for label, value in choices:
            action = QAction(label, menu, checkable=True)
            action.setData(value)
            action.setChecked(value == default)
            action.triggered.connect(lambda _checked, v=value: on_choose(v))
            group.addAction(action)
            menu.addAction(action)
        return menu

    @staticmethod
    def _check_menu_value(menu, value):
        for action in menu.actions():
            if action.isCheckable():
                action.setChecked(action.data() == value)

    def _build_gpu_menu(self, menu_video):
        self.menu_gpu = menu_video.addMenu("Mejora por GPU")
        self.act_gpu_upscale = self.action_registry.add(
            "gpu_upscale", "Superresolución (RTX Video / Intel)", checkable=True,
            tooltip="Solo actúa cuando el video se agranda (ventana más grande que el video). Requiere "
                    "\"RTX Video Enhancement\" activado en el Panel de control de NVIDIA y la salida Direct3D11.",
        )
        self.act_gpu_hdr = self.action_registry.add(
            "gpu_hdr", "HDR a partir de SDR (RTX Video HDR)", checkable=True,
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

    def _build_shortcuts(self):
        """Atajos sin entrada de menu (QShortcut de ventana), registrados
        con su descripcion para la ayuda."""
        S = self.action_registry.add_shortcut
        S(Qt.Key.Key_Escape, "Salir de pantalla completa", self._exit_fullscreen)
        S(Qt.Key.Key_Right, "Adelantar 5 s", lambda: self._seek_relative(5000))
        S(Qt.Key.Key_Left, "Retroceder 5 s", lambda: self._seek_relative(-5000))
        S("Shift+Right", "Adelantar 1 s", lambda: self._seek_relative(1000))
        S("Shift+Left", "Retroceder 1 s", lambda: self._seek_relative(-1000))
        S("Alt+Right", "Adelantar 30 s", lambda: self._seek_relative(30_000))
        S("Alt+Left", "Retroceder 30 s", lambda: self._seek_relative(-30_000))
        S("Ctrl+Alt+Right", "Adelantar 60 s", lambda: self._seek_relative(60_000))
        S("Ctrl+Alt+Left", "Retroceder 60 s", lambda: self._seek_relative(-60_000))
        S("A", "Siguiente relación de aspecto", lambda: self._cycle_choice(ASPECT_RATIOS, self._set_aspect_ratio,
                                                                          self.player.get_aspect_ratio()))
        S("C", "Siguiente recorte", lambda: self._cycle_choice(CROP_RATIOS, self._set_crop, self.player.get_crop()))
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
        self.action_registry.static_rows = [
            ("Buscar en la lista (con la lista enfocada)", QKeySequence(QKeySequence.StandardKey.Find)
             .toString(QKeySequence.SequenceFormat.NativeText)),
            ("Quitar de la lista (con la lista enfocada)", "Supr"),
            ("Volumen / buscar ±5 s", "Rueda / Ctrl+Rueda sobre el video"),
            ("Pantalla completa", "Doble clic sobre el video"),
        ]

    def shortcut_rows(self) -> list:
        """(descripcion, atajo) para Ayuda -> Atajos de teclado, generado
        del registro de acciones (no se desincroniza del codigo)."""
        return self.action_registry.shortcut_rows()

    def show_shortcuts_help(self):
        """Ayuda -> Atajos de teclado: la tabla, editable (player/shortcuts_dialog.py)."""
        from .shortcuts_dialog import ShortcutsDialog

        dialog = ShortcutsDialog(self.action_registry, on_changed=self.save_settings_now, parent=self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
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

    def open_paths(self, paths, play: bool = True, announce: bool = False):
        """Agrega lo que el usuario "abrio" (carpetas y .m3u expandidos) y,
        con play=True o si no suena nada, reproduce lo primero agregado.
        Devuelve cuantas entradas se agregaron, o None si hay carpetas: esas
        se recorren en segundo plano y se agregan al terminar (announce=True
        avisa en la barra de estado cuantas fueron)."""
        if needs_scan(paths):
            self._start_input_scan(paths, partial(self._finish_open_paths, play, announce), "Escaneando carpeta…")
            return None
        return self._finish_open_paths(play, announce, expand_inputs(paths), False)

    def _finish_open_paths(self, play: bool, announce: bool, entries: list, cancelled: bool) -> int:
        if entries:
            start_index = self.playlist.add(entries)
            if play or self.current_index == -1:
                self.play_index(start_index)
        if announce and entries:
            noun = "elemento agregado" if len(entries) == 1 else "elementos agregados"
            prefix = "Escaneo cancelado: " if cancelled else ""
            self.statusBar().showMessage(f"{prefix}{len(entries)} {noun} a la lista", 4000)
        return len(entries)

    def _add_and_maybe_play(self, entries):
        """Agrega y, si no sonaba nada, reproduce lo primero agregado."""
        if not entries:
            return
        start_index = self.playlist.add(entries)
        if self.current_index == -1:
            self.play_index(start_index)

    def handle_instance_message(self, action: str, paths):
        """Mensaje de otra instancia (ver single_instance.py)."""
        self.open_paths(paths, play=action == "open", announce=action == "enqueue")
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

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
    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Abrir archivos multimedia", self._open_dir(), build_open_filter()
        )
        if not paths:
            return
        self._remember_dir(paths[0])
        self._add_and_maybe_play(expand_inputs(paths))

    def open_folder(self):
        if self._folder_scan_thread is not None:
            self.statusBar().showMessage("Ya hay un escaneo de carpeta en curso", 4000)
            return
        folder = QFileDialog.getExistingDirectory(self, "Abrir carpeta", self._open_dir())
        if not folder:
            return
        self._remember_dir(folder)
        self._start_folder_scan(folder)

    def _start_folder_scan(self, folder: str):
        self.cancel_folder_scan()
        self._start_input_scan([folder], partial(self._finish_folder_scan, folder), f"Escaneando carpeta: {folder}")

    def _start_input_scan(self, paths, on_done, status: str):
        """Expande `paths` (con carpetas) en un QThread y llama a
        on_done(encontrados, cancelado) en el hilo de la UI. Con otro escaneo
        en curso, este espera su turno (soltar dos carpetas seguidas no pierde
        la segunda)."""
        if self._folder_scan_thread is not None:
            self._input_scan_queue.append((list(paths), on_done, status))
            return
        self._input_scan_done = on_done
        self._folder_scan_entries = []
        self.act_cancel_folder_scan.setEnabled(True)
        self.statusBar().showMessage(status)
        thread = QThread(self)
        worker = FolderScanWorker(paths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Solo metodos de la ventana como slots: PySide entrega una senal a un
        # lambda en el hilo que la emite (el del escaneo), y estos tocan la UI.
        # Un metodo de un QObject se encola al hilo de la ventana.
        worker.batchFound.connect(self._on_folder_scan_batch)
        worker.finished.connect(self._on_folder_scan_finished)
        worker.cancelled.connect(self._on_folder_scan_cancelled)
        worker.failed.connect(self._on_folder_scan_failed)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_folder_scan_worker)
        self._folder_scan_thread = thread
        self._folder_scan_worker = worker
        thread.start()

    def _on_folder_scan_batch(self, batch: list):
        self._folder_scan_entries.extend(batch)
        noun = "archivo" if len(self._folder_scan_entries) == 1 else "archivos"
        self.statusBar().showMessage(f"Escaneando carpeta… {len(self._folder_scan_entries)} {noun} encontrados")

    def _on_folder_scan_finished(self, found: list):
        self._complete_input_scan(found, cancelled=False)

    def _on_folder_scan_cancelled(self, found: list):
        self._complete_input_scan(found, cancelled=True)

    def _complete_input_scan(self, found: list, cancelled: bool):
        self._folder_scan_entries = list(found)
        self.act_cancel_folder_scan.setEnabled(False)
        done, self._input_scan_done = self._input_scan_done, None
        if done is not None:
            done(list(found), cancelled)

    def _finish_folder_scan(self, folder: str, found: list, cancelled: bool):
        if not found:
            text = "Escaneo cancelado: no se encontraron archivos multimedia soportados." if cancelled else (
                "No se encontraron archivos multimedia soportados."
            )
            QMessageBox.information(self, "Abrir carpeta", text)
            return
        self._add_and_maybe_play(found)
        noun = "elemento agregado" if len(found) == 1 else "elementos agregados"
        prefix = "Escaneo cancelado" if cancelled else "Carpeta agregada"
        self.statusBar().showMessage(f"{prefix}: {len(found)} {noun}", 5000)

    def _on_folder_scan_failed(self, error: str):
        self.act_cancel_folder_scan.setEnabled(False)
        self._input_scan_done = None
        QMessageBox.warning(self, "Abrir carpeta", f"No se pudo escanear la carpeta:\n{error}")

    def _clear_folder_scan_worker(self):
        self._folder_scan_thread = None
        self._folder_scan_worker = None
        if self._input_scan_queue:
            self._start_input_scan(*self._input_scan_queue.pop(0))

    def cancel_folder_scan(self):
        if self._folder_scan_worker is not None:
            self._folder_scan_worker.cancel()
            self.statusBar().showMessage("Cancelando escaneo de carpeta…", 3000)

    def open_url(self):
        dialog = OpenUrlDialog(self.player.network_caching_ms, self.player.rtsp_tcp, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.player.network_caching_ms = dialog.network_caching_ms()
        self.player.rtsp_tcp = dialog.rtsp_tcp()
        self.play_index(self.playlist.add([dialog.url()]))

    def open_recent_file(self, path: str):
        if not is_url(path) and not os.path.exists(path):
            QMessageBox.warning(self, "Archivo reciente", f"No se encontró el archivo:\n{path}")
            return
        self.play_index(self.playlist.add([path]))

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
        if self.playlist.count() == 0:
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
        if not save_m3u_playlist(path, self.playlist_entries()):
            QMessageBox.warning(self, "Guardar lista", f"No se pudo guardar la lista:\n{path}")

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
        self._add_and_maybe_play(load_m3u_playlist(path))

    def show_playlist_context_menu(self, pos):
        view = self.playlist_view
        index = view.indexAt(pos)
        row = view.to_source_row(index)
        path = self.playlist.path(row)
        selected = set(view.selected_source_rows())
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
            action.setEnabled(path is not None)
        act_show.setEnabled(path is not None and not is_url(path))
        if path is not None and len(selected) > 1 and row in selected:
            act_remove.setText("Quitar seleccionados de la lista")
        chosen = menu.exec(view.viewport().mapToGlobal(pos))
        if chosen == act_play and path is not None:
            self.play_index(row)
        elif chosen == act_remove and path is not None:
            # Clic derecho sobre una fila seleccionada quita toda la
            # seleccion; sobre una no seleccionada, solo esa (como el
            # Explorador).
            if row in selected:
                self.remove_selected_from_playlist()
            else:
                self.remove_rows([row])
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

    def _video_frame_global_rect(self) -> QRect:
        return QRect(self.video_frame.mapToGlobal(QPoint(0, 0)), self.video_frame.size())

    def _reposition_overlays(self):
        frame = self._video_frame_global_rect()
        hint = self._osd_label.sizeHint()
        self._osd_overlay.setGeometry(osd_rect(frame, hint.width(), hint.height()))
        if hasattr(self, "fullscreen"):
            self.fullscreen.reposition(frame)

    def _hide_overlays(self):
        self._osd_overlay.hide()
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
    def _populate_audio_track_menu(self):
        self.menu_audio_tracks.clear()
        current = self.player.get_current_audio_track()
        group = QActionGroup(self.menu_audio_tracks)
        group.setExclusive(True)
        for track_id, name in self.player.audio_tracks():
            label = name.decode("utf-8", errors="ignore") if isinstance(name, bytes) else str(name)
            action = QAction(label, self.menu_audio_tracks, checkable=True)
            action.setChecked(track_id == current)
            action.triggered.connect(lambda _checked, tid=track_id: self._select_audio_track(tid))
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
            action.triggered.connect(lambda _checked, tid=track_id: self._select_subtitle_track(tid))
            group.addAction(action)
            self.menu_subtitle_tracks.addAction(action)

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

    # ------------------------------------------------------------ imagen y sonido
    def open_video_adjust(self):
        if self.video_adjust_dialog is None:
            self.video_adjust_dialog = VideoAdjustDialog(self.player, self)
        self.video_adjust_dialog.show()
        self.video_adjust_dialog.raise_()
        self.video_adjust_dialog.activateWindow()

    def _set_aspect_ratio(self, ratio: str):
        self.player.set_aspect_ratio(ratio)
        self._check_menu_value(self.menu_aspect, ratio)
        self._show_osd(f"Aspecto: {choice_label(ASPECT_RATIOS, ratio)}")

    def _set_crop(self, ratio: str):
        self.player.set_crop(ratio)
        self._check_menu_value(self.menu_crop, ratio)
        self._show_osd(f"Recorte: {choice_label(CROP_RATIOS, ratio)}")

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

    def _populate_audio_device_menu(self):
        self.menu_audio_device.clear()
        group = QActionGroup(self.menu_audio_device)
        group.setExclusive(True)
        current = self.player.get_audio_device()
        devices = self.player.audio_output_devices() or [("", "Predeterminado")]
        if current and current not in {device for device, _name in devices}:
            # El dispositivo guardado ya no esta (desconectado): se sigue
            # mostrando para que se vea por que no suena por ahi.
            devices.append((current, "(desconectado)"))
        for device, name in devices:
            action = QAction(name or "Predeterminado", self.menu_audio_device, checkable=True)
            action.setChecked(device == current)
            action.triggered.connect(lambda _checked, d=device: self.player.set_audio_device(d))
            group.addAction(action)
            self.menu_audio_device.addAction(action)

    def show_media_info(self):
        details = self.player.media_details()
        if details is None:
            self.statusBar().showMessage("No hay nada abierto", 3000)
            return None
        dialog = MediaInfoDialog(details, self)
        dialog.show()
        return dialog

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
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        dropped = []
        for url in event.mimeData().urls():
            dropped.append(url.toLocalFile() if url.isLocalFile() else url.toString())
        inputs = dropped_inputs([d for d in dropped if d])
        if needs_scan(inputs):
            self._start_input_scan(inputs, self._finish_drop, "Escaneando lo soltado…")
        else:
            self._add_and_maybe_play(expand_inputs(inputs))
        event.acceptProposedAction()

    def _finish_drop(self, found: list, cancelled: bool):
        self._add_and_maybe_play(found)
        if found:
            noun = "elemento agregado" if len(found) == 1 else "elementos agregados"
            prefix = "Escaneo cancelado: " if cancelled else ""
            self.statusBar().showMessage(f"{prefix}{len(found)} {noun}", 5000)

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
