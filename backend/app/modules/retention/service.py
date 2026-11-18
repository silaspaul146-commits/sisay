"""Retention (U-2, DB spec 9.1). Raw reports are short-lived; incidents stay as history.

Runs nightly in the worker, in batches. Each step is idempotent and writes one audit summary row.
Redaction goes through reporting.redact_report(), the only audited path allowed to change
original report fields. It snaps the location to 1 km, removes free text, revokes credentials,
purges the reporter link and queues evidence purge. The report row itself is kept, so incident
counts and history stay intact.
"""
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, text

from app.core.config import Settings
from app.infrastructure.audit import audit

log = logging.getLogger(__name__)
BATCH = 1000


@dataclass
class RetentionResult:
    counts: dict[str, int] = field(default_factory=dict)


def run_retention(engine: Engine, settings: Settings) -> RetentionResult:
    result = RetentionResult()
    steps = [
        ("reports_redacted", lambda c: _redact_old_reports(c, settings.report_retention_days)),
        ("submitter_links_purged", lambda c: _purge_submitter_links(c, settings.report_submitter_retention_days)),
        ("credentials_deleted", lambda c: _delete_old_credentials(c, settings.credential_retention_days_after_expiry)),
        ("journey_checks_deleted", _delete_expired_journey_checks),
    ]
    for name, step in steps:
        total = 0
        while True:  # one transaction per batch keeps locks short
            with engine.begin() as conn:
                n = step(conn)
            total += n
            if n < BATCH:
                break
        result.counts[name] = total
    with engine.begin() as conn:
        audit(conn, action="retention.run", resource_type="retention_job", resource_id=uuid.uuid4(),
              actor_type="worker", metadata=result.counts)
    log.info("retention run", extra={"outcome": result.counts})
    return result


def _redact_old_reports(conn: Connection, days: int) -> int:
    ids = conn.execute(
        text("""SELECT id FROM reporting.reports
                WHERE redacted_at IS NULL AND received_at < now() - make_interval(days => :days)
                ORDER BY received_at LIMIT :batch FOR UPDATE SKIP LOCKED"""),
        {"days": days, "batch": BATCH},
    ).scalars().all()
    for rid in ids:
        conn.execute(text("SELECT reporting.redact_report(:id, :reason)"),
                     {"id": rid, "reason": f"retention: older than {days} days"})
    return len(ids)


def _purge_submitter_links(conn: Connection, days: int) -> int:
    return conn.execute(
        text("""UPDATE reporting.report_submitters SET user_id = NULL, installation_id = NULL,
                       identity_purged_at = now()
                WHERE report_id IN (
                  SELECT report_id FROM reporting.report_submitters
                  WHERE identity_purged_at IS NULL AND created_at < now() - make_interval(days => :days)
                  LIMIT :batch)"""),
        {"days": days, "batch": BATCH},
    ).rowcount


def _delete_old_credentials(conn: Connection, days: int) -> int:
    return conn.execute(
        text("""DELETE FROM reporting.report_access_credentials WHERE id IN (
                  SELECT id FROM reporting.report_access_credentials
                  WHERE COALESCE(revoked_at, expires_at) < now() - make_interval(days => :days)
                  LIMIT :batch)"""),
        {"days": days, "batch": BATCH},
    ).rowcount


def _delete_expired_journey_checks(conn: Connection) -> int:
    return conn.execute(
        text("""DELETE FROM subscription.journey_checks WHERE id IN (
                  SELECT id FROM subscription.journey_checks
                  WHERE expires_at < now() - interval '24 hours' LIMIT :batch)"""),
        {"batch": BATCH},
    ).rowcount


def purge_report_evidence(conn: Connection, report_id: uuid.UUID) -> int:
    """Handler for evidence.purge_requested. Object deletion is added with the evidence phase;
    until then no objects exist, so marking rows purged is the whole job."""
    return conn.execute(
        text("""UPDATE reporting.report_evidence SET upload_status = 'purged',
                       access_classification = 'restricted'
                WHERE report_id = :rid AND upload_status <> 'purged'"""),
        {"rid": report_id},
    ).rowcount
