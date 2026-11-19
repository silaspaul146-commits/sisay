"""Firebase Cloud Messaging HTTP v1 sender, without the Google SDK.

The service account signs a short JWT (RS256) that Google exchanges for a one-hour access token;
messages are POSTed to https://fcm.googleapis.com/v1/projects/<project>/messages:send.
Provider acceptance is NOT proof the person saw the message (DB spec F-22).
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import jwt

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


@dataclass(frozen=True)
class SendResult:
    outcome: str                  # accepted | invalid_token | retry | rejected
    message_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class PushMessage:
    token: str
    title: str
    body: str
    data: dict[str, str]
    high_priority: bool
    collapse_key: str


class FcmSender:
    def __init__(self, service_account_json: str, timeout_s: float = 15.0):
        info = json.loads(service_account_json)
        self.project_id: str = info["project_id"]
        self._email: str = info["client_email"]
        self._key: str = info["private_key"]
        self._token_uri: str = info.get("token_uri", TOKEN_URL)
        self._timeout = timeout_s
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def _token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at - 120:
                return self._access_token
            now = int(time.time())
            assertion = jwt.encode({"iss": self._email, "scope": SCOPE, "aud": self._token_uri,
                                    "iat": now, "exp": now + 3600}, self._key, algorithm="RS256")
            body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                           "assertion": assertion}).encode()
            req = urllib.request.Request(self._token_uri, data=body, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                payload = json.load(r)
            self._access_token = payload["access_token"]
            self._expires_at = time.time() + int(payload.get("expires_in", 3600))
            return self._access_token

    def send(self, m: PushMessage) -> SendResult:
        message = {
            "token": m.token,
            "notification": {"title": m.title, "body": m.body},
            "data": m.data,
            "android": {"priority": "HIGH" if m.high_priority else "NORMAL", "collapse_key": m.collapse_key,
                        "ttl": "21600s", "notification": {"channel_id": "sisay_alerts", "tag": m.collapse_key}},
            "apns": {"headers": {"apns-priority": "10" if m.high_priority else "5",
                                 "apns-collapse-id": m.collapse_key[:64]}},
        }
        try:
            req = urllib.request.Request(
                f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send", method="POST",
                data=json.dumps({"message": message}).encode(),
                headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                return SendResult("accepted", message_id=json.load(r).get("name"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code == 404 or "UNREGISTERED" in detail or ("INVALID_ARGUMENT" in detail and "token" in detail.lower()):
                return SendResult("invalid_token", error=f"{e.code} {detail}")
            if e.code in (429, 500, 502, 503, 504) or e.code == 401:
                return SendResult("retry", error=f"{e.code} {detail}")
            return SendResult("rejected", error=f"{e.code} {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return SendResult("retry", error=f"{type(e).__name__}: {e}")
