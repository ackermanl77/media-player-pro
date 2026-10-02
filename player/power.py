"""Acciones de energia al terminar la lista (apagar, hibernar, reiniciar)
con una cuenta regresiva cancelable dentro de la app.

Antes: Hibernar ejecutaba "shutdown /h" en el acto, y Apagar/Reiniciar
arrancaban el temporizador de 60 s de Windows que solo se podia cancelar
escribiendo "shutdown /a" en una consola (y el aviso en la barra de estado
no se veia en pantalla completa). Ahora las tres pasan por la misma
cuenta regresiva, por encima de todo, con "Cancelar" como boton por
defecto; recien al llegar a 0 se ejecuta el comando, sin demora del lado
de Windows."""

import subprocess
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

COUNTDOWN_S = 60
POWER_ACTIONS = ("shutdown", "hibernate", "restart")

_COMMANDS = {
    "shutdown": ["shutdown", "/s", "/t", "0"],
    "hibernate": ["shutdown", "/h"],
    "restart": ["shutdown", "/r", "/t", "0"],
}
_VERBS = {"shutdown": "se apagará", "hibernate": "se hibernará", "restart": "se reiniciará"}
_BUTTONS = {"shutdown": "Apagar ahora", "hibernate": "Hibernar ahora", "restart": "Reiniciar ahora"}


def power_command(action: str) -> list:
    return list(_COMMANDS[action])


def countdown_text(action: str, seconds: int) -> str:
    return f"Lista terminada: el equipo {_VERBS[action]} en {seconds} s."


def run_power_action(action: str, runner=None) -> bool:
    """Ejecuta el comando de Windows (o nada fuera de Windows). runner
    inyectable para las pruebas; por defecto subprocess.run."""
    if action not in _COMMANDS or not sys.platform.startswith("win"):
        return False
    (runner or subprocess.run)(power_command(action), check=False)
    return True


class PowerCountdownDialog(QDialog):
    """Cuenta regresiva no modal y siempre visible. fired(accion) al llegar
    a 0 (o con "... ahora"); cancelled() con Cancelar/Esc/cerrar."""

    fired = Signal(str)
    cancelled = Signal()

    def __init__(self, action: str, seconds: int = COUNTDOWN_S, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Reproductor Multimedia Pro")
        self.action = action
        self.remaining = int(seconds)
        self._done = False

        layout = QVBoxLayout(self)
        self.label = QLabel(countdown_text(action, self.remaining))
        self.label.setStyleSheet("font-size: 12pt;")
        layout.addWidget(self.label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_now = QPushButton(_BUTTONS[action])
        self.btn_now.setAutoDefault(False)
        self.btn_now.clicked.connect(self.fire)
        buttons.addWidget(self.btn_now)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setDefault(True)
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_cancel)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        if self._done:
            return
        self.remaining -= 1
        if self.remaining <= 0:
            self.fire()
            return
        self.label.setText(countdown_text(self.action, self.remaining))

    def fire(self):
        if self._done:
            return
        self._done = True
        self.timer.stop()
        self.fired.emit(self.action)
        self.accept()

    def reject(self):
        if not self._done:
            self._done = True
            self.timer.stop()
            self.cancelled.emit()
        super().reject()
