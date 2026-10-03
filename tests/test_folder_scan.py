"""Worker de escaneo en segundo plano: usa Qt pero no VLC."""

from player.folder_scan import FolderScanWorker


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return str(path)


def test_folder_scan_worker_emits_batches_and_finished(tmp_path):
    first = _touch(tmp_path / "a.mp3")
    second = _touch(tmp_path / "sub" / "b.mkv")
    worker = FolderScanWorker(str(tmp_path), batch_size=1)
    batches = []
    finished = []
    worker.batchFound.connect(lambda batch: batches.append(batch))
    worker.finished.connect(lambda found: finished.append(found))

    worker.run()

    assert batches == [[first], [second]]
    assert finished == [[first, second]]


def test_results_reach_a_qobject_slot_on_the_main_thread(tmp_path):
    """Same wiring as MainWindow._start_folder_scan: the worker runs in a
    QThread and its signals must land on the main (GUI) thread."""
    from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QThread, QTimer

    app = QCoreApplication.instance() or QCoreApplication([])
    _touch(tmp_path / "a.mp3")

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.threads = []

        def on_finished(self, found):
            self.threads.append(QThread.currentThread())

    receiver = Receiver()
    thread = QThread()
    worker = FolderScanWorker(str(tmp_path))
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(receiver.on_finished)
    worker.finished.connect(thread.quit)
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    thread.start()
    loop.exec()
    thread.wait(2000)
    app.processEvents()

    assert receiver.threads == [app.thread()]


def test_main_window_connects_scan_results_to_methods_not_lambdas():
    import inspect

    from player import main_window

    source = inspect.getsource(main_window.MainWindow._start_folder_scan)
    for signal in ("finished", "cancelled", "batchFound", "failed"):
        assert f"worker.{signal}.connect(lambda" not in source


def test_folder_scan_worker_can_be_cancelled(tmp_path):
    first = _touch(tmp_path / "a.mp3")
    _touch(tmp_path / "b.mp3")
    worker = FolderScanWorker(str(tmp_path), batch_size=1)
    cancelled = []

    def on_batch(_batch):
        worker.cancel()

    worker.batchFound.connect(on_batch)
    worker.cancelled.connect(lambda found: cancelled.append(found))

    worker.run()

    assert cancelled == [[first]]
