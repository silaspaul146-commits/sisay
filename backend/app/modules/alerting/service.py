"""Alert engine (Engineering pack 7.4, DB spec 4.9, 5.4, 8.1). Runs in the worker only.

evaluate_incident  incident changed -> create / update / withdraw / end / expire its alert
fan_out            a published alert version -> inbox rows per subscriber, push deliveries per device

Every alert change writes a new alert_versions row (history is append-only) and, when the
distribution level changes, an alert_distribution_decisions row explaining why. Fan-out is
idempotent: inbox and delivery rows have natural unique keys, so a retried event adds nothing.
"""
import json
import logging
import uuid

from sqlalchemy import Connection, text

from app.infrastructure.audit import audit
from app.infrastructure.outbox.outbox import enqueue, enqueue_unless_pending
from app.modules.alerting.policy import POLICY_VERSION, CurrentAlert, Decision, IncidentState, decide
from app.shared.ids import new_id

log = logging.getLogger(__name__)

_STATE_SQL = text("""
    SELECT i.id, i.category_id, c.code AS category_code, c.name AS category_name, c.default_severity,
           c.match_radius_m, c.match_time_window, i.severity, i.verification_status, i.operational_status,
           i.location_uncertainty_m, i.last_observed_at, p.min_alert_radius_m, p.review_before_publish,
           p.public_grid_m, now() AS now,
           EXISTS (SELECT 1 FROM review.review_items r
                   WHERE r.item_type = 'publication_review' AND r.incident_id = i.id
                     AND r.status = 'resolved' AND r.resolution = 'approved') AS publication_approved
    FROM incident.incidents i
    JOIN ref.incident_categories c ON c.id = i.category_id
    JOIN ref.disclosure_policies p ON p.id = c.disclosure_policy_id
    WHERE i.id = :iid
""")


def evaluate_incident(conn: Connection, incident_id: uuid.UUID) -> str:
    # One evaluation per incident at a time: parallel workers would otherwise race to create.
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"alert:{incident_id}"})
    src = conn.execute(_STATE_SQL, {"iid": incident_id}).first()
    if src is None:
        return "unknown_incident"
    state = IncidentState(
        category_code=src.category_code, category_name=src.category_name, default_severity=src.default_severity,
        severity=src.severity, verification_status=src.verification_status,
        operational_status=src.operational_status, location_uncertainty_m=src.location_uncertainty_m,
        last_observed_at=src.last_observed_at, match_radius_m=src.match_radius_m,
        match_time_window=src.match_time_window, min_alert_radius_m=src.min_alert_radius_m,
        review_before_publish=src.review_before_publish, publication_approved=src.publication_approved)
    row = conn.execute(text("""
        SELECT a.id, a.status, a.distribution_level, a.expires_at, a.current_version_number, v.message
        FROM alerting.alerts a
        JOIN alerting.alert_versions v ON v.alert_id = a.id AND v.version_number = a.current_version_number
        WHERE a.incident_id = :iid ORDER BY a.created_at DESC LIMIT 1 FOR UPDATE OF a
    """), {"iid": incident_id}).first()
    current = CurrentAlert(row.status, row.distribution_level, row.message, row.expires_at) if row else None
    d = decide(state, current, src.now)

    if d.action == "none":
        return "none"
    if d.action == "create":
        alert_id = new_id()
        conn.execute(text("""
            INSERT INTO alerting.alerts (id, incident_id, category_id, current_version_number, distribution_level,
                                         geographic_scope, status, distribution_reason, uncertainty_message, expires_at)
            SELECT :id, i.id, i.category_id, 1, :level,
                   ST_Multi(ST_Buffer(i.canonical_location, :radius)::geometry)::geography,
                   'active', :reason, :uncertainty, :expires
            FROM incident.incidents i WHERE i.id = :iid
        """), {"id": alert_id, "iid": incident_id, "level": d.level, "radius": d.radius_m, "reason": d.reason,
               "uncertainty": d.uncertainty, "expires": d.expires_at})
        _new_version(conn, alert_id, 1, d, src, previous_level=None)
        return "created"

    alert_id, version = row.id, row.current_version_number + 1
    if d.action == "refresh":
        conn.execute(text("""
            UPDATE alerting.alerts a
            SET expires_at = :expires, geographic_scope = ST_Multi(ST_Buffer(i.canonical_location, :radius)::geometry)::geography
            FROM incident.incidents i WHERE a.id = :id AND i.id = a.incident_id
        """), {"id": alert_id, "expires": d.expires_at, "radius": d.radius_m})
        return "refreshed"

    if d.action == "update":
        conn.execute(text("""
            UPDATE alerting.alerts a
            SET distribution_level = :level, distribution_reason = :reason, uncertainty_message = :uncertainty,
                expires_at = :expires, current_version_number = :v,
                geographic_scope = ST_Multi(ST_Buffer(i.canonical_location, :radius)::geometry)::geography
            FROM incident.incidents i WHERE a.id = :id AND i.id = a.incident_id
        """), {"id": alert_id, "level": d.level, "reason": d.reason, "uncertainty": d.uncertainty,
               "expires": d.expires_at, "v": version, "radius": d.radius_m})
    else:  # withdraw | over | expire
        conn.execute(text("""
            UPDATE alerting.alerts SET status = :status, uncertainty_message = :uncertainty,
                   current_version_number = :v WHERE id = :id
        """), {"id": alert_id, "status": d.status, "uncertainty": d.uncertainty, "v": version})
        if d.action == "withdraw":
            audit(conn, action="alert.withdraw", resource_type="alert", resource_id=alert_id, actor_type="worker",
                  metadata={"reason": d.reason})
    _new_version(conn, alert_id, version, d, src, previous_level=row.distribution_level)
    return {"update": "updated", "withdraw": "withdrawn", "over": "ended", "expire": "expired"}[d.action]


