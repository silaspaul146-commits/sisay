"""Citizen personal routes (API contract 7, 8, 9 and device registration). No account needed: the
caller is an app installation proven by X-Installation-Token. Everything here is scoped to that
installation's subscriber principal; another installation's ids answer 404, never 403, so ids
cannot be probed. Saved places are deleted for real on DELETE (they are personal data); alert
history keeps working because history rows only lose their link."""
import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, text

from app.core.db import get_engine
from app.core.errors import ApiError, validation_error
from app.modules.subscriptions.installation_auth import (
    InstallationToken, SettingsDep, authenticate, register_installation, subscriber_id,
)

router = APIRouter(tags=["citizen: places and alerts"])
Severity = Literal["low", "moderate", "medium", "high", "critical"]  # "medium" = API contract spelling


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _not_found() -> ApiError:
    return ApiError(404, "resource_not_found", "The resource was not found.")


# --- Installations and push endpoints -------------------------------------------------------------

class InstallationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["android", "ios", "web"]
    app_version: str | None = Field(default=None, max_length=40)


@router.post("/installations", status_code=201)
def create_installation(body: InstallationIn, response: Response, settings: SettingsDep) -> dict:
    """Register this app. Keep `installation_token` secret on the device; it is shown only once.
    Also send `installation_id` as X-Installation-ID when submitting reports."""
    with get_engine().begin() as conn:
        iid, token = register_installation(conn, body.platform, body.app_version, settings)
    _no_store(response)
    return {"installation_id": str(iid), "installation_token": token}


class PushEndpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["fcm"] = "fcm"
    token: str = Field(min_length=20, max_length=4096)


