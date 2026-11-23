"""Document scan: clause plan, deterministic checks, evidence-bound composition, gate.

The invariants asserted here are the ones the UI relies on:

- every anchor quote is a real substring of the draft;
- "could not check" never reads as "no findings";
- the composer cannot invent evidence, raise severity or hard-block;
- the web leg only runs when the user asked for it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.assistant.ports import EvidenceCandidate
from app.documents.projection import plain_text_document
from app.legal_review.checks import (
    evaluate_clause_markers,
    evaluate_consistency,
    evaluate_elements,
)
from app.legal_review.compose import (
    ComposedFinding,
    ComposeError,
    LegalComposer,
    WebCheck,
    WebEvidence,
)
from app.legal_review.contracts import ReviewCreate
from app.legal_review.document import split_text
from app.legal_review.scan import ScanSettings, run_document_scan
from app.legal_review.service import LegalService
from app.legal_review.store import LegalStore

DOCUMENT = """DEMAND GUARANTEE
Applicant: Atlas Trading Ltd
Beneficiary: Meridian Exports Pte Ltd
Amount: USD 250,000.00
Issue date: 2026-01-10
Expiry date: 2027-06-30
Governing rules: URDG 758
Jurisdiction: Singapore
Claim documents: demand and statement

1. Payment
The bank will pay against the documents presented.

