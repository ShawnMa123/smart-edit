"""Errors for the identity/authorization boundary.

The API registers one handler for `IdentityError` so the body keeps the global `{code, message,
detail?}` contract. `AuthRequired` (401) and `Forbidden` (403) never reveal whether a resource exists.
"""

from __future__ import annotations


class IdentityError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


class AuthRequired(IdentityError):
    def __init__(self, message: str = "authentication required") -> None:
        super().__init__(401, "AUTH_REQUIRED", message)


class Forbidden(IdentityError):
    """One code for \"no permission\" and \"does not exist\" (design D5 / security baseline)."""

    def __init__(self, message: str = "you do not have permission for this resource") -> None:
        super().__init__(403, "FORBIDDEN", message)


class InvalidCredentials(IdentityError):
    def __init__(self) -> None:
        # Deliberately identical for unknown email and wrong password.
        super().__init__(401, "INVALID_CREDENTIALS", "email or password is incorrect")


class RateLimited(IdentityError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            429,
            "RATE_LIMITED",
            "too many failed sign-in attempts; retry later",
            {"retry_after": retry_after},
        )


class CsrfRejected(IdentityError):
    def __init__(self) -> None:
        super().__init__(403, "CSRF_REJECTED", "the write request did not present a valid CSRF signal")


class Conflict(IdentityError):
    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(409, code, message, detail)


class NotFound(IdentityError):
    def __init__(self, message: str = "not found") -> None:
        super().__init__(404, "NOT_FOUND", message)


class InvalidRequest(IdentityError):
    def __init__(self, message: str) -> None:
        super().__init__(400, "INVALID_REQUEST", message)


class DatabaseUnavailable(RuntimeError):
    """PG is configured but unreachable; startup fails instead of falling back to fake identity."""


__all__ = [
    "AuthRequired",
    "Conflict",
    "CsrfRejected",
    "DatabaseUnavailable",
    "Forbidden",
    "IdentityError",
    "InvalidCredentials",
    "InvalidRequest",
    "NotFound",
    "RateLimited",
]