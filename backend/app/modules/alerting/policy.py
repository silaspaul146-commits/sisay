"""Alert policy `alert-2026.11.1` (PRD 8, Engineering pack 7.3-7.6, DB spec 4.9, DECISIONS U-8).

Pure functions: given an incident's state, decide whether people should be warned, at which level,
with which words, over which area and until when. No human approval gate (U-8): every alert says
how sure we are, starts with nearby subscribers, and widens only when the incident is verified as
serious. Report counts never widen an alert on their own (BR-07, BR-08).

Levels (DB vocabulary; PRD 8 in brackets):
  internal    staff only (held: e.g. a protected category awaiting publication approval)
  subscribers people whose saved place or route is near        [Level 1, localized]
  priority    the same people, high-priority push               [Level 2, expanded]
There is no "everyone in an area" broadcast: the platform does not track where phones are.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

POLICY_VERSION = "alert-2026.11.1"

SEVERITY_RANK = {"unknown": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}
MAX_ALERT_RADIUS_M = 50_000
MIN_LIFETIME = timedelta(hours=1)
WINDOW_FLOOR, WINDOW_CEILING = timedelta(hours=2), timedelta(hours=72)


@dataclass(frozen=True)
class IncidentState:
    category_code: str
    category_name: str
    default_severity: str
    severity: str
    verification_status: str
    operational_status: str
    location_uncertainty_m: int
    last_observed_at: datetime
    match_radius_m: int
    match_time_window: timedelta
    min_alert_radius_m: int
    review_before_publish: bool
    publication_approved: bool


@dataclass(frozen=True)
class CurrentAlert:
    status: str               # active | withdrawn | expired
    distribution_level: str
    message: str
    expires_at: datetime


@dataclass(frozen=True)
class Decision:
    action: str               # none | create | update | withdraw | over | expire | refresh
    level: str | None = None
    message: str | None = None
    uncertainty: str | None = None
    status: str = "active"
    notify: bool = True
    radius_m: int | None = None
    expires_at: datetime | None = None
    effective_severity: str | None = None
    reason: str = ""


def effective_severity(s: IncidentState) -> str:
    """Nobody has rated a new incident yet: use its type's default (Shooting = high) so the first
    warning is not blocked by 'unknown' (DB spec A-7 allows a category policy to override)."""
    return s.default_severity if s.severity == "unknown" else s.severity


def alert_window(s: IncidentState) -> timedelta:
    return min(max(s.match_time_window, WINDOW_FLOOR), WINDOW_CEILING)


def alert_radius(s: IncidentState) -> int:
    return min(max(s.min_alert_radius_m, s.match_radius_m) + max(s.location_uncertainty_m, 0), MAX_ALERT_RADIUS_M)


def level_for(s: IncidentState) -> str:
    if s.verification_status == "verified" and SEVERITY_RANK[effective_severity(s)] >= SEVERITY_RANK["high"]:
        return "priority"
    return "subscribers"


def wording(s: IncidentState) -> tuple[str, str]:
    """(message, uncertainty). Plain words, never 'safe', never a count presented as proof."""
    name = s.category_name.lower()
    if s.verification_status == "verified":
        return (f"{s.category_name} confirmed nearby by Sisay reviewers.",
                "Verified. The location shown is approximate.")
    if s.verification_status == "disputed":
        return (f"Update: the report of {name} nearby is disputed.",
                "Disputed: some information says this may not be accurate.")
    return (f"{s.category_name} reported nearby. Not confirmed yet.",
            "Unconfirmed: based on reports from people in the area. The location shown is approximate.")


def decide(s: IncidentState, current: CurrentAlert | None, now: datetime) -> Decision:
    active = current is not None and current.status == "active"
    name = s.category_name.lower()

    if s.operational_status == "merged":
        # The surviving incident carries the warning; tell nobody twice.
        return Decision("withdraw", level=current.distribution_level, status="withdrawn", notify=False,
                        message=f"This {name} report was combined with another one.",
                        uncertainty="Merged into another incident.", reason="incident merged") \
            if active else Decision("none", reason="merged, no active alert")
    if s.verification_status == "rejected" or s.operational_status == "withdrawn":
        return Decision("withdraw", level=current.distribution_level, status="withdrawn",
                        message=f"Withdrawn: the earlier warning about {name} was not accurate.",
                        uncertainty="Our reviewers found this report was not accurate.",
                        reason="incident rejected or withdrawn") \
            if active else Decision("none", reason="rejected, no active alert")
    if s.operational_status in ("resolved", "closed"):
        return Decision("over", level=current.distribution_level, status="expired",
                        message=f"Over: the {name} reported nearby is no longer happening.",
                        uncertainty="Reviewers marked this incident as over.", reason="incident over") \
            if active else Decision("none", reason="over, no active alert")

    if s.review_before_publish and not s.publication_approved:
        return Decision("none", level="internal", reason="protected category awaiting publication approval")

    expires = max(s.last_observed_at + alert_window(s), now + MIN_LIFETIME)
    if not active:
        if now - s.last_observed_at > alert_window(s):
            # A late (offline-synced) or old observation is not a new event (Engineering pack 7.6).
            return Decision("none", reason="observation too old to warn about")
        if current is not None and current.status == "expired" and s.last_observed_at <= current.expires_at:
            return Decision("none", reason="expired; nothing new observed since")
    if active and now >= current.expires_at:
        return Decision("expire", level=current.distribution_level, status="expired", notify=False,
                        message=current.message, uncertainty="This warning has expired.", reason="expired")

    level = level_for(s)
    message, uncertainty = wording(s)
    common = dict(level=level, message=message, uncertainty=uncertainty, radius_m=alert_radius(s),
                  expires_at=expires, effective_severity=effective_severity(s))
    if not active:
        return Decision("create", reason="eligible incident", **common)
    if level != current.distribution_level or message != current.message:
        return Decision("update", reason="material change: " + (
            f"level {current.distribution_level} -> {level}" if level != current.distribution_level else "status wording"),
            **common)
    return Decision("refresh", notify=False, reason="no material change", **common)
