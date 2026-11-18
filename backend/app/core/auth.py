"""Staff authentication and authorization (API contract 1.3, 16; DB spec 4.2, A-2; decision U-1).

Sign-in happens at an external OpenID Connect provider. This API only validates the provider's
access token (signature via the provider's JWKS, issuer, audience, expiry) and maps its `sub` to
identity.users.auth_subject. Permissions come only from active identity.platform_permissions rows,
read on every request, so a revocation takes effect immediately. Users are provisioned with
`python -m app.manage grant`; an unknown subject is refused, never auto-created.

Citizens never need an account: anonymous report routes do not use this module.
"""
import json
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.db import get_dashboard_engine
from app.core.errors import ApiError

KeyResolver = Callable[[str], Any]


def _unauthenticated() -> ApiError:
    return ApiError(401, "authentication_required", "A valid access token is required.")


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, algorithms: list[str], key_resolver: KeyResolver):
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms
        self.key_resolver = key_resolver

    def verify(self, token: str) -> dict:
        """Returns the validated claims, or raises a 401 ApiError. Never says why: the reason
        (expired, wrong audience, bad signature) is not the caller's business."""
        try:
            key = self.key_resolver(token)
            return jwt.decode(token, key, algorithms=self.algorithms, audience=self.audience, issuer=self.issuer,
                              leeway=30, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        except (jwt.PyJWTError, ValueError, KeyError):
            raise _unauthenticated()


def discover_jwks_url(issuer: str) -> str:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - https issuer from configuration
        return json.load(resp)["jwks_uri"]


@lru_cache
def get_token_verifier() -> TokenVerifier:
    settings: Settings = get_settings()
    if not (settings.oidc_issuer and settings.oidc_audience):
        raise ApiError(503, "authentication_not_configured", "Staff sign-in is not configured on this server.")
    jwks = jwt.PyJWKClient(settings.oidc_jwks_url or discover_jwks_url(settings.oidc_issuer),
                           cache_keys=True, lifespan=3600)
    return TokenVerifier(settings.oidc_issuer, settings.oidc_audience, settings.oidc_algorithms,
                         lambda token: jwks.get_signing_key_from_jwt(token).key)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    subject: str
    email: str | None
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise _unauthenticated()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthenticated()
    token = token.strip()
    if token.startswith("rpt_"):  # report access tokens never authenticate staff
        raise _unauthenticated()
    return token


def get_principal(
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    claims = verifier.verify(_bearer(authorization))
    with get_dashboard_engine().connect() as conn:
        user = conn.execute(
            text("SELECT id, email, status FROM identity.users WHERE auth_subject = :sub"), {"sub": claims["sub"]}
        ).first()
        if user is None or user.status != "active":
            # Same answer as a bad token: do not reveal which accounts exist.
            raise _unauthenticated()
        perms = conn.execute(
            text("""SELECT permission_code FROM identity.platform_permissions
                    WHERE user_id = :uid AND revoked_at IS NULL"""),
            {"uid": user.id},
        ).scalars().all()
    return Principal(user.id, claims["sub"], user.email, frozenset(perms))


def require(permission: str) -> Callable[..., Principal]:
    """Dependency factory: the signed-in user must hold `permission` (platform grant, A-2)."""
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.has(permission):
            raise ApiError(403, "insufficient_permission", "You do not have permission to perform this action.")
        return principal
    dependency.__name__ = f"require_{permission.replace('.', '_')}"
    return dependency
