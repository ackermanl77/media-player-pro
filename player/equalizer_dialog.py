"""Dialogo del ecualizador (antes dentro de main_window.py)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QSlider, QVBoxLayout

from .backend import VLCPlayer
from .settings import EqualizerSettings

# Nombres de los 18 presets de libVLC (vienen en ingles) en el mismo orden.
PRESET_NAMES_ES = {
    "Flat": "Plano", "Classical": "Clásica", "Club": "Club", "Dance": "Dance",
    "Full bass": "Graves", "Full bass and treble": "Graves y agudos", "Full treble": "Agudos",
    "Headphones": "Auriculares", "Large Hall": "Sala grande", "Live": "En vivo",
    "Party": "Fiesta", "Pop": "Pop", "Reggae": "Reggae", "Rock": "Rock", "Ska": "Ska",
    "Soft": "Suave", "Soft rock": "Rock suave", "Techno": "Techno",
}


def preset_display_name(name: str) -> str:
    return PRESET_NAMES_ES.get(name, name)


def format_band_frequency(freq: float) -> str:
    """31 Hz, 62,5 Hz, 1 kHz, 16 kHz (antes "62Hz" truncado y "1.0kHz")."""
    def _num(value):
        text = f"{value:.1f}".rstrip("0").rstrip(".")
        return text.replace(".", ",")
    if freq < 1000:
        return f"{_num(freq)} Hz"
    return f"{_num(freq / 1000)} kHz"


class EqualizerDialog(QDialog):
    def __init__(self, player: VLCPlayer, parent=None, initial=None):
        """initial: EqualizerSettings guardados (ver player/settings.py), para
        que el dialogo -- que se crea recien la primera vez que se abre --
        muestre el preset y los valores restaurados al iniciar la app."""
        super().__init__(parent)
        self.player = player
        self.setWindowTitle("Ecualizador")

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.enable_checkbox = QCheckBox("Activar ecualizador")
        top.addWidget(self.enable_checkbox)
        top.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Personalizado", -1)
        for i, name in enumerate(player.equalizer_preset_names()):
            self.preset_combo.addItem(preset_display_name(name), i)
        top.addWidget(self.preset_combo)
        layout.addLayout(top)

        bands_layout = QHBoxLayout()
        freqs = player.equalizer_band_frequencies()

        preamp_box = QVBoxLayout()
        self.preamp_value_label = QLabel("0 dB")
        preamp_box.addWidget(self.preamp_value_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.preamp_slider = QSlider(Qt.Orientation.Vertical)
        self.preamp_slider.setRange(-20, 20)
        self.preamp_slider.setValue(0)
        self.preamp_slider.setMinimumHeight(140)
        preamp_box.addWidget(self.preamp_slider, alignment=Qt.AlignmentFlag.AlignHCenter)
        preamp_box.addWidget(QLabel("Preamp"), alignment=Qt.AlignmentFlag.AlignHCenter)
        bands_layout.addLayout(preamp_box)

        self.band_sliders = []
        self.band_value_labels = []
        for i, freq in enumerate(freqs):
            box = QVBoxLayout()
            value_label = QLabel("0 dB")
            box.addWidget(value_label, alignment=Qt.AlignmentFlag.AlignHCenter)
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-20, 20)
            slider.setValue(0)
            slider.setMinimumHeight(140)
            box.addWidget(slider, alignment=Qt.AlignmentFlag.AlignHCenter)
            label_text = format_band_frequency(freq)
            box.addWidget(QLabel(label_text), alignment=Qt.AlignmentFlag.AlignHCenter)
            bands_layout.addLayout(box)
            self.band_sliders.append(slider)
            self.band_value_labels.append(value_label)
        layout.addLayout(bands_layout)

        self.set_controls_enabled(False)
        self._sync_from_state(initial)

        self.enable_checkbox.toggled.connect(self.on_enable_toggled)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.preamp_slider.valueChanged.connect(self.on_preamp_changed)
        for i, slider in enumerate(self.band_sliders):
            slider.valueChanged.connect(lambda val, idx=i: self.on_band_changed(idx, val))

    def set_controls_enabled(self, enabled: bool):
        self.preset_combo.setEnabled(enabled)
        self.preamp_slider.setEnabled(enabled)
        for s in self.band_sliders:
            s.setEnabled(enabled)

    def on_enable_toggled(self, enabled: bool):
        self.set_controls_enabled(enabled)
        if enabled:
            self.player.set_equalizer_preamp(float(self.preamp_slider.value()))
            for i, slider in enumerate(self.band_sliders):
                self.player.set_equalizer_band(i, float(slider.value()))
        else:
            self.player.disable_equalizer()

    def _sync_from_state(self, initial):
        """Refleja en los controles (sin reenviar nada a libVLC) el
        ecualizador que ya tiene el reproductor, o si esta desactivado, los
        valores guardados en `initial`."""
        active = self.player.get_equalizer_values()
        if active is not None:
            preamp, bands = active
        elif initial is not None:
            preamp, bands = initial.preamp, initial.bands
        else:
            return
        if initial is not None:
            combo_index = self.preset_combo.findData(initial.preset)
            if combo_index >= 0:
                self.preset_combo.setCurrentIndex(combo_index)  # aun sin conectar
        self._set_slider_values(preamp, bands)
        if active is not None:
            self.enable_checkbox.setChecked(True)  # aun sin conectar
            self.set_controls_enabled(True)

    def _set_slider_values(self, preamp: float, bands):
        preamp_val = int(round(preamp))
        self.preamp_slider.blockSignals(True)
        self.preamp_slider.setValue(preamp_val)
        self.preamp_slider.blockSignals(False)
        self.preamp_value_label.setText(f"{preamp_val:+d} dB")
        for i, slider in enumerate(self.band_sliders):
            band_val = int(round(bands[i])) if i < len(bands) else 0
            slider.blockSignals(True)
            slider.setValue(band_val)
            slider.blockSignals(False)
            self.band_value_labels[i].setText(f"{band_val:+d} dB")

    def state(self) -> EqualizerSettings:
        """Estado a guardar entre sesiones. Con el ecualizador activo, los
        valores exactos de libVLC (un preset usa pasos de 0.8 dB que los
        sliders enteros redondean); desactivado, lo que muestran los sliders."""
        active = self.player.get_equalizer_values()
        if active is not None:
            preamp, bands = active
        else:
            preamp = float(self.preamp_slider.value())
            bands = [float(s.value()) for s in self.band_sliders]
        return EqualizerSettings(
            enabled=active is not None,
            preset=self.preset_combo.currentData(),
            preamp=preamp,
            bands=bands,
        )

    def on_preset_changed(self, _index: int):
        preset_index = self.preset_combo.currentData()
        if preset_index is None or preset_index < 0:
            return
        if not self.player.apply_equalizer_preset(preset_index):
            return
        values = self.player.get_equalizer_values()
        if values is not None:
            self._set_slider_values(*values)

    def on_preamp_changed(self, val: int):
        self.preamp_value_label.setText(f"{val:+d} dB")
        if self.enable_checkbox.isChecked():
            self.player.set_equalizer_preamp(float(val))

    def on_band_changed(self, idx: int, val: int):
        self.band_value_labels[idx].setText(f"{val:+d} dB")
        if self.enable_checkbox.isChecked():
            self.player.set_equalizer_band(idx, float(val))
