"""Evidence family (design D1): the values the audit reasons about must be traceable.

These checks used to be the whole group. They stay because an audit that judges a number nobody can
locate in the source is worthless — but they now guard the audit's *own* inputs rather than being its
identity.
"""

from __future__ import annotations

from app.parsing.normalize import normalized_full_texts, span_locatable
from app.rules.types import (
    FAILED,
    FINDING,
    NOT_APPLICABLE,
    PASS,
    CheckResult,
    RuleEvaluationError,
    Unit,
)
from app.state import OVERREACH_OPS

NOT_RUN_REASON = "requires_agent_regulatory_output"


def _finding(unit: Unit, title: str, severity: str, gate_type: str, detail: dict) -> dict:
    return {
        "rule_ref": {"rule_id": unit.check_id, "version": 1},
        "title": title,
        "severity": severity,
        "gate_type": gate_type,
        "target_operations": ["start_approval", "formal_export", "handoff"] if gate_type == "hard_block" else [],
        "category": "evidence",
        "field_id": detail.get("field_id"),
        "evidence": detail.get("evidence"),
        "detail": detail,
    }


def _check_trail_overreach(unit: Unit, state: dict) -> CheckResult:
    entries = [entry for entry in state.get("trail") or [] if entry.get("op") in OVERREACH_OPS]
    if not entries:
        return CheckResult(unit.check_id, PASS)
    detail = {"entry_ids": [entry.get("id") for entry in entries], "evidence": entries[0].get("op")}
    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(unit, "Source text was summarised, rewritten or dropped", "critical", "hard_block", detail),
    )


def _check_provenance(unit: Unit, state: dict) -> CheckResult:
    fields = state.get("fields") or {}
    extracted = {key: value for key, value in fields.items() if value.get("status") == "extracted"}
    if not extracted:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="no_extracted_values")

    # Normalise each document once, not once per field (design D12).
    normalized = normalized_full_texts(state.get("docs") or [])
    broken = []
    for key, value in extracted.items():
        source = value.get("source")
        if not source or not span_locatable(source, [], normalized=normalized):
            broken.append(key)
    if not broken:
        return CheckResult(unit.check_id, PASS)

    detail = {"field_ids": broken, "evidence": ", ".join(broken)}
    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(unit, "An extracted value cannot be located in its own file", "critical", "hard_block", detail),
    )


def _check_finding_anchor(unit: Unit, state: dict) -> CheckResult:
    findings = state.get("findings") or []
    if not findings:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code="no_findings")

    known = set((state.get("fields") or {})) | set((state.get("extra_fields") or {}))
    dangling = [
        finding.get("id")
        for finding in findings
        if any(key not in known for key in (finding.get("field_keys") or []))
    ]
    if not dangling:
        return CheckResult(unit.check_id, PASS)

    detail = {"finding_ids": dangling, "evidence": ", ".join(str(item) for item in dangling)}
    return CheckResult(
        unit.check_id,
        FINDING,
        finding=_finding(unit, "A finding points at a field that does not exist", "warn", "advisory", detail),
    )


_CHECKS = {
    "trail_overreach": _check_trail_overreach,
    "provenance": _check_provenance,
    "finding_anchor": _check_finding_anchor,
}


def evaluate_evidence_unit(unit: Unit, state: dict) -> CheckResult:
    """Evaluate one evidence unit. Checks this build cannot run are `not_applicable` with a reason."""
    name = unit.check_id.split(":", 1)[-1]
    check = _CHECKS.get(name)
    if check is None:
        return CheckResult(unit.check_id, NOT_APPLICABLE, reason_code=NOT_RUN_REASON)
    try:
        return check(unit, state)
    except RuleEvaluationError as exc:
        return CheckResult(unit.check_id, FAILED, reason_code=str(exc))
    except Exception as exc:  # a crashing checker must not take the audit down
        return CheckResult(unit.check_id, FAILED, reason_code=f"checker_crashed: {type(exc).__name__}")


def evaluate_all(units: list[Unit], state: dict) -> list[CheckResult]:
    """Evaluate every evidence unit, isolating failures (task 8.3)."""
    return [evaluate_evidence_unit(unit, state) for unit in units]