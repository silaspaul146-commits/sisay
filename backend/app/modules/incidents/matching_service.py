"""Intake and matching for one submitted report, in one worker transaction (DB spec 6.1, 8.1).

Writes, atomically: intake status, match decision + candidates, then by outcome either an
association to an existing incident, a new provisional incident, or a review item. Never discards
or edits the report's original fields.
"""
import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.core.config import Settings
from app.infrastructure.audit import audit
from app.infrastructure.outbox.outbox import enqueue
from app.modules.incidents.matching_policy import (
    POLICY_VERSION,
    CandidateFacts,
    Decision,
    Outcome,
    ReportFacts,
    decide,
)
from app.shared.ids import new_id

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchResult:
    outcome: str
    incident_id: uuid.UUID | None
    decision_id: uuid.UUID | None


_CANDIDATES_SQL = text("""
    WITH r AS (
      SELECT rp.id, rp.category_id, rp.incident_location, rp.location_accuracy_m, rp.observed_at,
             c.match_radius_m, c.match_time_window
      FROM   reporting.reports rp
      JOIN   ref.incident_categories c ON c.id = rp.category_id
      WHERE  rp.id = :report_id
    )
    SELECT i.id, i.category_id, i.operational_status, i.verification_status, i.severity,
           i.first_observed_at, i.last_observed_at, i.location_uncertainty_m,
           ST_Distance(i.canonical_location, r.incident_location)               AS distance_m,
           r.match_radius_m + r.location_accuracy_m + i.location_uncertainty_m  AS allowed_m,
           CASE WHEN i.category_id = r.category_id THEN 1.0 ELSE cc.weight END   AS category_weight
    FROM   r
    JOIN   incident.incidents i
           ON i.operational_status IN ('active','monitoring')
          AND i.verification_status <> 'rejected'
          AND i.location_uncertainty_m <= :max_unc
          AND ST_DWithin(i.canonical_location, r.incident_location,
                         r.match_radius_m + r.location_accuracy_m + :max_unc)
          AND ST_DWithin(i.canonical_location, r.incident_location,
                         r.match_radius_m + r.location_accuracy_m + i.location_uncertainty_m)
          AND r.observed_at BETWEEN i.first_observed_at - r.match_time_window
                                AND i.last_observed_at  + r.match_time_window
    LEFT JOIN ref.category_compatibility cc
           ON cc.category_id = r.category_id AND cc.compatible_category_id = i.category_id
    WHERE  i.category_id = r.category_id OR cc.category_id IS NOT NULL
    ORDER  BY distance_m
    LIMIT  20
""")


def process_submitted_report(conn: Connection, report_id: uuid.UUID, settings: Settings,
                             rematch: bool = False) -> MatchResult | None:
    """`rematch` is used after a reviewer accepts a quarantined report: its earlier decision was
    'ineligible', so matching runs again as a new attempt."""
    report = conn.execute(
        text("""
            SELECT r.id, r.category_id, r.intake_status, r.intake_reason, r.incident_id, r.observed_at,
                   c.name AS category_name, c.match_time_window, c.default_severity,
                   s.installation_id, inst.status AS installation_status
            FROM   reporting.reports r
            JOIN   ref.incident_categories c ON c.id = r.category_id
            LEFT JOIN reporting.report_submitters s ON s.report_id = r.id
            LEFT JOIN identity.installations inst ON inst.id = s.installation_id
            WHERE  r.id = :rid
            FOR UPDATE OF r
        """),
        {"rid": report_id},
    ).first()
    if report is None:
        log.warning("report.submitted for unknown report", extra={"report_id": report_id})
        return None

    # Idempotent: a decision already exists, so an earlier delivery of this event did the work.
    # A rematch only proceeds while every earlier decision was 'ineligible'.
    done_sql = ("SELECT 1 FROM reporting.report_match_decisions WHERE report_id = :rid"
                + (" AND outcome <> 'ineligible'" if rematch else ""))
    if conn.execute(text(done_sql), {"rid": report_id}).first() or (rematch and report.incident_id is not None):
        return None

    intake_status = report.intake_status
    if intake_status == "received":
        intake_status, reason = _intake_decision(conn, report, settings)
        conn.execute(
            text("""UPDATE reporting.reports
                    SET intake_status = :status, intake_reason = COALESCE(:reason, intake_reason)
                    WHERE id = :rid"""),
            {"status": intake_status, "reason": reason, "rid": report_id},
        )

    if intake_status != "accepted":
        return _record_ineligible(conn, report_id, intake_status)

    _lock_category_family(conn, report.category_id)

    rows = conn.execute(_CANDIDATES_SQL, {"report_id": report_id,
                                          "max_unc": settings.report_matching_max_location_uncertainty_m}).all()
    facts = ReportFacts(category_id=report.category_id, observed_at=report.observed_at,
                        match_time_window=report.match_time_window, default_severity=report.default_severity)
    candidates = [
        CandidateFacts(incident_id=r.id, category_weight=float(r.category_weight), distance_m=float(r.distance_m),
                       allowed_m=float(r.allowed_m), first_observed_at=r.first_observed_at,
                       last_observed_at=r.last_observed_at, operational_status=r.operational_status,
                       verification_status=r.verification_status, severity=r.severity)
        for r in rows
    ]
    decision = decide(facts, candidates)

    if decision.outcome == Outcome.STRONG_MATCH:
        return _associate_existing(conn, report_id, decision)
    if decision.outcome == Outcome.NO_MATCH:
        return _create_provisional(conn, report_id, report.category_name, decision)
    return _queue_ambiguous(conn, report_id, decision)