@router.post("/devices/push-endpoints", status_code=201)
def register_push(body: PushEndpointIn, response: Response, settings: SettingsDep,
                  token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        device = authenticate(conn, token, settings)
        eid = conn.execute(text("SELECT identity.register_push_endpoint(:iid, :p, :t)"),
                           {"iid": device.installation_id, "p": body.provider, "t": body.token}).scalar_one()
    _no_store(response)
    return {"id": str(eid), "provider": body.provider, "status": "active"}


@router.delete("/devices/push-endpoints/{endpoint_id}", status_code=204)
def revoke_push(endpoint_id: uuid.UUID, settings: SettingsDep, token: InstallationToken = None) -> Response:
    with get_engine().begin() as conn:
        device = authenticate(conn, token, settings)
        n = conn.execute(text("""UPDATE identity.push_endpoints SET status = 'revoked', updated_at = now()
                                 WHERE id = :id AND installation_id = :iid"""),
                         {"id": endpoint_id, "iid": device.installation_id}).rowcount
    if not n:
        raise _not_found()
    return Response(status_code=204)


# --- Saved locations ------------------------------------------------------------------------------

class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SavedLocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    location: Point
    radius_m: int = Field(default=1000, ge=100, le=50_000)


class SavedLocationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    location: Point | None = None
    radius_m: int | None = Field(default=None, ge=100, le=50_000)
    enabled: bool | None = None


_LOCATION_COLS = """id, name, radius_m, enabled, created_at, updated_at,
                    ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon"""


def _location(r) -> dict:
    return {"id": str(r.id), "name": r.name, "location": {"latitude": r.lat, "longitude": r.lon},
            "radius_m": r.radius_m, "enabled": r.enabled, "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat()}


@router.post("/saved-locations", status_code=201)
def create_location(body: SavedLocationIn, response: Response, settings: SettingsDep,
                    token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        r = conn.execute(text(f"""
            INSERT INTO subscription.saved_locations (subscriber_id, name, location, radius_m)
            VALUES (:sid, :name, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)
            RETURNING {_LOCATION_COLS}"""),
            {"sid": sid, "name": body.name, "lat": body.location.latitude, "lon": body.location.longitude,
             "r": body.radius_m}).one()
    _no_store(response)
    return _location(r)


@router.get("/saved-locations")
def list_locations(response: Response, settings: SettingsDep, token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        rows = conn.execute(text(f"SELECT {_LOCATION_COLS} FROM subscription.saved_locations "
                                 "WHERE subscriber_id = :sid ORDER BY created_at"), {"sid": sid}).all()
    _no_store(response)
    return {"items": [_location(r) for r in rows], "next_cursor": None}


@router.get("/saved-locations/{location_id}")
def get_location(location_id: uuid.UUID, response: Response, settings: SettingsDep,
                 token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        r = conn.execute(text(f"SELECT {_LOCATION_COLS} FROM subscription.saved_locations "
                              "WHERE id = :id AND subscriber_id = :sid"), {"id": location_id, "sid": sid}).first()
    if r is None:
        raise _not_found()
    _no_store(response)
    return _location(r)


@router.patch("/saved-locations/{location_id}")
def update_location(location_id: uuid.UUID, body: SavedLocationPatch, response: Response, settings: SettingsDep,
                    token: InstallationToken = None) -> dict:
    sets, params = [], {"id": location_id}
    if body.name is not None:
        sets.append("name = :name"); params["name"] = body.name  # noqa: E702
    if body.radius_m is not None:
        sets.append("radius_m = :r"); params["r"] = body.radius_m  # noqa: E702
    if body.enabled is not None:
        sets.append("enabled = :enabled"); params["enabled"] = body.enabled  # noqa: E702
    if body.location is not None:
        sets.append("location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography")
        params.update(lat=body.location.latitude, lon=body.location.longitude)
    if not sets:
        raise validation_error("body", "Send at least one field to change.")
    with get_engine().begin() as conn:
        params["sid"] = subscriber_id(conn, authenticate(conn, token, settings))
        r = conn.execute(text(f"UPDATE subscription.saved_locations SET {', '.join(sets)} "
                              f"WHERE id = :id AND subscriber_id = :sid RETURNING {_LOCATION_COLS}"), params).first()
    if r is None:
        raise _not_found()
    _no_store(response)
    return _location(r)


@router.delete("/saved-locations/{location_id}", status_code=204)
def delete_location(location_id: uuid.UUID, settings: SettingsDep, token: InstallationToken = None) -> Response:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        n = conn.execute(text("DELETE FROM subscription.saved_locations WHERE id = :id AND subscriber_id = :sid"),
                         {"id": location_id, "sid": sid}).rowcount
    if not n:
        raise _not_found()
    return Response(status_code=204)


# --- Saved routes ---------------------------------------------------------------------------------

class LineString(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]] = Field(min_length=2, max_length=5000)

    @field_validator("coordinates")
    @classmethod
    def _bounds(cls, coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for lon, lat in coords:
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("Coordinates are [longitude, latitude] within valid ranges.")
        return coords


class SavedRouteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    route: LineString
    corridor_width_m: int = Field(default=1000, ge=100, le=20_000)


class SavedRoutePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    route: LineString | None = None
    corridor_width_m: int | None = Field(default=None, ge=100, le=20_000)
    enabled: bool | None = None


_ROUTE_COLS = """id, name, corridor_width_m, enabled, created_at, updated_at,
                 round(ST_Length(route_geometry))::int AS length_m,
                 ST_AsGeoJSON(ST_LineMerge(route_geometry::geometry), 6) AS geojson"""
_ROUTE_GEOM = "ST_Multi(ST_GeomFromGeoJSON(:geojson))::geography"


def _route(r, with_geometry: bool = True) -> dict:
    out = {"id": str(r.id), "name": r.name, "corridor_width_m": r.corridor_width_m, "enabled": r.enabled,
           "length_m": r.length_m, "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat()}
    if with_geometry:
        out["route"] = json.loads(r.geojson)
    return out


def _geojson(line: LineString) -> str:
    return json.dumps({"type": "LineString", "coordinates": [list(c) for c in line.coordinates]})


@router.post("/saved-routes", status_code=201)
def create_route(body: SavedRouteIn, response: Response, settings: SettingsDep,
                 token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        r = conn.execute(text(f"""
            INSERT INTO subscription.saved_routes (subscriber_id, name, route_geometry, corridor_width_m)
            VALUES (:sid, :name, {_ROUTE_GEOM}, :w) RETURNING {_ROUTE_COLS}"""),
            {"sid": sid, "name": body.name, "geojson": _geojson(body.route), "w": body.corridor_width_m}).one()
    _no_store(response)
    return _route(r)


@router.get("/saved-routes")
def list_routes(response: Response, settings: SettingsDep, token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        rows = conn.execute(text(f"SELECT {_ROUTE_COLS} FROM subscription.saved_routes "
                                 "WHERE subscriber_id = :sid ORDER BY created_at"), {"sid": sid}).all()
    _no_store(response)
    return {"items": [_route(r, with_geometry=False) for r in rows], "next_cursor": None}


@router.get("/saved-routes/{route_id}")
def get_route(route_id: uuid.UUID, response: Response, settings: SettingsDep,
              token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        r = conn.execute(text(f"SELECT {_ROUTE_COLS} FROM subscription.saved_routes "
                              "WHERE id = :id AND subscriber_id = :sid"), {"id": route_id, "sid": sid}).first()
    if r is None:
        raise _not_found()
    _no_store(response)
    return _route(r)


@router.patch("/saved-routes/{route_id}")
def update_route(route_id: uuid.UUID, body: SavedRoutePatch, response: Response, settings: SettingsDep,
                 token: InstallationToken = None) -> dict:
    sets, params = [], {"id": route_id}
    if body.name is not None:
        sets.append("name = :name"); params["name"] = body.name  # noqa: E702
    if body.corridor_width_m is not None:
        sets.append("corridor_width_m = :w"); params["w"] = body.corridor_width_m  # noqa: E702
    if body.enabled is not None:
        sets.append("enabled = :enabled"); params["enabled"] = body.enabled  # noqa: E702
    if body.route is not None:
        sets.append(f"route_geometry = {_ROUTE_GEOM}"); params["geojson"] = _geojson(body.route)  # noqa: E702
    if not sets:
        raise validation_error("body", "Send at least one field to change.")
    with get_engine().begin() as conn:
        params["sid"] = subscriber_id(conn, authenticate(conn, token, settings))
        r = conn.execute(text(f"UPDATE subscription.saved_routes SET {', '.join(sets)} "
                              f"WHERE id = :id AND subscriber_id = :sid RETURNING {_ROUTE_COLS}"), params).first()
    if r is None:
        raise _not_found()
    _no_store(response)
    return _route(r)


@router.delete("/saved-routes/{route_id}", status_code=204)
def delete_route(route_id: uuid.UUID, settings: SettingsDep, token: InstallationToken = None) -> Response:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        n = conn.execute(text("DELETE FROM subscription.saved_routes WHERE id = :id AND subscriber_id = :sid"),
                         {"id": route_id, "sid": sid}).rowcount
    if not n:
        raise _not_found()
    return Response(status_code=204)


# --- Alert subscriptions --------------------------------------------------------------------------

class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    saved_location_id: uuid.UUID | None = None
    saved_route_id: uuid.UUID | None = None
    categories: list[str] | None = Field(default=None, max_length=50)  # None or [] = every type
    minimum_severity: Severity = "moderate"
    enabled: bool = True


class SubscriptionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: list[str] | None = Field(default=None, max_length=50)
    minimum_severity: Severity | None = None
    enabled: bool | None = None


def _sev(s: str) -> str:
    return "moderate" if s == "medium" else s


def _set_categories(conn: Connection, subscription_id: uuid.UUID, codes: list[str] | None) -> None:
    conn.execute(text("DELETE FROM subscription.alert_subscription_categories WHERE subscription_id = :id"),
                 {"id": subscription_id})
    if codes:
        ids = conn.execute(text("SELECT id, code FROM ref.incident_categories WHERE code = ANY(:c) AND active"),
                           {"c": list(set(codes))}).all()
        unknown = sorted(set(codes) - {r.code for r in ids})
        if unknown:
            raise validation_error("categories", f"Unknown categories: {', '.join(unknown)}.")
        for r in ids:
            conn.execute(text("INSERT INTO subscription.alert_subscription_categories (subscription_id, category_id) "
                              "VALUES (:s, :c)"), {"s": subscription_id, "c": r.id})
    conn.execute(text("UPDATE subscription.alert_subscriptions SET all_categories = :all WHERE id = :id"),
                 {"all": not codes, "id": subscription_id})


_SUB_SQL = """
    SELECT s.id, s.saved_location_id, s.saved_route_id, s.all_categories, s.min_severity, s.enabled, s.created_at,
           COALESCE(sl.name, sr.name) AS target_name,
           ARRAY(SELECT c.code FROM subscription.alert_subscription_categories x
                 JOIN ref.incident_categories c ON c.id = x.category_id
                 WHERE x.subscription_id = s.id ORDER BY c.code) AS categories
    FROM subscription.alert_subscriptions s
    LEFT JOIN subscription.saved_locations sl ON sl.id = s.saved_location_id
    LEFT JOIN subscription.saved_routes sr ON sr.id = s.saved_route_id
    WHERE s.subscriber_id = :sid
"""


def _subscription(r) -> dict:
    return {"id": str(r.id), "saved_location_id": str(r.saved_location_id) if r.saved_location_id else None,
            "saved_route_id": str(r.saved_route_id) if r.saved_route_id else None, "target_name": r.target_name,
            "categories": [] if r.all_categories else list(r.categories), "all_categories": r.all_categories,
            "minimum_severity": r.min_severity, "enabled": r.enabled,
            "subscription_status": "active" if r.enabled else "paused", "created_at": r.created_at.isoformat()}


@router.post("/alert-subscriptions", status_code=201)
def create_subscription(body: SubscriptionIn, response: Response, settings: SettingsDep,
                        token: InstallationToken = None) -> dict:
    if (body.saved_location_id is None) == (body.saved_route_id is None):
        raise validation_error("saved_location_id", "Give exactly one of saved_location_id or saved_route_id.")
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        table, target = (("saved_locations", body.saved_location_id) if body.saved_location_id
                         else ("saved_routes", body.saved_route_id))
        owned = conn.execute(text(f"SELECT 1 FROM subscription.{table} WHERE id = :id AND subscriber_id = :sid"),
                             {"id": target, "sid": sid}).first()
        if owned is None:
            raise _not_found()
        column = "saved_location_id" if body.saved_location_id else "saved_route_id"
        existing = conn.execute(text(f"SELECT id FROM subscription.alert_subscriptions WHERE {column} = :t"),
                                {"t": target}).scalar()
        if existing:
            raise ApiError(409, "already_subscribed", "This place already has alerts set up; update that subscription.")
        new = conn.execute(text(f"""
            INSERT INTO subscription.alert_subscriptions (subscriber_id, {column}, min_severity, enabled)
            VALUES (:sid, :t, :sev, :enabled) RETURNING id"""),
            {"sid": sid, "t": target, "sev": _sev(body.minimum_severity), "enabled": body.enabled}).scalar_one()
        _set_categories(conn, new, body.categories)
        r = conn.execute(text(_SUB_SQL + " AND s.id = :id"), {"sid": sid, "id": new}).one()
    _no_store(response)
    return _subscription(r)


@router.get("/alert-subscriptions")
def list_subscriptions(response: Response, settings: SettingsDep, token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        rows = conn.execute(text(_SUB_SQL + " ORDER BY s.created_at"), {"sid": sid}).all()
    _no_store(response)
    return {"items": [_subscription(r) for r in rows], "next_cursor": None}


@router.patch("/alert-subscriptions/{subscription_id}")
def update_subscription(subscription_id: uuid.UUID, body: SubscriptionPatch, response: Response,
                        settings: SettingsDep, token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        if conn.execute(text("SELECT 1 FROM subscription.alert_subscriptions WHERE id = :id AND subscriber_id = :sid "
                             "FOR UPDATE"), {"id": subscription_id, "sid": sid}).first() is None:
            raise _not_found()
        if body.minimum_severity is not None:
            conn.execute(text("UPDATE subscription.alert_subscriptions SET min_severity = :v WHERE id = :id"),
                         {"v": _sev(body.minimum_severity), "id": subscription_id})
        if body.enabled is not None:
            conn.execute(text("UPDATE subscription.alert_subscriptions SET enabled = :v WHERE id = :id"),
                         {"v": body.enabled, "id": subscription_id})
        if "categories" in body.model_fields_set:
            _set_categories(conn, subscription_id, body.categories)
        r = conn.execute(text(_SUB_SQL + " AND s.id = :id"), {"sid": sid, "id": subscription_id}).one()
    _no_store(response)
    return _subscription(r)


@router.delete("/alert-subscriptions/{subscription_id}", status_code=204)
def delete_subscription(subscription_id: uuid.UUID, settings: SettingsDep, token: InstallationToken = None) -> Response:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        n = conn.execute(text("DELETE FROM subscription.alert_subscriptions WHERE id = :id AND subscriber_id = :sid"),
                         {"id": subscription_id, "sid": sid}).rowcount
    if not n:
        raise _not_found()
    return Response(status_code=204)
