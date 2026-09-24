import os
import subprocess
import sys
import tempfile

import vlc
from PySide6.QtCore import QEvent, Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .backend import VLCPlayer
from .bookmarks import add_bookmark, get_bookmarks
from .bookmarks_dialog import BookmarksDialog
from .formats import ALL_EXTS, build_open_filter, format_time, is_audio_file, is_url, normalize_path
from .m3u import format_m3u, parse_m3u
from .playlist_order import PlaylistOrder, playback_failed
from .recent_files import add_recent_file, clear_recent_files, get_recent_files
from .resume import clear_position, get_saved_position_ms, save_position
from .subtitle_dialog import OnlineSubtitleDialog

# Marcadores y punto A/B pintados sobre la barra de progreso.
_LOOP_MARKER_COLOR = QColor("#ff8c3c")
_BOOKMARK_MARKER_COLOR = QColor("#ffd23c")


def _icon_path(filename: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", filename)


class VideoFrame(QFrame):
    doubleClicked = Signal()
    mouseMoved = Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        self.mouseMoved.emit()
        super().mouseMoveEvent(event)


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


class PositionSlider(QSlider):
    """QSlider que además dibuja marcadores (punto A/B, marcadores
    nombrados) como pequeñas líneas de color sobre la barra, y emite
    hovered(fraccion, posicion_global) mientras el mouse se mueve encima
    (usado por MainWindow para la miniatura de vista previa)."""

    hovered = Signal(float, QPoint)
    hoverEnded = Signal()

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._markers = []  # lista de (fraccion 0..1, QColor)
        self.setMouseTracking(True)

    def set_markers(self, markers):
        self._markers = markers
        self.update()

    def _fraction_at(self, x: int) -> float:
        handle_width = self.style().pixelMetric(QStyle.PixelMetric.PM_SliderLength, None, self)
        usable_width = max(1, self.width() - handle_width)
        return max(0.0, min(1.0, (x - handle_width / 2) / usable_width))

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        fraction = self._fraction_at(int(event.position().x()))
        self.hovered.emit(fraction, event.globalPosition().toPoint())

    def leaveEvent(self, event):
        self.hoverEnded.emit()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._markers:
            return
        handle_width = self.style().pixelMetric(QStyle.PixelMetric.PM_SliderLength, None, self)
        usable_width = max(0, self.width() - handle_width)
        painter = QPainter(self)
        for fraction, color in self._markers:
            x = handle_width // 2 + int(max(0.0, min(1.0, fraction)) * usable_width)
            pen = QPen(color)
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawLine(x, self.height() - 7, x, self.height() - 1)


class EqualizerDialog(QDialog):
    def __init__(self, player: VLCPlayer, parent=None):
        super().__init__(parent)
        self.player = player
        self.setWindowTitle("Ecualizador")

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.enable_checkbox = QCheckBox("Activar ecualizador")
        top.addWidget(self.enable_checkbox)
        top.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Personalizado", -1)
        for i, name in enumerate(player.equalizer_preset_names()):
            self.preset_combo.addItem(name, i)
        top.addWidget(self.preset_combo)
        layout.addLayout(top)

        bands_layout = QHBoxLayout()
        freqs = player.equalizer_band_frequencies()

        preamp_box = QVBoxLayout()
        self.preamp_value_label = QLabel("0 dB")
        preamp_box.addWidget(self.preamp_value_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.preamp_slider = QSlider(Qt.Orientation.Vertical)
        self.preamp_slider.setRange(-20, 20)
        self.preamp_slider.setValue(0)
        self.preamp_slider.setMinimumHeight(140)
        preamp_box.addWidget(self.preamp_slider, alignment=Qt.AlignmentFlag.AlignHCenter)
        preamp_box.addWidget(QLabel("Preamp"), alignment=Qt.AlignmentFlag.AlignHCenter)
        bands_layout.addLayout(preamp_box)

        self.band_sliders = []
        self.band_value_labels = []
        for i, freq in enumerate(freqs):
            box = QVBoxLayout()
            value_label = QLabel("0 dB")
            box.addWidget(value_label, alignment=Qt.AlignmentFlag.AlignHCenter)
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-20, 20)
            slider.setValue(0)
            slider.setMinimumHeight(140)
            box.addWidget(slider, alignment=Qt.AlignmentFlag.AlignHCenter)
            label_text = f"{int(freq)}Hz" if freq < 1000 else f"{freq / 1000:.1f}kHz"
            box.addWidget(QLabel(label_text), alignment=Qt.AlignmentFlag.AlignHCenter)
            bands_layout.addLayout(box)
            self.band_sliders.append(slider)
            self.band_value_labels.append(value_label)
        layout.addLayout(bands_layout)

        self.set_controls_enabled(False)

        self.enable_checkbox.toggled.connect(self.on_enable_toggled)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.preamp_slider.valueChanged.connect(self.on_preamp_changed)
        for i, slider in enumerate(self.band_sliders):
            slider.valueChanged.connect(lambda val, idx=i: self.on_band_changed(idx, val))

    def set_controls_enabled(self, enabled: bool):
        self.preset_combo.setEnabled(enabled)
        self.preamp_slider.setEnabled(enabled)
        for s in self.band_sliders:
            s.setEnabled(enabled)

    def on_enable_toggled(self, enabled: bool):
        self.set_controls_enabled(enabled)
        if enabled:
            self.player.set_equalizer_preamp(float(self.preamp_slider.value()))
            for i, slider in enumerate(self.band_sliders):
                self.player.set_equalizer_band(i, float(slider.value()))
        else:
            self.player.disable_equalizer()

    def on_preset_changed(self, _index: int):
        preset_index = self.preset_combo.currentData()
        if preset_index is None or preset_index < 0:
            return
        self.player.apply_equalizer_preset(preset_index)
        eq = self.player.get_equalizer()
        preamp_val = int(eq.get_preamp())
        self.preamp_slider.blockSignals(True)
        self.preamp_slider.setValue(preamp_val)
        self.preamp_slider.blockSignals(False)
        self.preamp_value_label.setText(f"{preamp_val:+d} dB")
        for i, slider in enumerate(self.band_sliders):
            band_val = int(eq.get_amp_at_index(i))
            slider.blockSignals(True)
            slider.setValue(band_val)
            slider.blockSignals(False)
            self.band_value_labels[i].setText(f"{band_val:+d} dB")

    def on_preamp_changed(self, val: int):
        self.preamp_value_label.setText(f"{val:+d} dB")
        if self.enable_checkbox.isChecked():
            self.player.set_equalizer_preamp(float(val))

    def on_band_changed(self, idx: int, val: int):
        self.band_value_labels[idx].setText(f"{val:+d} dB")
        if self.enable_checkbox.isChecked():
            self.player.set_equalizer_band(idx, float(val))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reproductor Multimedia Pro")
        self.setWindowIcon(QIcon(_icon_path("icon.png")))

        self.player = VLCPlayer()
        self.current_index = -1
        self.dragging_slider = False
        self.repeat_mode = "none"  # none | one | all
        self.shuffle = False
        self.order = PlaylistOrder()
        self._advancing = False
        # Fallos seguidos (archivo roto/inexistente): al completar una vuelta
        # entera sin que nada se pueda reproducir, se detiene en vez de
        # reintentar para siempre (ver _handle_track_finished).
        self._consecutive_failures = 0
        self._max_time_seen_ms = 0
        # Marcadores de la pista actual: (ruta, lista). Leer bookmarks.json
        # en cada tick de 250 ms era innecesario (ver _current_bookmarks).
        self._bookmarks_cache = None
        self._dock_was_visible = True
        self.equalizer_dialog = None
        self.bookmarks_dialog = None
        self.loop_point_a = None
        self.loop_point_b = None
        self.on_finish_action = "none"
        self._known_durations = {}  # ruta -> largo en ms, para mostrarlo en la playlist

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
        self._preview_snapshot_path = os.path.join(tempfile.gettempdir(), "reproductor_multimedia_pro_preview.png")

        # OSD (on-screen display) transitoria sobre el video -- ver _show_osd.
        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.setInterval(1500)

        # Controles flotantes en pantalla completa -- ver _enter_fullscreen /
        # _on_fullscreen_mouse_activity. Reutilizan self.controls_bar en vez
        # de duplicar cada boton.
        self._fullscreen_idle_timer = QTimer(self)
        self._fullscreen_idle_timer.setSingleShot(True)
        self._fullscreen_idle_timer.setInterval(2500)
        self._fullscreen_idle_timer.timeout.connect(self._hide_floating_controls)

        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()

        self._osd_label.hide()
        self._osd_timer.timeout.connect(self._osd_label.hide)

        # Escucha movimientos de mouse en toda la app (no solo en video_frame)
        # para que mover el mouse sobre los propios controles flotantes
        # tambien cuente como actividad y no los oculte mientras se usan.
        QApplication.instance().installEventFilter(self)
        self.video_frame.mouseMoved.connect(self._on_fullscreen_mouse_activity)

        self.player.set_volume(80)
        self.volume_slider.setValue(80)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

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
        central_layout.addWidget(self.video_frame, stretch=1)

        # OSD (ver _show_osd): overlay flotante sobre el video, oculto salvo
        # cuando hay un mensaje transitorio que mostrar.
        self._osd_label = QLabel(self.video_frame)
        self._osd_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 170); color: white; padding: 6px 16px;"
            "border-radius: 8px; font-size: 13pt;"
        )
        self._osd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

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

        self.position_slider.hovered.connect(self._on_slider_hovered)
        self.position_slider.hoverEnded.connect(self._on_slider_hover_ended)

        # Playlist dock
        self.playlist_widget = QListWidget()
        self.playlist_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # itemActivated cubre doble clic Y Enter/Return sobre el item enfocado.
        self.playlist_widget.itemActivated.connect(
            lambda item: self.play_index(self.playlist_widget.row(item))
        )
        self.playlist_widget.installEventFilter(self)
        QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self.playlist_widget,
            activated=self.remove_selected_from_playlist,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        self.playlist_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(self.show_playlist_context_menu)

        self.playlist_dock = QDockWidget("Lista de reproducción", self)
        self.playlist_dock.setWidget(self.playlist_widget)
        self.playlist_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)

        self.statusBar().showMessage("Listo")

    def _enable_mouse_tracking_recursive(self, widget: QWidget):
        """Sin esto, un QWidget solo genera mouseMoveEvent con algun boton
        del mouse presionado; hace falta en cada widget de controls_bar para
        que moverse sobre los controles flotantes en pantalla completa
        cuente como actividad (ver _on_fullscreen_mouse_activity)."""
        widget.setMouseTracking(True)
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)

    def _build_controls_bar(self) -> QWidget:
        bar = QWidget()
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 8)

        seek_row = QHBoxLayout()
        self.label_time_current = QLabel("00:00")
        self.position_slider = PositionSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setToolTip(
            "Arrastra para buscar. Las marcas naranjas son el tramo A-B; las doradas, marcadores nombrados."
        )
        self.label_time_total = QLabel("00:00")
        seek_row.addWidget(self.label_time_current)
        seek_row.addWidget(self.position_slider, stretch=1)
        seek_row.addWidget(self.label_time_total)
        layout.addLayout(seek_row)

        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)

        buttons_row = QHBoxLayout()

        style = self.style()
        self.icon_play = style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.icon_pause = style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)

        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.btn_prev.setToolTip("Pista anterior (Ctrl+Izquierda)")
        self.btn_prev.clicked.connect(self.play_previous)

        self.btn_play = QPushButton()
        self.btn_play.setIcon(self.icon_play)
        self.btn_play.setToolTip("Reproducir/Pausar (Espacio)")
        self.btn_play.clicked.connect(self.toggle_play_pause)

        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.btn_stop.setToolTip("Detener")
        self.btn_stop.clicked.connect(self.stop)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.btn_next.setToolTip("Siguiente pista (Ctrl+Derecha)")
        self.btn_next.clicked.connect(lambda: self.play_next(auto=False))

        for b in (self.btn_prev, self.btn_play, self.btn_stop, self.btn_next):
            buttons_row.addWidget(b)

        buttons_row.addSpacing(16)

        self.btn_mute = QPushButton()
        self.icon_volume = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.icon_muted = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        self.btn_mute.setIcon(self.icon_volume)
        self.btn_mute.setToolTip("Silenciar (M)")
        self.btn_mute.clicked.connect(self.toggle_mute)
        buttons_row.addWidget(self.btn_mute)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 150)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setToolTip("Volumen (flechas arriba/abajo)")
        self.volume_slider.valueChanged.connect(self.player.set_volume)
        buttons_row.addWidget(self.volume_slider)

        self.label_volume_percent = QLabel("80%")
        self.label_volume_percent.setFixedWidth(36)
        self.volume_slider.valueChanged.connect(lambda v: self.label_volume_percent.setText(f"{v}%"))
        buttons_row.addWidget(self.label_volume_percent)

        buttons_row.addSpacing(16)

        buttons_row.addWidget(QLabel("Velocidad:"))
        self.speed_combo = QComboBox()
        for label, value in (("0.5x", 0.5), ("0.75x", 0.75), ("1.0x", 1.0),
                              ("1.25x", 1.25), ("1.5x", 1.5), ("2.0x", 2.0)):
            self.speed_combo.addItem(label, value)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.setToolTip("Velocidad de reproducción")
        self.speed_combo.currentIndexChanged.connect(
            lambda: self.player.set_rate(self.speed_combo.currentData())
        )
        buttons_row.addWidget(self.speed_combo)

        buttons_row.addStretch(1)

        self.btn_shuffle = QPushButton("Aleatorio")
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.setToolTip("Reproducir la playlist en orden aleatorio")
        self.btn_shuffle.toggled.connect(self._on_shuffle_toggled)
        buttons_row.addWidget(self.btn_shuffle)

        self.btn_repeat = QPushButton("Repetir: No")
        self.btn_repeat.setToolTip("Cicla entre No repetir / Repetir todo / Repetir uno")
        self.btn_repeat.clicked.connect(self._cycle_repeat_mode)
        buttons_row.addWidget(self.btn_repeat)

        self.btn_ab_loop = QPushButton("A-B")
        self.btn_ab_loop.setToolTip(
            "Marca un punto A, luego un punto B: repite en bucle solo ese tramo. "
            "Un tercer clic lo desactiva."
        )
        self.btn_ab_loop.clicked.connect(self._on_ab_loop_clicked)
        buttons_row.addWidget(self.btn_ab_loop)

        self.btn_fullscreen = QPushButton()
        self.btn_fullscreen.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
        self.btn_fullscreen.setToolTip("Pantalla completa (F)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        buttons_row.addWidget(self.btn_fullscreen)

        layout.addLayout(buttons_row)

        # Ninguno de estos controles debe quedarse con el foco de teclado:
        # si lo tuvieran, pulsar Espacio o las flechas activaría el propio
        # widget (p. ej. re-pulsar "Detener") en vez de disparar los atajos
        # globales de reproducción/búsqueda definidos en _build_shortcuts.
        for w in (
            self.btn_prev, self.btn_play, self.btn_stop, self.btn_next,
            self.btn_mute, self.position_slider, self.volume_slider,
            self.speed_combo, self.btn_shuffle, self.btn_repeat, self.btn_ab_loop,
            self.btn_fullscreen,
        ):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        return bar

    def _build_menu(self):
        menubar = self.menuBar()

        # -- Archivo --
        menu_file = menubar.addMenu("&Archivo")
        act_open_files = QAction("Abrir archivos...", self, shortcut=QKeySequence.StandardKey.Open)
        act_open_files.triggered.connect(self.open_files)
        menu_file.addAction(act_open_files)

        act_open_folder = QAction("Abrir carpeta...", self)
        act_open_folder.triggered.connect(self.open_folder)
        menu_file.addAction(act_open_folder)

        act_open_url = QAction("Abrir URL...", self, shortcut="Ctrl+U")
        act_open_url.triggered.connect(self.open_url)
        menu_file.addAction(act_open_url)

        self.menu_recent_files = menu_file.addMenu("Abrir reciente")
        self.menu_recent_files.aboutToShow.connect(self._populate_recent_files_menu)

        menu_file.addSeparator()

        act_save_playlist = QAction("Guardar lista (.m3u)...", self)
        act_save_playlist.triggered.connect(self.save_playlist)
        menu_file.addAction(act_save_playlist)

        act_load_playlist = QAction("Cargar lista...", self)
        act_load_playlist.triggered.connect(self.load_playlist)
        menu_file.addAction(act_load_playlist)

        menu_file.addSeparator()

        act_quit = QAction("Salir", self, shortcut=QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        menu_file.addAction(act_quit)

        # -- Reproducción --
        menu_playback = menubar.addMenu("&Reproducción")
        act_play_pause = QAction("Reproducir/Pausa", self, shortcut="Space")
        act_play_pause.triggered.connect(self.toggle_play_pause)
        menu_playback.addAction(act_play_pause)

        act_stop = QAction("Detener", self)
        act_stop.triggered.connect(self.stop)
        menu_playback.addAction(act_stop)

        act_next = QAction("Siguiente", self, shortcut="Ctrl+Right")
        act_next.triggered.connect(lambda: self.play_next(auto=False))
        menu_playback.addAction(act_next)

        act_prev = QAction("Anterior", self, shortcut="Ctrl+Left")
        act_prev.triggered.connect(self.play_previous)
        menu_playback.addAction(act_prev)

        act_next_frame = QAction("Avanzar un fotograma", self, shortcut=".")
        act_next_frame.setToolTip("Avanza un solo fotograma (el video debe estar en pausa)")
        act_next_frame.triggered.connect(self.step_frame)
        menu_playback.addAction(act_next_frame)

        menu_playback.addSeparator()

        self.menu_on_finish = menu_playback.addMenu("Al terminar la lista")
        on_finish_group = QActionGroup(self.menu_on_finish)
        on_finish_group.setExclusive(True)
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
            action.setChecked(key == "none")
            action.triggered.connect(lambda _checked, k=key: setattr(self, "on_finish_action", k))
            on_finish_group.addAction(action)
            self.menu_on_finish.addAction(action)

        menu_playback.addSeparator()

        act_add_bookmark = QAction("Agregar marcador aquí", self, shortcut="B")
        act_add_bookmark.triggered.connect(self.quick_add_bookmark)
        menu_playback.addAction(act_add_bookmark)

        act_show_bookmarks = QAction("Ver marcadores...", self)
        act_show_bookmarks.triggered.connect(self.show_bookmarks)
        menu_playback.addAction(act_show_bookmarks)

        # -- Audio --
        menu_audio = menubar.addMenu("&Audio")
        act_mute = QAction("Silenciar", self, shortcut="M")
        act_mute.triggered.connect(self.toggle_mute)
        menu_audio.addAction(act_mute)

        act_eq = QAction("Ecualizador...", self)
        act_eq.triggered.connect(self.open_equalizer)
        menu_audio.addAction(act_eq)

        self.act_visualizer = QAction("Visualizador de audio (espectro)", self, checkable=True)
        self.act_visualizer.setChecked(True)
        menu_audio.addAction(self.act_visualizer)

        self.menu_audio_tracks = menu_audio.addMenu("Pistas de audio")
        self.menu_audio_tracks.aboutToShow.connect(self._populate_audio_track_menu)

        # -- Video --
        menu_video = menubar.addMenu("&Video")
        act_fullscreen = QAction("Pantalla completa", self, shortcut="F")
        act_fullscreen.triggered.connect(self.toggle_fullscreen)
        menu_video.addAction(act_fullscreen)

        act_snapshot = QAction("Capturar fotograma...", self)
        act_snapshot.triggered.connect(self.take_snapshot)
        menu_video.addAction(act_snapshot)

        menu_video.addSeparator()

        self.menu_subtitle_tracks = menu_video.addMenu("Subtítulos")
        self.menu_subtitle_tracks.aboutToShow.connect(self._populate_subtitle_track_menu)

        act_load_sub = QAction("Cargar subtítulo externo...", self)
        act_load_sub.triggered.connect(self.load_subtitle_file)
        menu_video.addAction(act_load_sub)

        act_search_sub_online = QAction("Buscar subtítulos online...", self)
        act_search_sub_online.triggered.connect(self.search_subtitles_online)
        menu_video.addAction(act_search_sub_online)

        act_sub_delay_earlier = QAction("Adelantar subtítulos 50 ms", self, shortcut="G")
        act_sub_delay_earlier.triggered.connect(lambda: self._adjust_subtitle_delay(-50))
        menu_video.addAction(act_sub_delay_earlier)

        act_sub_delay_later = QAction("Retrasar subtítulos 50 ms", self, shortcut="H")
        act_sub_delay_later.triggered.connect(lambda: self._adjust_subtitle_delay(50))
        menu_video.addAction(act_sub_delay_later)

        act_sub_delay_reset = QAction("Restablecer sincronía de subtítulos", self)
        act_sub_delay_reset.triggered.connect(lambda: self._set_subtitle_delay(0))
        menu_video.addAction(act_sub_delay_reset)

        self.menu_sub_size = menu_video.addMenu("Tamaño de subtítulos")
        sub_size_group = QActionGroup(self.menu_sub_size)
        sub_size_group.setExclusive(True)
        for label, scale in (("Pequeño", 75), ("Normal", 100), ("Grande", 150), ("Muy grande", 200)):
            action = QAction(label, self.menu_sub_size, checkable=True)
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
            action.setChecked(factor == 0.0)
            action.triggered.connect(lambda _checked, f=factor: self.player.set_video_scale(f))
            zoom_group.addAction(action)
            self.menu_zoom.addAction(action)

        self.act_always_on_top = QAction("Siempre visible (encima de otras ventanas)", self, checkable=True)
        self.act_always_on_top.toggled.connect(self._on_always_on_top_toggled)
        menu_video.addAction(self.act_always_on_top)

        # -- Ver --
        menu_view = menubar.addMenu("&Ver")
        act_toggle_playlist = self.playlist_dock.toggleViewAction()
        act_toggle_playlist.setText("Mostrar lista de reproducción")
        menu_view.addAction(act_toggle_playlist)

        # -- Ayuda --
        menu_help = menubar.addMenu("A&yuda")
        act_about = QAction("Acerca de...", self)
        act_about.triggered.connect(self.show_about)
        menu_help.addAction(act_about)

    def _build_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._exit_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self._seek_relative(5000))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self._seek_relative(-5000))
        QShortcut(QKeySequence(Qt.Key.Key_Up), self, activated=lambda: self._nudge_volume(5))
        QShortcut(QKeySequence(Qt.Key.Key_Down), self, activated=lambda: self._nudge_volume(-5))

    # ------------------------------------------------------------ playlist
    def _display_name(self, path: str) -> str:
        if is_url(path):
            return f"🌐 {path}"
        prefix = "🎵" if is_audio_file(path) else "🎬"
        return f"{prefix} {os.path.basename(path)}"

    def add_files_to_playlist(self, paths):
        """Unico punto de entrada a la playlist (dialogos, carpetas, arrastrar
        y soltar, linea de comandos, recientes, .m3u): normaliza aqui cada
        ruta local una sola vez (ver formats.normalize_path)."""
        paths = [normalize_path(p) for p in paths]
        for p in paths:
            item = QListWidgetItem(self._display_name(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.playlist_widget.addItem(item)
        self.order.append(len(paths))

    def _update_playlist_item_duration(self, index: int, path: str, length_ms: int):
        item = self.playlist_widget.item(index)
        if item is not None:
            item.setText(f"{self._display_name(path)} — {format_time(length_ms)}")

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Abrir archivos multimedia", "", build_open_filter()
        )
        if not paths:
            return
        start_index = self.playlist_widget.count()
        self.add_files_to_playlist(paths)
        if self.current_index == -1:
            self.play_index(start_index)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Abrir carpeta")
        if not folder:
            return
        found = []
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in ALL_EXTS:
                    found.append(os.path.join(root, f))
        found.sort()
        if not found:
            QMessageBox.information(self, "Abrir carpeta", "No se encontraron archivos multimedia soportados.")
            return
        start_index = self.playlist_widget.count()
        self.add_files_to_playlist(found)
        if self.current_index == -1:
            self.play_index(start_index)

    def open_url(self):
        url, ok = QInputDialog.getText(self, "Abrir URL", "URL de audio/video o stream (http, rtsp, mms...):")
        if ok and url.strip():
            self.add_files_to_playlist([url.strip()])
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
        path, _ = QFileDialog.getSaveFileName(self, "Guardar lista de reproducción", "playlist.m3u", "Playlist M3U (*.m3u)")
        if not path:
            return
        if not path.lower().endswith((".m3u", ".m3u8")):
            path += ".m3u"
        entries = [
            self.playlist_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.playlist_widget.count())
        ]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(format_m3u(entries))
        except OSError as exc:
            QMessageBox.warning(self, "Guardar lista", f"No se pudo guardar la lista:\n{exc}")

    def load_playlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar lista de reproducción", "", "Playlist (*.m3u *.m3u8);;Todos los archivos (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            QMessageBox.warning(self, "Cargar lista", f"No se pudo leer la lista:\n{exc}")
            return
        entries = parse_m3u(data, path)
        if entries:
            start_index = self.playlist_widget.count()
            self.add_files_to_playlist(entries)
            if self.current_index == -1:
                self.play_index(start_index)

    def show_playlist_context_menu(self, pos):
        item = self.playlist_widget.itemAt(pos)
        menu = QMenu(self)
        act_play = menu.addAction("Reproducir")
        act_remove = menu.addAction("Quitar de la lista")
        menu.addSeparator()
        act_clear = menu.addAction("Vaciar lista")
        act_play.setEnabled(item is not None)
        act_remove.setEnabled(item is not None)
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
        elif chosen == act_clear:
            self.clear_playlist()

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
        for r in reversed(rows):
            self.playlist_widget.takeItem(r)
        self.order.remove(rows)

    def clear_playlist(self):
        self._save_current_position()
        self.playlist_widget.clear()
        self.current_index = -1
        self.player.stop()
        self.player.stop_preview()
        self.order.reset(0)

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
        self.current_index = index
        self.order.jump_to(index)
        self._max_time_seen_ms = 0
        self._bookmarks_cache = None
        if self.player.preview_current_path() not in (None, path):
            self.player.stop_preview()
        self.playlist_widget.setCurrentRow(index)
        self._advancing = False
        self.loop_point_a = None
        self.loop_point_b = None
        self.btn_ab_loop.setText("A-B")
        if self.bookmarks_dialog is not None:
            self.bookmarks_dialog.close()
            self.bookmarks_dialog = None
        self.player.load(path, enable_visualizer=self.act_visualizer.isChecked())
        self.player.attach_video_output(self.video_frame)
        self.player.play()
        self.player.set_rate(self.speed_combo.currentData())
        self.setWindowTitle(f"Reproductor Multimedia Pro — {self._display_name(path)}")
        self.statusBar().showMessage(f"Reproduciendo: {self._display_name(path)}")
        self._maybe_resume_position(path)
        add_recent_file(path)

    def _save_current_position(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            return
        save_position(path, self.player.get_time_ms(), self.player.get_length_ms())

    def _current_path_or_none(self):
        item = self.playlist_widget.item(self.current_index) if self.current_index != -1 else None
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _maybe_resume_position(self, path: str):
        if is_url(path):
            return
        saved_ms = get_saved_position_ms(path)
        if saved_ms:
            self.player.set_time_ms(saved_ms)
            self.statusBar().showMessage(f"Reanudado desde {format_time(saved_ms)}", 4000)

    def toggle_play_pause(self):
        if self.current_index == -1:
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

    def stop(self):
        # Guardar antes: despues de stop() get_time()/get_length() valen -1.
        self._save_current_position()
        self.player.stop()
        self.player.stop_preview()

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
        para siempre, cada 250 ms)."""
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
        if action == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "60"], check=False)
            self.statusBar().showMessage(
                "Lista terminada: el equipo se apagará en 60s (\"shutdown /a\" en una consola para cancelar)", 0
            )
        elif action == "hibernate":
            subprocess.run(["shutdown", "/h"], check=False)
        elif action == "restart":
            subprocess.run(["shutdown", "/r", "/t", "60"], check=False)
            self.statusBar().showMessage(
                "Lista terminada: el equipo se reiniciará en 60s (\"shutdown /a\" en una consola para cancelar)", 0
            )

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

    def _on_shuffle_toggled(self, checked: bool):
        self.shuffle = checked
        self.order.set_shuffle(checked)

    def _cycle_repeat_mode(self):
        order = ["none", "all", "one"]
        labels = {"none": "No", "all": "Todo", "one": "Uno"}
        idx = order.index(self.repeat_mode)
        self.repeat_mode = order[(idx + 1) % len(order)]
        self.btn_repeat.setText(f"Repetir: {labels[self.repeat_mode]}")

    def _on_ab_loop_clicked(self):
        if self.current_index == -1:
            return
        if self.loop_point_a is None:
            self.loop_point_a = self.player.get_time_ms()
            self.btn_ab_loop.setText(f"A: {format_time(self.loop_point_a)}")
        elif self.loop_point_b is None:
            candidate_b = self.player.get_time_ms()
            if candidate_b <= self.loop_point_a:
                self.statusBar().showMessage("El punto B debe ser posterior al punto A", 3000)
                return
            self.loop_point_b = candidate_b
            self.btn_ab_loop.setText(f"A-B: {format_time(self.loop_point_a)}-{format_time(self.loop_point_b)}")
        else:
            self.loop_point_a = None
            self.loop_point_b = None
            self.btn_ab_loop.setText("A-B")

    def _refresh_position_markers(self, length_ms: int):
        markers = []
        if self.loop_point_a is not None:
            markers.append((self.loop_point_a / length_ms, _LOOP_MARKER_COLOR))
        if self.loop_point_b is not None:
            markers.append((self.loop_point_b / length_ms, _LOOP_MARKER_COLOR))
        for b in self._current_bookmarks():
            markers.append((b["position_ms"] / length_ms, _BOOKMARK_MARKER_COLOR))
        self.position_slider.set_markers(markers)

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

    # ------------------------------------------------------------ sliders
    def _on_slider_pressed(self):
        self.dragging_slider = True

    def _on_slider_released(self):
        self.dragging_slider = False
        pos = self.position_slider.value() / 1000.0
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

    def _nudge_volume(self, delta: int):
        self.volume_slider.setValue(max(0, min(150, self.volume_slider.value() + delta)))
        self._show_osd(f"Volumen: {self.volume_slider.value()}%")

    # ------------------------------------------------------------------ OSD
    def _show_osd(self, text: str):
        """Muestra un mensaje breve y semitransparente sobre el video (p. ej.
        "+5s", "Volumen: 65%") que se oculta solo tras ~1.5s. Un unico punto
        de entrada reutilizado por step_frame/_seek_relative/_nudge_volume en
        vez de que cada uno dibuje su propio overlay."""
        self._osd_label.setText(text)
        self._osd_label.adjustSize()
        x = (self.video_frame.width() - self._osd_label.width()) // 2
        y = 24
        self._osd_label.move(max(0, x), y)
        self._osd_label.raise_()
        self._osd_label.show()
        self._osd_timer.start()

    # ------------------------------------------------------- vista previa
    # Buscar-y-capturar en el reproductor secundario (ver
    # VLCPlayer.seek_preview/take_preview_snapshot) no es instantáneo: la
    # búsqueda es asíncrona y libVLC necesita decodificar hasta ese punto
    # antes de que la captura tenga contenido real. Por eso: (1) el hover se
    # debounce con _preview_hover_timer (no se dispara en cada mousemove,
    # solo cuando el mouse se detiene ~300ms sobre la barra), y (2) tras
    # pedir la búsqueda se espera otro instante corto antes de capturar.
    def _on_slider_hovered(self, fraction: float, global_pos: QPoint):
        if self.current_index == -1 or self.player.get_length_ms() <= 0:
            return
        self._pending_hover_fraction = fraction
        self._pending_hover_pos = global_pos
        self._preview_hover_timer.start()

    def _on_slider_hover_ended(self):
        self._preview_hover_timer.stop()
        self._hide_hover_preview()
        if not self.player.is_preview_warmed_up():
            # Todavia no salio ningun fotograma, asi que no se puede pausar
            # sin romper su vout (ver VLCPlayer.load_preview_media): se
            # detiene para que no siga decodificando todo el archivo en
            # segundo plano hasta el proximo hover.
            self.player.stop_preview()

    def _show_hover_preview(self):
        path = self._current_path_or_none()
        if path is None or self._pending_hover_fraction is None or self._pending_hover_pos is None:
            return
        if self.player.preview_current_path() != path:
            self.player.load_preview_media(path)
        self.player.seek_preview(self._pending_hover_fraction)

        if self._preview_popup is None:
            self._preview_popup = QWidget(None, Qt.WindowType.ToolTip)
            self._preview_popup.setStyleSheet("background-color: black; border: 1px solid #888888;")
            popup_layout = QVBoxLayout(self._preview_popup)
            popup_layout.setContentsMargins(2, 2, 2, 2)
            popup_layout.setSpacing(2)
            self._preview_thumbnail_label = QLabel()
            self._preview_thumbnail_label.setFixedSize(160, 90)
            self._preview_thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            popup_layout.addWidget(self._preview_thumbnail_label)
            self._preview_time_label = QLabel()
            self._preview_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._preview_time_label.setStyleSheet("color: white; font-size: 9pt;")
            popup_layout.addWidget(self._preview_time_label)

        # Timestamp que representa la posicion sobre la que esta el mouse
        # (no la del fotograma capturado todavia, que llega despues via
        # _capture_hover_snapshot -- la posicion en si es inmediata).
        self._preview_time_label.setText(format_time(int(self._pending_hover_fraction * self.player.get_length_ms())))

        self._preview_popup.adjustSize()
        self._preview_popup.move(
            self._pending_hover_pos.x() - self._preview_popup.width() // 2,
            self._pending_hover_pos.y() - self._preview_popup.height() - 20,
        )
        self._preview_popup.show()

        # Le da tiempo al reproductor secundario a decodificar el fotograma
        # de la nueva posición antes de intentar capturarlo.
        QTimer.singleShot(180, self._capture_hover_snapshot)

    def _capture_hover_snapshot(self):
        if self._preview_popup is None or not self._preview_popup.isVisible():
            return
        if self.player.take_preview_snapshot(self._preview_snapshot_path, width=160, height=90):
            pixmap = QPixmap(self._preview_snapshot_path)
            if not pixmap.isNull():
                self._preview_thumbnail_label.setPixmap(pixmap)

    def _hide_hover_preview(self):
        if self._preview_popup is not None:
            self._preview_popup.hide()

    def toggle_mute(self):
        muted = not self.player.is_muted()
        self.player.set_muted(muted)
        self.btn_mute.setIcon(self.icon_muted if muted else self.icon_volume)

    # ------------------------------------------------------------ update loop
    def update_ui(self):
        length = self.player.get_length_ms()
        if length > 0 and not self.dragging_slider:
            pos = self.player.get_position()
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(int(pos * 1000))
            self.position_slider.blockSignals(False)
            self.label_time_current.setText(format_time(self.player.get_time_ms()))
            self.label_time_total.setText(format_time(length))
            self._refresh_position_markers(length)

            path = self._current_path_or_none()
            if path is not None and path not in self._known_durations:
                self._known_durations[path] = length
                self._update_playlist_item_duration(self.current_index, path, length)

        self.btn_play.setIcon(self.icon_pause if self.player.is_playing() else self.icon_play)

        if self.loop_point_b is not None and self.player.get_time_ms() >= self.loop_point_b:
            self.player.set_time_ms(self.loop_point_a)

        self.player.apply_pending_restore()

        state = self.player.get_state()
        if state == vlc.State.Playing:
            time_ms = self.player.get_time_ms()
            self._max_time_seen_ms = max(self._max_time_seen_ms, time_ms)
            if time_ms > 0 or length > 0:
                self._consecutive_failures = 0
        if state in (vlc.State.Error, vlc.State.Ended) and not self._advancing and self.current_index != -1:
            self._advancing = True
            try:
                self._handle_track_finished(state)
            finally:
                self._advancing = False

    def _handle_track_finished(self, state):
        failed = playback_failed(
            error_seen=self.player.error_seen(),
            state_is_error=state == vlc.State.Error,
            state_is_ended=state == vlc.State.Ended,
            length_ms=self.player.get_length_ms(),
            max_time_ms=self._max_time_seen_ms,
        )
        path = self._current_path_or_none()
        if failed:
            self._consecutive_failures += 1
            name = self._display_name(path) if path is not None else "?"
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
            self, "Cargar subtítulo", "", "Subtítulos (*.srt *.ass *.ssa *.sub *.vtt);;Todos los archivos (*.*)"
        )
        if path:
            self.player.load_subtitle_file(path)

    def search_subtitles_online(self):
        path = self._current_path_or_none()
        if path is None or is_url(path):
            QMessageBox.information(
                self, "Buscar subtítulos online", "Esta función solo funciona con archivos locales."
            )
            return
        dialog = OnlineSubtitleDialog(path, self)
        dialog.subtitle_ready.connect(self.player.load_subtitle_file)
        dialog.exec()

    def _adjust_subtitle_delay(self, delta_ms: int):
        self._set_subtitle_delay(self.player.get_subtitle_delay_ms() + delta_ms)

    def _set_subtitle_delay(self, delay_ms: int):
        self.player.set_subtitle_delay_ms(delay_ms)
        sign = "+" if delay_ms >= 0 else ""
        self.statusBar().showMessage(f"Sincronía de subtítulos: {sign}{delay_ms} ms", 3000)

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

    def take_snapshot(self):
        if self.current_index == -1:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar captura", "captura.png", "Imagen PNG (*.png)")
        if path:
            self.player.take_snapshot(path)

    # ------------------------------------------------------------ equalizer
    def open_equalizer(self):
        if self.equalizer_dialog is None:
            self.equalizer_dialog = EqualizerDialog(self.player, self)
        self.equalizer_dialog.show()
        self.equalizer_dialog.raise_()
        self.equalizer_dialog.activateWindow()

    # ------------------------------------------------------------ fullscreen
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._dock_was_visible = self.playlist_dock.isVisible()
            self.playlist_dock.setVisible(False)
            self.menuBar().setVisible(False)
            self._float_controls_bar()
            self.showFullScreen()
            self._on_fullscreen_mouse_activity()

    def _exit_fullscreen(self):
        if not self.isFullScreen():
            return
        self._fullscreen_idle_timer.stop()
        self._unfloat_controls_bar()
        self.showNormal()
        self.playlist_dock.setVisible(self._dock_was_visible)
        self.menuBar().setVisible(True)

    # -- controles flotantes (barra de transporte minima en pantalla completa)
    def _float_controls_bar(self):
        """Reparenta controls_bar (en vez de duplicar cada boton) como un
        overlay flotante sobre video_frame, oculto hasta que haya actividad
        de mouse -- ver _on_fullscreen_mouse_activity."""
        self.centralWidget().layout().removeWidget(self.controls_bar)
        self.controls_bar.setParent(self.video_frame)
        self.controls_bar.setStyleSheet("background-color: rgba(20, 20, 20, 200);")
        self.controls_bar.hide()

    def _unfloat_controls_bar(self):
        self.controls_bar.setParent(None)
        self.controls_bar.setStyleSheet("")
        self.centralWidget().layout().addWidget(self.controls_bar)
        self.controls_bar.show()

    def _reposition_floating_controls(self):
        if self.controls_bar.parent() is not self.video_frame:
            return
        height = self.controls_bar.sizeHint().height()
        self.controls_bar.setGeometry(0, self.video_frame.height() - height, self.video_frame.width(), height)
        self.controls_bar.raise_()

    def _show_floating_controls(self):
        if self.controls_bar.parent() is not self.video_frame:
            return
        self._reposition_floating_controls()
        self.controls_bar.show()

    def _hide_floating_controls(self):
        if self.controls_bar.parent() is self.video_frame:
            self.controls_bar.hide()

    def _on_fullscreen_mouse_activity(self):
        if not self.isFullScreen():
            return
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
        if event.type() == QEvent.Type.MouseMove and self.isFullScreen():
            self._on_fullscreen_mouse_activity()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isFullScreen():
            self._reposition_floating_controls()

    def _on_always_on_top_toggled(self, checked: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            local = url.toLocalFile()
            if os.path.isdir(local):
                for root, _dirs, files in os.walk(local):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in ALL_EXTS:
                            paths.append(os.path.join(root, f))
            elif os.path.splitext(local)[1].lower() in ALL_EXTS:
                paths.append(local)
        if paths:
            start_index = self.playlist_widget.count()
            self.add_files_to_playlist(paths)
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
            "Motor de decodificación: libVLC (python-vlc)\n"
            "Interfaz: PySide6\n\n"
            "Soporta prácticamente todos los formatos de audio y video "
            "conocidos por VLC, incluyendo formatos poco comunes.",
        )

    def closeEvent(self, event):
        self._save_current_position()
        self.player.stop()
        self.player.release_preview_player()
        if self._preview_popup is not None:
            self._preview_popup.close()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)
