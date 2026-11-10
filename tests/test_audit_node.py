"""Tasks 6.1 / 6.2 — the `audit` node and its standalone trigger.

The node is a thin shell: it may only call pure functions, write one `StageReport`, append trail
entries and store the report. Everything asserted here is about that shell — the numbers come from
`test_audit_project.py`, the decisions from `test_audit_gate.py`.
"""

from __future__ import annotations

import pytest

from app.audit.gate import evaluate as gate_for_state
from app.audit.policy import BLOCKED, START_APPROVAL
from app.audit.snapshot import snapshot_digest
from app.nodes.audit import AUDIT_AGENT, AUDIT_STAGE, audit_node
from app.nodes.gate import gate_node
from app.runtime import execute_chain, merge_update
from app.standalone import plan_standalone
from app.state import OVERREACH_OPS, STAGE_STATUS, TRAIL_OPS
from app.stages import AGENT_SPECS, STAGE_TARGETS

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
DOCUMENT = "DEMAND GUARANTEE\n" + "\n".join(f"{key}: {value}" for key, value in VALUES.items())


def _field(key: str, value: str) -> dict:
    return {
        "key": key,
        "value": value,
        "status": "extracted",
        "confirmed": False,
        "edited_by_user": False,
        "source": {"file_id": "F-1", "page": 1, "bbox": None, "span": value, "form_label": None},
        "normalized_from": value,
        "label": None,
        "doc_type": None,
        "notes": [],
    }


def _state(**overrides) -> dict:
    state = {
        "run_id": "R-1",
        "files": [{"file_id": "F-1", "filename": "g.txt", "mime": "text/plain", "path": "p", "sha256": "a" * 64}],
        "docs": [{"file_id": "F-1", "full_text": DOCUMENT}],
        "fields": {key: _field(key, value) for key, value in VALUES.items()},
        "extra_fields": {},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "agent": "agent1", "stage": "parse", "op": "read"}],
        "stages": [],
    }
    state.update(overrides)
    return state


def test_a_clean_document_audits_into_one_done_stage_report():
    """6.1 One report, agent4, zero model calls, findings counted."""
    update = audit_node(_state())
    report = update["stages"][0]

    assert list(report) == ["stage", "agent", "status", "reason", "produced", "model_calls"]
    assert report["stage"] == AUDIT_STAGE
    assert report["agent"] == AUDIT_AGENT
    assert report["status"] == "done"
    assert report["reason"] is None
    assert report["model_calls"] == 0
    assert report["produced"] == len(update["findings"].value) == 0


def test_the_verification_slot_carries_the_report_baseline():
    """3.3 / 6.1 `verification.audit` is where the report lives (`VerificationReport.audit`)."""
    state = _state()
    update = audit_node(state)
    verification = update["verification"]

    assert set(verification) == {"checks", "verdict", "credibility", "score", "audit"}
    assert verification["score"] is None
    assert verification["verdict"] == "pass"
    assert len(verification["checks"]) == 51
    assert verification["audit"]["snapshot_digest"] == snapshot_digest(state)
    assert verification["audit"]["planned"] == 51
    assert verification["audit"]["outcome"] == "no_findings"


def test_trail_entries_use_contract_ops_and_unique_ids():
    """6.1 The receipt plus one `emit` per finding, with ids that never collide."""
    state = _state()
    state["fields"]["expiry_date"] = _field("expiry_date", "2025-03-12")
    update = audit_node(state)
    trail = update["trail"]

    assert {entry["op"] for entry in trail} <= set(TRAIL_OPS)
    assert not OVERREACH_OPS & {entry["op"] for entry in trail}
    assert len({entry["id"] for entry in trail}) == len(trail)
    assert trail[0]["op"] == "pass"
    assert trail[0]["detail"]["snapshot_digest"] == snapshot_digest(state)
    assert trail[0]["detail"]["model_calls"] == 0
    assert [entry["op"] for entry in trail[1:]] == ["emit"] * len(update["findings"].value)
    assert {entry["agent"] for entry in trail} == {AUDIT_AGENT}
    assert trail[1]["id"] == "agent4.audit#002"


def test_a_failing_audit_returns_a_stage_report_instead_of_raising():
    """6.1 A broken audit must not take the run down, and must clear the old verification."""
    update = audit_node(_state(), bundles=[])

    report = update["stages"][0]
    assert report["stage"] == AUDIT_STAGE
    assert report["status"] in STAGE_STATUS and report["status"] == "failed"
    assert "audit refused" in report["reason"]
    assert update["verification"] is None, "a previous report must not survive a failed audit"
    assert update["gate"] is None, "an old decision must not sit next to a failed audit"
    assert update["trail"][0]["detail"]["audited"] is False


