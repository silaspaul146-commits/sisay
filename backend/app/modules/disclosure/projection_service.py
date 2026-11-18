"""Public projection generation (DB spec 7.1, 8.1) and fail-closed restriction (A-1).

`refresh_projection` is a pure function of the incident, its category, the category's disclosure
policy and the current time. Unchanged results write nothing; material changes bump the version
and append history in the same transaction.

`restrict_projection` must be called in the same transaction as any change that could make the
current public data unsafe (category, location, area or policy change; rejection; withdrawal;
merge). It removes the incident from the public views immediately and queues regeneration.
"""
import logging
import uuid

from sqlalchemy import Connection, text

from app.infrastructure.outbox.outbox import enqueue, enqueue_unless_pending
from app.modules.disclosure.projection_policy import (
    IncidentFacts,
    PolicyFacts,
    content_hash,
    eligibility,
    public_lifecycle,
    publication_state,
    uncertainty_note,
)
from app.shared.ids import new_id

log = logging.getLogger(__name__)

_SOURCE_SQL = text("""
    SELECT i.id, i.description, i.verification_status, i.operational_status, i.confidence_level,
           i.severity, i.created_at, i.last_observed_at, i.lock_version, i.affected_area IS NOT NULL AS has_area,
           c.code AS category_code,
           p.id AS policy_id, p.public_grid_m, p.public_location_mode, p.publish_on_map, p.publish_description,
           p.publish_affected_area, p.review_before_publish, p.public_delay, p.max_public_age,
           ST_X(disclosure.snap_public_point(i.canonical_location, p.public_grid_m)::geometry) AS public_lon,
           ST_Y(disclosure.snap_public_point(i.canonical_location, p.public_grid_m)::geometry) AS public_lat,
           CASE WHEN p.publish_affected_area AND i.affected_area IS NOT NULL THEN
             ST_AsText(ST_Multi(ST_SimplifyPreserveTopology(i.affected_area::geometry, p.public_grid_m / 111320.0)))
           END AS public_area_wkt,
           date_bin('15 minutes', i.last_observed_at, timestamptz '2000-01-01') AS public_observed_at,
           now() AS now
    FROM   incident.incidents i
    JOIN   ref.incident_categories c ON c.id = i.category_id
    JOIN   ref.disclosure_policies p ON p.id = c.disclosure_policy_id
    WHERE  i.id = :iid
    FOR SHARE OF i
""")


def refresh_projection(conn: Connection, incident_id: uuid.UUID, trigger_reason: str) -> str:
    src = conn.execute(_SOURCE_SQL, {"iid": incident_id}).first()
    if src is None:
        log.warning("projection.refresh for unknown incident", extra={"incident_id": incident_id})
        return "missing"

    policy = PolicyFacts(src.policy_id, src.public_grid_m, src.public_location_mode, src.publish_on_map,
                         src.publish_description, src.publish_affected_area, src.review_before_publish,
                         src.public_delay, src.max_public_age)
    facts = IncidentFacts(src.operational_status, src.verification_status, src.created_at, src.last_observed_at)
    approved = policy.review_before_publish and _publication_review_approved(conn, incident_id, src)
    visible, reason = eligibility(facts, policy, src.now, approved)
    state = publication_state(visible, reason)
    lifecycle = public_lifecycle(src.operational_status, src.verification_status)

    fields = {
        "is_visible": visible,
        "publication_state": state,
        "category": src.category_code,
        # Never publish a location for something that is not visible.
        "lon": round(src.public_lon, 7) if visible else None,
        "lat": round(src.public_lat, 7) if visible else None,
        "precision_m": policy.public_grid_m,
        "area_wkt": src.public_area_wkt if visible else None,
        # Only staff-written incident text, never report free text (provisional incidents have none).
        "description": (src.description[:1000] if policy.publish_description and src.description and visible
                        else None),
        "verification": src.verification_status,
        "lifecycle": lifecycle,
        "confidence": src.confidence_level,
        "severity": src.severity,
        "note": uncertainty_note(src.verification_status, src.confidence_level, policy.public_grid_m),
        "observed_at": src.public_observed_at.isoformat(),
        "policy_id": policy.id,
    }
    digest = content_hash(fields)

    current = conn.execute(
        text("""SELECT version, content_hash, publication_state
                FROM disclosure.public_incident_projections WHERE incident_id = :iid FOR UPDATE"""),
        {"iid": incident_id},
    ).first()
    if current is not None and bytes(current.content_hash) == digest and current.publication_state == state:
        return "unchanged"

    params = {
        "iid": incident_id, "visible": visible, "state": state, "lock_version": src.lock_version,
        "category": src.category_code, "lon": fields["lon"], "lat": fields["lat"],
        "precision": policy.public_grid_m, "area_wkt": fields["area_wkt"], "description": fields["description"],
        "verification": src.verification_status, "lifecycle": lifecycle, "confidence": src.confidence_level,
        "severity": src.severity, "note": fields["note"], "observed_at": src.public_observed_at,
        "policy_id": policy.id, "hash": digest,
    }
    location_expr = ("CASE WHEN CAST(:lon AS float8) IS NULL THEN NULL "
                     "ELSE ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography END")
    area_expr = ("CASE WHEN CAST(:area_wkt AS text) IS NULL THEN NULL "
                 "ELSE ST_GeogFromText('SRID=4326;' || :area_wkt) END")
    if current is None:
        # id is left to gen_random_uuid(): the public id must be v4, never a time-ordered v7.
        conn.execute(text(f"""
            INSERT INTO disclosure.public_incident_projections
              (incident_id, version, is_visible, publication_state, source_lock_version, public_category_code,
               public_location, public_precision_m, public_area, public_description, public_verification,
               public_lifecycle, public_confidence, public_severity, uncertainty_note, public_observed_at,
               disclosure_policy_id, content_hash)
            VALUES (:iid, 1, :visible, :state, :lock_version, :category, {location_expr}, :precision, {area_expr},
                    :description, :verification, :lifecycle, :confidence, :severity, :note, :observed_at,
                    :policy_id, :hash)
        """), params)
    else:
        conn.execute(text(f"""
            UPDATE disclosure.public_incident_projections
            SET    version = version + 1, is_visible = :visible, publication_state = :state,
                   restricted_reason = NULL, source_lock_version = :lock_version,
                   public_category_code = :category, public_location = {location_expr},
                   public_precision_m = :precision, public_area = {area_expr}, public_description = :description,
                   public_verification = :verification, public_lifecycle = :lifecycle,
                   public_confidence = :confidence, public_severity = :severity, uncertainty_note = :note,
                   public_observed_at = :observed_at, disclosure_policy_id = :policy_id,
                   content_hash = :hash, generated_at = now()
            WHERE  incident_id = :iid
        """), params)

    conn.execute(
        text("""
            INSERT INTO disclosure.public_incident_projection_history
              (incident_id, version, is_visible, publication_state, source_lock_version, public_category_code,
               public_location, public_precision_m, public_area, public_description, public_verification,
               public_lifecycle, public_confidence, public_severity, uncertainty_note, public_observed_at,
               disclosure_policy_id, content_hash, generated_at, trigger_reason)
            SELECT incident_id, version, is_visible, publication_state, source_lock_version, public_category_code,
                   public_location, public_precision_m, public_area, public_description, public_verification,
                   public_lifecycle, public_confidence, public_severity, uncertainty_note, public_observed_at,
                   disclosure_policy_id, content_hash, generated_at, :reason
            FROM   disclosure.public_incident_projections WHERE incident_id = :iid
        """),
        {"iid": incident_id, "reason": f"{trigger_reason}:{reason}"},
    )
    return state


