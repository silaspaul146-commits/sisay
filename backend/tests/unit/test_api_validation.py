"""API behaviour that is decided before any database access."""
import pytest
from fastapi.testclient import TestClient

from app.core.db import public_connection, transaction
from app.main import app


@pytest.fixture
def client():
    app.dependency_overrides[public_connection] = lambda: None
    app.dependency_overrides[transaction] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def assert_envelope(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()["error"]
    assert body["code"] == code and body["request_id"] and isinstance(body["details"], list)
    return body


def test_report_requires_idempotency_key(client):
    resp = client.post("/api/v1/reports", json={"category": "fire", "location": {"latitude": 1, "longitude": 1}})
    assert_envelope(resp, 422, "validation_error")


def test_invalid_report_body_does_not_echo_values(client):
    resp = client.post("/api/v1/reports", headers={"Idempotency-Key": "8a6b7c1e-0f5d-4c1b-9a8e-2f9d1c3b4a5e"},
                       json={"category": "fire", "location": {"latitude": 123.456789, "longitude": 1}})
    body = assert_envelope(resp, 422, "validation_error")
    assert "123.456789" not in resp.text
    assert any(d["field"] == "location.latitude" for d in body["details"])


@pytest.mark.parametrize("query", [
    "",                                                   # no geographic bound
    "?bbox=10,5,11,6&latitude=5&longitude=10&radius_km=1",  # both forms
    "?bbox=10,5,13,6",                                    # wider than 2 degrees
    "?bbox=11,5,10,6",                                    # west > east
    "?bbox=a,b,c,d",
    "?latitude=5&longitude=10",                           # radius missing
    "?latitude=5&longitude=10&radius_km=500",             # radius too large
])
def test_public_map_rejects_unbounded_or_malformed_queries(client, query):
    resp = client.get("/api/v1/public/incidents" + query)
    assert_envelope(resp, 422, "validation_error")


def test_unknown_route_uses_error_envelope(client):
    assert_envelope(client.get("/api/v1/nope"), 404, "resource_not_found")


def test_request_id_is_echoed(client):
    rid = "0b8e8d6f-6a3c-4f1e-9d2b-7c5a4e3f2d1c"
    resp = client.get("/health", headers={"X-Request-ID": rid})
    assert resp.status_code == 200 and resp.headers["X-Request-ID"] == rid


def test_openapi_documents_the_slice(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    for p in ("/api/v1/reports", "/api/v1/reports/{report_id}/status", "/api/v1/public/incidents",
              "/api/v1/public/incidents/{public_id}", "/api/v1/incident-categories"):
        assert p in paths
