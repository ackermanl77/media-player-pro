"""Video > Rotar / voltear (4.13): instance options and the menu."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from player.backend import ROTATION_VALUES, rotation_instance_args
from player.video_options import ROTATIONS


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_rotations_map_to_the_transform_filter():
    assert rotation_instance_args("") == []
    assert rotation_instance_args("90") == ["--video-filter=transform", "--transform-type=90"]
    assert rotation_instance_args("hflip") == ["--video-filter=transform", "--transform-type=hflip"]
    assert rotation_instance_args("45") == []
    assert set(ROTATION_VALUES) == {"90", "180", "270", "hflip", "vflip"}
    assert ROTATIONS[0][1] == ""


def test_a_new_rotation_rebuilds_the_instance(qapp):
    try:
        from player.backend import VLCPlayer
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    player = VLCPlayer()
    try:
        assert not player._needs_new_instance(False)
        player.set_rotation("270")
        assert player.get_rotation() == "270" and player._needs_new_instance(False)
        player._create_instance(visualizer=False)  # a real libVLC instance with the filter
        assert player.instance is not None and not player._needs_new_instance(False)
        assert player._instance_rotation_args == rotation_instance_args("270")
        player.set_rotation("sideways")
        assert player.get_rotation() == ""
    finally:
        player.close()


def test_the_video_menu_sets_the_rotation(qapp, tmp_path, monkeypatch):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    from player import settings as settings_module

    monkeypatch.setattr(settings_module, "_state_dir", lambda: tmp_path)
    window = MainWindow()
    try:
        actions = {a.data(): a for a in window.menu_rotation.actions() if a.isCheckable()}
        assert set(actions) == {"", *ROTATION_VALUES} and actions[""].isChecked()
        actions["vflip"].trigger()
        assert window.player.get_rotation() == "vflip" and actions["vflip"].isChecked()
        actions[""].trigger()
        assert window.player.get_rotation() == ""
    finally:
        window.close()
