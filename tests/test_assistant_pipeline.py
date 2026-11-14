"""Tasks 3.1-3.4 — query routing, evidence building, composer and the code reviewer."""

from __future__ import annotations

from app.assistant.domain.evidence import (
    build_candidate,
    claim_supported,
    detect_conflicts,
    document_citation_id,
    stable_citation_id,
)
from app.assistant.domain.query import analyze
from app.assistant.domain.state_machine import validate_answer
from app.assistant.pipeline import FixtureComposer, review_answer
from app.assistant.ports import EvidenceBundle, EvidenceCandidate
from app.assistant.schemas import Answer, Citation, Claim
from app.knowledge.text import normalize

INTENTS = {"product_faq", "trade_rule_explanation", "document_explanation", "out_of_scope"}


def _row(**overrides) -> dict:
    row = {
        "chunk_id": "KC-1",
        "source_id": "KS-1",
        "version_id": "KV-1",
        "source_type": "trade_rule",
        "title": "合成贸易规则摘要",
        "version_label": "demo-1",
        "text": "URDG 758 第 20 条要求索赔以书面形式提出，并附支持声明。本段是合成摘要。",
        "locator": {"section": "URDG 758 索赔", "page": 12},
        "section": "URDG 758 索赔",
        "page": 12,
        "synthetic": True,
        "effective_from": "2024-01-01",
        "effective_to": None,
    }
    row.update(overrides)
    return row


def _candidate(**overrides) -> EvidenceCandidate:
    candidate = build_candidate(_row(), {"urdg", "758", "索赔"})
    candidate.score = 4.0
    for key, value in overrides.items():
        setattr(candidate, key, value)
    return candidate


def _answer(claims: list[Claim], citations: list[Citation], **overrides) -> Answer:
    payload = {
        "outcome": "answered",
        "language": "zh-CN",
        "support_level": "strong",
        "claims": claims,
        "citations": citations,
    }
    payload.update(overrides)
    return Answer(**payload)


# --- 3.1 query routing ------------------------------------------------------------------------


def test_intents_are_deterministic_and_inside_the_enum():
    cases = {
        "提交版本后编辑锁会释放吗？": "product_faq",
        "URDG 758 第 20 条对索赔有什么要求？": "trade_rule_explanation",
        "今天天气怎么样": "out_of_scope",
    }
    for question, expected in cases.items():
        plan = analyze(question)
        assert plan.intent == expected
        assert plan.intent in INTENTS
    assert analyze("请解释这段文字", selection_text="保函文本").intent == "document_explanation"


def test_edit_audit_and_regulatory_requests_are_handed_off():
    assert analyze("帮我改写这段条款").handoff_target == "automation"
    assert analyze("帮我检查这份文档").handoff_target == "standards_audit"
    assert analyze("这是否合法？").handoff_target == "regulatory_advice"
    for question in ("帮我改写这段条款", "帮我检查这份文档", "这是否合法？"):
        plan = analyze(question)
        assert plan.intent == "out_of_scope"
        assert plan.handoff_target is not None


def test_capability_help_routes_to_product_faq_without_swallowing_handoffs():
    for question in (
        "你能做什么？",
        "这个助手不能做什么？",
        "怎么用这个助手？",
        "支持哪些问题？",
        "我该怎么提问？",
    ):
        plan = analyze(question)
        assert plan.intent == "product_faq", question
        assert plan.handoff_target is None

    # Capability-looking questions that ask for an action or a legal conclusion stay handoff.
    for question, target in (
        ("你能修改文档吗？", "automation"),
        ("帮我改写这段条款", "automation"),
        ("帮我检查这份文档", "standards_audit"),
        ("这是否合法？", "regulatory_advice"),
    ):
        assert analyze(question).handoff_target == target


def test_english_help_and_product_routing():
    help_plans = [
        analyze("What can you do?"),
        analyze("What can this assistant not do?"),
        analyze("How should I ask a question?"),
    ]
    for plan in help_plans:
        assert plan.intent == "product_faq"
        assert plan.capability_help is True
        assert plan.help_source_id == "KS-HELP-002"
        assert plan.language == "en"

    product = analyze("What documents are required for the application?")
    assert product.intent == "product_faq"
    assert product.capability_help is False

    rule = analyze("What does URDG 758 article 20 require for claims?")
    assert rule.intent == "trade_rule_explanation"
    assert rule.language == "en"


def test_english_composer_uses_english_templates():
    candidate = _candidate(
        title="Knowledge Assistant Guide (synthetic demo)",
        excerpt="What can you do: the assistant supports product FAQ and rule explanations.",
        source_text=(
            "What can you do: the assistant supports product FAQ and rule explanations. "
            "This is a synthetic demo guide."
        ),
        source_id="KS-HELP-002",
        source_type="product_manual",
    )
    answer = FixtureComposer().compose(
        analyze("What can you do?"), EvidenceBundle([candidate]), {}
    ).answer

    assert answer.language == "en"
    assert answer.outcome == "answered"
    assert answer.claims[0].text.startswith("According to ")
    assert all("synthetic" in limitation.lower() for limitation in answer.limitations)
    assert validate_answer(answer) == []


