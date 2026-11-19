"""Anonymous device credentials (DECISIONS "Alerts"). No account, no phone number: the app registers
once, keeps a secret installation token, and sends it as `X-Installation-Token` on personal routes
(saved places, subscriptions, alerts). The server stores only HMAC-SHA-256(pepper, token)."""
import base64
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import Connection, text

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.security import candidate_hashes, hash_report_token

PREFIX = "ins_"
_TOKEN_RE = re.compile(r"^ins_[A-Za-z0-9_-]{43}$")


def generate_installation_token() -> str:
    return PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def register_installation(conn: Connection, platform: str, app_version: str | None,
                          settings: Settings) -> tuple[uuid.UUID, str]:
    token = generate_installation_token()
    version = settings.token_pepper_active_version
    installation_id = conn.execute(
        text("""INSERT INTO identity.installations (platform, app_version, token_hash, token_pepper_version)
                VALUES (:platform, :app_version, :hash, :v) RETURNING id"""),
        {"platform": platform, "app_version": app_version,
         "hash": hash_report_token(token, settings.token_peppers[version]), "v": version},
    ).scalar_one()
    return installation_id, token


@dataclass(frozen=True)
class Device:
    installation_id: uuid.UUID


def _unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", "Register this app first (POST /installations) and send X-Installation-Token.")


def authenticate(conn: Connection, token: str | None, settings: Settings) -> Device:
    if not token or not _TOKEN_RE.match(token):
        raise _unauthorized()
    hashes = list(candidate_hashes(token, settings.token_peppers).values())
    row = conn.execute(
        text("""SELECT id FROM identity.installations
                WHERE token_hash = ANY(:hashes) AND status = 'active'"""),
        {"hashes": hashes},
    ).first()
    if row is None:
        raise _unauthorized()
    conn.execute(text("""UPDATE identity.installations SET last_seen_at = now()
                         WHERE id = :id AND last_seen_at < now() - interval '1 hour'"""), {"id": row.id})
    return Device(row.id)


def subscriber_id(conn: Connection, device: Device) -> uuid.UUID:
    """The installation's subscriber principal, created on first use."""
    conn.execute(
        text("""INSERT INTO subscription.subscriber_principals (installation_id) VALUES (:iid)
                ON CONFLICT (installation_id) WHERE installation_id IS NOT NULL DO NOTHING"""),
        {"iid": device.installation_id},
    )
    return conn.execute(text("SELECT id FROM subscription.subscriber_principals WHERE installation_id = :iid"),
                        {"iid": device.installation_id}).scalar_one()


InstallationToken = Annotated[str | None, Header(alias="X-Installation-Token")]
SettingsDep = Annotated[Settings, Depends(get_settings)]
