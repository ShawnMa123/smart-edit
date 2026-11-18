"""Builders for the knowledge-assistant tests (no fixtures here, like `tests/helpers.py`)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.assistant.adapters import (
    AssistantServices,
    FakeAuthorization,
    FakeIdentity,
    FakeSnapshots,
    StoreAudit,
    SystemClock,
    SystemIds,
)
from app.assistant.pipeline import FixtureComposer
from app.assistant.service import AssistantService
from app.assistant.store import SQLiteStore
from app.knowledge.retriever import LexicalRetriever
from app.knowledge.seed import seed_knowledge
from app.knowledge.service import KnowledgeService

WORKSPACE = "ws_demo_01"


def make_store(tmp_path: Path, *, seed: bool = True, name: str = "assistant.db") -> SQLiteStore:
    store = SQLiteStore(tmp_path / name)
    if seed:
        seed_knowledge(store)
    return store


def make_services(
    tmp_path: Path,
    *,
    seed: bool = True,
    retriever=None,
    gateway=None,
    egress=None,
    web=None,
    settings=None,
) -> AssistantServices:
    store = make_store(tmp_path, seed=seed)
    return AssistantServices(
        store=store,
        identity=FakeIdentity(),
        authorization=FakeAuthorization(),
        snapshots=FakeSnapshots(store),
        audit=StoreAudit(store),
        clock=SystemClock(),
        retriever=retriever or LexicalRetriever(store),
        gateway=gateway or FixtureComposer(),
        ids=SystemIds(),
        knowledge_admin=KnowledgeService(store),
        mode="test",
        egress=egress,
        web=web,
        settings=settings,
    )


def make_service(
    tmp_path: Path,
    *,
    seed: bool = True,
    retriever=None,
    gateway=None,
    egress=None,
    web=None,
    settings=None,
    deadline_seconds: int = 60,
) -> AssistantService:
    return AssistantService(
        make_services(
            tmp_path,
            seed=seed,
            retriever=retriever,
            gateway=gateway,
            egress=egress,
            web=web,
            settings=settings,
        ),
        deadline_seconds=deadline_seconds,
    )


def make_client(tmp_path: Path, *, services: AssistantServices | None = None) -> TestClient:
    app = create_app(
        llm=None,
        runs_dir=tmp_path / "runs",
        assistant_services=services or make_services(tmp_path),
    )
    return TestClient(app)


def headers(user: str = "user_a", key: str | None = None) -> dict[str, str]:
    values = {"X-Demo-User": user}
    if key:
        values["Idempotency-Key"] = key
    return values


def register_snapshot(
    client: TestClient, *, text: str, user: str = "user_a", document_id: str = "doc-1"
) -> dict:
    import hashlib

    response = client.post(
        "/assistant/snapshots",
        json={
            "document_id": document_id,
            "text": text,
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "version_label": "v1",
        },
        headers=headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()