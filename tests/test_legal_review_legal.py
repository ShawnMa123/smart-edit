"""Legal mode: `StatuteOutcome` -> `Finding` mapping and the "not checked != no problem" harness.

Bottom lines under test:
1. failed / timeout / no-reference -> `unable_to_assess` or `needs_input`, NEVER `no_findings`;
2. a normal return keeps `evidence_ids` non-empty and does not drop `chunk_id`;
3. timeout / uncovered / no-hit stay distinguishable through `reason_codes`;
4. an `unavailable`/`unsupported` answer (off-topic or no usable hit) is `unable_to_assess` and its
   retrieved references are never surfaced as citations.
"""

from __future__ import annotations

from app.assistant.ports import EvidenceCandidate
from app.assistant.statute import StatuteOutcome
from app.legal_review.contracts import ReviewCreate
from app.legal_review.service import create_review
from app.shared.ports import Principal

# In-scope legal question (hits the `trade_rule_explanation` intent via "保函").
QUESTION = "银行保函的金额条款有哪些法律要求？"


def _candidate(chunk_id: str, doc_id: str, article: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        citation_id=f"statute:{doc_id}:{chunk_id}",
        source_type="statute",
        title="示范法规",
        source_version=f"{article}@2020-01-01",
        excerpt="这是被检索到的条文摘录。",
        locator={
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "article_label": article,
            "jurisdiction": "CN",
        },
        chunk_id=chunk_id,
        effective_from="2020-01-01",
    )


class StubStatute:
    def __init__(self, outcome: StatuteOutcome):
        self._outcome = outcome
        self.calls = []

    def chat_detailed(self, principal, workspace_id, plan, applicable_on):
        self.calls.append((principal, workspace_id, plan.question, applicable_on))
        return self._outcome


def _submit(modes, question=None, statute=None):
    request = ReviewCreate(
        workspace_id="ws_demo",
        document_id="doc_demo",
        snapshot_id="snap_01",
        facts_version_id="facts_01",
        modes=modes,
        question=question,
    )
    return create_review(
        request, {}, statute=statute, principal=Principal("u1", "ws_demo")
    )


def test_legal_answer_produces_finding_with_traceable_evidence():
    outcome = StatuteOutcome(
        candidates=[_candidate("chunk_1", "doc_1", "第 12 条")],
        status="ok",
        reason="answered",
        hits=1,
        draft="该情形下应依据第 12 条办理。",
        answer_status="answered",
        cited_ids=("chunk_1",),
    )
    _, report = _submit(["legal"], question=QUESTION, statute=StubStatute(outcome))

    assert report.outcome == "findings_present"
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.method == "legal"
    assert finding.explanation == "该情形下应依据第 12 条办理。"
    assert finding.support_level == "strong"
    # Bottom line 2: evidence is traceable and the chunk id is not dropped.
    assert finding.evidence_ids
    assert "chunk_1" in [anchor["chunk_id"] for anchor in finding.anchors]
    assert report.coverage[0].status == "finding"


def test_legal_no_references_is_unable_to_assess_not_pass():
    outcome = StatuteOutcome(
        candidates=[],
        status="ok",
        reason="unsupported",
        answer_status="unsupported",
    )
    _, report = _submit(["legal"], question=QUESTION, statute=StubStatute(outcome))

    # Bottom line 1: an empty result is NOT "no findings".
    assert report.outcome == "unable_to_assess"
    assert report.findings == []
    assert report.coverage[0].status == "unable_to_assess"
    assert report.coverage[0].reason_codes == ["unsupported"]


def test_legal_transport_failure_is_distinct():
    # Bottom line 3: timeout vs uncovered vs no-hit each keep their own reason code.
    timeout = StubStatute(
        StatuteOutcome(status="failed", reason="timeout", answer_status="error")
    )
    _, timed_out = _submit(["legal"], question=QUESTION, statute=timeout)
    assert timed_out.coverage[0].status == "failed"
    assert timed_out.coverage[0].reason_codes == ["timeout"]

    uncovered = StubStatute(
        StatuteOutcome(status="failed", reason="corpus_updating", answer_status="error")
    )
    _, updating = _submit(["legal"], question=QUESTION, statute=uncovered)
    assert updating.coverage[0].status == "failed"
    assert updating.coverage[0].reason_codes == ["corpus_updating"]

    no_hit = StubStatute(
        StatuteOutcome(candidates=[], status="ok", reason="unsupported", answer_status="unsupported")
    )
    _, no_hit_report = _submit(["legal"], question=QUESTION, statute=no_hit)
    assert no_hit_report.coverage[0].status == "unable_to_assess"
    assert no_hit_report.coverage[0].reason_codes == ["unsupported"]

    # All three are distinguishable from one another.
    reasons = {
        timed_out.coverage[0].reason_codes[0],
        updating.coverage[0].reason_codes[0],
        no_hit_report.coverage[0].reason_codes[0],
    }
    assert reasons == {"timeout", "corpus_updating", "unsupported"}


def test_legal_without_statute_layer_is_failed_not_pass():
    # Bottom line 1 again: a missing statute layer must not read as "no problem".
    _, report = _submit(["legal"], question=QUESTION, statute=None)
    assert report.outcome == "unable_to_assess"
    assert report.findings == []
    assert report.coverage[0].status == "failed"
    assert report.coverage[0].reason_codes == ["statute_unavailable"]


def test_legal_empty_question_needs_input():
    _, report = _submit(["legal"], question="   ", statute=StubStatute(None))
    assert report.coverage[0].status == "needs_input"
    assert report.coverage[0].reason_codes == ["missing_question"]


def test_unavailable_answer_is_unable_to_assess_without_surfacing_citations():
    # Bottom line 4: the service says it cannot answer (off-topic / no usable hit). The references it
    # returned are irrelevant and must NOT be surfaced as a finding or as citations.
    outcome = StatuteOutcome(
        candidates=[_candidate("garbage_1", "doc_x", "第 1 条")],
        status="ok",
        reason="unavailable",
        hits=5,
        answer_status="unavailable",
    )
    _, report = _submit(["legal"], question="天津都有什么旅游景点？", statute=StubStatute(outcome))

    assert report.outcome == "unable_to_assess"
    assert report.findings == []
    assert report.coverage[0].status == "unable_to_assess"
    assert report.coverage[0].reason_codes == ["unavailable"]


def test_partial_answer_is_a_finding_with_caveat():
    # `partial` means the service engaged but could only cover part of the question — still a finding,
    # with `qualified` support and the caveat kept in the explanation.
    outcome = StatuteOutcome(
        candidates=[_candidate("chunk_1", "doc_1", "第 10 条")],
        status="ok",
        reason="partial",
        hits=1,
        draft="依据现有条文…但不构成完整法规体系。",
        answer_status="partial",
        cited_ids=("chunk_1",),
    )
    _, report = _submit(["legal"], question="从中国进口美国牛肉都有什么法规", statute=StubStatute(outcome))

    assert report.outcome == "findings_present"
    assert report.findings[0].support_level == "qualified"
    assert report.findings[0].explanation == "依据现有条文…但不构成完整法规体系。"
