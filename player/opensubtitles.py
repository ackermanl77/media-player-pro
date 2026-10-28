"""Cliente minimo de la API REST de OpenSubtitles (api.opensubtitles.com).
Requiere una API key del usuario (ver player.config) -- no incluye ninguna
key propia. Modulo puro: no depende de VLC ni de Qt, para poder probarlo
sin ninguno de los dos."""

import os
import re
import tempfile
from dataclasses import dataclass

import requests

from . import __version__
from .m3u import decode_playlist_bytes
from .subtitle_cues import MAX_SUBTITLE_BYTES, parse_cues

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = f"ReproductorMultimediaPro v{__version__}"
DEFAULT_LANGUAGES = "es,en"
SUBTITLE_EXTS = (".srt", ".ass", ".ssa", ".sub", ".vtt", ".smi")
_LANGUAGES_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2,4})?(,[a-z]{2,3}(-[a-z]{2,4})?)*$")
REQUEST_TIMEOUT_S = 15
DOWNLOAD_TIMEOUT_S = 30

# El algoritmo de hash de OpenSubtitles (tambien usado por BS.Player) no
# aplica a archivos mas chicos que dos "ventanas" de 64KB.
HASH_CHUNK_SIZE = 65536
HASH_MASK = 0xFFFFFFFFFFFFFFFF


class OpenSubtitlesError(Exception):
    pass


