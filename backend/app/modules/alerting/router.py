"""Alert routes. Citizens (API contract 10): the installation's own alert list, read from the inbox the
fan-out worker writes, so it works with or without push. They see only alert snapshots: wording,
status and a location snapped to the category's public grid; never the internal incident.
Staff (API contract 11.2): which alerts an incident produced and how many people they reached."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text

from app.core.auth import Principal, require
from app.core.db import get_dashboard_engine, get_engine
from app.core.errors import ApiError
from app.modules.subscriptions.installation_auth import InstallationToken, SettingsDep, authenticate, subscriber_id
from app.shared.cursor import decode_cursor, encode_cursor

router = APIRouter(tags=["alerts"])
LEVEL_NUMBER = {"internal": 0, "subscribers": 1, "priority": 2}

# Latest version this subscriber received for each alert, plus why they got it.
_FEED_SQL = """
    WITH latest AS (
      SELECT DISTINCT ON (ib.alert_id) ib.alert_id, ib.alert_version_id, ib.subscription_id, ib.created_at,
             ib.acknowledged_at
      FROM alerting.alert_inbox ib WHERE ib.subscriber_id = :sid
      ORDER BY ib.alert_id, ib.created_at DESC
    ), first_seen AS (
      SELECT alert_id, min(created_at) AS issued_at FROM alerting.alert_inbox WHERE subscriber_id = :sid GROUP BY alert_id
    )
    SELECT l.alert_id, l.created_at AS updated_at, l.acknowledged_at, f.issued_at, v.version_number, v.message,
           v.uncertainty_message, v.distribution_level, v.category_code, v.verification_status, v.severity,
           v.status AS version_status, v.public_precision_m, a.expires_at, a.status AS alert_status,
           ST_Y(v.public_point::geometry) AS lat, ST_X(v.public_point::geometry) AS lon,
           COALESCE(sl.name, sr.name) AS because_of, CASE WHEN sr.id IS NOT NULL THEN 'route' ELSE 'place' END AS because_kind
    FROM latest l
    JOIN first_seen f ON f.alert_id = l.alert_id
    JOIN alerting.alert_versions v ON v.id = l.alert_version_id
    JOIN alerting.alerts a ON a.id = l.alert_id
    LEFT JOIN subscription.alert_subscriptions s ON s.id = l.subscription_id
    LEFT JOIN subscription.saved_locations sl ON sl.id = s.saved_location_id
    LEFT JOIN subscription.saved_routes sr ON sr.id = s.saved_route_id
