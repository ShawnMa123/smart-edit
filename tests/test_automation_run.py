"""Automation run core over HTTP: lifecycle, result, idempotency, cancel and capabilities."""

from __future__ import annotations

import json

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


def _run_body(view: dict, *, replacement: str = "USD 600,000.00") -> dict:
    return {
        "task_type": "rewrite",
        "document_id": view["document_id"],
        "draft_id": view["draft_id"],
        "input": {
            "intent": "replace_text",
            "search_text": "USD 500,000.00",
            "replacement_text": replacement,
        },
    }


def _create_run(
    client: TestClient, view: dict, *, key: str = "run-key", replacement: str = "USD 600,000.00"
):
    return client.post(
        "/automation/runs",
        json=_run_body(view, replacement=replacement),
        headers=_h(**{"Idempotency-Key": key}),
    )


def _poll(client: TestClient, run_id: str) -> dict:
    for _ in range(40):
        current = client.get(f"/automation/runs/{run_id}", headers=_h()).json()
        if current["status"] in ("succeeded", "failed", "cancelled", "timed_out"):
            return current
    return current


def test_run_result_and_dependencies(client, host):
    view = _document(client)
    response = _create_run(client, view)
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "queued"

    finished = _poll(client, run["run_id"])
    assert finished["status"] == "succeeded", finished
    assert finished["result_id"]
    result = client.get(f"/automation/results/{finished['result_id']}", headers=_h()).json()
    assert result["outcome"] == "proposal_ready"
    assert result["completion"] == "complete"
    assert result["payload"]["preview"]["after_text"] == "USD 600,000.00"
    assert result["limitations"][0]["code"] == "fixture_backed"
    assert result["payload"]["risk_flags"]
    dependencies = host.automation.store.list_dependencies("run", run["run_id"])
    assert any(row["resource_type"] == "draft_revision" for row in dependencies)
    assert any(row["resource_type"] == "variables_version" for row in dependencies)


