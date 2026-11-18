"""Staff API: sign-in, permissions, verification, review queue, associations, merges."""
import pytest
from sqlalchemy import text

from tests.integration.conftest import BASE_LAT, BASE_LON, offset, submit

pytestmark = pytest.mark.integration

REVIEWER = ("incident.view", "incident.assess", "incident.verify", "incident.merge", "report.review")


def scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def bbox(d=0.05):
    return f"{BASE_LON - d},{BASE_LAT - d},{BASE_LON + d},{BASE_LAT + d}"


def one_incident(client, drain, **kw) -> str:
    rid = submit(client, **kw).json()["report_id"]
    drain()
    return rid


def incident_of(engine, report_id) -> str:
    return str(scalar(engine, "SELECT incident_id FROM reporting.reports WHERE id = :id", id=report_id))


# --- Authentication and authorization ---------------------------------------------------------

def test_staff_routes_need_a_valid_token_for_a_provisioned_user(client, staff):
    assert client.get("/api/v1/incidents").status_code == 401
    assert client.get("/api/v1/incidents", headers={"Authorization": "Bearer junk"}).status_code == 401

    headers = staff("incident.view")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["permissions"] == ["incident.view"]
    assert client.get("/api/v1/incidents", headers=headers).status_code == 200


def test_unknown_or_suspended_user_is_refused(client, engine, staff):
    headers = staff("incident.view")
    with engine.begin() as conn:
        conn.execute(text("UPDATE identity.users SET status = 'suspended'"))
    assert client.get("/api/v1/incidents", headers=headers).status_code == 401


def test_revoked_permission_takes_effect_immediately(client, engine, staff):
    headers = staff("incident.view")
    assert client.get("/api/v1/incidents", headers=headers).status_code == 200
    with engine.begin() as conn:
        conn.execute(text("UPDATE identity.platform_permissions SET revoked_at = now()"))
    resp = client.get("/api/v1/incidents", headers=headers)
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "insufficient_permission"


