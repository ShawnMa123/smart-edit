"""Minimal cross-capability contracts (principal, access, clock, ids, audit)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Principal:
    """The authenticated actor. Roles/capabilities are server-derived, never client claims."""

    user_id: str
    workspace_id: str
    roles: tuple[str, ...] = ("member",)
    authorization_version: str = "auth-demo-1"


@dataclass(frozen=True)
class AccessContext:
    principal: Principal
    workspace_id: str
    authorization_version: str


class ClockPort(Protocol):
    def now(self) -> str: ...


class IdsPort(Protocol):
    def new(self, prefix: str) -> str: ...


class AuditPort(Protocol):
    def append(
        self, request_id: str, run_id: str | None, event_type: str, actor: str, payload: dict[str, Any]
    ) -> None: ...


class IdempotencyPort(Protocol):
    def get(self, principal: str, method: str, path: str, key: str) -> dict[str, Any] | None: ...

    def put(
        self,
        principal: str,
        method: str,
        path: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None: ...


__all__ = [
    "AccessContext",
    "AuditPort",
    "ClockPort",
    "IdempotencyPort",
    "IdsPort",
    "Principal",
]