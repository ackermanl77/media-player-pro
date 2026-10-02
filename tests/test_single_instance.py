"""Una sola ventana (3.6): protocolo y servidor local, en el mismo proceso
(QLocalServer + QLocalSocket con un nombre unico por prueba)."""
import os
import sys
import subprocess
import time
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from player.single_instance import (
    InstanceServer,
    decode_message,
    encode_message,
    send_to_running_instance,
    server_name,
)




@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_messages_round_trip_and_reject_garbage():
    assert decode_message(encode_message("enqueue", ["C:/a.mp3", "http://x"]).strip()) == (
        "enqueue", ["C:/a.mp3", "http://x"])
    for bad in (b"no json", b'{"action": "borrar", "paths": []}', b'{"action": "open", "paths": "x"}',
                b"\xff\xfe", b"[]"):
        assert decode_message(bad) is None
    assert decode_message(b'{"action": "open", "paths": ["a", 3, ""]}') == ("open", ["a"])
    with pytest.raises(ValueError):
        encode_message("borrar", [])
    assert server_name("Ana Perez/x") == "ReproductorMultimediaPro-Ana_Perez_x"


def test_second_instance_hands_its_files_to_the_first(qapp):
    name = f"rmp-test-{uuid.uuid4().hex}"
    assert send_to_running_instance(["a.mp3"], name=name, timeout_ms=200) is False  # nadie escucha
    server = InstanceServer()
    received = []
    server.messageReceived.connect(lambda action, paths: received.append((action, paths)))
    assert server.start(name)
    try:
        # La segunda instancia es otro proceso de verdad (como un doble clic
        # en el Explorador con el programa ya abierto).
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import os,sys;os.environ['QT_QPA_PLATFORM']='offscreen';sys.path.insert(0,sys.argv[1]);"
            "from PySide6.QtCore import QCoreApplication;a=QCoreApplication([]);"
            "from player.single_instance import send_to_running_instance as s;"
            "sys.exit(0 if s(['C:/v/a.mkv','D:/b.mp3'],'open',name=sys.argv[2]) else 3)"
        )
        proc = subprocess.Popen([sys.executable, "-c", code, root, name])
        deadline = time.time() + 15
        while (proc.poll() is None or not received) and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        assert proc.wait(5) == 0
        assert received == [("open", ["C:/v/a.mkv", "D:/b.mp3"])]
    finally:
        server.close()
        QApplication.processEvents()
