"""Project planned units into the frozen contract rows (tasks 3.3, 4.1-4.3).

Two outputs, deliberately different:

1. **`Issue` rows** — one per planned unit, so a client can say "33 of 51 assessed" and open the row
   that settled it. The four audit fields (`check_id` / `gate_type` / `target_operations` / `method`)
   are the optional additions signed off in task 0.2.
2. **`Finding` drafts** — one per unit that produced a finding, numbered by `app/findings.py` so the
   audit never invents ids. The audit's own copy of each finding (with gate type, target operations and
   method) lives in `verification.audit["findings"]`, which is what the gate reads; the contract
   `Finding` keeps exactly its declared shape.

Severity never implies blocking: `gate_type` comes from the rule, `blocking` mirrors only
`gate_type == "hard_block"`.
"""

from __future__ import annotations

from app.audit.report import OUTCOME_FINDINGS, OUTCOME_NEEDS_INPUT, OUTCOME_NONE
from app.rules.types import (
    FAILED,
    FINDING,
    NEEDS_INPUT,
    NOT_APPLICABLE,
    PASS,
    UNABLE_TO_ASSESS,
    CheckResult,
    Unit,
)

DANGLING_ANCHOR = "dangling_anchor"
SEMANTIC_HARD_BLOCK = "semantic_hard_block"
HARD_BLOCK_GATE = "hard_block"

_LEVEL_BY_SEVERITY = {"critical": "fail", "warn": "warn", "info": "info"}
_LEVEL_BY_STATUS = {
    PASS: "info",
    NOT_APPLICABLE: "info",
    NEEDS_INPUT: "warn",
    UNABLE_TO_ASSESS: "warn",
    FAILED: "fail",
}


def known_fields(schema, state: dict) -> set[str]:
    """Every key a finding may point at: the schema's fields plus whatever normalization produced."""
    return (
        set(schema.fields)
        | set(state.get("fields") or {})
        | set(state.get("extra_fields") or {})
    )


def enforce_anchor(result: CheckResult, known: set[str]) -> CheckResult:
    """A finding must point at a field that exists; an unresolvable anchor is never guessed (4.3)."""
    finding = result.finding
    if not finding:
        return result
    field_id = finding.get("field_id")
    if field_id is None or field_id in known:
        return result
    return CheckResult(
        result.check_id, FAILED, reason_code=DANGLING_ANCHOR, detail={"field_id": field_id}
    )


def enforce_method_contract(result: CheckResult, unit: Unit) -> CheckResult:
    """Model output can never hard-block (4.2): a semantic `hard_block` is a contract violation."""
    finding = result.finding
    if not finding or unit.method != "semantic":
        return result
    if (finding.get("gate_type") or "") != HARD_BLOCK_GATE:
        return result
    return CheckResult(
        result.check_id,
        FAILED,
        reason_code=SEMANTIC_HARD_BLOCK,
        detail={"field_id": finding.get("field_id"), "gate_type": HARD_BLOCK_GATE},
    )


def finding_of(result: CheckResult, unit: Unit) -> dict | None:
    """The audit's copy of a finding: contract vocabulary plus the four audit fields."""
    finding = result.finding
    if result.status != FINDING or not finding:
        return None
    rule_ref = finding.get("rule_ref") or {}
    return {
        "check_id": result.check_id,
        "rule_id": rule_ref.get("rule_id"),
        "rule_version": rule_ref.get("version"),
        "category": finding.get("category") or "field",
        "severity": finding.get("severity") or "warn",
        "gate_type": finding.get("gate_type"),
        "target_operations": list(finding.get("target_operations") or ()),
        "method": unit.method,
        "field_id": finding.get("field_id"),
        "evidence": finding.get("evidence"),
        "message": finding.get("title") or result.check_id,
    }


def finding_draft(result: CheckResult, unit: Unit) -> dict | None:
    """A `Finding` draft for `materialize_findings()` — business fields only, no id.

    `rule_id` is the bare rule name, like every other producer's (`F-guarantee_number-max_length`);
    the version lives in the audit's own copy (`verification.audit["findings"][].rule_version`) and in
    the `Issue.check_id` (`RULE:<rule>@<version>`).
    """
    finding = finding_of(result, unit)
    if finding is None:
        return None
    return {
        "source": "business",
        "kind": _kind(result),
        "rule_id": finding["rule_id"],
        "severity": finding["severity"],
        "blocking": finding["gate_type"] == HARD_BLOCK_GATE,
        "resolved": False,
        "resolution": None,
        "field_keys": [finding["field_id"]] if finding["field_id"] else [],
        "message": finding["message"],
        "evidence": finding["evidence"],
        "citation": None,
        "suggestion": None,
    }


def _kind(result: CheckResult) -> str:
    reason = (result.detail or {}).get("reason")
    if reason in ("required_missing", "absent"):
        return "missing"
    if reason in ("invalid_value", "charset", "too_long"):
        return "invalid_value"
    if reason == "violated":
        return "policy_violation"
    return "inconsistent"


def project_issue(result: CheckResult, unit: Unit, *, finding_id: str | None = None) -> dict:
    """One `Issue` row for one planned unit."""
    finding = result.finding or {}
    level = _LEVEL_BY_SEVERITY.get(
        finding.get("severity"), _LEVEL_BY_STATUS.get(result.status, "info")
    )
    issue = {
        "checker": result.check_id,
        "level": level,
        "finding_ids": [finding_id] if finding_id else [],
        "detail": finding.get("title") or _detail(result),
        "location": finding.get("field_id") or unit.field_id,
        "check_id": result.check_id,
        "method": unit.method,
    }
    if finding.get("gate_type"):
        issue["gate_type"] = finding["gate_type"]
        issue["target_operations"] = list(finding.get("target_operations") or ())
    return issue


def _detail(result: CheckResult) -> str:
    return f"{result.status}" + (f" ({result.reason_code})" if result.reason_code else "")


def verdict_for(report: dict) -> str:
    """`verdict` answers "can the audit stand behind this report", not "is the document good"."""
    outcome = report.get("outcome")
    if outcome == OUTCOME_NONE:
        return "pass"
    if outcome in (OUTCOME_FINDINGS, OUTCOME_NEEDS_INPUT):
        return "warn"
    return "fail"  # unable_to_assess: nothing may be read off this report


def credibility(report: dict) -> dict:
    """Fully recomputable, never a subjective score: how much of the plan was actually assessed."""
    coverage = report.get("coverage") or {}
    return {
        "assessed": coverage.get("assessed"),
        "planned": report.get("planned"),
        "ratio": coverage.get("ratio"),
        "formula": "assessed / planned, assessed = pass + finding (not_applicable never counts)",
    }


def to_verification(report: dict, *, issues: list[dict], findings: list[dict]) -> dict:
    """The `VerificationReport` written on the run (`VerificationReport.audit` is the 0.2 addition)."""
    return {
        "checks": issues,
        "verdict": verdict_for(report),
        "credibility": credibility(report),
        "score": None,
        "audit": {**report, "findings": findings},
    }