"""Public projection rules (DB spec 7.1). Pure functions over incident + disclosure policy.

A projection is a sanitized, generalized view of an incident. It never contains reporter data,
evidence, internal coordinates or report free text. Verification status is NOT an eligibility
rule: unverified incidents are shown with their status (BR-21).
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

NO_SAFETY_NOTICE = (
    "This map shows community reports that may be unverified, approximate or out of date. "
    "An area with no reports is not necessarily safe."
)

_VERIFICATION_TEXT = {
    "unverified": "Unverified community report.",
    "under_review": "Report under review.",
    "verified": "Verified by reviewers.",
    "disputed": "Disputed: information is contested.",
    "rejected": "Rejected by reviewers.",
}


@dataclass(frozen=True)
class PolicyFacts:
    id: int
    public_grid_m: int
    public_location_mode: str  # generalized | area_only | hidden
    publish_on_map: bool
    publish_description: bool
    publish_affected_area: bool
    review_before_publish: bool
    public_delay: timedelta
    max_public_age: timedelta


@dataclass(frozen=True)
class IncidentFacts:
    operational_status: str
    verification_status: str
    created_at: datetime
    last_observed_at: datetime


def public_lifecycle(operational_status: str, verification_status: str) -> str:
    if operational_status in ("merged", "withdrawn") or verification_status == "rejected":
        return "removed"
    if operational_status == "closed":
        return "resolved"
    return operational_status  # active | monitoring | resolved


def eligibility(incident: IncidentFacts, policy: PolicyFacts, now: datetime,
                publication_review_approved: bool) -> tuple[bool, str]:
    """Returns (is_visible, reason). Reasons are for logs and history, never for public output."""
    if not policy.publish_on_map or policy.public_location_mode == "hidden":
        return False, "policy_hidden"
    if policy.public_location_mode == "area_only":
        return False, "area_only_not_mapped"  # docs/DECISIONS.md
    if public_lifecycle(incident.operational_status, incident.verification_status) == "removed":
        return False, "removed"
    if now < incident.created_at + policy.public_delay:
        return False, "publication_delay"
    if incident.last_observed_at <= now - policy.max_public_age:
        return False, "past_max_public_age"
    if policy.review_before_publish and not publication_review_approved:
        return False, "awaiting_publication_review"
    return True, "eligible"


def publication_state(is_visible: bool, reason: str) -> str:
    if is_visible:
        return "published"
    if reason in ("publication_delay", "awaiting_publication_review"):
        return "pending"  # not yet eligible
    return "withdrawn"  # no longer (or never) eligible


def format_precision(metres: int) -> str:
    if metres >= 1000:
        km = metres / 1000
        return f"{km:g} km"
    return f"{metres} m"


def uncertainty_note(verification_status: str, confidence: str, precision_m: int) -> str:
    return (f"{_VERIFICATION_TEXT.get(verification_status, 'Unverified community report.')} "
            f"Confidence: {confidence}. Location shown to within {format_precision(precision_m)}.")


def freshness_from_age(observed_at: datetime, now: datetime) -> str:
    """Provisional, category-independent rule (docs/DECISIONS.md)."""
    age = now - observed_at
    if age <= timedelta(hours=6):
        return "current"
    if age <= timedelta(hours=24):
        return "aging"
    return "stale"


def content_hash(fields: dict) -> bytes:
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str, separators=(",", ":")).encode()).digest()
