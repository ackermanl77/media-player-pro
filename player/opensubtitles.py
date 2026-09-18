"""Cliente minimo de la API REST de OpenSubtitles (api.opensubtitles.com).
Requiere una API key del usuario (ver player.config) -- no incluye ninguna
key propia. Modulo puro: no depende de VLC ni de Qt, para poder probarlo
sin ninguno de los dos."""

import os

import requests

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "ReproductorMultimediaPro v1.0"
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


def _parse_results(data: dict) -> list:
    results = []
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        files = attrs.get("files") or []
        if not files:
            continue
        results.append({
            "file_id": files[0]["file_id"],
            "language": attrs.get("language") or "?",
            "release": attrs.get("release") or attrs.get("feature_details", {}).get("title") or "?",
            "download_count": attrs.get("download_count") or 0,
            "file_name": files[0].get("file_name") or "subtitulo.srt",
        })
    results.sort(key=lambda r: r["download_count"], reverse=True)
    return results


def search_by_hash(api_key: str, file_hash: str, languages: str = "es,en") -> list:
    return _search(api_key, {"moviehash": file_hash, "languages": languages})


def search_by_query(api_key: str, query: str, languages: str = "es,en") -> list:
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
    return _parse_results(resp.json())


def download_subtitle(api_key: str, file_id: int, dest_path: str) -> str:
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
    link = resp.json().get("link")
    if not link:
        raise OpenSubtitlesError("La respuesta de OpenSubtitles no incluyó un link de descarga")
    try:
        sub_resp = requests.get(link, timeout=DOWNLOAD_TIMEOUT_S)
    except requests.RequestException as e:
        raise OpenSubtitlesError(f"Error de red al descargar el subtítulo: {e}") from e
    if sub_resp.status_code != 200:
        raise OpenSubtitlesError(f"La descarga del subtítulo falló: {sub_resp.status_code}")
    with open(dest_path, "wb") as f:
        f.write(sub_resp.content)
    return dest_path
