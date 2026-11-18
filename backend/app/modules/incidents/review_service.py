"""Staff decisions on incidents and reports (API contract 5, DB spec 4.4-4.6, 6.5, 8.1).

Every write runs in one transaction with its history row, audit row and outbox event. Lock order
is always reports first, then incidents in ascending id order, matching the worker's matching
transaction so the two cannot deadlock.

Rules from the specs:
- Verification is recorded as an authoritative assessment and mirrored on the incident (A-3).
- A rejected or merged incident leaves the public map in the same transaction (fail closed, A-1).
- Association changes always write report_association_history (the deferred trigger enforces it).
- A merge moves every report with merge_reassign, records merged_into, and never deletes anything.
"""
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Connection, text

from app.core.auth import Principal
from app.core.errors import ApiError, validation_error
from app.infrastructure.audit import audit
from app.infrastructure.outbox.outbox import enqueue
from app.modules.disclosure.projection_service import restrict_projection
from app.shared.ids import new_id

CLOSED_FOR_CHANGES = ("merged", "withdrawn")
ASSESSMENT_COLUMNS = {"severity": "severity", "confidence": "confidence_level", "freshness": "freshness_status"}
ASSESSMENT_VALUES = {"severity": ("unknown", "low", "moderate", "high", "critical"),
                     "confidence": ("low", "medium", "high"),
                     "freshness": ("current", "aging", "stale", "expired")}


def _not_found() -> ApiError:
    return ApiError(404, "resource_not_found", "The resource was not found.")


def _conflict(message: str, code: str = "invalid_state_transition") -> ApiError:
    return ApiError(409, code, message)


def _lock_incidents(conn: Connection, ids: list[uuid.UUID]) -> dict[uuid.UUID, object]:
    rows = {}
    for iid in sorted(set(ids)):
        row = conn.execute(
            text("""SELECT id, operational_status, verification_status, merged_into_incident_id, lock_version
                    FROM incident.incidents WHERE id = :id FOR UPDATE"""),
            {"id": iid},
        ).first()
        if row is None:
            raise _not_found()
        rows[iid] = row
    return rows


def _refresh(conn: Connection, incident_id: uuid.UUID, reason: str) -> None:
    enqueue(conn, "incident", incident_id, "projection.refresh", {"incident_id": str(incident_id), "reason": reason})


def _bump(conn: Connection, incident_id: uuid.UUID) -> datetime:
    return conn.execute(
        text("UPDATE incident.incidents SET lock_version = lock_version + 1 WHERE id = :id RETURNING updated_at"),
        {"id": incident_id},
    ).scalar_one()


def _resolve_items(conn: Connection, principal: Principal, resolution: str, *, item_type: str,
                   report_id: uuid.UUID | None = None, incident_id: uuid.UUID | None = None) -> None:
    conn.execute(
        text(f"""UPDATE review.review_items
                 SET status = 'resolved', resolution = :resolution, resolved_by = :uid, resolved_at = now()
                 WHERE item_type = :type AND status IN ('open','claimed')
                   AND {'report_id = :target' if report_id else 'incident_id = :target'}"""),
        {"resolution": resolution, "uid": principal.user_id, "type": item_type, "target": report_id or incident_id},
    )


# --- Verification and assessments ------------------------------------------------------------

@dataclass(frozen=True)
class VerificationResult:
    incident_id: uuid.UUID
    previous_status: str
    verification_status: str
    decision_recorded: bool
    updated_at: datetime


def verify_incident(conn: Connection, principal: Principal, incident_id: uuid.UUID, decision: str,
                    reason: str) -> VerificationResult:
    inc = _lock_incidents(conn, [incident_id])[incident_id]
    if inc.operational_status in CLOSED_FOR_CHANGES:
        raise _conflict("A merged or withdrawn incident cannot be verified.")
    previous = inc.verification_status

    conn.execute(
        text("""INSERT INTO incident.incident_assessments
                  (id, incident_id, assessment_type, assessment_value, rationale, assessor_id, actor_type,
                   source, is_authoritative)
                VALUES (:id, :iid, 'verification', :value, :reason, :uid, 'user', 'reviewer', true)"""),
        {"id": new_id(), "iid": incident_id, "value": decision, "reason": reason, "uid": principal.user_id},
    )
    conn.execute(
        text("""UPDATE incident.incidents SET verification_status = :value, is_provisional = false
                WHERE id = :iid"""),
        {"value": decision, "iid": incident_id},
    )
    updated_at = _bump(conn, incident_id)
    if decision == "rejected":
        restrict_projection(conn, incident_id, "verification rejected")  # off the map now, not after the worker
    else:
        _refresh(conn, incident_id, "verification_changed")
    _resolve_items(conn, principal, decision, item_type="incident_verification", incident_id=incident_id)
    audit(conn, action="incident.verify", resource_type="incident", resource_id=incident_id, actor_type="user",
          actor_id=principal.user_id, metadata={"previous": previous, "new": decision})
    return VerificationResult(incident_id, previous, decision, True, updated_at)


