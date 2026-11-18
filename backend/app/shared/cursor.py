"""Opaque keyset-pagination cursors: (timestamp, uuid) pairs, base64url JSON."""
import base64
import json
import uuid
from datetime import datetime

from app.core.errors import validation_error


def encode_cursor(ts: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps({"t": ts.isoformat(), "id": str(row_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise validation_error("cursor", "Invalid pagination cursor.")