def test_an_audit_never_writes_a_gate_decision():
    """6.3 / 5.2 The audit is evidence; only the gate command decides."""
    assert audit_node(_state())["gate"] is None

    state = _state()
    state["fields"].pop("guarantee_amount")
    assert audit_node(state)["gate"] is None


def test_an_audit_replaces_its_own_rows_and_keeps_other_producers():
    """Only audit findings are bound to the audit snapshot; regulatory/normalization rows stay."""
    state = _state()
    regulatory = {"id": "R-001", "source": "regulatory", "severity": "warn", "field_keys": []}
    state["findings"] = [regulatory]

    merge_update(state, audit_node(state))
    assert [finding["id"] for finding in state["findings"]].count("R-001") == 1

    merge_update(state, audit_node(state, bundles=[]))  # deterministic failure
    assert [finding["id"] for finding in state["findings"]] == ["R-001"]


def test_the_gate_command_stores_one_decision_bound_to_the_snapshot():
    """6.3 An audit alone approves nothing; asking for an operation stores one decision."""
    state = _state()
    state["fields"].pop("guarantee_amount")
    merge_update(state, audit_node(state))

    update = gate_node(state, START_APPROVAL)

    assert set(update) == {"gate"}, "the gate writes nothing but its decision"
    assert update["gate"]["operation"] == START_APPROVAL
    assert update["gate"]["decision"] == BLOCKED
    assert "hard_block" in update["gate"]["reason_codes"]
    assert update["gate"]["candidate_content_sha256"] == snapshot_digest(state)

    merge_update(state, update)
    assert state["gate"] == update["gate"]


def test_the_stored_report_is_what_the_gate_reads():
    """The contract `Finding` has no gate type, so the gate must read the audit's own copy."""
    state = _state()
    state["fields"].pop("guarantee_amount")
    merge_update(state, audit_node(state))

    decision = gate_for_state(state, START_APPROVAL, candidate_digest=snapshot_digest(state))

    assert decision["decision"] == BLOCKED
    assert "hard_block" in decision["reason_codes"]
    assert decision["authorized_finding_ids"] == ["B-001"]


def test_plan_standalone_audit_declares_the_whole_shared_layer():
    """6.2 `plan_standalone("audit", state)` returns a runnable chain, never a widening."""
    plan = plan_standalone("audit", _state(stages=[], fields={}))

    assert plan["status"] == 200
    assert plan["chain"] == ["parse", "extract", "normalize", "audit"]
    assert plan["target"] == "audit"

    done = _state(stages=[{"stage": stage, "status": "done"} for stage in ("parse", "extract", "normalize")])
    assert plan_standalone("audit", done)["chain"] == ["audit"]


def test_agent4_resolves_to_the_audit_target():
    """0.2 / 6.2 The agent id is an alias, not a second code path."""
    plan = plan_standalone("agent4", _state(fields={}))

    assert AGENT_SPECS["agent4"].standalone is True
    assert "audit" in STAGE_TARGETS
    assert plan["target"] == "audit"
    assert plan["requested"] == "agent4"
    assert plan["chain"][-1] == "audit"


def test_an_unimplemented_prerequisite_is_refused_not_skipped(monkeypatch):
    """`merge` does not exist in this build: say so instead of running without it."""
    from app import standalone
    from app.stages import AgentSpec

    patched = dict(STAGE_TARGETS)
    patched["pretend"] = AgentSpec("agent4", ("merge",), (), (), True)
    monkeypatch.setattr(standalone, "STAGE_TARGETS", patched)

    plan = standalone.plan_standalone("pretend", _state())

    assert plan["status"] == 409
    assert plan["error"] == "REFUSED"
    assert plan["missing"] == ["merge"]


def test_the_snapshot_digest_ignores_derived_data():
    """3.3 / 9.3 The digest identifies the candidate, not the audit's own output."""
    state = _state()
    before = snapshot_digest(state)

    state["findings"] = [{"id": "B-001"}]
    state["trail"].append({"id": "agent4.audit#001", "op": "pass"})
    assert snapshot_digest(state) == before, "derived rows must not move the digest"

    state["fields"]["guarantee_amount"] = _field("guarantee_amount", "500001.00")
    assert snapshot_digest(state) != before


def test_a_done_audit_is_not_repeated():
    """The stage is idempotent: a second trigger reuses the report instead of re-auditing."""
    state = _state()
    execute_chain(state, ["audit"])
    trail_after_first = len(state["trail"])

    execute_chain(state, ["audit"])

    assert [report["stage"] for report in state["stages"]] == ["audit"]
    assert len(state["trail"]) == trail_after_first