def assess_incident(conn: Connection, principal: Principal, incident_id: uuid.UUID, assessment_type: str,
                    value: str, rationale: str | None) -> tuple[uuid.UUID, datetime]:
    if assessment_type == "verification":
        raise validation_error("assessment_type", "Use POST /incidents/{id}/verify for verification decisions.")
    if assessment_type not in ASSESSMENT_COLUMNS:
        raise validation_error("assessment_type", "Supported types: severity, confidence, freshness.")
    if value not in ASSESSMENT_VALUES[assessment_type]:
        raise validation_error("assessment_value",
                               f"For {assessment_type} use one of: {', '.join(ASSESSMENT_VALUES[assessment_type])}.")
    inc = _lock_incidents(conn, [incident_id])[incident_id]
    if inc.operational_status in CLOSED_FOR_CHANGES:
        raise _conflict("A merged or withdrawn incident cannot be assessed.")

    assessment_id = new_id()
    created_at = conn.execute(
        text("""INSERT INTO incident.incident_assessments
                  (id, incident_id, assessment_type, assessment_value, rationale, assessor_id, actor_type,
                   source, is_authoritative)
                VALUES (:id, :iid, :type, :value, :rationale, :uid, 'user', 'reviewer', true)
                RETURNING assessed_at"""),
        {"id": assessment_id, "iid": incident_id, "type": assessment_type, "value": value,
         "rationale": rationale, "uid": principal.user_id},
    ).scalar_one()
    column = ASSESSMENT_COLUMNS[assessment_type]  # fixed whitelist, never user input
    conn.execute(text(f"UPDATE incident.incidents SET {column} = :value WHERE id = :iid"),
                 {"value": value, "iid": incident_id})
    _bump(conn, incident_id)
    _refresh(conn, incident_id, f"{assessment_type}_assessed")
    return assessment_id, created_at


# --- Corrections and status (PATCH /incidents/{id}) ------------------------------------------

OPERATIONAL_VALUES = ("active", "monitoring", "resolved", "closed")  # merged/withdrawn have their own paths
CORRECTION_FIELDS = ("title", "description", "category", "location")
STATUS_FIELDS = ("operational_status", "severity")


@dataclass(frozen=True)
class UpdateResult:
    changed: tuple[str, ...]
    version: int


