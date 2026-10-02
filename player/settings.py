"""Ajustes del usuario y sesion (playlist) que sobreviven entre ejecuciones.
Modulo puro, sin VLC ni Qt: mismo patron que config.py/resume.py sobre
jsonstore (escritura atomica + .bak). MainWindow es quien lee sus widgets y
llama a save_settings()/save_session(); aqui solo se valida y normaliza.

Dos archivos separados en ~/.reproductor_multimedia_pro/:
- settings.json: preferencias (volumen, EQ, velocidad, geometria...). Se
  escribe al cerrar la ventana.
- session.json: la playlist y su elemento actual. Se escribe con debounce
  cada vez que cambia la lista (asi un cierre abrupto no la pierde) y al
  cerrar -- separado para no reescribir las preferencias en cada cambio.

Cada campo leido se valida por separado: un valor invalido o de otro tipo
vuelve a su default sin descartar el resto del archivo.

Deliberadamente NO se guarda "Al terminar la lista" (apagar/hibernar/
reiniciar): una accion asi tiene que elegirse a conciencia en cada sesion.
"""

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .jsonstore import load_json, save_json

MAX_VOLUME = 150
REPEAT_MODES = ("none", "all", "one")
# Velocidades del menu; con [ y ] se puede elegir cualquier valor entre
# MIN_RATE y MAX_RATE en pasos de RATE_STEP.
SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0)
MIN_RATE = 0.25
MAX_RATE = 4.0
RATE_STEP = 0.1
THEMES = ("system", "dark", "light")
HW_DECODING_MODES = ("any", "d3d11va", "dxva2", "none")
MIN_NETWORK_CACHING_MS = 0
MAX_NETWORK_CACHING_MS = 60_000
SUBTITLE_SCALES = (75, 100, 150, 200)
VIDEO_SCALES = (0.0, 0.5, 1.0, 1.5, 2.0)
EQ_BAND_COUNT = 10
EQ_MIN_DB = -20.0
EQ_MAX_DB = 20.0
# Tope de entradas de la sesion: evita que un session.json gigante (o
# manipulado) congele el arranque.
MAX_SESSION_ENTRIES = 20_000


def _state_dir() -> Path:
    return Path.home() / ".reproductor_multimedia_pro"


def settings_file() -> Path:
    return _state_dir() / "settings.json"


def session_file() -> Path:
    return _state_dir() / "session.json"


@dataclass
class EqualizerSettings:
    enabled: bool = False
    preset: int = -1  # -1 = "Personalizado"
    preamp: float = 0.0
    bands: list = field(default_factory=lambda: [0.0] * EQ_BAND_COUNT)


@dataclass
class Settings:
    volume: int = 80
    muted: bool = False
    rate: float = 1.0
    repeat_mode: str = "none"
    shuffle: bool = False
    visualizer: bool = True
    subtitle_scale: int = 100
    video_scale: float = 0.0
    always_on_top: bool = False
    restore_session: bool = True
    equalizer: EqualizerSettings = field(default_factory=EqualizerSettings)
    geometry: str = ""       # QMainWindow.saveGeometry() en base64
    window_state: str = ""   # QMainWindow.saveState() en base64 (dock)
    last_open_dir: str = ""
    show_remaining_time: bool = False
    theme: str = "system"
    # Mejora por GPU (ver backend.gpu_instance_args).
    gpu_upscale: bool = False
    gpu_hdr: bool = False
    hw_decoding: str = "any"
    # Streams de red (dialogo "Abrir URL").
    network_caching_ms: int = 1000
    rtsp_tcp: bool = False
    # Una sola ventana: abrir un archivo con el programa ya abierto lo manda
    # a esa ventana (ver single_instance.py).
    allow_multiple_windows: bool = False


@dataclass
class Session:
    entries: list = field(default_factory=list)
    current_index: int = -1


