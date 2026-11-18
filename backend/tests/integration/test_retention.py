"""U-2: raw reports are short-lived; the incident stays as history."""
import pytest
from sqlalchemy import text

from tests.integration.conftest import submit

pytestmark = pytest.mark.integration


def test_retention_redacts_reports_but_keeps_incident_history(client, engine, drain):
    from app.core.config import get_settings
    from app.modules.retention.service import run_retention

    resp = submit(client, description="Fire behind the house of a named person")
    drain()
    settings = get_settings().model_copy(update={"report_retention_days": 0, "report_submitter_retention_days": 0})
    result = run_retention(engine, settings)
    assert result.counts["reports_redacted"] == 1
    drain()  # evidence.purge_requested is handled, not left to die

    with engine.connect() as conn:
        r = conn.execute(text("SELECT description, location_accuracy_m, redacted_at, incident_id "
                              "FROM reporting.reports")).one()
        assert r.description is None and r.location_accuracy_m >= 1000 and r.redacted_at is not None
        assert r.incident_id is not None  # still counted in the incident
        assert conn.execute(text("SELECT count(*) FROM incident.incidents")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM ops.outbox_events WHERE status = 'dead'")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM ops.audit_logs WHERE action = 'retention.run'")).scalar() == 1

    status = client.get(f"/api/v1/reports/{resp.json()['report_id']}/status",
                        headers={"X-Report-Access-Token": resp.json()["access_token"]})
    assert status.status_code == 401  # credentials revoked by redaction
    assert run_retention(engine, settings).counts["reports_redacted"] == 0  # idempotent
