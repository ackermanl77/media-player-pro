"""Modelo/vista de la lista (playlist_model.py) y su controlador
(playlist_controller.py), sin VLC: el analisis de metadatos se reemplaza
por uno falso. Qt "offscreen"; no se simulan teclas ni mouse: se llama a
los mismos metodos que usa la vista."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from player.formats import normalize_path
from player.playlist_controller import PlaylistController
from player.playlist_model import (
    DURATION_ROLE,
    ITEM_ID_ROLE,
    NOW_PLAYING_ROLE,
    PATH_ROLE,
    PlaylistModel,
    PlaylistView,
    moved_order,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class FakeProbe:
    def __init__(self, on_parsed):
        self.on_parsed = on_parsed
        self.probed = []
        self.closed = False

    def pending_count(self):
        return 0

    def probe(self, path):
        self.probed.append(path)
        return True

    def close(self):
        self.closed = True


@pytest.fixture
def controller(qapp):
    c = PlaylistController(probe_factory=FakeProbe)
    yield c
    c.close()


def _names(controller):
    return [os.path.basename(p) for p in controller.entries()]


def _fake(*names):
    return [f"C:/fake/{n}" for n in names]


def test_moved_order_inserts_the_dragged_rows_before_the_target():
    assert moved_order(4, [1], 4) == [0, 2, 3, 1]
    assert moved_order(4, [3], 0) == [3, 0, 1, 2]
    assert moved_order(5, [0, 2], 4) == [1, 3, 0, 2, 4]
    assert moved_order(3, [1], 1) == [0, 1, 2]  # soltar sobre si misma
    assert moved_order(3, [1], 2) == [0, 1, 2]
    assert moved_order(3, [7, -1], 0) == [0, 1, 2]


def test_model_roles_marker_and_ids(qapp):
    model = PlaylistModel()
    model.append_paths([os.path.normpath("C:/fake/a.mp3"), "http://radio/x"])
    assert model.rowCount() == 2
    assert model.index(0).data(PATH_ROLE) == os.path.normpath("C:/fake/a.mp3")
    assert model.index(0).data(Qt.ItemDataRole.ToolTipRole) == os.path.normpath("C:/fake/a.mp3")
    assert model.index(0).data() == "🎵 a.mp3" and model.index(1).data() == "🌐 http://radio/x"
    assert [model.index(r).data(ITEM_ID_ROLE) for r in range(2)] == [0, 1]
    model.set_current_row(1)
    assert model.index(1).data().startswith("▶ ") and model.index(1).data(NOW_PLAYING_ROLE)
    assert model.index(1).data(Qt.ItemDataRole.FontRole).bold()
    assert model.index(0).data(Qt.ItemDataRole.FontRole) is None
    assert model.set_icy_title("http://radio/x", "Tema") and model.index(1).data() == "▶ 🌐 Tema"
    assert not model.set_icy_title("http://radio/x", "Tema")
    model.set_duration(os.path.normpath("C:/fake/a.mp3"), 61_000)
    assert model.index(0).data() == "🎵 a.mp3 — 01:01" and model.index(0).data(DURATION_ROLE) == 61_000
    model.set_tags(os.path.normpath("C:/fake/a.mp3"), "Artista", "Titulo")
    assert model.index(0).data() == "🎵 Artista — Titulo — 01:01"


def test_model_flags_allow_dropping_only_between_rows(qapp):
    model = PlaylistModel()
    model.append_paths(["C:/a.mp3"])
    assert model.flags(model.index(0)) & Qt.ItemFlag.ItemIsDragEnabled
    assert not model.flags(model.index(0)) & Qt.ItemFlag.ItemIsDropEnabled
    assert model.flags(model.index(-1)) & Qt.ItemFlag.ItemIsDropEnabled
    assert model.supportedDropActions() == Qt.DropAction.MoveAction


def test_reorder_keeps_selection_current_shuffle_and_session_row(controller):
    controller.add(_fake("a.mp3", "b.mp3", "c.mp3", "d.mp3"))
    view = PlaylistView()
    view.setModel(controller.proxy)
    view.set_source_rows_selected([1])
    controller.current_index = 1
    controller.order.jump_to(1)
    controller.session_row = 2
    controller.order.set_shuffle(True)
    upcoming = [controller.entries()[i] for i in controller.order.upcoming()]
    saves = []
    controller.contentsChanged.connect(lambda: saves.append(1))
    controller.move_rows([1], 4)
    assert _names(controller) == ["a.mp3", "c.mp3", "d.mp3", "b.mp3"]
    assert controller.current_index == 3 and controller.order.current == 3
    assert controller.session_row == 1  # "c.mp3" sigue siendo la de la sesion
    assert view.selected_source_rows() == [3]  # la seleccion sigue a "b.mp3"
    assert [controller.entries()[i] for i in controller.order.upcoming()] == upcoming
    assert saves == [1]


def test_sort_by_name_and_path_is_natural_and_keeps_current(controller):
    controller.add(["C:/z/Pista 10.mp3", "C:/a/Pista 2.mp3", "C:/m/otra.mp3"])
    controller.current_index = 0
    controller.sort("name")
    assert _names(controller) == ["otra.mp3", "Pista 2.mp3", "Pista 10.mp3"]
    assert controller.current_index == 2
    controller.sort("path")
    # normalize_path(): the same "C:/..." is absolute on Windows, cwd-relative on Linux.
    assert controller.entries() == [
        normalize_path(p) for p in ("C:/a/Pista 2.mp3", "C:/m/otra.mp3", "C:/z/Pista 10.mp3")]
    assert controller.current_index == 2


def test_filter_proxy_follows_new_tags_and_maps_rows(controller):
    controller.add(_fake("uno.mp3", "dos.mp3", "tres.mp3"))
    controller.set_filter("  BEATLES ")
    assert controller.visible_rows() == [] and controller.first_visible_row() == -1
    controller.model.set_tags(os.path.normpath("C:/fake/dos.mp3"), "The Beatles", "Help")
    assert controller.visible_rows() == [1] and controller.first_visible_row() == 1
    controller.set_filter("")
    assert controller.visible_rows() == [0, 1, 2]


def test_remove_rows_updates_current_session_and_order(controller):
    controller.add(_fake("a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3"))
    controller.current_index = 3
    controller.order.jump_to(3)
    controller.session_row = 4
    assert controller.remove_rows([0, 2, 9]) == [0, 2]
    assert _names(controller) == ["b.mp3", "d.mp3", "e.mp3"]
    assert controller.current_index == 1 and controller.order.current == 1
    assert controller.session_row == 2
    controller.remove_rows([1])
    assert controller.current_index == -1
    assert controller.order.advance(repeat_all=False) == 1  # la que tomo su lugar


def test_metadata_is_queued_for_local_files_and_totalled(controller, tmp_path):
    real = tmp_path / "a.wav"
    real.write_bytes(b"x")
    titles = []
    controller.summaryChanged.connect(titles.append)
    controller.add([str(real), "http://radio/x", str(tmp_path / "falta.mp3")])
    controller._probe_next_metadata()
    assert controller._metadata_probe.probed == [str(real)]  # ni URLs ni archivos inexistentes
    controller._on_metadata_parsed(str(real), 125_000, "Titulo", "Artista")
    assert controller.model.index(0).data() == "🎵 Artista — Titulo — 02:05"
    assert titles[-1] == "Lista de reproducción (3 elementos) — 02:05"
    controller.note_duration(str(tmp_path / "falta.mp3"), 5_000)
    assert titles[-1] == "Lista de reproducción (3 elementos) — 02:10"
    controller.clear()
    assert titles[-1] == "Lista de reproducción" and controller.count() == 0


def test_view_maps_a_drop_position_to_source_rows_through_the_filter(controller):
    controller.add(_fake("a.mp3", "b.mp3", "xa.mp3", "c.mp3", "xb.mp3"))
    view = PlaylistView()
    view.setModel(controller.proxy)
    view.resize(300, 300)
    view.show()
    controller.set_filter("x")  # solo se ven xa (fila 2) y xb (fila 4)
    first = view.visualRect(controller.proxy.index(0, 0))
    second = view.visualRect(controller.proxy.index(1, 0))
    assert view.drop_target_row(QPoint(5, first.top() + 1)) == 2
    assert view.drop_target_row(QPoint(5, second.bottom() - 1)) == 5
    assert view.drop_target_row(QPoint(5, 290)) == 5  # debajo de todo: al final
    dropped = []
    view.rowsDropped.connect(lambda rows, target: dropped.append((rows, target)))
    view.rowsDropped.connect(controller.move_rows)
    view.set_source_rows_selected([4])
    assert view.handle_internal_drop(QPoint(5, first.top() + 1))
    assert dropped == [([4], 2)]
    assert _names(controller) == ["a.mp3", "b.mp3", "xb.mp3", "xa.mp3", "c.mp3"]
    view.close()
