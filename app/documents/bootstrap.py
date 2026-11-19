"""Build the local document host and automation services (H1 adapter)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.approval.service import ApprovalService
from app.automation.run_service import AutomationRunService
from app.automation.service import AutomationService
from app.automation.store import AutomationStore
from app.documents.service import DocumentService
from app.documents.store import HostStore
from app.shared.adapters import (
    FakeIdentity,
    SystemClock,
    SystemIds,
    assert_host_mode_safe,
    resolve_host_mode,
)

DB_ENV = "SMART_EDIT_HOST_DB"


@dataclass(frozen=True)
class HostServices:
    store: HostStore
    documents: DocumentService
    automation: AutomationService
    runs: AutomationRunService
    approvals: ApprovalService
    identity: FakeIdentity
    clock: SystemClock
    ids: SystemIds
    mode: str


def build_host_services(
    *,
    db_path: str | Path | None = None,
    mode: str | None = None,
    identity: object | None = None,
    activity: object | None = None,
    document_access: object | None = None,
    version_provider: object | None = None,
) -> HostServices:
    resolved = resolve_host_mode(mode)
    assert_host_mode_safe(resolved)
    store = HostStore(db_path or os.environ.get(DB_ENV, "runs/host.db"))
    resolved_identity = identity or FakeIdentity()
    clock = SystemClock()
    ids = SystemIds()
    automation_store = AutomationStore(store)
    automation_store.recover_runs()
    return HostServices(
        store=store,
        documents=DocumentService(
            store,
            resolved_identity,
            clock,
            ids,
            authorizer=document_access,
            activity=activity,
        ),
        automation=AutomationService(
            store,
            automation_store,
            resolved_identity,
            clock,
            ids,
            authorizer=document_access,
            version_provider=version_provider,
            activity=activity,
        ),
        runs=AutomationRunService(
            store,
            automation_store,
            resolved_identity,
            clock,
            ids,
            authorizer=document_access,
            activity=activity,
        ),
        approvals=ApprovalService(store, document_access, ids, activity),
        identity=resolved_identity,
        clock=clock,
        ids=ids,
        mode=resolved,
    )


__all__ = ["DB_ENV", "HostServices", "build_host_services"]