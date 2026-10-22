"""Archivo > Convertir / extraer audio (3.19) y Reproduccion > Grabar (3.19).

Convertir usa el modulo stream_out_transcode de libVLC en un Instance aparte,
sin video ni audio en pantalla: un archivo local se recodifica mas rapido que
en tiempo real (verificado con libVLC 3.0.23: un clip de 6 s en < 1 s). El
progreso es la posicion del reproductor de esa conversion, leida con un QTimer.

Grabar duplica lo que se esta reproduciendo (un stream en vivo o un archivo)
hacia un .ts sin recodificar (#duplicate{dst=display,dst=std{...}}): se ve y
se graba a la vez. Lo arma VLCPlayer.set_recording() en la proxima carga.
"""

import logging
import os
import time
from dataclasses import dataclass

import vlc
from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConvertProfile:
    key: str
    label: str
    extension: str
    transcode: str  # el contenido de #transcode{...}
    mux: str


PROFILES = [
    ConvertProfile("mp4_h264", "Video MP4 (H.264 + AAC)", ".mp4",
                   "vcodec=h264,venc=x264{preset=veryfast,crf=21},vb=0,acodec=mp4a,ab=160,channels=2,soverlay", "mp4"),
    ConvertProfile("mkv_h265", "Video MKV (H.265 + AAC, más pequeño)", ".mkv",
                   "vcodec=hevc,venc=x265{preset=fast,crf=26},vb=0,acodec=mp4a,ab=160,channels=2", "mkv"),
    ConvertProfile("mp3", "Solo audio MP3 (192 kbps)", ".mp3",
                   "vcodec=none,acodec=mp3,ab=192,channels=2,samplerate=44100", "raw"),
    ConvertProfile("ogg", "Solo audio Ogg Vorbis", ".ogg", "vcodec=none,acodec=vorb,ab=160,channels=2", "ogg"),
    ConvertProfile("flac", "Solo audio FLAC (sin pérdida)", ".flac", "vcodec=none,acodec=flac,channels=2", "raw"),
]
PROFILES_BY_KEY = {profile.key: profile for profile in PROFILES}


def _sout_path(path: str) -> str:
    # Dentro de dst='...' libVLC acepta "/" en Windows; una comilla simple se duplica.
    return path.replace("\\", "/").replace("'", "''")


def transcode_sout(profile: ConvertProfile, output_path: str) -> str:
    return f"#transcode{{{profile.transcode}}}:std{{access=file,mux={profile.mux},dst='{_sout_path(output_path)}'}}"


def record_sout(output_path: str) -> str:
    """Ver y grabar a la vez, sin recodificar (MPEG-TS admite casi cualquier codec)."""
    return f"#duplicate{{dst=display,dst=std{{access=file,mux=ts,dst='{_sout_path(output_path)}'}}}}"


def default_output_path(source: str, profile: ConvertProfile, folder: str = "") -> str:
    """<carpeta>/<nombre>.<ext> sin pisar nada: agrega " (2)", " (3)"..."""
    base = os.path.splitext(os.path.basename(source.rstrip("/\\")) or "convertido")[0]
    folder = folder or os.path.dirname(source) or os.getcwd()
    candidate = os.path.join(folder, base + profile.extension)
    counter = 2
    while os.path.exists(candidate) or os.path.normcase(os.path.abspath(candidate)) == os.path.normcase(os.path.abspath(source)):
        candidate = os.path.join(folder, f"{base} ({counter}){profile.extension}")
        counter += 1
    return candidate


def recording_path(folder: str, title: str, now=None) -> str:
    stamp = time.strftime("%Y-%m-%d %H-%M-%S", time.localtime(now))
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in (title or "grabacion")).strip()[:60] or "grabacion"
    return os.path.join(folder, f"{safe} {stamp}.ts")


class ConvertJob(QObject):
    """Una conversion en curso. `progress(0..1)` y `finished(ok, mensaje)`."""

    progress = Signal(float)
    finished = Signal(bool, str)

    POLL_MS = 250

    def __init__(self, source: str, output_path: str, profile: ConvertProfile, parent=None, instance_factory=None,
                 media_options=()):
        super().__init__(parent)
        self.source = source
        self.output_path = output_path
        self.profile = profile
        self._factory = instance_factory or (
            lambda: vlc.Instance(["--quiet", "--no-video-title-show", "--aout=adummy", "--vout=dummy"]))
        self._media_options = list(media_options)
        self._instance = None
        self._player = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self.running = False

    def start(self) -> bool:
        from .formats import is_url

        self._instance = self._factory()
        if self._instance is None:
            self.finished.emit(False, "libVLC no pudo iniciarse")
            return False
        if is_url(self.source):
            media = self._instance.media_new(self.source)
        else:
            media = self._instance.media_new_path(os.path.normpath(self.source))
        for option in self._media_options:
            media.add_option(option)
        media.add_option(":sout=" + transcode_sout(self.profile, self.output_path))
        media.add_option(":no-sout-all")  # solo la primera pista de audio y de video
        media.add_option(":sout-keep")
        self._player = self._instance.media_player_new()
        self._player.set_media(media)
        if self._player.play() != 0:
            self._finish(False, "libVLC no pudo empezar la conversión")
            return False
        self.running = True
        self._timer.start()
        log.info("Convirtiendo %s -> %s (%s)", self.source, self.output_path, self.profile.key)
        return True

    def cancel(self):
        if self.running:
            self._finish(False, "Conversión cancelada", remove_output=True)

    def _poll(self):
        state = self._player.get_state() if self._player is not None else vlc.State.Error
        if state == vlc.State.Ended:
            ok = os.path.exists(self.output_path) and os.path.getsize(self.output_path) > 0
            self._finish(ok, self.output_path if ok else "La conversión no produjo ningún archivo")
        elif state == vlc.State.Error:
            self._finish(False, "libVLC no pudo convertir este archivo con ese formato", remove_output=True)
        else:
            self.progress.emit(max(0.0, min(1.0, self._player.get_position() or 0.0)))

    def _finish(self, ok: bool, message: str, remove_output: bool = False):
        self._timer.stop()
        self.running = False
        if self._player is not None:
            self._player.stop()
            self._player.release()
            self._player = None
        if self._instance is not None:
            self._instance.release()
            self._instance = None
        if remove_output and os.path.exists(self.output_path):
            try:
                os.remove(self.output_path)
            except OSError:
                pass
        if ok:
            self.progress.emit(1.0)
        log.info("Conversion %s: %s", "terminada" if ok else "fallida", message)
        self.finished.emit(ok, message)
