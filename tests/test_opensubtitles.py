"""Prueba el cliente de OpenSubtitles sin tocar la red real: requests.get/
post se reemplazan por dobles. El algoritmo de hash se prueba con
vectores construidos a mano (archivos sinteticos con contenido conocido),
no contra la API."""
import pytest

from player import opensubtitles as osub


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.content = content
        self.text = text

    def json(self):
        return self._json_data


# ------------------------------------------------------------ hash ----
def test_hash_of_an_all_zero_file_equals_its_size(tmp_path):
    path = tmp_path / "zeros.bin"
    path.write_bytes(b"\x00" * (65536 * 2))
    assert osub.compute_opensubtitles_hash(str(path)) == f"{65536 * 2:016x}"


def test_hash_reflects_the_first_and_last_chunks(tmp_path):
    size = 65536 * 3
    data = bytearray(size)
    data[0:8] = (5).to_bytes(8, "little")
    data[-8:] = (7).to_bytes(8, "little")
    path = tmp_path / "edges.bin"
    path.write_bytes(bytes(data))
    expected = (size + 5 + 7) & osub.HASH_MASK
    assert osub.compute_opensubtitles_hash(str(path)) == f"{expected:016x}"


def test_hash_is_none_for_files_smaller_than_128kb(tmp_path):
    path = tmp_path / "small.bin"
    path.write_bytes(b"\x00" * 1000)
    assert osub.compute_opensubtitles_hash(str(path)) is None


# ------------------------------------------------------------ search --
def test_search_parses_results_and_sorts_by_download_count(monkeypatch):
    payload = {
        "data": [
            {
                "attributes": {
                    "language": "es",
                    "release": "Peli.2024.1080p",
                    "download_count": 10,
                    "files": [{"file_id": 111, "file_name": "peli.srt"}],
                }
            },
            {
                "attributes": {
                    "language": "en",
                    "release": "Movie.2024.1080p",
                    "download_count": 500,
                    "files": [{"file_id": 222, "file_name": "movie.srt"}],
                }
            },
        ]
    }
    monkeypatch.setattr(osub.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    results = osub.search_by_query("fake-key", "Peli 2024")
    assert [r["file_id"] for r in results] == [222, 111]
    assert results[0]["language"] == "en"


def test_search_skips_entries_without_files(monkeypatch):
    payload = {"data": [{"attributes": {"language": "es", "download_count": 1, "files": []}}]}
    monkeypatch.setattr(osub.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    assert osub.search_by_query("fake-key", "algo") == []


def test_search_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(osub.requests, "get", lambda *a, **k: FakeResponse(401, text="unauthorized"))
    with pytest.raises(osub.OpenSubtitlesError):
        osub.search_by_query("bad-key", "algo")


def test_search_raises_on_network_error(monkeypatch):
    def raise_it(*a, **k):
        raise osub.requests.RequestException("sin conexión")

    monkeypatch.setattr(osub.requests, "get", raise_it)
    with pytest.raises(osub.OpenSubtitlesError):
        osub.search_by_query("fake-key", "algo")


# ------------------------------------------------------------ download --
def test_download_subtitle_writes_the_file(monkeypatch, tmp_path):
    def fake_post(url, json=None, headers=None, timeout=None):
        assert json == {"file_id": 111}
        return FakeResponse(200, {"link": "https://example.com/sub.srt"})

    def fake_get(url, timeout=None):
        assert url == "https://example.com/sub.srt"
        return FakeResponse(200, content=b"1\n00:00:01,000 --> 00:00:02,000\nHola\n")

    monkeypatch.setattr(osub.requests, "post", fake_post)
    monkeypatch.setattr(osub.requests, "get", fake_get)

    dest = tmp_path / "sub.srt"
    result = osub.download_subtitle("fake-key", 111, str(dest))
    assert result == str(dest)
    assert dest.read_bytes().startswith(b"1\n00:00:01")


def test_download_subtitle_raises_when_no_link_in_response(monkeypatch, tmp_path):
    monkeypatch.setattr(osub.requests, "post", lambda *a, **k: FakeResponse(200, {}))
    with pytest.raises(osub.OpenSubtitlesError):
        osub.download_subtitle("fake-key", 111, str(tmp_path / "sub.srt"))


# ---------------------------------------------- respuestas raras (3.11)
def test_malformed_results_are_skipped_not_raised(monkeypatch):
    payload = {"data": [
        {"attributes": {"files": [{"file_name": "sin_id.srt"}]}},            # sin file_id
        {"attributes": {"files": "no-es-lista"}},
        "no-es-dict",
        {"attributes": {"language": "es", "files": [{"file_id": 7, "file_name": "a.ass"}],
                        "download_count": "muchas"}},
    ]}
    monkeypatch.setattr(osub.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    results = osub.search_by_query("key", "x")
    assert [(r["file_id"], r["download_count"], r["file_name"]) for r in results] == [(7, 0, "a.ass")]


def test_non_json_response_raises_opensubtitles_error(monkeypatch):
    class HtmlResponse(FakeResponse):
        def json(self):
            raise ValueError("no es JSON")

    monkeypatch.setattr(osub.requests, "get", lambda *a, **k: HtmlResponse(200, None, text="<html>"))
    with pytest.raises(osub.OpenSubtitlesError):
        osub.search_by_hash("key", "abc")


def test_download_reports_quota_and_extension_helpers(monkeypatch, tmp_path):
    monkeypatch.setattr(osub.requests, "post", lambda *a, **k: FakeResponse(
        200, {"link": "https://dl/x", "remaining": 17, "reset_time": "5 horas"}))
    monkeypatch.setattr(osub.requests, "get", lambda *a, **k: FakeResponse(200, None, content=b"1\n"))
    result = osub.download_subtitle_file("key", 1, str(tmp_path / "s.srt"))
    assert (result.remaining, result.reset_time) == (17, "5 horas")
    assert osub.subtitle_extension("Movie.ES.ass") == ".ass" and osub.subtitle_extension("x.zip") == ".srt"
    assert osub.normalize_languages(" Es; EN ,pt-BR,es, xx-yyyyy1") == "es,en,pt-br"
    assert osub.USER_AGENT.endswith(__import__("player").__version__)
