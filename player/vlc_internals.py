"""Lo que python-vlc no expone bien de libVLC 3, por ctypes.

1. Pistas de un Media (libvlc_media_tracks_get): la estructura MediaTrack de
   python-vlc 3.0.21203 declara audio/video/subtitle como tres campos
   seguidos cuando en libVLC son una union, asi que bitrate/language/
   description se leen desplazados y el proceso se cae (verificado contra
   libVLC 3.0.23). Aqui se declara la estructura real.

2. Filtros de audio: libvlc_media_player_new crea la variable "audio-filter"
   del reproductor SIN heredar de la Instance, asi que --audio-filter en los
   argumentos de la Instance se ignora (verificado: ni normvol ni gain
   cambian el nivel), y libvlc_media_player_set_equalizer la pisa con
   "equalizer". Para normalizar el volumen se fija la variable con
   var_SetChecked de libvlccore, en el reproductor (la lee la salida de audio
   al crearse) y en su salida de audio ya creada (objeto hijo con tipo
   "audio output"), igual que hace libVLC con el ecualizador. Son simbolos
   exportados de libvlccore; si faltan (otra version), audio_filters_supported()
   devuelve False y la UI desactiva la opcion.
"""

import ctypes
import logging
import os

import vlc

log = logging.getLogger(__name__)

# libvlc_track_type_t
TRACK_AUDIO = 0
TRACK_VIDEO = 1
TRACK_TEXT = 2

_VLC_VAR_STRING = 0x0040


class _AudioTrack(ctypes.Structure):
    _fields_ = [("channels", ctypes.c_uint), ("rate", ctypes.c_uint)]


class _VideoTrack(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_uint), ("width", ctypes.c_uint),
        ("sar_num", ctypes.c_uint), ("sar_den", ctypes.c_uint),
        ("frame_rate_num", ctypes.c_uint), ("frame_rate_den", ctypes.c_uint),
    ]


class _SubtitleTrack(ctypes.Structure):
    _fields_ = [("encoding", ctypes.c_char_p)]


class _TrackUnion(ctypes.Union):
    _fields_ = [
        ("audio", ctypes.POINTER(_AudioTrack)),
        ("video", ctypes.POINTER(_VideoTrack)),
        ("subtitle", ctypes.POINTER(_SubtitleTrack)),
    ]


class _MediaTrack(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("codec", ctypes.c_uint32), ("original_fourcc", ctypes.c_uint32), ("id", ctypes.c_int),
        ("type", ctypes.c_int), ("profile", ctypes.c_int), ("level", ctypes.c_int), ("u", _TrackUnion),
        ("bitrate", ctypes.c_uint), ("language", ctypes.c_char_p), ("description", ctypes.c_char_p),
    ]


_TrackArray = ctypes.POINTER(ctypes.POINTER(_MediaTrack))


def _handle(obj) -> int:
    """Puntero nativo de un objeto de python-vlc (Media, MediaPlayer)."""
    param = obj._as_parameter_
    return param.value if isinstance(param, ctypes.c_void_p) else int(param)


def _libvlc_function(name, restype, argtypes):
    func = getattr(vlc.dll, name)
    func.restype = restype
    func.argtypes = argtypes
    return func


