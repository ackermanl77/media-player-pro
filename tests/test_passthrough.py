"""Audio > Passthrough (3.16): instance options, settings and the menu."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from player.backend import passthrough_instance_args
from player.settings import Settings, settings_from_dict


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_modes_map_to_libvlc_options_per_platform():
    assert passthrough_instance_args("off", "win32") == []
    assert passthrough_instance_args("ac3_dts", "win32") == ["--mmdevice-passthrough=1"]
    assert passthrough_instance_args("all", "win32") == ["--mmdevice-passthrough=2"]
    assert passthrough_instance_args("all", "linux") == ["--spdif"]
    assert passthrough_instance_args("bogus", "win32") == []


def test_settings_keep_only_known_modes():
    assert Settings().audio_passthrough == "off"
    assert settings_from_dict({"audio_passthrough": "all"}).audio_passthrough == "all"
    assert settings_from_dict({"audio_passthrough": "dolby"}).audio_passthrough == "off"


def test_a_new_mode_rebuilds_the_instance_with_its_option(qapp):
    try:
        from player.backend import VLCPlayer
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    player = VLCPlayer()
    try:
        player._create_instance(visualizer=False)
        assert not player._needs_new_instance(False)
        player.set_audio_passthrough("all")
        assert player.get_audio_passthrough() == "all" and player._needs_new_instance(False)
        player._create_instance(visualizer=False)  # a real libVLC instance with the option
        assert player.instance is not None and not player._needs_new_instance(False)
        assert player._instance_passthrough_args == passthrough_instance_args("all")
        player.set_audio_passthrough("nonsense")
        assert player.get_audio_passthrough() == "off"
    finally:
        player.close()


def test_the_audio_menu_sets_saves_and_restores_the_mode(qapp, tmp_path, monkeypatch):
    try:
        from player.main_window import MainWindow
    except OSError:
        pytest.skip("VLC (libvlc) no esta instalado")
    from player import settings as settings_module

    monkeypatch.setattr(settings_module, "_state_dir", lambda: tmp_path)
    window = MainWindow()
    try:
        modes = {action.data(): action for action in window.passthrough_group.actions()}
        assert set(modes) == {"off", "ac3_dts", "all"} and modes["off"].isChecked()
        modes["ac3_dts"].trigger()
        assert window.player.get_audio_passthrough() == "ac3_dts" and modes["ac3_dts"].isChecked()
        assert window.current_settings().audio_passthrough == "ac3_dts"
        window.save_settings_now()
    finally:
        window.close()
    again = MainWindow()
    try:
        assert again.player.get_audio_passthrough() == "ac3_dts"
        assert next(a for a in again.passthrough_group.actions() if a.isChecked()).data() == "ac3_dts"
    finally:
        again.close()
