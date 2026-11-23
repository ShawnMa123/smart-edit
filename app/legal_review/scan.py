"""Document risk scan: plan → deterministic checks → per-clause retrieval → compose → gate.

Design `legal-document-risk-scan`:

- D1 the plan is the denominator; a clause that was not planned can never read as "checked".
- D2 evidence comes from `/v1/retrieve` per clause, not from `/v1/chat` (which runs a server-side
  LLM and cannot be audited clause by clause).
- D3 the composer may only cite retrieved ids and may not raise severity or the gate.
- D5 the gate is derived from findings plus coverage, never from a model's opinion.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable

from app.legal_review.checks import (
    MARKERS,
    anchor_for,
    detect_document_type,
    evaluate_clause_markers,
    evaluate_consistency,
    evaluate_elements,
    make_finding,
    rule_id_for,
)
from app.legal_review.compliance import COMPOSER_RULES, detect as detect_compliance
from app.legal_review.compliance import evaluate_compliance
from app.legal_review.compose import ComposeError, LegalComposer
from app.legal_review.contracts import (
    CheckResult,
    EvidenceAnchor,
    Finding,
    ReviewCreate,
    ReviewReport,
    RuleRef,
)
from app.legal_review.document import Clause, ClausePlan, split_clauses

SETTLED = frozenset({"pass", "finding", "not_applicable"})
_CJK = re.compile(r"[\u4e00-\u9fff]")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ScanSettings:
    max_clauses: int = 12
    clause_chars: int = 1200
    deadline_seconds: int = 90
    coverage_ratio: float = 0.6
    web_default: bool = False
    max_web_calls: int = 2
    compose_timeout: float = 45.0
    max_evidence: int = 5

    @classmethod
    def from_env(cls) -> "ScanSettings":
        def _int(name: str, default: int) -> int:
            raw = (os.environ.get(name) or "").strip()
            try:
                return max(1, int(raw)) if raw else default
            except ValueError:
                return default

        def _float(name: str, default: float) -> float:
            raw = (os.environ.get(name) or "").strip()
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        def _flag(name: str, default: bool) -> bool:
            raw = (os.environ.get(name) or "").strip().lower()
            if not raw:
                return default
            return raw in {"1", "true", "yes", "on"}

        return cls(
            max_clauses=_int("SMART_EDIT_LEGAL_MAX_CLAUSES", 12),
            clause_chars=_int("SMART_EDIT_LEGAL_CLAUSE_CHARS", 1200),
            deadline_seconds=_int("SMART_EDIT_LEGAL_SCAN_DEADLINE", 90),
            coverage_ratio=_float("SMART_EDIT_LEGAL_COVERAGE_RATIO", 0.6),
            web_default=_flag("SMART_EDIT_LEGAL_WEB_DEFAULT", False),
            max_web_calls=_int("SMART_EDIT_LEGAL_MAX_WEB_CALLS", 2),
            compose_timeout=_float("SMART_EDIT_LEGAL_COMPOSE_TIMEOUT", 45.0),
            max_evidence=_int("SMART_EDIT_LEGAL_MAX_EVIDENCE", 5),
        )


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _language(text: str) -> str:
    return "zh-CN" if _CJK.search(text or "") else "en"


def _clause_query(clause: Clause, request: ReviewCreate) -> str:
    """One query per clause: its heading, a body preview and the business type."""
    body = _WHITESPACE.sub(" ", clause.text).strip()
    parts = [clause.heading or "", body[:220], request.business_type or ""]
    return " ".join(part for part in parts if part)[:400]


def _evidence_payload(candidates: list[Any], limit: int) -> list[dict]:
    payload: list[dict] = []
    for index, candidate in enumerate(candidates[:limit], start=1):
        locator = dict(getattr(candidate, "locator", None) or {})
        payload.append(
            {
                "id": f"E{index}",
                "citation_id": str(getattr(candidate, "citation_id", "") or ""),
                "chunk_id": locator.get("chunk_id") or getattr(candidate, "chunk_id", None),
                "doc_id": locator.get("doc_id"),
                "article_label": locator.get("article_label"),
                "jurisdiction": locator.get("jurisdiction"),
                "effective_from": getattr(candidate, "effective_from", None)
                or locator.get("effective_from"),
                "title": getattr(candidate, "title", None),
                "excerpt": str(getattr(candidate, "excerpt", "") or "")[:600],
            }
        )
    return payload


def _evidence_anchors(payload: list[dict], cited_ids: tuple[str, ...]) -> list[dict]:
    by_id = {item["id"]: item for item in payload}
    anchors: list[dict] = []
    for evidence_id in cited_ids:
        item = by_id.get(evidence_id)
        if item is None:
            continue
        anchors.append(
            EvidenceAnchor(
                chunk_id=item.get("chunk_id"),
                doc_id=item.get("doc_id"),
                article_label=item.get("article_label"),
                jurisdiction=item.get("jurisdiction"),
                effective_from=item.get("effective_from"),
                title=item.get("title"),
                source_version=item.get("article_label"),
                excerpt=item.get("excerpt"),
            ).model_dump()
        )
    return anchors


def _marker_rules(clause_text: str) -> list[dict]:
    """The closed rule catalogue the composer may reference for this clause.

    The compliance ids are offered on every clause: the lexical layer is deliberately conservative,
    and the model is the second pair of eyes for sanctions / export control beyond those terms.
    """
    keys = {spec.key for spec in MARKERS if re.search(spec.pattern, clause_text, re.IGNORECASE)}
    rules = [
        {
            "rule_id": rule_id_for(f"marker_{spec.key}"),
            "label": spec.label,
            "severity": "Warning",
            "gate_type": "human_review",
        }
        for spec in MARKERS
        if spec.key in keys
    ]
    rules.extend(dict(rule) for rule in COMPOSER_RULES)
    rules.append(
        {
            "rule_id": "LEGAL-RISK-NEW",
            "label": "Further legal risk",
            "severity": "Warning",
            "gate_type": "human_review",
        }
    )
    return rules


def _coverage_summary(checks: list[CheckResult], plan: ClausePlan, settings: ScanSettings) -> dict:
    by_status: dict[str, int] = {}
    for check in checks:
        by_status[check.status] = by_status.get(check.status, 0) + 1
    planned = len(checks)
    assessed = sum(by_status.get(status, 0) for status in SETTLED)
    return {
        "planned": planned,
        "settled": assessed,
        "assessed": assessed,
        "assessed_ratio": round(assessed / planned, 3) if planned else 0.0,
        "by_status": by_status,
        "clauses": len(plan.clauses),
        "truncated": plan.truncated,
        "coverage_ratio_policy": settings.coverage_ratio,
    }


def gate_for(
    findings: list[Finding],
    summary: dict,
    settings: ScanSettings,
    checks: list[CheckResult] | None = None,
) -> dict:
    """The gate is a function of findings and coverage only."""
    reasons: list[str] = []
    if any(finding.gate_type == "hard_block" for finding in findings):
        reasons.append("hard_block_finding")
    if summary.get("assessed_ratio", 0.0) < settings.coverage_ratio:
        reasons.append("limited_coverage")
    # A unit that could not be evaluated (failed / unable_to_assess / needs_input) must surface in
    # the gate: otherwise "we could not check" would look like "nothing to fix".
    if checks and any(
        check.status in ("failed", "unable_to_assess", "needs_input") for check in checks
    ):
        reasons.append("unchecked_units")
    if any(finding.gate_type == "human_review" for finding in findings):
        reasons.append("human_review_finding")
    if "hard_block_finding" in reasons:
        status = "blocked"
    elif reasons:
        status = "needs_human_review"
    elif findings:
        status = "advisory"
    else:
        status = "clear"
    return {
        "status": status,
        "reasons": reasons,
        "coverage_ratio": summary.get("assessed_ratio", 0.0),
        "policy": "legal-scan/1",
    }


def _scan_clause_evidence(
    statute: Any, principal: Any, request: ReviewCreate, clause: Clause
) -> tuple[list[Any], str, int, str]:
    """One `/v1/retrieve` per clause. Failures are reported as reasons, never as "no hit"."""
    query = _clause_query(clause, request)
    if statute is None or not hasattr(statute, "search_detailed"):
        return [], "statute_unavailable", 0, query
    plan = SimpleNamespace(
        question=query,
        jurisdictions=list(request.jurisdiction_codes or []),
        applicable_on=request.applicable_on,
        retrieval_terms=(),
    )
    try:
        outcome = statute.search_detailed(principal, request.workspace_id, plan, request.applicable_on)
    except Exception as exc:  # noqa: BLE001 - a retrieval crash is a failure, never "no findings"
        return [], f"retrieval_error:{type(exc).__name__}", 0, query
    return (
        list(getattr(outcome, "candidates", None) or []),
        str(getattr(outcome, "reason", "") or "no_hit"),
        int(getattr(outcome, "hits", 0) or 0),
        query,
    )


def _web_question(request: ReviewCreate, clauses: list[Clause], assessment=None) -> str:
    """A compliance-focused question when the draft already shows controlled goods + a destination."""
    if assessment is not None and assessment.goods and assessment.destinations:
        from app.legal_review.compliance import labels

        return (
            f"{labels(assessment.goods)} exported to {labels(assessment.destinations)}: which "
            "export-control and sanctions rules apply (EAR/ITAR, OFAC, EU/UN), and what is "
            "prohibited?"
        )[:400]
    heads = "; ".join((clause.heading or clause.preview) for clause in clauses[:5])
    prefix = request.business_type or "trade finance"
    return f"{prefix} — is this wording legally risky under current rules? {heads}"[:400]


def _composed_finding(
    plan: ClausePlan,
    clause: Clause,
    item: Any,
    evidence: list[dict],
) -> Finding:
    """Turn one validated composer item into a Finding with a draft anchor and citations."""
    anchor = None
    if item.quote_start is not None and item.quote_end is not None:
        anchor = anchor_for(
            plan, clause, clause.start_cp + item.quote_start, clause.start_cp + item.quote_end
        )
    if anchor is None:
        anchor = anchor_for(
            plan, clause, clause.start_cp, min(clause.end_cp, clause.start_cp + 240)
        )
    cited = tuple(item.evidence_ids)
    evidence_by_id = {entry["id"]: entry for entry in evidence}
    return make_finding(
        check_id=f"LEGAL:clause:{clause.clause_id}:statute",
        title=item.title,
        explanation=item.explanation,
        severity=item.severity,
        gate_type=item.gate_type,
        category="legal",
        operations=(),
        rule_id=item.rule_id,
        suggestion=item.suggestion,
        document_anchors=[anchor] if anchor else [],
        anchors=_evidence_anchors(evidence, cited),
        evidence_ids=[str(evidence_by_id[eid]["citation_id"] or eid) for eid in cited],
        basis="statute",
        support_level=item.support_level,
        applicability={
            "jurisdictions": sorted(
                {
                    str(evidence_by_id[eid].get("jurisdiction"))
                    for eid in cited
                    if evidence_by_id.get(eid, {}).get("jurisdiction")
                }
            ),
            "assessment_date": datetime.now(timezone.utc).date().isoformat(),
            "limitations": [],
        },
    )


def run_document_scan(
    request: ReviewCreate,
    snapshot: dict[str, Any],
    *,
    run_id: str,
    report_id: str,
    statute: Any = None,
    composer: LegalComposer | None = None,
    principal: Any = None,
    settings: ScanSettings | None = None,
    progress: Callable[[dict], None] | None = None,
) -> ReviewReport:
    """Scan one draft. Deterministic checks always run; the legal leg runs when `legal` is asked."""
    settings = settings or ScanSettings.from_env()
    started = time.monotonic()
    deadline = started + settings.deadline_seconds
    plan = split_clauses(
        snapshot.get("content"),
        text=snapshot.get("text"),
        max_chars=settings.clause_chars,
        max_clauses=settings.max_clauses,
    )
    document_type = request.business_type or detect_document_type(plan.text)
    snapshot_meta = {
        "document_id": snapshot.get("document_id") or request.document_id,
        "revision": snapshot.get("revision"),
        "content_sha256": snapshot.get("content_sha256"),
        "document_type": document_type,
    }
    limitations: list[dict] = []

    if plan.no_text:
        check = CheckResult(
            check_id="LEGAL:document:text",
            method="deterministic",
            scope_key="document",
            status="needs_input",
            reason_codes=["no_document_text"],
            missing_facts=["document_text"],
        )
        summary = _coverage_summary([check], plan, settings)
        return ReviewReport(
            report_id=report_id,
            run_id=run_id,
            completion="partial",
            outcome="needs_input",
            findings=[],
            coverage=[check],
            limitations=[
                {
                    "code": "no_document_text",
                    "message": "The saved draft has no text to scan.",
                }
            ],
            snapshot=snapshot_meta,
            coverage_summary=summary,
            retrieval={"queries": 0, "hits": 0, "layers": []},
            gate={
                "status": "blocked",
                "reasons": ["no_document_text"],
                "coverage_ratio": 0.0,
                "policy": "legal-scan/1",
            },
        )

    checks: list[CheckResult] = []
    findings: list[Finding] = []
    for check, finding in evaluate_elements(plan, document_type=document_type):
        checks.append(check)
        if finding is not None:
            findings.append(finding)
    for check, finding in evaluate_consistency(plan, applicable_on=request.applicable_on):
        checks.append(check)
        if finding is not None:
            findings.append(finding)
    for check, finding in evaluate_compliance(plan):
        checks.append(check)
        if finding is not None:
            findings.append(finding)
    for clause in plan.clauses:
        check, clause_findings = evaluate_clause_markers(plan, clause)
        checks.append(check)
        findings.extend(clause_findings)
    if progress is not None:
        progress(
            {
                "stage": "deterministic",
                "done": len(checks),
                "current": None,
                "findings": len(findings),
            }
        )

    legal_enabled = "legal" in set(request.modes)
    web_requested = (
        bool(request.web_search) if request.web_search is not None else settings.web_default
    )
    language = _language(plan.text)
    queries: list[str] = []
    hits_total = 0
    layers: list[dict] = []
    uncovered: list[Clause] = []
    web_used = False
    web_calls = 0

    if legal_enabled:
        if statute is None or not hasattr(statute, "search_detailed"):
            for clause in plan.clauses:
                checks.append(
                    CheckResult(
                        check_id=f"LEGAL:clause:{clause.clause_id}:statute",
                        method="legal",
                        scope_key=clause.clause_id,
                        clause_id=clause.clause_id,
                        status="failed",
                        reason_codes=["statute_unavailable"],
                        search_queries=[_clause_query(clause, request)],
                    )
                )
            layers.append({"layer": "statute", "status": "failed", "detail": "statute_unavailable"})
        else:
            workers = min(4, max(1, len(plan.clauses)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(
                    pool.map(
                        lambda clause: _scan_clause_evidence(statute, principal, request, clause),
                        plan.clauses,
                    )
                )
            for index, (clause, result) in enumerate(zip(plan.clauses, results), start=1):
                candidates, reason, hits, query = result
                queries.append(query)
                hits_total += hits
                check_id = f"LEGAL:clause:{clause.clause_id}:statute"
                evidence = _evidence_payload(candidates, settings.max_evidence)
                if not candidates:
                    status = "needs_input" if reason == "empty" else "unable_to_assess"
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status=status,
                            reason_codes=[reason or "no_hit"],
                            search_queries=[query],
                        )
                    )
                    uncovered.append(clause)
                    continue
                if reason.startswith("uncovered:") or reason in ("low_confidence", "superseded"):
                    # Hits exist, but the service itself says they do not cover the question.
                    # A finding built on them would overstate what the corpus supports.
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status="unable_to_assess",
                            reason_codes=[reason],
                            evidence_count=len(evidence),
                            search_queries=[query],
                        )
                    )
                    uncovered.append(clause)
                    continue
                if composer is None or not composer.available:
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status="unable_to_assess",
                            reason_codes=["composer_unavailable"],
                            evidence_count=len(evidence),
                            search_queries=[query],
                        )
                    )
                    continue
                if time.monotonic() > deadline:
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status="unable_to_assess",
                            reason_codes=["deadline_exceeded"],
                            evidence_count=len(evidence),
                            search_queries=[query],
                        )
                    )
                    continue
                try:
                    composed = composer.review_clause(
                        clause_id=clause.clause_id,
                        clause_text=clause.text,
                        rules=_marker_rules(clause.text),
                        evidence=evidence,
                        language=language,
                    )
                except ComposeError as exc:
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status="failed",
                            reason_codes=[exc.code],
                            evidence_count=len(evidence),
                            search_queries=[query],
                        )
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 - a composer crash is a failed unit
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status="failed",
                            reason_codes=[f"compose_error:{type(exc).__name__}"],
                            evidence_count=len(evidence),
                            search_queries=[query],
                        )
                    )
                    continue
                if composed:
                    finding_ids: list[str] = []
                    for item in composed:
                        finding = _composed_finding(plan, clause, item, evidence)
                        findings.append(finding)
                        finding_ids.append(finding.finding_id)
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status="finding",
                            reason_codes=["risk_found"],
                            finding_ids=finding_ids,
                            evidence_count=len(evidence),
                            search_queries=[query],
                        )
                    )
                else:
                    checks.append(
                        CheckResult(
                            check_id=check_id,
                            method="legal",
                            scope_key=clause.clause_id,
                            clause_id=clause.clause_id,
                            status="pass",
                            reason_codes=["no_risk_found"],
                            evidence_count=len(evidence),
                            search_queries=[query],
                        )
                    )
                if progress is not None:
                    progress(
                        {
                            "stage": "retrieving",
                            "done": len(checks),
                            "current": f"{index}/{len(plan.clauses)}",
                            "findings": len(findings),
                        }
                    )
            layers.append({"layer": "statute", "status": "ok", "hits": hits_total})

    if legal_enabled and web_requested:
        web_check_id = "LEGAL:web:supplement"
        if composer is None or not composer.available:
            checks.append(
                CheckResult(
                    check_id=web_check_id,
                    method="legal",
                    scope_key="web",
                    status="unable_to_assess",
                    reason_codes=["composer_unavailable"],
                )
            )
        elif not uncovered:
            checks.append(
                CheckResult(
                    check_id=web_check_id,
                    method="legal",
                    scope_key="web",
                    status="not_applicable",
                    reason_codes=["web_not_needed"],
                )
            )
        else:
            try:
                web = composer.web_check(
                    _web_question(request, uncovered, detect_compliance(plan.text)),
                    language=language,
                )
            except ComposeError as exc:
                checks.append(
                    CheckResult(
                        check_id=web_check_id,
                        method="legal",
                        scope_key="web",
                        status="failed",
                        reason_codes=[exc.code],
                    )
                )
                layers.append({"layer": "web", "status": "failed", "detail": exc.code})
            except Exception as exc:  # noqa: BLE001 - a web crash is a failed unit
                checks.append(
                    CheckResult(
                        check_id=web_check_id,
                        method="legal",
                        scope_key="web",
                        status="failed",
                        reason_codes=[f"web_error:{type(exc).__name__}"],
                    )
                )
                layers.append({"layer": "web", "status": "failed"})
            else:
                web_calls += 1
                if web.usable:
                    anchors = [
                        EvidenceAnchor(title=item.title, url=item.url, unverified=True).model_dump()
                        for item in web.usable
                    ]
                    finding = make_finding(
                        check_id=web_check_id,
                        title="Web sources need a human check",
                        explanation=(
                            "The statute corpus did not cover this clause, so a web search was "
                            "used to look for a conflict. Web sources are unverified and cannot "
                            "block a submission on their own."
                        ),
                        severity="Info",
                        gate_type="human_review",
                        category="web",
                        operations=(),
                        rule_id="LEGAL-WEB-SUPPLEMENT",
                        suggestion="Open each link and confirm it before relying on it.",
                        basis="web",
                        support_level="insufficient",
                        anchors=anchors,
                    )
                    findings.append(finding)
                    web_used = True
                    checks.append(
                        CheckResult(
                            check_id=web_check_id,
                            method="legal",
                            scope_key="web",
                            status="finding",
                            reason_codes=["web_used"],
                            finding_ids=[finding.finding_id],
                            evidence_count=len(anchors),
                        )
                    )
                    layers.append({"layer": "web", "status": "ok", "hits": len(anchors)})
                else:
                    checks.append(
                        CheckResult(
                            check_id=web_check_id,
                            method="legal",
                            scope_key="web",
                            status="unable_to_assess",
                            reason_codes=["web_no_citation"],
                        )
                    )
                    layers.append({"layer": "web", "status": "skipped", "detail": web.note})

    summary = _coverage_summary(checks, plan, settings)
    if plan.truncated:
        limitations.append(
            {
                "code": "truncated",
                "message": f"Only the first {len(plan.clauses)} clauses were scanned.",
            }
        )
    if legal_enabled and web_requested and not web_used:
        limitations.append(
            {
                "code": "web_not_used",
                "message": "The web check produced no citable source; nothing external was kept.",
            }
        )

    if findings:
        outcome = "findings_present"
        completion = "complete"
    elif any(check.status == "needs_input" for check in checks):
        outcome = "needs_input"
        completion = "partial"
    elif any(check.status in ("unable_to_assess", "failed") for check in checks):
        outcome = "unable_to_assess"
        completion = "partial"
    else:
        outcome = "no_findings"
        completion = "complete"
    if plan.truncated:
        completion = "partial"

    retrieval = {
        "queries": len(queries),
        "hits": hits_total,
        "web_requested": web_requested,
        "web_used": web_used,
        "web_calls": web_calls,
        "layers": layers,
    }
    return ReviewReport(
        report_id=report_id,
        run_id=run_id,
        completion=completion,
        outcome=outcome,
        findings=findings,
        coverage=checks,
        limitations=limitations,
        snapshot=snapshot_meta,
        coverage_summary=summary,
        retrieval=retrieval,
        gate=gate_for(findings, summary, settings, checks),
    )


__all__ = [
    "SETTLED",
    "ScanSettings",
    "gate_for",
    "run_document_scan",
]