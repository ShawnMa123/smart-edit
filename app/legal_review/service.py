"""Legal review service — L1 deterministic slice.

One synthetic rule runs synchronously over supplied facts and produces a CheckResult +
Finding. This is the minimal vertical loop, not the async worker (that is L2).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from app.legal_review.contracts import CheckResult, Finding, ReviewCreate, ReviewReport, ReviewRun
from app.legal_review.rules import Rule, evaluate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ── synthetic rule bundle (spec §14.2: one synthetic rule first) ───────────────
_DEMO_AMOUNT_REQUIRED = Rule(
    rule_id="DEMO-AMOUNT-REQUIRED",
    version="1",
    title="Missing amount",
    domain="template",
    severity="Critical",
    gate_type="hard_block",
    target_operations=("start_approval",),
    applicability={},
    required_facts=(),
    expression={"op": "exists", "field_id": "amount"},
    explanation="The synthetic template requires an amount before approval.",
)

_RULES = (_DEMO_AMOUNT_REQUIRED,)


def _evaluate_rule(rule: Rule, facts: dict) -> CheckResult:
    missing = [f for f in rule.required_facts if (facts.get(f) or {}).get("state") == "missing"]
    if missing:
        return CheckResult(
            check_id=f"check_{rule.rule_id.lower()}",
            method="deterministic",
            scope_key=rule.domain,
            status="needs_input",
            rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
            reason_codes=["missing_required_facts"],
            missing_facts=missing,
        )

    verdict = evaluate(rule.expression, facts)
    if verdict is False:
        finding = _make_finding(rule)
        return CheckResult(
            check_id=f"check_{rule.rule_id.lower()}",
            method="deterministic",
            scope_key=rule.domain,
            status="finding",
            rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
            reason_codes=["rule_violated"],
            finding_ids=[finding.finding_id],
        )
    if verdict is True:
        return CheckResult(
            check_id=f"check_{rule.rule_id.lower()}",
            method="deterministic",
            scope_key=rule.domain,
            status="pass",
            rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
        )
    return CheckResult(
        check_id=f"check_{rule.rule_id.lower()}",
        method="deterministic",
        scope_key=rule.domain,
        status="unable_to_assess",
        rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
        reason_codes=["unconfirmed_fact"],
    )


def _make_finding(rule: Rule) -> Finding:
    return Finding(
        finding_id=f"lf_{uuid.uuid4().hex[:12]}",
        check_id=f"check_{rule.rule_id.lower()}",
        method="deterministic",
        category="field",
        severity=rule.severity,
        gate_type=rule.gate_type,
        target_operations=list(rule.target_operations),
        title=rule.title,
        explanation=rule.explanation,
        rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
        applicability={"jurisdictions": [], "assessment_date": _iso(_utcnow())[:10], "conditions": [], "limitations": ["Missing field has no text anchor"]},
    )


def run_deterministic(facts: dict) -> tuple[list[CheckResult], list[Finding]]:
    """Run every deterministic rule once; a missing required fact is needs_input, never pass."""
    checks: list[CheckResult] = []
    findings: list[Finding] = []
    for rule in _RULES:
        check = _evaluate_rule(rule, facts)
        checks.append(check)
        if check.status == "finding":
            findings.append(_make_finding(rule))
    return checks, findings


_LEGAL_CHECK_ID = "check_legal"
# The advice is presented, not enforced: legal findings are advisory-only (`spec` §4.2).
_LEGAL_EVIDENCE_ONLY = (
    "The statute service did not return a directly usable answer; the excerpts below are the "
    "statute evidence it returned."
)


def _coverage_notes(coverage: Any) -> list[str]:
    """Pull human-readable coverage notes out of the service's `coverage` block."""
    notes: list[str] = []
    if isinstance(coverage, dict):
        for note in coverage.get("notes") or []:
            notes.append(str(note))
    return notes


def _support_level(answer_status: str | None) -> str:
    status = (answer_status or "").strip().lower()
    if status == "answered":
        return "strong"
    if status == "partial":
        return "qualified"
    if status in ("unavailable", "unsupported", "error"):
        return "insufficient"
    return "not_applicable"


def _legal_finding(
    outcome: Any, check_id: str, candidates: list[Any], reason: str, coverage: Any
) -> Finding:
    """Map one `StatuteOutcome` (with references) onto a legal `Finding`.

    `draft` becomes the explanation, `candidates` become `evidence_ids` + `anchors` (keeping
    chunk_id/doc_id/条文号), and `answer_status` becomes `support_level`.
    """
    anchors: list[dict] = []
    evidence_ids: list[str] = []
    jurisdictions: set[str] = set()
    for candidate in candidates:
        citation_id = str(getattr(candidate, "citation_id", "") or "")
        if citation_id and citation_id not in evidence_ids:
            evidence_ids.append(citation_id)
        locator = getattr(candidate, "locator", None) or {}
        jurisdiction = str(locator.get("jurisdiction") or "")
        if jurisdiction:
            jurisdictions.add(jurisdiction)
        anchors.append(
            {
                "chunk_id": getattr(candidate, "chunk_id", None),
                "doc_id": locator.get("doc_id"),
                "article_label": locator.get("article_label"),
                "jurisdiction": locator.get("jurisdiction"),
                "effective_from": getattr(candidate, "effective_from", None),
                "title": getattr(candidate, "title", None),
                "source_version": getattr(candidate, "source_version", None),
                "excerpt": getattr(candidate, "excerpt", None),
            }
        )
    draft = getattr(outcome, "draft", None)
    explanation = str(draft) if draft else _LEGAL_EVIDENCE_ONLY
    return Finding(
        finding_id=f"lf_{uuid.uuid4().hex[:12]}",
        check_id=check_id,
        method="legal",
        category="legal",
        severity="Info",
        gate_type="advisory",
        target_operations=[],
        title="Legal advice",
        explanation=explanation,
        anchors=anchors,
        rule_refs=[],
        evidence_ids=evidence_ids,
        applicability={
            "jurisdictions": sorted(jurisdictions),
            "assessment_date": _iso(_utcnow())[:10],
            "conditions": [],
            "limitations": _coverage_notes(coverage) or [f"reason: {reason}"],
        },
        support_level=_support_level(getattr(outcome, "answer_status", None)),
        disposition="open",
        version=1,
    )


