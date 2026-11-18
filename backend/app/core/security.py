"""Anonymous report access tokens (DB spec 7.3, API contract 1.3).

The token is a 256-bit random secret, base64url, prefixed `rpt_` so secret scanners recognise
leaks. The server stores only HMAC-SHA-256(pepper[v], token). Peppers live outside the database.
"""
import base64
import hashlib
import hmac
import re
import secrets

TOKEN_PREFIX = "rpt_"
_TOKEN_RE = re.compile(r"^rpt_[A-Za-z0-9_-]{43}$")  # 32 bytes -> 43 base64url chars, no padding


def generate_report_token() -> str:
    return TOKEN_PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def is_well_formed_token(token: str) -> bool:
    return bool(_TOKEN_RE.match(token))


def hash_report_token(token: str, pepper: str) -> bytes:
    return hmac.new(pepper.encode(), token.encode(), hashlib.sha256).digest()


def candidate_hashes(token: str, peppers: dict[int, str]) -> dict[int, bytes]:
    """Hash under every configured pepper version, for lookup during pepper rotation."""
    return {version: hash_report_token(token, pepper) for version, pepper in peppers.items()}
