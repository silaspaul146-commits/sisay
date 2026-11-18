"""Identifier generation (DB spec 3.1, 7.3)."""
import secrets
import uuid

# Crockford base32 without I, L, O, U.
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id() -> uuid.UUID:
    """Time-ordered UUIDv7 for internal primary keys. Never used for public identifiers."""
    return uuid.uuid7()


def new_public_reference() -> str:
    """12 Crockford base32 characters in three groups: 60 random bits. Identifies, never authorizes."""
    value = secrets.randbits(60)
    chars = [CROCKFORD[(value >> (5 * i)) & 31] for i in range(12)]
    s = "".join(chars)
    return f"{s[0:4]}-{s[4:8]}-{s[8:12]}"
