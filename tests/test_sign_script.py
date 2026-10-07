"""packaging/sign_and_package.py: firma del .exe y del instalador (Authenticode)."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging"))
import sign_and_package as sp  # noqa: E402


def test_signtool_firma_sha256_con_sello_rfc3161():
    cmd = sp.sign_command("signtool.exe", "ABC", "app.exe", "http://ts.example")
    assert cmd == ["signtool.exe", "sign", "/sha1", "ABC", "/fd", "SHA256", "/tr", "http://ts.example", "/td", "SHA256", "app.exe"]


def test_inno_recibe_la_herramienta_codesign_y_el_iss_la_usa():
    args = sp.inno_sign_args(r"C:\Kits\signtool.exe", "ABC", "http://ts.example")
    assert args == ["/DSign", r"/Scodesign=$qC:\Kits\signtool.exe$q sign /sha1 ABC /fd SHA256 /tr http://ts.example /td SHA256 $f"]
    with open(sp.ISS, encoding="utf-8-sig") as handle:
        iss = handle.read().replace("\r\n", "\n")
    assert "#ifdef Sign\nSignTool=codesign\nSignedUninstaller=yes\n#endif" in iss


def test_la_version_sale_de_player():
    from player import __version__

    assert sp.app_version() == __version__


def test_sin_huella_no_firma_nada():
    with mock.patch.dict(os.environ, {"CODESIGN_THUMBPRINT": ""}), mock.patch.object(sp.subprocess, "run") as run:
        assert sp.main([]) == 1
    run.assert_not_called()


def test_firma_el_exe_y_compila_el_instalador_firmado(tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"MZ")
    env = {"CODESIGN_THUMBPRINT": "AB CD", "CODESIGN_TIMESTAMP_URL": ""}
    with mock.patch.dict(os.environ, env), mock.patch.object(sp, "EXE", str(exe)), \
            mock.patch.object(sp, "find_signtool", return_value="signtool.exe"), \
            mock.patch.object(sp, "find_iscc", return_value="ISCC.exe"), \
            mock.patch.object(sp.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
        assert sp.main([]) == 0
    sign, iscc = (call.args[0] for call in run.call_args_list)
    assert sign[:4] == ["signtool.exe", "sign", "/sha1", "ABCD"] and sp.DEFAULT_TIMESTAMP_URL in sign
    assert iscc[0] == "ISCC.exe" and "/DSign" in iscc and iscc[-1] == sp.ISS
