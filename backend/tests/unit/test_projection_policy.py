from datetime import UTC, datetime, timedelta

from app.modules.disclosure.projection_policy import (
    IncidentFacts,
    PolicyFacts,
    content_hash,
    eligibility,
    freshness_from_age,
    public_lifecycle,
    publication_state,
    uncertainty_note,
)

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def policy(**overrides) -> PolicyFacts:
    base = dict(id=1, public_grid_m=250, public_location_mode="generalized", publish_on_map=True,
                publish_description=False, publish_affected_area=False, review_before_publish=False,
                public_delay=timedelta(0), max_public_age=timedelta(days=7))
    base.update(overrides)
    return PolicyFacts(**base)


def incident(**overrides) -> IncidentFacts:
    base = dict(operational_status="active", verification_status="unverified",
                created_at=NOW - timedelta(hours=1), last_observed_at=NOW - timedelta(hours=1))
    base.update(overrides)
    return IncidentFacts(**base)


def test_unverified_incident_is_publicly_visible():
    assert eligibility(incident(), policy(), NOW, False) == (True, "eligible")


def test_publication_delay_keeps_projection_pending():
    visible, reason = eligibility(incident(created_at=NOW - timedelta(minutes=10)),
                                  policy(public_delay=timedelta(minutes=30)), NOW, False)
    assert not visible and publication_state(visible, reason) == "pending"


def test_review_before_publish_requires_approval():
    p = policy(review_before_publish=True)
    assert eligibility(incident(), p, NOW, False) == (False, "awaiting_publication_review")
    assert eligibility(incident(), p, NOW, True)[0] is True


def test_old_incidents_age_out():
    visible, reason = eligibility(incident(last_observed_at=NOW - timedelta(days=4)),
                                  policy(max_public_age=timedelta(days=3)), NOW, False)
    assert not visible and publication_state(visible, reason) == "withdrawn"


def test_removed_states_are_never_visible():
    for op, ver in (("merged", "unverified"), ("withdrawn", "unverified"), ("active", "rejected")):
        assert public_lifecycle(op, ver) == "removed"
        assert eligibility(incident(operational_status=op, verification_status=ver), policy(), NOW, False)[0] is False


def test_hidden_and_area_only_policies_do_not_map():
    assert eligibility(incident(), policy(public_location_mode="hidden"), NOW, False)[0] is False
    assert eligibility(incident(), policy(publish_on_map=False), NOW, False)[0] is False
    assert eligibility(incident(), policy(public_location_mode="area_only"), NOW, False)[0] is False


def test_uncertainty_note_states_status_confidence_and_precision():
    note = uncertainty_note("unverified", "low", 2000)
    assert "Unverified" in note and "low" in note and "2 km" in note
    assert "250 m" in uncertainty_note("verified", "high", 250)


def test_freshness_bands():
    assert freshness_from_age(NOW - timedelta(hours=1), NOW) == "current"
    assert freshness_from_age(NOW - timedelta(hours=12), NOW) == "aging"
    assert freshness_from_age(NOW - timedelta(days=2), NOW) == "stale"


def test_content_hash_is_order_independent_and_sensitive_to_change():
    a = content_hash({"x": 1, "y": "b"})
    assert a == content_hash({"y": "b", "x": 1})
    assert a != content_hash({"x": 2, "y": "b"})
