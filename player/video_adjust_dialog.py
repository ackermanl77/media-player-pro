"""Video -> Ajustes de video: brillo, contraste, saturacion, tono y gamma
(filtro "adjust" de libVLC), en vivo, como el ecualizador."""

import math
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from .backend import VLCPlayer
from .settings import VIDEO_ADJUST_RANGES, VideoAdjustSettings

LABELS = {
    "brightness": "Brillo",
    "contrast": "Contraste",
    "saturation": "Saturación",
    "hue": "Tono",
    "gamma": "Gamma",
}
STEPS = 300  # posiciones de cada slider: los valores neutros caen justo en una


def to_slider(name: str, value: float) -> int:
    """Valor del ajuste -> posicion 0..STEPS. Gamma va en escala
    logaritmica (0,01..10, neutro 1 en el centro)."""
    low, high, _neutral = VIDEO_ADJUST_RANGES[name]
    value = max(low, min(high, value))
    if name == "gamma":
        return round((math.log10(value) + 2) / 3 * STEPS)
    return round((value - low) / (high - low) * STEPS)


def from_slider(name: str, position: int) -> float:
    low, high, _neutral = VIDEO_ADJUST_RANGES[name]
    fraction = max(0, min(STEPS, position)) / STEPS
    if name == "gamma":
        return round(10 ** (fraction * 3 - 2), 3)
    return round(low + fraction * (high - low), 3)


def format_value(name: str, value: float) -> str:
    if name == "hue":
        return f"{value:+.0f}°".replace("+0°", "0°")
    return f"{value:.2f}".replace(".", ",")


class VideoAdjustDialog(QDialog):
    def __init__(self, player: VLCPlayer, parent=None):
        super().__init__(parent)
        self.player = player
        self.setWindowTitle("Ajustes de video")
        layout = QVBoxLayout(self)
        self.enable_checkbox = QCheckBox("Activar ajustes de imagen")
        layout.addWidget(self.enable_checkbox)

        grid = QGridLayout()
        self.sliders = {}
        self.value_labels = {}
        for row, name in enumerate(VIDEO_ADJUST_RANGES):
            label = QLabel(LABELS[name])
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, STEPS)
            slider.setAccessibleName(LABELS[name])
            value = QLabel()
            value.setMinimumWidth(48)
            grid.addWidget(label, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(value, row, 2)
            self.sliders[name] = slider
            self.value_labels[name] = value
        layout.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.reset_button = QPushButton("Restablecer")
        close_button = QPushButton("Cerrar")
        buttons.addWidget(self.reset_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._load(player.get_video_adjust())
        self.enable_checkbox.toggled.connect(lambda _checked: self._apply())
        for slider in self.sliders.values():
            slider.valueChanged.connect(lambda _value: self._on_slider())
        self.reset_button.clicked.connect(self.reset)
        close_button.clicked.connect(self.close)
        self.resize(420, self.sizeHint().height())

    def _load(self, adjust: VideoAdjustSettings):
        self.enable_checkbox.blockSignals(True)
        self.enable_checkbox.setChecked(adjust.enabled)
        self.enable_checkbox.blockSignals(False)
        for name, slider in self.sliders.items():
            slider.blockSignals(True)
            slider.setValue(to_slider(name, getattr(adjust, name)))
            slider.blockSignals(False)
            self.value_labels[name].setText(format_value(name, getattr(adjust, name)))

    def state(self) -> VideoAdjustSettings:
        values = {name: from_slider(name, slider.value()) for name, slider in self.sliders.items()}
        return VideoAdjustSettings(enabled=self.enable_checkbox.isChecked(), **values)

    def _on_slider(self):
        # Mover un slider activa los ajustes (si no, no se veria el cambio).
        if not self.enable_checkbox.isChecked():
            self.enable_checkbox.blockSignals(True)
            self.enable_checkbox.setChecked(True)
            self.enable_checkbox.blockSignals(False)
        self._apply()

    def _apply(self):
        state = self.state()
        for name in self.sliders:
            self.value_labels[name].setText(format_value(name, getattr(state, name)))
        self.player.set_video_adjust(state)

    def reset(self):
        neutral = replace(VideoAdjustSettings(), enabled=False)
        self._load(neutral)
        self.player.set_video_adjust(neutral)
