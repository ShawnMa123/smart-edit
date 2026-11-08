"""The operation gate (AI-audit §7.2-7.3, design D8).

The gate answers one protected operation about one candidate snapshot. It never trusts a client's rule
ids, statuses or report id, and uncertainty is never `allowed`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from app.audit.policy import (
    ALLOWED,
    BLOCKED,
    INDETERMINATE,
    LIMITED_COVERAGE_RATIO,
    MIN_ASSESSED_RATIO,
    POLICY_REVISION,
    GateError,
    policy_for,
)
from app.rules.types import FAILED, NEEDS_INPUT, UNABLE_TO_ASSESS

_RESOLVED_DISPOSITIONS = frozenset({"accepted", "rejected", "needs_human_review"})


def _finding_label(finding: dict) -> str:
    if finding.get("id"):
        return str(finding["id"])
    rule_ref = finding.get("rule_ref") or {}
    return f"{rule_ref.get('rule_id', 'rule')}@{rule_ref.get('version', '?')}"


def _latest_dispositions(events: Iterable[dict]) -> dict[str, str]:
    latest: dict[str, str] = {}
    for event in events:
        finding_id = event.get("finding_id")
        if finding_id:
            latest[str(finding_id)] = str(event.get("disposition"))
    return latest


def evaluate_gate(
    report: dict,
    *,
    operation: str,
    candidate_digest: str,
    findings: Sequence[dict] = (),
    dispositions: Sequence[dict] = (),
    now: datetime | None = None,
    template_digest: str | None = None,
) -> dict:
    """Decide one operation from an audit report, its findings and the disposition history."""
    policy = policy_for(operation)
    evaluated_at = (now or datetime.now(timezone.utc)).isoformat()
    decision = {
        "decision": INDETERMINATE,
        "operation": operation,
        "candidate_content_sha256": candidate_digest,
        "policy_revision": POLICY_REVISION,
        "evaluated_at": evaluated_at,
        "reason_codes": [],
        "authorized_finding_ids": [],
        # Transparency: an `allowed` answer must say what it is allowing.
        "coverage": {},
        "open_gaps": 0,
        "advisory_finding_ids": [],
        "unsupported_capability": None,
    }
    reasons: list[str] = []

    def settle(verdict: str) -> dict:
        decision["decision"] = verdict
        decision["reason_codes"] = reasons
        return decision

    if not report:
        reasons.append("no_audit_report")
        return settle(INDETERMINATE)

    # The report must be about the candidate that will actually be submitted.
    if report.get("freshness") == "stale" or report.get("snapshot_digest") != candidate_digest:
        reasons.append("stale_report")
        return settle(INDETERMINATE)

    # A template edit invalidates a report just as a document edit does (design D20). The digest is the
    # template's own hash, so a changed controlled clause cannot be silently ignored.
    if template_digest is not None:
        recorded = (report.get("template") or {}).get("content_sha256")
        if recorded != template_digest:
            reasons.append("stale_report")
            reasons.append("template_changed")
            return settle(INDETERMINATE)

    if policy.unsupported_reason:
        reasons.append(policy.unsupported_reason)
        decision["unsupported_capability"] = policy.unsupported_reason
        return settle(INDETERMINATE)

    hard_blocks = [
        finding
        for finding in findings
        if finding.get("gate_type") == "hard_block"
        and (finding.get("method") or "deterministic") == "deterministic"
        and operation in (finding.get("target_operations") or ())
    ]
    decision["authorized_finding_ids"] = [_finding_label(finding) for finding in hard_blocks]

    if not policy.content_gate:
        reasons.append("draft_not_gated")
        return settle(ALLOWED)

    counts = report.get("counts") or {}
    # An `allowed` answer must state what it is allowing: how much was assessed, how many gaps stay open,
    # and which advisories the reviewer is accepting.
    decision["coverage"] = dict(report.get("coverage") or {})
    decision["open_gaps"] = int(counts.get(NEEDS_INPUT) or 0)
    decision["advisory_finding_ids"] = [
        _finding_label(finding)
        for finding in findings
        if (finding.get("gate_type") or "advisory") == "advisory"
    ]

    if "rule_conflict" in (report.get("reasons") or []):
        # Two published versions of the same rule disagree; nothing may be allowed on this snapshot.
        reasons.append("rule_conflict")
        return settle(BLOCKED)

    if hard_blocks:
        reasons.append("hard_block")
        return settle(BLOCKED)

    if counts.get(FAILED):
        reasons.append("check_failed")
        return settle(BLOCKED)

    if counts.get(NEEDS_INPUT):
        reasons.append("needs_input")
        if policy.block_on_needs_input:
            return settle(BLOCKED)
        reasons.append("gaps_listed")

    if policy.block_on_unresolved_critical:
        latest = _latest_dispositions(dispositions)
        unresolved = [
            finding
            for finding in findings
            if finding.get("severity") == "critical"
            and latest.get(_finding_label(finding)) not in _RESOLVED_DISPOSITIONS
        ]
        if unresolved:
            reasons.append("unresolved_critical")
            decision["authorized_finding_ids"] = [_finding_label(f) for f in unresolved]
            return settle(BLOCKED)

    if counts.get(UNABLE_TO_ASSESS):
        reasons.append("unable_to_assess")
        return settle(INDETERMINATE)

    if policy.enforce_coverage:
        assessed = decision["coverage"].get("assessed")
        ratio = decision["coverage"].get("ratio")
        if assessed is not None:
            if assessed == 0:
                # Nothing was actually assessed: "not applicable" is not an assessment.
                reasons.append("no_assessed_checks")
                return settle(INDETERMINATE)
            if ratio is not None and ratio < MIN_ASSESSED_RATIO:
                reasons.append("limited_coverage")
                return settle(INDETERMINATE)
            if ratio is not None and ratio < LIMITED_COVERAGE_RATIO:
                # Allowed, but the client must print "assessed X of Y planned".
                reasons.append("limited_coverage")

    return settle(ALLOWED)


def evaluate(
    state: dict,
    operation: str,
    candidate_digest: str,
    *,
    dispositions: Sequence[dict] = (),
    now: datetime | None = None,
    template_digest: str | None = None,
) -> dict:
    """Gate convenience used by the node layer.

    The report is read from `state["verification"]["audit"]` — the slot task 3.3 fills. Pass
    `template_digest` (the currently resolved template hash) to detect a template edit; without it the
    gate can only judge document staleness.
    """
    if operation not in _known_operations():
        raise GateError(f"unknown operation {operation!r}")
    verification = state.get("verification") or {}
    report = verification.get("audit") if isinstance(verification, dict) else None
    # The audit's own findings carry the gate type; the contract `Finding` deliberately does not, so
    # falling back to `state["findings"]` would degrade every hard block to advisory.
    findings = (report or {}).get("findings") or state.get("findings") or ()
    return evaluate_gate(
        report or {},
        operation=operation,
        candidate_digest=candidate_digest,
        findings=findings,
        dispositions=dispositions,
        now=now,
        template_digest=template_digest,
    )


def _known_operations() -> tuple[str, ...]:
    from app.audit.policy import OPERATIONS

    return OPERATIONS


def store_decision(state: dict, decision: dict) -> dict:
    """Return the state update that records a decision on the run (`EditState.gate` already exists)."""
    return {"gate": decision}