"""Envoltorio delgado sobre python-vlc: decodificacion nativa (sin recompresion)
para maxima calidad y compatibilidad de formatos, aceleracion por hardware cuando
el driver de video la soporta.

Es el unico modulo que importa `vlc`: la UI usa PlaybackState y las senales
de PlayerEvents (eventos de libVLC llevados al hilo de Qt) en vez de
vlc.State y de sondear el estado cada 250 ms."""

import enum
import logging
import os
import pathlib
import sys
import time

import vlc
from PySide6.QtCore import QObject, Signal

from . import vlc_internals
from .formats import is_audio_file, is_url
from .settings import (  # "any" = decodificacion por hardware automatica
    DEINTERLACE_MODES,
    HW_DECODING_MODES,
    MAX_VOLUME,
    VideoAdjustSettings,
)

BASE_VLC_ARGS = [
    "--no-video-title-show",
    "--quiet",
    "--avcodec-hw=any",
    # Reconectar un stream HTTP que se corta en vez de darlo por terminado.
    "--http-reconnect",
]

# audio-visual/effect-list son opciones de instancia/reproductor: libvlc las
# ignora silenciosamente si se pasan como media.add_option() por-input, asi
# que solo se pueden activar recreando el Instance con ellas en los args.
VISUALIZER_VLC_ARGS = ["--audio-visual=visual", "--effect-list=spectrum"]

# Instancia propia y liviana del reproductor de miniaturas: sin audio, sin
# subtitulos ni OSD, y sin las opciones de GPU/visualizador/subtitulos del
# principal (recrear el principal ya no la toca).
PREVIEW_VLC_ARGS = [
    "--quiet",
    "--no-audio",
    "--no-spu",
    "--no-osd",
    "--no-video-title-show",
    "--avcodec-hw=any",
]
# Busqueda rapida (salta al keyframe mas cercano): justo lo que necesita
# una miniatura, y mucho mas barata en HEVC/AV1 con GOP largos.
PREVIEW_MEDIA_OPTIONS = (":no-audio", ":no-spu", ":input-fast-seek")

DEFAULT_SUBTITLE_SCALE = 100  # porcentaje; --sub-text-scale es tambien de instancia
DEFAULT_NETWORK_CACHING_MS = 1000


log = logging.getLogger(__name__)


class VLCInitError(RuntimeError):
    """Ni siquiera BASE_VLC_ARGS produjo un vlc.Instance: la instalacion de
    VLC no sirve (o es demasiado vieja). run.py lo muestra al usuario."""


class PlaybackState(enum.Enum):
    IDLE = "idle"            # nunca se cargo nada
    OPENING = "opening"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"


_STATE_MAP = {
    vlc.State.NothingSpecial: PlaybackState.IDLE,
    vlc.State.Opening: PlaybackState.OPENING,
    vlc.State.Buffering: PlaybackState.BUFFERING,
    vlc.State.Playing: PlaybackState.PLAYING,
    vlc.State.Paused: PlaybackState.PAUSED,
    vlc.State.Stopped: PlaybackState.STOPPED,
    vlc.State.Ended: PlaybackState.ENDED,
    vlc.State.Error: PlaybackState.ERROR,
}

FINISHED_STATES = (PlaybackState.ENDED, PlaybackState.ERROR)
IDLE_STATES = (PlaybackState.IDLE, PlaybackState.STOPPED, PlaybackState.ENDED, PlaybackState.ERROR)


def disable_vlc_input(media_player):
    """Hace que la ventana de video que libVLC crea dentro de nuestro widget
    no se quede con el mouse ni el teclado. Por defecto libVLC crea una
    ventana hija HABILITADA ("VLC (Direct3D11 output)") que cubre todo el
    widget: el doble clic, el movimiento del mouse (controles flotantes en
    pantalla completa) y, tras un clic, el foco de teclado iban a esa ventana
    (de otro hilo) y nunca llegaban a Qt. Con esto la ventana hija queda
    deshabilitada y Windows le pasa la entrada al widget padre. Verificado
    contra libVLC 3.0.23 (ver tests/test_video_input.py). Son propiedades del
    MediaPlayer (sobreviven a set_media) pero hay que repetirlas cada vez
    que se crea uno nuevo."""
    media_player.video_set_mouse_input(False)
    media_player.video_set_key_input(False)


def _attach_window(media_player, widget):
    wid = int(widget.winId())
    if sys.platform.startswith("win"):
        media_player.set_hwnd(wid)
    elif sys.platform.startswith("linux"):
        media_player.set_xwindow(wid)
    elif sys.platform == "darwin":
        media_player.set_nsobject(wid)