2. Extension
The guarantee will be automatically extended for one year.
"""

NEUTRAL = """DEMAND GUARANTEE
Applicant: Atlas Trading Ltd
Beneficiary: Meridian Exports Pte Ltd
Amount: USD 250,000.00
Issue date: 2026-01-10
Expiry date: 2027-06-30
Governing rules: URDG 758
Jurisdiction: Singapore
Claim documents: demand and statement
The bank will pay against the documents presented.
"""

CANDIDATE = EvidenceCandidate(
    citation_id="cite_1",
    source_type="statute",
    title="URDG 758",
    source_version="第九条@2010-07-01",
    excerpt="The guarantor shall examine a demand within five business days.",
    locator={
        "chunk_id": "chunk_9",
        "doc_id": "urdg-758",
        "article_label": "第九条",
        "jurisdiction": "INT",
    },
    source_text="The guarantor shall examine a demand within five business days.",
    chunk_id="chunk_9",
    effective_from="2010-07-01",
)


class FakeStatute:
    def __init__(self, candidates=None, reason="ok", hits=1) -> None:
        self.candidates = list(candidates or [])
        self.reason = reason
        self.hits = hits
        self.calls: list[str] = []

    def search_detailed(self, principal, workspace_id, plan, applicable_on):
        self.calls.append(plan.question)
        return SimpleNamespace(
            candidates=list(self.candidates),
            reason=self.reason,
            hits=self.hits,
            status="ok",
        )


class FakeComposer:
    available = True

    def __init__(self, findings=None, web=None) -> None:
        self.findings = list(findings or [])
        self.web = web
        self.reviewed: list[str] = []
        self.web_calls = 0

    def review_clause(self, *, clause_id, clause_text, rules, evidence, language="zh-CN"):
        self.reviewed.append(clause_id)
        return list(self.findings)

    def web_check(self, question, *, language="zh-CN", max_keyword=3):
        self.web_calls += 1
        return self.web or WebCheck(attempted=True)


class FakeDocuments:
    def __init__(self, view: dict) -> None:
        self.view = view

    def document_view(self, principal, document_id):
        return {**self.view, "document_id": document_id}


def _request(**overrides) -> ReviewCreate:
    values = {
        "workspace_id": "ws_demo",
        "document_id": "doc_1",
        "modes": ["deterministic", "legal"],
        "scope": "document",
        "applicable_on": "2026-11-20",
    }
    values.update(overrides)
    return ReviewCreate(**values)


def _snapshot(text: str, *, revision: int = 1) -> dict:
    return {
        "document_id": "doc_1",
        "revision": revision,
        "content_sha256": "sha-" + str(revision),
        "text": text,
        "content": plain_text_document(text),
    }


def _scan(*, text: str = DOCUMENT, statute=None, composer=None, settings=None, **overrides):
    request = _request(**overrides)
    return run_document_scan(
        request,
        _snapshot(text),
        run_id="lr_1",
        report_id="lrep_1",
        statute=statute,
        composer=composer,
        settings=settings or ScanSettings(),
    )


def test_split_clauses_keeps_every_anchor_inside_the_draft():
    plan = split_text(DOCUMENT)

    assert len(plan.clauses) >= 3
    for clause in plan.clauses:
        assert plan.text[clause.start_cp : clause.end_cp] == clause.text
        check, findings = evaluate_clause_markers(plan, clause)
        assert check.clause_id == clause.clause_id
        for finding in findings:
            for anchor in finding.document_anchors:
                assert anchor.quote in plan.text
                assert anchor.start_cp >= clause.start_cp


def test_missing_elements_are_findings_with_a_document_level_reason():
    plan = split_text("DEMAND GUARANTEE\n\nApplicant: A\n\nBeneficiary: B")
    results = {check.check_id: (check, finding) for check, finding in evaluate_elements(plan)}

    amount, amount_finding = results["LEGAL:element:amount"]
    assert amount.status == "finding"
    assert amount_finding.severity == "Critical"
    assert amount_finding.gate_type == "hard_block"
    assert amount_finding.basis == "rule"

    applicant, applicant_finding = results["LEGAL:element:applicant"]
    assert applicant.status == "pass"
    assert applicant_finding is None


def test_dates_out_of_order_and_expired_are_findings_but_unparsed_is_needs_input():
    inverted = split_text("Issue date: 2027-01-01\n\nExpiry date: 2026-01-01")
    results = {
        check.check_id: check
        for check, _ in evaluate_consistency(inverted, applicable_on="2026-11-20")
    }
    assert results["LEGAL:consistency:dates_ordered"].status == "finding"
    assert results["LEGAL:consistency:not_expired"].status == "finding"

    unparsed = split_text("DEMAND GUARANTEE\n\nAmount: USD 1.00")
    results = {
        check.check_id: check
        for check, _ in evaluate_consistency(unparsed, applicable_on="2026-11-20")
    }
    assert results["LEGAL:consistency:dates_ordered"].status == "needs_input"
    assert results["LEGAL:consistency:not_expired"].status == "needs_input"
    assert "issue_date" in results["LEGAL:consistency:dates_ordered"].missing_facts


def test_a_marker_anchor_points_at_the_wording_that_matched():
    plan = split_text(DOCUMENT)
    clause = next(clause for clause in plan.clauses if "automatically extended" in clause.text)

    check, findings = evaluate_clause_markers(plan, clause)

    assert check.status == "finding"
    marker = next(
        finding
        for finding in findings
        if finding.rule_refs[0].rule_id == "LEGAL-MARKER-AUTOMATIC-EXTENSION"
    )
    assert marker.gate_type == "human_review"
    assert marker.document_anchors
    assert "automatically extended" in marker.document_anchors[0].quote


def test_legal_mode_without_a_statute_is_unable_to_assess_not_a_clean_pass():
    report = _scan(text=NEUTRAL, statute=None, composer=None)

    assert report.outcome == "unable_to_assess"
    assert report.completion == "partial"
    assert report.findings == []
    legal_checks = [check for check in report.coverage if ":statute" in check.check_id]
    assert legal_checks
    assert {check.status for check in legal_checks} == {"failed"}
    assert {check.reason_codes[0] for check in legal_checks} == {"statute_unavailable"}
    assert report.gate["status"] == "needs_human_review"
    assert "unchecked_units" in report.gate["reasons"]


def test_coverage_counts_every_planned_unit_and_stays_internally_consistent():
    report = _scan(text=DOCUMENT, statute=FakeStatute([CANDIDATE]), composer=FakeComposer())

    summary = report.coverage_summary
    assert summary["planned"] == len(report.coverage)
    assert summary["settled"] == summary["assessed"]
    assert summary["assessed_ratio"] == pytest.approx(
        summary["assessed"] / summary["planned"], abs=0.001
    )
    assert summary["clauses"] >= 3


def test_the_report_names_the_text_it_scanned():
    """A report must prove which revision and how many characters it read, plus a preview."""
    report = _scan(text=DOCUMENT)

    assert report.snapshot["revision"] == 1
    assert report.snapshot["characters"] == len(split_text(DOCUMENT).text)
    assert report.snapshot["preview"].startswith("DEMAND GUARANTEE")


def test_a_composed_finding_carries_evidence_and_a_draft_anchor():
    start = DOCUMENT.index("automatically extended")
    composed = ComposedFinding(
        rule_id="LEGAL-RISK-NEW",
        title="Extension needs a notice period",
        explanation="URDG 758 requires the extension mechanism to be stated clearly.",
        suggestion="State the notice period before an extension applies.",
        evidence_ids=("E1",),
        severity="Warning",
        gate_type="human_review",
        support_level="qualified",
        quote_start=start,
        quote_end=start + len("automatically extended"),
    )
    report = _scan(text=DOCUMENT, statute=FakeStatute([CANDIDATE]), composer=FakeComposer([composed]))

    finding = next(item for item in report.findings if item.basis == "statute")
    assert finding.evidence_ids == ["cite_1"]
    assert finding.anchors and finding.anchors[0].chunk_id == "chunk_9"
    assert finding.document_anchors
    assert "automatically extended" in finding.document_anchors[0].quote
    clause_check = next(
        check
        for check in report.coverage
        if check.check_id.endswith(":statute") and check.finding_ids
    )
    assert clause_check.evidence_count == 1
    assert clause_check.search_queries
    assert report.retrieval["hits"] >= 1
    assert report.gate["status"] == "needs_human_review"


def test_web_leg_is_off_unless_the_user_asks_for_it():
    web = WebCheck(
        attempted=True,
        usable=(WebEvidence(title="ICC guidance", url="https://iccwbo.org/x"),),
    )

    default_report = _scan(
        text=NEUTRAL,
        statute=FakeStatute([], reason="zero:no_match", hits=0),
        composer=FakeComposer(web=web),
    )
    assert default_report.retrieval["web_requested"] is False
    assert default_report.retrieval["web_calls"] == 0
    assert not any(
        check.check_id == "LEGAL:web:supplement" for check in default_report.coverage
    )

    asked_report = _scan(
        text=NEUTRAL,
        statute=FakeStatute([], reason="zero:no_match", hits=0),
        composer=FakeComposer(web=web),
        web_search=True,
    )
    assert asked_report.retrieval["web_requested"] is True
    assert asked_report.retrieval["web_calls"] == 1
    assert asked_report.retrieval["web_used"] is True
    web_finding = next(item for item in asked_report.findings if item.basis == "web")
    assert web_finding.gate_type == "human_review"
    assert web_finding.support_level == "insufficient"
    assert web_finding.anchors[0].url == "https://iccwbo.org/x"
    assert web_finding.anchors[0].unverified is True


def test_stale_revision_fails_the_run_instead_of_scanning_another_draft():
    service = LegalService(
        store=LegalStore(":memory:"),
        documents=FakeDocuments(
            {
                "draft_id": "draft_2",
                "revision": 5,
                "content_sha256": "sha-5",
                "text": NEUTRAL,
                "content": plain_text_document(NEUTRAL),
            }
        ),
    )
    request = _request(modes=["deterministic"], expected_revision=4)

    run, needs_scan = service.submit(request, {})

    assert needs_scan is True
    service.execute_document_scan(run.run_id, request)
    stored = service.get_run(run.run_id)
    assert stored.status == "failed"
    assert stored.error == "stale_snapshot"


def test_idempotency_returns_the_same_run():
    service = LegalService(store=LegalStore(":memory:"))
    request = ReviewCreate(
        workspace_id="ws_demo",
        document_id="doc_1",
        snapshot_id="snap",
        facts_version_id="facts",
        modes=["deterministic"],
    )

    first, _ = service.submit(request, {}, idempotency_key="k-1")
    second, needs_scan = service.submit(request, {}, idempotency_key="k-1")

    assert second.run_id == first.run_id
    assert needs_scan is False
    assert service.get_report(first.report_id or "").report_id == first.report_id


class FakeGateway:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def compose_json(self, system, payload, *, timeout=None):
        self.calls += 1
        return self.payload


def test_composer_drops_invented_rules_and_clamps_severity_and_gate():
    gateway = FakeGateway(
        {
            "findings": [
                {
                    "rule_id": "LEGAL-MARKER-AUTOMATIC-EXTENSION",
                    "title": "Extension",
                    "explanation": "e",
                    "evidence_ids": ["E1", "E9"],
                    "support_level": "strong",
                    "quote": "automatically extended",
                },
                {"rule_id": "INVENTED-RULE", "explanation": "x"},
                {
                    "rule_id": "LEGAL-RISK-NEW",
                    "title": "New",
                    "explanation": "new risk",
                    "evidence_ids": [],
                    "support_level": "strong",
                    "quote": "text that is not there",
                },
            ],
            "no_finding_reason": None,
        }
    )
    composer = LegalComposer(gateway, approved=True)

    out = composer.review_clause(
        clause_id="clause-02",
        clause_text=DOCUMENT,
        rules=[
            {
                "rule_id": "LEGAL-MARKER-AUTOMATIC-EXTENSION",
                "label": "Automatic extension",
                "severity": "Warning",
                "gate_type": "human_review",
            }
        ],
        evidence=[{"id": "E1", "citation_id": "cite_1"}],
    )

    assert len(out) == 2  # the invented rule id is dropped
    first = out[0]
    assert first.evidence_ids == ("E1",)  # unknown evidence id is dropped
    assert first.severity == "Warning"
    assert first.gate_type == "human_review"
    assert first.quote_start is not None
    second = out[1]
    assert second.support_level == "insufficient"
    assert second.quote_start is None


def test_composer_is_unavailable_without_approval_or_json_support():
    assert LegalComposer(FakeGateway({}), approved=False).available is False
    assert LegalComposer(object(), approved=True).available is False


def test_composer_refuses_to_run_when_unavailable():
    with pytest.raises(ComposeError):
        LegalComposer(FakeGateway({}), approved=False).review_clause(
            clause_id="c", clause_text="x", rules=[], evidence=[]
        )


def test_composer_denies_when_redaction_fails():
    composer = LegalComposer(FakeGateway({}), approved=True, redact=lambda text: None)

    with pytest.raises(ComposeError) as error:
        composer.review_clause(clause_id="c", clause_text="clause", rules=[], evidence=[])

    assert error.value.code == "redaction_unavailable"


def test_web_citations_are_deduped_by_url():
    citation = SimpleNamespace(
        title="ICC guidance", locator={"url": "https://iccwbo.org/urdg-758"}
    )

    class WebGateway(FakeGateway):
        def general_web(self, question, *, max_keyword, language="en"):
            return SimpleNamespace(
                answer=SimpleNamespace(citations=[citation, citation, citation], limitations=[]),
                annotations=[],
            )

    composer = LegalComposer(WebGateway({}), approved=True)

    web = composer.web_check("is this clause risky?")

    assert web.attempted is True
    assert len(web.usable) == 1
    assert web.usable[0].url == "https://iccwbo.org/urdg-758"