def test_viewer_cannot_verify(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    resp = client.post(f"/api/v1/incidents/{iid}/verify", headers=staff("incident.view"),
                       json={"decision": "verified", "reason": "looks right"})
    assert resp.status_code == 403
    assert scalar(engine, "SELECT verification_status FROM incident.incidents") == "unverified"


# --- Incident reads ---------------------------------------------------------------------------

def test_internal_incident_detail_and_reports(client, drain, engine, staff):
    rid = one_incident(client, drain, description="Smoke behind the market")
    iid = incident_of(engine, rid)
    h = staff("incident.view")
    items = client.get("/api/v1/incidents?category=fire", headers=h).json()["items"]
    assert [i["id"] for i in items] == [iid]
    detail = client.get(f"/api/v1/incidents/{iid}", headers=h).json()
    assert detail["public"]["on_map"] is True and abs(detail["location"]["latitude"] - BASE_LAT) < 1e-6
    reports = client.get(f"/api/v1/incidents/{iid}/reports", headers=h).json()["items"]
    assert [r["report_id"] for r in reports] == [rid]
    assert "Smoke" not in str(reports)  # report text is not part of the incident view


# --- Verification and assessments ---------------------------------------------------------------

def test_verification_is_recorded_with_history_and_audit(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    h = staff(*REVIEWER)
    resp = client.post(f"/api/v1/incidents/{iid}/verify", headers=h,
                       json={"decision": "verified", "reason": "Two independent calls confirmed it."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["previous_status"] == "unverified" and resp.json()["verification_status"] == "verified"
    with engine.connect() as conn:
        inc = conn.execute(text("SELECT verification_status, is_provisional FROM incident.incidents")).one()
        assert inc.verification_status == "verified" and not inc.is_provisional
        assert conn.execute(text("SELECT count(*) FROM ops.audit_logs WHERE action = 'incident.verify' "
                                 "AND actor_id IS NOT NULL")).scalar() == 1
    drain()
    feature = client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"][0]
    assert feature["properties"]["verification_status"] == "verified"
    events = [e["event_type"] for e in client.get(f"/api/v1/incidents/{iid}/history", headers=h).json()["items"]]
    assert "verification_assessed" in events and "report_auto_create_provisional" in events


def test_rejection_removes_the_incident_from_the_map_immediately(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    public_id = client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"][0]["id"]
    resp = client.post(f"/api/v1/incidents/{iid}/verify", headers=staff(*REVIEWER),
                       json={"decision": "rejected", "reason": "Hoax confirmed by local contact."})
    assert resp.status_code == 200
    # Before the worker runs: already gone (fail closed).
    assert client.get(f"/api/v1/public/incidents/{public_id}").status_code == 404
    drain()
    assert client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"] == []
    removed = client.get("/api/v1/public/incidents/removals?since=2000-01-01T00:00:00Z").json()["items"]
    assert [r["public_id"] for r in removed] == [public_id]


def test_severity_assessment_updates_incident_and_map(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    h = staff(*REVIEWER)
    resp = client.post(f"/api/v1/incidents/{iid}/assessments", headers=h,
                       json={"assessment_type": "severity", "assessment_value": "high", "rationale": "3 houses"})
    assert resp.status_code == 201, resp.text
    drain()
    assert client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"][0]["properties"]["severity"] == "high"
    bad = client.post(f"/api/v1/incidents/{iid}/assessments", headers=h,
                      json={"assessment_type": "severity", "assessment_value": "apocalyptic"})
    assert bad.status_code == 422
    assert scalar(engine, "SELECT severity FROM incident.incidents") == "high"
    via_verify = client.post(f"/api/v1/incidents/{iid}/assessments", headers=h,
                             json={"assessment_type": "verification", "assessment_value": "verified"})
    assert via_verify.status_code == 422


# --- Review queue and associations --------------------------------------------------------------

def _ambiguous(client, drain, engine):
    one_incident(client, drain)
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=600)
    one_incident(client, drain, lat=lat, lon=lon)
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=300)
    rid = one_incident(client, drain, lat=lat, lon=lon)
    assert scalar(engine, "SELECT incident_id FROM reporting.reports WHERE id = :id", id=rid) is None
    return rid


def test_reviewer_resolves_an_ambiguous_match_by_association(client, drain, engine, staff):
    rid = _ambiguous(client, drain, engine)
    h = staff(*REVIEWER)
    items = client.get("/api/v1/review/items?item_type=ambiguous_match", headers=h).json()["items"]
    assert len(items) == 1 and items[0]["report_id"] == rid
    assert items[0]["summary"]["category"] == "fire" and items[0]["summary"]["candidate_count"] == 2
    assert items[0]["summary"]["report_reference"]
    item_id = items[0]["id"]

    detail = client.get(f"/api/v1/review/items/{item_id}", headers=h).json()
    assert len(detail["match"]["candidates"]) == 2 and detail["report"]["location"]["accuracy_m"] == 20
    target = detail["match"]["candidates"][0]["incident_id"]
    cands = client.get(f"/api/v1/incidents/{target}/matching-candidates", headers=h).json()["items"]
    assert [c["report_id"] for c in cands] == [rid]

    assert client.post(f"/api/v1/review/items/{item_id}/claim", headers=h).status_code == 200
    other = staff(*REVIEWER)
    assert client.post(f"/api/v1/review/items/{item_id}/claim", headers=other).status_code == 409

    resp = client.post(f"/api/v1/incidents/{target}/report-associations", headers=h,
                       json={"report_id": rid, "reason": "Same fire, seen from the road."})
    assert resp.status_code == 200, resp.text
    with engine.connect() as conn:
        assert str(conn.execute(text("SELECT incident_id FROM reporting.reports WHERE id = :id"),
                                {"id": rid}).scalar()) == target
        assert conn.execute(text("SELECT report_count FROM incident.incidents WHERE id = :id"),
                            {"id": target}).scalar() == 2
        assert conn.execute(text("SELECT action FROM reporting.report_association_history "
                                 "WHERE report_id = :id"), {"id": rid}).scalar() == "review_assign"
        item = conn.execute(text("SELECT status, resolution FROM review.review_items WHERE id = :id"),
                            {"id": item_id}).one()
        assert item.status == "resolved" and item.resolution == "associated"


def test_reassociation_moves_counts_and_keeps_history(client, drain, engine, staff):
    rid_a = one_incident(client, drain)
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=5000)
    rid_b = one_incident(client, drain, lat=lat, lon=lon)
    a, b = incident_of(engine, rid_a), incident_of(engine, rid_b)
    resp = client.post(f"/api/v1/incidents/{b}/report-associations", headers=staff(*REVIEWER),
                       json={"report_id": rid_a, "reason": "Reporter pin was wrong."})
    assert resp.status_code == 200
    counts = dict(scalar_rows(engine, "SELECT id::text, report_count FROM incident.incidents"))
    assert counts == {a: 0, b: 2}
    actions = [r[0] for r in scalar_rows(engine, "SELECT action FROM reporting.report_association_history "
                                                 "WHERE report_id = :id ORDER BY created_at", id=rid_a)]
    assert actions == ["auto_create_provisional", "reassign"]


def scalar_rows(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def test_quarantined_report_accepted_by_reviewer_is_matched(client, drain, engine, staff):
    rid = submit(client).json()["report_id"]
    with engine.begin() as conn:  # simulate the abuse control firing
        conn.execute(text("UPDATE reporting.reports SET intake_status = 'quarantined', "
                          "intake_reason = 'test' WHERE id = :id"), {"id": rid})
    drain()
    h = staff(*REVIEWER)
    items = client.get("/api/v1/review/items?item_type=report_quarantine", headers=h).json()["items"]
    assert len(items) == 1
    bad = client.post(f"/api/v1/review/items/{items[0]['id']}/resolve", headers=h, json={"resolution": "approved"})
    assert bad.status_code == 422
    resp = client.post(f"/api/v1/review/items/{items[0]['id']}/resolve", headers=h,
                       json={"resolution": "accepted", "reason": "Verified by phone."})
    assert resp.status_code == 200, resp.text
    drain()
    with engine.connect() as conn:
        r = conn.execute(text("SELECT intake_status, incident_id FROM reporting.reports WHERE id = :id"),
                         {"id": rid}).one()
        assert r.intake_status == "accepted" and r.incident_id is not None
        attempts = conn.execute(text("SELECT attempt, outcome FROM reporting.report_match_decisions "
                                     "WHERE report_id = :id ORDER BY attempt"), {"id": rid}).all()
        assert [(a.attempt, a.outcome) for a in attempts] == [(1, "ineligible"), (2, "no_match")]


def test_publication_review_gates_protected_categories(client, drain, engine, staff):
    one_incident(client, drain, category="kidnapping")
    with engine.begin() as conn:  # publication delay has passed
        conn.execute(text("UPDATE incident.incidents SET created_at = now() - interval '3 hours'"))
    from app.modules.disclosure.projection_service import enqueue_freshness_sweep
    with engine.begin() as conn:
        enqueue_freshness_sweep(conn)
    drain()
    assert client.get(f"/api/v1/public/incidents?bbox={bbox(0.2)}").json()["features"] == []

    items = client.get("/api/v1/review/items?item_type=publication_review",
                       headers=staff(*REVIEWER)).json()["items"]
    assert len(items) == 1
    # report.review alone cannot approve publication
    weak = client.post(f"/api/v1/review/items/{items[0]['id']}/resolve", headers=staff("report.review"),
                       json={"resolution": "approved"})
    assert weak.status_code == 403
    ok = client.post(f"/api/v1/review/items/{items[0]['id']}/resolve", headers=staff(*REVIEWER),
                     json={"resolution": "approved", "reason": "Family consents; area generalized."})
    assert ok.status_code == 200
    drain()
    features = client.get(f"/api/v1/public/incidents?bbox={bbox(0.2)}").json()["features"]
    assert len(features) == 1 and features[0]["properties"]["precision_m"] == 5000


def test_rejected_publication_is_not_reopened_by_the_sweep(client, drain, engine, staff):
    one_incident(client, drain, category="kidnapping")
    with engine.begin() as conn:
        conn.execute(text("UPDATE incident.incidents SET created_at = now() - interval '3 hours'"))
    from app.modules.disclosure.projection_service import enqueue_freshness_sweep
    with engine.begin() as conn:
        enqueue_freshness_sweep(conn)
    drain()
    h = staff(*REVIEWER)
    item = client.get("/api/v1/review/items?item_type=publication_review", headers=h).json()["items"][0]
    client.post(f"/api/v1/review/items/{item['id']}/resolve", headers=h, json={"resolution": "rejected"})
    drain()
    with engine.begin() as conn:
        enqueue_freshness_sweep(conn)
    drain()
    assert client.get("/api/v1/review/items?item_type=publication_review", headers=h).json()["items"] == []
    assert client.get(f"/api/v1/public/incidents?bbox={bbox(0.2)}").json()["features"] == []


# --- Merge ------------------------------------------------------------------------------------

def test_merge_moves_reports_and_redirects(client, drain, engine, staff):
    rid_a = one_incident(client, drain)
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=5000)
    rid_b = one_incident(client, drain, lat=lat, lon=lon)
    a, b = incident_of(engine, rid_a), incident_of(engine, rid_b)
    source_public = [f["id"] for f in client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"]]
    assert len(source_public) == 2
    h = staff(*REVIEWER)

    resp = client.post(f"/api/v1/incidents/{a}/merge", headers=h,
                       json={"source_incident_id": b, "reason": "Same fire; second pin was wrong."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["reports_moved"] == 1 and resp.json()["redirect_to"] == a

    with engine.connect() as conn:
        src = conn.execute(text("SELECT operational_status, merged_into_incident_id, report_count "
                                "FROM incident.incidents WHERE id = :id"), {"id": b}).one()
        assert src.operational_status == "merged" and str(src.merged_into_incident_id) == a and src.report_count == 0
        assert conn.execute(text("SELECT report_count FROM incident.incidents WHERE id = :id"), {"id": a}).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM reporting.reports WHERE incident_id = :id"),
                            {"id": a}).scalar() == 2
        assert conn.execute(text("SELECT count(*) FROM reporting.report_association_history "
                                 "WHERE action = 'merge_reassign'")).scalar() == 1
    # The merged incident left the map in the merge transaction.
    assert len(client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"]) == 1
    drain()
    assert client.get(f"/api/v1/incidents/{b}", headers=h).json()["redirect_to"] == a

    # No merging into a merged incident, and no re-merging.
    assert client.post(f"/api/v1/incidents/{b}/merge", headers=h,
                       json={"source_incident_id": a, "reason": "cycle attempt"}).status_code == 409
    assert client.post(f"/api/v1/incidents/{a}/merge", headers=h,
                       json={"source_incident_id": b, "reason": "again"}).status_code == 409
    assert client.post(f"/api/v1/incidents/{a}/merge", headers=h,
                       json={"source_incident_id": a, "reason": "self"}).status_code == 422


# --- Corrections, status changes and unlinking (PATCH /incidents, unassociate) -----------------

EDITOR = REVIEWER + ("incident.correct",)


def test_status_change_is_recorded_and_shown_publicly(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    h = staff(*REVIEWER)
    resp = client.patch(f"/api/v1/incidents/{iid}", headers=h,
                        json={"operational_status": "resolved", "reason": "Fire service confirmed it is out."})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] == ["operational_status"] and body["operational_status"] == "resolved"
    drain()
    feature = client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"][0]
    assert feature["properties"]["lifecycle"] == "resolved"
    events = [e for e in client.get(f"/api/v1/incidents/{iid}/history", headers=h).json()["items"]
              if e["event_type"] == "operational_assessed"]
    assert events[0]["new_value"] == "resolved" and events[0]["reason"].startswith("Fire service")
    assert scalar(engine, "SELECT count(*) FROM ops.audit_logs WHERE action = 'incident.status_change'") == 1
    # merged/withdrawn are not settable here
    bad = client.patch(f"/api/v1/incidents/{iid}", headers=h, json={"operational_status": "merged", "reason": "x" * 5})
    assert bad.status_code == 422


def test_corrections_keep_old_values_and_need_their_own_permission(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    assessor = staff(*REVIEWER)  # no incident.correct
    denied = client.patch(f"/api/v1/incidents/{iid}", headers=assessor,
                          json={"title": "Market fire", "reason": "Clearer title"})
    assert denied.status_code == 403
    h = staff(*EDITOR)
    resp = client.patch(f"/api/v1/incidents/{iid}", headers=h,
                        json={"title": "Market fire", "category": "explosion",
                              "reason": "Gas cylinder explosion, not a fire."})
    assert resp.status_code == 200, resp.text
    assert sorted(resp.json()["changed"]) == ["category", "title"] and resp.json()["category"] == "explosion"
    rows = scalar_rows(engine, "SELECT field_name, previous_value, corrected_value FROM incident.incident_corrections "
                               "ORDER BY field_name")
    assert [r.field_name for r in rows] == ["category_id", "title"]
    assert rows[1].corrected_value == "Market fire"
    history = [e["event_type"] for e in client.get(f"/api/v1/incidents/{iid}/history", headers=h).json()["items"]]
    assert "corrected_title" in history and "corrected_category_id" in history
    unknown = client.patch(f"/api/v1/incidents/{iid}", headers=h, json={"category": "dragons", "reason": "test"})
    assert unknown.status_code == 422


def test_location_correction_hides_the_old_public_point_until_regenerated(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    public_id = client.get(f"/api/v1/public/incidents?bbox={bbox()}").json()["features"][0]["id"]
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=8000)
    resp = client.patch(f"/api/v1/incidents/{iid}", headers=staff(*EDITOR),
                        json={"location": {"latitude": lat, "longitude": lon, "uncertainty_m": 150},
                              "reason": "Reporter pinned their own house; event was at Mile 4."})
    assert resp.status_code == 200, resp.text
    assert client.get(f"/api/v1/public/incidents/{public_id}").status_code == 404  # fail closed before the worker
    drain()
    assert client.get(f"/api/v1/public/incidents?bbox={bbox(0.02)}").json()["features"] == []
    moved = client.get(f"/api/v1/public/incidents?bbox={lon - 0.03},{lat - 0.03},{lon + 0.03},{lat + 0.03}").json()
    assert len(moved["features"]) == 1


def test_stale_version_is_rejected(client, drain, engine, staff):
    iid = incident_of(engine, one_incident(client, drain))
    h = staff(*EDITOR)
    version = client.get(f"/api/v1/incidents/{iid}", headers=h).json()["version"]
    ok = client.patch(f"/api/v1/incidents/{iid}", headers=h,
                      json={"severity": "high", "reason": "Three houses", "expected_version": version})
    assert ok.status_code == 200 and ok.json()["version"] == version + 1
    stale = client.patch(f"/api/v1/incidents/{iid}", headers=h,
                         json={"severity": "low", "reason": "Small", "expected_version": version})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"
    assert scalar(engine, "SELECT severity FROM incident.incidents") == "high"
    empty = client.patch(f"/api/v1/incidents/{iid}", headers=h, json={"reason": "nothing"})
    assert empty.status_code == 422


def test_unlinking_a_report_keeps_it_and_its_history(client, drain, engine, staff):
    rid_a = one_incident(client, drain)
    lat, lon = offset(BASE_LAT, BASE_LON, east_m=100)
    rid_b = one_incident(client, drain, lat=lat, lon=lon)
    iid = incident_of(engine, rid_a)
    assert incident_of(engine, rid_b) == iid
    h = staff(*REVIEWER)
    resp = client.post(f"/api/v1/reports/{rid_b}/unassociate", headers=h,
                       json={"reason": "Different fire across the valley."})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"report_id": rid_b, "result": "unassociated", "previous_incident_id": iid,
                           "incident_remaining_reports": 1}
    assert scalar(engine, "SELECT incident_id FROM reporting.reports WHERE id = :id", id=rid_b) is None
    actions = [r[0] for r in scalar_rows(engine, "SELECT action FROM reporting.report_association_history "
                                                 "WHERE report_id = :id ORDER BY created_at", id=rid_b)]
    assert actions[-1] == "review_unassign"
    again = client.post(f"/api/v1/reports/{rid_b}/unassociate", headers=h, json={"reason": "again"})
    assert again.json()["result"] == "unchanged"
    # it can be linked again later
    relink = client.post(f"/api/v1/incidents/{iid}/report-associations", headers=h,
                         json={"report_id": rid_b, "reason": "Same fire after all."})
    assert relink.status_code == 200
    assert scalar(engine, "SELECT report_count FROM incident.incidents WHERE id = :id", id=iid) == 2
    assert client.post(f"/api/v1/reports/{rid_b}/unassociate", headers=staff("incident.view"),
                       json={"reason": "nope"}).status_code == 403
