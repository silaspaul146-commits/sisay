"""Staff routes: internal incident management and the review queue (API contract 5, 16).

All routes need a provider-issued bearer token for a provisioned user (app/core/auth.py) and the
specific platform permission below. They connect as app_dashboard, which cannot read reporter
identity or access credentials. Permission names follow the database vocabulary; the mapping
from the API contract's names is in docs/DECISIONS.md.

  incident.view   list/read incidents, their reports and history
  incident.assess  severity / confidence / freshness assessments; operational status (PATCH)
  incident.correct title, description, category and location corrections (PATCH)
  incident.verify  verification decisions; publication approvals
  incident.merge   merges
  report.review    review queue, match candidates, report (un)associations, quarantine decisions
"""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.auth import Principal, get_principal, require
from app.core.db import get_dashboard_engine
from app.core.errors import ApiError
from app.modules.incidents import review_service as svc
from app.shared.cursor import decode_cursor, encode_cursor

router = APIRouter(tags=["staff"])

Reason = Annotated[str, Field(min_length=3, max_length=2000)]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


# --- Me -------------------------------------------------------------------------------------

@router.get("/auth/me")
def me(principal: Annotated[Principal, Depends(get_principal)], response: Response) -> dict:
    _no_store(response)
    return {"id": str(principal.user_id), "email": principal.email, "permissions": sorted(principal.permissions)}


# --- Incidents (read) -----------------------------------------------------------------------

_INCIDENT_COLUMNS = """
    i.id, c.code AS category, i.title, i.description, i.verification_status, i.operational_status,
    i.severity, i.confidence_level, i.freshness_status, i.is_provisional, i.report_count,
    i.location_uncertainty_m, i.merged_into_incident_id, i.first_observed_at, i.last_observed_at,
    i.created_at, i.updated_at,
    ST_Y(i.canonical_location::geometry) AS lat, ST_X(i.canonical_location::geometry) AS lon
"""


