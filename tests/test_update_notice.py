"""DialogsMixin.show_update: la versión nueva se avisa y abre la página de descarga solo con Sí."""
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from player.update_check import UpdateInfo  # noqa: E402
from player.window_dialogs import DialogsMixin  # noqa: E402


@pytest.mark.parametrize("answer, opened", [(QMessageBox.StandardButton.Yes, True),
                                            (QMessageBox.StandardButton.No, False)])
def test_update_notice_opens_the_download_page_only_on_yes(answer, opened):
    window = MagicMock()
    info = UpdateInfo("9.0.0", "https://example.com/get", "Mejor ecualizador")
    with patch("player.window_dialogs.QMessageBox.question", return_value=answer) as question, \
            patch("player.window_dialogs.QDesktopServices.openUrl") as open_url:
        DialogsMixin.show_update(window, info)
    assert "9.0.0" in window.statusBar().showMessage.call_args.args[0]
    assert "Mejor ecualizador" in question.call_args.args[2]
    assert open_url.called is opened
