"""Place search: provider parsing, caching, spacing, failure, and the API envelope (no network)."""
import io
import json
import urllib.error
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.places import geocoder as g
from app.modules.places import router as places_router

BAMENDA = {
    "lat": "5.9597", "lon": "10.1460", "name": "Bamenda", "addresstype": "city",
    "boundingbox": ["5.80", "6.12", "10.00", "10.30"],
    "address": {"city": "Bamenda", "county": "Mezam", "state": "North-West"},
}
NKWEN = {
    "lat": "5.98", "lon": "10.18", "name": "Nkwen", "addresstype": "suburb",
    "address": {"suburb": "Nkwen", "city": "Bamenda", "state": "North-West"},
}


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _fake(monkeypatch, items=None, fail=False):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        if fail:
            raise urllib.error.URLError("down")
        return _Resp(json.dumps(items or []).encode())
    monkeypatch.setattr(g.urllib.request, "urlopen", urlopen)
    return calls


def test_parse_shapes_results():
    places = g.parse([BAMENDA, NKWEN, {"lat": "x"}, {"lat": "1", "lon": "1"}])
    assert [p.name for p in places] == ["Bamenda", "Nkwen"]
    assert places[0].kind == "town" and places[0].detail == "Mezam, North-West"
    assert places[0].bbox == (10.0, 5.8, 10.3, 6.12)
    assert places[1].kind == "neighbourhood" and places[1].detail == "Bamenda, North-West"


def test_request_is_bounded_to_service_area_and_identified(monkeypatch):
    calls = _fake(monkeypatch, [BAMENDA])
    geo = g.NominatimGeocoder("Sisay/test", min_interval_s=0)
    assert geo.search("Bamenda", "fr")[0].name == "Bamenda"
    req = calls[0]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
    assert qs["countrycodes"] == ["cm"] and qs["bounded"] == ["1"] and qs["q"] == ["Bamenda"]
    assert req.get_header("User-agent") == "Sisay/test"
    assert req.get_header("Accept-language").startswith("fr")


def test_cache_answers_repeat_searches(monkeypatch):
    calls = _fake(monkeypatch, [BAMENDA])
    geo = g.NominatimGeocoder("Sisay/test", min_interval_s=0)
    geo.search("Bamenda")
    geo.search("  bamenda ")
    assert len(calls) == 1
    geo.search("Bamenda", "fr")  # language is part of the key
    assert len(calls) == 2


def test_cache_is_bounded(monkeypatch):
    _fake(monkeypatch, [BAMENDA])
    geo = g.NominatimGeocoder("Sisay/test", min_interval_s=0, cache_size=2)
    for q in ("aa", "bb", "cc"):
        geo.search(q)
    assert len(geo._cache) == 2


def test_upstream_failure_is_unavailable(monkeypatch):
    _fake(monkeypatch, fail=True)
    with pytest.raises(g.SearchUnavailable):
        g.NominatimGeocoder("Sisay/test", min_interval_s=0).search("Bamenda")


@pytest.fixture
def client(monkeypatch):
    geo = g.NominatimGeocoder("Sisay/test", min_interval_s=0)
    monkeypatch.setattr(places_router, "geocoder", lambda: geo)
    return TestClient(app)


def test_api_returns_places(client, monkeypatch):
    _fake(monkeypatch, [BAMENDA, NKWEN])
    resp = client.post("/api/v1/public/place-search", json={"query": "Bamenda", "limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == [{"name": "Bamenda", "detail": "Mezam, North-West", "latitude": 5.9597,
                              "longitude": 10.146, "kind": "town", "bbox": [10.0, 5.8, 10.3, 6.12]}]
    assert "OpenStreetMap" in body["attribution"]
    assert resp.headers["Cache-Control"] == "no-store"


def test_api_rejects_blank_and_unknown_fields(client, monkeypatch):
    calls = _fake(monkeypatch, [BAMENDA])
    assert client.post("/api/v1/public/place-search", json={"query": "  "}).status_code == 422
    assert client.post("/api/v1/public/place-search", json={"query": "ok", "x": 1}).status_code == 422
    assert client.post("/api/v1/public/place-search", json={"query": "ok", "lang": "de"}).status_code == 422
    assert calls == []


def test_api_unavailable_envelope(client, monkeypatch):
    _fake(monkeypatch, fail=True)
    resp = client.post("/api/v1/public/place-search", json={"query": "Bamenda"})
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "search_unavailable"


def test_app_config_serves_map_settings():
    resp = TestClient(app).get("/api/v1/public/app-config")
    assert resp.status_code == 200
    m = resp.json()["map"]
    assert m["tile_url"].startswith("https://") and "{z}" in m["tile_url"]
    assert m["subdomains"] == ["a", "b", "c"] and "OpenStreetMap" in m["attribution"]
