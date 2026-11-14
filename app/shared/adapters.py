"""Local adapters plus the production guard shared by host-backed capabilities.

Only local/test may use the fake identity and the local SQLite host. Production must fail closed
until an approved identity/host adapter is wired.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from app.shared.ports import Principal

MODE_ENV = "SMART_EDIT_HOST_MODE"
DEFAULT_WORKSPACE = "ws_demo_01"


def resolve_host_mode(env: str | None = None) -> str:
    raw = (env if env is not None else os.environ.get(MODE_ENV, "local")).strip().lower()
    if raw not in ("local", "test", "production"):
        raise ValueError(f"{MODE_ENV} must be local, test or production")
    return raw


def assert_host_mode_safe(mode: str) -> None:
    if mode == "production":
        raise RuntimeError(
            "the document host only has local/fake adapters in this build; production must fail "
            "closed until an approved host, identity and lock adapter is configured"
        )


class FakeIdentity:
    """`X-Demo-User` is a local/test-only switch; two principals make isolation testable."""

    def resolve(self, request) -> Principal:
        user = (request.headers.get("x-demo-user") or "user_demo_01").strip()
        if not user:
            user = "user_demo_01"
        return Principal(user_id=user, workspace_id=DEFAULT_WORKSPACE)


class SystemClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class SystemIds:
    def new(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"


__all__ = [
    "DEFAULT_WORKSPACE",
    "FakeIdentity",
    "MODE_ENV",
    "SystemClock",
    "SystemIds",
    "assert_host_mode_safe",
    "resolve_host_mode",
]