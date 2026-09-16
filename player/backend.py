"""Envoltorio delgado sobre python-vlc: decodificacion nativa (sin recompresion)
para maxima calidad y compatibilidad de formatos, aceleracion por hardware cuando
el driver de video la soporta."""

import os
import sys

import vlc

from .formats import is_audio_file, is_url

BASE_VLC_ARGS = [
    "--no-video-title-show",
    "--quiet",
    "--avcodec-hw=any",
]

# audio-visual/effect-list son opciones de instancia/reproductor: libvlc las
# ignora silenciosamente si se pasan como media.add_option() por-input, asi
# que solo se pueden activar recreando el Instance con ellas en los args.
VISUALIZER_VLC_ARGS = ["--audio-visual=visual", "--effect-list=spectrum"]


class VLCPlayer:
    def __init__(self):
        self._volume = 80
        self._muted = False
        self._rate = 1.0
        self._equalizer = None
        self._video_widget = None
        self._visualizer_on = False
        self._create_instance(visualizer=False)

    def _create_instance(self, visualizer: bool):
        args = BASE_VLC_ARGS + (VISUALIZER_VLC_ARGS if visualizer else [])
        self.instance = vlc.Instance(args)
        self.media_player = self.instance.media_player_new()
        self._visualizer_on = visualizer

        self.media_player.audio_set_volume(self._volume)
        self.media_player.audio_set_mute(self._muted)
        self.media_player.set_rate(self._rate)
        if self._equalizer is not None:
            self.media_player.set_equalizer(self._equalizer)
        if self._video_widget is not None:
            self._attach_to_widget(self._video_widget)

    # -- salida de video ---------------------------------------------------
    def _attach_to_widget(self, widget):
        wid = int(widget.winId())
        if sys.platform.startswith("win"):
            self.media_player.set_hwnd(wid)
        elif sys.platform.startswith("linux"):
            self.media_player.set_xwindow(wid)
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(wid)

    def attach_video_output(self, widget):
        self._video_widget = widget
        self._attach_to_widget(widget)

    # -- carga / transporte --------------------------------------------------
    def load(self, path_or_url: str, enable_visualizer: bool = False):
        # Sin el visualizador, un archivo de solo audio deja el video_frame en
        # negro. El filtro "visual" de libVLC genera un espectro y lo manda
        # por la misma salida de video ya embebida, como si fuera un video
        # normal -- pero solo se puede activar/desactivar recreando el
        # Instance (ver VISUALIZER_VLC_ARGS).
        want_visualizer = enable_visualizer and is_audio_file(path_or_url)
        if want_visualizer != self._visualizer_on:
            self.media_player.stop()
            self._create_instance(visualizer=want_visualizer)

        if is_url(path_or_url):
            media = self.instance.media_new(path_or_url)
        else:
            # libvlc_media_new_path falla silenciosamente en Windows con
            # rutas que usan "/" (el reproductor se queda en
            # State.NothingSpecial para siempre, sin pasar nunca a
            # State.Error): normalizar a "\" antes de pasarlo. Rutas asi
            # llegan tipicamente por argumentos de linea de comandos.
            media = self.instance.media_new_path(os.path.normpath(path_or_url))
        self.media_player.set_media(media)
        return media

    def play(self):
        self.media_player.play()

    def toggle_pause(self):
        self.media_player.pause()

    def stop(self):
        self.media_player.stop()

    def is_playing(self) -> bool:
        return self.media_player.is_playing() == 1

    def get_state(self):
        return self.media_player.get_state()

    # -- tiempo / posicion ----------------------------------------------------
    def get_length_ms(self) -> int:
        return max(self.media_player.get_length(), 0)

    def get_time_ms(self) -> int:
        return max(self.media_player.get_time(), 0)

    def set_time_ms(self, ms: int):
        self.media_player.set_time(int(ms))

    def get_position(self) -> float:
        return max(self.media_player.get_position(), 0.0)

    def set_position(self, pos: float):
        self.media_player.set_position(pos)

    # -- audio -----------------------------------------------------------
    def get_volume(self) -> int:
        return self.media_player.audio_get_volume()

    def set_volume(self, vol: int):
        self._volume = max(0, min(200, vol))
        self.media_player.audio_set_volume(self._volume)

    def is_muted(self) -> bool:
        return bool(self.media_player.audio_get_mute())

    def set_muted(self, muted: bool):
        self._muted = muted
        self.media_player.audio_set_mute(muted)

    def get_rate(self) -> float:
        return self.media_player.get_rate()

    def set_rate(self, rate: float):
        self._rate = rate
        self.media_player.set_rate(rate)

    def audio_tracks(self):
        return self.media_player.audio_get_track_description() or []

    def get_current_audio_track(self) -> int:
        return self.media_player.audio_get_track()

    def set_audio_track(self, track_id: int):
        self.media_player.audio_set_track(track_id)

    # -- subtitulos --------------------------------------------------------
    def subtitle_tracks(self):
        return self.media_player.video_get_spu_description() or []

    def get_current_subtitle_track(self) -> int:
        return self.media_player.video_get_spu()

    def set_subtitle_track(self, track_id: int):
        self.media_player.video_set_spu(track_id)

    def load_subtitle_file(self, path: str):
        self.media_player.video_set_subtitle_file(path)

    # -- video -------------------------------------------------------------
    def take_snapshot(self, path: str, width: int = 0, height: int = 0):
        self.media_player.video_take_snapshot(0, path, width, height)

    def has_active_video_output(self) -> bool:
        return bool(self.media_player.has_vout())

    def has_video(self) -> bool:
        if not self.media_player.has_vout():
            return False
        w, h = self.media_player.video_get_size(0)
        return w > 0 and h > 0

    # -- ecualizador -------------------------------------------------------
    def equalizer_preset_names(self):
        count = vlc.libvlc_audio_equalizer_get_preset_count()
        return [
            vlc.libvlc_audio_equalizer_get_preset_name(i).decode("utf-8")
            for i in range(count)
        ]

    def equalizer_band_frequencies(self):
        count = vlc.libvlc_audio_equalizer_get_band_count()
        return [vlc.libvlc_audio_equalizer_get_band_frequency(i) for i in range(count)]

    def get_equalizer(self):
        return self._equalizer

    def apply_equalizer_preset(self, index: int):
        eq = vlc.AudioEqualizer(index)
        self._equalizer = eq
        self.media_player.set_equalizer(eq)

    def set_equalizer_preamp(self, amp: float):
        if self._equalizer is None:
            self._equalizer = vlc.AudioEqualizer()
        self._equalizer.set_preamp(amp)
        self.media_player.set_equalizer(self._equalizer)

    def set_equalizer_band(self, index: int, amp: float):
        if self._equalizer is None:
            self._equalizer = vlc.AudioEqualizer()
        self._equalizer.set_amp_at_index(amp, index)
        self.media_player.set_equalizer(self._equalizer)

    def disable_equalizer(self):
        self._equalizer = None
        self.media_player.set_equalizer(None)