def test_missing_applicability_information_asks_one_to_three_questions():
    plan = analyze("URDG 758 是否适用于德国？")
    assert plan.intent == "trade_rule_explanation"
    assert 1 <= len(plan.clarification_questions) <= 3
    resolved = analyze(
        "URDG 758 是否适用于德国？", jurisdiction_codes=["DE"], rule_version="URDG 758",
        applicable_on="2025-01-01",
    )
    assert resolved.clarification_questions == []


def test_document_intent_without_a_selection_asks_for_one():
    plan = analyze("这段文本是什么意思？", has_snapshot=True)
    assert plan.intent == "document_explanation"
    assert plan.clarification_questions
    assert plan.language == "zh-CN"
    assert analyze("what does this document say?", has_snapshot=True).language == "en"


# --- 3.2 evidence -----------------------------------------------------------------------------


def test_citation_ids_are_stable_and_version_scoped():
    first = stable_citation_id("KS-1", "KV-1", "KC-1")
    assert first == stable_citation_id("KS-1", "KV-1", "KC-1")
    assert first != stable_citation_id("KS-1", "KV-2", "KC-1")
    assert first != document_citation_id("snap_1", 0, 5)
    assert document_citation_id("snap_1", 0, 5) == document_citation_id("snap_1", 0, 5)


def test_candidate_carries_only_an_excerpt_and_a_locator():
    candidate = _candidate()
    assert candidate.excerpt
    assert normalize(candidate.excerpt) in normalize(candidate.source_text)
    assert candidate.locator["section"] == "URDG 758 索赔"
    assert candidate.locator["page"] == 12
    assert candidate.synthetic is True
    assert claim_supported("URDG 758 要求书面索赔", candidate)
    assert not claim_supported("UCP 600 适用于商业信用证", candidate)


def test_conflicting_sources_are_surfaced_instead_of_resolved():
    first = _candidate(citation_id="cite_a", source_id="KS-A", excerpt="URDG 758 要求书面索赔。")
    second = _candidate(citation_id="cite_b", source_id="KS-B", excerpt="URDG 758 允许口头索赔。")
    conflicts = detect_conflicts([first, second])
    assert conflicts and set(conflicts[0]["source_ids"]) == {"KS-A", "KS-B"}
    assert conflicts[0]["entity"] == "urdg758"

    same_source = _candidate(citation_id="cite_c", source_id="KS-A", excerpt="URDG 758 允许口头索赔。")
    assert detect_conflicts([first, same_source]) == []


# --- 3.3 composer -----------------------------------------------------------------------------


def _plan(question: str, **kwargs):
    return analyze(question, **kwargs)


def test_no_evidence_is_an_explicit_insufficient_answer():
    composition = FixtureComposer().compose(
        _plan("提交版本后编辑锁会释放吗？"), EvidenceBundle([]), {}
    )
    answer = composition.answer
    assert answer.outcome == "insufficient_evidence"
    assert answer.support_level == "insufficient"
    assert answer.claims == [] and answer.citations == []
    assert answer.limitations
    assert validate_answer(answer) == []


def test_handoff_clarification_and_out_of_scope_shapes():
    handoff = FixtureComposer().compose(_plan("帮我改写这段条款"), EvidenceBundle([]), {}).answer
    assert handoff.outcome == "needs_handoff" and handoff.handoff_target == "automation"

    clarification = FixtureComposer().compose(
        _plan("URDG 758 是否适用于德国？"), EvidenceBundle([]), {}
    ).answer
    assert clarification.outcome == "needs_clarification"
    assert 1 <= len(clarification.clarification_questions) <= 3

    out_of_scope = FixtureComposer().compose(
        _plan("今天天气怎么样"), EvidenceBundle([]), {}
    ).answer
    assert out_of_scope.outcome == "unable_to_assess"
    for answer in (handoff, clarification, out_of_scope):
        assert validate_answer(answer) == []


def test_answers_only_cite_ids_from_the_evidence_bundle():
    candidate = _candidate()
    composition = FixtureComposer().compose(
        _plan("URDG 758 第 20 条对索赔有什么要求？"), EvidenceBundle([candidate]), {}
    )
    answer = composition.answer
    assert answer.outcome == "answered"
    assert {citation.id for citation in answer.citations} == {candidate.citation_id}
    assert all(set(claim.citation_ids) <= set(composition.details) for claim in answer.claims)
    assert any("合成" in limitation for limitation in answer.limitations)
    assert validate_answer(answer) == []


