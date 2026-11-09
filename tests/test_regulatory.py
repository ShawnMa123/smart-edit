"""Agent 3 contract tests: empty retrieval, honesty, citations, modes, escalation, reruns."""

from __future__ import annotations

import copy

from app.regulatory.node import regulatory_node
from app.regulatory.retriever import (
    FakeRetriever,
    KnowledgeBaseEmpty,
    RetrievalInvalidResponse,
    RetrievalUnavailable,
)
from app.runtime import execute_chain
from tests.helpers import make_doc

CORPUS = {
    "version": "2026-11-09.1",
    "documents": 92,
    "jurisdictions": ["AU", "CN", "US"],
    "built_at": "2026-11-09T00:00:00Z",
}

CHUNK = {
    "chunk_id": "chunk-1",
    "doc_id": "cn-customs-guarantee-2018",
    "source_doc": "中华人民共和国海关事务担保条例",
    "title": "海关事务担保条例",
    "text": "第464条 保函金额 USD 500,000.00 应当以书面形式约定，适用 URDG 758。",
    "score": 0.91,
    "articles": ["第464条"],
    "effective_from": "2021-01-01",
    "effective_to": None,
    "jurisdictions": ["CN"],
    "applies_to": ["guarantee", "customs"],
}


def _chunk() -> dict:
    return copy.deepcopy(CHUNK)


def _state(text: str = "保函编号 BG-2026-0001，金额 USD 500,000.00，适用 URDG 758。") -> dict:
    return {"docs": [make_doc(text)], "findings": [], "trail": [], "stages": []}


def _normalized_state(text: str = "保函编号 BG-2026-0001") -> dict:
    state = _state(text)
    state["fields"] = {
        "guarantee_amount": {"key": "guarantee_amount", "value": "USD 500,000.00"},
        "applicant_country": {"key": "applicant_country", "value": "CN"},
        "transaction_date": {"key": "transaction_date", "value": "2026-03-15"},
    }
    state["business_type"] = "guarantee"
    state["stages"] = [
        {"stage": "normalize", "agent": "agent1", "status": "done", "reason": None, "produced": 3, "model_calls": 0}
    ]
    return state


def test_empty_retrieval_sets_unavailable_and_escalates():
    update = regulatory_node(_state(), retriever=FakeRetriever([], CORPUS))

    legal = update["legal"]
    assert legal["coverage"]["unavailable"] is True
    assert legal["escalate_to_human"] is True
    assert update["retrieved"] == []
    assert update["stages"][0]["status"] == "done", "a completed search with no hits is not a failed stage"


def test_empty_retrieval_never_says_no_issue():
    update = regulatory_node(_state(), retriever=FakeRetriever([], CORPUS))

    summary = update["legal"]["summary"]
    assert "法规建议未覆盖" in summary
    for forbidden in ("未发现问题", "无适用规则", "合法合规"):
        assert forbidden not in summary
    assert any(f["rule_id"] == "REG-COVERAGE" for f in update["findings"])


def test_empty_corpus_fails_the_stage():
    retriever = FakeRetriever([], {"version": "v0", "documents": 0, "jurisdictions": []})
    update = regulatory_node(_state(), retriever=retriever)

    assert update["stages"][0]["status"] == "failed"
    assert update["stages"][0]["reason"] == "knowledge_base_empty"
    assert update["legal"]["coverage"]["unavailable"] is True
    assert update["legal"]["escalate_to_human"] is True


def test_service_unavailable_fails_the_stage():
    update = regulatory_node(
        _state(), retriever=FakeRetriever(error=RetrievalUnavailable("connection refused"))
    )

    assert update["stages"][0]["status"] == "failed"
    assert update["stages"][0]["reason"].startswith("retrieval_unavailable")
    assert "法规建议未覆盖" in update["legal"]["summary"]
    assert update["legal"]["escalate_to_human"] is True


def test_invalid_response_fails_the_stage():
    update = regulatory_node(
        _state(), retriever=FakeRetriever(error=RetrievalInvalidResponse("no corpus"))
    )

    assert update["stages"][0]["status"] == "failed"
    assert update["stages"][0]["reason"].startswith("retrieval_invalid_response")


def test_not_configured_fails_the_stage(monkeypatch):
    monkeypatch.setenv("SMART_EDIT_RAG", "off")
    update = regulatory_node(_state())

    assert update["stages"][0]["status"] == "failed"
    assert update["stages"][0]["reason"] == "retrieval_not_configured"
    assert update["retrieved"] == []


