"""Outbox worker loop (DB spec 8.2). Run with `python -m app.worker`.

Wakes on LISTEN 'outbox' and polls as a fallback. Each event runs in its own transaction together
with marking it processed, so database-only handlers take effect exactly once. Handlers are still
idempotent because a lease can expire under a slow handler. Events without a handler are retried
and end up 'dead' (visible to operators) rather than being silently dropped.
"""
import logging
import os
import signal
import socket
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg
from sqlalchemy import Connection, Engine

from app.core.config import Settings, get_settings, libpq_url
from app.core.db import get_engine
from app.infrastructure.outbox.outbox import (
    OutboxEvent,
    claim,
    complete,
    delete_processed_older_than,
    release_for_retry,
)
from app.modules.disclosure.projection_service import enqueue_freshness_sweep, refresh_projection
from app.modules.incidents.matching_service import process_submitted_report
from app.modules.retention.service import purge_report_evidence, run_retention

log = logging.getLogger(__name__)

Handler = Callable[[Connection, OutboxEvent, Settings], None]
RETENTION_RETRY_S = 900.0


class LeaseLost(Exception):
    pass


def handle_report_submitted(conn: Connection, event: OutboxEvent, settings: Settings) -> None:
    result = process_submitted_report(conn, uuid.UUID(event.payload["report_id"]), settings)
    if result:
        log.info("report matched", extra={"event_id": event.id, "report_id": event.aggregate_id,
                                          "outcome": result.outcome})


def handle_projection_refresh(conn: Connection, event: OutboxEvent, settings: Settings) -> None:
    state = refresh_projection(conn, uuid.UUID(event.payload["incident_id"]), event.payload.get("reason", "event"))
    log.info("projection refreshed", extra={"event_id": event.id, "incident_id": event.aggregate_id,
                                            "outcome": state})


def handle_evidence_purge(conn: Connection, event: OutboxEvent, settings: Settings) -> None:
    purge_report_evidence(conn, uuid.UUID(event.payload["report_id"]))


HANDLERS: dict[str, Handler] = {
    "report.submitted": handle_report_submitted,
    "projection.refresh": handle_projection_refresh,
    "evidence.purge_requested": handle_evidence_purge,
}


class Worker:
    def __init__(self, settings: Settings | None = None, worker_id: str | None = None,
                 engine: Engine | None = None):
        self.settings = settings or get_settings()
        self.engine = engine or get_engine()
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.stopping = False
        self._last_sweep = 0.0
        self._last_housekeeping = 0.0
        self._last_retention_date = None
        self._retention_retry_at = 0.0

    def process_batch(self) -> int:
        with self.engine.begin() as conn:
            events = claim(conn, self.worker_id, self.settings.outbox_batch_size, self.settings.outbox_lease_seconds)
        for event in events:
            self._process_one(event)
        return len(events)

    def _process_one(self, event: OutboxEvent) -> None:
        handler = HANDLERS.get(event.event_type)
        try:
            if handler is None:
                raise LookupError(f"no handler for {event.event_type}")
            with self.engine.begin() as conn:
                handler(conn, event, self.settings)
                if not complete(conn, event.id, self.worker_id):
                    raise LeaseLost(f"lease lost for {event.id}")
        except Exception as exc:  # noqa: BLE001 - every failure is retried, then dead-lettered
            with self.engine.begin() as conn:
                status = release_for_retry(conn, event, self.worker_id, f"{type(exc).__name__}: {exc}",
                                           self.settings.outbox_max_attempts)
            level = logging.ERROR if status == "dead" else logging.WARNING
            log.log(level, "outbox event failed", exc_info=status == "dead",
                    extra={"event_id": event.id, "event_type": event.event_type, "outcome": status})

    def run_periodic(self) -> None:
        now = time.monotonic()
        if now - self._last_sweep >= self.settings.projection_freshness_interval_s:
            with self.engine.begin() as conn:
                queued = enqueue_freshness_sweep(conn)
            self._last_sweep = now
            log.info("freshness sweep", extra={"outcome": queued})
        if now - self._last_housekeeping >= 3600:
            with self.engine.begin() as conn:
                deleted = delete_processed_older_than(conn)
            self._last_housekeeping = now
            log.info("outbox housekeeping", extra={"outcome": deleted})
        today = datetime.now(UTC)
        if (today.hour >= self.settings.retention_hour_utc and self._last_retention_date != today.date()
                and now >= self._retention_retry_at):
            # Several workers may run this; every step is idempotent and uses SKIP LOCKED.
            try:
                run_retention(self.engine, self.settings)
                self._last_retention_date = today.date()
            except Exception:  # noqa: BLE001 - must not retry on every loop iteration
                self._retention_retry_at = now + RETENTION_RETRY_S
                log.exception("retention run failed; retrying later", extra={"outcome": "retry_scheduled"})

    def run_forever(self, install_signal_handlers: bool = True) -> None:
        if install_signal_handlers:  # only possible in the main thread
            signal.signal(signal.SIGINT, self.stop)
            signal.signal(signal.SIGTERM, self.stop)
        # LISTEN needs a session-level connection: use Neon's direct endpoint, never the pooler.
        dsn = libpq_url(self.engine.url.render_as_string(hide_password=False)).replace("-pooler.", ".")
        log.info("worker started", extra={"worker_id": self.worker_id})
        while not self.stopping:
            # Reconnect when the LISTEN connection drops (Neon compute restart, network blip).
            # Events written meanwhile are picked up by the next poll.
            try:
                with psycopg.connect(dsn, autocommit=True) as listen_conn:
                    listen_conn.execute("LISTEN outbox")
                    self._loop(listen_conn)
            except psycopg.OperationalError:
                log.exception("listen connection lost; reconnecting")
                time.sleep(self.settings.outbox_poll_interval_s)
        log.info("worker stopped", extra={"worker_id": self.worker_id})

    def _loop(self, listen_conn: psycopg.Connection) -> None:
        while not self.stopping:
            try:
                processed = self.process_batch()
                self.run_periodic()
            except Exception:  # database blip: back off and keep running
                log.exception("worker loop error")
                time.sleep(self.settings.outbox_poll_interval_s)
                continue
            if processed == 0:
                for _ in listen_conn.notifies(timeout=self.settings.outbox_poll_interval_s, stop_after=1):
                    pass

    def stop(self, *_):
        self.stopping = True
