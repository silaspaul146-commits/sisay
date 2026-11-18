"""Transactional outbox (DB spec 8.2).

Producers call `enqueue` inside the same transaction as the state change. Workers `claim` a batch
with a lease, run each handler in its own transaction together with `complete`, and on failure
`release_for_retry` in a fresh transaction with exponential backoff.
"""
import json
import random
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from app.shared.ids import new_id


@dataclass(frozen=True)
class OutboxEvent:
    id: uuid.UUID
    sequence: int
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]
    attempts: int


def enqueue(conn: Connection, aggregate_type: str, aggregate_id: uuid.UUID, event_type: str,
            payload: dict[str, Any] | None = None) -> uuid.UUID:
    """Payloads carry identifiers only: no coordinates, tokens or free text (Domain model 9)."""
    event_id = new_id()
    conn.execute(
        text("""
            INSERT INTO ops.outbox_events (id, aggregate_type, aggregate_id, event_type, payload)
            VALUES (:id, :aggregate_type, :aggregate_id, :event_type, CAST(:payload AS jsonb))
        """),
        {"id": event_id, "aggregate_type": aggregate_type, "aggregate_id": aggregate_id,
         "event_type": event_type, "payload": json.dumps(payload or {}, default=str)},
    )
    return event_id


def enqueue_unless_pending(conn: Connection, aggregate_type: str, aggregate_id: uuid.UUID,
                           event_type: str, payload: dict[str, Any] | None = None) -> bool:
    """Used by periodic jobs so repeated sweeps do not pile up identical work."""
    exists = conn.execute(
        text("""
            SELECT 1 FROM ops.outbox_events
            WHERE aggregate_id = :aggregate_id AND event_type = :event_type AND status = 'pending'
            LIMIT 1
        """),
        {"aggregate_id": aggregate_id, "event_type": event_type},
    ).first()
    if exists:
        return False
    enqueue(conn, aggregate_type, aggregate_id, event_type, payload)
    return True


_CLAIM_SQL = text("""
    WITH c AS (
      SELECT id
      FROM   ops.outbox_events
      WHERE  (status = 'pending'    AND available_at <= now())
         OR  (status = 'processing' AND locked_until  <  now())
      ORDER  BY available_at, sequence
      LIMIT  :limit
      FOR UPDATE SKIP LOCKED
    )
    UPDATE ops.outbox_events e
    SET    status = 'processing', locked_by = :worker_id,
           locked_until = now() + make_interval(secs => :lease), attempts = e.attempts + 1
    FROM   c
    WHERE  e.id = c.id
    RETURNING e.id, e.sequence, e.aggregate_type, e.aggregate_id, e.event_type, e.payload, e.attempts
""")


def claim(conn: Connection, worker_id: str, limit: int, lease_seconds: int) -> list[OutboxEvent]:
    rows = conn.execute(_CLAIM_SQL, {"limit": limit, "worker_id": worker_id, "lease": lease_seconds}).all()
    events = [OutboxEvent(r.id, r.sequence, r.aggregate_type, r.aggregate_id, r.event_type,
                          r.payload or {}, r.attempts) for r in rows]
    return sorted(events, key=lambda e: e.sequence)


def complete(conn: Connection, event_id: uuid.UUID, worker_id: str) -> bool:
    """Mark processed in the handler's transaction. False means the lease was lost: roll back."""
    result = conn.execute(
        text("""
            UPDATE ops.outbox_events
            SET    status = 'processed', processed_at = now(), locked_by = NULL, locked_until = NULL
            WHERE  id = :id AND locked_by = :worker_id AND status = 'processing'
        """),
        {"id": event_id, "worker_id": worker_id},
    )
    return result.rowcount == 1


def backoff_seconds(attempts: int) -> float:
    """least(2^attempts s, 15 min) + jitter."""
    return min(2.0 ** attempts, 900.0) + random.uniform(0, 1.0)


def release_for_retry(conn: Connection, event: OutboxEvent, worker_id: str, error: str, max_attempts: int) -> str:
    status = "dead" if event.attempts >= max_attempts else "pending"
    conn.execute(
        text("""
            UPDATE ops.outbox_events
            SET    status = :status, locked_by = NULL, locked_until = NULL, last_error = :error,
                   available_at = now() + make_interval(secs => :delay)
            WHERE  id = :id AND locked_by = :worker_id
        """),
        {"status": status, "error": error[:2000], "delay": backoff_seconds(event.attempts),
         "id": event.id, "worker_id": worker_id},
    )
    return status


def delete_processed_older_than(conn: Connection, days: int = 7, batch: int = 10_000) -> int:
    result = conn.execute(
        text("""
            DELETE FROM ops.outbox_events
            WHERE id IN (SELECT id FROM ops.outbox_events
                         WHERE status = 'processed' AND processed_at < now() - make_interval(days => :days)
                         LIMIT :batch)
        """),
        {"days": days, "batch": batch},
    )
    return result.rowcount
