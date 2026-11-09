"""Tasks 3.3 and 4.1-4.3 — the report baseline and its projection into contract rows.

The two halves are deliberately tested apart: `summarise()` owns the numbers, `project.py` owns the
shape a client reads. A bug in either must be visible without an HTTP request.
"""

from __future__ import annotations

import pytest

from app.audit.gate import evaluate_gate
from app.audit.policy import START_APPROVAL
from app.audit.project import (
    DANGLING_ANCHOR,
    SEMANTIC_HARD_BLOCK,
    credibility,
    enforce_anchor,
    enforce_method_contract,
    finding_draft,
    finding_of,
    known_fields,
    project_issue,
    to_verification,
    verdict_for,
)
from app.audit.report import OUTCOME_FINDINGS, OUTCOME_NEEDS_INPUT, OUTCOME_NONE, OUTCOME_UNABLE
from app.audit.runner import audit_state
from app.rules.schema import load_schema
from app.rules.types import FAILED, FINDING, NEEDS_INPUT, CheckResult, Unit

CLEAN_VALUES = {
    "guarantee_number": "BG-2026-00417",
    "guarantee_amount": "500000.00",
    "currency": "USD",
    "applicant_name": "Alpha Tech Pte Ltd",
    "beneficiary_name": "Beta Construction Ltd",
    "issue_date": "2026-03-12",
    "expiry_date": "2027-03-12",
    "governing_rules": "URDG 758",
}
DOCUMENT = "DEMAND GUARANTEE\n" + "\n".join(f"{key}: {value}" for key, value in CLEAN_VALUES.items())


def _field(key: str, value: str, *, status: str = "extracted") -> dict:
    return {
        "key": key,
        "value": value,
        "status": status,
        "confirmed": False,
        "edited_by_user": False,
        "source": {"file_id": "F-1", "page": 1, "bbox": None, "span": value, "form_label": None}
        if status == "extracted"
        else None,
        "normalized_from": value,
        "label": None,
        "doc_type": None,
        "notes": [],
    }


def _state(*, omit: tuple[str, ...] = (), statuses: dict | None = None) -> dict:
    statuses = statuses or {}
    return {
        "docs": [{"file_id": "F-1", "full_text": DOCUMENT}],
        "fields": {
            key: _field(key, value, status=statuses.get(key, "extracted"))
            for key, value in CLEAN_VALUES.items()
            if key not in omit
        },
        "extra_fields": {},
        "findings": [],
        "trail": [{"id": "agent1.parse#001", "op": "read"}],
    }


def _audited(
    state: dict | None = None,
    *,
    snapshot_digest: str = "digest-clean",
    current_digest: str | None = None,
) -> dict:
    return audit_state(
        state or _state(),
        snapshot_digest=snapshot_digest,
        current_digest=current_digest,
    )


def test_the_report_carries_its_baseline():
    """3.3 The report names the snapshot, the schema, the bundles and the engine."""
    result = _audited()
    verification = to_verification(result["report"], issues=[], findings=[])
    audit = verification["audit"]

    assert audit["snapshot_digest"] == "digest-clean"
    assert audit["schema_version"] == load_schema().version
    assert audit["bundle_versions"] == {"guarantee-core": "1.0.0"}
    assert audit["engine_version"] == "1.0.0"
    assert audit["planned"] == 51
    assert audit["findings"] == []
    assert verification["score"] is None


def test_a_different_digest_marks_the_report_stale_instead_of_rebinding():
    """3.3 A report about another snapshot stays about that snapshot."""
    result = _audited(current_digest="digest-after-edit")

    assert result["report"]["freshness"] == "stale"
    assert result["report"]["freshness_reasons"] == ["snapshot_changed"]
    assert result["report"]["snapshot_digest"] == "digest-clean"


