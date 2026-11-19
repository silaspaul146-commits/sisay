"""Alert policy decisions (no database)."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.modules.alerting.policy import CurrentAlert, IncidentState, alert_radius, decide, effective_severity

NOW = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
SHOOTING = IncidentState(
    category_code="shooting", category_name="Shooting", default_severity="high", severity="unknown",
    verification_status="unverified", operational_status="active", location_uncertainty_m=20,
    last_observed_at=NOW - timedelta(minutes=3), match_radius_m=750, match_time_window=timedelta(hours=3),
    min_alert_radius_m=1000, review_before_publish=False, publication_approved=False)


def active(level="subscribers", message="Shooting reported nearby. Not confirmed yet.", expires=NOW + timedelta(hours=2)):
    return CurrentAlert("active", level, message, expires)


def test_one_fresh_unconfirmed_report_creates_a_localized_warning():
    d = decide(SHOOTING, None, NOW)
    assert d.action == "create" and d.level == "subscribers" and d.notify
    assert "Not confirmed" in d.message and "Unconfirmed" in d.uncertainty
    assert d.effective_severity == "high" and d.radius_m == 1020
    assert d.expires_at == SHOOTING.last_observed_at + timedelta(hours=3)


def test_assessed_severity_wins_over_the_default():
    assert effective_severity(replace(SHOOTING, severity="low")) == "low"
    assert effective_severity(SHOOTING) == "high"


def test_verified_and_serious_widens_but_verified_and_minor_does_not():
    assert decide(replace(SHOOTING, verification_status="verified"), active(), NOW).level == "priority"
    minor = replace(SHOOTING, verification_status="verified", severity="low")
    assert decide(minor, active(), NOW).level == "subscribers"


def test_more_reports_alone_change_nothing():
    d = decide(replace(SHOOTING, location_uncertainty_m=60), active(), NOW)
    assert d.action == "refresh" and not d.notify


def test_rejection_withdraws_and_merge_withdraws_quietly():
    d = decide(replace(SHOOTING, verification_status="rejected"), active(), NOW)
    assert d.action == "withdraw" and d.notify and d.message.startswith("Withdrawn")
    m = decide(replace(SHOOTING, operational_status="merged"), active(), NOW)
    assert m.action == "withdraw" and not m.notify
    assert decide(replace(SHOOTING, verification_status="rejected"), None, NOW).action == "none"


def test_over_ends_the_alert():
    d = decide(replace(SHOOTING, operational_status="resolved"), active(), NOW)
    assert d.action == "over" and d.status == "expired" and d.message.startswith("Over")


def test_protected_categories_wait_for_approval():
    held = replace(SHOOTING, review_before_publish=True)
    assert decide(held, None, NOW).action == "none"
    assert decide(replace(held, publication_approved=True), None, NOW).action == "create"


def test_old_observations_do_not_start_alerts_but_expired_ones_can_return_with_news():
    old = replace(SHOOTING, last_observed_at=NOW - timedelta(hours=5))
    assert decide(old, None, NOW).action == "none"
    expired = CurrentAlert("expired", "subscribers", "x", NOW - timedelta(hours=1))
    assert decide(replace(SHOOTING, last_observed_at=NOW - timedelta(hours=2)), expired, NOW).action == "none"
    assert decide(SHOOTING, expired, NOW).action == "create"  # observed after the old alert expired


def test_active_alert_past_expiry_expires_silently():
    d = decide(replace(SHOOTING, last_observed_at=NOW - timedelta(hours=6)), active(expires=NOW - timedelta(minutes=1)), NOW)
    assert d.action == "expire" and not d.notify


def test_radius_is_capped_and_never_below_the_category_floor():
    assert alert_radius(replace(SHOOTING, match_radius_m=100, location_uncertainty_m=0)) == 1000
    assert alert_radius(replace(SHOOTING, location_uncertainty_m=90_000)) == 50_000


def test_wording_never_says_safe():
    for v in ("unverified", "under_review", "verified", "disputed"):
        d = decide(replace(SHOOTING, verification_status=v), None, NOW)
        assert "safe" not in (d.message + d.uncertainty).lower()
