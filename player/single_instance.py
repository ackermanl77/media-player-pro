"""Una sola ventana: si el programa ya esta abierto, abrir un archivo (doble
clic en el Explorador, "Abrir con", linea de comandos) se lo manda a esa
ventana en vez de arrancar otro proceso con su propio libVLC.

Usa QLocalServer/QLocalSocket (una tuberia con nombre en Windows) con un
nombre por usuario. El mensaje es una linea JSON:
{"action": "open"|"enqueue", "paths": [...]}. "open" reproduce lo
recibido; "enqueue" solo lo agrega a la lista.

Se puede desactivar con Archivo -> Permitir varias ventanas o con
--new-window."""

import getpass
import json
import logging
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

SERVER_PREFIX = "ReproductorMultimediaPro"
ACTIONS = ("open", "enqueue")
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
NEWLINE = bytes([10])


def server_name(user=None) -> str:
    try:
        user = user if user is not None else getpass.getuser()
    except Exception:  # noqa: BLE001 -- sin USERNAME en el entorno
        user = "usuario"
    return f"{SERVER_PREFIX}-{re.sub(r'[^A-Za-z0-9_.-]', '_', user) or 'usuario'}"


def encode_message(action: str, paths) -> bytes:
    if action not in ACTIONS:
        raise ValueError(action)
    return (json.dumps({"action": action, "paths": [str(p) for p in paths]}) + "\n").encode("utf-8")


def decode_message(data: bytes):
    """(accion, rutas) o None si el mensaje no es valido."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict) or msg.get("action") not in ACTIONS:
        return None
    paths = msg.get("paths")
    if not isinstance(paths, list):
        return None
    return msg["action"], [p for p in paths if isinstance(p, str) and p]


def send_to_running_instance(paths, action: str = "open", name=None, timeout_ms: int = 1500) -> bool:
    """True si habia una instancia escuchando y recibio el mensaje."""
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(encode_message(action, paths))
    socket.flush()
    # waitForBytesWritten devuelve False si ya no queda nada pendiente (en
    # Windows la tuberia suele aceptar todo en el acto).
    ok = socket.bytesToWrite() == 0 or socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return ok


class InstanceServer(QObject):
    """Escucha a las instancias nuevas. messageReceived(accion, rutas) en el
    hilo de la UI."""

    messageReceived = Signal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)
        self._buffers = {}

    def start(self, name=None) -> bool:
        name = name or server_name()
        if self._server.listen(name):
            return True
        # Fuera de Windows puede quedar un socket huerfano de un cierre
        # abrupto: se borra y se reintenta una vez.
        QLocalServer.removeServer(name)
        ok = self._server.listen(name)
        if not ok:
            log.warning("No se pudo escuchar en %s: %s", name, self._server.errorString())
        return ok

    def close(self):
        self._buffers.clear()
        self._server.close()

    def is_listening(self) -> bool:
        return self._server.isListening()

    # Los sockets son hijos del QLocalServer (los destruye el). Los slots
    # usan sender() en vez de lambdas que capturen el socket: una referencia
    # de Python a un socket que Qt ya destruyo terminaba en un acceso
    # invalido al liberar el servidor.
    def _on_new_connection(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[id(socket)] = b""
            socket.readyRead.connect(self._on_ready_read)
            socket.disconnected.connect(self._on_disconnected)

    def _on_ready_read(self):
        socket = self.sender()
        if socket is None:
            return
        self._consume(socket)

    def _consume(self, socket):
        key = id(socket)
        data = self._buffers.get(key, b"") + bytes(socket.readAll())
        if len(data) > MAX_MESSAGE_BYTES:
            self._buffers.pop(key, None)
            socket.abort()
            return
        while NEWLINE in data:
            line, data = data.split(NEWLINE, 1)
            decoded = decode_message(line)
            if decoded is not None:
                self.messageReceived.emit(decoded[0], decoded[1])
        self._buffers[key] = data

    def _on_disconnected(self):
        socket = self.sender()
        if socket is None:
            return
        if socket.bytesAvailable():
            self._consume(socket)
        self._buffers.pop(id(socket), None)
        socket.deleteLater()
