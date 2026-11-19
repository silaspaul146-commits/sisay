"""Alerts end to end: device registration, saved places and routes, the alert engine, fan-out and
the citizen feed. The citizen API and the worker run as their real database roles (app_citizen,
app_worker), so a missing grant fails here and not first in production."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, text

from tests.integration.conftest import BASE_LAT, BASE_LON, TEST_URL, offset, submit

pytestmark = pytest.mark.integration
REVIEWER = ("incident.view", "incident.assess", "incident.verify", "incident.correct", "incident.merge",
            "report.review")


def _role_engine(role: str):
    eng = create_engine(TEST_URL, pool_pre_ping=True)

    @event.listens_for(eng, "connect")
    def _set_role(dbapi_conn, _record):  # noqa: ANN001
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET ROLE {role}")
        dbapi_conn.commit()
    return eng


@pytest.fixture
def as_roles(engine, monkeypatch):
    """Citizen routes as app_citizen; the worker as app_worker."""
    citizen = _role_engine("app_citizen")
    for module in ("app.modules.subscriptions.router", "app.modules.alerting.router"):
        monkeypatch.setattr(f"{module}.get_engine", lambda: citizen)
    yield
    citizen.dispose()


@pytest.fixture
def drain_as_worker(as_roles, engine):
    from app.core.config import get_settings
    from app.infrastructure.workers.runner import Worker
    worker_engine = _role_engine("app_worker")
    worker = Worker(get_settings(), worker_id="alert-test-worker", engine=worker_engine)

    def _drain(max_rounds: int = 30) -> None:
        for _ in range(max_rounds):
            if worker.process_batch() == 0:
                break
        else:
            raise AssertionError("outbox did not drain")
        with engine.connect() as conn:
            dead = conn.execute(text("SELECT event_type, last_error FROM ops.outbox_events WHERE status = 'dead'")).all()
        assert not dead, dead
    yield _drain
    worker_engine.dispose()


def device(client) -> dict:
    r = client.post("/api/v1/installations", json={"platform": "android", "app_version": "0.1.0"})
    assert r.status_code == 201, r.text
    return {"X-Installation-Token": r.json()["installation_token"]}


# A route along the Bamenda road that passes ~300 m east of BASE (where reports land).
def route_coords():
    a = offset(BASE_LAT, BASE_LON, east_m=300, north_m=-3000)
    b = offset(BASE_LAT, BASE_LON, east_m=300, north_m=3000)
    return [[a[1], a[0]], [b[1], b[0]]]


def save_route(client, h, **sub) -> str:
    r = client.post("/api/v1/saved-routes", headers=h, json={
        "name": "Bambili to Bamenda", "route": {"type": "LineString", "coordinates": route_coords()},
        "corridor_width_m": 1000})
    assert r.status_code == 201, r.text
    s = client.post("/api/v1/alert-subscriptions", headers=h, json={"saved_route_id": r.json()["id"], **sub})
    assert s.status_code == 201, s.text
    return r.json()["id"]


def save_place(client, h, lat=BASE_LAT, lon=BASE_LON, radius_m=1000, **sub) -> str:
    r = client.post("/api/v1/saved-locations", headers=h, json={
        "name": "Home", "location": {"latitude": lat, "longitude": lon}, "radius_m": radius_m})
    assert r.status_code == 201, r.text
    s = client.post("/api/v1/alert-subscriptions", headers=h, json={"saved_location_id": r.json()["id"], **sub})
    assert s.status_code == 201, s.text
    return r.json()["id"]


def feed(client, h) -> list[dict]:
    r = client.get("/api/v1/alerts", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def incident_id(engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text("SELECT id FROM incident.incidents ORDER BY created_at LIMIT 1")).scalar())


# --- Device credentials and ownership -------------------------------------------------------------

def test_personal_routes_need_the_installation_token(client, as_roles):
    assert client.get("/api/v1/saved-locations").status_code == 401
    assert client.get("/api/v1/saved-locations", headers={"X-Installation-Token": "ins_" + "A" * 43}).status_code == 401
    me, other = device(client), device(client)
    place = save_place(client, me)
    assert [p["id"] for p in client.get("/api/v1/saved-locations", headers=me).json()["items"]] == [place]
    assert client.get("/api/v1/saved-locations", headers=other).json()["items"] == []
    assert client.get(f"/api/v1/saved-locations/{place}", headers=other).status_code == 404
    assert client.delete(f"/api/v1/saved-locations/{place}", headers=other).status_code == 404
    assert client.patch(f"/api/v1/saved-locations/{place}", headers=me, json={"radius_m": 2000}).json()["radius_m"] == 2000
    dup = client.post("/api/v1/alert-subscriptions", headers=me, json={"saved_location_id": place})
    assert dup.status_code == 409
    assert client.delete(f"/api/v1/saved-locations/{place}", headers=me).status_code == 204
    assert client.get("/api/v1/alert-subscriptions", headers=me).json()["items"] == []  # cascaded


def test_push_registration_hides_the_token_and_moves_on_reinstall(client, engine, as_roles):
    first, second = device(client), device(client)
    token = "fcm-" + "x" * 60
    a = client.post("/api/v1/devices/push-endpoints", headers=first, json={"token": token})
    assert a.status_code == 201 and "token" not in a.json()
    b = client.post("/api/v1/devices/push-endpoints", headers=second, json={"token": token})
    assert b.json()["id"] == a.json()["id"]  # same FCM token now belongs to the new installation
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM identity.push_endpoints WHERE status = 'active'")).scalar() == 1


# --- The Mile 5 story ------------------------------------------------------------------------------

def test_route_subscriber_is_warned_about_an_unconfirmed_shooting(client, engine, as_roles, drain_as_worker):
    h = device(client)
    client.post("/api/v1/devices/push-endpoints", headers=h, json={"token": "fcm-" + "y" * 60})
    save_route(client, h)
    far = device(client)
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=25_000)
    save_place(client, far, lat=lat, lon=lon)

    assert submit(client, category="shooting").status_code == 201
    drain_as_worker()

    items = feed(client, h)
    assert len(items) == 1
    a = items[0]
    assert a["status"] == "active" and a["verification_status"] == "unverified"
    assert a["message"] == "Shooting reported nearby. Not confirmed yet."
    assert "Unconfirmed" in a["uncertainty"] and a["distribution_level"] == 1
    assert a["severity"] == "high"  # unknown severity falls back to the type's default
    assert a["because"] == {"kind": "route", "name": "Bambili to Bamenda"}
    # Public location only: snapped to the security grid, never the reported point.
    assert a["location"]["precision_m"] == 500
    assert (round(a["location"]["latitude"], 6), round(a["location"]["longitude"], 6)) != (BASE_LAT, BASE_LON)
    assert feed(client, far) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM alerting.alert_deliveries WHERE delivery_status = 'queued'")).scalar() == 1

    # A second report about the same event is not a new alert, and not a new notification.
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=80)
    submit(client, category="shooting", lat=lat, lon=lon)
    drain_as_worker()
    assert len(feed(client, h)) == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM alerting.alert_versions")).scalar() == 1

    ack = client.post(f"/api/v1/alerts/{a['id']}/acknowledgements", headers=h)
    assert ack.status_code == 201 and feed(client, h)[0]["acknowledged"] is True


def test_verification_upgrades_and_rejection_withdraws(client, engine, as_roles, drain_as_worker, staff):
    h = device(client)
    save_place(client, h)
    submit(client, category="shooting")
    drain_as_worker()
    iid = incident_id(engine)
    reviewer = staff(*REVIEWER)

    assert client.post(f"/api/v1/incidents/{iid}/verify", headers=reviewer,
                       json={"decision": "verified", "reason": "Two calls confirm gunfire"}).status_code == 200
    drain_as_worker()
    a = feed(client, h)[0]
    assert a["verification_status"] == "verified" and a["distribution_level"] == 2
    assert a["message"] == "Shooting confirmed nearby by Sisay reviewers."
    detail = client.get(f"/api/v1/alerts/{a['id']}", headers=h).json()
    assert [u["version"] for u in detail["updates"]] == [1, 2]

    client.post(f"/api/v1/incidents/{iid}/verify", headers=reviewer,
                json={"decision": "rejected", "reason": "It was fireworks at a wedding"})
    drain_as_worker()
    a = feed(client, h)[0]
    assert a["status"] == "withdrawn" and a["message"].startswith("Withdrawn:")
    staff_view = client.get(f"/api/v1/incidents/{iid}/alerts", headers=reviewer).json()["items"][0]
    assert staff_view["status"] == "withdrawn" and staff_view["people_reached"] == 1
    assert [v["distribution_level_code"] for v in staff_view["versions"]] == ["subscribers", "priority", "priority"]
    with engine.connect() as conn:
        levels = conn.execute(text("SELECT new_level FROM alerting.alert_distribution_decisions ORDER BY created_at")).scalars().all()
    assert levels == ["subscribers", "priority", "withdrawn"]


def test_incident_over_ends_the_alert(client, engine, as_roles, drain_as_worker, staff):
    h = device(client)
    save_place(client, h)
    submit(client, category="fire")
    drain_as_worker()
    iid = incident_id(engine)
    client.patch(f"/api/v1/incidents/{iid}", headers=staff(*REVIEWER),
                 json={"operational_status": "resolved", "reason": "Fire brigade put it out"})
    drain_as_worker()
    a = feed(client, h)[0]
    assert a["status"] == "expired" and a["message"].startswith("Over:")


# --- Filters and protections -----------------------------------------------------------------------

def test_category_and_severity_filters(client, as_roles, drain_as_worker):
    floods_only, critical_only, everything = device(client), device(client), device(client)
    save_place(client, floods_only, categories=["flood"])
    save_place(client, critical_only, minimum_severity="critical")
    save_place(client, everything, minimum_severity="medium")  # contract spelling of moderate
    submit(client, category="shooting")
    drain_as_worker()
    assert feed(client, floods_only) == [] and feed(client, critical_only) == []
    assert len(feed(client, everything)) == 1
    bad = client.post("/api/v1/saved-locations", headers=everything,
                      json={"name": "x", "location": {"latitude": BASE_LAT, "longitude": BASE_LON}})
    sub = client.post("/api/v1/alert-subscriptions", headers=everything,
                      json={"saved_location_id": bad.json()["id"], "categories": ["dragons"]})
    assert sub.status_code == 422


def test_protected_category_waits_for_publication_approval(client, engine, as_roles, drain_as_worker, staff):
    h = device(client)
    save_place(client, h)
    submit(client, category="kidnapping")
    drain_as_worker()
    assert feed(client, h) == []
    with engine.begin() as conn:  # the protected category's publication delay has passed
        conn.execute(text("UPDATE incident.incidents SET created_at = now() - interval '3 hours'"))
    from app.modules.disclosure.projection_service import enqueue_freshness_sweep
    with engine.begin() as conn:
        enqueue_freshness_sweep(conn)
    drain_as_worker()
    assert feed(client, h) == []  # still held: nobody has approved it
    reviewer = staff(*REVIEWER)
    item = client.get("/api/v1/review/items?item_type=publication_review", headers=reviewer).json()["items"][0]
    assert client.post(f"/api/v1/review/items/{item['id']}/resolve", headers=reviewer,
                       json={"resolution": "approved", "reason": "Family consented"}).status_code == 200
    drain_as_worker()
    a = feed(client, h)
    assert len(a) == 1 and a[0]["location"]["precision_m"] == 5000


def test_an_old_offline_observation_does_not_raise_an_alert(client, as_roles, drain_as_worker):
    h = device(client)
    save_place(client, h)
    two_days_ago = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    submit(client, category="fire", observed_at=two_days_ago)
    drain_as_worker()
    assert feed(client, h) == []


def test_fan_out_is_idempotent(client, engine, as_roles, drain_as_worker):
    from app.modules.alerting.service import fan_out
    h = device(client)
    save_place(client, h)
    submit(client, category="fire")
    drain_as_worker()
    with engine.begin() as conn:
        aid, vid = conn.execute(text("SELECT alert_id, id FROM alerting.alert_versions")).one()
        assert fan_out(conn, uuid.UUID(str(aid)), uuid.UUID(str(vid)), True) == (0, 0)
    assert len(feed(client, h)) == 1
