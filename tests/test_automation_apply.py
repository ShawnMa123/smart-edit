"""Automation over HTTP: fixture proposal, accept, atomic apply, idempotency and undo."""

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


def _document(client: TestClient) -> dict:
    response = client.post(
        "/documents",
        json={"document_id": "doc-1", "title": "G", "text": "Amount: USD 500,000.00"},
        headers=_h(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _lock(client: TestClient, view: dict) -> dict:
    response = client.post(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}/lock",
        json={"lease_seconds": 120},
        headers=_h(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _proposal(client: TestClient, view: dict) -> dict:
    response = client.post(
        "/automation/proposals",
        json={
            "document_id": view["document_id"],
            "draft_id": view["draft_id"],
            "search_text": "USD 500,000.00",
            "replacement_text": "USD 600,000.00",
        },
        headers=_h(**{"Idempotency-Key": "proposal-key"}),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _accept(client: TestClient, proposal: dict) -> dict:
    response = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/decisions",
        json={"decision": "accepted", "reason": "reviewed"},
        headers=_h(
            **{
                "If-Match": f'"proposal-{proposal["revision"]}"',
                "Idempotency-Key": "accept-key",
            }
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _apply_body(proposal: dict, view: dict, lock: dict) -> dict:
    return {
        "proposal_id": proposal["proposal_id"],
        "expected_snapshot_id": view["content_sha256"],
        "expected_draft_revision": view["revision"],
        "lock_id": lock["lock_id"],
        "fencing_token": lock["fencing_token"],
        "acknowledged_risk_codes": [],
    }


def test_accept_apply_replay_and_undo(client):
    view = _document(client)
    lock = _lock(client, view)
    proposal = _proposal(client, view)
    assert proposal["context"]["revision"] == 1
    assert proposal["applicability"] == "current"

    accepted = _accept(client, proposal)
    assert accepted["disposition"] == "accepted"
    assert accepted["application_status"] == "not_applied"

    first = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/apply",
        json=_apply_body(proposal, view, lock),
        headers=_h(**{"If-Match": '"draft-1"', "Idempotency-Key": "apply-key"}),
    )
    assert first.status_code == 201, first.text
    receipt = first.json()
    assert receipt["previous_revision"] == 1
    assert receipt["new_revision"] == 2

    draft = client.get(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}", headers=_h()
    ).json()
    assert draft["revision"] == 2
    assert "USD 600,000.00" in draft["text"]

    replay = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/apply",
        json=_apply_body(proposal, view, lock),
        headers=_h(**{"If-Match": '"draft-1"', "Idempotency-Key": "apply-key"}),
    )
    assert replay.status_code == 201
    assert replay.json()["receipt_id"] == receipt["receipt_id"]

    different_key = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/apply",
        json=_apply_body(proposal, view, lock),
        headers=_h(**{"If-Match": '"draft-1"', "Idempotency-Key": "apply-key-2"}),
    )
    assert different_key.status_code == 409
    assert different_key.json()["error"]["code"] == "already_applied"

    undo = client.post(
        f"/automation/applications/{receipt['receipt_id']}/undo",
        json={
            "expected_draft_revision": 2,
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h(**{"If-Match": '"draft-2"', "Idempotency-Key": "undo-key"}),
    )
    assert undo.status_code == 201, undo.text
    reversal = undo.json()
    assert reversal["reversal_of_receipt_id"] == receipt["receipt_id"]

    restored = client.get(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}", headers=_h()
    ).json()
    assert restored["revision"] == 3
    assert restored["text"] == "Amount: USD 500,000.00"

    twice = client.post(
        f"/automation/applications/{receipt['receipt_id']}/undo",
        json={
            "expected_draft_revision": 3,
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h(**{"If-Match": '"draft-3"', "Idempotency-Key": "undo-key-2"}),
    )
    assert twice.status_code == 409
    assert twice.json()["error"]["code"] == "undo_conflict"


def test_apply_after_head_moved_is_stale(client):
    view = _document(client)
    lock = _lock(client, view)
    proposal = _proposal(client, view)
    _accept(client, proposal)

    saved = client.put(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}",
        json={
            "text": "Amount: USD 700,000.00",
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
        headers=_h(**{"If-Match": '"draft-1"'}),
    )
    assert saved.status_code == 200

    stale = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/apply",
        json=_apply_body(proposal, view, lock),
        headers=_h(**{"If-Match": '"draft-1"', "Idempotency-Key": "stale-key"}),
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_context"
    head = client.get(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}", headers=_h()
    ).json()
    assert head["text"] == "Amount: USD 700,000.00"


def test_outbox_failure_rolls_back_apply(client, host):
    view = _document(client)
    lock = _lock(client, view)
    proposal = _proposal(client, view)
    _accept(client, proposal)

    original = host.store._enqueue

    def boom(*args, **kwargs):
        raise RuntimeError("outbox down")

    host.store._enqueue = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        client.post(
            f"/automation/proposals/{proposal['proposal_id']}/apply",
            json=_apply_body(proposal, view, lock),
            headers=_h(**{"If-Match": '"draft-1"', "Idempotency-Key": "rollback-key"}),
        )
    host.store._enqueue = original  # type: ignore[method-assign]

    draft = client.get(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}", headers=_h()
    ).json()
    assert draft["revision"] == 1
    assert host.automation.store.get_application_by_proposal(proposal["proposal_id"]) is None


def test_cross_user_cannot_read_or_apply(client):
    view = _document(client)
    lock = _lock(client, view)
    proposal = _proposal(client, view)
    _accept(client, proposal)

    hidden = client.get(
        f"/automation/proposals/{proposal['proposal_id']}", headers=_h("user_b")
    )
    assert hidden.status_code == 404
    denied = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/apply",
        json=_apply_body(proposal, view, lock),
        headers=_h("user_b", **{"If-Match": '"draft-1"', "Idempotency-Key": "other"}),
    )
    assert denied.status_code == 404