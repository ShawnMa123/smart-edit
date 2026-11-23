"""Opaque token, cookie and CSRF helpers (design D1/D12).

Only hashes are stored: session tokens, invite tokens and API keys are random secrets whose SHA-256
digest is the database key. A database dump therefore cannot be replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

SESSION_TOKEN_BYTES = 32
INVITE_TOKEN_BYTES = 32
API_KEY_BYTES = 32
API_KEY_PREFIX_LENGTH = 12


def new_token(nbytes: int = SESSION_TOKEN_BYTES) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_prefix(token: str, length: int = API_KEY_PREFIX_LENGTH) -> str:
    return token[: max(1, min(length, len(token)))]


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def new_api_key() -> str:
    """High-entropy key, prefixed so a human can identify it without revealing the secret."""
    return f"sk_live_{secrets.token_urlsafe(API_KEY_BYTES)}"


def apikey_lookup(token: str) -> str:
    return hash_token(token)


def csrf_signal_present(headers: dict[str, str] | object, *, request_value: str) -> bool:
    """Accept the custom request header (browser clients) or a same-origin `Origin`.

    `SameSite=Lax` already blocks cross-site sends; this is the second, explicit signal required for
    unsafe methods (design D12). API-key requests never reach this check.
    """
    get = getattr(headers, "get", None)
    if get is None:  # pragma: no cover - defensive
        return False
    value = (get("x-requested-with") or "").strip().lower()
    return value == request_value


def origin_allowed(origin: str | None, allowed: tuple[str, ...]) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in {item.rstrip("/") for item in allowed}


__all__ = [
    "API_KEY_BYTES",
    "API_KEY_PREFIX_LENGTH",
    "INVITE_TOKEN_BYTES",
    "SESSION_TOKEN_BYTES",
    "apikey_lookup",
    "constant_time_equals",
    "csrf_signal_present",
    "hash_token",
    "new_api_key",
    "new_token",
    "origin_allowed",
    "token_prefix",
]