"""Optional LLM answerer: citations, fallback, and no fabrication."""

from __future__ import annotations

import json

from app.regulatory.answer import LLMAnswerer, resolve_answerer
from app.regulatory.node import regulatory_node
from app.regulatory.retriever import FakeRetriever
from tests.helpers import make_doc

CORPUS = {
    "version": "2026-11-09.1",
    "documents": 92,
    "jurisdictions": ["CN"],
    "built_at": "2026-11-09T00:00:00Z",
}
CHUNK = {
    "chunk_id": "chunk-1",
    "doc_id": "cn-customs-guarantee-2018",
    "source_doc": "中华人民共和国海关事务担保条例",
    "title": "海关事务担保条例",
    "text": "第二条 当事人向海关申请提供担保，承诺履行法律义务。",
    "score": 0.9,
    "articles": ["第二条"],
    "effective_from": "2018-03-19",
    "jurisdictions": ["CN"],
    "applies_to": ["guarantee"],
}


def _state() -> dict:
    return {
        "docs": [make_doc("保函编号 BG-2026-0001，适用 URDG 758。")],
        "findings": [],
        "trail": [],
        "stages": [],
    }


def _retriever() -> FakeRetriever:
    return FakeRetriever([CHUNK], CORPUS)


def test_llm_answerer_uses_verbatim_claim_and_records_llm_call():
    def chat(messages):
        assert any("只允许逐字引用" in message["content"] for message in messages)
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "第二条 当事人向海关申请提供担保，承诺履行法律义务。",
                        "chunk_id": "chunk-1",
                        "kind": "applicable_rule",
                    }
                ],
                "summary": "检索到 1 条相关条文；仅指出适用规则与差异候选，不构成法律结论。",
            },
            ensure_ascii=False,
        )

    update = regulatory_node(
        _state(), retriever=_retriever(), answerer=LLMAnswerer(chat, model="fake-model")
    )

    legal = update["legal"]
    assert legal["claims"][0]["chunk_id"] == "chunk-1"
    assert legal["claims"][0]["support"] == "supported"
    assert update["stages"][0]["model_calls"] == 1
    llm_entries = [entry for entry in update["trail"] if entry["op"] == "llm_call"]
    assert llm_entries and llm_entries[0]["model"] == "fake-model"
    assert llm_entries[0]["prompt_hash"]


def test_llm_answerer_falls_back_to_extractive_on_error():
    def broken(messages):
        raise RuntimeError("provider down")

    update = regulatory_node(
        _state(), retriever=_retriever(), answerer=LLMAnswerer(broken, model="fake-model")
    )

    assert update["legal"]["claims"][0]["support"] == "supported"
    assert update["stages"][0]["model_calls"] == 1
    fallback = [
        entry
        for entry in update["trail"]
        if entry["op"] == "pass" and "llm_failed" in str(entry["detail"].get("reason"))
    ]
    assert fallback


def test_llm_answerer_fabricated_chunk_id_is_downgraded():
    def chat(messages):
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "第二条 当事人向海关申请提供担保。",
                        "chunk_id": "made-up",
                        "kind": "applicable_rule",
                    }
                ],
                "summary": "检索到 1 条相关条文。",
            },
            ensure_ascii=False,
        )

    update = regulatory_node(
        _state(), retriever=_retriever(), answerer=LLMAnswerer(chat, model="fake-model")
    )

    claims = update["legal"]["claims"]
    assert len(claims) == 1, "downgrade must not delete the claim"
    assert claims[0]["support"] == "insufficient"
    assert claims[0]["chunk_id"] is None


def test_llm_risk_claim_becomes_a_cited_finding():
    text = "第二条 当事人向海关申请提供担保，承诺履行法律义务。"

    def chat(messages):
        return json.dumps(
            {"claims": [{"text": text, "chunk_id": "chunk-1", "kind": "risk"}], "summary": "检索到 1 条相关条文。"},
            ensure_ascii=False,
        )

    update = regulatory_node(
        _state(), retriever=_retriever(), answerer=LLMAnswerer(chat, model="fake-model")
    )

    hits = [finding for finding in update["findings"] if finding["rule_id"] == "REG-RISK"]
    assert len(hits) == 1
    assert hits[0]["citation"] == "chunk-1"
    assert hits[0]["evidence"] == text
    assert hits[0]["blocking"] is False
    assert hits[0]["field_keys"] == []


def test_resolve_answerer_defaults_to_extractive_and_can_select_llm():
    from app.regulatory.answer import ExtractiveAnswerer

    assert isinstance(resolve_answerer({}), ExtractiveAnswerer)
    llm = resolve_answerer(
        {
            "SMART_EDIT_ANSWERER": "llm",
            "SMART_EDIT_ANSWER_BASE": "http://127.0.0.1:9/v1",
            "SMART_EDIT_ANSWER_MODEL": "fake",
        }
    )
    assert isinstance(llm, LLMAnswerer)
