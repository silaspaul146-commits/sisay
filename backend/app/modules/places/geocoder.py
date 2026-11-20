"""Place search for the map ("area search", PRD pilot scope), behind our own API.

The phone never talks to the geocoding provider directly: the provider sees our server, not the
person, and we can swap providers (an open decision, docs/PRODUCT.md) without an app update.
Today's provider is OpenStreetMap Nominatim. Its public service allows at most one request per
second and no autocomplete, so we search on submit, space calls out, and cache answers.

Search text can reveal where someone means to go: it is never logged, and the API takes it in a
POST body so it stays out of access logs.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# North-West and South-West regions with a margin (west, south, east, north).
SERVICE_AREA = (8.4, 3.85, 11.4, 7.3)


@dataclass(frozen=True)
class Place:
    name: str
    detail: str
    lat: float
    lon: float
    kind: str
    bbox: tuple[float, float, float, float] | None  # west, south, east, north

    def as_dict(self) -> dict:
        return {"name": self.name, "detail": self.detail, "latitude": self.lat, "longitude": self.lon,
                "kind": self.kind, "bbox": list(self.bbox) if self.bbox else None}


class SearchUnavailable(Exception):
    pass


def normalize(q: str) -> str:
    return " ".join(q.lower().split())


def _kind(item: dict) -> str:
    t = item.get("addresstype") or item.get("type") or ""
    if t in ("city", "town", "village", "hamlet", "municipality"):
        return "town"
    if t in ("suburb", "neighbourhood", "quarter", "city_district", "residential"):
        return "neighbourhood"
    if t in ("road", "street"):
        return "road"
    if t in ("county", "state", "state_district", "region"):
        return "area"
    return "place"


def _detail(item: dict, name: str) -> str:
    a = item.get("address") or {}
    seen: list[str] = []
    for k in ("suburb", "city", "town", "village", "county", "state"):
        p = a.get(k)
        if p and p != name and p not in seen:
            seen.append(p)
    return ", ".join(seen[:3])


def parse(items: list[dict]) -> list[Place]:
    out: list[Place] = []
    for it in items:
        try:
            lat, lon = float(it["lat"]), float(it["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        bbox = None
        bb = it.get("boundingbox")  # [south, north, west, east] as strings
        if isinstance(bb, list) and len(bb) == 4:
            try:
                s, n, w, e = (float(x) for x in bb)
                bbox = (w, s, e, n)
            except (TypeError, ValueError):
                pass
        name = it.get("name") or (it.get("display_name") or "").split(",")[0].strip()
        if not name:
            continue
        out.append(Place(name=name, detail=_detail(it, name), lat=lat, lon=lon, kind=_kind(it), bbox=bbox))
    return out


class NominatimGeocoder:
    def __init__(self, user_agent: str, url: str = NOMINATIM_URL, min_interval_s: float = 1.1,
                 cache_size: int = 2000, cache_ttl_s: float = 7 * 24 * 3600, timeout_s: float = 8.0):
        self._ua = user_agent
        self._url = url
        self._min_interval = min_interval_s
        self._cache: OrderedDict[tuple[str, str], tuple[float, list[Place]]] = OrderedDict()
        self._cache_size = cache_size
        self._ttl = cache_ttl_s
        self._timeout = timeout_s
        self._lock = threading.Lock()  # one upstream call at a time
        self._cache_lock = threading.Lock()
        self._last_call = 0.0

    def _cached(self, key: tuple[str, str]) -> list[Place] | None:
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < self._ttl:
                self._cache.move_to_end(key)
                return hit[1]
            return None

    def _store(self, key: tuple[str, str], places: list[Place]) -> None:
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), places)
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def search(self, q: str, lang: str = "en", limit: int = 8) -> list[Place]:
        key = (normalize(q), lang)
        hit = self._cached(key)
        if hit is not None:
            return hit[:limit]
        w, s, e, n = SERVICE_AREA
        params = urllib.parse.urlencode({
            "q": q.strip(), "format": "jsonv2", "addressdetails": 1, "limit": 10,
            "countrycodes": "cm", "viewbox": f"{w},{n},{e},{s}", "bounded": 1,
        })
        req = urllib.request.Request(f"{self._url}?{params}", headers={
            "User-Agent": self._ua, "Accept-Language": f"{lang},en;q=0.5", "Accept": "application/json"})
        # Waiting for our turn can take a while under load; give up rather than hang the phone.
        if not self._lock.acquire(timeout=self._timeout):
            raise SearchUnavailable("busy")
        try:
            hit = self._cached(key)  # another request may have just fetched it
            if hit is not None:
                return hit[:limit]
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    items = json.loads(resp.read())
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                raise SearchUnavailable(type(exc).__name__) from None
            finally:
                self._last_call = time.monotonic()
        finally:
            self._lock.release()
        places = parse(items if isinstance(items, list) else [])
        self._store(key, places)
        return places[:limit]