def update_incident(conn: Connection, principal: Principal, incident_id: uuid.UUID, changes: dict,
                    reason: str, expected_version: int | None) -> UpdateResult:
    """Corrections (incident.correct) and status changes (incident.assess) in one transaction.

    Corrections never overwrite silently: each changed field gets an incident_corrections row with
    the previous and new value. A category or location change can alter what the public may see,
    so the projection is restricted at once and regenerated by the worker (fail closed).
    """
    if not changes:
        raise validation_error("body", "Send at least one field to change.")
    needs_correct = [f for f in changes if f in CORRECTION_FIELDS]
    needs_assess = [f for f in changes if f in STATUS_FIELDS]
    if needs_correct and not principal.has("incident.correct"):
        raise ApiError(403, "insufficient_permission", "Correcting incident details requires incident.correct.")
    if needs_assess and not principal.has("incident.assess"):
        raise ApiError(403, "insufficient_permission", "Changing status or severity requires incident.assess.")
    if "operational_status" in changes and changes["operational_status"] not in OPERATIONAL_VALUES:
        raise validation_error("operational_status", f"Use one of: {', '.join(OPERATIONAL_VALUES)}. "
                               "Merges use POST /incidents/{id}/merge.")
    if "severity" in changes and changes["severity"] not in ASSESSMENT_VALUES["severity"]:
        raise validation_error("severity", f"Use one of: {', '.join(ASSESSMENT_VALUES['severity'])}.")

    cur = conn.execute(
        text("""SELECT i.title, i.description, i.category_id, c.code AS category, i.operational_status,
                       i.severity, i.location_uncertainty_m, i.lock_version,
                       ST_Y(i.canonical_location::geometry) AS lat, ST_X(i.canonical_location::geometry) AS lon
                FROM incident.incidents i JOIN ref.incident_categories c ON c.id = i.category_id
                WHERE i.id = :id FOR UPDATE OF i"""),
        {"id": incident_id},
    ).first()
    if cur is None:
        raise _not_found()
    if cur.operational_status in CLOSED_FOR_CHANGES:
        raise _conflict("A merged or withdrawn incident cannot be changed.")
    if expected_version is not None and expected_version != cur.lock_version:
        raise _conflict("Someone else changed this incident. Reload it and try again.", code="version_conflict")

    changed: list[str] = []
    restrict = False

    def correct(field_name: str, previous, new) -> None:
        conn.execute(
            text("""INSERT INTO incident.incident_corrections
                      (id, incident_id, field_name, previous_value, corrected_value, reason, actor_id)
                    VALUES (:id, :iid, :field, CAST(:prev AS jsonb), CAST(:new AS jsonb), :reason, :uid)"""),
            {"id": new_id(), "iid": incident_id, "field": field_name, "prev": json.dumps(previous),
             "new": json.dumps(new), "reason": reason, "uid": principal.user_id},
        )

    if "title" in changes and changes["title"] != cur.title:
        correct("title", cur.title, changes["title"])
        conn.execute(text("UPDATE incident.incidents SET title = :v WHERE id = :id"),
                     {"v": changes["title"], "id": incident_id})
        changed.append("title")
    if "description" in changes and changes["description"] != cur.description:
        correct("description", cur.description, changes["description"])
        conn.execute(text("UPDATE incident.incidents SET description = :v WHERE id = :id"),
                     {"v": changes["description"], "id": incident_id})
        changed.append("description")
        restrict = True  # staff text may become public under some policies; re-check before showing
    if "category" in changes and changes["category"] != cur.category:
        category_id = conn.execute(
            text("SELECT id FROM ref.incident_categories WHERE code = :code AND active"),
            {"code": changes["category"]},
        ).scalar_one_or_none()
        if category_id is None:
            raise validation_error("category", "Unknown or inactive category.")
        correct("category_id", cur.category_id, category_id)
        conn.execute(text("UPDATE incident.incidents SET category_id = :v WHERE id = :id"),
                     {"v": category_id, "id": incident_id})
        changed.append("category")
        restrict = True  # a new category can mean a stricter disclosure policy
    if "location" in changes:
        loc = changes["location"]
        if (loc["latitude"], loc["longitude"]) != (cur.lat, cur.lon):
            correct("canonical_location", {"latitude": cur.lat, "longitude": cur.lon},
                    {"latitude": loc["latitude"], "longitude": loc["longitude"]})
            conn.execute(
                text("""UPDATE incident.incidents
                        SET canonical_location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                        WHERE id = :id"""),
                {"lat": loc["latitude"], "lon": loc["longitude"], "id": incident_id},
            )
            changed.append("location")
            restrict = True
        if loc.get("uncertainty_m") is not None and loc["uncertainty_m"] != cur.location_uncertainty_m:
            correct("location_uncertainty_m", cur.location_uncertainty_m, loc["uncertainty_m"])
            conn.execute(text("UPDATE incident.incidents SET location_uncertainty_m = :v WHERE id = :id"),
                         {"v": loc["uncertainty_m"], "id": incident_id})
            changed.append("location_uncertainty_m")

    for field_name, assessment_type, column in (("operational_status", "operational", "operational_status"),
                                                ("severity", "severity", "severity")):
        if field_name in changes and changes[field_name] != getattr(cur, column):
            conn.execute(
                text("""INSERT INTO incident.incident_assessments
                          (id, incident_id, assessment_type, assessment_value, rationale, assessor_id, actor_type,
                           source, is_authoritative)
                        VALUES (:id, :iid, :type, :value, :reason, :uid, 'user', 'reviewer', true)"""),
                {"id": new_id(), "iid": incident_id, "type": assessment_type, "value": changes[field_name],
                 "reason": reason, "uid": principal.user_id},
            )
            conn.execute(text(f"UPDATE incident.incidents SET {column} = :v WHERE id = :id"),  # fixed whitelist
                         {"v": changes[field_name], "id": incident_id})
            changed.append(field_name)

    if not changed:
        return UpdateResult((), cur.lock_version)
    version = conn.execute(
        text("UPDATE incident.incidents SET lock_version = lock_version + 1 WHERE id = :id RETURNING lock_version"),
        {"id": incident_id},
    ).scalar_one()
    if restrict:
        restrict_projection(conn, incident_id, "corrected")  # also enqueues the refresh
    else:
        _refresh(conn, incident_id, "incident_updated")
    corrected = [f for f in changed if f not in STATUS_FIELDS]
    if corrected:
        audit(conn, action="incident.correct", resource_type="incident", resource_id=incident_id,
              actor_type="user", actor_id=principal.user_id, metadata={"fields": corrected})
    if "operational_status" in changed:
        audit(conn, action="incident.status_change", resource_type="incident", resource_id=incident_id,
              actor_type="user", actor_id=principal.user_id,
              metadata={"previous": cur.operational_status, "new": changes["operational_status"]})
    return UpdateResult(tuple(changed), version)