def test_unsupported_task_type_is_rejected_without_a_run(client, host):
    view = _document(client)
    response = client.post(
        "/automation/runs",
        json={
            "task_type": "compare",
            "document_id": view["document_id"],
            "draft_id": view["draft_id"],
            "input": {},
        },
        headers=_h(**{"Idempotency-Key": "unsupported"}),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_implemented"
    assert (
        host.automation.store.list_runs(
            document_id=view["document_id"], owner_user_id="user_a", workspace_id="ws_demo_01"
        )
        == []
    )


def test_run_creation_is_idempotent_and_rejects_a_different_body(client):
    view = _document(client)
    first = _create_run(client, view, key="same-key")
    assert first.status_code == 202
    replay = _create_run(client, view, key="same-key")
    assert replay.status_code == 202
    assert replay.json()["run_id"] == first.json()["run_id"]

    conflict = _create_run(client, view, key="same-key", replacement="USD 700,000.00")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_cancel_queued_run(client, host):
    view = _document(client)
    host.runs.execute = lambda run_id: None  # keep the run queued for the cancel path
    created = _create_run(client, view, key="cancel-key")
    assert created.status_code == 202
    run = created.json()
    read = client.get(f"/automation/runs/{run['run_id']}", headers=_h())
    assert read.headers["ETag"] == f'"run-{run["revision"]}"'
    missing = client.post(
        f"/automation/runs/{run['run_id']}/cancel",
        json={"reason": "test"},
        headers=_h(),
    )
    assert missing.status_code == 428
    cancelled = client.post(
        f"/automation/runs/{run['run_id']}/cancel",
        json={"reason": "test"},
        headers=_h(**{"If-Match": f'"run-{run["revision"]}"'}),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_execute_times_out_when_deadline_passed(host):
    draft = host.store.create_document(
        workspace_id="ws_demo_01", owner_user_id="user_a", title="G", text="Amount: USD 500,000.00"
    )
    run = host.automation.store.create_run(
        task_type="rewrite",
        document_id=draft["document_id"],
        draft_id=draft["draft_id"],
        owner_user_id="user_a",
        workspace_id="ws_demo_01",
        deadline_at="2000-01-01T00:00:00+00:00",
        request_json="{}",
        dependencies=[],
    )
    host.runs.execute(run["run_id"])
    finished = host.automation.store.get_run(run["run_id"])
    assert finished["status"] == "timed_out"
    assert finished["result_id"] is None


def test_publish_after_cancel_is_rejected(host):
    from app.automation.store import AutomationStore
    from app.documents.errors import HostError

    draft = host.store.create_document(
        workspace_id="ws_demo_01", owner_user_id="user_a", title="G", text="Amount: USD 500,000.00"
    )
    run = host.automation.store.create_run(
        task_type="rewrite",
        document_id=draft["document_id"],
        draft_id=draft["draft_id"],
        owner_user_id="user_a",
        workspace_id="ws_demo_01",
        deadline_at="2999-01-01T00:00:00+00:00",
        request_json="{}",
        dependencies=[],
    )
    assert host.automation.store.cancel_run(run["run_id"])
    with pytest.raises(HostError) as error:
        AutomationStore(host.store).publish_result(
            run_id=run["run_id"],
            completion="complete",
            outcome="proposal_ready",
            payload={},
            limitations=[],
            proposal=None,
            review=None,
            dependencies=[],
            request_id="",
        )
    assert error.value.code == "run_not_running"


def test_publish_failure_rolls_back_result(host):
    draft = host.store.create_document(
        workspace_id="ws_demo_01", owner_user_id="user_a", title="G", text="Amount: USD 500,000.00"
    )
    run = host.automation.store.create_run(
        task_type="rewrite",
        document_id=draft["document_id"],
        draft_id=draft["draft_id"],
        owner_user_id="user_a",
        workspace_id="ws_demo_01",
        deadline_at="2999-01-01T00:00:00+00:00",
        request_json=json.dumps(
            {
                "task_type": "rewrite",
                "document_id": draft["document_id"],
                "draft_id": draft["draft_id"],
                "input": {
                    "intent": "replace_text",
                    "search_text": "USD 500,000.00",
                    "replacement_text": "USD 600,000.00",
                },
            }
        ),
        dependencies=[],
    )

    def boom(*args, **kwargs):
        raise RuntimeError("outbox down")

    original = host.store._enqueue
    host.store._enqueue = boom  # type: ignore[method-assign]
    host.runs.execute(run["run_id"])
    host.store._enqueue = original  # type: ignore[method-assign]

    finished = host.automation.store.get_run(run["run_id"])
    assert finished["status"] == "failed"
    assert host.automation.store.get_result_by_run(run["run_id"]) is None


def test_capability_and_cross_user(client):
    view = _document(client)
    denied = client.post(
        "/automation/runs",
        json=_run_body(view),
        headers=_h(**{"X-Demo-Capabilities": "read", "Idempotency-Key": "no-ai"}),
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "capability_denied"

    created = _create_run(client, view, key="owner-run")
    run_id = created.json()["run_id"]
    hidden = client.get(f"/automation/runs/{run_id}", headers=_h("user_b"))
    assert hidden.status_code == 404


def test_apply_rejects_a_missing_review_receipt(client, host):
    view = _document(client)
    lock = client.post(
        f"/documents/{view['document_id']}/drafts/{view['draft_id']}/lock",
        json={"lease_seconds": 120},
        headers=_h(),
    ).json()
    run = _poll(client, _create_run(client, view, key="review-run").json()["run_id"])
    result = client.get(f"/automation/results/{run['result_id']}", headers=_h()).json()
    proposal = result["payload"]
    accepted = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/decisions",
        json={"decision": "accepted"},
        headers=_h(**{"If-Match": f'"proposal-{proposal["revision"]}"', "Idempotency-Key": "acc"}),
    )
    assert accepted.status_code == 201

    with host.store.transaction() as conn:
        conn.execute(
            "DELETE FROM automation_reviews WHERE review_id=?",
            (proposal["review_receipt"]["receipt_id"],),
        )

    rejected = client.post(
        f"/automation/proposals/{proposal['proposal_id']}/apply",
        json={
            "proposal_id": proposal["proposal_id"],
            "expected_snapshot_id": proposal["context"]["content_sha256"],
            "expected_draft_revision": proposal["context"]["revision"],
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
            "acknowledged_risk_codes": proposal["risk_flags"],
        },
        headers=_h(**{"If-Match": '"draft-1"', "Idempotency-Key": "apply-review-missing"}),
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "review_required"