def _decode(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def libvlc_version() -> str:
    try:
        return _decode(vlc.libvlc_get_version()).split(" ")[0]
    except Exception:  # noqa: BLE001 -- solo informativo
        return "?"


def gpu_instance_args(upscale: bool, hdr: bool, hw_decoding: str) -> list:
    """Opciones de instancia de la "Mejora por GPU" (Direct3D11, Windows).
    --d3d11-upscale-mode=super activa RTX Video Super Resolution (o el
    equivalente de Intel) y --d3d11-hdr-mode=generate RTX Video HDR; ambas
    las acepta libVLC 3.0.23 (un valor desconocido cae al modo por defecto).
    hw_decoding cambia --avcodec-hw de BASE_VLC_ARGS (el ultimo gana)."""
    args = []
    if hw_decoding in HW_DECODING_MODES and hw_decoding != "any":
        args.append(f"--avcodec-hw={hw_decoding}")
    if upscale:
        args.append("--d3d11-upscale-mode=super")
    if hdr:
        args.append("--d3d11-hdr-mode=generate")
    return args


def passthrough_instance_args(mode: str, platform: str = sys.platform) -> list:
    """Audio > Passthrough (3.16): el audio comprimido (AC3/DTS, o tambien E-AC3,
    TrueHD y DTS-HD) sale sin decodificar hacia un receptor o barra de sonido.
    En Windows es --mmdevice-passthrough de la salida WASAPI (1 = AC3/DTS,
    2 = todos); en otros sistemas, --spdif. Solo funciona si el dispositivo de
    salida lo admite; si no, libVLC decodifica como siempre."""
    if mode not in ("ac3_dts", "all"):
        return []
    if platform == "win32":
        return [f"--mmdevice-passthrough={1 if mode == 'ac3_dts' else 2}"]
    return ["--spdif"]


def create_instance_with_fallback(base_args, optional_groups, factory=None):
    """Intenta vlc.Instance(base + todos los grupos opcionales). Una opcion
    desconocida (p. ej. las de GPU en un VLC viejo) hace que vlc.Instance
    devuelva None; antes eso terminaba en un AttributeError dentro de
    load() y no se podia reproducir nada hasta reiniciar. Aqui se reintenta
    descartando los grupos en orden (el primero de la lista se descarta
    primero) y se devuelve (instancia, nombres descartados). Si ni la base
    sirve, VLCInitError."""
    factory = factory or vlc.Instance
    groups = [(name, list(args)) for name, args in optional_groups if args]
    for dropped_count in range(len(groups) + 1):
        kept = groups[dropped_count:]
        args = list(base_args) + [a for _name, group in kept for a in group]
        instance = factory(args)
        if instance is not None:
            dropped = [name for name, _group in groups[:dropped_count]]
            if dropped:
                log.warning("libVLC rechazo opciones; se descartaron: %s", dropped)
            return instance, dropped
        log.warning("vlc.Instance(%s) devolvio None", args)
    raise VLCInitError("libVLC no pudo inicializarse con sus opciones basicas")


class PlayerEvents(QObject):
    """Eventos de libVLC convertidos en senales de Qt. Los callbacks de
    libVLC corren en un hilo propio de libVLC y solo hacen emit(): como este
    QObject vive en el hilo de la UI, Qt encola la senal y el slot corre en
    el hilo principal. Nunca se llama a libVLC desde dentro de un callback
    (libVLC no es reentrante).

    Las senales de transicion llevan la "generacion" del Media que las
    disparo (VLCPlayer.generation): un EndReached del archivo anterior que
    llega encolado despues de abrir otro se descarta comparandola."""

    endReached = Signal(int)
    errorOccurred = Signal(int)
    opening = Signal(int)
    playing = Signal(int)
    paused = Signal(int)
    stopped = Signal(int)
    buffering = Signal(int, float)
    lengthChanged = Signal(int, int)
    chapterChanged = Signal(int, int)
    tracksChanged = Signal(int)
    metaChanged = Signal(int)
    snapshotTaken = Signal(str)


class VLCPlayer:
    def __init__(self):
        self._volume = 80
        self._muted = False
        self._rate = 1.0
        self._audio_delay_ms = 0
        self._equalizer = None
        self._video_widget = None
        self._visualizer_on = False
        self._subtitle_scale = DEFAULT_SUBTITLE_SCALE
        self._instance_subtitle_scale = DEFAULT_SUBTITLE_SCALE
        self._video_scale = 0.0  # 0 = ajustar a ventana (default de libVLC)
        # Estado del MediaPlayer que se reaplica al recrearlo (como el zoom):
        # relacion de aspecto y recorte ("" = el del video), desentrelazado
        # ("auto" = el default de libVLC, que no se puede volver a pedir una
        # vez fijado otro modo: hace falta un MediaPlayer nuevo), ajustes de
        # imagen, dispositivo de salida ("" = predeterminado) y normalizacion.
        self._aspect_ratio = ""
        self._crop = ""
        self._deinterlace = "auto"
        self._deinterlace_applied = False
        self._video_adjust = VideoAdjustSettings()
        self._audio_device = ""
        self._normalize = False
        # Mejora por GPU (opciones de instancia, ver gpu_instance_args).
        self._gpu_upscale = False
        self._gpu_hdr = False
        self._hw_decoding = "any"
        self._instance_gpu_args = []
        self._passthrough = "off"  # Audio > Passthrough (3.16)
        self._instance_passthrough_args = []
        # Grupos de opciones que libVLC rechazo en la ultima recreacion (ver
        # create_instance_with_fallback); la UI los lee con
        # take_dropped_options() para avisar y desmarcar el menu.
        self._dropped_options = []
        # Streams de red (opciones por Media, ver _new_media).
        self.network_caching_ms = DEFAULT_NETWORK_CACHING_MS
        self.rtsp_tcp = False
        self.instance = None
        self.media_player = None
        self._event_manager = None
        self._media = None
        self._media_event_manager = None
        self.events = PlayerEvents()
        # Se incrementa con cada Media nuevo (load/reload); ver PlayerEvents.
        self.generation = 0
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
        # progreso -- con su propia Instance liviana (PREVIEW_VLC_ARGS), asi
        # que no interrumpe la reproduccion real ni depende de sus ajustes
        # (ver seek_preview()/take_preview_snapshot()).
        self._preview_instance = None
        self._preview_player = None
        self._preview_widget = None
        self._preview_path = None
        self._preview_warmed_up = False
        self._create_instance(visualizer=False)

    # -- ciclo de vida -----------------------------------------------------
    def _release_main(self):
        if self.media_player is not None:
            self.media_player.stop()
            self.media_player.release()
            self.media_player = None
        self._event_manager = None
        self._release_media()
        if self.instance is not None:
            self.instance.release()
            self.instance = None

    def _release_media(self):
        if self._media is not None:
            self._media.release()
            self._media = None
        self._media_event_manager = None

    def _release_instance(self):
        """Libera explicitamente los objetos de libVLC del reproductor
        principal. Reemplazar las referencias de Python no alcanza:
        python-vlc no llama release() al recolectarlas, asi que cada
        recreacion (cambiar entre audio y video con el visualizador, cambiar
        el tamano de subtitulos) dejaba un MediaPlayer + Instance completos
        (hilos, vout, decodificadores) vivos hasta cerrar la app. El
        reproductor de vista previa tiene su propia Instance y no se toca."""
        self._release_main()

    def close(self):
        """Libera todo (principal y vista previa) antes de que Qt destruya
        los widgets nativos donde dibujan."""
        self.release_preview_player()
        self._release_main()

    def _gpu_args(self) -> list:
        return gpu_instance_args(self._gpu_upscale, self._gpu_hdr, self._hw_decoding)

    def _passthrough_args(self) -> list:
        return passthrough_instance_args(self._passthrough)

    def _create_instance(self, visualizer: bool):
        self._release_instance()
        base = BASE_VLC_ARGS + [f"--sub-text-scale={self._subtitle_scale}"]
        gpu = self._gpu_args()
        passthrough = self._passthrough_args()
        groups = [("gpu", gpu), ("passthrough", passthrough), ("visualizer", VISUALIZER_VLC_ARGS if visualizer else [])]
        log.info("Creando vlc.Instance con %s + %s", base, [g for _n, g in groups if g])
        self.instance, dropped = create_instance_with_fallback(base, groups)
        if dropped:
            self._dropped_options.extend(d for d in dropped if d not in self._dropped_options)
        if "gpu" in dropped:
            # No volver a intentarlo en cada carga: la UI desmarca el menu.
            self._gpu_upscale = self._gpu_hdr = False
            self._hw_decoding = "any"
            gpu = []
        if "passthrough" in dropped:
            self._passthrough = "off"
            passthrough = []
        if "visualizer" in dropped:
            visualizer = False
        self.media_player = self.instance.media_player_new()
        disable_vlc_input(self.media_player)
        self._attach_events()
        self._visualizer_on = visualizer
        self._instance_subtitle_scale = self._subtitle_scale
        self._instance_gpu_args = gpu
        self._instance_passthrough_args = passthrough

        self.media_player.audio_set_volume(self._volume)
        self.media_player.audio_set_mute(self._muted)
        self.media_player.set_rate(self._rate)
        if self._equalizer is not None:
            self.media_player.set_equalizer(self._equalizer)
        # El zoom es estado del MediaPlayer (no del Media): sin esto, se
        # perdia en silencio al recrear -- el menu seguia marcando "200%"
        # mientras el video volvia a "ajustar a ventana".
        self.media_player.video_set_scale(self._video_scale)
        self._apply_video_state()
        if self._audio_device:
            self.media_player.audio_output_device_set(None, self._audio_device)
        if self._normalize:
            self._apply_audio_filters()
        if self._video_widget is not None:
            _attach_window(self.media_player, self._video_widget)

    def take_dropped_options(self) -> list:
        dropped, self._dropped_options = self._dropped_options, []
        return dropped

    # -- eventos de libVLC -> Qt ---------------------------------------------
    def _attach_events(self):
        # Hay que conservar la referencia al EventManager: python-vlc guarda
        # el callback de ctypes en el propio objeto, y si este se recolecta
        # los eventos dejan de llegar (o llegan a un puntero liberado).
        em = self.media_player.event_manager()
        self._event_manager = em
        et = vlc.EventType
        ev = self.events
        handlers = {
            et.MediaPlayerEncounteredError: self._on_vlc_error,
            et.MediaPlayerEndReached: lambda _e: ev.endReached.emit(self.generation),
            et.MediaPlayerOpening: lambda _e: ev.opening.emit(self.generation),
            et.MediaPlayerPlaying: lambda _e: ev.playing.emit(self.generation),
            et.MediaPlayerPaused: lambda _e: ev.paused.emit(self.generation),
            et.MediaPlayerStopped: lambda _e: ev.stopped.emit(self.generation),
            et.MediaPlayerBuffering: lambda e: ev.buffering.emit(self.generation, float(e.u.new_cache)),
            et.MediaPlayerLengthChanged: lambda e: ev.lengthChanged.emit(self.generation, int(e.u.new_length)),
            # EventUnion (python-vlc) no expone new_chapter; es el mismo int
            # en el mismo offset que new_title.
            et.MediaPlayerChapterChanged: lambda e: ev.chapterChanged.emit(self.generation, int(e.u.new_title)),
            et.MediaPlayerESAdded: lambda _e: ev.tracksChanged.emit(self.generation),
            et.MediaPlayerESDeleted: lambda _e: ev.tracksChanged.emit(self.generation),
            et.MediaPlayerSnapshotTaken: lambda e: ev.snapshotTaken.emit(_decode(e.u.filename)),
        }
        for event_type, handler in handlers.items():
            em.event_attach(event_type, handler)

    def _on_vlc_error(self, _event):
        self._error_seen = True
        self.events.errorOccurred.emit(self.generation)

    def _attach_media_events(self, media):
        em = media.event_manager()
        self._media_event_manager = em
        em.event_attach(vlc.EventType.MediaMetaChanged, lambda _e: self.events.metaChanged.emit(self.generation))

    # -- salida de video ---------------------------------------------------
    def _attach_to_widget(self, widget):
        _attach_window(self.media_player, widget)

    def attach_video_output(self, widget):
        self._video_widget = widget
        self._attach_to_widget(widget)

    # -- carga / transporte --------------------------------------------------
    def _needs_new_instance(self, want_visualizer: bool) -> bool:
        return (
            want_visualizer != self._visualizer_on
            or self._subtitle_scale != self._instance_subtitle_scale
            or self._gpu_args() != self._instance_gpu_args
            or self._passthrough_args() != self._instance_passthrough_args
        )

    def load(self, path_or_url: str, enable_visualizer: bool = False, start_ms: int = 0):
        """start_ms: posicion inicial (reanudar). Va como :start-time del
        Media, asi el archivo arranca directo ahi -- antes se llamaba
        set_time() justo despues de play(), cuando libVLC todavia no tenia
        el archivo abierto: se oian/veian los primeros instantes desde 0:00
        y la busqueda podia perderse."""
        # Sin el visualizador, un archivo de solo audio deja el video_frame en
        # negro. El filtro "visual" de libVLC genera un espectro y lo manda
        # por la misma salida de video ya embebida, como si fuera un video
        # normal -- pero solo se puede activar/desactivar recreando el
        # Instance (ver VISUALIZER_VLC_ARGS). Para un stream de red no se
        # sabe hasta abrirlo (ver enable_stream_visualizer).
        want_visualizer = enable_visualizer and is_audio_file(path_or_url)
        if self._needs_new_instance(want_visualizer):
            self._create_instance(visualizer=want_visualizer)

        log.info("Abriendo %s", path_or_url)
        media = self._new_media(path_or_url)
        if start_ms and start_ms > 0:
            media.add_option(f":start-time={start_ms / 1000:.3f}")
        self._set_media(media)
        self._current_path = path_or_url
        self._external_subtitles = []
        self._pending_restore = None
        self._error_seen = False
        # El desfase de audio es del input: libVLC lo vuelve a 0 con cada
        # Media nuevo; se reaplica al llegar a Playing (apply_pending_restore).
        self._audio_delay_ms = 0
        return media

    def _set_media(self, media):
        self.generation += 1
        self._release_media()
        self._media = media
        self._attach_media_events(media)
        self.media_player.set_media(media)

    def _new_media(self, path_or_url: str):
        if is_url(path_or_url):
            media = self.instance.media_new(path_or_url)
            media.add_option(f":network-caching={int(self.network_caching_ms)}")
            if self.rtsp_tcp and path_or_url.lower().startswith(("rtsp://", "rtsps://")):
                media.add_option(":rtsp-tcp")
            return media
        # libvlc_media_new_path falla silenciosamente en Windows con
        # rutas que usan "/" (el reproductor se queda en
        # State.NothingSpecial para siempre, sin pasar nunca a
        # State.Error): normalizar a "\" antes de pasarlo. Rutas asi
        # llegan tipicamente por argumentos de linea de comandos.
        return self.instance.media_new_path(os.path.normpath(path_or_url))

    def reload_preserving_state(self, visualizer=None) -> bool:
        """Recrea el Instance (para aplicar opciones de instancia como
        --sub-text-scale, la mejora por GPU o el visualizador de un stream)
        y recarga el mismo archivo SIN pasar por el flujo de "abrir pista"
        de la UI: conserva posicion, pausa, pista de audio, pista de
        subtitulos, subtitulos externos cargados y desfases de subtitulos y
        audio. Devuelve False (sin hacer nada) si no hay nada
        reproduciendose/en pausa -- en ese caso la proxima load() ya recrea
        el Instance por su cuenta.

        Verificado contra libVLC 3.0.23: la posicion, la pista de audio, la
        de subtitulos y los subtitulos externos se pueden fijar como
        opciones del Media antes de play(); los desfases no (se resetean a 0
        con cada Media nuevo), asi que esos -- y deshabilitar pistas (id
        -1), que no tiene opcion equivalente -- se reaplican en
        apply_pending_restore() una vez que el nuevo input esta en Playing."""
        state = self.playback_state()
        if self._current_path is None or state not in (PlaybackState.PLAYING, PlaybackState.PAUSED):
            return False
        snapshot = {
            "time_ms": self.get_time_ms() if self.is_seekable() else 0,
            "paused": state == PlaybackState.PAUSED,
            "audio_track": self.get_current_audio_track(),
            "subtitle_track": self.get_current_subtitle_track(),
            "subtitle_delay_ms": self.get_subtitle_delay_ms(),
            "audio_delay_ms": self.get_audio_delay_ms(),
        }
        external_subtitles = list(self._external_subtitles)
        path = self._current_path

        self._create_instance(visualizer=self._visualizer_on if visualizer is None else visualizer)
        media = self._new_media(path)
        if snapshot["time_ms"] > 0:
            media.add_option(f":start-time={snapshot['time_ms'] / 1000:.3f}")
        if snapshot["audio_track"] >= 0:
            media.add_option(f":audio-track-id={snapshot['audio_track']}")
        if snapshot["subtitle_track"] >= 0:
            media.add_option(f":sub-track-id={snapshot['subtitle_track']}")
        for sub in external_subtitles:
            media.slaves_add(vlc.MediaSlaveType.subtitle, 4, pathlib.Path(sub).absolute().as_uri())
        self._set_media(media)
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
        state = self.playback_state()
        if state in (PlaybackState.ENDED, PlaybackState.ERROR, PlaybackState.STOPPED):
            self._pending_restore = None
            return False
        if state != PlaybackState.PLAYING:
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
        if snapshot.get("audio_delay_ms"):
            self.set_audio_delay_ms(snapshot["audio_delay_ms"])
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
        return self.playback_state() in IDLE_STATES

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
        return self.playback_state() == PlaybackState.PAUSED

    def get_state(self):
        """vlc.State crudo (lo usan las pruebas contra libVLC); la UI usa
        playback_state()."""
        return self.media_player.get_state()

    def playback_state(self) -> PlaybackState:
        return _STATE_MAP.get(self.media_player.get_state(), PlaybackState.IDLE)

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

    def is_seekable(self) -> bool:
        return bool(self.media_player.is_seekable())

    def is_live_stream(self) -> bool:
        """Un stream en vivo (radio, camara, TV): se esta reproduciendo pero
        no tiene largo ni se puede buscar."""
        return (
            self._current_path is not None
            and is_url(self._current_path)
            and self.playback_state() == PlaybackState.PLAYING
            and self.get_length_ms() <= 0
        )

    # -- audio -----------------------------------------------------------
    def get_volume(self) -> int:
        return self.media_player.audio_get_volume()

    def set_volume(self, vol: int):
        # Un solo tope para la UI y el backend (antes 150 vs 200).
        self._volume = max(0, min(MAX_VOLUME, int(vol)))
        self.media_player.audio_set_volume(self._volume)

    def is_muted(self) -> bool:
        # El estado propio, no audio_get_mute(): sin audio abierto (p. ej.
        # tras stop()) libVLC devuelve -1, que bool() tomaba como "silenciado"
        # y hacia que el boton de silencio no hiciera nada.
        return self._muted

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

    # -- salida de audio -----------------------------------------------------
    def audio_output_devices(self) -> list:
        """[(id, descripcion)] de la salida de audio actual (el primero suele
        ser "" = predeterminado del sistema)."""
        devices = []
        head = self.media_player.audio_output_device_enum()
        node = head
        try:
            while node:
                devices.append((_decode(node.contents.device), _decode(node.contents.description)))
                node = node.contents.next
        finally:
            if head:
                vlc.libvlc_audio_output_device_list_release(head)
        return devices

    def set_audio_device(self, device_id: str):
        self._audio_device = device_id or ""
        self.media_player.audio_output_device_set(None, self._audio_device)

    def get_audio_device(self) -> str:
        return self._audio_device

    def volume_normalization_supported(self) -> bool:
        return vlc_internals.audio_filters_supported()

    def _apply_audio_filters(self) -> bool:
        chain = ":".join(
            (["equalizer"] if self._equalizer is not None else []) + (["normvol"] if self._normalize else [])
        )
        return vlc_internals.set_audio_filters(self.media_player, chain)

    def set_volume_normalization(self, enabled: bool) -> bool:
        """Normalizador de volumen de VLC (normvol: baja los pasajes que
        superan el nivel maximo), en vivo. False si esta version de libVLC no
        lo permite (ver vlc_internals)."""
        if not self.volume_normalization_supported():
            self._normalize = False
            return False
        was, self._normalize = self._normalize, bool(enabled)
        if self._normalize or was:
            return self._apply_audio_filters()
        return True

    def is_volume_normalized(self) -> bool:
        return self._normalize

    # -- informacion del medio ------------------------------------------------
    def media_details(self, timeout_s: float = 3.0):
        """Datos del archivo/stream actual para el dialogo de informacion:
        {"path", "duration_ms", "meta": {...}, "tracks": [...]} (ver
        vlc_internals.media_tracks), o None si no hay nada cargado. Si el
        Media todavia no se analizo, lo analiza (con tope de tiempo)."""
        media = self._media
        if media is None or self._current_path is None:
            return None
        tracks = vlc_internals.media_tracks(media)
        if not tracks and media.get_parsed_status() != vlc.MediaParsedStatus.done:
            flags = vlc.MediaParseFlag.network if is_url(self._current_path) else vlc.MediaParseFlag.local
            media.parse_with_options(flags, int(timeout_s * 1000))
            deadline = time.monotonic() + timeout_s
            while media.get_parsed_status() == 0 and time.monotonic() < deadline:
                time.sleep(0.05)
            tracks = vlc_internals.media_tracks(media)
        meta = {}
        for key, field in (
            ("title", vlc.Meta.Title), ("artist", vlc.Meta.Artist), ("album", vlc.Meta.Album),
            ("date", vlc.Meta.Date), ("genre", vlc.Meta.Genre), ("track_number", vlc.Meta.TrackNumber),
            ("description", vlc.Meta.Description), ("copyright", vlc.Meta.Copyright),
            ("encoded_by", vlc.Meta.EncodedBy), ("now_playing", vlc.Meta.NowPlaying),
        ):
            value = _decode(media.get_meta(field)).strip()
            if value:
                meta[key] = value
        return {
            "path": self._current_path,
            "duration_ms": max(int(media.get_duration()), 0),
            "meta": meta,
            "tracks": tracks,
        }

    def get_audio_delay_ms(self) -> int:
        return self.media_player.audio_get_delay() // 1000

    def set_audio_delay_ms(self, delay_ms: int) -> bool:
        """Desfase de audio (sincronia A/V), en ms; positivo = el audio se
        oye mas tarde. Como el de subtitulos, libVLC lo vuelve a 0 con cada
        Media nuevo."""
        self._audio_delay_ms = int(delay_ms)
        return self.media_player.audio_set_delay(int(delay_ms) * 1000) == 0

    def has_video_track(self) -> bool:
        return self.media_player.video_get_track_count() > 0

    def is_audio_only_stream(self) -> bool:
        """Para URLs, el tipo no se sabe por la extension: True cuando el
        input ya abierto tiene audio y ninguna pista de video."""
        return (
            self._current_path is not None
            and is_url(self._current_path)
            and self.media_player.audio_get_track_count() > 0
            and self.media_player.video_get_track_count() <= 0
        )

    def enable_stream_visualizer(self) -> bool:
        """Activa el visualizador para un stream de solo audio ya abierto
        (recrea el Instance y reconecta, conservando el estado)."""
        if self._visualizer_on or not self.is_audio_only_stream():
            return False
        return self.reload_preserving_state(visualizer=True)

    def visualizer_active(self) -> bool:
        return self._visualizer_on

    def now_playing(self) -> str:
        """Titulo que anuncia una radio por internet (ICY "StreamTitle"), o
        "" si no hay."""
        if self._media is None:
            return ""
        return _decode(self._media.get_meta(vlc.Meta.NowPlaying)).strip()

    def media_title(self) -> str:
        if self._media is None:
            return ""
        return _decode(self._media.get_meta(vlc.Meta.Title)).strip()

    # -- capitulos -------------------------------------------------------
    def chapters(self) -> list:
        """[(inicio_ms, duracion_ms, nombre)] del titulo actual (MKV/MP4 con
        capitulos), o [] si no tiene."""
        try:
            descriptions = list(self.media_player.get_full_chapter_descriptions(-1) or [])
        except Exception:  # noqa: BLE001 -- sin input abierto python-vlc puede fallar
            return []
        return [
            (int(c.time_offset), int(c.duration), _decode(c.name).strip())
            for c in descriptions
        ]

    def get_chapter(self) -> int:
        return self.media_player.get_chapter()

    def set_chapter(self, index: int):
        self.media_player.set_chapter(int(index))

    def next_chapter(self):
        self.media_player.next_chapter()

    def previous_chapter(self):
        self.media_player.previous_chapter()

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

    def add_subtitle_before_play(self, path: str):
        """Agrega un subtitulo externo al Media recien cargado, antes de
        play() (p. ej. uno descargado mientras sonaba otro archivo)."""
        if self._media is None:
            return
        self._media.slaves_add(vlc.MediaSlaveType.subtitle, 4, pathlib.Path(path).absolute().as_uri())
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
        # (ver _needs_new_instance).
        self._subtitle_scale = scale

    # -- mejora por GPU ------------------------------------------------------
    def set_gpu_options(self, upscale: bool, hdr: bool, hw_decoding: str = "any"):
        """Igual que el tamano de subtitulos: solo cambia el objetivo; se
        aplica en la proxima load() o con reload_preserving_state()."""
        self._gpu_upscale = bool(upscale)
        self._gpu_hdr = bool(hdr)
        self._hw_decoding = hw_decoding if hw_decoding in HW_DECODING_MODES else "any"

    def gpu_options(self):
        return self._gpu_upscale, self._gpu_hdr, self._hw_decoding

    # -- passthrough de audio (3.16) -------------------------------------------
    def set_audio_passthrough(self, mode: str):
        """Como las opciones de GPU: se aplica en la proxima load() o con
        reload_preserving_state()."""
        self._passthrough = mode if mode in ("off", "ac3_dts", "all") else "off"

    def get_audio_passthrough(self) -> str:
        return self._passthrough

    # -- video -------------------------------------------------------------
    def set_video_scale(self, factor: float):
        self._video_scale = factor
        self.media_player.video_set_scale(factor)

    def get_video_scale(self) -> float:
        return self._video_scale

    def _apply_video_state(self):
        """Aspecto, recorte, desentrelazado y ajustes de imagen en un
        MediaPlayer recien creado."""
        self._deinterlace_applied = False
        if self._aspect_ratio:
            self.media_player.video_set_aspect_ratio(self._aspect_ratio)
        if self._crop:
            self.media_player.video_set_crop_geometry(self._crop)
        if self._deinterlace != "auto":
            self._set_deinterlace_now(self._deinterlace)
        if self._video_adjust.enabled:
            self._apply_video_adjust()

    def set_aspect_ratio(self, ratio: str):
        """"16:9", "4:3"... o "" para el del video."""
        self._aspect_ratio = ratio or ""
        self.media_player.video_set_aspect_ratio(self._aspect_ratio or None)

    def get_aspect_ratio(self) -> str:
        return self._aspect_ratio

    def set_crop(self, ratio: str):
        """Recorta el video a esa relacion ("16:9", "2.35:1"...); "" = sin recorte."""
        self._crop = ratio or ""
        self.media_player.video_set_crop_geometry(self._crop or None)

    def get_crop(self) -> str:
        return self._crop

    def _set_deinterlace_now(self, mode: str):
        # libVLC 3: NULL/"" lo desactiva; un nombre de modo lo activa con ese modo.
        self.media_player.video_set_deinterlace(None if mode == "off" else mode)
        self._deinterlace_applied = True

    def set_deinterlace(self, mode: str) -> bool:
        """Modo de desentrelazado (ver settings.DEINTERLACE_MODES). Devuelve
        True si hay que recrear el reproductor para aplicarlo: volver a
        "auto" despues de haber fijado otro modo (libVLC 3 no tiene API para
        pedir de nuevo el automatico)."""
        mode = mode if mode in DEINTERLACE_MODES else "auto"
        self._deinterlace = mode
        if mode == "auto":
            return self._deinterlace_applied
        self._set_deinterlace_now(mode)
        return False

    def get_deinterlace(self) -> str:
        return self._deinterlace

    def _apply_video_adjust(self):
        adj = self._video_adjust
        mp = self.media_player
        options = vlc.VideoAdjustOption
        mp.video_set_adjust_float(options.Brightness, adj.brightness)
        mp.video_set_adjust_float(options.Contrast, adj.contrast)
        mp.video_set_adjust_float(options.Saturation, adj.saturation)
        mp.video_set_adjust_float(options.Hue, adj.hue)
        mp.video_set_adjust_float(options.Gamma, adj.gamma)
        mp.video_set_adjust_int(options.Enable, 1 if adj.enabled else 0)

    def set_video_adjust(self, adjust: VideoAdjustSettings):
        """Brillo, contraste, saturacion, tono y gamma (filtro "adjust" de
        libVLC, en vivo)."""
        self._video_adjust = adjust
        self._apply_video_adjust()

    def get_video_adjust(self) -> VideoAdjustSettings:
        return self._video_adjust

    def take_snapshot(self, path: str, width: int = 0, height: int = 0) -> bool:
        """True si libVLC acepto la captura (sin salida de video devuelve
        -1). El archivo se escribe poco despues, en el hilo de video; el
        evento snapshotTaken avisa cuando quedo en disco."""
        return self.media_player.video_take_snapshot(0, path, width, height) == 0

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
    # reproduccion real es un segundo vlc.MediaPlayer (en su propia Instance
    # liviana) que se busca y capta por separado; el media_player principal
    # nunca se toca.
    def _ensure_preview_player(self):
        if self._preview_player is None:
            if self._preview_instance is None:
                self._preview_instance, _dropped = create_instance_with_fallback(PREVIEW_VLC_ARGS, [])
            self._preview_player = self._preview_instance.media_player_new()
            self._preview_player.audio_set_mute(True)
            disable_vlc_input(self._preview_player)
            if self._preview_widget is not None:
                _attach_window(self._preview_player, self._preview_widget)
        return self._preview_player

    def attach_preview_output(self, widget):
        """Recuerda el widget (que nunca se muestra en pantalla) donde el
        reproductor de vista previa crea su salida de video; el reproductor
        en si se crea recien con el primer hover (_ensure_preview_player)."""
        self._preview_widget = widget
        if self._preview_player is not None:
            _attach_window(self._preview_player, widget)

    def preview_current_path(self):
        return self._preview_path

    @staticmethod
    def preview_supported(path_or_url) -> bool:
        """Sin miniatura para audio (no hay fotogramas: el reproductor de
        vista previa decodificaba sin fin sin poder capturar nada) ni para
        URLs (seria una segunda conexion/descarga del mismo stream)."""
        return bool(path_or_url) and not is_url(path_or_url) and not is_audio_file(path_or_url)

    def load_preview_media(self, path_or_url: str) -> bool:
        """Carga (sin que el usuario la vea ni la oiga) el archivo actual en
        el reproductor de vista previa. No hace falta recargar si ya es el
        mismo archivo (ver preview_current_path). Devuelve False sin hacer
        nada para audio y URLs (ver preview_supported).

        Deliberadamente NO se pausa aqui. Se probo contra libVLC real:
        llamar set_pause(1) inmediatamente despues de play(), antes de que
        el primer fotograma llegue a la salida de video, deja el vout
        "vacio" para siempre -- has_vout() e incluso
        video_take_snapshot() siguen devolviendo exito, pero nunca se
        escribe ningun archivo, en ningun intento posterior. Se deja
        reproduciendo (sin audio) hasta que take_preview_snapshot()
        confirma que ya salio un fotograma real, momento en el que recien
        es seguro pausarlo (ver ahi)."""
        if not self.preview_supported(path_or_url):
            return False
        player = self._ensure_preview_player()
        media = self._preview_instance.media_new_path(os.path.normpath(path_or_url))
        for option in PREVIEW_MEDIA_OPTIONS:
            media.add_option(option)
        player.set_media(media)
        media.release()  # set_media retiene su propia referencia
        player.play()
        self._preview_path = path_or_url
        self._preview_warmed_up = False
        return True

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

    def has_preview_player(self) -> bool:
        return self._preview_player is not None

    def release_preview_player(self):
        """Libera el reproductor de vista previa y su Instance (la UI lo
        llama tras un rato sin hovers y al cerrar): no retiene abierto el
        archivo ni un segundo decodificador -- en un 4K HEVC, otro pool de
        superficies de la GPU."""
        if self._preview_player is not None:
            self._preview_player.stop()
            self._preview_player.release()
            self._preview_player = None
        if self._preview_instance is not None:
            self._preview_instance.release()
            self._preview_instance = None
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

    def _replace_equalizer(self, eq):
        """Aplica `eq` (o None = desactivado) y libera el anterior.
        libvlc_media_player_set_equalizer copia los valores, asi que el
        objeto viejo se puede liberar apenas se reemplaza (python-vlc no lo
        libera solo al recolectarlo)."""
        old, self._equalizer = self._equalizer, eq
        self.media_player.set_equalizer(eq)
        self._keep_normalizer()
        if old is not None and old is not eq:
            old.release()

    def apply_equalizer_preset(self, index: int) -> bool:
        # OJO: vlc.AudioEqualizer(index) NO crea un preset: python-vlc toma
        # el entero como un puntero C crudo, y cualquier uso posterior
        # (set_equalizer, get_preamp, set_amp_at_index, recrear el Instance)
        # termina en "access violation". La funcion correcta es
        # libvlc_audio_equalizer_new_from_preset, que devuelve None si el
        # indice no existe.
        eq = vlc.libvlc_audio_equalizer_new_from_preset(int(index))
        if eq is None:
            log.warning("Preset de ecualizador inexistente: %s", index)
            return False
        self._replace_equalizer(eq)
        return True

    def get_equalizer_values(self):
        """(preamp, [bandas]) del ecualizador activo, o None si esta
        desactivado."""
        if self._equalizer is None:
            return None
        count = vlc.libvlc_audio_equalizer_get_band_count()
        return (
            float(self._equalizer.get_preamp()),
            [float(self._equalizer.get_amp_at_index(i)) for i in range(count)],
        )

    def set_equalizer_values(self, preamp: float, bands):
        """Activa el ecualizador con estos valores exactos (en dB), p. ej. al
        restaurar los ajustes guardados."""
        eq = vlc.AudioEqualizer()
        eq.set_preamp(float(preamp))
        for i, amp in enumerate(bands):
            eq.set_amp_at_index(float(amp), i)
        self._replace_equalizer(eq)

    def set_equalizer_preamp(self, amp: float):
        if self._equalizer is None:
            self._equalizer = vlc.AudioEqualizer()
        self._equalizer.set_preamp(amp)
        self.media_player.set_equalizer(self._equalizer)
        self._keep_normalizer()

    def set_equalizer_band(self, index: int, amp: float):
        if self._equalizer is None:
            self._equalizer = vlc.AudioEqualizer()
        self._equalizer.set_amp_at_index(amp, index)
        self.media_player.set_equalizer(self._equalizer)
        self._keep_normalizer()

    def disable_equalizer(self):
        self._replace_equalizer(None)

    def _keep_normalizer(self):
        # set_equalizer deja la cadena de filtros en "equalizer" (o vacia):
        # volver a agregar el normalizador.
        if self._normalize:
            self._apply_audio_filters()


class MediaInfoProbe:
    """Lee duracion y etiquetas (artista/titulo) de archivos locales SIN
    reproducirlos, con libvlc_media_parse_with_options (asincrono, en hilos
    de libVLC). Usa su propia Instance minima: no depende de que el
    principal se recree. `on_parsed(path, duration_ms, title, artist)` se
    llama en el hilo de la UI (el evento de libVLC se encola con una senal)."""

    PARSE_TIMEOUT_MS = 5000

    class _Signals(QObject):
        parsed = Signal(int)

    def __init__(self, on_parsed):
        self._on_parsed = on_parsed
        self._instance = None
        self._pending = {}  # id -> (path, media, event_manager)
        self._next_id = 0
        self._signals = self._Signals()
        self._signals.parsed.connect(self._finish)

    def _ensure_instance(self):
        if self._instance is None:
            self._instance, _ = create_instance_with_fallback(["--quiet", "--no-video", "--no-audio"], [])
        return self._instance

    def pending_count(self) -> int:
        return len(self._pending)

    def probe(self, path: str) -> bool:
        if is_url(path):
            return False
        instance = self._ensure_instance()
        media = instance.media_new_path(os.path.normpath(path))
        job = self._next_id
        self._next_id += 1
        em = media.event_manager()
        em.event_attach(vlc.EventType.MediaParsedChanged, lambda _e, j=job: self._signals.parsed.emit(j))
        self._pending[job] = (path, media, em)
        if media.parse_with_options(vlc.MediaParseFlag.local, self.PARSE_TIMEOUT_MS) != 0:
            if self._pending.pop(job, None) is not None:
                em.event_detach(vlc.EventType.MediaParsedChanged)
                media.release()
            return False
        return True

    def _finish(self, job: int):
        entry = self._pending.pop(job, None)
        if entry is None:
            return
        path, media, em = entry
        em.event_detach(vlc.EventType.MediaParsedChanged)
        duration = 0
        title = artist = ""
        try:
            if media.get_parsed_status() == vlc.MediaParsedStatus.done:
                duration = max(int(media.get_duration()), 0)
                title = _decode(media.get_meta(vlc.Meta.Title)).strip()
                artist = _decode(media.get_meta(vlc.Meta.Artist)).strip()
        finally:
            media.release()
        self._on_parsed(path, duration, title, artist)

    def close(self):
        for _path, media, em in self._pending.values():
            em.event_detach(vlc.EventType.MediaParsedChanged)
            media.parse_stop()
            media.release()
        self._pending = {}
        if self._instance is not None:
            self._instance.release()
            self._instance = None
