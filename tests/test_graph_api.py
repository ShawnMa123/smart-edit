"""Graph control-plane HTTP endpoints (additive to the five console endpoints)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.runner import Runner
from app.runs import RunStore
from app.store import RunStore as Ledger
from tests.graph_helpers import FakeLLM, build_test_graph


def _client(tmp_path: Path):
    runs = RunStore(runs_dir=tmp_path / "runs")
    runner = Runner(
        runs,
        graph=build_test_graph(FakeLLM()),
        ledger=Ledger(tmp_path / "ledger.sqlite"),
    )
    return TestClient(create_app(store=runs, llm=None, runner=runner)), runs


def _new_run(client: TestClient) -> str:
    response = client.post(
        "/runs", json={"text": "保函编号：BG-2026-0001\n币种：USD\n"}
    )
    assert response.status_code == 201
    return response.json()["thread_id"]


def test_run_resume_and_events(tmp_path):
    client, _ = _client(tmp_path)
    thread_id = _new_run(client)

    started = client.post(f"/runs/{thread_id}/run")
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "interrupted"
    assert set(body["interrupt"]) == {
        "run_id",
        "business_type",
        "fields",
        "findings",
        "legal",
        "verification",
        "stages",
    }
    assert any(report["stage"] == "parse" and report["status"] == "done" for report in body["stages"])

    timeline = client.get(f"/runs/{thread_id}/events")
    assert timeline.status_code == 200
    types = {event["type"] for event in timeline.json()["events"]}
    assert {"node", "stage", "trail"} <= types

    resumed = client.post(
        f"/runs/{thread_id}/resume", json={"edits": [], "recheck": False}
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "complete"
    assert resumed.json()["gate"]["verdict"] in ("pass", "blocked")

    # A second identical resume must not append another hitl report or trail entry.
    hitl_before = len([r for r in resumed.json()["stages"] if r["stage"] == "hitl"])
    trail_before = len(resumed.json()["trail"])
    duplicate = client.post(
        f"/runs/{thread_id}/resume", json={"edits": [], "recheck": False}
    )
    assert duplicate.status_code == 200
    assert len([r for r in duplicate.json()["stages"] if r["stage"] == "hitl"]) == hitl_before
    assert len(duplicate.json()["trail"]) == trail_before


def test_autostart_returns_the_first_interrupt(tmp_path):
    """Task 9.1 is available without changing the console's default create semantics."""
    client, _ = _client(tmp_path)
    response = client.post(
        "/runs?autostart=true",
        json={"text": "保函编号：BG-2026-0001\n币种：USD\n"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "interrupted"
    assert body["interrupt"]["run_id"] == body["thread_id"]
    assert any(report["stage"] == "parse" for report in body["stages"])


def test_unknown_run_on_the_control_plane_is_404(tmp_path):
    client, _ = _client(tmp_path)
    assert client.post("/runs/nope/run").status_code == 404
    assert client.post("/runs/nope/resume", json={}).status_code == 404
    assert client.get("/runs/nope/events").status_code == 404


def test_agent3_enriched_is_opt_in(tmp_path, monkeypatch):
    from app.regulatory.retriever import FakeRetriever

    monkeypatch.setattr(
        "app.regulatory.node.resolve_retriever",
        lambda: FakeRetriever([], {"version": "test", "documents": 0, "jurisdictions": []}),
    )
    client, _ = _client(tmp_path)
    thread_id = _new_run(client)

    raw = client.post(f"/runs/{thread_id}/stages/agent3")
    enriched = client.post(f"/runs/{thread_id}/stages/agent3?input_mode=enriched")

    assert raw.status_code == 200
    assert enriched.status_code == 200
    assert any(report["stage"] == "agent3" for report in enriched.json()["stages"])
