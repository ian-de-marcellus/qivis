"""Invite tokens and signed session cookies (stdlib only)."""

import hashlib
import hmac
import secrets

COOKIE = "qivis_guest"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign(guest_id: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), guest_id.encode(), hashlib.sha256).hexdigest()
    return f"{guest_id}.{mac}"


def verify(cookie: str | None, secret: str) -> str | None:
    """The guest id in a valid cookie, else None."""
    if not cookie or "." not in cookie:
        return None
    guest_id, _, mac = cookie.rpartition(".")
    expected = hmac.new(secret.encode(), guest_id.encode(), hashlib.sha256).hexdigest()
    return guest_id if hmac.compare_digest(mac, expected) else None