def _legal_check_result(
    check_id: str, status: str, reason: str, coverage: Any, finding_ids: list[str] | None = None
) -> CheckResult:
    # `reason_codes` keeps each failure mode distinguishable (timeout / uncovered / no-hit / ...).
    codes = [reason] + [f"coverage:{note}" for note in _coverage_notes(coverage)]
    return CheckResult(
        check_id=check_id,
        method="legal",
        scope_key="legal",
        status=status,  # type: ignore[arg-type]
        reason_codes=codes,
        finding_ids=finding_ids or [],
    )


def run_legal(
    statute: Any,
    principal: Any,
    workspace_id: str,
    question: str | None,
    *,
    applicable_on: str | None = None,
    jurisdiction_codes: list[str] | None = None,
) -> tuple[list[CheckResult], list[Finding]]:
    """Ask the statute service (`/v1/chat`) and map its outcome onto CheckResult + Finding.

    The service's own `answer_status` is the scope/relevance signal: `answered`/`partial` means it
    engaged (so we surface a Finding with its draft + citations); `unavailable`/`unsupported`/`error`
    means it could not answer (off-topic or no usable hit), which is `unable_to_assess` — the
    retrieved references are irrelevant and are never surfaced as citations.
    """
    check_id = _LEGAL_CHECK_ID
    question_text = (question or "").strip()
    if not question_text:
        return [
            _legal_check_result(
                check_id, "needs_input", "missing_question", {}, []
            )
        ], []
    if statute is None or not hasattr(statute, "chat_detailed"):
        return [
            _legal_check_result(
                check_id, "failed", "statute_unavailable", {}, []
            )
        ], []

    plan = SimpleNamespace(
        question=question_text,
        jurisdictions=list(jurisdiction_codes or []),
        applicable_on=applicable_on,
        retrieval_terms=(),
    )
    try:
        outcome = statute.chat_detailed(principal, workspace_id, plan, applicable_on)
    except Exception as exc:  # noqa: BLE001 - a retrieval crash is a failure, never "no findings"
        return [
            _legal_check_result(
                check_id, "failed", f"retrieval_error:{type(exc).__name__}", {}, []
            )
        ], []

    reason = str(getattr(outcome, "reason", "") or "unsupported")
    status = str(getattr(outcome, "status", "failed") or "failed")
    candidates = list(getattr(outcome, "candidates", None) or [])
    coverage = getattr(outcome, "coverage", None) or {}
    answer_status = str(getattr(outcome, "answer_status", None) or "").strip().lower()

    if status == "failed":
        return [_legal_check_result(check_id, "failed", reason or "failed", coverage)], []
    if not candidates:
        check_status = "needs_input" if reason == "empty" else "unable_to_assess"
        return [_legal_check_result(check_id, check_status, reason or "no_hit", coverage)], []
    if answer_status not in ("answered", "partial"):
        # The service returned references but could not answer (off-topic or no usable hit). Those
        # references are irrelevant and must not be surfaced as citations — "could not answer" must
        # never read as an answer.
        return [
            _legal_check_result(
                check_id, "unable_to_assess", answer_status or reason or "unsupported", coverage
            )
        ], []

    finding = _legal_finding(outcome, check_id, candidates, reason, coverage)
    return [
        _legal_check_result(check_id, "finding", reason, coverage, [finding.finding_id])
    ], [finding]


def create_review(
    request: ReviewCreate,
    facts: dict,
    *,
    statute: Any = None,
    principal: Any = None,
) -> tuple[ReviewRun, ReviewReport]:
    run_id = f"lr_{uuid.uuid4().hex[:12]}"
    report_id = f"lrep_{uuid.uuid4().hex[:12]}"
    now = _utcnow()
    deadline = now + timedelta(seconds=120)

    checks: list[CheckResult] = []
    findings: list[Finding] = []
    if "deterministic" in request.modes:
        d_checks, d_findings = run_deterministic(facts)
        checks.extend(d_checks)
        findings.extend(d_findings)
    if "legal" in request.modes:
        l_checks, l_findings = run_legal(
            statute,
            principal,
            request.workspace_id,
            request.question,
            applicable_on=request.applicable_on,
            jurisdiction_codes=request.jurisdiction_codes,
        )
        checks.extend(l_checks)
        findings.extend(l_findings)

    completion = "complete"
    if findings:
        outcome = "findings_present"
    elif any(c.status == "needs_input" for c in checks):
        outcome = "needs_input"
        completion = "partial"
    elif any(c.status in ("unable_to_assess", "failed") for c in checks):
        # "Could not check" is never reported as "no findings" (safety invariant).
        outcome = "unable_to_assess"
        completion = "partial"
    else:
        outcome = "no_findings"

    run = ReviewRun(
        run_id=run_id,
        status="succeeded",
        stage="done",
        created_at=_iso(now),
        deadline_at=_iso(deadline),
        report_id=report_id,
        finished_at=_iso(_utcnow()),
    )
    report = ReviewReport(
        report_id=report_id,
        run_id=run_id,
        completion=completion,
        outcome=outcome,
        findings=findings,
        coverage=checks,
    )
    return run, report
