"""Auth settings for the PG identity stack (design D1/D10/D12).

`AUTH_MODE=fake` is the default: it preserves `X-Demo-User` for tests and for machines without a PG
tunnel. `AUTH_MODE=pg` fails closed at startup when the database URL is missing or unreachable —
there is no silent fallback to SQLite identity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

AUTH_MODE_ENV = "SMART_EDIT_AUTH_MODE"
DATABASE_URL_ENV = "SMART_EDIT_DATABASE_URL"
COOKIE_SECURE_ENV = "SMART_EDIT_AUTH_COOKIE_SECURE"
ENVIRONMENT_ENV = "SMART_EDIT_ENV"
SESSION_TTL_ENV = "SMART_EDIT_AUTH_SESSION_TTL"
INVITE_TTL_ENV = "SMART_EDIT_AUTH_INVITE_TTL"
LOGIN_LIMIT_ENV = "SMART_EDIT_AUTH_LOGIN_MAX_FAILURES"
LOGIN_WINDOW_ENV = "SMART_EDIT_AUTH_LOGIN_WINDOW"
ALLOWED_ORIGINS_ENV = "SMART_EDIT_AUTH_ALLOWED_ORIGINS"
DB_POOL_MIN_ENV = "SMART_EDIT_AUTH_POOL_MIN"
DB_POOL_MAX_ENV = "SMART_EDIT_AUTH_POOL_MAX"
DB_CONNECT_TIMEOUT_ENV = "SMART_EDIT_AUTH_CONNECT_TIMEOUT"

AUTH_MODES = ("fake", "pg")
COOKIE_NAME = "smart_edit_session"
CSRF_HEADER = "x-csrf-token"
CSRF_REQUEST_HEADER = "x-requested-with"
CSRF_REQUEST_VALUE = "smart-edit"
DEFAULT_SESSION_TTL = 7 * 24 * 3600
DEFAULT_INVITE_TTL = 72 * 3600
DEFAULT_LOGIN_MAX_FAILURES = 5
DEFAULT_LOGIN_WINDOW = 300
DEFAULT_ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
_TRUE = {"1", "true", "yes", "on"}


def _positive_int(values: dict[str, str], key: str, default: int) -> int:
    raw = (values.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer; got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{key} must be greater than 0; got {value!r}")
    return value


@dataclass(frozen=True)
class AuthSettings:
    """Resolved identity settings; every field is validated before any connection is opened."""

    mode: str = "fake"
    database_url: str | None = None
    cookie_secure: bool = False
    session_ttl_seconds: int = DEFAULT_SESSION_TTL
    invite_ttl_seconds: int = DEFAULT_INVITE_TTL
    login_max_failures: int = DEFAULT_LOGIN_MAX_FAILURES
    login_window_seconds: int = DEFAULT_LOGIN_WINDOW
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    pool_min_size: int = 1
    pool_max_size: int = 8
    connect_timeout: int = 5

    @property
    def is_pg(self) -> bool:
        return self.mode == "pg"

    @classmethod
    def from_env(
        cls,
        values: dict[str, str] | None = None,
        *,
        mode: str | None = None,
    ) -> "AuthSettings":
        values = dict(os.environ if values is None else values)
        raw_mode = (mode if mode is not None else values.get(AUTH_MODE_ENV) or "fake").strip().lower()
        if raw_mode not in AUTH_MODES:
            raise ValueError(f"{AUTH_MODE_ENV} must be one of {AUTH_MODES}; got {raw_mode!r}")

        database_url = (values.get(DATABASE_URL_ENV) or "").strip() or None
        if raw_mode == "pg" and not database_url:
            raise ValueError(
                f"{DATABASE_URL_ENV} is required when {AUTH_MODE_ENV}=pg "
                "(start the PG tunnel first: ssh -f -N team04-pg)"
            )

        raw_secure = (values.get(COOKIE_SECURE_ENV) or "").strip().lower()
        environment = (values.get(ENVIRONMENT_ENV) or "").strip().lower()
        # Production must default to Secure; local HTTP development may opt out explicitly.
        cookie_secure = raw_secure in _TRUE if raw_secure else environment == "production"

        origins_raw = (values.get(ALLOWED_ORIGINS_ENV) or "").strip()
        origins = (
            tuple(part.strip() for part in origins_raw.split(",") if part.strip())
            if origins_raw
            else DEFAULT_ALLOWED_ORIGINS
        )

        pool_min = _positive_int(values, DB_POOL_MIN_ENV, 1)
        pool_max = _positive_int(values, DB_POOL_MAX_ENV, 8)
        if pool_max < pool_min:
            raise ValueError(f"{DB_POOL_MAX_ENV} must be >= {DB_POOL_MIN_ENV}")

        return cls(
            mode=raw_mode,
            database_url=database_url,
            cookie_secure=cookie_secure,
            session_ttl_seconds=_positive_int(values, SESSION_TTL_ENV, DEFAULT_SESSION_TTL),
            invite_ttl_seconds=_positive_int(values, INVITE_TTL_ENV, DEFAULT_INVITE_TTL),
            login_max_failures=_positive_int(values, LOGIN_LIMIT_ENV, DEFAULT_LOGIN_MAX_FAILURES),
            login_window_seconds=_positive_int(values, LOGIN_WINDOW_ENV, DEFAULT_LOGIN_WINDOW),
            allowed_origins=origins,
            pool_min_size=pool_min,
            pool_max_size=pool_max,
            connect_timeout=_positive_int(values, DB_CONNECT_TIMEOUT_ENV, 5),
        )


__all__ = [
    "ALLOWED_ORIGINS_ENV",
    "AUTH_MODES",
    "AUTH_MODE_ENV",
    "AuthSettings",
    "COOKIE_NAME",
    "COOKIE_SECURE_ENV",
    "CSRF_HEADER",
    "CSRF_REQUEST_HEADER",
    "CSRF_REQUEST_VALUE",
    "DATABASE_URL_ENV",
    "DEFAULT_ALLOWED_ORIGINS",
    "DEFAULT_INVITE_TTL",
    "DEFAULT_LOGIN_MAX_FAILURES",
    "DEFAULT_LOGIN_WINDOW",
    "DEFAULT_SESSION_TTL",
    "ENVIRONMENT_ENV",
]