def _new_version(conn: Connection, alert_id: uuid.UUID, number: int, d: Decision, src, previous_level: str | None) -> None:
    version_id = new_id()
    level = d.level or previous_level
    conn.execute(text("""
        INSERT INTO alerting.alert_versions
          (id, alert_id, version_number, message, uncertainty_message, geographic_scope, distribution_level,
           change_reason, actor_type, category_code, verification_status, severity, status, notify,
           public_point, public_precision_m, policy_version)
        SELECT :vid, a.id, :n, :message, :uncertainty, a.geographic_scope, :level, :reason, 'worker', :cat,
               :verification, :severity, :status, :notify,
               disclosure.snap_public_point(i.canonical_location, :grid), :grid, :policy
        FROM alerting.alerts a JOIN incident.incidents i ON i.id = a.incident_id WHERE a.id = :aid
    """), {"vid": version_id, "aid": alert_id, "n": number, "message": d.message, "uncertainty": d.uncertainty,
           "level": level, "reason": d.reason, "cat": src.category_code, "verification": src.verification_status,
           "severity": d.effective_severity or src.severity, "status": d.status, "notify": d.notify,
           "grid": src.public_grid_m, "policy": POLICY_VERSION})
    new_level = "withdrawn" if d.action == "withdraw" else level
    if new_level != previous_level:
        conn.execute(text("""
            INSERT INTO alerting.alert_distribution_decisions
              (id, alert_id, alert_version_id, previous_level, new_level, reason, decision_source, inputs, actor_type)
            VALUES (:id, :aid, :vid, :prev, :new, :reason, :source, CAST(:inputs AS jsonb), 'worker')
        """), {"id": new_id(), "aid": alert_id, "vid": version_id, "prev": previous_level, "new": new_level,
               "reason": d.reason, "source": "expiry_job" if d.action == "expire" else "policy_engine",
               "inputs": json.dumps({"verification": src.verification_status, "severity": src.severity,
                                     "effective_severity": d.effective_severity, "policy": POLICY_VERSION})})
    enqueue(conn, "alert", alert_id, "alert.version_published",
            {"alert_id": str(alert_id), "alert_version_id": str(version_id), "notify": d.notify})


# --- Fan-out ------------------------------------------------------------------------------------

