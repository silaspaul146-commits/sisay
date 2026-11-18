"""Staff token validation and permission checks (no database: get_principal is overridden where needed)."""
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import Principal, TokenVerifier, _bearer, get_principal, require
from app.core.errors import ApiError, install_error_handlers

ISS, AUD = "https://idp.example.test/", "crisis-api"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key=KEY, **overrides) -> str:
    now = int(time.time())
    claims = {"iss": ISS, "aud": AUD, "sub": "user-1", "iat": now, "exp": now + 300} | overrides
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="RS256")


verifier = TokenVerifier(ISS, AUD, ["RS256"], lambda _t: KEY.public_key())


def test_valid_token_returns_claims():
    assert verifier.verify(token())["sub"] == "user-1"


@pytest.mark.parametrize("bad", [
    token(exp=int(time.time()) - 120),           # expired beyond leeway
    token(aud="another-api"),
    token(iss="https://evil.example.test/"),
    token(key=OTHER_KEY),                        # signed by someone else
    token(sub=None),                             # required claim missing
    jwt.encode({"iss": ISS, "aud": AUD, "sub": "x", "iat": 0, "exp": 2**31}, "secret", algorithm="HS256"),
    "not-a-jwt",
])
def test_invalid_tokens_are_401(bad):
    with pytest.raises(ApiError) as e:
        verifier.verify(bad)
    assert e.value.status == 401


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer rpt_" + "A" * 43])
def test_bearer_header_is_required_and_report_tokens_never_authenticate_staff(header):
    with pytest.raises(ApiError) as e:
        _bearer(header)
    assert e.value.status == 401


def _app(principal: Principal) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/verify-only")
    def endpoint(p: Principal = Depends(require("incident.verify"))):
        return {"user": str(p.user_id)}

    app.dependency_overrides[get_principal] = lambda: principal
    return TestClient(app)


def test_permission_is_required():
    viewer = Principal(uuid.uuid4(), "s", None, frozenset({"incident.view"}))
    resp = _app(viewer).get("/verify-only")
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "insufficient_permission"

    verifier_user = Principal(uuid.uuid4(), "s", None, frozenset({"incident.verify"}))
    assert _app(verifier_user).get("/verify-only").status_code == 200


def test_unconfigured_sign_in_is_503(monkeypatch):
    from app.core import auth
    from app.core.config import Settings
    auth.get_token_verifier.cache_clear()
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(oidc_issuer=None, oidc_audience=None))
    with pytest.raises(ApiError) as e:
        auth.get_token_verifier()
    assert e.value.status == 503
    auth.get_token_verifier.cache_clear()
