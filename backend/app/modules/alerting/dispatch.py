"""Push dispatch (DB spec 8.1 "Dispatch"): two transactions around the provider call.

Tx 1 claims queued deliveries (SKIP LOCKED, so several workers never send the same one) and marks
them 'sending'. The provider calls happen outside any transaction. Tx 2 records each result:
accepted, permanently rejected (bad token -> endpoint marked invalid), or retried with backoff.
Before sending, the endpoint must still be active and still belong to the subscriber's
installation (A-9), and an older version is not sent when a newer one for the same alert is
already waiting (no "unconfirmed" after "withdrawn").
"""
import logging
from collections import Counter
from typing import Protocol

from sqlalchemy import Engine, text

from app.infrastructure.push.fcm import PushMessage, SendResult

log = logging.getLogger(__name__)
STUCK_AFTER = "10 minutes"


class Sender(Protocol):
    def send(self, m: PushMessage) -> SendResult: ...


def dispatch_batch(engine: Engine, sender: Sender, batch: int = 100, max_attempts: int = 6) -> Counter:
    with engine.begin() as conn:
        conn.execute(text(f"""UPDATE alerting.alert_deliveries SET delivery_status = 'queued', next_attempt_at = now()
                              WHERE delivery_status = 'sending' AND attempted_at < now() - interval '{STUCK_AFTER}'"""))
        rows = conn.execute(text("""
            WITH claimed AS (
              UPDATE alerting.alert_deliveries d
              SET delivery_status = 'sending', attempted_at = now(), attempts = d.attempts + 1
              WHERE d.id IN (SELECT id FROM alerting.alert_deliveries
                             WHERE delivery_status = 'queued' AND next_attempt_at <= now()
                             ORDER BY next_attempt_at LIMIT :n FOR UPDATE SKIP LOCKED)
              RETURNING d.*
            )
            SELECT c.id, c.attempts, c.alert_id, e.token, e.status AS endpoint_status,
                   (e.installation_id = sp.installation_id) AS owned,
                   v.version_number, v.message, v.uncertainty_message, v.status AS version_status,
                   v.distribution_level, v.category_code, a.expires_at < now() AND a.status = 'active' AS lapsed,
                   EXISTS (SELECT 1 FROM alerting.alert_deliveries n
                           JOIN alerting.alert_versions nv ON nv.id = n.alert_version_id
                           WHERE n.alert_id = c.alert_id AND n.endpoint_id = c.endpoint_id
                             AND nv.version_number > v.version_number
                             AND n.delivery_status IN ('queued','sending','provider_accepted')) AS superseded
            FROM claimed c
            JOIN identity.push_endpoints e ON e.id = c.endpoint_id
            JOIN subscription.subscriber_principals sp ON sp.id = c.subscriber_id
            JOIN alerting.alert_versions v ON v.id = c.alert_version_id
            JOIN alerting.alerts a ON a.id = c.alert_id
        """), {"n": batch}).all()

    results: list[tuple] = []
    for r in rows:
        if r.endpoint_status != "active" or not r.owned:
            results.append((r, "cancelled", None, "endpoint no longer valid for this subscriber"))
            continue
        if r.superseded or r.lapsed:
            results.append((r, "cancelled", None, "superseded by a newer update" if r.superseded else "alert expired"))
            continue
        res = sender.send(PushMessage(
            token=r.token, title=r.message, body=r.uncertainty_message,
            data={"alert_id": str(r.alert_id), "version": str(r.version_number), "status": r.version_status or "active",
                  "category": r.category_code or ""},
            high_priority=r.distribution_level == "priority", collapse_key=f"alert-{r.alert_id}"))
        results.append((r, res.outcome, res.message_id, res.error))

    counts: Counter = Counter()
    with engine.begin() as conn:
        for r, outcome, message_id, error in results:
            err = (error or "")[:500] or None
            if outcome == "accepted":
                conn.execute(text("""UPDATE alerting.alert_deliveries SET delivery_status = 'provider_accepted',
                                     provider_message_id = :mid, provider_accepted_at = now(), last_error = NULL
                                     WHERE id = :id"""), {"id": r.id, "mid": message_id})
                conn.execute(text("""UPDATE identity.push_endpoints SET last_success_at = now(), updated_at = now()
                                     WHERE token = :t"""), {"t": r.token})
            elif outcome == "invalid_token":
                conn.execute(text("UPDATE alerting.alert_deliveries SET delivery_status = 'provider_rejected', "
                                  "last_error = :e WHERE id = :id"), {"id": r.id, "e": err})
                conn.execute(text("UPDATE identity.push_endpoints SET status = 'invalid', updated_at = now() "
                                  "WHERE token = :t"), {"t": r.token})
            elif outcome == "retry" and r.attempts < max_attempts:
                conn.execute(text("""UPDATE alerting.alert_deliveries SET delivery_status = 'queued', last_error = :e,
                                     next_attempt_at = now() + make_interval(secs => 30 * power(2, :a - 1))
                                     WHERE id = :id"""), {"id": r.id, "e": err, "a": r.attempts})
            else:
                status = {"cancelled": "cancelled", "rejected": "provider_rejected"}.get(outcome, "failed")
                conn.execute(text("UPDATE alerting.alert_deliveries SET delivery_status = :s, last_error = :e "
                                  "WHERE id = :id"), {"id": r.id, "s": status, "e": err})
            counts[outcome] += 1
    if counts:
        log.info("push dispatch", extra={"outcome": dict(counts)})
    return counts
