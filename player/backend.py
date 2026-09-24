"""Envoltorio delgado sobre python-vlc: decodificacion nativa (sin recompresion)
para maxima calidad y compatibilidad de formatos, aceleracion por hardware cuando
el driver de video la soporta."""

import os
import pathlib
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

DEFAULT_SUBTITLE_SCALE = 100  # porcentaje; --sub-text-scale es tambien de instancia


class VLCPlayer:
    def __init__(self):
        self._volume = 80
        self._muted = False
        self._rate = 1.0
        self._equalizer = None
        self._video_widget = None
        self._visualizer_on = False
        self._subtitle_scale = DEFAULT_SUBTITLE_SCALE
        self._instance_subtitle_scale = DEFAULT_SUBTITLE_SCALE
        self._video_scale = 0.0  # 0 = ajustar a ventana (default de libVLC)
        self.instance = None
        self.media_player = None
        # Ruta/URL cargada con load() y subtitulos externos agregados sobre
        # ella: hacen falta para recargar el mismo archivo al recrear el
        # Instance (ver reload_preserving_state).
        self._current_path = None
        self._external_subtitles = []
        self._pending_restore = None
        # Lo pone en True el evento MediaPlayerEncounteredError (hilo de
        # libVLC): en libVLC 3 un archivo inexistente dispara el evento pero
        # get_state() termina en Ended, no en Error (ver
        # playlist_order.playback_failed).
        self._error_seen = False
        # Reproductor secundario, invisible, dedicado solo a generar
        # miniaturas de vista previa al pasar el mouse por la barra de
        # progreso -- separado del media_player principal para no
        # interrumpir la reproduccion real (ver seek_preview()/
        # take_preview_snapshot()).
        self._preview_player = None
        self._preview_widget = None
        self._preview_path = None
        self._preview_warmed_up = False
        self._create_instance(visualizer=False)

    def _release_instance(self):
        """Libera explicitamente los objetos de libVLC actuales. Reemplazar
        las referencias de Python no alcanza: python-vlc no llama release()
        al recolectarlas, asi que cada recreacion (cambiar entre audio y
        video con el visualizador, cambiar el tamano de subtitulos) dejaba
        un MediaPlayer + Instance completos (hilos, vout, decodificadores)
        vivos hasta cerrar la app -- y el reproductor de vista previa
        seguia decodificando el archivo viejo."""
        if self._preview_player is not None:
            self._preview_player.stop()
            self._preview_player.release()
            self._preview_player = None
        if self.media_player is not None:
            self.media_player.stop()
            self.media_player.release()
            self.media_player = None
        if self.instance is not None:
            self.instance.release()
            self.instance = None

    def _on_vlc_error(self, _event):
        self._error_seen = True

    def _create_instance(self, visualizer: bool):
        self._release_instance()
        args = BASE_VLC_ARGS + (VISUALIZER_VLC_ARGS if visualizer else [])
        args = args + [f"--sub-text-scale={self._subtitle_scale}"]
        self.instance = vlc.Instance(args)
        self.media_player = self.instance.media_player_new()
        self.media_player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error
        )
        self._visualizer_on = visualizer
        self._instance_subtitle_scale = self._subtitle_scale

        self.media_player.audio_set_volume(self._volume)
        self.media_player.audio_set_mute(self._muted)
        self.media_player.set_rate(self._rate)
        if self._equalizer is not None:
            self.media_player.set_equalizer(self._equalizer)
        # El zoom es estado del MediaPlayer (no del Media): sin esto, se
        # perdia en silencio al recrear -- el menu seguia marcando "200%"
        # mientras el video volvia a "ajustar a ventana".
        self.media_player.video_set_scale(self._video_scale)
        if self._video_widget is not None:
            self._attach_to_widget(self._video_widget)
        # El reproductor de vista previa (si existia) vivia en la Instance
        # vieja y se libero con ella (_release_instance): se recrea
        # perezosamente (ver _ensure_preview_player) contra la nueva,
        # reenganchandose al mismo widget invisible si habia uno.
        self._preview_path = None
        self._preview_warmed_up = False
        if self._preview_widget is not None:
            self._attach_preview_widget(self._preview_widget)

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
        if want_visualizer != self._visualizer_on or self._subtitle_scale != self._instance_subtitle_scale:
            self._create_instance(visualizer=want_visualizer)

        media = self._new_media(path_or_url)
        self.media_player.set_media(media)
        self._current_path = path_or_url
        self._external_subtitles = []
        self._pending_restore = None
        self._error_seen = False
        return media

    def _new_media(self, path_or_url: str):
        if is_url(path_or_url):
            return self.instance.media_new(path_or_url)
        # libvlc_media_new_path falla silenciosamente en Windows con
        # rutas que usan "/" (el reproductor se queda en
        # State.NothingSpecial para siempre, sin pasar nunca a
        # State.Error): normalizar a "\" antes de pasarlo. Rutas asi
        # llegan tipicamente por argumentos de linea de comandos.
        return self.instance.media_new_path(os.path.normpath(path_or_url))

    def reload_preserving_state(self) -> bool:
        """Recrea el Instance (para aplicar opciones de instancia como
        --sub-text-scale) y recarga el mismo archivo SIN pasar por el flujo
        de "abrir pista" de la UI: conserva posicion, pausa, pista de audio,
        pista de subtitulos, subtitulos externos cargados y desfase de
        subtitulos. Devuelve False (sin hacer nada) si no hay nada
        reproduciendose/en pausa -- en ese caso la proxima load() ya recrea
        el Instance por su cuenta.

        Verificado contra libVLC 3.0.23: la posicion, la pista de audio, la
        de subtitulos y los subtitulos externos se pueden fijar como
        opciones del Media antes de play(); el desfase de subtitulos no (y
        se resetea a 0 con cada Media nuevo), asi que ese -- y deshabilitar
        pistas (id -1), que no tiene opcion equivalente -- se reaplica en
        apply_pending_restore() una vez que el nuevo input esta en Playing."""
        state = self.get_state()
        if self._current_path is None or state not in (vlc.State.Playing, vlc.State.Paused):
            return False
        snapshot = {
            "time_ms": self.get_time_ms(),
            "paused": state == vlc.State.Paused,
            "audio_track": self.get_current_audio_track(),
            "subtitle_track": self.get_current_subtitle_track(),
            "subtitle_delay_ms": self.get_subtitle_delay_ms(),
        }
        external_subtitles = list(self._external_subtitles)
        path = self._current_path

        self._create_instance(visualizer=self._visualizer_on)
        media = self._new_media(path)
        if snapshot["time_ms"] > 0:
            media.add_option(f":start-time={snapshot['time_ms'] / 1000:.3f}")
        if snapshot["audio_track"] >= 0:
            media.add_option(f":audio-track-id={snapshot['audio_track']}")
        if snapshot["subtitle_track"] >= 0:
            media.add_option(f":sub-track-id={snapshot['subtitle_track']}")
        for sub in external_subtitles:
            media.slaves_add(vlc.MediaSlaveType.subtitle, 4, pathlib.Path(sub).absolute().as_uri())
        self.media_player.set_media(media)
        self._external_subtitles = external_subtitles
        self._error_seen = False
        self._pending_restore = snapshot
        self.media_player.play()
        return True

    def apply_pending_restore(self) -> bool:
        """Termina lo que reload_preserving_state() no puede fijar antes de
        play(). Se llama desde el tick de la UI; no hace nada hasta que el
        input nuevo llega a Playing. Devuelve True cuando lo aplico."""
        if self._pending_restore is None:
            return False
        state = self.get_state()
        if state in (vlc.State.Ended, vlc.State.Error, vlc.State.Stopped):
            self._pending_restore = None
            return False
        if state != vlc.State.Playing:
            return False
        self._pending_restore["waits"] = self._pending_restore.get("waits", 0) + 1
        if (
            self._pending_restore["time_ms"] > 0
            and self.get_time_ms() <= 0
            and self._pending_restore["waits"] <= 20  # ~5 s de ticks de la UI
        ):
            # Verificado contra libVLC 3.0.23: pausar apenas llega a Playing,
            # antes de que el :start-time se haga efectivo, deja el tiempo
            # clavado en 0 aunque se reanude despues. Esperar al proximo tick.
            return False
        snapshot, self._pending_restore = self._pending_restore, None
        if snapshot["subtitle_delay_ms"]:
            self.set_subtitle_delay_ms(snapshot["subtitle_delay_ms"])
        if snapshot["audio_track"] < 0:
            self.set_audio_track(-1)
        if snapshot["subtitle_track"] != self.get_current_subtitle_track():
            self.set_subtitle_track(snapshot["subtitle_track"])
        if snapshot["paused"]:
            self.set_paused(True)
        return True

    def current_path(self):
        return self._current_path

    def error_seen(self) -> bool:
        return self._error_seen

    def is_idle(self) -> bool:
        """True si no hay nada en curso que pausar/reanudar: nunca se
        reprodujo, se detuvo, termino o fallo. En esos estados
        libvlc_media_player_pause() es un no-op (verificado contra libVLC
        3.0.23), asi que Reproducir/Pausa tiene que volver a llamar play()."""
        return self.get_state() in (
            vlc.State.NothingSpecial, vlc.State.Stopped, vlc.State.Ended, vlc.State.Error,
        )

    def play(self):
        self.media_player.play()

    def toggle_pause(self):
        self.media_player.pause()

    def set_paused(self, paused: bool):
        self.media_player.set_pause(1 if paused else 0)

    def stop(self):
        self.media_player.stop()

    def is_playing(self) -> bool:
        return self.media_player.is_playing() == 1

    def is_paused(self) -> bool:
        return self.media_player.get_state() == vlc.State.Paused

    def get_state(self):
        return self.media_player.get_state()

    def next_frame(self) -> bool:
        """Avanza un solo fotograma (libvlc_media_player_next_frame). Solo
        tiene sentido con el reproductor en pausa: si sigue reproduciendo,
        el siguiente refresco de video pisa de inmediato el fotograma
        adelantado, y ademas varios modulos de video de libVLC ignoran la
        llamada si el estado no es Paused. Devuelve False sin llamar a
        libVLC si no esta pausado."""
        if not self.is_paused():
            return False
        self.media_player.next_frame()
        return True

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
        if path not in self._external_subtitles:
            self._external_subtitles.append(path)

    def get_subtitle_delay_ms(self) -> int:
        return self.media_player.video_get_spu_delay() // 1000

    def set_subtitle_delay_ms(self, delay_ms: int):
        self.media_player.video_set_spu_delay(delay_ms * 1000)

    def set_subtitle_scale(self, scale: int):
        # --sub-text-scale es una opcion de instancia (modulo freetype): no
        # hay setter en caliente en el MediaPlayer, asi que solo cambia el
        # valor objetivo aqui; load() recrea el Instance en la proxima carga
        # (ver la comparacion con _instance_subtitle_scale mas arriba).
        self._subtitle_scale = scale

    # -- video -------------------------------------------------------------
    def set_video_scale(self, factor: float):
        self._video_scale = factor
        self.media_player.video_set_scale(factor)

    def get_video_scale(self) -> float:
        return self._video_scale

    def take_snapshot(self, path: str, width: int = 0, height: int = 0):
        self.media_player.video_take_snapshot(0, path, width, height)

    def has_active_video_output(self) -> bool:
        return bool(self.media_player.has_vout())

    def has_video(self) -> bool:
        if not self.media_player.has_vout():
            return False
        w, h = self.media_player.video_get_size(0)
        return w > 0 and h > 0

    # -- vista previa de la barra de progreso -------------------------------
    # libVLC no ofrece forma de capturar un fotograma en una posicion dada
    # sin realmente decodificar hasta ahi: no hay una API de "snapshot en
    # frio". La unica manera confiable con python-vlc de no interrumpir la
    # reproduccion real es un segundo vlc.MediaPlayer (misma Instance, mismo
    # archivo) que se busca y capta por separado; el media_player principal
    # nunca se toca. Esto sigue implicando una busqueda real (aunque
    # invisible para el usuario) en ese reproductor secundario.
    def _ensure_preview_player(self):
        if self._preview_player is None:
            self._preview_player = self.instance.media_player_new()
            self._preview_player.audio_set_mute(True)
        return self._preview_player

    def _attach_preview_widget(self, widget):
        player = self._ensure_preview_player()
        wid = int(widget.winId())
        if sys.platform.startswith("win"):
            player.set_hwnd(wid)
        elif sys.platform.startswith("linux"):
            player.set_xwindow(wid)
        elif sys.platform == "darwin":
            player.set_nsobject(wid)

    def attach_preview_output(self, widget):
        """Engancha el reproductor de vista previa a un widget que nunca se
        muestra en pantalla -- solo existe para darle a libVLC una ventana
        nativa donde crear su salida de video."""
        self._preview_widget = widget
        self._attach_preview_widget(widget)

    def preview_current_path(self):
        return self._preview_path

    def load_preview_media(self, path_or_url: str):
        """Carga (sin que el usuario la vea ni la oiga -- silenciado en
        _ensure_preview_player) el archivo actual en el reproductor de
        vista previa. No hace falta recargar si ya es el mismo archivo
        (ver preview_current_path).

        Deliberadamente NO se pausa aqui. Se probo contra libVLC real:
        llamar set_pause(1) inmediatamente despues de play(), antes de que
        el primer fotograma llegue a la salida de video, deja el vout
        "vacio" para siempre -- has_vout() e incluso
        video_take_snapshot() siguen devolviendo exito, pero nunca se
        escribe ningun archivo, en ningun intento posterior. Se deja
        reproduciendo (silenciado) hasta que take_preview_snapshot()
        confirma que ya salio un fotograma real, momento en el que recien
        es seguro pausarlo (ver ahi)."""
        player = self._ensure_preview_player()
        if is_url(path_or_url):
            media = self.instance.media_new(path_or_url)
        else:
            media = self.instance.media_new_path(os.path.normpath(path_or_url))
        player.set_media(media)
        player.play()
        self._preview_path = path_or_url
        self._preview_warmed_up = False

    def seek_preview(self, position: float):
        """Busca una posicion (0..1) en el reproductor de vista previa. Es
        una busqueda real, pero en un reproductor separado e invisible, asi
        que no afecta la posicion/estado de lo que el usuario esta viendo."""
        if self._preview_player is None:
            return
        self._preview_player.set_position(max(0.0, min(1.0, position)))

    def take_preview_snapshot(self, path: str, width: int = 0, height: int = 0) -> bool:
        if self._preview_player is None:
            return False
        ok = self._preview_player.video_take_snapshot(0, path, width, height) == 0
        if ok and not self._preview_warmed_up:
            # Ya salio al menos un fotograma real de la salida de video:
            # pausar ahora (a diferencia de pausar antes del primer
            # fotograma, ver load_preview_media) deja el reproductor listo
            # para seguir sirviendo capturas en futuras busquedas sin
            # seguir decodificando/gastando CPU de fondo entre un hover y
            # el siguiente.
            self._preview_warmed_up = True
            self._preview_player.set_pause(1)
        return ok

    def stop_preview(self):
        """Detiene (sin liberar) el reproductor de vista previa y olvida el
        archivo cargado, para que no siga decodificando en segundo plano
        (p. ej. si el mouse salio de la barra antes de la primera captura,
        momento en que todavia no se pudo pausar -- ver load_preview_media)
        ni retenga abierto un archivo que ya no es el actual."""
        if self._preview_player is not None:
            self._preview_player.stop()
        self._preview_path = None
        self._preview_warmed_up = False

    def is_preview_warmed_up(self) -> bool:
        return self._preview_warmed_up

    def release_preview_player(self):
        if self._preview_player is not None:
            self._preview_player.stop()
            self._preview_player.release()
            self._preview_player = None
            self._preview_path = None
            self._preview_warmed_up = False

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
