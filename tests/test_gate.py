"""Export gate and immutable export (design §9 / tasks 6.5-6.6)."""

from __future__ import annotations

from app.nodes.export import export_node
from app.nodes.pipeline_gate import evaluate_export_gate, export_gate_node
from app.stages import stage_report
from app.storage.doc_versions import DocVersionStore


def _stages(**statuses: str) -> list[dict]:
    names = {
        "ingest": "agent1",
        "parse": "agent1",
        "extract": "agent1",
        "normalize": "agent1",
        "agent2": "agent2",
        "agent3": "agent3",
        "audit": "agent4",
    }
    return [
        stage_report(stage, status=statuses.get(stage, "done"), reason=None, agent=agent)
        for stage, agent in names.items()
    ]


def _state(**overrides) -> dict:
    state = {
        "run_id": "R-1",
        "files": [],
        "stages": _stages(),
        "findings": [],
        "fields": {},
        "legal": None,
        "verification": {
            "checks": [],
            "verdict": "pass",
            "credibility": {"assessed": 1, "planned": 1, "ratio": 1.0, "formula": "x"},
            "score": None,
        },
    }
    state.update(overrides)
    return state


def _allowed(monkeypatch):
    def fake(*args, **kwargs):
        return {
            "decision": "allowed",
            "operation": "formal_export",
            "candidate_content_sha256": args[2] if len(args) > 2 else "x",
            "policy_revision": "test",
            "evaluated_at": "2026-11-09T00:00:00+00:00",
            "reason_codes": [],
            "authorized_finding_ids": [],
        }

    monkeypatch.setattr("app.nodes.pipeline_gate.evaluate_operation", fake)


def test_all_checks_pass(monkeypatch):
    _allowed(monkeypatch)
    decision = evaluate_export_gate(_state())
    assert decision["verdict"] == "pass"
    assert decision["blocked"] is False
    assert decision["reasons"] == []


def test_missing_verification_blocks(monkeypatch):
    _allowed(monkeypatch)
    decision = evaluate_export_gate(_state(verification=None))
    assert decision["verdict"] == "blocked"
    assert "VERIFICATION_MISSING" in decision["reason_codes"]


def test_failed_verification_blocks(monkeypatch):
    _allowed(monkeypatch)
    decision = evaluate_export_gate(
        _state(verification={"checks": [], "verdict": "fail", "credibility": {}, "score": 0.9})
    )
    assert "VERIFICATION_FAIL" in decision["reason_codes"]


def test_unresolved_blocking_finding_blocks(monkeypatch):
    _allowed(monkeypatch)
    decision = evaluate_export_gate(
        _state(
            findings=[
                {
                    "id": "B-001",
                    "blocking": True,
                    "resolved": False,
                    "severity": "critical",
                }
            ]
        )
    )
    assert "BLOCKING_UNRESOLVED" in decision["reason_codes"]


def test_unconfirmed_inferred_field_blocks(monkeypatch):
    _allowed(monkeypatch)
    decision = evaluate_export_gate(
        _state(fields={"issue_date": {"status": "inferred", "confirmed": False}})
    )
    assert "INFERRED_UNCONFIRMED" in decision["reason_codes"]


def test_non_done_stage_blocks_even_with_zero_produced(monkeypatch):
    _allowed(monkeypatch)
    stages = [s for s in _stages() if s["stage"] != "agent2"]
    stages.append(stage_report("agent2", status="failed", reason="not checked", agent="agent2"))
    decision = evaluate_export_gate(_state(stages=stages))
    assert "STAGE_NOT_DONE" in decision["reason_codes"]
    incomplete = next(r for r in decision["reasons"] if r["code"] == "STAGE_NOT_DONE")
    assert incomplete["detail"]["stages"][0]["stage"] == "agent2"


def test_legal_escalation_and_unavailable_coverage_are_separate_reasons(monkeypatch):
    _allowed(monkeypatch)
    decision = evaluate_export_gate(
        _state(
            legal={
                "escalate_to_human": True,
                "coverage": {"unavailable": True, "notes": ["no_index"]},
            }
        )
    )
    assert "LEGAL_ESCALATED" in decision["reason_codes"]
    assert "COVERAGE_UNAVAILABLE" in decision["reason_codes"]


def test_operation_gate_indeterminate_is_not_a_pass(monkeypatch):
    def fake(*args, **kwargs):
        return {
            "decision": "indeterminate",
            "operation": "formal_export",
            "candidate_content_sha256": "x",
            "reason_codes": ["stale_report"],
            "evaluated_at": "2026-09-01T00:00:00+00:00",
        }

    monkeypatch.setattr("app.nodes.pipeline_gate.evaluate_operation", fake)
    decision = evaluate_export_gate(_state())
    assert decision["verdict"] == "blocked"
    assert "GATE_INDETERMINATE" in decision["reason_codes"]


def test_all_reasons_are_returned_without_short_circuit(monkeypatch):
    _allowed(monkeypatch)
    state = _state(
        verification={"checks": [], "verdict": "fail", "credibility": {}, "score": 0.99},
        findings=[{"id": "B-001", "blocking": True, "resolved": False}],
        fields={"x": {"status": "inferred", "confirmed": False}},
        legal={"escalate_to_human": True, "coverage": {"unavailable": True}},
    )
    state["stages"] = [s for s in state["stages"] if s["stage"] != "parse"]
    codes = set(evaluate_export_gate(state)["reason_codes"])
    assert {
        "VERIFICATION_FAIL",
        "BLOCKING_UNRESOLVED",
        "INFERRED_UNCONFIRMED",
        "STAGE_NOT_DONE",
        "LEGAL_ESCALATED",
        "COVERAGE_UNAVAILABLE",
    } <= codes


def test_score_never_blocks(monkeypatch):
    _allowed(monkeypatch)
    decision = evaluate_export_gate(
        _state(verification={"checks": [], "verdict": "pass", "credibility": {}, "score": 0.01})
    )
    assert decision["verdict"] == "pass"
    assert decision["score"] == 0.01


def test_gate_node_writes_a_stage_report(monkeypatch):
    _allowed(monkeypatch)
    update = export_gate_node(_state())
    assert update["stages"][0]["stage"] == "gate"
    assert update["stages"][0]["status"] == "done"
    assert update["gate"]["verdict"] == "pass"


def test_export_refuses_a_blocked_gate_and_writes_version_on_pass(tmp_path):
    blocked = export_node({"run_id": "R-1", "gate": {"verdict": "blocked", "reason_codes": ["X"]}})
    assert blocked["export"] is None
    assert blocked["stages"][0]["status"] == "skipped"

    store = DocVersionStore(tmp_path)
    passing = {
        "run_id": "R-1",
        "business_type": "guarantee",
        "fields": {"a": {"value": "1"}},
        "verification": {"verdict": "pass"},
        "gate": {"verdict": "pass", "candidate_content_sha256": "digest"},
    }
    first = export_node(passing, versions=store)
    second = export_node(passing, versions=store)
    assert first["export"]["version_no"] == 1
    assert second["export"]["version_no"] == 2
    assert first["export"]["doc_id"] == "R-1"
    assert first["export"]["snapshot_id"] == "digest"
    assert store.latest("R-1")["version_no"] == 2