# --- Report association ----------------------------------------------------------------------

def associate_report(conn: Connection, principal: Principal, incident_id: uuid.UUID, report_id: uuid.UUID,
                     reason: str) -> str:
    report = conn.execute(
        text("SELECT id, incident_id, intake_status FROM reporting.reports WHERE id = :id FOR UPDATE"),
        {"id": report_id},
    ).first()
    if report is None:
        raise _not_found()
    if report.incident_id == incident_id:
        return "unchanged"
    if report.intake_status != "accepted":
        raise _conflict("Only accepted reports can be associated. Resolve the quarantine review first.")

    previous = report.incident_id
    incidents = _lock_incidents(conn, [incident_id] + ([previous] if previous else []))
    target = incidents[incident_id]
    if target.operational_status in CLOSED_FOR_CHANGES:
        raise _conflict("The incident is merged or withdrawn; associate the report with the surviving incident.")

    action = "reassign" if previous else "review_assign"
    conn.execute(
        text("""INSERT INTO reporting.report_association_history
                  (id, report_id, previous_incident_id, new_incident_id, action, reason, actor_id, actor_type)
                VALUES (:id, :rid, :prev, :new, :action, :reason, :uid, 'user')"""),
        {"id": new_id(), "rid": report_id, "prev": previous, "new": incident_id, "action": action,
         "reason": reason, "uid": principal.user_id},
    )
    conn.execute(text("UPDATE reporting.reports SET incident_id = :iid WHERE id = :rid"),
                 {"iid": incident_id, "rid": report_id})
    conn.execute(
        text("""UPDATE incident.incidents i
                SET report_count = i.report_count + 1,
                    first_observed_at = LEAST(i.first_observed_at, r.observed_at),
                    last_observed_at  = GREATEST(i.last_observed_at, r.observed_at),
                    lock_version = i.lock_version + 1
                FROM reporting.reports r WHERE i.id = :iid AND r.id = :rid"""),
        {"iid": incident_id, "rid": report_id},
    )
    if previous:
        conn.execute(
            text("""UPDATE incident.incidents SET report_count = GREATEST(report_count - 1, 0),
                           lock_version = lock_version + 1 WHERE id = :id"""),
            {"id": previous},
        )
        _refresh(conn, previous, "report_reassigned")
    _refresh(conn, incident_id, "report_associated")
    _resolve_items(conn, principal, "associated", item_type="ambiguous_match", report_id=report_id)
    audit(conn, action="report.associate", resource_type="report", resource_id=report_id, actor_type="user",
          actor_id=principal.user_id,
          metadata={"incident_id": str(incident_id), "previous_incident_id": str(previous) if previous else None,
                    "association_action": action})
    return "associated"


@dataclass(frozen=True)
class UnassociateResult:
    outcome: str                         # "unassociated" | "unchanged"
    previous_incident_id: uuid.UUID | None
    remaining_reports: int | None