def _publication_review_approved(conn: Connection, incident_id: uuid.UUID, src) -> bool:
    approved = conn.execute(
        text("""SELECT 1 FROM review.review_items
                WHERE incident_id = :iid AND item_type = 'publication_review'
                  AND status = 'resolved' AND resolution = 'approved' LIMIT 1"""),
        {"iid": incident_id},
    ).first()
    if approved:
        return True
    rejected = conn.execute(
        text("""SELECT 1 FROM review.review_items
                WHERE incident_id = :iid AND item_type = 'publication_review'
                  AND status = 'resolved' AND resolution = 'rejected' LIMIT 1"""),
        {"iid": incident_id},
    ).first()
    # Make sure reviewers see it: open a publication review if none is pending, unless a reviewer
    # already refused publication (otherwise every freshness sweep would reopen it).
    if not rejected and public_lifecycle(src.operational_status, src.verification_status) != "removed":
        conn.execute(
            text("""INSERT INTO review.review_items (id, item_type, incident_id, priority)
                    VALUES (:id, 'publication_review', :iid, 2) ON CONFLICT DO NOTHING"""),
            {"id": new_id(), "iid": incident_id},
        )
    return False


def restrict_projection(conn: Connection, incident_id: uuid.UUID, reason: str) -> None:
    """Fail closed, in the caller's transaction. Only the worker republishes."""
    conn.execute(
        text("""UPDATE disclosure.public_incident_projections
                SET publication_state = 'restricted', restricted_reason = :reason, generated_at = now()
                WHERE incident_id = :iid"""),
        {"iid": incident_id, "reason": reason},
    )
    enqueue(conn, "incident", incident_id, "projection.refresh", {"incident_id": str(incident_id), "reason": reason})


def enqueue_freshness_sweep(conn: Connection, limit: int = 1000) -> int:
    """Periodic job: re-evaluate projections whose eligibility depends on time (publication delay,
    maximum public age)."""
    ids = conn.execute(
        text("""
            SELECT i.id
            FROM   incident.incidents i
            LEFT JOIN disclosure.public_incident_projections p ON p.incident_id = i.id
            WHERE  (i.operational_status IN ('active','monitoring') AND i.last_observed_at > now() - interval '8 days')
               OR  p.publication_state = 'pending'
               OR  (p.is_visible AND p.publication_state = 'published')
            ORDER  BY i.last_observed_at DESC
            LIMIT  :limit
        """),
        {"limit": limit},
    ).scalars().all()
    return sum(enqueue_unless_pending(conn, "incident", iid, "projection.refresh",
                                      {"incident_id": str(iid), "reason": "freshness_sweep"}) for iid in ids)
