"""Assistant API error type (mapped to the error body in `app/api/assistant.py`)."""

from __future__ import annotations

from typing import Any


class AssistantError(Exception):
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