def test_every_planned_unit_becomes_exactly_one_issue():
    """4.1 The Issue list is the plan, not whatever happened to produce output."""
    result = _audited()
    units = {unit.check_id: unit for unit in result["units"]}
    issues = [project_issue(item, units[item.check_id]) for item in result["results"]]

    assert len(issues) == result["report"]["planned"] == 51
    assert len({issue["checker"] for issue in issues}) == 51
    passing = next(issue for issue in issues if issue["detail"] == "pass")
    assert passing["level"] == "info"
    assert passing["finding_ids"] == []
    assert passing["method"] == "deterministic"
    assert "gate_type" not in passing, "a settled row gates nothing"


def test_a_rule_failure_becomes_a_finding_with_gate_type_and_rule_reference():
    """4.1 A deterministic finding cites its rule and declares how it gates."""
    state = _state()
    state["fields"]["expiry_date"] = _field("expiry_date", "2025-03-12")  # before the issue date
    result = _audited(state)
    units = {unit.check_id: unit for unit in result["units"]}
    failure = next(
        item
        for item in result["results"]
        if item.check_id.startswith("RULE:GR-EXPIRY-AFTER-ISSUE")
    )

    audit_finding = finding_of(failure, units[failure.check_id])
    draft = finding_draft(failure, units[failure.check_id])

    assert audit_finding["gate_type"] == "hard_block"
    assert "start_approval" in audit_finding["target_operations"]
    assert audit_finding["method"] == "deterministic"
    assert audit_finding["rule_id"] == "GR-EXPIRY-AFTER-ISSUE"
    assert audit_finding["field_id"] == "expiry_date"

    assert draft["blocking"] is True
    assert draft["rule_id"] == "GR-EXPIRY-AFTER-ISSUE", "the bare rule name, as other agents write it"
    assert draft["resolved"] is False and draft["resolution"] is None
    assert draft["field_keys"] == ["expiry_date"]


def test_severity_never_implies_blocking():
    """4.1 `critical` with an advisory gate type must not become blocking."""
    unit = Unit(check_id="RULE:ADVISORY", family="rule", rule_ref={"rule_id": "A", "version": 1})
    result = CheckResult(
        unit.check_id,
        FINDING,
        finding={
            "rule_ref": {"rule_id": "A", "version": 1},
            "title": "advisory",
            "severity": "critical",
            "gate_type": "advisory",
            "target_operations": [],
            "category": "field",
            "field_id": "guarantee_amount",
            "evidence": "500000.00",
        },
    )

    assert finding_draft(result, unit)["blocking"] is False


def test_a_semantic_hard_block_is_a_contract_violation_and_never_blocks():
    """4.2 A model opinion cannot hard-block: the unit fails loudly and the finding is dropped."""
    unit = Unit(check_id="SEM:1", family="rule", method="semantic")
    result = CheckResult(
        unit.check_id,
        FINDING,
        finding={
            "rule_ref": {"rule_id": "SEM", "version": 1},
            "title": "the model is unhappy",
            "severity": "critical",
            "gate_type": "hard_block",
            "target_operations": [START_APPROVAL],
            "field_id": "guarantee_amount",
        },
    )

    guarded = enforce_method_contract(result, unit)
    decision = evaluate_gate(
        {"freshness": "current", "snapshot_digest": "d", "counts": {}, "coverage": {}},
        operation=START_APPROVAL,
        candidate_digest="d",
        findings=[item for item in (finding_of(guarded, unit),) if item],
    )

    assert guarded.status == FAILED
    assert guarded.reason_code == SEMANTIC_HARD_BLOCK
    assert finding_of(guarded, unit) is None
    assert decision["authorized_finding_ids"] == []
    assert "hard_block" not in decision["reason_codes"]


