"""Ecualizador contra libVLC real. Regresion: vlc.AudioEqualizer(indice)
tomaba el indice como un puntero C -- elegir cualquier preset terminaba en
"access violation", y tambien cada cambio de banda y cada recreacion del
Instance (audio <-> video con el visualizador) hasta desactivar el EQ.
Se omite si no hay VLC."""
import os
import sys
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

try:
    import vlc
except OSError:
    pytest.skip("VLC (libvlc) no esta instalado; se omiten estas pruebas.", allow_module_level=True)

from PySide6.QtWidgets import QApplication

from player import backend as backend_module
from player.backend import VLCPlayer
from player.main_window import EqualizerDialog
from player.settings import EqualizerSettings


@pytest.fixture
def player(monkeypatch):
    monkeypatch.setattr(
        backend_module, "BASE_VLC_ARGS", backend_module.BASE_VLC_ARGS + ["--aout=adummy", "--vout=dummy"]
    )
    p = VLCPlayer()
    yield p
    p._release_instance()


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _wav(path, seconds=1.0):
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\x00\x00" * int(8000 * seconds))
    return str(path)


def _expected(index):
    eq = vlc.libvlc_audio_equalizer_new_from_preset(index)
    try:
        return eq.get_preamp(), [eq.get_amp_at_index(i) for i in range(vlc.libvlc_audio_equalizer_get_band_count())]
    finally:
        eq.release()


def test_every_preset_applies_the_real_preset_values(player):
    count = vlc.libvlc_audio_equalizer_get_preset_count()
    assert count > 0
    for index in range(count):
        assert player.apply_equalizer_preset(index) is True
        preamp, bands = player.get_equalizer_values()
        exp_preamp, exp_bands = _expected(index)
        assert preamp == pytest.approx(exp_preamp)
        assert bands == pytest.approx(exp_bands)


def test_after_a_preset_bands_change_and_the_instance_can_be_recreated(player, tmp_path):
    assert player.apply_equalizer_preset(13)  # "Rock"
    player.set_equalizer_band(0, 2.0)
    player.set_equalizer_preamp(-3.0)
    preamp, bands = player.get_equalizer_values()
    assert preamp == pytest.approx(-3.0) and bands[0] == pytest.approx(2.0)
    # Con el bug, recrear el Instance (audio con visualizador) reaplicaba el
    # puntero invalido en _create_instance -> access violation.
    player.load(_wav(tmp_path / "a.wav"), enable_visualizer=True)
    assert player._visualizer_on is True
    player.load(_wav(tmp_path / "b.wav"), enable_visualizer=False)
    assert player.get_equalizer_values()[1][0] == pytest.approx(2.0)


def test_the_flat_preset_is_a_real_equalizer_not_none(player):
    assert player.apply_equalizer_preset(0)
    assert player.get_equalizer() is not None


def test_an_unknown_preset_is_rejected_and_keeps_the_current_one(player):
    assert player.apply_equalizer_preset(3)
    before = player.get_equalizer_values()
    assert player.apply_equalizer_preset(10_000) is False
    assert player.get_equalizer_values() == before


def test_replacing_or_disabling_releases_the_previous_equalizer(player, monkeypatch):
    assert player.apply_equalizer_preset(1)
    released = []
    old = player.get_equalizer()
    original = old.release
    monkeypatch.setattr(old, "release", lambda: (released.append("preset"), original()))
    assert player.apply_equalizer_preset(2)
    assert released == ["preset"]

    current = player.get_equalizer()
    original2 = current.release
    monkeypatch.setattr(current, "release", lambda: (released.append("disable"), original2()))
    player.disable_equalizer()
    assert released == ["preset", "disable"]
    assert player.get_equalizer() is None and player.get_equalizer_values() is None


def test_set_equalizer_values_restores_exact_values(player):
    bands = [0.8 * i for i in range(10)]
    player.set_equalizer_values(4.8, bands)
    preamp, got = player.get_equalizer_values()
    assert preamp == pytest.approx(4.8) and got == pytest.approx(bands)


def test_choosing_a_preset_in_the_dialog_updates_sliders(qapp, player):
    dialog = EqualizerDialog(player)
    try:
        dialog.enable_checkbox.setChecked(True)
        for data in (0, 13):  # "Plano" (antes AttributeError sobre None) y "Rock"
            dialog.preset_combo.setCurrentIndex(dialog.preset_combo.findData(data))
            exp_preamp, exp_bands = _expected(data)
            assert dialog.preamp_slider.value() == round(exp_preamp * 10)
            assert [s.value() for s in dialog.band_sliders] == [round(b * 10) for b in exp_bands]
        state = dialog.state()
        assert state.enabled and state.preset == 13
        assert state.bands == pytest.approx(_expected(13)[1])  # exactos, no los enteros del slider
    finally:
        dialog.close()


def test_dialog_built_later_shows_the_restored_equalizer(qapp, player):
    player.set_equalizer_values(6.0, [1.0] * 10)
    dialog = EqualizerDialog(player, initial=EqualizerSettings(enabled=True, preset=5, preamp=6.0, bands=[1.0] * 10))
    try:
        assert dialog.enable_checkbox.isChecked()
        assert dialog.preset_combo.currentData() == 5
        assert dialog.preamp_slider.value() == 60
        assert dialog.preamp_spin.value() == pytest.approx(6.0)
        # Sincronizar el combo no debe reaplicar el preset encima de los
        # valores restaurados.
        assert player.get_equalizer_values()[1] == pytest.approx([1.0] * 10)
    finally:
        dialog.close()


def test_mute_toggles_even_after_stop(player, tmp_path):
    # libVLC devuelve -1 en audio_get_mute() sin audio abierto (tras stop):
    # antes is_muted() lo tomaba como True y el boton de silencio no hacia nada.
    player.load(_wav(tmp_path / "m.wav"))
    player.play()
    player.stop()
    assert player.is_muted() is False
    player.set_muted(not player.is_muted())
    assert player.is_muted() is True


def test_band_labels_and_preset_names_are_spanish():
    from player.equalizer_dialog import PRESET_NAMES_ES, format_band_frequency, preset_display_name

    assert [format_band_frequency(f) for f in (31.25, 62.5, 1000, 16000, 125)] == [
        "31,2 Hz", "62,5 Hz", "1 kHz", "16 kHz", "125 Hz"]
    assert len(PRESET_NAMES_ES) == 18
    assert preset_display_name("Full bass and treble") == "Graves y agudos"
    assert preset_display_name("Desconocido") == "Desconocido"


def test_dialog_uses_tenth_db_steps_and_spinboxes(qapp, player):
    dialog = EqualizerDialog(player)
    try:
        dialog.enable_checkbox.setChecked(True)
        dialog.preamp_slider.setValue(15)
        dialog.band_sliders[0].setValue(-25)
        assert dialog.preamp_spin.value() == pytest.approx(1.5)
        assert dialog.band_spins[0].value() == pytest.approx(-2.5)
        assert dialog.preamp_value_label.text() == "+1,5 dB"
        assert dialog.band_value_labels[0].text() == "-2,5 dB"

        dialog.preamp_spin.setValue(-3.2)
        dialog.band_spins[1].setValue(4.4)
        assert dialog.preamp_slider.value() == -32
        assert dialog.band_sliders[1].value() == 44
        preamp, bands = player.get_equalizer_values()
        assert preamp == pytest.approx(-3.2)
        assert bands[1] == pytest.approx(4.4)
    finally:
        dialog.close()
