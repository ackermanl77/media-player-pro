"""Abrir medios en MainWindow (6.6): dialogos de abrir archivos/carpeta,
arrastrar y soltar, mensajes de otra instancia y el escaneo de carpetas en
segundo plano (folder_scan.FolderScanWorker). Mixin, como window_menus."""

import os
from functools import partial

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QFileDialog, QMessageBox

from .folder_scan import FolderScanWorker
from .formats import build_open_filter
from .inputs import dropped_inputs, expand_inputs, needs_scan


class InputsMixin:
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
