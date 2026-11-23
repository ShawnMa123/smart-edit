"""Document list: multiple documents per applicant, scoped to the caller (multi-document UI)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.documents.bootstrap import build_host_services
from tests.assistant_helpers import make_services


@pytest.fixture
def client(tmp_path):
    host = build_host_services(db_path=tmp_path / "host.db", mode="test")
    app = create_app(
        llm=None,
        runs_dir=tmp_path / "runs",
        assistant_services=make_services(tmp_path, seed=False),
        host_services=host,
    )
    with TestClient(app) as test_client:
        yield test_client


def _headers(user: str) -> dict[str, str]:
    return {"X-Demo-User": user}


def _create(client: TestClient, document_id: str, user: str, title: str) -> None:
    response = client.post(
        "/documents",
        json={"document_id": document_id, "title": title, "text": f"{title} body"},
        headers=_headers(user),
    )
    assert response.status_code == 201, response.text


def test_the_list_contains_only_the_callers_documents_as_drafts(client: TestClient):
    _create(client, "doc-a1", "user_a", "Guarantee A")
    _create(client, "doc-a2", "user_a", "Guarantee B")
    _create(client, "doc-b1", "user_b", "Someone else's")

    listing = client.get("/documents", headers=_headers("user_a"))

    assert listing.status_code == 200
    assert listing.headers["Cache-Control"] == "no-store"
    items = listing.json()
    assert {item["document_id"] for item in items} == {"doc-a1", "doc-a2"}
    assert {item["title"] for item in items} == {"Guarantee A", "Guarantee B"}
    assert all(item["submission_status"] == "draft" for item in items)
    assert all(item["revision"] == 1 for item in items)
    # The applicant can open any of them from the list entry point.
    opened = client.get(f"/documents/{items[0]['document_id']}", headers=_headers("user_a"))
    assert opened.status_code == 200
    assert opened.json()["text"].endswith("body")