def _incident_summary(r) -> dict:
    return {"id": str(r.id), "category": r.category, "title": r.title,
            "verification_status": r.verification_status, "operational_status": r.operational_status,
            "severity": r.severity, "confidence_level": r.confidence_level, "reports_count": r.report_count,
            "is_provisional": r.is_provisional, "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat()}


@router.get("/incidents")
def list_incidents(
    response: Response,
    _: Annotated[Principal, Depends(require("incident.view"))],
    category: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]+$")] = None,
    verification_status: Annotated[str | None, Query(pattern=r"^[a-z_]+$")] = None,
    operational_status: Annotated[str | None, Query(pattern=r"^[a-z_]+$")] = None,
    severity: Annotated[str | None, Query(pattern=r"^[a-z_]+$")] = None,
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[float | None, Query(gt=0, le=200)] = None,
    from_: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: Annotated[AwareDatetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> dict:
    where, params = ["true"], {"limit": limit + 1}
    for column, value in (("c.code", category), ("i.verification_status", verification_status),
                          ("i.operational_status", operational_status), ("i.severity", severity)):
        if value is not None:
            key = column.split(".")[1]
            where.append(f"{column} = :{key}")
            params[key] = value
    point = (latitude, longitude, radius_km)
    if any(p is not None for p in point):
        if not all(p is not None for p in point):
            raise ApiError(422, "validation_error", "The submitted request is invalid.",
                           [{"field": "radius_km", "message": "Give latitude, longitude and radius_km together."}])
        where.append("ST_DWithin(i.canonical_location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :r)")
        params.update(lat=latitude, lon=longitude, r=radius_km * 1000)
    if from_:
        where.append("i.last_observed_at >= :from_ts")
        params["from_ts"] = from_
    if to:
        where.append("i.first_observed_at <= :to_ts")
        params["to_ts"] = to
    if cursor:
        params["c_t"], params["c_id"] = decode_cursor(cursor)
        where.append("(i.created_at, i.id) < (:c_t, :c_id)")
    with get_dashboard_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT {_INCIDENT_COLUMNS} FROM incident.incidents i
            JOIN ref.incident_categories c ON c.id = i.category_id
            WHERE {' AND '.join(where)} ORDER BY i.created_at DESC, i.id DESC LIMIT :limit
        """), params).all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
    _no_store(response)
    return {"items": [_incident_summary(r) for r in rows], "next_cursor": next_cursor}


def _incident_detail(conn, incident_id: uuid.UUID) -> dict:
    r = conn.execute(text(f"""
        SELECT {_INCIDENT_COLUMNS}, i.lock_version, p.id AS public_id, p.publication_state, p.is_visible
        FROM incident.incidents i
        JOIN ref.incident_categories c ON c.id = i.category_id
        LEFT JOIN disclosure.public_incident_projections p ON p.incident_id = i.id
        WHERE i.id = :id
    """), {"id": incident_id}).first()
    if r is None:
        raise ApiError(404, "resource_not_found", "The resource was not found.")
    return {
        **_incident_summary(r),
        "version": r.lock_version,
        "description": r.description,
        "location": {"latitude": r.lat, "longitude": r.lon, "uncertainty_m": r.location_uncertainty_m},
        "freshness_status": r.freshness_status,
        "first_observed_at": r.first_observed_at.isoformat(),
        "last_observed_at": r.last_observed_at.isoformat(),
        "redirect_to": str(r.merged_into_incident_id) if r.merged_into_incident_id else None,
        "public": ({"public_id": str(r.public_id), "publication_state": r.publication_state,
                    "on_map": r.is_visible and r.publication_state == "published"} if r.public_id else None),
    }


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: uuid.UUID, response: Response,
                 _: Annotated[Principal, Depends(require("incident.view"))]) -> dict:
    with get_dashboard_engine().connect() as conn:
        detail = _incident_detail(conn, incident_id)
    _no_store(response)
    return detail


@router.get("/incidents/{incident_id}/reports")
def list_incident_reports(incident_id: uuid.UUID, response: Response,
                          _: Annotated[Principal, Depends(require("incident.view"))]) -> dict:
    """Report metadata only. Reporter identity and evidence need separate, audited access."""
    with get_dashboard_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT r.id, r.public_reference, c.code AS category, r.observed_at, r.received_at,
                   r.intake_status, r.location_accuracy_m, r.redacted_at IS NOT NULL AS redacted
            FROM reporting.reports r JOIN ref.incident_categories c ON c.id = r.category_id
            WHERE r.incident_id = :id ORDER BY r.observed_at
        """), {"id": incident_id}).all()
    _no_store(response)
    return {"items": [{"report_id": str(r.id), "public_reference": r.public_reference, "category": r.category,
                       "observed_at": r.observed_at.isoformat(), "received_at": r.received_at.isoformat(),
                       "intake_status": r.intake_status, "location_accuracy_m": r.location_accuracy_m,
                       "redacted": r.redacted, "association_status": "associated"} for r in rows],
            "next_cursor": None}


@router.get("/incidents/{incident_id}/history")
def incident_history(incident_id: uuid.UUID, response: Response,
                     _: Annotated[Principal, Depends(require("incident.view"))]) -> dict:
    with get_dashboard_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT a.assessment_type || '_assessed' AS event_type, a.actor_type, a.assessor_id AS actor_id,
                   NULL AS previous_value, a.assessment_value AS new_value, a.rationale AS reason,
                   a.assessed_at AS created_at
            FROM incident.incident_assessments a WHERE a.incident_id = :id
            UNION ALL
            SELECT 'report_' || h.action, h.actor_type, h.actor_id,
                   h.previous_incident_id::text, h.report_id::text, h.reason, h.created_at
            FROM reporting.report_association_history h
            WHERE h.new_incident_id = :id OR h.previous_incident_id = :id
            UNION ALL
            SELECT 'incident_' || r.relationship_type, r.actor_type, r.actor_id,
                   r.source_incident_id::text, r.target_incident_id::text, r.reason, r.created_at
            FROM incident.incident_relationships r
            WHERE r.source_incident_id = :id OR r.target_incident_id = :id
            UNION ALL
            SELECT 'corrected_' || k.field_name, 'user', k.actor_id,
                   k.previous_value::text, k.corrected_value::text, k.reason, k.created_at
            FROM incident.incident_corrections k WHERE k.incident_id = :id
            ORDER BY created_at
        """), {"id": incident_id}).all()
    _no_store(response)
    return {"items": [{"event_type": r.event_type, "actor_type": r.actor_type,
                       "actor_id": str(r.actor_id) if r.actor_id else None,
                       "previous_value": r.previous_value, "new_value": r.new_value, "reason": r.reason,
                       "created_at": r.created_at.isoformat()} for r in rows]}


@router.get("/incidents/{incident_id}/matching-candidates")
def matching_candidates(incident_id: uuid.UUID, response: Response,
                        _: Annotated[Principal, Depends(require("report.review"))]) -> dict:
    """Unassociated reports whose ambiguous match listed this incident as a candidate."""
    with get_dashboard_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT d.report_id, d.outcome, d.explanation->>'reason' AS reason, d.policy_version,
                   m.rank, m.total_score, m.distance_m, m.category_score, m.spatial_score,
                   m.temporal_score, m.state_score, m.contradictions
            FROM reporting.report_match_candidates m
            JOIN reporting.report_match_decisions d ON d.id = m.match_decision_id
            JOIN reporting.reports r ON r.id = d.report_id
            WHERE m.incident_id = :id AND d.outcome = 'ambiguous' AND r.incident_id IS NULL
            ORDER BY d.decided_at DESC
        """), {"id": incident_id}).all()
    _no_store(response)
    return {"items": [{"report_id": str(r.report_id), "possible_incident_id": str(incident_id),
                       "match_status": r.outcome, "rank": r.rank, "total_score": float(r.total_score),
                       "distance_m": float(r.distance_m),
                       "scores": {"category": float(r.category_score), "spatial": float(r.spatial_score),
                                  "temporal": float(r.temporal_score), "state": float(r.state_score)},
                       "contradictory_factors": list(r.contradictions), "reason": r.reason,
                       "policy_version": r.policy_version} for r in rows]}


