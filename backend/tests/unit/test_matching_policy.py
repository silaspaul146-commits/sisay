import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.incidents.matching_policy import (
    AMBIGUOUS_THRESHOLD,
    CandidateFacts,
    Outcome,
    ReportFacts,
    decide,
    spatial_score,
    state_score,
    temporal_score,
)

T0 = datetime(2026, 11, 14, 8, 30, tzinfo=UTC)
REPORT = ReportFacts(category_id=1, observed_at=T0, match_time_window=timedelta(hours=6), default_severity="high")


def candidate(**overrides) -> CandidateFacts:
    base = dict(incident_id=uuid.uuid4(), category_weight=1.0, distance_m=50.0, allowed_m=1000.0,
                first_observed_at=T0 - timedelta(minutes=30), last_observed_at=T0 + timedelta(minutes=10),
                operational_status="active", verification_status="unverified", severity="unknown")
    base.update(overrides)
    return CandidateFacts(**base)


def test_no_candidates_creates_provisional_incident():
    d = decide(REPORT, [])
    assert d.outcome == Outcome.NO_MATCH
    assert d.selected_incident_id is None


def test_close_same_category_same_time_is_strong_match():
    c = candidate()
    d = decide(REPORT, [c])
    assert d.outcome == Outcome.STRONG_MATCH
    assert d.selected_incident_id == c.incident_id


def test_proximity_alone_is_never_a_strong_match():
    # Same place, but observed at the very edge of the time window.
    c = candidate(distance_m=0.0, first_observed_at=T0 - timedelta(hours=8), last_observed_at=T0 - timedelta(hours=6))
    d = decide(REPORT, [c])
    assert d.outcome != Outcome.STRONG_MATCH


def test_compatible_category_below_floor_is_only_ambiguous():
    c = candidate(category_weight=0.6)  # e.g. kidnapping vs missing_person
    d = decide(REPORT, [c])
    assert d.outcome == Outcome.AMBIGUOUS
    assert "floor" in d.reason


def test_two_close_candidates_are_ambiguous_not_forced():
    a, b = candidate(distance_m=40.0), candidate(distance_m=60.0)
    d = decide(REPORT, [a, b])
    assert d.outcome == Outcome.AMBIGUOUS
    assert "margin" in d.reason
    assert len(d.candidates) == 2


def test_contradiction_blocks_strong_match():
    c = candidate(severity="low")  # report category default is high: two levels apart
    d = decide(REPORT, [c])
    assert d.outcome == Outcome.AMBIGUOUS
    assert "severity_two_levels_apart" in d.reason


def test_disputed_incident_halves_state_score():
    assert state_score("active", "disputed") == 0.5
    assert state_score("monitoring", "unverified") == 0.7
    assert state_score("resolved", "verified") == 0.0


def test_far_weak_candidate_is_no_match():
    c = candidate(distance_m=990.0, category_weight=0.5, first_observed_at=T0 - timedelta(hours=11),
                  last_observed_at=T0 - timedelta(hours=5, minutes=50), operational_status="monitoring")
    d = decide(REPORT, [c])
    assert d.candidates[0].total < AMBIGUOUS_THRESHOLD
    assert d.outcome == Outcome.NO_MATCH


def test_candidates_ranked_best_first_and_explanation_is_complete():
    far, near = candidate(distance_m=800.0), candidate(distance_m=10.0)
    d = decide(REPORT, [far, near])
    assert d.candidates[0].incident_id == near.incident_id
    exp = d.explanation()
    assert exp["policy_version"] == "match-2026.11.1"
    assert len(exp["candidates"]) == 2 and "thresholds" in exp


@pytest.mark.parametrize("distance,allowed,expected", [(0, 100, 1.0), (50, 100, 0.5), (100, 100, 0.0),
                                                       (150, 100, 0.0), (10, 0, 0.0)])
def test_spatial_score(distance, allowed, expected):
    assert spatial_score(distance, allowed) == pytest.approx(expected)


def test_temporal_score_decays_linearly_outside_interval():
    first, last, window = T0, T0 + timedelta(hours=1), timedelta(hours=6)
    assert temporal_score(T0 + timedelta(minutes=30), first, last, window) == 1.0
    assert temporal_score(T0 - timedelta(hours=3), first, last, window) == pytest.approx(0.5)
    assert temporal_score(last + timedelta(hours=6), first, last, window) == 0.0
