"""Ciclo de vida de la busqueda/descarga de subtitulos online (3.11), sin
red: las funciones de opensubtitles se reemplazan por dobles."""
import os
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from player import config
from player import subtitle_dialog as sd
from player.opensubtitles import DownloadResult


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _collect(signal):
    got = []
    signal.connect(lambda *args: got.append(args))
    return got


@pytest.mark.parametrize("error", [OSError("disco"), ValueError("json"), KeyError("file_id")])
def test_search_thread_reports_any_error_instead_of_hanging(qapp, monkeypatch, error):
    def boom(*_a, **_k):
        raise error

    monkeypatch.setattr(sd, "compute_opensubtitles_hash", boom)
    thread = sd._SearchThread("key", "C:/v/peli.mkv", "es")
    failed, ok = _collect(thread.failed), _collect(thread.succeeded)
    thread.run()  # en este hilo, sincronico
    assert len(failed) == 1 and ok == []


def test_download_thread_reports_errors(qapp, monkeypatch):
    def boom(*_a):
        raise PermissionError("ro")

    monkeypatch.setattr(sd, "download_subtitle_file", boom)
    thread = sd._DownloadThread("key", 1, "x.srt")
    failed = _collect(thread.failed)
    thread.run()
    assert failed == [("ro",)]


def test_destination_uses_the_result_extension_and_temp_when_read_only(tmp_path):
    video = str(tmp_path / "Peli.mkv")
    assert sd.destination_path(video, "es", "Peli.ES.ass") == str(tmp_path / "Peli.es.ass")
    assert sd.destination_path(video, "en", "") == str(tmp_path / "Peli.en.srt")
    temp = sd.destination_path(video, "es", "a.vtt", writable=False)
    try:
        assert temp.endswith(".es.vtt") and os.path.dirname(temp) != str(tmp_path)
    finally:
        os.remove(temp)
    assert sd.plural(1, "resultado", "resultados") == "1 resultado"
    assert sd.plural(3, "descarga", "descargas") == "3 descargas"


def _dialog_with_one_result(tmp_path):
    config.set_opensubtitles_api_key("key")
    video = tmp_path / "peli.mkv"
    video.write_bytes(b"x")
    dialog = sd.OnlineSubtitleDialog(str(video), auto_search=False)
    dialog._on_search_succeeded([{"file_id": 5, "language": "es", "release": "Peli", "download_count": 1,
                                  "file_name": "peli.srt"}])
    dialog.list_widget.setCurrentRow(0)
    return dialog, str(video)


def test_a_late_download_after_closing_is_discarded(qapp, monkeypatch, tmp_path):
    release = threading.Event()

    def slow_download(_key, _file_id, dest):
        release.wait(5)
        with open(dest, "w", encoding="utf-8") as f:
            f.write("1\n")
        return DownloadResult(dest, 3, "")

    monkeypatch.setattr(sd, "download_subtitle_file", slow_download)
    dialog, _video = _dialog_with_one_result(tmp_path)
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    ready = _collect(dialog.subtitle_ready)
    dialog._on_download_clicked()
    thread = dialog._download_thread
    assert thread is not None and thread.parent() is None  # no muere con el dialogo
    assert sd.running_subtitle_jobs() == 1
    dialog.reject()  # el usuario cierra mientras descarga
    release.set()
    assert sd.wait_for_subtitle_jobs(5000)
    QApplication.processEvents()
    assert ready == []


def test_a_finished_download_reports_the_source_video_and_quota(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(sd, "download_subtitle_file", lambda _k, _f, dest: DownloadResult(dest, 9, "mañana"))
    dialog, video = _dialog_with_one_result(tmp_path)
    ready, status = _collect(dialog.subtitle_ready), _collect(dialog.status_message)
    dialog._on_download_clicked()
    assert sd.wait_for_subtitle_jobs(5000)
    QApplication.processEvents()
    assert ready == [(video, os.path.splitext(video)[0] + ".es.srt")]
    assert "Descargas restantes hoy: 9" in status[0][0]


def test_existing_subtitle_is_not_overwritten_without_asking(qapp, monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(sd, "_track", lambda thread: started.append(thread))
    monkeypatch.setattr(sd.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    dialog, video = _dialog_with_one_result(tmp_path)
    with open(os.path.splitext(video)[0] + ".es.srt", "w", encoding="utf-8") as f:
        f.write("mio\n")
    dialog._on_download_clicked()
    assert started == []
    dialog.close()


def test_languages_are_normalized_and_persisted(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(sd, "_track", lambda thread: None)
    dialog, _video = _dialog_with_one_result(tmp_path)
    dialog.languages_edit.setText("PT-br; es")
    dialog._start_search()
    assert config.get_subtitle_languages() == "pt-br,es"
    assert dialog.languages_edit.text() == "pt-br,es"
    dialog.close()
