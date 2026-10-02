"""Diagnostico de VLC faltante o de otra arquitectura (prerequisito
externo: el .exe no incluye libVLC)."""
from player import vlc_check as vc


def test_32_bit_vlc_with_a_64_bit_app_is_explained():
    msg = vc.missing_vlc_message(found={"32": True, "64": False}, bits=64, platform="win32")
    assert "32 bits" in msg and "64 bits" in msg and vc.VLC_DOWNLOAD_URL in msg


def test_missing_and_broken_installs_have_distinct_messages():
    missing = vc.missing_vlc_message(found={}, bits=64, platform="win32")
    broken = vc.missing_vlc_message(found={"64": True}, bits=64, platform="win32")
    assert "No se encontró" in missing and "Reinstala" in broken
    assert "64 bits" in vc.missing_vlc_message(found={}, bits=64, platform="linux")


def test_candidate_dirs_and_detection():
    env = {"ProgramW6432": "C:\\Program Files", "ProgramFiles(x86)": "C:\\Program Files (x86)"}
    dirs = vc.candidate_vlc_dirs(env)
    assert dirs["64"].replace("\\", "/").endswith("VideoLAN/VLC")
    found = vc.find_installed_vlc(env, exists=lambda p: "(x86)" in p)
    assert found == {"64": False, "32": True}


def test_version_parsing_and_warning():
    assert vc.parse_vlc_version(b"3.0.23 Vetinari") == (3, 0, 23)
    assert vc.parse_vlc_version("nada") == ()
    assert vc.version_warning("3.0.23 Vetinari") is None
    assert "2.2.8" in vc.version_warning("2.2.8 Weatherwax")


def test_bundled_vlc_is_used_only_when_present():
    env = {}
    assert vc.configure_bundled_vlc("C:/app", env, exists=lambda p: False) is False and env == {}
    assert vc.configure_bundled_vlc("C:/app", env, exists=lambda p: True) is True
    assert env["PYTHON_VLC_LIB_PATH"].endswith("libvlc.dll")
    assert env["PYTHON_VLC_MODULE_PATH"].replace("\\", "/").endswith("vlc/plugins")
    user = {"PYTHON_VLC_LIB_PATH": "D:/mi/libvlc.dll"}
    assert vc.configure_bundled_vlc("C:/app", user, exists=lambda p: True) is False
    assert vc.configure_bundled_vlc(None, {}, exists=lambda p: True) is False
