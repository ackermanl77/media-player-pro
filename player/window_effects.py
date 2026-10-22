"""Audio > Efectos (3.17) y Video > Filtros (4.17) de MainWindow. Mixin, como
window_menus.

- Efectos de audio: modo nocturno (compresor), ampliar estereo y sonido
  envolvente virtual para auriculares se encienden en vivo (la cadena
  "audio-filter" del reproductor, vlc_internals); el modo nocturno lleva
  ademas parametros de instancia, y el tono (scaletempo_pitch, en semitonos)
  es opcion de instancia: esos dos recargan el archivo conservando el estado.
- Filtros de video: enfocar, reducir ruido, suavizar bandas y quitar bloques
  van en la misma opcion --video-filter que la rotacion, asi que se aplican
  igual que ella (reload_preserving_state).
"""

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu

from .backend import libvlc_version
from .video_options import AUDIO_EFFECTS, PITCH_STEPS, VIDEO_FILTERS, choice_label, format_pitch


class EffectsMixin:
    def _build_audio_effects_menu(self, parent_menu) -> QMenu:
        menu = QMenu("Efectos", parent_menu)
        menu.setToolTipsVisible(True)
        self.audio_effect_actions = {}
        tips = {
            "compressor": "Acerca el volumen de diálogos y explosiones: para ver películas de noche sin molestar",
            "stereo_widen": "Separa más los canales izquierdo y derecho",
            "headphone_channel_mixer": "Simula altavoces alrededor al escuchar con auriculares",
        }
        for label, value in AUDIO_EFFECTS:
            action = QAction(label, menu, checkable=True)
            action.setData(value)
            action.setToolTip(tips[value])
            action.toggled.connect(lambda _checked: self._on_audio_effects_changed())
            self.audio_effect_actions[value] = action
            menu.addAction(action)
        menu.addSeparator()
        self.menu_pitch = menu.addMenu("Tono")
        self.pitch_group = QActionGroup(self.menu_pitch)
        self.pitch_group.setExclusive(True)
        for step in PITCH_STEPS:
            action = QAction(format_pitch(step), self.menu_pitch, checkable=True)
            action.setData(float(step))
            action.setChecked(step == 0)
            action.triggered.connect(lambda _checked, s=step: self._set_pitch(s))
            self.pitch_group.addAction(action)
            self.menu_pitch.addAction(action)
        if not self.player.audio_effects_supported():
            menu.setEnabled(False)
            menu.setToolTip(f"No disponible con esta versión de VLC ({libvlc_version()})")
        return menu

    def _build_video_filters_menu(self, parent_menu) -> QMenu:
        menu = QMenu("Filtros", parent_menu)
        menu.setToolTipsVisible(True)
        self.video_filter_actions = {}
        tips = {
            "sharpen": "Realza los bordes de un video algo blando",
            "hqdn3d": "Suaviza el grano y el ruido (videos con poca luz)",
            "gradfun": "Quita los escalones de color en cielos y degradados",
            "postproc": "Disimula los bloques de un video muy comprimido",
        }
        for label, value in VIDEO_FILTERS:
            action = QAction(label, menu, checkable=True)
            action.setData(value)
            action.setToolTip(tips[value])
            action.toggled.connect(lambda _checked: self._on_video_filters_changed())
            self.video_filter_actions[value] = action
            menu.addAction(action)
        return menu

    @staticmethod
    def _set_checked_quietly(action, checked: bool):
        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def _checked_values(self, actions: dict) -> tuple:
        return tuple(value for value, action in actions.items() if action.isChecked())

    # -- Audio > Efectos (3.17) -------------------------------------------------
    def _on_audio_effects_changed(self, announce: bool = True):
        effects = self._checked_values(self.audio_effect_actions)
        needs_reload = self.player.set_audio_effects(effects)
        if needs_reload and self.current_index != -1:
            self.player.reload_preserving_state()
            self._report_dropped_options()
        if announce:
            names = [label for label, value in AUDIO_EFFECTS if value in effects]
            self._show_osd("Efectos: " + (", ".join(names) if names else "ninguno"))

    def _set_pitch(self, semitones: float, announce: bool = True):
        for action in self.pitch_group.actions():
            action.setChecked(action.data() == float(semitones))
        if self.player.set_pitch(semitones) and self.current_index != -1:
            self.player.reload_preserving_state()
            self._report_dropped_options()
        if announce:
            self._show_osd(f"Tono: {format_pitch(self.player.get_pitch())}")

    def _restore_audio_effects(self, effects, pitch: float):
        for value, action in self.audio_effect_actions.items():
            self._set_checked_quietly(action, value in effects)
        self.player.set_audio_effects(effects)
        self._set_pitch(pitch, announce=False)

    # -- Video > Filtros (4.17) -------------------------------------------------
    def _on_video_filters_changed(self, announce: bool = True):
        filters = self._checked_values(self.video_filter_actions)
        if filters == self.player.get_video_filters():
            return
        self.player.set_video_filters(filters)
        if self.current_index != -1:
            self.player.reload_preserving_state()
        self._report_dropped_options()
        if announce:
            names = [choice_label(VIDEO_FILTERS, value) for value in filters]
            self._show_osd("Filtros: " + (", ".join(names) if names else "ninguno"))

    def _restore_video_filters(self, filters):
        for value, action in self.video_filter_actions.items():
            self._set_checked_quietly(action, value in filters)
        self.player.set_video_filters(filters)

    def _uncheck_dropped_effects(self, dropped) -> list:
        """Si libVLC rechazo los filtros o efectos, desmarcarlos; devuelve los
        nombres para el aviso de _report_dropped_options()."""
        messages = []
        if "rotation" in dropped:
            for action in self.video_filter_actions.values():
                self._set_checked_quietly(action, False)
        if "audio_effects" in dropped:
            for action in self.audio_effect_actions.values():
                self._set_checked_quietly(action, False)
            for action in self.pitch_group.actions():
                action.setChecked(action.data() == 0.0)
            messages.append("los efectos de audio")
        return messages
