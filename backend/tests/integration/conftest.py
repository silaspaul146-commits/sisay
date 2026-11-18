"""Integration fixtures: a real PostgreSQL + PostGIS database, migrated to head.

Set TEST_DATABASE_URL (e.g. postgresql+psycopg://postgres:postgres@localhost:5432/crisis_test).
Without it every integration test is skipped. The database is truncated between tests.
"""
import math
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]
TEST_URL = os.environ.get("TEST_DATABASE_URL")

DATA_TABLES = """
  ops.outbox_events, ops.audit_logs, review.review_notes, review.review_items,
  disclosure.public_incident_projection_history, disclosure.public_incident_projections,
  reporting.report_association_history, reporting.report_match_candidates, reporting.report_match_decisions,
  reporting.report_evidence, reporting.report_access_credentials, reporting.report_submitters, reporting.reports,
  incident.incident_assessments, incident.incident_corrections, incident.incident_relationships,
  incident.incidents, identity.installations
"""


def _reset_caches():
    from app.core.config import get_settings
    from app.core.db import get_engine, get_public_engine
    for f in (get_settings, get_engine, get_public_engine):
        f.cache_clear()


def alembic_config():
    from alembic.config import Config
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db():
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set: integration tests need PostgreSQL + PostGIS")
    os.environ.update({"DATABASE_URL": TEST_URL, "MIGRATION_DATABASE_URL": TEST_URL, "APP_ENV": "test"})
    os.environ.pop("PUBLIC_DATABASE_URL", None)
    _reset_caches()
    from alembic import command
    command.upgrade(alembic_config(), "head")
    yield TEST_URL
    _reset_caches()


@pytest.fixture
def engine(migrated_db):
    from app.core.db import get_engine
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(f"TRUNCATE {DATA_TABLES} CASCADE"))
    return eng


@pytest.fixture
def client(engine):
    from app.main import app
    return TestClient(app)


@pytest.fixture
def drain(engine):
    """Run the outbox worker synchronously until no events are left."""
    from app.core.config import get_settings
    from app.infrastructure.workers.runner import Worker
    worker = Worker(get_settings(), worker_id="test-worker")

    def _drain(max_rounds: int = 20) -> None:
        for _ in range(max_rounds):
            if worker.process_batch() == 0:
                return
        raise AssertionError("outbox did not drain")
    return _drain


def offset(lat: float, lon: float, east_m: float = 0.0, north_m: float = 0.0) -> tuple[float, float]:
    return lat + north_m / 111_320, lon + east_m / (111_320 * math.cos(math.radians(lat)))


BASE_LAT, BASE_LON = 5.9631, 10.1591


def submit(client, category="fire", lat=BASE_LAT, lon=BASE_LON, key=None, headers=None, **extra):
    body = {"category": category,
            "location": {"latitude": lat, "longitude": lon, "accuracy_m": 20, "source": "gps"}}
    body.update(extra)
    h = {"Idempotency-Key": str(key or uuid.uuid4())}
    h.update(headers or {})
    return client.post("/api/v1/reports", json=body, headers=h)
