"""Archivo > Abrir disco / Abrir carpeta compartida / Explorar la red local
(3.18), Archivo > Convertir / extraer audio y Reproduccion > Grabar (3.19).
Mixin de MainWindow, como window_dialogs."""

import os

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QDialog, QMessageBox

from .converter import recording_path
from .convert_dialog import ConvertDialog
from .formats import is_url
from .sources_dialog import NetworkBrowserDialog, OpenDiscDialog, OpenShareDialog


class SourcesMixin:
    def open_disc(self):
        dialog = OpenDiscDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            mrl = dialog.mrl()
        except ValueError as error:
            QMessageBox.warning(self, "Abrir disco", str(error).capitalize())
            return
        self.play_index(self.playlist.add([mrl]))

    def open_share(self):
        dialog = OpenShareDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        url = dialog.url()
        # La contrasena queda solo en memoria (opciones del Media), nunca en la lista.
        self.player.set_share_credentials(url, dialog.media_options())
        self.play_index(self.playlist.add([url]))

    def browse_network(self):
        if getattr(self, "network_browser", None) is not None and self.network_browser.isVisible():
            self.network_browser.raise_()
            return
        dialog = NetworkBrowserDialog(lambda mrl: self.play_index(self.playlist.add([mrl])), self)
        self.network_browser = dialog
        dialog.show()
        dialog.start()

    def open_convert_dialog(self):
        source = self._current_path_or_none() or ""
        options = self.player._share_options(source) if source and is_url(source) else []
        dialog = ConvertDialog(source, self, media_options=options)
        self.convert_dialog = dialog
        dialog.show()

    # -- Reproduccion > Grabar (3.19) ----------------------------------------------
    def _recordings_dir(self) -> str:
        movies = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation)
        return os.path.join(movies or os.path.expanduser("~"), "Reproductor Multimedia Pro")

    def toggle_recording(self, checked: bool):
        path = self._current_path_or_none()
        if checked and (path is None or self.current_index == -1):
            self.act_record.setChecked(False)
            self._show_osd("Nada que grabar")
            return
        if checked:
            folder = self._recordings_dir()
            os.makedirs(folder, exist_ok=True)
            target = recording_path(folder, self._display_name(path))
            self.player.set_recording(target)
            self.player.reload_preserving_state()
            self._show_osd("● Grabando")
            self.statusBar().showMessage(f"Grabando en {target}", 8000)
        else:
            target = self.player.recording_path()
            self.player.set_recording(None)
            self.player.reload_preserving_state()
            self._show_osd("Grabación detenida")
            if target:
                self.statusBar().showMessage(f"Grabación guardada: {target}", 10000)

    def _stop_recording_quietly(self):
        """Al cambiar de pista se deja de grabar (cada grabacion es un archivo)."""
        if self.player.recording_path():
            self.player.set_recording(None)
            self.act_record.blockSignals(True)
            self.act_record.setChecked(False)
            self.act_record.blockSignals(False)
