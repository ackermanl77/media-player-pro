"""Lanzadores de dialogos de MainWindow (6.6): abrir URL, listas M3U,
marcadores, ir a un tiempo, subtitulos, capturas, ecualizador, ajustes de
imagen, informacion del medio, Acerca de, carpeta de registros. Mixin, como
window_menus."""

import os

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from . import __version__
from .backend import libvlc_version
from .bookmarks_dialog import BookmarksDialog
from .equalizer_dialog import EqualizerDialog
from .formats import format_time, is_url, parse_time_input, path_key, snapshot_file_name
from .logs import current_log_dir
from .media_info_dialog import MediaInfoDialog
from .m3u import load_playlist as load_m3u_playlist
from .m3u import save_playlist as save_m3u_playlist
from .subtitle_dialog import OnlineSubtitleDialog
from .url_dialog import OpenUrlDialog
from .video_adjust_dialog import VideoAdjustDialog


class DialogsMixin:
    def show_shortcuts_help(self):
        """Ayuda -> Atajos de teclado: la tabla, editable (player/shortcuts_dialog.py)."""
        from .shortcuts_dialog import ShortcutsDialog

        dialog = ShortcutsDialog(self.action_registry, on_changed=self.save_settings_now, parent=self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.shortcuts_dialog = dialog
        dialog.show()

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

    def open_url(self):
        dialog = OpenUrlDialog(self.player.network_caching_ms, self.player.rtsp_tcp, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.player.network_caching_ms = dialog.network_caching_ms()
        self.player.rtsp_tcp = dialog.rtsp_tcp()
        self.play_index(self.playlist.add([dialog.url()]))

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

    def open_equalizer(self):
        if self.equalizer_dialog is None:
            self.equalizer_dialog = EqualizerDialog(self.player, self, initial=self.settings.equalizer)
        self.equalizer_dialog.show()
        self.equalizer_dialog.raise_()
        self.equalizer_dialog.activateWindow()

    def open_video_adjust(self):
        if self.video_adjust_dialog is None:
            self.video_adjust_dialog = VideoAdjustDialog(self.player, self)
        self.video_adjust_dialog.show()
        self.video_adjust_dialog.raise_()
        self.video_adjust_dialog.activateWindow()

    def show_media_info(self):
        details = self.player.media_details()
        if details is None:
            self.statusBar().showMessage("No hay nada abierto", 3000)
            return None
        dialog = MediaInfoDialog(details, self)
        dialog.show()
        return dialog

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

    def show_update(self, info):
        """Hay una versión nueva (player/update_check.py; run.py busca una vez al arrancar)."""
        self.statusBar().showMessage(f"Reproductor Multimedia Pro {info.version} ya está disponible", 15000)
        notes = f"\n\n{info.notes}" if info.notes else ""
        answer = QMessageBox.question(
            self, "Actualización disponible",
            f"Ya está disponible Reproductor Multimedia Pro {info.version} (tienes la {__version__}).{notes}"
            "\n\n¿Abrir la página de descarga?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(info.url))

    def open_log_folder(self):
        folder = current_log_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
