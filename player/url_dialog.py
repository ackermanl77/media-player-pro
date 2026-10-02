"""Dialogo "Abrir URL": la direccion (precargada desde el portapapeles si
parece una URL), la cache de red y RTSP por TCP. Antes era un
QInputDialog que aceptaba cualquier texto, sin ninguna opcion de red."""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from .formats import is_url, looks_like_url
from .settings import MAX_NETWORK_CACHING_MS, MIN_NETWORK_CACHING_MS


class OpenUrlDialog(QDialog):
    def __init__(self, network_caching_ms: int, rtsp_tcp: bool, parent=None, clipboard_text=None):
        super().__init__(parent)
        self.setWindowTitle("Abrir URL")
        self.resize(520, 0)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("URL de audio/video o stream (http, https, rtsp, rtmp, srt, mms, udp, ftp...):"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://...")
        if clipboard_text is None:
            clipboard = QGuiApplication.clipboard()
            clipboard_text = clipboard.text() if clipboard is not None else ""
        if looks_like_url(clipboard_text or ""):
            self.url_edit.setText(clipboard_text.strip())
            self.url_edit.selectAll()
        layout.addWidget(self.url_edit)

        form = QFormLayout()
        self.caching_spin = QSpinBox()
        self.caching_spin.setRange(MIN_NETWORK_CACHING_MS, MAX_NETWORK_CACHING_MS)
        self.caching_spin.setSingleStep(100)
        self.caching_spin.setSuffix(" ms")
        self.caching_spin.setValue(int(network_caching_ms))
        self.caching_spin.setToolTip(
            "Cuánto almacena antes de reproducir. Más alto = más estable en redes lentas, pero con más demora."
        )
        form.addRow("Caché de red:", self.caching_spin)
        self.rtsp_tcp_check = QCheckBox("RTSP por TCP (para cámaras o redes que bloquean UDP)")
        self.rtsp_tcp_check.setChecked(bool(rtsp_tcp))
        form.addRow("", self.rtsp_tcp_check)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #d04040;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def url(self) -> str:
        return self.url_edit.text().strip()

    def network_caching_ms(self) -> int:
        return self.caching_spin.value()

    def rtsp_tcp(self) -> bool:
        return self.rtsp_tcp_check.isChecked()

    def _on_accept(self):
        if not is_url(self.url()):
            self.error_label.setText("Escribe una dirección completa, con su esquema (p. ej. https:// o rtsp://).")
            return
        self.accept()