def _intake_decision(conn: Connection, report, settings: Settings) -> tuple[str, str | None]:
    """Abuse controls that never require identity (FR-SEC-004). Suspicious reports are quarantined
    for review, not discarded."""
    if report.installation_status == "revoked":
        return "quarantined", "installation revoked"
    if report.installation_id is not None:
        recent = conn.execute(
            text("""SELECT count(*) FROM reporting.report_submitters
                    WHERE installation_id = :iid AND created_at > now() - interval '1 hour'"""),
            {"iid": report.installation_id},
        ).scalar_one()
        if recent > settings.intake_max_reports_per_installation_per_hour:
            return "quarantined", "installation rate limit exceeded"
    return "accepted", None


def _lock_category_family(conn: Connection, category_id: int) -> None:
    """Serialize matching per category family so two reports of one new event cannot both create a
    provisional incident (F-19). Locks are taken in ascending id order to avoid deadlocks."""
    compatible = conn.execute(
        text("SELECT compatible_category_id FROM ref.category_compatibility WHERE category_id = :cid"),
        {"cid": category_id},
    ).scalars().all()
    for cid in sorted({category_id, *compatible}):
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('match:' || :cid, 0))"),
                     {"cid": str(cid)})


def _insert_decision(conn: Connection, report_id: uuid.UUID, decision: Decision,
                     selected: uuid.UUID | None = None, created: uuid.UUID | None = None) -> uuid.UUID:
    decision_id = new_id()
    conn.execute(
        text("""
            INSERT INTO reporting.report_match_decisions
              (id, report_id, attempt, outcome, selected_incident_id, created_incident_id, policy_version, explanation)
            VALUES (:id, :rid,
                    (SELECT COALESCE(max(attempt), 0) + 1 FROM reporting.report_match_decisions WHERE report_id = :rid),
                    :outcome, :selected, :created, :policy, CAST(:explanation AS jsonb))
        """),
        {"id": decision_id, "rid": report_id, "outcome": decision.outcome.value, "selected": selected,
         "created": created, "policy": POLICY_VERSION, "explanation": json.dumps(decision.explanation())},
    )
    for rank, c in enumerate(decision.candidates, start=1):
        conn.execute(
            text("""
                INSERT INTO reporting.report_match_candidates
                  (match_decision_id, incident_id, rank, total_score, distance_m, category_score,
                   spatial_score, temporal_score, state_score, contradictions)
                VALUES (:did, :iid, :rank, :total, :dist, :cat, :spa, :tem, :sta, CAST(:contra AS text[]))
            """),
            {"did": decision_id, "iid": c.incident_id, "rank": rank, "total": c.total, "dist": c.distance_m,
             "cat": c.category, "spa": c.spatial, "tem": c.temporal, "sta": c.state, "contra": c.contradictions},
        )
    return decision_id


def _set_association(conn: Connection, report_id: uuid.UUID, incident_id: uuid.UUID, action: str,
                     reason: str, decision_id: uuid.UUID) -> None:
    # History first: the deferred trigger refuses an incident_id change without it (DB spec 11.4).
    conn.execute(
        text("""
            INSERT INTO reporting.report_association_history
              (id, report_id, previous_incident_id, new_incident_id, action, reason, match_decision_id, actor_type)
            VALUES (:id, :rid, NULL, :iid, :action, :reason, :did, 'worker')
        """),
        {"id": new_id(), "rid": report_id, "iid": incident_id, "action": action, "reason": reason, "did": decision_id},
    )
    conn.execute(text("UPDATE reporting.reports SET incident_id = :iid WHERE id = :rid"),
                 {"iid": incident_id, "rid": report_id})
    audit(conn, action="report.associate", resource_type="report", resource_id=report_id, actor_type="worker",
          metadata={"incident_id": str(incident_id), "association_action": action, "decision_id": str(decision_id)})


