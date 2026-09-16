"""Envoltorio delgado sobre python-vlc: decodificacion nativa (sin recompresion)
para maxima calidad y compatibilidad de formatos, aceleracion por hardware cuando
el driver de video la soporta."""

import sys

import vlc

from .formats import is_url


class VLCPlayer:
    def __init__(self):
        vlc_args = [
            "--no-video-title-show",
            "--quiet",
            "--avcodec-hw=any",
        ]
        self.instance = vlc.Instance(vlc_args)
        self.media_player = self.instance.media_player_new()
        self._equalizer = None

    # -- salida de video ---------------------------------------------------
    def attach_video_output(self, widget):
        wid = int(widget.winId())
        if sys.platform.startswith("win"):
            self.media_player.set_hwnd(wid)
        elif sys.platform.startswith("linux"):
            self.media_player.set_xwindow(wid)
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(wid)

    # -- carga / transporte --------------------------------------------------
    def load(self, path_or_url: str):
        if is_url(path_or_url):
            media = self.instance.media_new(path_or_url)
        else:
            media = self.instance.media_new_path(path_or_url)
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
        self.media_player.audio_set_volume(max(0, min(200, vol)))

    def is_muted(self) -> bool:
        return bool(self.media_player.audio_get_mute())

    def set_muted(self, muted: bool):
        self.media_player.audio_set_mute(muted)

    def get_rate(self) -> float:
        return self.media_player.get_rate()

    def set_rate(self, rate: float):
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
