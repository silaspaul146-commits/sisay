"""Report submission and anonymous status (API contract 3, DB spec 7.3 and 8.1).

Submission commits report + submitter link + access credential + outbox event in one transaction
and returns without waiting for matching. Retries with the same Idempotency-Key and the same
payload return the original result (200, never the token again); a changed payload returns 409.
"""
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import ApiError, validation_error
from app.core.security import candidate_hashes, generate_report_token, hash_report_token, is_well_formed_token
from app.infrastructure.outbox.outbox import enqueue
from app.modules.reporting.schemas import PublicIncidentSummary, ReportCreate, ReportCreated, ReportStatus
from app.shared.enums import DEFAULT_ACCURACY_M, LocationSource, MatchingStatus
from app.shared.ids import new_id, new_public_reference

CLOCK_TOLERANCE = timedelta(minutes=15)  # matches ck_reports_observed_not_future


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def request_fingerprint(payload: ReportCreate) -> bytes:
    """SHA-256 of the canonical client payload. Server-derived defaults are excluded so that
    identical retries always produce the same fingerprint."""
    canonical = {
        "category": payload.category,
        "description": payload.description,
        "lat": round(payload.location.latitude, 7),
        "lon": round(payload.location.longitude, 7),
        "accuracy_m": payload.location.accuracy_m,
        "source": payload.location.source.value if payload.location.source else None,
        "observed_at": _iso(payload.observed_at),
        "client_created_at": _iso(payload.client_created_at),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).digest()


def resolve_observed_at(payload: ReportCreate, received_at: datetime) -> tuple[datetime, str | None]:
    """Observed time is the client's claim; server receipt time stays authoritative and separate.
    A delayed offline report keeps its earlier time and is never treated as newly observed."""
    if payload.observed_at is not None:
        if payload.observed_at > received_at + CLOCK_TOLERANCE:
            raise validation_error("observed_at", "Observation time cannot be in the future.")
        return payload.observed_at, None
    if payload.client_created_at is not None:
        if payload.client_created_at > received_at + CLOCK_TOLERANCE:
            return received_at, "client clock ahead of server; observed_at set to received_at"
        return payload.client_created_at, None
    return received_at, None


@dataclass(frozen=True)
class SubmitContext:
    idempotency_key: uuid.UUID
    installation_id: uuid.UUID | None
    client_platform: str
    client_token: str | None
    source_type: str = "citizen_app"


def submit_report(conn: Connection, payload: ReportCreate, ctx: SubmitContext, settings: Settings) -> tuple[int, ReportCreated]:
    category = conn.execute(
        text("SELECT id FROM ref.incident_categories WHERE code = :code AND active"),
        {"code": payload.category},
    ).first()
    if category is None:
        raise validation_error("category", "Unsupported incident category.", code="unsupported_category")

    if ctx.client_token is not None and not is_well_formed_token(ctx.client_token):
        raise validation_error("X-Report-Access-Token", "Malformed report access token.")

    scope = f"inst:{ctx.installation_id}" if ctx.installation_id else "anon:"
    fingerprint = request_fingerprint(payload)
    received_at: datetime = conn.execute(text("SELECT now()")).scalar_one()
    observed_at, intake_note = resolve_observed_at(payload, received_at)

    source = payload.location.source or LocationSource.MANUAL_PIN
    accuracy = payload.location.accuracy_m if payload.location.accuracy_m is not None else DEFAULT_ACCURACY_M[source]

    if ctx.installation_id:
        conn.execute(
            text("""
                INSERT INTO identity.installations (id, platform) VALUES (:id, :platform)
                ON CONFLICT (id) DO UPDATE SET last_seen_at = now()
            """),
            {"id": ctx.installation_id, "platform": ctx.client_platform},
        )

    report_id = new_id()
    inserted = None
    for _ in range(3):  # retry only on the (astronomically rare) public_reference collision
        try:
            with conn.begin_nested():
                inserted = conn.execute(
                    text("""
                        INSERT INTO reporting.reports (
                          id, public_reference, category_id, description, incident_location,
                          location_accuracy_m, location_source, observed_at, client_created_at, received_at,
                          source_type, idempotency_scope, idempotency_key, request_fingerprint, intake_reason)
                        VALUES (
                          :id, :public_reference, :category_id, :description,
                          ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                          :accuracy, :source, :observed_at, :client_created_at, :received_at,
                          :source_type, :scope, :key, :fingerprint, :intake_reason)
                        ON CONFLICT (idempotency_scope, idempotency_key) DO NOTHING
                        RETURNING id
                    """),
                    {"id": report_id, "public_reference": new_public_reference(), "category_id": category.id,
                     "description": payload.description, "lon": payload.location.longitude,
                     "lat": payload.location.latitude, "accuracy": accuracy, "source": source.value,
                     "observed_at": observed_at, "client_created_at": payload.client_created_at,
                     "received_at": received_at, "source_type": ctx.source_type, "scope": scope,
                     "key": ctx.idempotency_key, "fingerprint": fingerprint, "intake_reason": intake_note},
                ).first()
            break
        except IntegrityError as exc:
            if "uq_reports_public_reference" not in str(exc.orig):
                raise
    else:
        raise ApiError(503, "service_unavailable", "The report could not be stored. Please retry.")

    if inserted is None:
        return 200, _replay(conn, scope, ctx.idempotency_key, fingerprint)

    conn.execute(
        text("INSERT INTO reporting.report_submitters (report_id, installation_id) VALUES (:rid, :iid)"),
        {"rid": report_id, "iid": ctx.installation_id},
    )

    token = ctx.client_token or generate_report_token()
    version = settings.token_pepper_active_version
    try:
        with conn.begin_nested():
            conn.execute(
                text("""
                    INSERT INTO reporting.report_access_credentials
                      (id, report_id, token_hash, hash_key_version, expires_at)
                    VALUES (:id, :rid, :hash, :version, :expires_at)
                """),
                {"id": new_id(), "rid": report_id, "hash": hash_report_token(token, settings.token_peppers[version]),
                 "version": version, "expires_at": received_at + timedelta(days=settings.report_token_ttl_days)},
            )
    except IntegrityError:
        # A client reused one token for two reports. Reject the whole submission.
        raise validation_error("X-Report-Access-Token", "Use a new access token for each report.")

    enqueue(conn, "report", report_id, "report.submitted", {"report_id": str(report_id)})

    reference = conn.execute(
        text("SELECT public_reference FROM reporting.reports WHERE id = :id"), {"id": report_id}
    ).scalar_one()
    return 201, ReportCreated(
        report_id=report_id,
        public_reference=reference,
        access_token=None if ctx.client_token else token,
        intake_status="received",
        matching_status=MatchingStatus.PENDING,
        received_at=received_at,
    )


