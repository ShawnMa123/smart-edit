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


def _evaluate_rule(rule: Rule, facts: dict) -> tuple[CheckResult, Finding | None]:
    missing = [f for f in rule.required_facts if (facts.get(f) or {}).get("state") == "missing"]
    if missing:
        return (
            CheckResult(
                check_id=f"check_{rule.rule_id.lower()}",
                method="deterministic",
                scope_key=rule.domain,
                status="needs_input",
                rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
                reason_codes=["missing_required_facts"],
                missing_facts=missing,
            ),
            None,
        )

    verdict = evaluate(rule.expression, facts)
    if verdict is False:
        # One finding id, used by both the CheckResult and the report — never two different ids
        # for the same finding.
        finding = _make_finding(rule)
        return (
            CheckResult(
                check_id=f"check_{rule.rule_id.lower()}",
                method="deterministic",
                scope_key=rule.domain,
                status="finding",
                rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
                reason_codes=["rule_violated"],
                finding_ids=[finding.finding_id],
            ),
            finding,
        )
    if verdict is True:
        return (
            CheckResult(
                check_id=f"check_{rule.rule_id.lower()}",
                method="deterministic",
                scope_key=rule.domain,
                status="pass",
                rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
            ),
            None,
        )
    return (
        CheckResult(
            check_id=f"check_{rule.rule_id.lower()}",
            method="deterministic",
            scope_key=rule.domain,
            status="unable_to_assess",
            rule_refs=[{"rule_id": rule.rule_id, "version": rule.version}],
            reason_codes=["unconfirmed_fact"],
        ),
        None,
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
        check, finding = _evaluate_rule(rule, facts)
        checks.append(check)
        if finding is not None:
            findings.append(finding)
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
    # A requested mode this build does not implement must be visible as "could not assess", never
    # silently omitted (an omitted mode would turn the report into a clean pass).
    modes = list(dict.fromkeys(request.modes))
    for mode in modes:
        if mode not in ("deterministic", "legal"):
            checks.append(
                CheckResult(
                    check_id=f"check_{mode}",
                    method=mode,
                    scope_key=mode,
                    status="unable_to_assess",
                    reason_codes=["unsupported_mode"],
                )
            )
    if "deterministic" in modes:
        d_checks, d_findings = run_deterministic(facts)
        checks.extend(d_checks)
        findings.extend(d_findings)
    if "legal" in modes:
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


# ── document scan orchestration (`legal-document-risk-scan`) ──────────────────
class LegalRequestError(RuntimeError):
    """A request the service refuses; the API maps it onto the project error contract."""

    def __init__(
        self, status: int, code: str, message: str, detail: dict | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


class LegalService:
    """Question reviews (synchronous) and document scans (queued + polled)."""

    def __init__(
        self,
        *,
        store: Any,
        statute: Any = None,
        composer: Any = None,
        documents: Any = None,
        settings: Any = None,
    ) -> None:
        from app.legal_review.scan import ScanSettings

        self.store = store
        self.statute = statute
        self.composer = composer
        self.documents = documents
        self.settings = settings or ScanSettings.from_env()

    # --- submit -----------------------------------------------------------------------------
    def submit(
        self,
        request: ReviewCreate,
        facts: dict,
        *,
        principal: Any = None,
        idempotency_key: str | None = None,
    ) -> tuple[ReviewRun, bool]:
        """Return `(run, needs_background_scan)`; repeats of a key return the original run."""
        if idempotency_key:
            existing = self.store.get_by_key(idempotency_key)
            if existing is not None:
                return existing, False

        if request.scope == "question":
            run, report = create_review(
                request, facts, statute=self.statute, principal=principal
            )
            self._save(run, report, request)
            if idempotency_key:
                bound = self.store.remember(idempotency_key, run.run_id)
                if bound is not None and bound.run_id != run.run_id:
                    return bound, False
            return run, False

        now = _utcnow()
        run_id = f"lr_{uuid.uuid4().hex[:12]}"
        report_id = f"lrep_{uuid.uuid4().hex[:12]}"
        deadline = now + timedelta(seconds=self.settings.deadline_seconds + 30)
        run = ReviewRun(
            run_id=run_id,
            status="queued",
            stage="queued",
            created_at=_iso(now),
            deadline_at=_iso(deadline),
            report_id=report_id,
            progress={"stage": "queued", "planned": 0, "done": 0, "current": None},
        )
        self.store.save_run(
            run, workspace_id=request.workspace_id, document_id=request.document_id
        )
        if idempotency_key:
            bound = self.store.remember(idempotency_key, run.run_id)
            if bound is not None and bound.run_id != run.run_id:
                return bound, False
        return run, True

    # --- scan -------------------------------------------------------------------------------
    def execute_document_scan(
        self, run_id: str, request: ReviewCreate, principal: Any = None
    ) -> None:
        """Background task: resolve the draft, scan it, persist the report. Never raises."""
        from app.legal_review.scan import run_document_scan

        run = self.store.get_run(run_id)
        if run is None:
            return

        def progress(payload: dict) -> None:
            current = self.store.get_run(run_id) or run
            self.store.save_run(
                current.model_copy(
                    update={
                        "status": "running",
                        "stage": str(payload.get("stage") or "running"),
                        "progress": payload,
                    }
                ),
                workspace_id=request.workspace_id,
                document_id=request.document_id,
            )

        try:
            snapshot = self._snapshot(principal, request)
            progress({"stage": "splitting", "planned": 0, "done": 0, "current": None})
            report = run_document_scan(
                request,
                snapshot,
                run_id=run.run_id,
                report_id=run.report_id or f"lrep_{uuid.uuid4().hex[:12]}",
                statute=self.statute,
                composer=self.composer,
                principal=principal,
                settings=self.settings,
                progress=progress,
            )
        except LegalRequestError as exc:
            self._fail(run, exc.code, request)
            return
        except Exception as exc:  # noqa: BLE001 - the polled run must show the failure
            self._fail(run, f"scan_error:{type(exc).__name__}", request)
            return

        self.store.save_report(
            report, workspace_id=request.workspace_id, document_id=request.document_id
        )
        finished = self.store.get_run(run_id) or run
        self.store.save_run(
            finished.model_copy(
                update={
                    "status": "succeeded",
                    "stage": "done",
                    "finished_at": _iso(_utcnow()),
                    "progress": {
                        "stage": "done",
                        "planned": report.coverage_summary.get("planned", 0),
                        "done": len(report.coverage),
                        "current": None,
                        "findings": len(report.findings),
                    },
                }
            ),
            workspace_id=request.workspace_id,
            document_id=request.document_id,
        )

    def _snapshot(self, principal: Any, request: ReviewCreate) -> dict:
        if self.documents is None:
            raise LegalRequestError(
                409,
                "document_host_unavailable",
                "this server has no document host, so the draft cannot be read",
            )
        try:
            view = self.documents.document_view(principal, request.document_id)
        except Exception as exc:  # noqa: BLE001 - HostError carries its own status/code
            status = int(getattr(exc, "status", 404) or 404)
            code = str(getattr(exc, "code", "document_unavailable") or "document_unavailable")
            raise LegalRequestError(status, code, str(exc)) from exc
        if request.draft_id and view.get("draft_id") != request.draft_id:
            raise LegalRequestError(
                409,
                "stale_snapshot",
                "the draft changed since this scan was requested",
                {"revision": view.get("revision")},
            )
        if request.expected_revision is not None and int(view.get("revision") or 0) != int(
            request.expected_revision
        ):
            raise LegalRequestError(
                409,
                "stale_snapshot",
                "the draft changed since this scan was requested",
                {"revision": view.get("revision")},
            )
        expected_sha = request.expected_content_sha256
        if expected_sha and str(view.get("content_sha256") or "") != expected_sha:
            raise LegalRequestError(
                409,
                "stale_snapshot",
                "the draft content changed since this scan was requested",
                {"revision": view.get("revision")},
            )
        return view

    def _save(self, run: ReviewRun, report: ReviewReport, request: ReviewCreate) -> None:
        self.store.save_report(
            report, workspace_id=request.workspace_id, document_id=request.document_id
        )
        self.store.save_run(
            run, workspace_id=request.workspace_id, document_id=request.document_id
        )

    def _fail(self, run: ReviewRun, code: str, request: ReviewCreate) -> None:
        self.store.save_run(
            run.model_copy(
                update={
                    "status": "failed",
                    "stage": "failed",
                    "error": code,
                    "finished_at": _iso(_utcnow()),
                }
            ),
            workspace_id=request.workspace_id,
            document_id=request.document_id,
        )

    # --- reads ------------------------------------------------------------------------------
    def get_run(self, run_id: str) -> ReviewRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise LegalRequestError(404, "resource_unavailable", "legal run not found")
        return run

    def get_report(self, report_id: str) -> ReviewReport:
        report = self.store.get_report(report_id)
        if report is None:
            raise LegalRequestError(404, "resource_unavailable", "legal report not found")
        return report

    def report_workspace(self, report_id: str) -> str | None:
        return self.store.report_workspace(report_id)


__all__ = [
    "LegalRequestError",
    "LegalService",
    "create_review",
    "run_deterministic",
    "run_legal",
]
