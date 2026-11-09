"""`POST /runs/{thread_id}/gate` — the gate is a command, not an audit stage output."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.audit.snapshot import snapshot_digest
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


def _seed(store: RunStore, thread_id: str, *, drop: str | None = None) -> None:
    """Put the run one audit away from done without making extract/normalize overwrite the fields."""
    state = store.get(thread_id)
    state["docs"] = [
        {"file_id": "F-1", "full_text": "\n".join(f"{key}: {value}" for key, value in VALUES.items())}
    ]
    state["fields"] = {
        key: _field(key, value) for key, value in VALUES.items() if key != drop
    }
    state["stages"] = [
        stage_report(stage, status="done", agent="agent1")
        for stage in ("parse", "extract", "normalize")
    ]


def _audit(client: TestClient, thread_id: str) -> dict:
    response = client.post(f"/runs/{thread_id}/stages/audit")
    assert response.status_code == 200, response.text
    return response.json()


def test_gate_returns_indeterminate_without_an_audit(api):
    client, _ = api
    thread_id = _new_run(client)

    response = client.post(f"/runs/{thread_id}/gate", json={"operation": "start_approval"})

    assert response.status_code == 200
    body = response.json()
    assert body["gate"]["decision"] == "indeterminate"
    assert body["gate"]["reason_codes"] == ["no_audit_report"]
    assert body["verification"] is None


def test_gate_blocks_a_missing_required_field(tmp_path):
    client, store = _build(tmp_path)
    thread_id = _new_run(client, "DEMAND GUARANTEE")
    _seed(store, thread_id, drop="guarantee_amount")
    _audit(client, thread_id)

    response = client.post(f"/runs/{thread_id}/gate", json={"operation": "start_approval"})

    body = response.json()
    assert body["gate"]["decision"] == "blocked"
    assert "hard_block" in body["gate"]["reason_codes"]
    assert body["gate"]["authorized_finding_ids"] == ["B-001"]
    assert body["verification"]["verdict"] == "fail"


def test_gate_allows_a_clean_document(api):
    client, _ = api
    thread_id = _new_run(client)
    _audit(client, thread_id)

    response = client.post(f"/runs/{thread_id}/gate", json={"operation": "start_approval"})

    body = response.json()
    assert body["gate"]["decision"] == "allowed"
    assert body["gate"]["reason_codes"] == []
    assert body["verification"]["verdict"] == "pass"


def test_gate_rejects_unknown_or_missing_operation(api):
    client, _ = api
    thread_id = _new_run(client)

    for payload in ({}, {"operation": "approve_by_email"}):
        response = client.post(f"/runs/{thread_id}/gate", json=payload)

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "UNKNOWN_OPERATION"
        assert "start_approval" in body["detail"]["known_operations"]


def test_gate_rejects_an_unknown_run(api):
    client, _ = api

    response = client.post("/runs/R-nope/gate", json={"operation": "start_approval"})

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_run"


def test_gate_binds_the_candidate_digest(api):
    client, store = api
    thread_id = _new_run(client)
    _audit(client, thread_id)
    current = snapshot_digest(store.get(thread_id))

    stale = client.post(
        f"/runs/{thread_id}/gate",
        json={"operation": "start_approval", "candidate_digest": "a-different-candidate"},
    ).json()
    fresh = client.post(
        f"/runs/{thread_id}/gate",
        json={"operation": "start_approval", "candidate_digest": current},
    ).json()

    assert stale["gate"]["decision"] == "indeterminate"
    assert stale["gate"]["reason_codes"] == ["stale_report"]
    assert stale["gate"]["candidate_content_sha256"] == "a-different-candidate"
    assert fresh["gate"]["decision"] == "allowed"
    assert fresh["gate"]["candidate_content_sha256"] == current


def test_gate_decision_is_stored_on_the_run(api):
    client, _ = api
    thread_id = _new_run(client)
    _audit(client, thread_id)

    asked = client.post(
        f"/runs/{thread_id}/gate", json={"operation": "start_approval"}
    ).json()

    body = client.get(f"/runs/{thread_id}").json()
    assert body["gate"] == asked["gate"]


def test_asking_the_gate_twice_updates_the_decision(tmp_path):
    client, store = _build(tmp_path)
    thread_id = _new_run(client, "DEMAND GUARANTEE")
    _seed(store, thread_id, drop="guarantee_amount")
    _audit(client, thread_id)

    first = client.post(
        f"/runs/{thread_id}/gate", json={"operation": "start_approval"}
    ).json()["gate"]
    second = client.post(
        f"/runs/{thread_id}/gate", json={"operation": "save_draft"}
    ).json()["gate"]

    assert first["decision"] == "blocked"
    assert second["decision"] == "allowed"
    assert second["reason_codes"] == ["draft_not_gated"]
    stored = client.get(f"/runs/{thread_id}").json()["gate"]
    assert stored["operation"] == "save_draft"
    assert stored["decision"] == "allowed"
