"""Construccion de acciones, menus, atajos fijos y menus contextuales de
MainWindow (6.6). Mixin: los metodos usan el estado de la ventana (self.player,
self.action_registry, ...) y se llaman desde MainWindow.__init__ y sus senales."""

import sys

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QMenu

from . import theme
from .backend import libvlc_version
from .formats import format_rate, format_time, is_url
from .recent_files import clear_recent_files, get_recent_files
from .settings import RATE_STEP, REPEAT_MODES, SPEEDS
from .video_options import ASPECT_RATIOS, CROP_RATIOS, DEINTERLACE_LABELS, ROTATIONS

AB_NUDGE_MS = 100         # paso para mover los puntos A/B
REPEAT_LABELS = {"none": "No repetir", "all": "Repetir todo", "one": "Repetir uno"}
AUDIO_DELAY_STEP_MS = 50



class MenusMixin:
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
        # Reproducir en un Chromecast (3.14): la lista se busca al abrir el submenu.
        from .renderers import RendererDiscovery

        self.renderer_discovery = RendererDiscovery(self)
        self.renderer_discovery.changed.connect(self._populate_renderer_menu)
        self.menu_renderers = QMenu("Reproducir en", menu_playback)
        self.menu_renderers.aboutToShow.connect(self._on_renderer_menu_shown)
        menu_playback.addMenu(self.menu_renderers)
        self._populate_renderer_menu()

        # -- Audio --  (A&udio: "&Archivo" ya usa Alt+A)
        menu_audio = menubar.addMenu("A&udio")
        self.menu_audio_tracks = QMenu("Pista de audio", menu_audio)
        self.menu_audio_tracks.aboutToShow.connect(self._populate_audio_track_menu)
        self.menu_audio_device = QMenu("Dispositivo de salida", menu_audio)
        self.menu_audio_device.aboutToShow.connect(self._populate_audio_device_menu)
        # Passthrough a un receptor (3.16): opcion de instancia, como la mejora por GPU.
        self.menu_passthrough = QMenu("Passthrough (receptor por HDMI/S/PDIF)", menu_audio)
        self.menu_passthrough.setToolTipsVisible(True)
        self.passthrough_group = QActionGroup(self)
        for mode, text in (("off", "Desactivado (decodificar en la PC)"), ("ac3_dts", "AC3 y DTS"),
                           ("all", "Todos los formatos (E-AC3, TrueHD, DTS-HD)")):
            action = self.menu_passthrough.addAction(text)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(mode == "off")
            action.setToolTip("Envía el audio comprimido sin decodificar a un receptor o barra de sonido; "
                              "solo si el dispositivo de salida lo admite.")
            self.passthrough_group.addAction(action)
            action.triggered.connect(lambda _checked, m=mode: self._set_audio_passthrough(m))
        R.populate(menu_audio, [
            "mute", "equalizer", "visualizer", "normalize_volume", self.menu_audio_tracks, self.menu_audio_device,
            self.menu_passthrough, None, "audio_earlier", "audio_later", "audio_sync_reset",
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
        self.menu_rotation = self._choice_menu(menu_video, "Rotar / voltear", ROTATIONS, "", self._set_rotation)
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
        # Con los controles del sistema (SMTC) la misma pulsacion puede llegar
        # dos veces (aqui y por SMTC): media_command() descarta la repetida.
        S(Qt.Key.Key_MediaTogglePlayPause, "Tecla multimedia Reproducir/Pausar", lambda: self.media_command("toggle"))
        S(Qt.Key.Key_MediaPlay, "Tecla multimedia Reproducir", lambda: self.media_command("play"))
        S(Qt.Key.Key_MediaPause, "Tecla multimedia Pausa", lambda: self.media_command("pause"))
        S(Qt.Key.Key_MediaStop, "Tecla multimedia Detener", lambda: self.media_command("stop"))
        S(Qt.Key.Key_MediaNext, "Tecla multimedia Siguiente", lambda: self.media_command("next"))
        S(Qt.Key.Key_MediaPrevious, "Tecla multimedia Anterior", lambda: self.media_command("previous"))
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

    def _show_video_context_menu(self, global_pos: QPoint):
        self.video_context_menu.popup(global_pos)

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

    def _on_renderer_menu_shown(self):
        if not self.renderer_discovery.running and not self.renderer_discovery.start():
            self.statusBar().showMessage("No se pudo buscar dispositivos en la red", 4000)
        # Los dispositivos responden en unos segundos: la busqueda sigue un rato.
        QTimer.singleShot(30_000, self.renderer_discovery.stop)
        self._populate_renderer_menu()

    def _populate_renderer_menu(self):
        menu = self.menu_renderers
        menu.clear()
        current = self.player.get_renderer()
        local = menu.addAction("Esta PC")
        local.setCheckable(True)
        local.setChecked(current is None)
        local.triggered.connect(lambda _checked: self.cast_to(None))
        renderers = self.renderer_discovery.renderers()
        if renderers:
            menu.addSeparator()
        for renderer in renderers:
            action = menu.addAction(renderer.name + ("" if renderer.can_video else " (solo audio)"))
            action.setCheckable(True)
            action.setChecked(current is not None and current.key == renderer.key)
            action.triggered.connect(lambda _checked, r=renderer: self.cast_to(r))
        if not renderers:
            searching = menu.addAction("Buscando dispositivos (Chromecast)…" if self.renderer_discovery.running
                                       else "Ningún dispositivo encontrado")
            searching.setEnabled(False)

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
