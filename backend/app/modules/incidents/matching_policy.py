"""Conservative report-to-incident matching policy, version match-2026.11.1 (DB spec 6.3).

SQL narrows candidates (DB spec 6.2); this module scores them and decides. It is pure so it can be
tested exhaustively. Never edit a released policy in place: copy it under a new version and record
that version in report_match_decisions.policy_version.

Rules that must hold whatever the weights:
- Proximity alone never produces a strong match: every component has its own floor.
- Any contradiction flag blocks a strong match.
- Close competing candidates are ambiguous, not forced.
- No candidate above the ambiguity threshold -> create a provisional incident.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.shared.enums import SEVERITY_RANK

POLICY_VERSION = "match-2026.11.1"

WEIGHTS = {"category": 0.30, "spatial": 0.30, "temporal": 0.25, "state": 0.15}
FLOORS = {"category": 0.7, "spatial": 0.3, "temporal": 0.4, "state": 0.5}
STRONG_THRESHOLD = 0.80
AMBIGUOUS_THRESHOLD = 0.45
STRONG_MARGIN = 0.15


class Outcome(StrEnum):
    STRONG_MATCH = "strong_match"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"
    INELIGIBLE = "ineligible"


@dataclass(frozen=True)
class ReportFacts:
    category_id: int
    observed_at: datetime
    match_time_window: timedelta
    default_severity: str  # category default, used only as a contradiction signal


@dataclass(frozen=True)
class CandidateFacts:
    incident_id: UUID
    category_weight: float  # 1.0 same category, else ref.category_compatibility weight
    distance_m: float
    allowed_m: float  # match radius + report accuracy + incident uncertainty
    first_observed_at: datetime
    last_observed_at: datetime
    operational_status: str
    verification_status: str
    severity: str


@dataclass
class ScoredCandidate:
    incident_id: UUID
    total: float
    distance_m: float
    category: float
    spatial: float
    temporal: float
    state: float
    contradictions: list[str] = field(default_factory=list)

    def meets_floors(self) -> bool:
        return (self.category >= FLOORS["category"] and self.spatial >= FLOORS["spatial"]
                and self.temporal >= FLOORS["temporal"] and self.state >= FLOORS["state"])


@dataclass
class Decision:
    outcome: Outcome
    selected_incident_id: UUID | None
    candidates: list[ScoredCandidate]  # ranked, best first
    reason: str

    def explanation(self) -> dict:
        return {
            "policy_version": POLICY_VERSION,
            "weights": WEIGHTS,
            "floors": FLOORS,
            "thresholds": {"strong": STRONG_THRESHOLD, "ambiguous": AMBIGUOUS_THRESHOLD, "margin": STRONG_MARGIN},
            "reason": self.reason,
            "candidates": [{**asdict(c), "incident_id": str(c.incident_id)} for c in self.candidates],
        }


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def spatial_score(distance_m: float, allowed_m: float) -> float:
    if allowed_m <= 0:
        return 0.0
    return _clamp(1.0 - distance_m / allowed_m)


def temporal_score(observed_at: datetime, first: datetime, last: datetime, window: timedelta) -> float:
    """1.0 inside [first, last]; linear decay to 0 at the window edge."""
    if first <= observed_at <= last:
        return 1.0
    gap = (first - observed_at) if observed_at < first else (observed_at - last)
    window_s = window.total_seconds()
    if window_s <= 0:
        return 0.0
    return _clamp(1.0 - gap.total_seconds() / window_s)


def state_score(operational_status: str, verification_status: str) -> float:
    base = {"active": 1.0, "monitoring": 0.7}.get(operational_status, 0.0)
    if verification_status == "disputed":
        base *= 0.5
    return base


def contradictions(report: ReportFacts, c: CandidateFacts) -> list[str]:
    flags: list[str] = []
    if c.operational_status in ("resolved", "closed") and report.observed_at > c.last_observed_at:
        flags.append("observed_after_incident_resolved")
    if c.severity != "unknown":
        gap = abs(SEVERITY_RANK[c.severity] - SEVERITY_RANK[report.default_severity])
        if gap >= 2:
            flags.append("severity_two_levels_apart")
    if c.verification_status == "rejected":
        flags.append("incident_rejected")
    return flags


def score(report: ReportFacts, c: CandidateFacts) -> ScoredCandidate:
    cat = _clamp(c.category_weight)
    spa = spatial_score(c.distance_m, c.allowed_m)
    tem = temporal_score(report.observed_at, c.first_observed_at, c.last_observed_at, report.match_time_window)
    sta = state_score(c.operational_status, c.verification_status)
    total = (WEIGHTS["category"] * cat + WEIGHTS["spatial"] * spa
             + WEIGHTS["temporal"] * tem + WEIGHTS["state"] * sta)
    return ScoredCandidate(c.incident_id, round(total, 4), round(c.distance_m, 1),
                           round(cat, 4), round(spa, 4), round(tem, 4), round(sta, 4),
                           contradictions(report, c))


def decide(report: ReportFacts, candidates: list[CandidateFacts]) -> Decision:
    scored = sorted((score(report, c) for c in candidates), key=lambda s: s.total, reverse=True)
    if not scored or scored[0].total < AMBIGUOUS_THRESHOLD:
        return Decision(Outcome.NO_MATCH, None, scored, "no candidate reached the ambiguity threshold")

    top = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    close_competitor = runner_up is not None and (top.total - runner_up.total) < STRONG_MARGIN

    if (top.total >= STRONG_THRESHOLD and top.meets_floors() and not top.contradictions
            and not close_competitor):
        return Decision(Outcome.STRONG_MATCH, top.incident_id, scored, "top candidate met every floor and margin")

    reasons = []
    if top.total < STRONG_THRESHOLD:
        reasons.append("top score below strong threshold")
    if not top.meets_floors():
        reasons.append("a component score is below its floor")
    if top.contradictions:
        reasons.append("contradictions: " + ", ".join(top.contradictions))
    if close_competitor:
        reasons.append("second candidate within margin")
    return Decision(Outcome.AMBIGUOUS, None, scored, "; ".join(reasons))