_MATCH_SQL = """
    WITH a AS (
      SELECT al.id, al.geographic_scope, al.category_id, v.severity, p.min_alert_radius_m AS min_r
      FROM alerting.alerts al
      JOIN alerting.alert_versions v ON v.id = :vid
      JOIN ref.incident_categories c ON c.id = al.category_id
      JOIN ref.disclosure_policies p ON p.id = c.disclosure_policy_id
      WHERE al.id = :aid
    ), matched AS (
      SELECT s.id AS subscription_id, s.subscriber_id
      FROM a
      JOIN subscription.saved_locations sl
        ON ST_DWithin(sl.location, a.geographic_scope, 50000)
       AND ST_DWithin(sl.location, a.geographic_scope, GREATEST(sl.radius_m, a.min_r))
      JOIN subscription.alert_subscriptions s ON s.saved_location_id = sl.id
      WHERE sl.enabled AND s.enabled
        AND ops.severity_rank(a.severity) >= ops.severity_rank(s.min_severity)
        AND (s.all_categories OR EXISTS (SELECT 1 FROM subscription.alert_subscription_categories sc
                                          WHERE sc.subscription_id = s.id AND sc.category_id = a.category_id))
      UNION ALL
      SELECT s.id, s.subscriber_id
      FROM a
      JOIN subscription.saved_routes r
        ON ST_DWithin(r.route_geometry, a.geographic_scope, 10000)
       AND ST_DWithin(r.route_geometry, a.geographic_scope, GREATEST(r.corridor_width_m / 2.0, a.min_r))
      JOIN subscription.alert_subscriptions s ON s.saved_route_id = r.id
      WHERE r.enabled AND s.enabled
        AND ops.severity_rank(a.severity) >= ops.severity_rank(s.min_severity)
        AND (s.all_categories OR EXISTS (SELECT 1 FROM subscription.alert_subscription_categories sc
                                          WHERE sc.subscription_id = s.id AND sc.category_id = a.category_id))
    )
"""


def fan_out(conn: Connection, alert_id: uuid.UUID, version_id: uuid.UUID, notify: bool) -> tuple[int, int]:
    """Returns (inbox rows added, push deliveries queued)."""
    status = conn.execute(text("SELECT status FROM alerting.alert_versions WHERE id = :vid"), {"vid": version_id}).scalar_one()
    previous = """SELECT DISTINCT ON (subscriber_id) subscription_id, subscriber_id FROM alerting.alert_inbox
                  WHERE alert_id = :aid AND alert_version_id <> :vid"""
    if status == "active":
        # New and earlier recipients: an update must reach whoever got the first warning.
        source = _MATCH_SQL + f", everyone AS (SELECT * FROM matched UNION ALL {previous}) "
        pick = "SELECT DISTINCT ON (subscriber_id) subscriber_id, subscription_id FROM everyone"
    else:
        # Withdrawn / over / expired: only the people who were warned.
        source = f"WITH everyone AS ({previous}) "
        pick = "SELECT subscriber_id, subscription_id FROM everyone"
    added = conn.execute(text(source + f"""
        INSERT INTO alerting.alert_inbox (alert_id, alert_version_id, subscriber_id, subscription_id)
        SELECT :aid, :vid, subscriber_id, subscription_id FROM ({pick}) x
        ON CONFLICT (alert_version_id, subscriber_id) DO NOTHING
    """), {"aid": alert_id, "vid": version_id}).rowcount
    queued = 0
    if notify:
        queued = conn.execute(text("""
            INSERT INTO alerting.alert_deliveries (alert_id, alert_version_id, subscriber_id, subscription_id, endpoint_id)
            SELECT ib.alert_id, ib.alert_version_id, ib.subscriber_id, ib.subscription_id, e.id
            FROM alerting.alert_inbox ib
            JOIN subscription.subscriber_principals sp ON sp.id = ib.subscriber_id
            JOIN identity.push_endpoints e ON e.installation_id = sp.installation_id AND e.status = 'active'
            WHERE ib.alert_version_id = :vid
            ON CONFLICT (alert_version_id, endpoint_id) DO NOTHING
        """), {"vid": version_id}).rowcount
    return added, queued


def enqueue_expiry_sweep(conn: Connection, limit: int = 1000) -> int:
    """Periodic: alerts past their expiry get re-evaluated (and so expire, or are refreshed)."""
    ids = conn.execute(text("""SELECT incident_id FROM alerting.alerts
                               WHERE status = 'active' AND expires_at <= now() LIMIT :n"""), {"n": limit}).scalars().all()
    return sum(enqueue_unless_pending(conn, "incident", iid, "alert.evaluate", {"incident_id": str(iid)}) for iid in ids)
