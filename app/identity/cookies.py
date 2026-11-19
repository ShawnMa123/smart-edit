"""Session cookie helpers (design D1/D12).

`HttpOnly` + `SameSite=Lax` always; `Secure` comes from settings (production must enable it).
"""

from __future__ import annotations

from app.identity.settings import COOKIE_NAME, AuthSettings


def set_session_cookie(response, token: str, settings: AuthSettings, *, max_age: int | None = None) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age if max_age is not None else settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response, settings: AuthSettings) -> None:
    response.delete_cookie(
        COOKIE_NAME, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/"
    )


def session_token(request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


__all__ = ["clear_session_cookie", "session_token", "set_session_cookie"]