"""Document-host HTTP contract: ETag/If-Match, conflicts and locks."""

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


def _headers(user: str = "user_a", **extra: str) -> dict[str, str]:
    return {"X-Demo-User": user, **extra}


def _create(client: TestClient, *, user: str = "user_a") -> dict:
    response = client.post(
        "/documents",
        json={"document_id": "doc-1", "title": "Guarantee", "text": "Amount: USD 500,000.00"},
        headers=_headers(user),
    )
    assert response.status_code == 201, response.text
    assert response.headers["ETag"] == '"draft-1"'
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def _lock(client: TestClient, view: dict, *, user: str = "user_a") -> dict:
    response = client.post(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}/lock",
        json={"lease_seconds": 30},
        headers=_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_read_and_etag(client):
    view = _create(client)
    assert view["revision"] == 1
    assert view["text"] == "Amount: USD 500,000.00"
    assert view["content_sha256"]

    read = client.get(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}", headers=_headers()
    )
    assert read.status_code == 200
    assert read.headers["ETag"] == '"draft-1"'
    assert read.json()["draft_id"] == view["draft_id"]


def test_conditional_save_requires_match_and_locks(client):
    view = _create(client)
    lock = _lock(client, view)
    url = f"/documents/{view['document_id']}/drafts/{view['draft_id']}"

    missing = client.put(
        url,
        json={"text": "two", "lock_id": lock["lock_id"], "fencing_token": lock["fencing_token"]},
        headers=_headers(),
    )
    assert missing.status_code == 428
    assert missing.json()["error"]["code"] == "precondition_required"

    saved = client.put(
        url,
        json={"text": "Amount: USD 600,000.00", "lock_id": lock["lock_id"], "fencing_token": lock["fencing_token"]},
        headers=_headers(**{"If-Match": '"draft-1"'}),
    )
    assert saved.status_code == 200, saved.text
    assert saved.headers["ETag"] == '"draft-2"'
    assert saved.json()["revision"] == 2

    stale = client.put(
        url,
        json={"text": "three", "lock_id": lock["lock_id"], "fencing_token": lock["fencing_token"]},
        headers=_headers(**{"If-Match": '"draft-1"'}),
    )
    assert stale.status_code == 412
    body = stale.json()["error"]
    assert body["code"] == "stale_draft"
    assert body["current_revision"] == 2
    assert "text" not in body

    wrong_token = client.put(
        url,
        json={
            "text": "three",
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"] + 1,
        },
        headers=_headers(**{"If-Match": '"draft-2"'}),
    )
    assert wrong_token.status_code == 409
    assert wrong_token.json()["error"]["code"] == "lock_conflict"

    head = client.get(url, headers=_headers()).json()
    assert head["text"] == "Amount: USD 600,000.00"


def test_save_without_current_lock_is_rejected(client):
    view = _create(client)
    url = f"/documents/{view['document_id']}/drafts/{view['draft_id']}"
    response = client.put(
        url,
        json={"text": "two", "lock_id": "lock_missing", "fencing_token": 1},
        headers=_headers(**{"If-Match": '"draft-1"'}),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lock_conflict"


def test_second_user_cannot_lock_or_read(client):
    view = _create(client)
    _lock(client, view, user="user_a")
    conflict = client.post(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}/lock",
        json={"lease_seconds": 30},
        headers=_headers("user_b"),
    )
    assert conflict.status_code == 404

    hidden = client.get(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}", headers=_headers("user_b")
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_lock_heartbeat_and_release(client):
    view = _create(client)
    lock = _lock(client, view)
    base = f"/documents/{view['document_id']}/locks/{lock['lock_id']}"
    heartbeat = client.post(
        f"{base}/heartbeat", json={"lease_seconds": 90}, headers=_headers()
    )
    assert heartbeat.status_code == 200
    released = client.post(f"{base}/release", headers=_headers())
    assert released.status_code == 200
    assert released.json()["released_at"] is not None


def test_error_body_has_request_id(client):
    response = client.get("/documents/missing", headers=_headers())
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]