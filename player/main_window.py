import os
import random
import subprocess
import sys

import vlc
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from .backend import VLCPlayer
from .formats import ALL_EXTS, build_open_filter, format_time, is_url
from .resume import clear_position, get_saved_position_ms, save_position
from .subtitle_dialog import OnlineSubtitleDialog


class VideoFrame(QFrame):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


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
        self.preamp_slider = QSlider(Qt.Orientation.Vertical)
        self.preamp_slider.setRange(-20, 20)
        self.preamp_slider.setValue(0)
        self.preamp_slider.setMinimumHeight(140)
        preamp_box.addWidget(self.preamp_slider, alignment=Qt.AlignmentFlag.AlignHCenter)
        preamp_box.addWidget(QLabel("Preamp"), alignment=Qt.AlignmentFlag.AlignHCenter)
        bands_layout.addLayout(preamp_box)

        self.band_sliders = []
        for i, freq in enumerate(freqs):
            box = QVBoxLayout()
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-20, 20)
            slider.setValue(0)
            slider.setMinimumHeight(140)
            box.addWidget(slider, alignment=Qt.AlignmentFlag.AlignHCenter)
            label_text = f"{int(freq)}Hz" if freq < 1000 else f"{freq / 1000:.1f}kHz"
            box.addWidget(QLabel(label_text), alignment=Qt.AlignmentFlag.AlignHCenter)
            bands_layout.addLayout(box)
            self.band_sliders.append(slider)
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
        self.preamp_slider.blockSignals(True)
        self.preamp_slider.setValue(int(eq.get_preamp()))
        self.preamp_slider.blockSignals(False)
        for i, slider in enumerate(self.band_sliders):
            slider.blockSignals(True)
            slider.setValue(int(eq.get_amp_at_index(i)))
            slider.blockSignals(False)

    def on_preamp_changed(self, val: int):
        if self.enable_checkbox.isChecked():
            self.player.set_equalizer_preamp(float(val))

    def on_band_changed(self, idx: int, val: int):
        if self.enable_checkbox.isChecked():
            self.player.set_equalizer_band(idx, float(val))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reproductor Multimedia Pro")

        self.player = VLCPlayer()
        self.current_index = -1
        self.dragging_slider = False
        self.repeat_mode = "none"  # none | one | all
        self.shuffle = False
        self._advancing = False
        self._dock_was_visible = True
        self.equalizer_dialog = None
        self.loop_point_a = None
        self.loop_point_b = None
        self.on_finish_action = "none"

        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()

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
        self.video_frame.doubleClicked.connect(self.toggle_fullscreen)
        central_layout.addWidget(self.video_frame, stretch=1)

        self.controls_bar = self._build_controls_bar()
        central_layout.addWidget(self.controls_bar)

        self.setCentralWidget(central)

        # Playlist dock
        self.playlist_widget = QListWidget()
        self.playlist_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.playlist_widget.itemDoubleClicked.connect(
            lambda item: self.play_index(self.playlist_widget.row(item))
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

    def _build_controls_bar(self) -> QWidget:
        bar = QWidget()
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 8)

        seek_row = QHBoxLayout()
        self.label_time_current = QLabel("00:00")
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
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
        self.btn_prev.clicked.connect(self.play_previous)

        self.btn_play = QPushButton()
        self.btn_play.setIcon(self.icon_play)
        self.btn_play.clicked.connect(self.toggle_play_pause)

        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.btn_stop.clicked.connect(self.stop)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.btn_next.clicked.connect(lambda: self.play_next(auto=False))

        for b in (self.btn_prev, self.btn_play, self.btn_stop, self.btn_next):
            buttons_row.addWidget(b)

        buttons_row.addSpacing(16)

        self.btn_mute = QPushButton()
        self.icon_volume = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.icon_muted = style.standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        self.btn_mute.setIcon(self.icon_volume)
        self.btn_mute.clicked.connect(self.toggle_mute)
        buttons_row.addWidget(self.btn_mute)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 150)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.valueChanged.connect(self.player.set_volume)
        buttons_row.addWidget(self.volume_slider)

        buttons_row.addSpacing(16)

        buttons_row.addWidget(QLabel("Velocidad:"))
        self.speed_combo = QComboBox()
        for label, value in (("0.5x", 0.5), ("0.75x", 0.75), ("1.0x", 1.0),
                              ("1.25x", 1.25), ("1.5x", 1.5), ("2.0x", 2.0)):
            self.speed_combo.addItem(label, value)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.currentIndexChanged.connect(
            lambda: self.player.set_rate(self.speed_combo.currentData())
        )
        buttons_row.addWidget(self.speed_combo)

        buttons_row.addStretch(1)

        self.btn_shuffle = QPushButton("Aleatorio")
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.toggled.connect(self._on_shuffle_toggled)
        buttons_row.addWidget(self.btn_shuffle)

        self.btn_repeat = QPushButton("Repetir: No")
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
        return path if is_url(path) else os.path.basename(path)

    def add_files_to_playlist(self, paths):
        for p in paths:
            item = QListWidgetItem(self._display_name(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.playlist_widget.addItem(item)

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

    def save_playlist(self):
        if self.playlist_widget.count() == 0:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar lista de reproducción", "playlist.m3u", "Playlist M3U (*.m3u)")
        if not path:
            return
        if not path.lower().endswith(".m3u"):
            path += ".m3u"
        with open(path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for i in range(self.playlist_widget.count()):
                f.write(self.playlist_widget.item(i).data(Qt.ItemDataRole.UserRole) + "\n")

    def load_playlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar lista de reproducción", "", "Playlist (*.m3u *.m3u8);;Todos los archivos (*.*)"
        )
        if not path:
            return
        entries = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                entries.append(line)
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
        chosen = menu.exec(self.playlist_widget.mapToGlobal(pos))
        if chosen == act_play and item is not None:
            self.play_index(self.playlist_widget.row(item))
        elif chosen == act_remove and item is not None:
            row = self.playlist_widget.row(item)
            self.playlist_widget.takeItem(row)
            if row == self.current_index:
                self.current_index = -1
                self.player.stop()
            elif row < self.current_index:
                self.current_index -= 1
        elif chosen == act_clear:
            self.playlist_widget.clear()
            self.current_index = -1
            self.player.stop()

    # ------------------------------------------------------------ transport
    def play_index(self, index: int):
        item = self.playlist_widget.item(index)
        if item is None:
            return
        self._save_current_position()
        path = item.data(Qt.ItemDataRole.UserRole)
        self.current_index = index
        self.playlist_widget.setCurrentRow(index)
        self._advancing = False
        self.loop_point_a = None
        self.loop_point_b = None
        self.btn_ab_loop.setText("A-B")
        self.player.load(path, enable_visualizer=self.act_visualizer.isChecked())
        self.player.attach_video_output(self.video_frame)
        self.player.play()
        self.player.set_rate(self.speed_combo.currentData())
        self.setWindowTitle(f"Reproductor Multimedia Pro — {self._display_name(path)}")
        self.statusBar().showMessage(f"Reproduciendo: {self._display_name(path)}")
        self._maybe_resume_position(path)

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
                self.play_index(0)
            return
        self.player.toggle_pause()

    def stop(self):
        self.player.stop()

    def play_next(self, auto: bool):
        count = self.playlist_widget.count()
        if count == 0:
            return
        if self.repeat_mode == "one" and auto:
            self.play_index(self.current_index)
            return
        if self.shuffle:
            next_index = self.current_index
            if count > 1:
                while next_index == self.current_index:
                    next_index = random.randint(0, count - 1)
            else:
                next_index = 0
        else:
            next_index = self.current_index + 1
            if next_index >= count:
                if self.repeat_mode == "all":
                    next_index = 0
                elif auto:
                    self.player.stop()
                    self._handle_playlist_finished()
                    return
                else:
                    return
        self.play_index(next_index)

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
        prev_index = self.current_index - 1
        if prev_index < 0:
            if self.repeat_mode == "all":
                prev_index = self.playlist_widget.count() - 1
            else:
                self.player.set_time_ms(0)
                return
        self.play_index(prev_index)

    def _on_shuffle_toggled(self, checked: bool):
        self.shuffle = checked

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

    def _nudge_volume(self, delta: int):
        self.volume_slider.setValue(max(0, min(150, self.volume_slider.value() + delta)))

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

        self.btn_play.setIcon(self.icon_pause if self.player.is_playing() else self.icon_play)

        if self.loop_point_b is not None and self.player.get_time_ms() >= self.loop_point_b:
            self.player.set_time_ms(self.loop_point_a)

        state = self.player.get_state()
        if state == vlc.State.Error and not self._advancing and self.current_index != -1:
            failed_item = self.playlist_widget.item(self.current_index)
            failed_name = self._display_name(failed_item.data(Qt.ItemDataRole.UserRole)) if failed_item else "?"
            self.statusBar().showMessage(f"No se pudo reproducir: {failed_name}", 5000)
            self._advancing = True
            self.play_next(auto=True)
            self._advancing = False
        elif state == vlc.State.Ended and not self._advancing and self.current_index != -1:
            # Se vio/escuchó completo: la próxima vez que se abra, empieza de
            # nuevo en vez de "reanudar" a un segundo del final.
            finished_path = self._current_path_or_none()
            if finished_path is not None and not is_url(finished_path):
                clear_position(finished_path)
            self._advancing = True
            self.play_next(auto=True)
            self._advancing = False

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
        # que recrear el Instance (VLCPlayer.load() lo hace solo), lo que
        # implica recargar el archivo actual. Se preserva posición y estado
        # de pausa para que el cambio se sienta transparente.
        was_playing = self.player.is_playing()
        position = self.player.get_position()
        self.play_index(self.current_index)
        if position > 0:
            self.player.set_position(position)
        if not was_playing:
            self.player.set_paused(True)

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
            self.controls_bar.setVisible(False)
            self.showFullScreen()

    def _exit_fullscreen(self):
        if not self.isFullScreen():
            return
        self.showNormal()
        self.playlist_dock.setVisible(self._dock_was_visible)
        self.menuBar().setVisible(True)
        self.controls_bar.setVisible(True)

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
            "Reproductor de música y video de alta calidad.\n\n"
            "Motor de decodificación: libVLC (python-vlc)\n"
            "Interfaz: PySide6\n\n"
            "Soporta prácticamente todos los formatos de audio y video "
            "conocidos por VLC, incluyendo formatos poco comunes.",
        )

    def closeEvent(self, event):
        self._save_current_position()
        self.player.stop()
        super().closeEvent(event)