def _text(value) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def media_tracks(media) -> list:
    """Pistas elementales de un Media ya analizado (o reproduciendose), como
    dicts: type ("audio"/"video"/"text"/"other"), codec (descripcion de
    libVLC, p. ej. "H264 - MPEG-4 AVC (part 10)"), fourcc, id, bitrate
    (bits/s, 0 si no se sabe), language, description y, segun el tipo,
    width/height/fps o channels/rate o encoding."""
    get = _libvlc_function("libvlc_media_tracks_get", ctypes.c_uint, [ctypes.c_void_p, ctypes.POINTER(_TrackArray)])
    release = _libvlc_function("libvlc_media_tracks_release", None, [_TrackArray, ctypes.c_uint])
    describe = _libvlc_function("libvlc_media_get_codec_description", ctypes.c_char_p, [ctypes.c_int, ctypes.c_uint32])
    array = _TrackArray()
    count = get(_handle(media), ctypes.byref(array))
    tracks = []
    try:
        for i in range(count):
            t = array[i].contents
            kind = {TRACK_AUDIO: "audio", TRACK_VIDEO: "video", TRACK_TEXT: "text"}.get(t.type, "other")
            fourcc = t.codec.to_bytes(4, "little").decode("latin-1").strip("\x00 ")
            track = {
                "type": kind,
                "id": t.id,
                "codec": _text(describe(t.type, t.codec)) or fourcc,
                "fourcc": fourcc,
                "bitrate": int(t.bitrate),
                "language": _text(t.language),
                "description": _text(t.description),
            }
            if kind == "video" and t.video:
                v = t.video.contents
                track.update(width=v.width, height=v.height,
                             fps=(v.frame_rate_num / v.frame_rate_den) if v.frame_rate_den else 0.0)
            elif kind == "audio" and t.audio:
                a = t.audio.contents
                track.update(channels=a.channels, rate=a.rate)
            elif kind == "text" and t.subtitle:
                track.update(encoding=_text(t.subtitle.contents.encoding))
            tracks.append(track)
    finally:
        if count:
            release(array, count)
    return tracks


# -- filtros de audio -----------------------------------------------------------
class _VlcList(ctypes.Structure):
    _fields_ = [("i_type", ctypes.c_int), ("i_count", ctypes.c_int), ("p_values", ctypes.POINTER(ctypes.c_void_p))]


_core = None
_core_checked = False


def _libvlccore():
    global _core, _core_checked
    if _core_checked:
        return _core
    _core_checked = True
    try:
        core = ctypes.CDLL(os.path.join(os.path.dirname(vlc.dll._name), "libvlccore.dll")) \
            if os.name == "nt" else ctypes.CDLL("libvlccore.so.9")
        core.var_SetChecked.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        core.var_SetChecked.restype = ctypes.c_int
        core.vlc_list_children.argtypes = [ctypes.c_void_p]
        core.vlc_list_children.restype = ctypes.POINTER(_VlcList)
        core.vlc_list_release.argtypes = [ctypes.POINTER(_VlcList)]
        core.vlc_list_release.restype = None
        _core = core
    except (OSError, AttributeError):
        log.warning("libvlccore sin var_SetChecked/vlc_list_children: no se puede normalizar el volumen", exc_info=True)
    return _core


def audio_filters_supported() -> bool:
    return vlc.libvlc_get_version().startswith(b"3.") and _libvlccore() is not None


def _set_string(core, obj: int, name: bytes, value: str) -> bool:
    buf = ctypes.create_string_buffer(value.encode("utf-8"))
    return core.var_SetChecked(obj, name, _VLC_VAR_STRING, ctypes.cast(buf, ctypes.c_void_p)) == 0


def set_audio_filters(media_player, chain: str) -> bool:
    """Fija la cadena de filtros de audio ("equalizer:normvol", "" = ninguno)
    en el reproductor y en su salida de audio si ya existe (se reconstruye
    en vivo). False si no se pudo."""
    core = _libvlccore() if audio_filters_supported() else None
    if core is None or media_player is None:
        return False
    obj = _handle(media_player)
    ok = _set_string(core, obj, b"audio-filter", chain)
    children = core.vlc_list_children(obj)
    if children:
        try:
            for i in range(children.contents.i_count):
                child = children.contents.p_values[i]
                # El primer campo de todo vlc_object_t es su tipo ("audio output").
                kind = ctypes.cast(ctypes.c_void_p(child), ctypes.POINTER(ctypes.c_char_p))[0]
                if kind == b"audio output":
                    ok = _set_string(core, child, b"audio-filter", chain) and ok
        finally:
            core.vlc_list_release(children)
    return ok
