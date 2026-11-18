"""First vertical slice acceptance (Engineering pack 9.2, DB spec 12.2):
anonymous report -> idempotency -> conservative matching -> provisional incident or association
-> sanitized public projection -> public GeoJSON."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.security import generate_report_token
from tests.integration.conftest import BASE_LAT, BASE_LON, offset, submit

pytestmark = pytest.mark.integration

PUBLIC_PROPERTIES = {"public_id", "category", "verification_status", "lifecycle", "severity", "confidence_level",
                     "freshness_status", "precision_m", "uncertainty_note", "observed_at", "last_updated_at"}


def scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def bbox_around(lat=BASE_LAT, lon=BASE_LON, d=0.05):
    return f"{lon - d},{lat - d},{lon + d},{lat + d}"


# --- Submission and idempotency -------------------------------------------------------------

def test_anonymous_report_with_only_category_and_location(client, engine):
    resp = client.post("/api/v1/reports", headers={"Idempotency-Key": str(uuid.uuid4())},
                       json={"category": "fire", "location": {"latitude": BASE_LAT, "longitude": BASE_LON}})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["access_token"].startswith("rpt_")
    assert body["intake_status"] == "received" and body["matching_status"] == "pending"

    rid = body["report_id"]
    assert scalar(engine, "SELECT count(*) FROM reporting.reports") == 1
    # Default accuracy is applied for an unknown source; the token itself is never stored.
    assert scalar(engine, "SELECT location_accuracy_m FROM reporting.reports WHERE id = :id", id=rid) == 250
    assert scalar(engine, "SELECT count(*) FROM reporting.report_access_credentials WHERE report_id = :id "
                          "AND token_hash <> convert_to(:t, 'UTF8')", id=rid, t=body["access_token"]) == 1
    # Report and its outbox event committed together.
    assert scalar(engine, "SELECT count(*) FROM ops.outbox_events WHERE event_type = 'report.submitted' "
                          "AND aggregate_id = :id", id=rid) == 1


def test_missing_or_unknown_category_is_rejected(client, engine):
    resp = client.post("/api/v1/reports", headers={"Idempotency-Key": str(uuid.uuid4())},
                       json={"location": {"latitude": BASE_LAT, "longitude": BASE_LON}})
    assert resp.status_code == 422
    resp = submit(client, category="not_a_category")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "unsupported_category"
    assert scalar(engine, "SELECT count(*) FROM reporting.reports") == 0


def test_same_key_same_payload_returns_original_without_token(client, engine):
    key = uuid.uuid4()
    first = submit(client, key=key)
    replay = submit(client, key=key)
    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["report_id"] == first.json()["report_id"]
    assert replay.json()["replayed"] is True and "access_token" not in replay.json()
    assert scalar(engine, "SELECT count(*) FROM reporting.reports") == 1


def test_same_key_different_payload_is_409(client, engine):
    key = uuid.uuid4()
    assert submit(client, key=key).status_code == 201
    resp = submit(client, key=key, description="changed")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "idempotency_conflict"
    assert scalar(engine, "SELECT count(*) FROM reporting.reports") == 1


def test_client_generated_token_is_accepted_and_never_echoed(client):
    token = generate_report_token()
    resp = submit(client, headers={"X-Report-Access-Token": token})
    assert resp.status_code == 201 and "access_token" not in resp.json()
    rid = resp.json()["report_id"]

    ok = client.get(f"/api/v1/reports/{rid}/status", headers={"X-Report-Access-Token": token})
    assert ok.status_code == 200 and ok.json()["report_id"] == rid

    wrong = client.get(f"/api/v1/reports/{rid}/status", headers={"X-Report-Access-Token": generate_report_token()})
    missing = client.get(f"/api/v1/reports/{uuid.uuid4()}/status", headers={"X-Report-Access-Token": token})
    assert wrong.status_code == missing.status_code == 401  # existence is not revealed


# --- Matching -------------------------------------------------------------------------------

def test_unmatched_report_creates_provisional_incident(client, engine, drain):
    resp = submit(client)
    drain()
    rid = resp.json()["report_id"]
    with engine.connect() as conn:
        inc = conn.execute(text("""
            SELECT i.* FROM incident.incidents i JOIN reporting.reports r ON r.incident_id = i.id WHERE r.id = :id
        """), {"id": rid}).one()
        assert inc.is_provisional and inc.severity == "unknown" and inc.verification_status == "unverified"
        assert inc.report_count == 1 and inc.description is None and inc.title == "Reported fire"
        assert conn.execute(text("SELECT outcome FROM reporting.report_match_decisions WHERE report_id = :id"),
                            {"id": rid}).scalar() == "no_match"
        assert conn.execute(text("SELECT action FROM reporting.report_association_history WHERE report_id = :id"),
                            {"id": rid}).scalar() == "auto_create_provisional"

    status = client.get(f"/api/v1/reports/{rid}/status",
                        headers={"X-Report-Access-Token": resp.json()["access_token"]}).json()
    assert status["matching_status"] == "provisional_incident_created"
    assert status["reporter_status"] == "linked_to_incident"
    assert status["incident"]["verification_status"] == "unverified"


def test_strong_match_associates_with_existing_incident(client, engine, drain):
    first = submit(client)
    drain()
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=30)
    second = submit(client, lat=lat, lon=lon)
    drain()
    with engine.connect() as conn:
        incidents = conn.execute(text("SELECT DISTINCT incident_id FROM reporting.reports")).scalars().all()
        assert len(incidents) == 1 and incidents[0] is not None
        assert conn.execute(text("SELECT report_count FROM incident.incidents")).scalar() == 2
        assert conn.execute(text("SELECT outcome FROM reporting.report_match_decisions WHERE report_id = :id"),
                            {"id": second.json()["report_id"]}).scalar() == "strong_match"
    assert first.json()["report_id"] != second.json()["report_id"]  # both reports kept


def test_ambiguous_match_is_queued_for_review_and_not_associated(client, engine, drain):
    submit(client)
    drain()
    lat_b, lon_b = offset(BASE_LAT, BASE_LON, east_m=600)  # beyond 500 m + accuracies: separate incident
    submit(client, lat=lat_b, lon=lon_b)
    drain()
    assert scalar(engine, "SELECT count(*) FROM incident.incidents") == 2

    lat_c, lon_c = offset(BASE_LAT, BASE_LON, east_m=300)  # equidistant from both
    rid = submit(client, lat=lat_c, lon=lon_c).json()["report_id"]
    drain()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT incident_id FROM reporting.reports WHERE id = :id"), {"id": rid}).scalar() is None
        d = conn.execute(text("SELECT id, outcome FROM reporting.report_match_decisions WHERE report_id = :id"),
                         {"id": rid}).one()
        assert d.outcome == "ambiguous"
        assert conn.execute(text("SELECT count(*) FROM reporting.report_match_candidates WHERE match_decision_id = :d"),
                            {"d": d.id}).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM review.review_items WHERE report_id = :id "
                                 "AND item_type = 'ambiguous_match' AND status = 'open'"), {"id": rid}).scalar() == 1
    assert scalar(engine, "SELECT count(*) FROM incident.incidents") == 2  # nothing forced


def test_reprocessing_an_outbox_event_has_no_duplicate_effects(client, engine, drain):
    submit(client)
    drain()
    with engine.begin() as conn:
        conn.execute(text("""UPDATE ops.outbox_events SET status = 'pending', processed_at = NULL,
                             available_at = now() WHERE event_type = 'report.submitted'"""))
    drain()
    assert scalar(engine, "SELECT count(*) FROM reporting.report_match_decisions") == 1
    assert scalar(engine, "SELECT count(*) FROM incident.incidents") == 1
    assert scalar(engine, "SELECT count(*) FROM disclosure.public_incident_projection_history") == 1


# --- Public projection ----------------------------------------------------------------------

def test_public_map_returns_sanitized_geojson(client, engine, drain):
    submit(client, description="Fire at the house of a named person")
    drain()
    resp = client.get(f"/api/v1/public/incidents?bbox={bbox_around()}")
    assert resp.status_code == 200
    fc = resp.json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 1
    assert "not necessarily safe" in fc["notice"]
    feature = fc["features"][0]
    assert feature["geometry"]["type"] == "Point" and set(feature["properties"]) == PUBLIC_PROPERTIES
    assert feature["properties"]["verification_status"] == "unverified"

    internal_id = scalar(engine, "SELECT id FROM incident.incidents")
    assert str(internal_id) not in resp.text and "named person" not in resp.text
    lon, lat = feature["geometry"]["coordinates"]
    exact = scalar(engine, """SELECT ST_Distance(canonical_location,
                                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) FROM incident.incidents""",
                   lon=lon, lat=lat)
    assert exact <= 250 * 0.71 + 1  # generalized to the standard 250 m grid

    detail = client.get(f"/api/v1/public/incidents/{feature['id']}").json()
    assert detail["properties"]["description"] is None  # report free text is never published


def test_no_reports_is_not_presented_as_safe(client, engine):
    fc = client.get(f"/api/v1/public/incidents?bbox={bbox_around(lat=4.0, lon=9.7)}").json()
    assert fc["features"] == [] and "does not mean the area is safe" in fc["notice"]


def test_sensitive_category_is_delayed_and_coarsely_generalized(client, engine, drain):
    from app.modules.disclosure.projection_service import refresh_projection

    submit(client, category="armed_clash")
    drain()
    assert client.get(f"/api/v1/public/incidents?bbox={bbox_around()}").json()["features"] == []
    assert scalar(engine, "SELECT publication_state FROM disclosure.public_incident_projections") == "pending"

    with engine.begin() as conn:  # simulate the 30-minute publication delay passing
        conn.execute(text("UPDATE incident.incidents SET created_at = now() - interval '1 hour'"))
        refresh_projection(conn, conn.execute(text("SELECT id FROM incident.incidents")).scalar(), "test")
    features = client.get(f"/api/v1/public/incidents?bbox={bbox_around()}").json()["features"]
    assert len(features) == 1 and features[0]["properties"]["precision_m"] == 2000
    lon, lat = features[0]["geometry"]["coordinates"]
    assert scalar(engine, """SELECT ST_Distance(canonical_location,
                               ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) FROM incident.incidents""",
                  lon=lon, lat=lat) <= 2000 * 0.71 + 1


def test_restriction_hides_projection_in_the_same_transaction(client, engine, drain):
    from app.modules.disclosure.projection_service import restrict_projection

    submit(client)
    drain()
    public_id = client.get(f"/api/v1/public/incidents?bbox={bbox_around()}").json()["features"][0]["id"]
    with engine.begin() as conn:
        restrict_projection(conn, conn.execute(text("SELECT id FROM incident.incidents")).scalar(), "location corrected")
        assert conn.execute(text("SELECT count(*) FROM disclosure.public_incidents_v")).scalar() == 0
    assert client.get(f"/api/v1/public/incidents/{public_id}").status_code == 404
    removals = client.get("/api/v1/public/incidents/removals?since=2000-01-01T00:00:00Z").json()["items"]
    assert [r["public_id"] for r in removals] == [public_id]
    drain()  # the worker regenerates and republishes
    assert client.get(f"/api/v1/public/incidents/{public_id}").status_code == 200


def test_never_published_incident_is_not_listed_as_removed(client, engine, drain):
    """A pending (delayed or review-gated) incident must not leak through the removals feed."""
    submit(client, category="armed_clash")
    drain()
    assert scalar(engine, "SELECT publication_state FROM disclosure.public_incident_projections") == "pending"
    removals = client.get("/api/v1/public/incidents/removals?since=2000-01-01T00:00:00Z").json()["items"]
    assert removals == []


def test_rls_tolerates_a_cleared_organization_setting(engine):
    """After SET LOCAL ends the setting reads '' for the session; policies must not cast it."""
    with engine.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'app_analytics'")).first():
            pytest.skip("runtime roles not created in this database")
        conn.execute(text("SELECT set_config('app.organization_id', '', false)"))
        conn.execute(text("SET ROLE app_analytics"))  # superusers bypass RLS
        try:
            assert conn.execute(text("SELECT count(*) FROM humanitarian.humanitarian_impact_records")).scalar() == 0
        finally:
            conn.execute(text("RESET ROLE"))


# --- Database guards ------------------------------------------------------------------------

def test_original_report_fields_are_immutable(client, engine):
    rid = submit(client).json()["report_id"]
    with pytest.raises(DBAPIError, match="immutable"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE reporting.reports SET description = 'edited' WHERE id = :id"), {"id": rid})


def test_association_change_without_history_is_rejected(client, engine, drain):
    rid = submit(client).json()["report_id"]
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=5000)
    submit(client, lat=lat, lon=lon)
    drain()
    other = scalar(engine, """SELECT i.id FROM incident.incidents i
                              WHERE i.id <> (SELECT incident_id FROM reporting.reports WHERE id = :id)""", id=rid)
    with pytest.raises(DBAPIError, match="without history"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE reporting.reports SET incident_id = :i WHERE id = :id"), {"i": other, "id": rid})


def test_report_can_exist_without_incident_during_intake(client, engine):
    rid = submit(client).json()["report_id"]
    assert scalar(engine, "SELECT incident_id IS NULL FROM reporting.reports WHERE id = :id", id=rid)
