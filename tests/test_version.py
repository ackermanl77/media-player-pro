"""Version unica (player.__version__) y lo que se genera de ella: el
recurso de version del .exe, pyproject.toml y el workflow de release."""
import importlib.util
from pathlib import Path

import pytest

import player

ROOT = Path(__file__).resolve().parent.parent


def _version_resource():
    # packaging/ no es un paquete (y "packaging" choca con la libreria de
    # PyPI del mismo nombre): se carga el archivo directamente.
    spec = importlib.util.spec_from_file_location("version_resource", ROOT / "packaging" / "version_resource.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_spec_reads_the_same_version_as_the_package():
    vr = _version_resource()
    assert vr.read_version(str(ROOT)) == player.__version__


@pytest.mark.parametrize("text, expected", [
    ("0.1.0", (0, 1, 0, 0)),
    ("1.2", (1, 2, 0, 0)),
    ("2.0.1rc1", (2, 0, 1, 0)),
    ("1.2.3.4.5", (1, 2, 3, 4)),
    ("70000.x", (65535, 0, 0, 0)),
])
def test_version_tuple_has_four_16_bit_numbers(text, expected):
    assert _version_resource().version_tuple(text) == expected


def test_version_strings_name_the_product_and_exe():
    strings = _version_resource().version_strings("1.4.2")
    assert strings["ProductVersion"] == strings["FileVersion"] == "1.4.2"
    assert strings["OriginalFilename"] == "ReproductorMultimediaPro.exe"
    assert strings["ProductName"] == "Reproductor Multimedia Pro"


def test_build_version_info_with_pyinstaller():
    pytest.importorskip("PyInstaller")
    info = _version_resource().build_version_info("1.4.2")
    assert info.ffi.fileVersionMS == (1 << 16) | 4 and info.ffi.fileVersionLS == 2 << 16
    text = str(info)
    assert "ProductVersion', '1.4.2'" in text and "0c0a04b0" in text


def test_pyproject_and_spec_take_the_version_from_the_package():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = { attr = "player.__version__" }' in pyproject
    assert "\nversion =" not in pyproject.split("[tool.setuptools.dynamic]")[0]
    spec = (ROOT / "ReproductorMultimediaPro.spec").read_text(encoding="utf-8")
    assert "version=build_version_info(APP_VERSION)" in spec


def test_release_workflow_runs_ci_first_on_version_tags():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in release
    assert "uses: ./.github/workflows/ci.yml" in release and "needs: test" in release
    assert "workflow_call:" in ci
    assert "pyinstaller --noconfirm ReproductorMultimediaPro.spec" in release
    assert "Compress-Archive" in release and "gh release create" in release


# ------------------------------------------------- 8.7 manifiesto e iconos de documento
def _packaging_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_manifest_sets_a_utf8_code_page_and_per_monitor_dpi(tmp_path):
    import xml.etree.ElementTree as ET

    path = _packaging_module("windows_manifest").write_manifest(str(tmp_path))
    root = ET.parse(path).getroot()
    values = {el.tag.split("}")[1]: el.text for el in root.iter() if el.text and el.text.strip()}
    assert values["activeCodePage"] == "UTF-8"
    assert values["dpiAwareness"] == "PerMonitorV2"
    assert values["longPathAware"] == "true"
    level = next(el for el in root.iter() if el.tag.endswith("requestedExecutionLevel"))
    assert level.get("level") == "asInvoker"


def test_the_spec_embeds_the_manifest_and_both_document_icons():
    text = (ROOT / "ReproductorMultimediaPro.spec").read_text(encoding="utf-8")
    assert "manifest=MANIFEST_PATH" in text
    assert ('icon=["player/assets/icon.ico", "player/assets/media_document.ico", '
            '"player/assets/playlist_document.ico"]') in text


def test_document_icons_are_checked_in_at_every_explorer_size():
    icons = _packaging_module("document_icons")
    for path in (icons.MEDIA_ICON, icons.PLAYLIST_ICON):
        data = Path(path).read_bytes()
        assert icons.read_ico_sizes(data) == list(icons.ICON_SIZES)
        assert b"\x89PNG" in data


def test_ico_container_round_trips():
    icons = _packaging_module("document_icons")
    data = icons.ico_bytes([(16, b"\x89PNG-a"), (256, b"\x89PNG-bb")])
    assert icons.read_ico_sizes(data) == [16, 256]
    assert data.endswith(b"\x89PNG-a\x89PNG-bb")


def test_the_installer_gives_media_and_playlists_their_own_document_icon():
    iss = (ROOT / "installer" / "ReproductorMultimediaPro.iss").read_text(encoding="utf-8")
    assert r'{#AppKey}.Media\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},1"' in iss
    assert r'{#AppKey}.Playlist\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},2"' in iss
    assert '#emit Ext(".m3u", "Playlist")' in iss and '#emit Ext(".m3u8", "Playlist")' in iss
    assert '#emit Ext(".mkv")' in iss