# -- validacion ---------------------------------------------------------------
def _bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _number(value):
    """int/float finito (no bool), o None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _choice(value, choices, default):
    num = _number(value) if not isinstance(value, str) else None
    for c in choices:
        if isinstance(c, str):
            if value == c:
                return c
        elif num is not None and math.isclose(num, c):
            return c
    return default


def clamp_rate(value, default: float = 1.0) -> float:
    """Velocidad valida: dentro de [MIN_RATE, MAX_RATE], redondeada a
    centesimas (asi 1.0 + 0.1 + 0.1 da 1.2 y no 1.2000000000000002)."""
    num = _number(value)
    if num is None:
        return default
    return round(max(MIN_RATE, min(MAX_RATE, float(num))), 2)


def _db(value, default: float = 0.0) -> float:
    num = _number(value)
    if num is None:
        return default
    return float(max(EQ_MIN_DB, min(EQ_MAX_DB, num)))


def _str(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _equalizer_from_dict(raw) -> EqualizerSettings:
    eq = EqualizerSettings()
    if not isinstance(raw, dict):
        return eq
    eq.enabled = _bool(raw.get("enabled"), eq.enabled)
    preset = _number(raw.get("preset"))
    eq.preset = int(preset) if preset is not None and preset == int(preset) and preset >= -1 else -1
    eq.preamp = _db(raw.get("preamp"))
    bands = raw.get("bands")
    if isinstance(bands, list) and len(bands) == EQ_BAND_COUNT:
        eq.bands = [_db(b) for b in bands]
    return eq


def settings_from_dict(raw) -> Settings:
    s = Settings()
    if not isinstance(raw, dict):
        return s
    volume = _number(raw.get("volume"))
    if volume is not None:
        s.volume = int(max(0, min(MAX_VOLUME, round(volume))))
    s.muted = _bool(raw.get("muted"), s.muted)
    s.rate = clamp_rate(raw.get("rate"), s.rate)
    s.repeat_mode = _choice(raw.get("repeat_mode"), REPEAT_MODES, s.repeat_mode)
    s.shuffle = _bool(raw.get("shuffle"), s.shuffle)
    s.visualizer = _bool(raw.get("visualizer"), s.visualizer)
    s.subtitle_scale = _choice(raw.get("subtitle_scale"), SUBTITLE_SCALES, s.subtitle_scale)
    s.video_scale = _choice(raw.get("video_scale"), VIDEO_SCALES, s.video_scale)
    s.always_on_top = _bool(raw.get("always_on_top"), s.always_on_top)
    s.restore_session = _bool(raw.get("restore_session"), s.restore_session)
    s.equalizer = _equalizer_from_dict(raw.get("equalizer"))
    s.geometry = _str(raw.get("geometry"))
    s.window_state = _str(raw.get("window_state"))
    s.last_open_dir = _str(raw.get("last_open_dir"))
    s.show_remaining_time = _bool(raw.get("show_remaining_time"), s.show_remaining_time)
    s.theme = _choice(raw.get("theme"), THEMES, s.theme)
    s.gpu_upscale = _bool(raw.get("gpu_upscale"), s.gpu_upscale)
    s.gpu_hdr = _bool(raw.get("gpu_hdr"), s.gpu_hdr)
    s.hw_decoding = _choice(raw.get("hw_decoding"), HW_DECODING_MODES, s.hw_decoding)
    caching = _number(raw.get("network_caching_ms"))
    if caching is not None:
        s.network_caching_ms = int(max(MIN_NETWORK_CACHING_MS, min(MAX_NETWORK_CACHING_MS, round(caching))))
    s.rtsp_tcp = _bool(raw.get("rtsp_tcp"), s.rtsp_tcp)
    s.allow_multiple_windows = _bool(raw.get("allow_multiple_windows"), s.allow_multiple_windows)
    return s


def session_from_dict(raw) -> Session:
    session = Session()
    if not isinstance(raw, dict):
        return session
    entries = raw.get("entries")
    if isinstance(entries, list):
        session.entries = [e for e in entries if isinstance(e, str) and e][:MAX_SESSION_ENTRIES]
    index = _number(raw.get("current_index"))
    if index is not None and index == int(index) and 0 <= index < len(session.entries):
        session.current_index = int(index)
    return session


# -- lectura / escritura ------------------------------------------------------
def load_settings() -> Settings:
    return settings_from_dict(load_json(settings_file(), dict, {}))


def save_settings(settings: Settings) -> bool:
    # Pasar por settings_from_dict tambien al guardar: nunca se escribe algo
    # que la proxima lectura rechazaria.
    return save_json(settings_file(), asdict(settings_from_dict(asdict(settings))))


def load_session() -> Session:
    return session_from_dict(load_json(session_file(), dict, {}))


def save_session(session: Session) -> bool:
    return save_json(session_file(), asdict(session_from_dict(asdict(session))))


def clear_session() -> bool:
    return save_session(Session())
