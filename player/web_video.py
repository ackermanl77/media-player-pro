"""Videos de paginas web (YouTube, Vimeo, Twitch...) con yt-dlp (3.15).

libVLC 3 abre streams directos (http de un archivo, HLS, DASH, RTSP...), pero no
la pagina de un video: sus scripts Lua para YouTube se rompen cada vez que el
sitio cambia. yt-dlp se mantiene al dia con esos cambios, asi que, si esta
instalado (el modulo `yt_dlp` en este Python o `yt-dlp.exe` en el PATH; no se
incluye con el programa), una URL de un sitio conocido se resuelve a sus streams
antes de reproducirla.

Las URL de los streams caducan (horas), asi que la lista guarda la de la pagina y
se resuelve cada vez que se reproduce. YouTube da 1080p solo como video y audio
separados: el audio va a libVLC como :input-slave del mismo Media.

Solo se mandan a yt-dlp los sitios de KNOWN_SITES: una URL http sin extension
tambien puede ser una radio por Internet, que debe seguir yendo directo a libVLC.
"""

import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

# Video de hasta 1080p con su mejor audio (o un archivo con los dos).
FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/b"
RESOLVE_TIMEOUT_S = 60
KNOWN_SITES = (
    "youtube.com", "youtu.be", "youtube-nocookie.com", "vimeo.com", "twitch.tv", "dailymotion.com",
    "archive.org", "soundcloud.com", "bandcamp.com", "tiktok.com", "instagram.com", "facebook.com",
    "x.com", "twitter.com", "reddit.com", "rumble.com", "odysee.com", "bilibili.com", "nicovideo.jp",
    "ted.com", "kick.com", "streamable.com",
)


@dataclass(frozen=True)
class WebStream:
    page_url: str
    video_url: str
    audio_url: Optional[str] = None
    title: str = ""
    headers: dict = field(default_factory=dict)


class WebVideoError(RuntimeError):
    pass


def is_page_url(url: str) -> bool:
    """True para la pagina de un video en un sitio conocido (no un stream directo)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == site or host.endswith("." + site) for site in KNOWN_SITES)


def _module_available() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def _executable() -> Optional[str]:
    return shutil.which("yt-dlp")


def available() -> bool:
    return _module_available() or _executable() is not None


def _from_info(page_url: str, info: dict) -> WebStream:
    if info.get("_type") == "playlist" and info.get("entries"):
        info = next(entry for entry in info["entries"] if entry)
    requested = info.get("requested_formats") or []
    if len(requested) >= 2:
        video, audio = requested[0], requested[1]
        if video.get("vcodec") == "none" and audio.get("vcodec") != "none":
            video, audio = audio, video
        video_url, audio_url, headers = video.get("url"), audio.get("url"), video.get("http_headers") or {}
    else:
        chosen = requested[0] if requested else info
        video_url, audio_url, headers = chosen.get("url"), None, chosen.get("http_headers") or info.get("http_headers") or {}
    if not video_url:
        raise WebVideoError("yt-dlp no devolvió ningún stream reproducible")
    return WebStream(page_url, video_url, audio_url, str(info.get("title") or ""), dict(headers))


def resolve(page_url: str) -> WebStream:
    """Los streams de la pagina `page_url` (bloquea: llamar desde un hilo). Lanza
    WebVideoError con un mensaje para el usuario."""
    if _module_available():
        import yt_dlp

        options = {"quiet": True, "no_warnings": True, "noplaylist": True, "format": FORMAT,
                   "socket_timeout": 20, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(page_url, download=False)
        except Exception as error:  # noqa: BLE001 - los errores de yt-dlp son muchos
            raise WebVideoError(f"yt-dlp no pudo abrir la página: {error}") from error
        return _from_info(page_url, ydl.sanitize_info(info))
    executable = _executable()
    if executable is None:
        raise WebVideoError("yt-dlp no está instalado")
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            [executable, "-J", "--no-playlist", "--no-warnings", "-f", FORMAT, page_url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=RESOLVE_TIMEOUT_S, creationflags=creation,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WebVideoError(f"yt-dlp no respondió: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()[-1:] or ["error desconocido"]
        raise WebVideoError(f"yt-dlp no pudo abrir la página: {detail[0]}")
    try:
        info = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise WebVideoError("yt-dlp devolvió una respuesta que no se entiende") from error
    return _from_info(page_url, info)


class ResolveWorker:
    """Resuelve una pagina en un hilo y avisa al hilo de Qt (ver MainWindow._resolve_web_video)."""

    def __init__(self, page_url: str, on_done, on_failed):
        from PySide6.QtCore import QObject, QThread, Signal

        class _Bridge(QObject):
            done = Signal(object)
            failed = Signal(str)

        class _Thread(QThread):
            # QThread.run is a C++ virtual: it has to be overridden in a subclass (assigning
            # `thread.run = f` on an instance is never called).
            def __init__(self, body):
                super().__init__()
                self._body = body

            def run(self):
                self._body()

        self.page_url = page_url
        self._bridge = _Bridge()  # lives in the caller's (Qt) thread: signals are queued to it
        self._bridge.done.connect(on_done)
        self._bridge.failed.connect(on_failed)
        self._thread = _Thread(self._run)

    def _run(self) -> None:
        try:
            stream = resolve(self.page_url)
        except WebVideoError as error:
            self._bridge.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001
            self._bridge.failed.emit(f"yt-dlp falló: {error}")
        else:
            self._bridge.done.emit(stream)

    def start(self) -> None:
        self._thread.start()

    def wait(self, ms: int = 5000) -> bool:
        return self._thread.wait(ms)


def media_options(stream: WebStream) -> list:
    """Opciones de libVLC para el Media de `stream`: el audio separado y las
    cabeceras que pide el sitio."""
    options = []
    if stream.audio_url:
        options.append(f":input-slave={stream.audio_url}")
    agent = stream.headers.get("User-Agent")
    if agent:
        options.append(f":http-user-agent={agent}")
    referer = stream.headers.get("Referer")
    if referer:
        options.append(f":http-referrer={referer}")
    return options