def compute_opensubtitles_hash(path: str):
    """Hash de OpenSubtitles: tamano de archivo + suma (mod 2**64) de los
    bloques de 8 bytes de los primeros y ultimos 64KB del archivo. None si
    el archivo es demasiado chico para que el algoritmo tenga sentido."""
    filesize = os.path.getsize(path)
    if filesize < HASH_CHUNK_SIZE * 2:
        return None
    file_hash = filesize
    with open(path, "rb") as f:
        for _ in range(HASH_CHUNK_SIZE // 8):
            file_hash = (file_hash + int.from_bytes(f.read(8), "little")) & HASH_MASK
        f.seek(max(0, filesize - HASH_CHUNK_SIZE))
        for _ in range(HASH_CHUNK_SIZE // 8):
            file_hash = (file_hash + int.from_bytes(f.read(8), "little")) & HASH_MASK
    return f"{file_hash:016x}"


def _headers(api_key: str, json_body: bool = False) -> dict:
    headers = {"Api-Key": api_key, "User-Agent": USER_AGENT}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def normalize_languages(text) -> str:
    """"Es, EN ;pt-BR" -> "es,en,pt-br". Codigos ISO 639 separados por
    coma, como los pide la API; "" si no hay ninguno valido."""
    if not isinstance(text, str):
        return ""
    parts = [p.strip().lower() for p in re.split(r"[,; ]+", text) if p.strip()]
    seen = []
    for p in parts:
        if _LANGUAGES_RE.match(p) and p not in seen:
            seen.append(p)
    return ",".join(seen)


def subtitle_extension(file_name) -> str:
    """Extension a usar para el archivo descargado: la del propio
    resultado (".ass", ".vtt"...) si es de subtitulos; si no, ".srt"."""
    ext = os.path.splitext(file_name or "")[1].lower()
    return ext if ext in SUBTITLE_EXTS else ".srt"


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _parse_results(data) -> list:
    """Tolerante a respuestas raras: un item sin los campos esperados se
    salta en vez de tirar KeyError (que antes dejaba el dialogo colgado en
    "Buscando...")."""
    results = []
    items = _as_dict(data).get("data")
    for item in items if isinstance(items, list) else []:
        attrs = _as_dict(_as_dict(item).get("attributes"))
        files = attrs.get("files")
        if not isinstance(files, list) or not files:
            continue
        first = _as_dict(files[0])
        file_id = first.get("file_id")
        if isinstance(file_id, bool) or not isinstance(file_id, int):
            continue
        count = attrs.get("download_count")
        results.append({
            "file_id": file_id,
            "language": str(attrs.get("language") or "?"),
            "release": str(attrs.get("release") or _as_dict(attrs.get("feature_details")).get("title") or "?"),
            "download_count": count if isinstance(count, int) and not isinstance(count, bool) else 0,
            "file_name": str(first.get("file_name") or "subtitulo.srt"),
        })
    results.sort(key=lambda r: r["download_count"], reverse=True)
    return results


def _json(resp):
    try:
        return resp.json()
    except ValueError as e:  # 200 con HTML de un proxy, cuerpo vacio, etc.
        raise OpenSubtitlesError("OpenSubtitles devolvió una respuesta inválida") from e


def search_by_hash(api_key: str, file_hash: str, languages: str = DEFAULT_LANGUAGES) -> list:
    return _search(api_key, {"moviehash": file_hash, "languages": languages})


def search_by_query(api_key: str, query: str, languages: str = DEFAULT_LANGUAGES) -> list:
    return _search(api_key, {"query": query, "languages": languages})


def _search(api_key: str, params: dict) -> list:
    try:
        resp = requests.get(
            f"{API_BASE}/subtitles", params=params, headers=_headers(api_key), timeout=REQUEST_TIMEOUT_S
        )
    except requests.RequestException as e:
        raise OpenSubtitlesError(f"Error de red al buscar subtítulos: {e}") from e
    if resp.status_code != 200:
        raise OpenSubtitlesError(f"OpenSubtitles respondió {resp.status_code}: {resp.text[:200]}")
    return _parse_results(_json(resp))


@dataclass
class DownloadResult:
    path: str
    remaining: object = None   # descargas que quedan hoy (int) o None si la API no lo dijo
    reset_time: str = ""


def request_download(api_key: str, file_id: int):
    """(link, descargas restantes, cuando se reinicia la cuota)."""
    try:
        resp = requests.post(
            f"{API_BASE}/download",
            json={"file_id": file_id},
            headers=_headers(api_key, json_body=True),
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise OpenSubtitlesError(f"Error de red al solicitar la descarga: {e}") from e
    if resp.status_code != 200:
        raise OpenSubtitlesError(f"OpenSubtitles respondió {resp.status_code}: {resp.text[:200]}")
    data = _as_dict(_json(resp))
    link = data.get("link")
    if not isinstance(link, str) or not link:
        raise OpenSubtitlesError("La respuesta de OpenSubtitles no incluyó un link de descarga")
    remaining = data.get("remaining")
    remaining = remaining if isinstance(remaining, int) and not isinstance(remaining, bool) else None
    return link, remaining, str(data.get("reset_time") or "")


def _validate_subtitle_file(path: str, extension: str) -> None:
    with open(path, "rb") as f:
        content = f.read(MAX_SUBTITLE_BYTES + 1)
    if not content or len(content) > MAX_SUBTITLE_BYTES or b"\x00" in content:
        raise OpenSubtitlesError("La descarga del subtítulo está vacía o no es válida")

    text = decode_playlist_bytes(content)
    if extension in (".srt", ".vtt", ".ass", ".ssa"):
        if extension == ".vtt" and not re.search(r"(?im)^\ufeff?WEBVTT(?:\s|$)", text):
            raise OpenSubtitlesError("La descarga no tiene un encabezado WebVTT válido")
        if not any(start < end for start, end in parse_cues(text, extension)):
            raise OpenSubtitlesError("La descarga no contiene subtítulos válidos")
    elif extension == ".sub":
        if not re.search(r"(?m)^\s*\{\d+\}\{\d+\}.+", text):
            raise OpenSubtitlesError("La descarga no contiene subtítulos MicroDVD válidos")
    elif extension == ".smi":
        if not re.search(r"(?is)<sami(?:\s|>)", text) or not re.search(r"(?is)<sync\b", text):
            raise OpenSubtitlesError("La descarga no contiene subtítulos SAMI válidos")
    elif extension not in SUBTITLE_EXTS:
        raise OpenSubtitlesError("La extensión del subtítulo descargado no es válida")


def download_subtitle_file(api_key: str, file_id: int, dest_path: str) -> DownloadResult:
    link, remaining, reset_time = request_download(api_key, file_id)
    sub_resp = None
    temp_path = None
    try:
        sub_resp = requests.get(link, timeout=DOWNLOAD_TIMEOUT_S, stream=True)
        if sub_resp.status_code != 200:
            raise OpenSubtitlesError(f"La descarga del subtítulo falló: {sub_resp.status_code}")

        content_length = sub_resp.headers.get("Content-Length", "")
        try:
            declared_size = int(content_length)
        except (TypeError, ValueError):
            declared_size = 0
        if declared_size > MAX_SUBTITLE_BYTES:
            raise OpenSubtitlesError("El subtítulo descargado supera el tamaño máximo permitido")

        dest_dir = os.path.dirname(os.path.abspath(dest_path))
        prefix = f".{os.path.basename(dest_path)}."
        fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix=".part", dir=dest_dir)
        size = 0
        with os.fdopen(fd, "wb") as f:
            for chunk in sub_resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_SUBTITLE_BYTES:
                    raise OpenSubtitlesError("El subtítulo descargado supera el tamaño máximo permitido")
                f.write(chunk)

        extension = os.path.splitext(dest_path)[1].lower()
        _validate_subtitle_file(temp_path, extension)
        os.replace(temp_path, dest_path)
        temp_path = None
    except requests.RequestException as e:
        raise OpenSubtitlesError(f"Error de red al descargar el subtítulo: {e}") from e
    except OSError as e:
        raise OpenSubtitlesError(f"No se pudo guardar el subtítulo: {e}") from e
    finally:
        if sub_resp is not None:
            sub_resp.close()
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    return DownloadResult(dest_path, remaining, reset_time)


def download_subtitle(api_key: str, file_id: int, dest_path: str) -> str:
    return download_subtitle_file(api_key, file_id, dest_path).path