"""


def _feed_item(r) -> dict:
    status = r.version_status or r.alert_status
    if status == "active" and r.alert_status != "active":
        status = r.alert_status  # e.g. expired after this version was sent
    return {
        "id": str(r.alert_id), "category": r.category_code, "message": r.message,
        "uncertainty": r.uncertainty_message, "status": status,
        "distribution_level": LEVEL_NUMBER.get(r.distribution_level, 1),
        "verification_status": r.verification_status, "severity": r.severity, "version": r.version_number,
        "location": ({"latitude": r.lat, "longitude": r.lon, "precision_m": r.public_precision_m}
                     if r.lat is not None else None),
        "because": ({"kind": r.because_kind, "name": r.because_of} if r.because_of else None),
        "issued_at": r.issued_at.isoformat(), "updated_at": r.updated_at.isoformat(),
        "expires_at": r.expires_at.isoformat(), "acknowledged": r.acknowledged_at is not None,
    }


@router.get("/alerts")
def list_alerts(response: Response, settings: SettingsDep, token: InstallationToken = None,
                limit: Annotated[int, Query(ge=1, le=100)] = 30, cursor: str | None = None) -> dict:
    params: dict = {"limit": limit + 1}
    where = ""
    if cursor:
        params["c_t"], params["c_id"] = decode_cursor(cursor)
        where = "WHERE (l.created_at, l.alert_id) < (:c_t, :c_id)"
    with get_engine().begin() as conn:
        params["sid"] = subscriber_id(conn, authenticate(conn, token, settings))
        rows = conn.execute(text(_FEED_SQL + where + " ORDER BY l.created_at DESC, l.alert_id DESC LIMIT :limit"),
                            params).all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].updated_at, rows[-1].alert_id)
    response.headers["Cache-Control"] = "no-store"
    return {"items": [_feed_item(r) for r in rows], "next_cursor": next_cursor}


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: uuid.UUID, response: Response, settings: SettingsDep, token: InstallationToken = None) -> dict:
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        r = conn.execute(text(_FEED_SQL + " WHERE l.alert_id = :aid"), {"sid": sid, "aid": alert_id}).first()
        if r is None:
            raise ApiError(404, "resource_not_found", "The resource was not found.")
        updates = conn.execute(text("""
            SELECT v.version_number, v.message, v.status, v.verification_status, ib.created_at
            FROM alerting.alert_inbox ib JOIN alerting.alert_versions v ON v.id = ib.alert_version_id
            WHERE ib.subscriber_id = :sid AND ib.alert_id = :aid ORDER BY ib.created_at
        """), {"sid": sid, "aid": alert_id}).all()
    response.headers["Cache-Control"] = "no-store"
    return {**_feed_item(r), "updates": [
        {"version": u.version_number, "message": u.message, "status": u.status,
         "verification_status": u.verification_status, "received_at": u.created_at.isoformat()} for u in updates]}


@router.post("/alerts/{alert_id}/acknowledgements", status_code=201)
def acknowledge(alert_id: uuid.UUID, response: Response, settings: SettingsDep, token: InstallationToken = None) -> dict:
    """Confirms the person saw it. It never confirms the incident (API contract 10.6)."""
    with get_engine().begin() as conn:
        sid = subscriber_id(conn, authenticate(conn, token, settings))
        at = conn.execute(text("""
            UPDATE alerting.alert_inbox SET acknowledged_at = COALESCE(acknowledged_at, now())
            WHERE subscriber_id = :sid AND alert_id = :aid RETURNING acknowledged_at
        """), {"sid": sid, "aid": alert_id}).scalars().all()
    if not at:
        raise ApiError(404, "resource_not_found", "The resource was not found.")
    response.headers["Cache-Control"] = "no-store"
    return {"alert_id": str(alert_id), "acknowledged": True, "acknowledged_at": max(at).isoformat()}


# --- Staff -----------------------------------------------------------------------------------------

@router.get("/incidents/{incident_id}/alerts")
def incident_alerts(incident_id: uuid.UUID, response: Response,
                    _: Annotated[Principal, Depends(require("incident.view"))]) -> dict:
    with get_dashboard_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT a.id, a.status, a.distribution_level, a.created_at, a.expires_at, a.current_version_number,
                   v.message, v.uncertainty_message,
                   (SELECT count(DISTINCT subscriber_id) FROM alerting.alert_inbox ib WHERE ib.alert_id = a.id) AS people,
                   (SELECT count(*) FROM alerting.alert_deliveries d WHERE d.alert_id = a.id) AS pushes
            FROM alerting.alerts a
            JOIN alerting.alert_versions v ON v.alert_id = a.id AND v.version_number = a.current_version_number
            WHERE a.incident_id = :iid ORDER BY a.created_at DESC
        """), {"iid": incident_id}).all()
        versions = conn.execute(text("""
            SELECT v.alert_id, v.version_number, v.message, v.status, v.distribution_level, v.change_reason,
                   v.notify, v.created_at
            FROM alerting.alert_versions v JOIN alerting.alerts a ON a.id = v.alert_id
            WHERE a.incident_id = :iid ORDER BY v.created_at
        """), {"iid": incident_id}).all()
    response.headers["Cache-Control"] = "no-store"
    return {"items": [{
        "id": str(r.id), "status": r.status, "distribution_level": LEVEL_NUMBER.get(r.distribution_level, 1),
        "distribution_level_code": r.distribution_level, "message": r.message, "uncertainty": r.uncertainty_message,
        "issued_at": r.created_at.isoformat(), "expires_at": r.expires_at.isoformat(), "version": r.current_version_number,
        "people_reached": r.people, "push_messages": r.pushes,
        "versions": [{"version": v.version_number, "message": v.message, "status": v.status,
                      "distribution_level_code": v.distribution_level, "reason": v.change_reason,
                      "notified": v.notify, "created_at": v.created_at.isoformat()}
                     for v in versions if v.alert_id == r.id]} for r in rows], "next_cursor": None}