def test_a_dangling_anchor_fails_the_unit_and_keeps_no_finding():
    """4.3 An anchor that does not resolve is never guessed."""
    unit = Unit(check_id="RULE:X", family="rule")
    result = CheckResult(
        unit.check_id,
        FINDING,
        finding={
            "rule_ref": {"rule_id": "X", "version": 1},
            "title": "typo",
            "severity": "warn",
            "gate_type": "advisory",
            "field_id": "guarantee_ammount",
        },
    )
    known = known_fields(load_schema(), _state())

    guarded = enforce_anchor(result, known)

    assert guarded.status == FAILED
    assert guarded.reason_code == DANGLING_ANCHOR
    assert guarded.detail == {"field_id": "guarantee_ammount"}
    assert finding_of(guarded, unit) is None


def test_a_resolvable_anchor_points_at_its_field():
    """4.3 A resolvable anchor becomes the row's location, so the reviewer lands on the value."""
    result = _audited(_state(omit=("guarantee_amount",)))
    units = {unit.check_id: unit for unit in result["units"]}
    failure = next(
        item for item in result["results"] if item.check_id == "SCHEMA:guarantee_amount:required"
    )

    issue = project_issue(
        failure, units[failure.check_id], finding_id="B-001"
    )

    assert issue["location"] == "guarantee_amount"
    assert issue["finding_ids"] == ["B-001"]
    assert issue["level"] == "fail"
    assert issue["gate_type"] == "hard_block"
    assert "start_approval" in issue["target_operations"]
    assert issue["check_id"] == "SCHEMA:guarantee_amount:required"


def test_verdict_answers_whether_the_audit_can_stand_behind_the_report():
    assert verdict_for({"outcome": OUTCOME_NONE}) == "pass"
    assert verdict_for({"outcome": OUTCOME_FINDINGS}) == "warn"
    assert verdict_for({"outcome": OUTCOME_NEEDS_INPUT}) == "warn"
    assert verdict_for({"outcome": OUTCOME_UNABLE}) == "fail"


def test_a_failed_issue_makes_the_verdict_fail_even_when_the_outcome_is_only_findings():
    assert verdict_for({"outcome": OUTCOME_FINDINGS}, [{"level": "fail"}]) == "fail"
    assert verdict_for({"outcome": OUTCOME_NONE}, [{"level": "fail"}]) == "fail"


def test_warn_and_info_issues_are_warn_and_pass():
    assert verdict_for({"outcome": OUTCOME_NONE}, [{"level": "warn"}]) == "warn"
    assert verdict_for({"outcome": OUTCOME_NONE}, [{"level": "info"}]) == "pass"


def test_unable_to_assess_is_fail_even_with_only_warnings():
    assert verdict_for({"outcome": OUTCOME_UNABLE}, [{"level": "warn"}]) == "fail"


def test_a_real_critical_failure_does_not_report_warn():
    """The bug this closes: seven critical issues were projected while `verdict` stayed `warn`."""
    result = _audited(_state(omit=("guarantee_amount",)))
    units = {unit.check_id: unit for unit in result["units"]}
    issues = [project_issue(row, units[row.check_id]) for row in result["results"]]

    verification = to_verification(result["report"], issues=issues, findings=[])

    assert any(issue["level"] == "fail" for issue in issues)
    assert verification["verdict"] == "fail"


def test_credibility_is_recomputable_from_the_plan():
    """No subjective score: the number is `assessed / planned` and says how it was computed."""
    report = _audited()["report"]
    entry = credibility(report)

    assert entry["assessed"] == report["coverage"]["assessed"] == 33
    assert entry["planned"] == 51
    assert entry["ratio"] == 0.647
    assert "not_applicable never counts" in entry["formula"]


def test_unsettled_units_are_reported_as_needs_input_not_as_pass():
    """The projection must not launder a gap into a green row."""
    result = _audited(_state(statuses={key: "inferred" for key in CLEAN_VALUES}))
    units = {unit.check_id: unit for unit in result["units"]}
    gap = next(item for item in result["results"] if item.status == NEEDS_INPUT)

    issue = project_issue(gap, units[gap.check_id])

    assert issue["level"] == "warn"
    assert "needs_input" in issue["detail"]