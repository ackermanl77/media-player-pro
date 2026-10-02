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