# --- Incidents (decisions) ------------------------------------------------------------------

class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["verified", "rejected", "disputed", "under_review"]
    reason: Reason


@router.post("/incidents/{incident_id}/verify")
def verify(incident_id: uuid.UUID, body: VerifyIn, response: Response,
           principal: Annotated[Principal, Depends(require("incident.verify"))]) -> dict:
    with get_dashboard_engine().begin() as conn:
        r = svc.verify_incident(conn, principal, incident_id, body.decision, body.reason)
    _no_store(response)
    return {"incident_id": str(r.incident_id), "previous_status": r.previous_status,
            "verification_status": r.verification_status, "decision_recorded": r.decision_recorded,
            "updated_at": r.updated_at.isoformat()}


class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    uncertainty_m: int | None = Field(default=None, ge=0, le=100_000)


class IncidentPatch(BaseModel):
    """Only the fields sent are changed. `reason` is required and lands in the history."""
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]+$")
    location: LocationIn | None = None
    operational_status: Literal["active", "monitoring", "resolved", "closed"] | None = None
    severity: Literal["unknown", "low", "moderate", "high", "critical"] | None = None
    reason: Reason
    expected_version: int | None = Field(default=None, ge=1)


@router.patch("/incidents/{incident_id}")
def update_incident(incident_id: uuid.UUID, body: IncidentPatch, response: Response,
                    principal: Annotated[Principal, Depends(require("incident.view"))]) -> dict:
    """Corrections need incident.correct; operational_status and severity need incident.assess.
    Verification decisions use POST /incidents/{id}/verify."""
    changes = {f: getattr(body, f) for f in body.model_fields_set if f not in ("reason", "expected_version")}
    for f, v in changes.items():
        if v is None and f != "description":
            raise ApiError(422, "validation_error", "The submitted request is invalid.",
                           [{"field": f, "message": "This field cannot be empty."}])
    if "location" in changes:
        changes["location"] = changes["location"].model_dump()
    with get_dashboard_engine().begin() as conn:
        result = svc.update_incident(conn, principal, incident_id, changes, body.reason, body.expected_version)
        detail = _incident_detail(conn, incident_id)
    _no_store(response)
    return {**detail, "changed": list(result.changed)}


class AssessmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessment_type: Literal["severity", "confidence", "freshness", "verification", "geographic_impact"]
    assessment_value: str = Field(pattern=r"^[a-z_]+$", max_length=32)
    rationale: str | None = Field(default=None, max_length=2000)


@router.post("/incidents/{incident_id}/assessments", status_code=201)
def assess(incident_id: uuid.UUID, body: AssessmentIn, response: Response,
           principal: Annotated[Principal, Depends(require("incident.assess"))]) -> dict:
    with get_dashboard_engine().begin() as conn:
        assessment_id, created_at = svc.assess_incident(conn, principal, incident_id, body.assessment_type,
                                                        body.assessment_value, body.rationale)
    _no_store(response)
    return {"assessment_id": str(assessment_id), "incident_id": str(incident_id),
            "assessment_type": body.assessment_type, "assessment_value": body.assessment_value,
            "created_at": created_at.isoformat()}


class AssociationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: uuid.UUID
    reason: Reason


@router.post("/incidents/{incident_id}/report-associations")
def associate(incident_id: uuid.UUID, body: AssociationIn, response: Response,
              principal: Annotated[Principal, Depends(require("report.review"))]) -> dict:
    with get_dashboard_engine().begin() as conn:
        svc.associate_report(conn, principal, incident_id, body.report_id, body.reason)
    _no_store(response)
    return {"report_id": str(body.report_id), "incident_id": str(incident_id), "association_status": "associated"}


class UnassociateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason


@router.post("/reports/{report_id}/unassociate")
def unassociate(report_id: uuid.UUID, body: UnassociateIn, response: Response,
                principal: Annotated[Principal, Depends(require("report.review"))]) -> dict:
    with get_dashboard_engine().begin() as conn:
        r = svc.unassociate_report(conn, principal, report_id, body.reason)
    _no_store(response)
    return {"report_id": str(report_id), "result": r.outcome,
            "previous_incident_id": str(r.previous_incident_id) if r.previous_incident_id else None,
            "incident_remaining_reports": r.remaining_reports}


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_incident_id: uuid.UUID
    reason: Reason


@router.post("/incidents/{incident_id}/merge")
def merge(incident_id: uuid.UUID, body: MergeIn, response: Response,
          principal: Annotated[Principal, Depends(require("incident.merge"))]) -> dict:
    with get_dashboard_engine().begin() as conn:
        moved = svc.merge_incidents(conn, principal, incident_id, body.source_incident_id, body.reason)
    _no_store(response)
    return {"surviving_incident_id": str(incident_id), "merged_incident_id": str(body.source_incident_id),
            "status": "merged", "redirect_to": str(incident_id), "reports_moved": moved}


# --- Review queue ---------------------------------------------------------------------------

