"""Errors the document host and automation API can express at the HTTP boundary."""

from __future__ import annotations

from typing import Any


class HostError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        detail: Any = None,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
        self.retryable = retryable


class RevisionConflict(HostError):
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__(
            412,
            "stale_draft",
            "the draft moved since this write was based on it",
            {
                "conflict": "stale_draft",
                "current_revision": current["revision"],
                "content_sha256": current["text_sha256"],
            },
        )


class LockConflict(HostError):
    def __init__(self, message: str = "the draft lock is missing, expired or owned by someone else") -> None:
        super().__init__(409, "lock_conflict", message)


class HostNotFound(HostError):
    def __init__(self, message: str = "resource not found") -> None:
        super().__init__(404, "RESOURCE_NOT_FOUND", message)


class PreconditionRequired(HostError):
    def __init__(self, message: str = "this write requires If-Match with the current revision") -> None:
        super().__init__(428, "precondition_required", message)


__all__ = [
    "HostError",
    "HostNotFound",
    "LockConflict",
    "PreconditionRequired",
    "RevisionConflict",
]