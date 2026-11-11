"""Executable assertions for seam (B + D) -> gate.

Run from the repo root:
    .venv/Scripts/python.exe -m pytest fixtures/seam_bd_to_gate/assert.py -q

The gate is a pure decision function; these assertions pin the properties the frontend and the
export service both rely on: every reason is returned at once, and `score` never decides.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.nodes.pipeline_gate import evaluate_export_gate

STATE = json.loads(Path(__file__).with_name("input.json").read_text(encoding="utf-8"))


def test_gate_is_blocked_and_returns_every_reason():
    decision = evaluate_export_gate(STATE)
    assert decision["verdict"] == "blocked"
    assert decision["blocked"] is True
    codes = set(decision["reason_codes"])
    assert {
        "VERIFICATION_FAIL",
        "BLOCKING_UNRESOLVED",
        "INFERRED_UNCONFIRMED",
        "STAGE_NOT_DONE",
        "LEGAL_ESCALATED",
        "COVERAGE_UNAVAILABLE",
    } <= codes
    assert len(decision["reasons"]) >= 6, "the gate must not short-circuit at the first reason"


def test_gate_binds_the_candidate_and_the_operation():
    decision = evaluate_export_gate(STATE)
    assert decision["operation"] == "formal_export"
    assert decision["candidate_content_sha256"]
    assert (STATE["run_id"], STATE["business_type"]) == ("seam-bd-to-gate", "guarantee")


def test_score_is_display_only():
    low = evaluate_export_gate(STATE)
    high_state = copy.deepcopy(STATE)
    high_state["verification"]["score"] = 0.99
    high = evaluate_export_gate(high_state)

    assert low["score"] == 0.02
    assert high["score"] == 0.99
    assert low["reason_codes"] == high["reason_codes"]
    assert not [code for code in low["reason_codes"] if "SCORE" in code.upper()]


def test_missing_verification_is_an_explicit_reason():
    without = copy.deepcopy(STATE)
    without.pop("verification")
    decision = evaluate_export_gate(without)
    assert "VERIFICATION_MISSING" in decision["reason_codes"]


def test_unresolved_critical_finding_is_listed_by_id():
    decision = evaluate_export_gate(STATE)
    reason = next(r for r in decision["reasons"] if r["code"] == "BLOCKING_UNRESOLVED")
    assert reason["detail"]["finding_ids"] == ["B-001"]


def test_required_stage_failure_names_the_stage():
    decision = evaluate_export_gate(STATE)
    reason = next(r for r in decision["reasons"] if r["code"] == "STAGE_NOT_DONE")
    assert reason["detail"]["stages"][0]["stage"] == "agent3"
