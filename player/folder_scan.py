"""Escaneo de carpetas fuera del hilo principal.

La logica de recorrido vive en player.inputs.scan_folder_batches() (pura,
sin Qt). Este modulo solo la ejecuta en un QObject para moverlo a un
QThread y emitir resultados por senales."""

from PySide6.QtCore import QObject, Signal, Slot

from .inputs import scan_folder_batches


class FolderScanWorker(QObject):
    batchFound = Signal(list)
    finished = Signal(list)
    cancelled = Signal(list)
    failed = Signal(str)

    def __init__(self, folder: str, batch_size: int = 200):
        super().__init__()
        self.folder = folder
        self.batch_size = batch_size
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    @Slot()
    def run(self) -> None:
        found = []
        try:
            for batch in scan_folder_batches(self.folder, batch_size=self.batch_size, should_stop=self.is_cancelled):
                if self._cancelled:
                    break
                found.extend(batch)
                self.batchFound.emit(list(batch))
        except OSError as exc:
            self.failed.emit(str(exc))
            return
        if self._cancelled:
            self.cancelled.emit(found)
        else:
            self.finished.emit(found)
