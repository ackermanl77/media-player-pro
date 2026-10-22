"""Dialogos de Archivo > Abrir disco / Abrir carpeta compartida / Explorar la
red local (3.18). Las direcciones las arma player/sources.py.

El explorador de la red usa el servicio de descubrimiento "upnp" de libVLC:
cada servidor UPnP/DLNA (un NAS, Plex, Jellyfin, el "compartir multimedia" de
Windows) aparece como un Media en la lista del discoverer; abrir uno lo
analiza con red (parse_with_options) y sus carpetas y archivos son sus
subitems. La lista se lee con un QTimer en el hilo de la UI -- sin callbacks
de libVLC, que llegarian en otro hilo.
"""

import logging

import vlc
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .sources import (
    DISC_KINDS,
    SHARE_PROTOCOLS,
    UPNP_SERVICE,
    disc_mrl,
    optical_drives,
    share_media_options,
    share_url,
)

log = logging.getLogger(__name__)

MRL_ROLE = Qt.ItemDataRole.UserRole
MEDIA_ROLE = Qt.ItemDataRole.UserRole + 1
POLL_MS = 500
PARSE_TIMEOUT_MS = 8000


class OpenDiscDialog(QDialog):
    def __init__(self, parent=None, drives=None):
        super().__init__(parent)
        self.setWindowTitle("Abrir disco")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind_combo = QComboBox()
        for label, kind in DISC_KINDS:
            self.kind_combo.addItem(label, kind)
        form.addRow("Tipo:", self.kind_combo)
        self.drive_combo = QComboBox()
        self.drive_combo.setEditable(True)
        for drive in optical_drives() if drives is None else drives:
            self.drive_combo.addItem(drive)
        self.drive_combo.setToolTip("La unidad del disco (D:, E:...) o, fuera de Windows, el dispositivo")
        form.addRow("Unidad:", self.drive_combo)
        self.title_spin = QSpinBox()
        self.title_spin.setRange(0, 999)
        self.title_spin.setSpecialValueText("Desde el principio (o el menú)")
        form.addRow("Título / pista:", self.title_spin)
        layout.addLayout(form)
        if self.drive_combo.count() == 0:
            layout.addWidget(QLabel("No se encontró ninguna unidad de CD/DVD/Blu-ray: escribe la unidad."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mrl(self) -> str:
        return disc_mrl(self.kind_combo.currentData(), self.drive_combo.currentText(), self.title_spin.value())


class OpenShareDialog(QDialog):
    """Un archivo o carpeta en un servidor SMB/NFS/SFTP/FTP. La contrasena no
    va en la direccion: se pasa como opcion del Media (sources.py)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Abrir carpeta compartida")
        self.resize(480, 0)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.protocol_combo = QComboBox()
        for label, value in SHARE_PROTOCOLS:
            self.protocol_combo.addItem(label, value)
        form.addRow("Protocolo:", self.protocol_combo)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("nas.local, 192.168.1.20 o \\\\nas\\videos")
        form.addRow("Servidor:", self.host_edit)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("videos/peliculas/archivo.mkv (una carpeta abre su contenido)")
        form.addRow("Ruta:", self.path_edit)
        self.user_edit = QLineEdit()
        form.addRow("Usuario:", self.user_edit)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setToolTip("Solo se usa mientras el programa está abierto; no se guarda")
        form.addRow("Contraseña:", self.password_edit)
        self.domain_edit = QLineEdit()
        self.domain_edit.setPlaceholderText("opcional (SMB)")
        form.addRow("Dominio:", self.domain_edit)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(0, 65535)
        self.port_spin.setSpecialValueText("Predeterminado")
        form.addRow("Puerto:", self.port_spin)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def protocol(self) -> str:
        return self.protocol_combo.currentData()

    def url(self) -> str:
        return share_url(self.protocol(), self.host_edit.text(), self.path_edit.text(), self.user_edit.text(),
                         self.port_spin.value())

    def media_options(self) -> list:
        return share_media_options(self.protocol(), self.user_edit.text(), self.password_edit.text(), self.domain_edit.text())

    def _accept_if_valid(self):
        try:
            self.url()
        except ValueError as error:
            self.error_label.setText(str(error).capitalize())
            return
        self.accept()


def _media_title(media) -> str:
    title = media.get_meta(vlc.Meta.Title) or ""
    return title or media.get_mrl() or "?"


class NetworkBrowserDialog(QDialog):
    """Archivo > Explorar la red local: servidores UPnP/DLNA y su contenido.
    Doble clic (o Abrir) en un archivo lo agrega a la lista y lo reproduce."""

    def __init__(self, on_open, parent=None, instance_factory=None):
        super().__init__(parent)
        self.setWindowTitle("Explorar la red local (UPnP / DLNA)")
        self.resize(560, 460)
        self._on_open = on_open
        self._factory = instance_factory or (lambda: vlc.Instance(["--quiet"]))
        self._instance = None
        self._discoverer = None
        self._servers: dict = {}  # MRL -> QTreeWidgetItem
        self._pending: dict = {}  # QTreeWidgetItem -> (Media, intentos)
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Buscando servidores multimedia en la red…")
        layout.addWidget(self.status_label)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self._open_item(item))
        layout.addWidget(self.tree)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(lambda: self._open_item(self.tree.currentItem()))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._poll)
        self.finished.connect(lambda _result: self.stop())

    def start(self) -> bool:
        try:
            self._instance = self._factory()
            self._discoverer = self._instance.media_discoverer_new(UPNP_SERVICE) if self._instance else None
            if self._discoverer is None or self._discoverer.start() != 0:
                raise RuntimeError("upnp")
        except Exception:  # noqa: BLE001 - un libVLC sin el modulo upnp
            log.warning("no se pudo iniciar el descubrimiento UPnP", exc_info=True)
            self.status_label.setText("Esta versión de VLC no puede buscar servidores UPnP/DLNA.")
            self.stop()
            return False
        self.timer.start()
        self._poll()
        return True

    def stop(self):
        self.timer.stop()
        if self._discoverer is not None:
            try:
                self._discoverer.stop()
                self._discoverer.release()
            except Exception:  # noqa: BLE001
                pass
        self._discoverer = None
        if self._instance is not None:
            self._instance.release()
        self._instance = None
        self._pending.clear()

    def _poll(self):
        if self._discoverer is None:
            return
        media_list = self._discoverer.media_list()
        if media_list is not None:
            media_list.lock()
            try:
                for index in range(media_list.count()):
                    media = media_list.item_at_index(index)
                    if media is not None and media.get_mrl() not in self._servers:
                        self._servers[media.get_mrl()] = self._add_item(self.tree.invisibleRootItem(), media, folder=True)
            finally:
                media_list.unlock()
        if self._servers:
            self.status_label.setText(f"Servidores encontrados: {len(self._servers)}. Abre uno para ver su contenido.")
        self._check_pending()

    def _add_item(self, parent: QTreeWidgetItem, media, folder: bool) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent, [_media_title(media)])
        item.setData(0, MRL_ROLE, media.get_mrl())
        item.setData(0, MEDIA_ROLE, media)
        if folder:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return item

    def _on_expanded(self, item: QTreeWidgetItem):
        media = item.data(0, MEDIA_ROLE)
        if media is None or item.childCount() or item in self._pending:
            return
        media.parse_with_options(vlc.MediaParseFlag.network, PARSE_TIMEOUT_MS)
        self._pending[item] = media
        item.setText(0, f"{_media_title(media)}  (cargando…)")

    def _check_pending(self):
        for item, media in list(self._pending.items()):
            status = media.get_parsed_status()
            if status in (vlc.MediaParsedStatus.skipped, vlc.MediaParsedStatus.failed, vlc.MediaParsedStatus.timeout,
                          vlc.MediaParsedStatus.done):
                del self._pending[item]
                item.setText(0, _media_title(media))
                self._fill_children(item, media)

    def _fill_children(self, item: QTreeWidgetItem, media):
        subitems = media.subitems()
        count = subitems.count() if subitems is not None else 0
        for index in range(count):
            child = subitems.item_at_index(index)
            if child is None:
                continue
            is_folder = child.get_type() == vlc.MediaType.directory
            self._add_item(item, child, folder=is_folder)
        if count == 0:
            item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)

    def _open_item(self, item):
        if item is None:
            return
        media = item.data(0, MEDIA_ROLE)
        if (media is not None and media.get_type() == vlc.MediaType.directory) or item.parent() is None:
            item.setExpanded(True)
            return
        mrl = item.data(0, MRL_ROLE)
        if mrl:
            self._on_open(mrl)
