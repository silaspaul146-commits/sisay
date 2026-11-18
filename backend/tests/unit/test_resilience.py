"""Failure handling that must not depend on a database."""
import time
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import install_error_handlers


def test_unexpected_error_keeps_request_id():
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret detail")

    rid = str(uuid.uuid4())
    resp = TestClient(app, raise_server_exceptions=False).get("/boom", headers={"X-Request-ID": rid})
    assert resp.status_code == 500
    assert resp.headers["X-Request-ID"] == rid
    body = resp.json()["error"]
    assert body["code"] == "internal_error" and body["request_id"] == rid
    assert "secret" not in resp.text


def test_failed_retention_is_not_retried_on_every_loop(monkeypatch):
    from app.infrastructure.workers import runner

    calls = []

    def failing(*_):
        calls.append(1)
        raise RuntimeError("db down")

    monkeypatch.setattr(runner, "run_retention", failing)
    worker = runner.Worker(Settings(retention_hour_utc=0), worker_id="t")
    worker._last_sweep = worker._last_housekeeping = time.monotonic()  # skip the DB-backed periodic jobs

    worker.run_periodic()
    worker.run_periodic()
    assert len(calls) == 1
    assert worker._last_retention_date is None  # still due once the retry window has passed

    worker._retention_retry_at = 0.0
    worker.run_periodic()
    assert len(calls) == 2
