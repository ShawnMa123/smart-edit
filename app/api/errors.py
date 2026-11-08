"""Error contract for the HTTP boundary.

Design: `openspec/changes/frontend-console/design.md` D4/D5.
Spec: `openspec/changes/frontend-console/specs/console-api/spec.md`.

Every refusal leaves the server with the same body shape (`{code, message, detail?}`) so a client
branches on `code` and treats `message` as human detail only.
"""

from __future__ import annotations


class ApiFailure(Exception):
    """A refusal the API can express as `status` + `code`."""

    def __init__(self, status: int, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


class IncompleteResult(RuntimeError):
    """`stages` could not be assembled; the response must be a 500, never a clean-looking 200."""


def error_body(code: str, message: str, detail: dict | None = None) -> dict:
    body: dict = {"code": code, "message": message}
    if detail:
        body["detail"] = detail
    return body