def _associate_existing(conn: Connection, report_id: uuid.UUID, decision: Decision) -> MatchResult:
    incident_id = decision.selected_incident_id
    locked = conn.execute(
        text("""SELECT operational_status FROM incident.incidents WHERE id = :iid FOR UPDATE"""),
        {"iid": incident_id},
    ).first()
    if locked is None or locked.operational_status not in ("active", "monitoring"):
        # Changed between the candidate query and the lock: do not force it.
        decision = Decision(Outcome.AMBIGUOUS, None, decision.candidates,
                            "selected incident changed state before association")
        return _queue_ambiguous(conn, report_id, decision)

    decision_id = _insert_decision(conn, report_id, decision, selected=incident_id)
    _set_association(conn, report_id, incident_id, "auto_match", decision.reason, decision_id)
    conn.execute(
        text("""
            UPDATE incident.incidents i
            SET    report_count = i.report_count + 1,
                   first_observed_at = LEAST(i.first_observed_at, r.observed_at),
                   last_observed_at  = GREATEST(i.last_observed_at, r.observed_at),
                   lock_version = i.lock_version + 1
            FROM   reporting.reports r
            WHERE  i.id = :iid AND r.id = :rid
        """),
        {"iid": incident_id, "rid": report_id},
    )
    enqueue(conn, "incident", incident_id, "projection.refresh", {"incident_id": str(incident_id),
                                                                  "reason": "report_associated"})
    return MatchResult(Outcome.STRONG_MATCH, incident_id, decision_id)


def _create_provisional(conn: Connection, report_id: uuid.UUID, category_name: str, decision: Decision) -> MatchResult:
    """DB spec 6.4. Title is generated, never copied from report free text; description stays NULL."""
    incident_id = new_id()
    conn.execute(
        text("""
            INSERT INTO incident.incidents
              (id, category_id, title, description, canonical_location, location_uncertainty_m,
               is_provisional, origin, verification_status, operational_status, severity,
               confidence_level, freshness_status, first_observed_at, last_observed_at, report_count)
            SELECT :iid, r.category_id, :title, NULL, r.incident_location, r.location_accuracy_m,
                   true, 'auto_from_report', 'unverified', 'active', 'unknown',
                   'low', 'current', r.observed_at, r.observed_at, 1
            FROM   reporting.reports r WHERE r.id = :rid
        """),
        {"iid": incident_id, "title": f"Reported {category_name.lower()}", "rid": report_id},
    )
    decision_id = _insert_decision(conn, report_id, decision, created=incident_id)
    _set_association(conn, report_id, incident_id, "auto_create_provisional", decision.reason, decision_id)

    # Initial assessment history, so projection columns have a source from the start (DB spec 6.4).
    # Matching engine rows are authoritative for confidence and freshness only (A-3).
    for a_type, value, authoritative in (("confidence", "low", True), ("freshness", "current", True),
                                         ("severity", "unknown", False), ("verification", "unverified", False)):
        conn.execute(
            text("""
                INSERT INTO incident.incident_assessments
                  (id, incident_id, assessment_type, assessment_value, rationale, actor_type, source, is_authoritative)
                VALUES (:id, :iid, :type, :value, 'initial state of a provisional incident', 'worker',
                        'matching_engine', :auth)
            """),
            {"id": new_id(), "iid": incident_id, "type": a_type, "value": value, "auth": authoritative},
        )
    enqueue(conn, "incident", incident_id, "projection.refresh", {"incident_id": str(incident_id),
                                                                  "reason": "incident_created"})
    return MatchResult(Outcome.NO_MATCH, incident_id, decision_id)


def _queue_ambiguous(conn: Connection, report_id: uuid.UUID, decision: Decision) -> MatchResult:
    decision_id = _insert_decision(conn, report_id, decision)
    conn.execute(
        text("""
            INSERT INTO review.review_items (id, item_type, report_id, match_decision_id, priority)
            VALUES (:id, 'ambiguous_match', :rid, :did, 2)
            ON CONFLICT DO NOTHING
        """),
        {"id": new_id(), "rid": report_id, "did": decision_id},
    )
    return MatchResult(Outcome.AMBIGUOUS, None, decision_id)


def _record_ineligible(conn: Connection, report_id: uuid.UUID, intake_status: str) -> MatchResult:
    decision = Decision(Outcome.INELIGIBLE, None, [], f"intake status {intake_status}")
    decision_id = _insert_decision(conn, report_id, decision)
    if intake_status in ("quarantined", "needs_review"):
        conn.execute(
            text("""
                INSERT INTO review.review_items (id, item_type, report_id, priority)
                VALUES (:id, 'report_quarantine', :rid, 3)
                ON CONFLICT DO NOTHING
            """),
            {"id": new_id(), "rid": report_id},
        )
    return MatchResult(Outcome.INELIGIBLE, None, decision_id)