def _replay(conn: Connection, scope: str, key: uuid.UUID, fingerprint: bytes) -> ReportCreated:
    row = conn.execute(
        text("""
            SELECT id, public_reference, request_fingerprint, intake_status, incident_id, received_at
            FROM reporting.reports WHERE idempotency_scope = :scope AND idempotency_key = :key
        """),
        {"scope": scope, "key": key},
    ).one()
    if bytes(row.request_fingerprint) != fingerprint:
        raise ApiError(409, "idempotency_conflict",
                       "This Idempotency-Key was already used with a different request.")
    return ReportCreated(
        report_id=row.id,
        public_reference=row.public_reference,
        access_token=None,
        intake_status=row.intake_status,
        matching_status=derive_matching_status(conn, row.id, row.incident_id),
        received_at=row.received_at,
        replayed=True,
    )


def derive_matching_status(conn: Connection, report_id: uuid.UUID, incident_id: uuid.UUID | None) -> str:
    if incident_id is not None:
        action = conn.execute(
            text("""
                SELECT action FROM reporting.report_association_history
                WHERE report_id = :rid AND new_incident_id = :iid
                ORDER BY created_at DESC LIMIT 1
            """),
            {"rid": report_id, "iid": incident_id},
        ).scalar()
        if action == "auto_create_provisional":
            return MatchingStatus.PROVISIONAL_INCIDENT_CREATED
        return MatchingStatus.MATCHED_EXISTING_INCIDENT
    outcome = conn.execute(
        text("""
            SELECT outcome FROM reporting.report_match_decisions
            WHERE report_id = :rid ORDER BY attempt DESC LIMIT 1
        """),
        {"rid": report_id},
    ).scalar()
    if outcome == "ambiguous":
        return MatchingStatus.NEEDS_REVIEW
    if outcome == "ineligible":
        return MatchingStatus.FAILED
    return MatchingStatus.PENDING


def get_report_status(conn: Connection, report_id: uuid.UUID, token: str | None, settings: Settings) -> ReportStatus:
    invalid = ApiError(401, "invalid_access_token", "The report access token is missing or invalid.")
    if not token or not is_well_formed_token(token):
        raise invalid
    hashes = list(candidate_hashes(token, settings.token_peppers).values())
    cred = conn.execute(
        text("""
            SELECT id, last_used_at FROM reporting.report_access_credentials
            WHERE report_id = :rid AND token_hash = ANY(:hashes)
              AND revoked_at IS NULL AND expires_at > now()
        """),
        {"rid": report_id, "hashes": hashes},
    ).first()
    if cred is None:
        raise invalid  # same answer whether or not the report exists
    if cred.last_used_at is None or cred.last_used_at < datetime.now(UTC) - timedelta(hours=1):
        conn.execute(text("UPDATE reporting.report_access_credentials SET last_used_at = now() WHERE id = :id"),
                     {"id": cred.id})

    r = conn.execute(
        text("""
            SELECT r.id, r.public_reference, c.code AS category, r.description, r.intake_status,
                   r.incident_id, r.received_at,
                   (SELECT count(*) FROM reporting.report_evidence e
                    WHERE e.report_id = r.id AND e.upload_status <> 'purged') AS evidence_count
            FROM reporting.reports r JOIN ref.incident_categories c ON c.id = r.category_id
            WHERE r.id = :rid
        """),
        {"rid": report_id},
    ).one()

    incident = None
    if r.incident_id is not None:
        p = conn.execute(
            text("""
                SELECT id, public_category_code, public_verification, public_lifecycle, uncertainty_note
                FROM disclosure.public_incident_projections
                WHERE incident_id = :iid AND is_visible AND publication_state = 'published'
            """),
            {"iid": r.incident_id},
        ).first()
        if p is not None:
            incident = PublicIncidentSummary(public_id=p.id, category=p.public_category_code,
                                             verification_status=p.public_verification,
                                             lifecycle=p.public_lifecycle, uncertainty_note=p.uncertainty_note)

    matching = derive_matching_status(conn, r.id, r.incident_id)
    if r.intake_status == "rejected":
        reporter_status = "not_published"
    elif r.intake_status in ("needs_review", "quarantined") or matching == MatchingStatus.NEEDS_REVIEW:
        reporter_status = "under_review"
    elif r.incident_id is not None:
        reporter_status = "linked_to_incident"
    else:
        reporter_status = "received"

    return ReportStatus(
        report_id=r.id, public_reference=r.public_reference, category=r.category, description=r.description,
        reporter_status=reporter_status, intake_status=r.intake_status, matching_status=matching,
        received_at=r.received_at, evidence_count=r.evidence_count, incident=incident,
    )
