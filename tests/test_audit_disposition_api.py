"""`POST /runs/{thread_id}/findings/{finding_id}/disposition` — append-only human handling."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.llm import resolve_llm
from app.runs import RunStore
from app.stages import stage_report

FIXTURE = Path("fixtures/llm/extract_sample.json")
SAMPLE_TEXT = Path("fixtures/llm/sample_document.txt").read_text(encoding="utf-8")
VALUES = {
    "guarantee_number": "BG-2026-00417",
    "guarantee_amount": "500000.00",
    "currency": "USD",
    "applicant_name": "Alpha Tech Pte Ltd",
    "beneficiary_name": "Beta Construction Ltd",
    "issue_date": "2026-03-12",
    "expiry_date": "2027-03-12",
    "governing_rules": "URDG 758",
}


def _build(tmp_path):
    store = RunStore(runs_dir=tmp_path / "runs")
    llm = resolve_llm(f"fixture:{FIXTURE}")
    return TestClient(create_app(store=store, llm=llm)), store


@pytest.fixture
def api(tmp_path):
    return _build(tmp_path)


def _new_run(client: TestClient, text: str = SAMPLE_TEXT) -> str:
    response = client.post("/runs", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()["thread_id"]


def _field(key: str, value: str) -> dict:
    return {
        "key": key,
        "value": value,
        "status": "extracted",
        "confirmed": False,
        "edited_by_user": False,
        "source": {
            "file_id": "F-1",
            "page": 1,
            "bbox": None,
            "span": value,
            "form_label": None,
        },
        "normalized_from": value,
        "label": None,
        "doc_type": None,
        "notes": [],
    }


def _seed_blocked(store: RunStore, thread_id: str) -> None:
    state = store.get(thread_id)
    state["docs"] = [
        {"file_id": "F-1", "full_text": "\n".join(f"{key}: {value}" for key, value in VALUES.items())}
    ]
    state["fields"] = {
        key: _field(key, value) for key, value in VALUES.items() if key != "guarantee_amount"
    }
    state["stages"] = [
        stage_report(stage, status="done", agent="agent1")
        for stage in ("parse", "extract", "normalize")
    ]


def _audit(client: TestClient, thread_id: str) -> dict:
    response = client.post(f"/runs/{thread_id}/stages/audit")
    assert response.status_code == 200, response.text
    return response.json()


def _dispose(client: TestClient, thread_id: str, finding_id: str, **payload):
    payload.setdefault("actor", "ops")
    return client.post(
        f"/runs/{thread_id}/findings/{finding_id}/disposition", json=payload
    )


def test_disposition_appends_and_preserves_history(tmp_path):
    client, store = _build(tmp_path)
    thread_id = _new_run(client, "DEMAND GUARANTEE")
    _seed_blocked(store, thread_id)
    _audit(client, thread_id)
    before = copy.deepcopy(store.get(thread_id)["findings"][0])

    first = _dispose(client, thread_id, "B-001", disposition="accepted", reason="checked")
    second = _dispose(
        client, thread_id, "B-001", disposition="rejected", reason="vendor will resend"
    )

    assert first.status_code == second.status_code == 200
    body = second.json()
    assert [event["disposition"] for event in body["events"]] == ["accepted", "rejected"]
    assert body["latest"] == "rejected"
    assert body["events"][0]["actor"] == "ops"
    assert store.get(thread_id)["findings"][0] == before, "the finding itself is untouched"
    assert before["resolved"] is False and before["resolution"] is None
    trail = store.get(thread_id)["trail"]
    assert trail[-1]["op"] == "transform"
    assert trail[-1]["detail"] == {
        "finding_id": "B-001",
        "disposition": "rejected",
        "actor": "ops",
    }


def test_rejecting_a_critical_finding_requires_a_reason(tmp_path):
    client, store = _build(tmp_path)
    thread_id = _new_run(client, "DEMAND GUARANTEE")
    _seed_blocked(store, thread_id)
    _audit(client, thread_id)

    response = _dispose(client, thread_id, "B-001", disposition="rejected", reason="   ")

    assert response.status_code == 400
    assert response.json()["code"] == "REASON_REQUIRED"
    assert store.get(thread_id)["dispositions"] == []


def test_unknown_finding_is_404(api):
    client, _ = api
    thread_id = _new_run(client)

    response = _dispose(client, thread_id, "B-999", disposition="accepted")

    assert response.status_code == 404
    assert response.json()["code"] == "UNKNOWN_FINDING"


def test_unknown_disposition_or_missing_actor_is_refused(tmp_path):
    client, store = _build(tmp_path)
    thread_id = _new_run(client, "DEMAND GUARANTEE")
    _seed_blocked(store, thread_id)
    _audit(client, thread_id)

    unknown = _dispose(client, thread_id, "B-001", disposition="dismissed")
    anonymous = _dispose(
        client, thread_id, "B-001", disposition="accepted", actor=""
    )

    assert unknown.status_code == 400
    assert unknown.json()["code"] == "INVALID_DISPOSITION"
    assert anonymous.status_code == 400
    assert anonymous.json()["code"] == "INVALID_DISPOSITION"
    assert store.get(thread_id)["dispositions"] == []


def test_latest_disposition_changes_the_gate_answer(api):
    client, store = api
    thread_id = _new_run(client)
    _audit(client, thread_id)
    state = store.get(thread_id)
    state["findings"].append(
        {
            "id": "B-999",
            "source": "business",
            "kind": "inconsistent",
            "rule_id": "manual_review",
            "severity": "critical",
            "blocking": False,
            "resolved": False,
            "resolution": None,
            "field_keys": [],
            "message": "needs a human decision",
            "evidence": None,
            "citation": None,
            "suggestion": None,
        }
    )
    state["verification"]["audit"]["findings"].append(
        {
            "id": "B-999",
            "check_id": "EVIDENCE:manual",
            "rule_id": "manual_review",
            "rule_version": 1,
            "category": "evidence",
            "severity": "critical",
            "gate_type": "advisory",
            "target_operations": [],
            "method": "deterministic",
            "field_id": None,
            "evidence": None,
            "message": "needs a human decision",
        }
    )

    before = client.post(
        f"/runs/{thread_id}/gate", json={"operation": "start_approval"}
    ).json()["gate"]
    accepted = _dispose(client, thread_id, "B-999", disposition="accepted", reason="reviewed")
    after_dispose = client.get(f"/runs/{thread_id}").json()["gate"]
    after = client.post(
        f"/runs/{thread_id}/gate", json={"operation": "start_approval"}
    ).json()["gate"]

    assert before["decision"] == "blocked"
    assert before["reason_codes"] == ["unresolved_critical"]
    assert accepted.status_code == 200
    assert accepted.json()["latest"] == "accepted"
    assert after_dispose is None, "a decision made before the disposition is stale"
    assert after["decision"] == "allowed"
    assert after["reason_codes"] == []
