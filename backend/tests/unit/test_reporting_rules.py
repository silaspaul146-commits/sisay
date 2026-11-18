import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.errors import ApiError
from app.core.security import candidate_hashes, generate_report_token, hash_report_token, is_well_formed_token
from app.modules.reporting.schemas import ReportCreate
from app.modules.reporting.service import request_fingerprint, resolve_observed_at
from app.shared.enums import LocationSource
from app.shared.ids import new_id, new_public_reference

DB_REFERENCE_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$")
RECEIVED = datetime(2026, 11, 14, 8, 33, tzinfo=UTC)


def minimal(**overrides) -> ReportCreate:
    data = {"category": "armed_clash", "location": {"latitude": 5.9631, "longitude": 10.1591}}
    data.update(overrides)
    return ReportCreate.model_validate(data)


def test_only_category_and_location_are_required():
    r = minimal()
    assert r.description is None and r.observed_at is None and r.location.accuracy_m is None


@pytest.mark.parametrize("missing", ["category", "location"])
def test_missing_required_field_is_rejected(missing):
    data = {"category": "fire", "location": {"latitude": 1, "longitude": 1}}
    del data[missing]
    with pytest.raises(ValidationError):
        ReportCreate.model_validate(data)


def test_coordinates_and_lengths_are_validated():
    with pytest.raises(ValidationError):
        minimal(location={"latitude": 91, "longitude": 0})
    with pytest.raises(ValidationError):
        minimal(location={"latitude": 0, "longitude": 181})
    with pytest.raises(ValidationError):
        minimal(description="x" * 2001)
    with pytest.raises(ValidationError):
        minimal(unexpected="field")


def test_api_location_source_aliases_map_to_stored_values():
    assert minimal(location={"latitude": 0, "longitude": 0, "source": "gps"}).location.source == LocationSource.DEVICE_GPS
    assert minimal(location={"latitude": 0, "longitude": 0, "source": "map_pin"}).location.source == LocationSource.MANUAL_PIN


def test_blank_description_becomes_none():
    assert minimal(description="   ").description is None


def test_fingerprint_is_stable_for_identical_retries_and_changes_with_payload():
    a = minimal(description="Gunshots near the market", observed_at="2026-11-14T08:30:00Z")
    b = minimal(description="Gunshots near the market", observed_at="2026-11-14T09:30:00+01:00")  # same instant
    assert request_fingerprint(a) == request_fingerprint(b)
    assert len(request_fingerprint(a)) == 32
    assert request_fingerprint(a) != request_fingerprint(minimal(description="Different"))
    assert request_fingerprint(minimal()) != request_fingerprint(
        minimal(location={"latitude": 5.9632, "longitude": 10.1591}))


def test_observed_time_keeps_offline_delay_and_rejects_future():
    late = minimal(client_created_at=(RECEIVED - timedelta(hours=5)).isoformat())
    observed, note = resolve_observed_at(late, RECEIVED)
    assert observed == RECEIVED - timedelta(hours=5) and note is None  # not treated as newly observed

    assert resolve_observed_at(minimal(), RECEIVED) == (RECEIVED, None)

    with pytest.raises(ApiError):
        resolve_observed_at(minimal(observed_at=(RECEIVED + timedelta(hours=1)).isoformat()), RECEIVED)

    skewed = minimal(client_created_at=(RECEIVED + timedelta(hours=2)).isoformat())
    observed, note = resolve_observed_at(skewed, RECEIVED)
    assert observed == RECEIVED and "clock" in note


def test_report_tokens_are_256_bit_prefixed_and_hashed_with_pepper():
    t = generate_report_token()
    assert t.startswith("rpt_") and is_well_formed_token(t)
    assert not is_well_formed_token("rpt_short") and not is_well_formed_token("x" * 47)
    assert generate_report_token() != t
    h1 = hash_report_token(t, "pepper-1")
    assert len(h1) == 32 and h1 == hash_report_token(t, "pepper-1")
    assert h1 != hash_report_token(t, "pepper-2")
    assert set(candidate_hashes(t, {1: "pepper-1", 2: "pepper-2"})) == {1, 2}


def test_public_reference_matches_database_check_and_ids_are_v7():
    refs = {new_public_reference() for _ in range(2000)}
    assert len(refs) == 2000
    assert all(DB_REFERENCE_RE.match(r) for r in refs)
    assert new_id().version == 7 and isinstance(new_id(), uuid.UUID)
