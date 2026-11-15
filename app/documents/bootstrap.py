"""Build the local document host and automation services (H1 adapter)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
    identity: FakeIdentity
    clock: SystemClock
    ids: SystemIds
    mode: str


def build_host_services(
    *, db_path: str | Path | None = None, mode: str | None = None
) -> HostServices:
    resolved = resolve_host_mode(mode)
    assert_host_mode_safe(resolved)
    store = HostStore(db_path or os.environ.get(DB_ENV, "runs/host.db"))
    identity = FakeIdentity()
    clock = SystemClock()
    ids = SystemIds()
    automation_store = AutomationStore(store)
    automation_store.recover_runs()
    return HostServices(
        store=store,
        documents=DocumentService(store, identity, clock, ids),
        automation=AutomationService(store, automation_store, identity, clock, ids),
        runs=AutomationRunService(store, automation_store, identity, clock, ids),
        identity=identity,
        clock=clock,
        ids=ids,
        mode=resolved,
    )


__all__ = ["DB_ENV", "HostServices", "build_host_services"]