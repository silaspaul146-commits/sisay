"""FCM sender: access-token exchange and error classification (no network)."""
import io
import json
import urllib.error

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.infrastructure.push import fcm

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode()
ACCOUNT = json.dumps({"project_id": "sisay-test", "client_email": "push@sisay-test.iam.gserviceaccount.com",
                      "private_key": PEM, "token_uri": "https://oauth2.googleapis.com/token"})
MSG = fcm.PushMessage(token="t" * 40, title="Shooting reported nearby.", body="Unconfirmed.",
                      data={"alert_id": "a"}, high_priority=True, collapse_key="alert-a")


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _fake(monkeypatch, send_behaviour):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req)
        if req.full_url.endswith("/token"):
            body = dict(x.split("=", 1) for x in req.data.decode().split("&"))
            claims = jwt.decode(body["assertion"], KEY.public_key(), algorithms=["RS256"],
                                audience="https://oauth2.googleapis.com/token")
            assert claims["scope"] == fcm.SCOPE and claims["iss"].startswith("push@")
            return _Resp(json.dumps({"access_token": "ya29.test", "expires_in": 3600}).encode())
        return send_behaviour(req)
    monkeypatch.setattr(fcm.urllib.request, "urlopen", urlopen)
    return calls


def test_accepted_message_and_token_reuse(monkeypatch):
    calls = _fake(monkeypatch, lambda req: _Resp(b'{"name": "projects/sisay-test/messages/123"}'))
    s = fcm.FcmSender(ACCOUNT)
    assert s.send(MSG) == fcm.SendResult("accepted", message_id="projects/sisay-test/messages/123")
    s.send(MSG)
    assert sum(c.full_url.endswith("/token") for c in calls) == 1  # access token cached
    sent = json.loads(calls[1].data)["message"]
    assert sent["android"]["priority"] == "HIGH" and sent["android"]["collapse_key"] == "alert-a"
    assert calls[1].headers["Authorization"] == "Bearer ya29.test"


@pytest.mark.parametrize("code,body,outcome", [
    (404, '{"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}', "invalid_token"),
    (400, '{"error": {"status": "INVALID_ARGUMENT", "message": "The registration token is not a valid FCM registration token"}}', "invalid_token"),
    (503, '{"error": {"status": "UNAVAILABLE"}}', "retry"),
    (429, '{"error": {"status": "RESOURCE_EXHAUSTED"}}', "retry"),
    (403, '{"error": {"status": "PERMISSION_DENIED"}}', "rejected"),
])
def test_errors_are_classified(monkeypatch, code, body, outcome):
    def fail(req):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(body.encode()))
    _fake(monkeypatch, fail)
    assert fcm.FcmSender(ACCOUNT).send(MSG).outcome == outcome
