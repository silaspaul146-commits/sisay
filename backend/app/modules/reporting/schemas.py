"""Reporting API schemas (API contract 3)."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.shared.enums import LOCATION_SOURCE_ALIASES, LocationSource


class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: int | None = Field(default=None, ge=0, le=100_000)
    source: LocationSource | None = None

    @field_validator("source", mode="before")
    @classmethod
    def _alias(cls, v):
        if isinstance(v, str) and v in LOCATION_SOURCE_ALIASES:
            return LOCATION_SOURCE_ALIASES[v]
        return v


class ReportCreate(BaseModel):
    """Only category and location are required (BR-19, FR-REP-002)."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=2, max_length=63, pattern=r"^[a-z][a-z0-9_]+$")
    location: LocationIn
    description: str | None = Field(default=None, max_length=2000)
    observed_at: AwareDatetime | None = None
    client_created_at: AwareDatetime | None = None

    @field_validator("description")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ReportCreated(BaseModel):
    report_id: uuid.UUID
    public_reference: str
    # Present only on the first successful response, and only when the server generated the token.
    access_token: str | None = None
    intake_status: str
    matching_status: str
    received_at: datetime
    replayed: bool = False
    notice: str = "Submitting a report does not mean it has been verified."


class PublicIncidentSummary(BaseModel):
    public_id: uuid.UUID
    category: str
    verification_status: str
    lifecycle: str
    uncertainty_note: str


class ReportStatus(BaseModel):
    report_id: uuid.UUID
    public_reference: str
    category: str
    description: str | None
    reporter_status: Literal["received", "under_review", "linked_to_incident", "not_published"]
    intake_status: str
    matching_status: str
    received_at: datetime
    evidence_count: int
    incident: PublicIncidentSummary | None