def test_raw_mode_without_business_type_sets_uncertain():
    state = _state("航空器租赁安排，交付地点为境外。")
    update = regulatory_node(state, retriever=FakeRetriever([_chunk()], CORPUS))

    legal = update["legal"]
    assert legal["input_mode"] == "raw"
    assert legal["coverage"]["business_type_uncertain"] is True
    assert legal["escalate_to_human"] is True
    assert all(finding["field_keys"] == [] for finding in update["findings"])


def test_raw_mode_infers_business_type_from_body():
    retriever = FakeRetriever([_chunk()], CORPUS)
    update = regulatory_node(_state(), retriever=retriever)

    legal = update["legal"]
    assert legal["input_mode"] == "raw"
    assert legal["coverage"]["business_type_uncertain"] is False
    assert legal["coverage"]["inferred_business_type"] == "guarantee"
    assert retriever.calls[0]["filters"]["applies_to"] == ["guarantee"]


def test_enriched_mode_uses_fields_and_normalize():
    retriever = FakeRetriever([_chunk()], CORPUS)
    update = regulatory_node(_normalized_state(), retriever=retriever)

    legal = update["legal"]
    assert legal["input_mode"] == "enriched"
    assert legal["coverage"]["business_type_uncertain"] is False
    assert retriever.calls[0]["filters"]["applies_to"] == ["guarantee"]
    assert retriever.calls[0]["filters"]["as_of"] == "2026-03-15"
    assert legal["escalate_to_human"] is False


def test_transaction_date_missing_falls_back_with_note():
    state = _state()
    update = regulatory_node(state, retriever=FakeRetriever([_chunk()], CORPUS))

    notes = update["legal"]["coverage"]["notes"]
    assert any("交易日期" in note for note in notes)
    assert update["legal"]["escalate_to_human"] is True
    assert any(f["rule_id"] == "REG-TRANSACTION-DATE" for f in update["findings"])


def test_mock_hit_is_critical_but_not_blocking():
    state = _normalized_state()
    state["fields"]["applicant"] = {"key": "applicant", "value": "SANCTIONED DEMO LTD"}
    update = regulatory_node(state, retriever=FakeRetriever([_chunk()], CORPUS))

    hits = [f for f in update["findings"] if f["rule_id"] == "REG-MOCK-SANCTIONS"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "critical"
    assert hits[0]["blocking"] is False
    assert "非真实名单" in hits[0]["message"]
    assert update["legal"]["escalate_to_human"] is True


def test_same_doc_two_modes_keeps_parse_blocks_identical():
    state = _state()
    blocks = copy.deepcopy(state["docs"][0]["blocks"])

    raw_state = copy.deepcopy(state)
    enriched_state = copy.deepcopy(state)
    enriched_state["fields"] = _normalized_state()["fields"]
    enriched_state["business_type"] = "guarantee"
    enriched_state["stages"] = _normalized_state()["stages"]

    regulatory_node(raw_state, retriever=FakeRetriever([_chunk()], CORPUS))
    regulatory_node(enriched_state, retriever=FakeRetriever([_chunk()], CORPUS))

    assert raw_state["docs"][0]["blocks"] == blocks
    assert enriched_state["docs"][0]["blocks"] == blocks


def test_retrigger_clears_old_regulatory_findings(tmp_path):
    path = tmp_path / "guarantee.txt"
    path.write_text("保函编号 BG-2026-0001\n金额 USD 500,000.00\n适用规则 URDG 758\n", encoding="utf-8")
    state = {
        "files": [
            {
                "file_id": "F-1",
                "filename": path.name,
                "mime": "text/plain",
                "path": str(path),
                "sha256": "sha-1",
            }
        ],
        "findings": [],
        "trail": [],
        "stages": [],
    }
    retriever = FakeRetriever([_chunk()], CORPUS)

    execute_chain(state, ["parse", "agent3"], retriever=retriever)
    first_ids = [f["id"] for f in state["findings"] if f["source"] == "regulatory"]
    assert first_ids
    assert state["legal"]["input_mode"] == "raw"

    execute_chain(state, ["agent3"], retriever=retriever)
    second_ids = [f["id"] for f in state["findings"] if f["source"] == "regulatory"]

    assert second_ids == first_ids, "the old set is replaced, not appended to"
    assert len(state["stages"]) == 3, "parse once + agent3 twice"
    assert state["legal"]["input_mode"] == "raw"