def unassociate_report(conn: Connection, principal: Principal, report_id: uuid.UUID,
                       reason: str) -> UnassociateResult:
    """Detach a wrongly linked report. The report and its history stay; it can be linked again later."""
    report = conn.execute(
        text("SELECT id, incident_id FROM reporting.reports WHERE id = :id FOR UPDATE"), {"id": report_id},
    ).first()
    if report is None:
        raise _not_found()
    if report.incident_id is None:
        return UnassociateResult("unchanged", None, None)
    previous = report.incident_id
    _lock_incidents(conn, [previous])

    conn.execute(
        text("""INSERT INTO reporting.report_association_history
                  (id, report_id, previous_incident_id, new_incident_id, action, reason, actor_id, actor_type)
                VALUES (:id, :rid, :prev, NULL, 'review_unassign', :reason, :uid, 'user')"""),
        {"id": new_id(), "rid": report_id, "prev": previous, "reason": reason, "uid": principal.user_id},
    )
    conn.execute(text("UPDATE reporting.reports SET incident_id = NULL WHERE id = :rid"), {"rid": report_id})
    remaining = conn.execute(
        text("""UPDATE incident.incidents SET report_count = GREATEST(report_count - 1, 0),
                       lock_version = lock_version + 1
                WHERE id = :id RETURNING report_count"""),
        {"id": previous},
    ).scalar_one()
    _refresh(conn, previous, "report_unassociated")
    audit(conn, action="report.unassociate", resource_type="report", resource_id=report_id, actor_type="user",
          actor_id=principal.user_id, metadata={"previous_incident_id": str(previous)})
    return UnassociateResult("unassociated", previous, remaining)


# --- Merge ------------------------------------------------------------------------------------

def merge_incidents(conn: Connection, principal: Principal, target_id: uuid.UUID, source_id: uuid.UUID,
                    reason: str) -> int:
    """Merge source into target. Returns the number of reports moved."""
    if target_id == source_id:
        raise validation_error("source_incident_id", "An incident cannot be merged into itself.")
    # Reports first (worker lock order), then both incidents in id order.
    report_ids = conn.execute(
        text("SELECT id FROM reporting.reports WHERE incident_id = :src ORDER BY id FOR UPDATE"),
        {"src": source_id},
    ).scalars().all()
    incidents = _lock_incidents(conn, [target_id, source_id])
    target, source = incidents[target_id], incidents[source_id]
    if target.operational_status == "merged":
        raise _conflict(f"The target incident was merged into {target.merged_into_incident_id}; "
                        "merge into the surviving incident.")
    if source.operational_status == "merged":
        raise _conflict("The source incident is already merged.")
    if target.operational_status == "withdrawn":
        raise _conflict("A withdrawn incident cannot receive a merge.")
    # Neither incident is merged, so no redirect chain exists and a cycle is impossible (DB spec 4.4).

    # Reports may have been associated after the first read; take any newcomers too.
    report_ids = conn.execute(
        text("SELECT id FROM reporting.reports WHERE incident_id = :src ORDER BY id FOR UPDATE"),
        {"src": source_id},
    ).scalars().all()

    conn.execute(
        text("""INSERT INTO incident.incident_relationships
                  (id, source_incident_id, target_incident_id, relationship_type, reason, actor_id, actor_type)
                VALUES (:id, :src, :tgt, 'merged_into', :reason, :uid, 'user')"""),
        {"id": new_id(), "src": source_id, "tgt": target_id, "reason": reason, "uid": principal.user_id},
    )
    for rid in report_ids:
        conn.execute(
            text("""INSERT INTO reporting.report_association_history
                      (id, report_id, previous_incident_id, new_incident_id, action, reason, actor_id, actor_type)
                    VALUES (:id, :rid, :src, :tgt, 'merge_reassign', :reason, :uid, 'user')"""),
            {"id": new_id(), "rid": rid, "src": source_id, "tgt": target_id, "reason": reason,
             "uid": principal.user_id},
        )
    if report_ids:
        conn.execute(text("UPDATE reporting.reports SET incident_id = :tgt WHERE id = ANY(:ids)"),
                     {"tgt": target_id, "ids": list(report_ids)})

    conn.execute(
        text("""UPDATE incident.incidents t
                SET report_count = t.report_count + :n,
                    first_observed_at = LEAST(t.first_observed_at, s.first_observed_at),
                    last_observed_at  = GREATEST(t.last_observed_at, s.last_observed_at),
                    lock_version = t.lock_version + 1
                FROM incident.incidents s WHERE t.id = :tgt AND s.id = :src"""),
        {"n": len(report_ids), "tgt": target_id, "src": source_id},
    )
    conn.execute(
        text("""UPDATE incident.incidents
                SET operational_status = 'merged', merged_into_incident_id = :tgt, report_count = 0,
                    lock_version = lock_version + 1
                WHERE id = :src"""),
        {"tgt": target_id, "src": source_id},
    )
    restrict_projection(conn, source_id, "merged")
    _refresh(conn, target_id, "incident_merged")
    audit(conn, action="incident.merge", resource_type="incident", resource_id=target_id, actor_type="user",
          actor_id=principal.user_id, metadata={"merged_incident_id": str(source_id), "reports_moved": len(report_ids)})
    return len(report_ids)