def test_conflicting_evidence_becomes_unable_to_assess():
    first = _candidate(citation_id="cite_a", source_id="KS-A", excerpt="URDG 758 要求书面索赔。")
    second = _candidate(citation_id="cite_b", source_id="KS-B", excerpt="URDG 758 允许口头索赔。")
    conflicts = detect_conflicts([first, second])
    answer = FixtureComposer().compose(
        _plan("URDG 758 第 20 条对索赔有什么要求？"), EvidenceBundle([first, second]),
        {"conflicts": conflicts},
    ).answer
    assert answer.outcome == "unable_to_assess"
    assert answer.support_level == "insufficient"
    assert any("冲突" in limitation for limitation in answer.limitations)
    assert validate_answer(answer) == []


# --- 3.4 reviewer -----------------------------------------------------------------------------


def test_forged_citation_is_removed_and_run_abstains():
    good = _candidate()
    answer = _answer(
        claims=[Claim(id="c1", text="URDG 758 要求书面索赔", kind="fact",
                      citation_ids=["cite_forged"])],
        citations=[Citation(
            id="cite_forged", source_type="trade_rule", title=good.title,
            source_version=good.source_version, locator={},
        )],
    )
    reviewed, issues = review_answer(answer, EvidenceBundle([good]), None)

    assert issues and issues[0]["code"] == "citation_not_in_bundle"
    assert reviewed.outcome == "insufficient_evidence"
    assert reviewed.claims == [] and reviewed.citations == []
    assert validate_answer(reviewed) == []


def test_citation_that_does_not_match_its_source_is_rejected():
    good = _candidate()
    forged_source = _candidate(citation_id="cite_2", excerpt="这段摘录不在来源正文里。")
    answer = _answer(
        claims=[Claim(id="c1", text="URDG 758 要求书面索赔", kind="fact",
                      citation_ids=["cite_2"])],
        citations=[Citation(
            id="cite_2", source_type="trade_rule", title=good.title,
            source_version=good.source_version, locator={},
        )],
    )
    reviewed, issues = review_answer(answer, EvidenceBundle([forged_source]), None)

    assert [issue["code"] for issue in issues] == ["excerpt_not_in_source"]
    assert reviewed.outcome == "insufficient_evidence"


def test_an_amount_that_is_not_in_the_cited_text_is_rejected():
    candidate = _candidate()
    answer = _answer(
        claims=[Claim(
            id="c1", text="URDG 758 要求索赔金额为 USD 1,000,000", kind="fact",
            citation_ids=[candidate.citation_id],
        )],
        citations=[Citation(
            id=candidate.citation_id, source_type="trade_rule", title=candidate.title,
            source_version=candidate.source_version, locator={},
        )],
    )
    reviewed, issues = review_answer(answer, EvidenceBundle([candidate]), None)

    assert issues[0]["code"] == "entity_not_supported"
    assert reviewed.claims == []
    # Only structured issue codes are recorded — never hidden chain-of-thought.
    assert set(issues[0]) == {"code", "claim_id", "explanation"}


def test_document_selection_requires_the_exact_snapshot_slice():
    text = "保函文本：URDG 758 适用。"
    start = text.index("URDG")
    candidate = EvidenceCandidate(
        citation_id=document_citation_id("snap_1", start, start + 8),
        source_type="document_snapshot", title="doc-1", source_version="v1",
        excerpt="URDG 758", locator={"node_id": "block_0", "start_offset": start,
                                    "end_offset": start + 8},
        source_text=text, source_id="snap_1", version_id="snap_1",
        start_offset=start, end_offset=start + 8,
    )
    claim = Claim(id="c1", text="URDG 758", kind="interpretation",
                  citation_ids=[candidate.citation_id])
    citation = Citation(
        id=candidate.citation_id, source_type="document_snapshot", title="doc-1",
        source_version="v1", locator=candidate.locator,
    )
    reviewed, issues = review_answer(
        _answer([claim], [citation]), EvidenceBundle([candidate]), {"id": "snap_1", "text": text}
    )
    assert issues == [] and reviewed.outcome == "answered"

    reviewed, issues = review_answer(
        _answer([claim], [citation]), EvidenceBundle([candidate]),
        {"id": "snap_1", "text": "different text"},
    )
    assert issues and issues[0]["code"] == "anchor_mismatch"
    assert reviewed.outcome == "insufficient_evidence"


def test_a_supported_answer_stays_publishable():
    candidate = _candidate()
    answer = _answer(
        claims=[Claim(id="c1", text="URDG 758 要求书面索赔", kind="fact",
                      citation_ids=[candidate.citation_id])],
        citations=[Citation(
            id=candidate.citation_id, source_type="trade_rule", title=candidate.title,
            source_version=candidate.source_version, locator=candidate.locator,
        )],
    )
    reviewed, issues = review_answer(answer, EvidenceBundle([candidate]), None)
    assert issues == []
    assert reviewed.outcome == "answered" and reviewed.support_level == "strong"