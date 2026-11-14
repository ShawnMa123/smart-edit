"""Build the A services with local adapters (design D2). C swaps this factory."""

from __future__ import annotations

import os
from pathlib import Path

from app.assistant.adapters import (
    AssistantServices,
    FakeAuthorization,
    FakeIdentity,
    FakeSnapshots,
    StoreAudit,
    SystemClock,
    assert_safe_mode,
    resolve_mode,
)
from app.assistant.pipeline import FixtureComposer
from app.assistant.store import SQLiteStore
from app.knowledge.retriever import LexicalRetriever
from app.knowledge.seed import seed_knowledge
from app.knowledge.service import KnowledgeService

DB_ENV = "SMART_EDIT_ASSISTANT_DB"


def build_services(
    *,
    db_path: str | Path | None = None,
    mode: str | None = None,
    seed: bool = True,
) -> AssistantServices:
    resolved = resolve_mode(mode)
    assert_safe_mode(resolved)
    store = SQLiteStore(db_path or os.environ.get(DB_ENV, "runs/assistant.db"))
    if seed:
        # Reconcile even when the DB is non-empty: an older local DB must gain new fixture
        # sources/versions (e.g. English corpus, help guide) on restart.
        seed_knowledge(store)
    return AssistantServices(
        store=store,
        identity=FakeIdentity(),
        authorization=FakeAuthorization(),
        snapshots=FakeSnapshots(store),
        audit=StoreAudit(store),
        clock=SystemClock(),
        retriever=LexicalRetriever(store),
        gateway=FixtureComposer(),
        knowledge_admin=KnowledgeService(store),
        mode=resolved,
    )