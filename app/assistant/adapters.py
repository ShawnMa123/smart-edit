"""Local/fake adapters and the production guard (design D2 / task 0.2).

A only ships local implementations. `SMART_EDIT_ASSISTANT_MODE=production` refuses to start while
these fakes are wired, instead of silently pretending to be a production deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.assistant.ports import AccessContext, Principal
from app.assistant.store import SQLiteStore, now_iso

MODE_ENV = "SMART_EDIT_ASSISTANT_MODE"
DEFAULT_WORKSPACE = "ws_demo_01"


def resolve_mode(env: str | None = None) -> str:
    raw = (env if env is not None else os.environ.get(MODE_ENV, "local")).strip().lower()
    if raw not in ("local", "test", "production"):
        raise ValueError(f"{MODE_ENV} must be local, test or production")
    return raw


def assert_safe_mode(mode: str, settings: object | None = None) -> None:
    """Fail closed unless production declares an approved external processor (design D5)."""
    from app.assistant.settings import AssistantSettings, assert_production_safe

    assert_production_safe(mode, settings if isinstance(settings, AssistantSettings) else None)


class FakeIdentity:
    """`X-Demo-User` is a local/test-only switch; two principals make isolation testable."""

    def resolve(self, request) -> Principal:
        user = (request.headers.get("x-demo-user") or "user_demo_01").strip()
        if not user:
            user = "user_demo_01"
        return Principal(user_id=user, workspace_id=DEFAULT_WORKSPACE)


class FakeAuthorization:
    def resolve(self, principal: Principal, workspace_id: str) -> AccessContext:
        if principal.workspace_id != workspace_id:
            raise PermissionError("workspace is not visible to this principal")
        return AccessContext(
            principal=principal, workspace_id=workspace_id,
            authorization_version=principal.authorization_version,
        )


class FakeSnapshots:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def get(self, snapshot_id: str, principal: Principal) -> dict | None:
        snapshot = self.store.get_snapshot(snapshot_id)
        if not snapshot or snapshot["created_by"] != principal.user_id:
            return None
        if snapshot["workspace_id"] != principal.workspace_id:
            return None
        return snapshot


class StoreAudit:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def append(self, request_id, run_id, event_type, actor, payload) -> None:
        self.store.append_audit(
            request_id=request_id, run_id=run_id, event_type=event_type, actor=actor, payload=payload
        )


class SystemClock:
    def now(self) -> str:
        return now_iso()


class SystemIds:
    def new(self, prefix: str) -> str:
        from app.assistant.store import new_id

        return new_id(prefix)


@dataclass(frozen=True)
class AssistantServices:
    store: SQLiteStore
    identity: FakeIdentity
    authorization: FakeAuthorization
    snapshots: FakeSnapshots
    audit: StoreAudit
    clock: SystemClock
    retriever: object
    gateway: object
    ids: SystemIds = SystemIds()
    knowledge_admin: object | None = None
    mode: str = "local"
    # Knowledge-assistant-web-rag: optional layers; unset means "no external call".
    egress: object | None = None
    web: object | None = None
    settings: object | None = None
    # `knowledge-statute-retrieval`: optional external statute source; unset means "no statute leg".
    statute: object | None = None
    # `user-management`: PG authorization, evidence filtering and activity writes.
    resource_authorization: object | None = None
    evidence_authorizer: object | None = None
    activity: object | None = None
    auth_mode: str = "fake"