@router.get("/review/items")
def list_review_items(
    response: Response,
    _: Annotated[Principal, Depends(require("report.review"))],
    status: Annotated[Literal["open", "claimed", "resolved", "dismissed"] | None, Query()] = None,
    item_type: Annotated[Literal["ambiguous_match", "report_quarantine", "incident_verification",
                                 "publication_review"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> dict:
    params: dict = {"limit": limit + 1}
    if status is None:
        where = ["ri.status IN ('open','claimed')"]
    else:
        where = ["ri.status = :status"]
        params["status"] = status
    if item_type:
        where.append("ri.item_type = :item_type")
        params["item_type"] = item_type
    if cursor:
        params["c_t"], params["c_id"] = decode_cursor(cursor)
        where.append("(ri.created_at, ri.id) > (:c_t, :c_id)")
    with get_dashboard_engine().connect() as conn:
        rows = conn.execute(text(f"""
            SELECT ri.id, ri.item_type, ri.status, ri.priority, ri.report_id, ri.incident_id,
                   ri.match_decision_id, ri.assigned_to, ri.resolution, ri.created_at,
                   COALESCE(ic.code, rc.code) AS category, i.title AS incident_title,
                   i.report_count AS incident_report_count, r.public_reference AS report_reference,
                   (SELECT count(*) FROM reporting.report_match_candidates m
                     WHERE m.match_decision_id = ri.match_decision_id) AS candidate_count
            FROM review.review_items ri
            LEFT JOIN incident.incidents i ON i.id = ri.incident_id
            LEFT JOIN ref.incident_categories ic ON ic.id = i.category_id
            LEFT JOIN reporting.reports r ON r.id = ri.report_id
            LEFT JOIN ref.incident_categories rc ON rc.id = r.category_id
            WHERE {' AND '.join(where)}
            ORDER BY ri.created_at, ri.id LIMIT :limit
        """), params).all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
    _no_store(response)
    return {"items": [{**_item(r), "summary": {
                "category": r.category, "incident_title": r.incident_title,
                "incident_report_count": r.incident_report_count, "report_reference": r.report_reference,
                "candidate_count": r.candidate_count}} for r in rows],
            "next_cursor": next_cursor}


def _item(r) -> dict:
    s = lambda v: str(v) if v else None  # noqa: E731
    return {"id": str(r.id), "item_type": r.item_type, "status": r.status, "priority": r.priority,
            "report_id": s(r.report_id), "incident_id": s(r.incident_id),
            "match_decision_id": s(r.match_decision_id), "assigned_to": s(r.assigned_to),
            "resolution": r.resolution, "created_at": r.created_at.isoformat()}


@router.get("/review/items/{item_id}")
def get_review_item(item_id: uuid.UUID, response: Response,
                    _: Annotated[Principal, Depends(require("report.review"))]) -> dict:
    """Everything a reviewer needs to decide: the report (with its exact location, which reviewers
    need to judge a match) and the scored candidates. Never reporter identity."""
    with get_dashboard_engine().connect() as conn:
        item = conn.execute(text("""
            SELECT id, item_type, status, priority, report_id, incident_id, match_decision_id,
                   assigned_to, resolution, created_at
            FROM review.review_items WHERE id = :id"""), {"id": item_id}).first()
        if item is None:
            raise ApiError(404, "resource_not_found", "The resource was not found.")
        result = _item(item)
        if item.report_id:
            rep = conn.execute(text("""
                SELECT r.public_reference, c.code AS category, r.description, r.observed_at, r.received_at,
                       r.intake_status, r.intake_reason, r.location_accuracy_m, r.location_source, r.incident_id,
                       ST_Y(r.incident_location::geometry) AS lat, ST_X(r.incident_location::geometry) AS lon
                FROM reporting.reports r JOIN ref.incident_categories c ON c.id = r.category_id
                WHERE r.id = :id"""), {"id": item.report_id}).one()
            result["report"] = {
                "public_reference": rep.public_reference, "category": rep.category,
                "description": rep.description, "observed_at": rep.observed_at.isoformat(),
                "received_at": rep.received_at.isoformat(), "intake_status": rep.intake_status,
                "intake_reason": rep.intake_reason, "incident_id": str(rep.incident_id) if rep.incident_id else None,
                "location": {"latitude": rep.lat, "longitude": rep.lon, "accuracy_m": rep.location_accuracy_m,
                             "source": rep.location_source}}
        if item.match_decision_id:
            d = conn.execute(text("""SELECT outcome, policy_version, explanation->>'reason' AS reason
                                     FROM reporting.report_match_decisions WHERE id = :id"""),
                             {"id": item.match_decision_id}).one()
            cands = conn.execute(text("""
                SELECT m.incident_id, m.rank, m.total_score, m.distance_m, m.contradictions,
                       c.code AS category, i.title, i.verification_status, i.operational_status
                FROM reporting.report_match_candidates m
                JOIN incident.incidents i ON i.id = m.incident_id
                JOIN ref.incident_categories c ON c.id = i.category_id
                WHERE m.match_decision_id = :id ORDER BY m.rank"""), {"id": item.match_decision_id}).all()
            result["match"] = {
                "outcome": d.outcome, "policy_version": d.policy_version, "reason": d.reason,
                "candidates": [{"incident_id": str(c.incident_id), "rank": c.rank,
                                "total_score": float(c.total_score), "distance_m": float(c.distance_m),
                                "contradictions": list(c.contradictions), "category": c.category,
                                "title": c.title, "verification_status": c.verification_status,
                                "operational_status": c.operational_status} for c in cands]}
    _no_store(response)
    return result


@router.post("/review/items/{item_id}/claim")
def claim(item_id: uuid.UUID, response: Response,
          principal: Annotated[Principal, Depends(require("report.review"))]) -> dict:
    with get_dashboard_engine().begin() as conn:
        svc.claim_item(conn, principal, item_id)
    _no_store(response)
    return {"id": str(item_id), "status": "claimed", "assigned_to": str(principal.user_id)}


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Literal["left_unassociated", "accepted", "rejected", "approved", "dismissed"]
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/review/items/{item_id}/resolve")
def resolve(item_id: uuid.UUID, body: ResolveIn, response: Response,
            principal: Annotated[Principal, Depends(require("report.review"))]) -> dict:
    with get_dashboard_engine().begin() as conn:
        status = svc.resolve_item(conn, principal, item_id, body.resolution, body.reason)
    _no_store(response)
    return {"id": str(item_id), "status": status, "resolution": body.resolution}

