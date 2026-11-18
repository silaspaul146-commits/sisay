"""Public map API (API contract 4, DB spec 5.3 and 7.2). No account required.

Reads only disclosure.public_incidents_v and disclosure.public_incident_removals_v, through the
public database role. Responses are GeoJSON; coordinates are [longitude, latitude] and are the
generalized public point, never the internal or reporter location.
"""
import base64
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime
from sqlalchemy import Connection, text

from app.core.db import public_connection
from app.core.errors import ApiError, validation_error
from app.modules.disclosure.projection_policy import NO_SAFETY_NOTICE, freshness_from_age

router = APIRouter(prefix="/public", tags=["public map"])

MAX_BBOX_DEGREES = 2.0
MAX_RADIUS_KM = 50.0
EMPTY_NOTICE = "No reports have been received for this area. This does not mean the area is safe."

_COLUMNS = """public_id, public_category_code, ST_X(public_location::geometry) AS lon,
              ST_Y(public_location::geometry) AS lat, public_precision_m, public_verification,
              public_lifecycle, public_confidence, public_severity, uncertainty_note,
              public_observed_at, generated_at"""


def _encode_cursor(observed_at: datetime, public_id: uuid.UUID) -> str:
    raw = json.dumps({"t": observed_at.isoformat(), "id": str(public_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise validation_error("cursor", "Invalid pagination cursor.")


def parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        raise validation_error("bbox", "Use west,south,east,north in decimal degrees.")
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= 90 and -90 <= n <= 90):
        raise validation_error("bbox", "Coordinates out of range.")
    if w >= e or s >= n:
        raise validation_error("bbox", "West must be less than east and south less than north. "
                                       "Split boxes that cross the antimeridian.")
    if e - w > MAX_BBOX_DEGREES or n - s > MAX_BBOX_DEGREES:
        raise validation_error("bbox", f"The box may span at most {MAX_BBOX_DEGREES:g} degrees each way.")
    return w, s, e, n


def _feature(row, now: datetime, detail: dict | None = None) -> dict:
    props = {
        "public_id": str(row.public_id),
        "category": row.public_category_code,
        "verification_status": row.public_verification,
        "lifecycle": row.public_lifecycle,
        "severity": row.public_severity,
        "confidence_level": row.public_confidence,
        "freshness_status": freshness_from_age(row.public_observed_at, now),
        "precision_m": row.public_precision_m,
        "uncertainty_note": row.uncertainty_note,
        "observed_at": row.public_observed_at.isoformat(),
        "last_updated_at": row.generated_at.isoformat(),
    }
    if detail:
        props.update(detail)
    return {"type": "Feature", "id": str(row.public_id),
            "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]}, "properties": props}


@router.get("/incidents")
def list_public_incidents(
    response: Response,
    conn: Annotated[Connection, Depends(public_connection)],
    bbox: Annotated[str | None, Query(description="west,south,east,north")] = None,
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[float | None, Query(gt=0, le=MAX_RADIUS_KM)] = None,
    category: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]+$")] = None,
    verification_status: Annotated[str | None, Query(pattern=r"^(unverified|under_review|verified|disputed)$")] = None,
    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: Annotated[AwareDatetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    cursor: str | None = None,
) -> dict:
    point_params = (latitude, longitude, radius_km)
    using_point = any(p is not None for p in point_params)
    if bbox and using_point:
        raise validation_error("bbox", "Use either bbox or latitude/longitude/radius_km, not both.")
    if not bbox and not all(p is not None for p in point_params):
        raise validation_error("bbox", "Provide bbox, or latitude, longitude and radius_km.")

    where, params = [], {"limit": limit + 1}
    if bbox:
        params.update(zip(("w", "s", "e", "n"), parse_bbox(bbox)))
        where.append("public_location && ST_MakeEnvelope(:w, :s, :e, :n, 4326)::geography")
    else:
        params.update({"lat": latitude, "lon": longitude, "radius_m": radius_km * 1000})
        where.append("ST_DWithin(public_location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius_m)")
    if category:
        where.append("public_category_code = :category")
        params["category"] = category
    if verification_status:
        where.append("public_verification = :verification")
        params["verification"] = verification_status
    if from_:
        where.append("public_observed_at >= :from_ts")
        params["from_ts"] = from_
    if to:
        where.append("public_observed_at <= :to_ts")
        params["to_ts"] = to
    if cursor:
        params["c_t"], params["c_id"] = _decode_cursor(cursor)
        where.append("(public_observed_at, public_id) < (:c_t, :c_id)")

    rows = conn.execute(text(f"""
        SELECT {_COLUMNS} FROM disclosure.public_incidents_v
        WHERE {' AND '.join(where)}
        ORDER BY public_observed_at DESC, public_id DESC
        LIMIT :limit
    """), params).all()

    now = datetime.now(UTC)
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].public_observed_at, rows[-1].public_id)
    response.headers["Cache-Control"] = "public, max-age=30"
    return {
        "type": "FeatureCollection",
        "features": [_feature(r, now) for r in rows],
        "next_cursor": next_cursor,
        "notice": NO_SAFETY_NOTICE if rows else EMPTY_NOTICE,
        "generated_at": now.isoformat(),
    }


@router.get("/incidents/removals")
def list_public_removals(
    conn: Annotated[Connection, Depends(public_connection)],
    since: Annotated[AwareDatetime, Query(description="Return removals after this time (max 7 days back)")],
) -> dict:
    """Offline map caches use this to drop incidents that are no longer public. Exposes ids and
    times only, nothing about why an incident was removed."""
    rows = conn.execute(
        text("""SELECT public_id, removed_at FROM disclosure.public_incident_removals_v
                WHERE removed_at > :since ORDER BY removed_at LIMIT 5000"""),
        {"since": since},
    ).all()
    return {"items": [{"public_id": str(r.public_id), "removed_at": r.removed_at.isoformat()} for r in rows]}


@router.get("/incidents/{public_id}")
def get_public_incident(public_id: uuid.UUID, response: Response,
                        conn: Annotated[Connection, Depends(public_connection)]) -> dict:
    row = conn.execute(
        text(f"""SELECT {_COLUMNS}, public_description,
                        CASE WHEN public_area IS NULL THEN NULL ELSE ST_AsGeoJSON(public_area)::json END AS area
                 FROM disclosure.public_incidents_v WHERE public_id = :pid"""),
        {"pid": public_id},
    ).first()
    if row is None:
        raise ApiError(404, "resource_not_found", "The incident is not available.")
    response.headers["Cache-Control"] = "public, max-age=30"
    feature = _feature(row, datetime.now(UTC), {"description": row.public_description, "affected_area": row.area})
    feature["notice"] = NO_SAFETY_NOTICE
    return feature
