"""Shared vocabulary. Values match the CHECK constraints; see docs/DECISIONS.md."""
from enum import StrEnum


class Severity(StrEnum):
    UNKNOWN = "unknown"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK = {s.value: i for i, s in enumerate(Severity)}


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class OperationalStatus(StrEnum):
    ACTIVE = "active"
    MONITORING = "monitoring"
    RESOLVED = "resolved"
    CLOSED = "closed"
    MERGED = "merged"
    WITHDRAWN = "withdrawn"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Freshness(StrEnum):
    CURRENT = "current"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"


class LocationSource(StrEnum):
    DEVICE_GPS = "device_gps"
    DEVICE_NETWORK = "device_network"
    MANUAL_PIN = "manual_pin"
    GEOCODED_ADDRESS = "geocoded_address"


# API contract aliases (gps, manual, map_pin) accepted on input.
LOCATION_SOURCE_ALIASES = {
    "gps": LocationSource.DEVICE_GPS,
    "manual": LocationSource.MANUAL_PIN,
    "map_pin": LocationSource.MANUAL_PIN,
}

# Accuracy assumed when the client cannot supply one; matching must always use accuracy (DB spec 4.5).
DEFAULT_ACCURACY_M = {
    LocationSource.DEVICE_GPS: 50,
    LocationSource.DEVICE_NETWORK: 500,
    LocationSource.MANUAL_PIN: 250,
    LocationSource.GEOCODED_ADDRESS: 500,
}


class MatchingStatus(StrEnum):
    PENDING = "pending"
    MATCHED_EXISTING_INCIDENT = "matched_existing_incident"
    PROVISIONAL_INCIDENT_CREATED = "provisional_incident_created"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