# --- Review queue -----------------------------------------------------------------------------

RESOLUTIONS = {
    "ambiguous_match": {"left_unassociated"},          # associating goes through report-associations
    "report_quarantine": {"accepted", "rejected"},
    "publication_review": {"approved", "rejected"},
    "incident_verification": set(),                    # resolved by POST /incidents/{id}/verify
}


def _lock_item(conn: Connection, item_id: uuid.UUID):
    item = conn.execute(
        text("""SELECT id, item_type, status, assigned_to, report_id, incident_id
                FROM review.review_items WHERE id = :id FOR UPDATE"""),
        {"id": item_id},
    ).first()
    if item is None:
        raise _not_found()
    return item


def claim_item(conn: Connection, principal: Principal, item_id: uuid.UUID) -> None:
    item = _lock_item(conn, item_id)
    if item.status == "claimed" and item.assigned_to == principal.user_id:
        return
    if item.status != "open":
        raise _conflict("This review item is already claimed or closed.")
    conn.execute(text("UPDATE review.review_items SET status = 'claimed', assigned_to = :uid WHERE id = :id"),
                  {"uid": principal.user_id, "id": item_id})


def resolve_item(conn: Connection, principal: Principal, item_id: uuid.UUID, resolution: str,
                 reason: str | None) -> str:
    item = _lock_item(conn, item_id)
    if item.status not in ("open", "claimed"):
        raise _conflict("This review item is already closed.")
    if item.status == "claimed" and item.assigned_to != principal.user_id:
        raise _conflict("This review item is claimed by another reviewer.")

    if resolution == "dismissed":
        status = "dismissed"
    elif resolution in RESOLUTIONS[item.item_type]:
        status = "resolved"
    else:
        allowed = sorted(RESOLUTIONS[item.item_type] | {"dismissed"})
        raise validation_error("resolution", f"For {item.item_type} use one of: {', '.join(allowed)}.")

    if item.item_type == "publication_review" and status == "resolved" and not principal.has("incident.verify"):
        raise ApiError(403, "insufficient_permission", "Publication decisions require incident.verify.")

    if item.item_type == "report_quarantine" and status == "resolved":
        report = conn.execute(text("SELECT intake_status FROM reporting.reports WHERE id = :id FOR UPDATE"),
                              {"id": item.report_id}).first()
        new_status = "accepted" if resolution == "accepted" else "rejected"
        conn.execute(
            text("""UPDATE reporting.reports SET intake_status = :s, intake_reason = :reason WHERE id = :id"""),
            {"s": new_status, "reason": f"reviewer: {reason or resolution}"[:500], "id": item.report_id},
        )
        if new_status == "accepted" and report.intake_status != "accepted":
            enqueue(conn, "report", item.report_id, "report.rematch_requested", {"report_id": str(item.report_id)})

    conn.execute(
        text("""UPDATE review.review_items
                SET status = :status, resolution = :resolution, resolved_by = :uid, resolved_at = now(),
                    assigned_to = COALESCE(assigned_to, :uid)
                WHERE id = :id"""),
        {"status": status, "resolution": resolution, "uid": principal.user_id, "id": item_id},
    )
    if item.item_type == "publication_review" and item.incident_id:
        _refresh(conn, item.incident_id, f"publication_{resolution}")
    return status
