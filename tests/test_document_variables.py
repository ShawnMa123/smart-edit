"""Variables are versioned independently from document content."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.documents.bootstrap import build_host_services
from tests.assistant_helpers import make_services


@pytest.fixture
def host(tmp_path):
    return build_host_services(db_path=tmp_path / "host.db", mode="test")


@pytest.fixture
def client(tmp_path, host):
    app = create_app(
        llm=None,
        runs_dir=tmp_path / "runs",
        assistant_services=make_services(tmp_path, seed=False),
        host_services=host,
    )
    with TestClient(app) as test_client:
        yield test_client


def _h(user: str = "user_a", **extra: str) -> dict[str, str]:
    return {"X-Demo-User": user, **extra}


def _create(client: TestClient) -> dict:
    response = client.post(
        "/documents",
        json={
            "document_id": "doc-1",
            "title": "G",
            "text": "Amount: USD 500,000.00",
            "variables": {"guarantee_amount": "500000.00"},
        },
        headers=_h(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _lock(client: TestClient, view: dict, user: str = "user_a") -> dict:
    response = client.post(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}/lock",
        json={"lease_seconds": 120},
        headers=_h(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_content_save_preserves_variables(client, host):
    view = _create(client)
    lock = _lock(client, view)
    saved = client.put(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}",
        json={
            "text": "Amount: USD 600,000.00",
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h(**{"If-Match": '"draft-1"'}),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["revision"] == 2
    assert body["variables_version"] == 1
    assert body["variables"] == {"guarantee_amount": "500000.00"}
    assert host.store.get_draft(view["draft_id"])["variables_json"] == '{"guarantee_amount": "500000.00"}'


def test_variable_update_is_independent_and_conditional(client):
    view = _create(client)
    lock = _lock(client, view)
    url = f"/documents/{view['document_id']}/drafts/{view['draft_id']}/variables"

    missing = client.patch(
        url,
        json={
            "variables": {"guarantee_amount": "600000.00"},
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h(),
    )
    assert missing.status_code == 428

    updated = client.patch(
        url,
        json={
            "variables": {"guarantee_amount": "600000.00"},
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h(**{"If-Match": '"variables-1"'}),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["revision"] == 1
    assert body["variables_version"] == 2
    assert body["variables"] == {"guarantee_amount": "600000.00"}
    assert updated.headers["ETag"] == '"variables-2"'

    stale = client.patch(
        url,
        json={
            "variables": {"guarantee_amount": "700000.00"},
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h(**{"If-Match": '"variables-1"'}),
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "stale_variables"


def test_variable_update_requires_lock_and_owner(client):
    view = _create(client)
    lock = _lock(client, view)
    url = f"/documents/{view['document_id']}/drafts/{view['draft_id']}/variables"
    wrong = client.patch(
        url,
        json={
            "variables": {"guarantee_amount": "600000.00"},
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"] + 1,
        },
        headers=_h(**{"If-Match": '"variables-1"'}),
    )
    assert wrong.status_code == 409
    assert wrong.json()["error"]["code"] == "lock_conflict"

    hidden = client.patch(
        url,
        json={
            "variables": {"guarantee_amount": "600000.00"},
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h("user_b", **{"If-Match": '"variables-1"'}),
    )
    assert hidden.status_code == 404