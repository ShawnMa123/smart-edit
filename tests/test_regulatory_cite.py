"""Citation downgrade, entity extraction and query-builder tests."""

from __future__ import annotations

import copy

from app.regulatory.cite_check import cite_check
from app.regulatory.entities import extract_entities
from app.regulatory.query import build_query
from tests.helpers import make_doc

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


def test_fabricated_chunk_id_downgraded_not_deleted():
    claims = [
        {
            "text": "第464条 保函金额 USD 500,000.00",
            "chunk_id": "made-up",
            "kind": "applicable_rule",
            "support": "supported",
        }
    ]
    out, trail = cite_check(claims, [_chunk()])

    assert len(out) == 1, "a claim is never deleted"
    assert out[0]["support"] == "insufficient"
    assert out[0]["chunk_id"] is None
    assert trail and trail[0]["detail"]["reason"] == "chunk_id_not_in_retrieved"
    assert trail[0]["op"] == "transform"


def test_entity_missing_in_cited_chunk_keeps_citation():
    claims = [
        {
            "text": "保函金额 USD 999,999.00",
            "chunk_id": "chunk-1",
            "kind": "applicable_rule",
            "support": "supported",
        }
    ]
    out, trail = cite_check(claims, [_chunk()])

    assert out[0]["support"] == "insufficient"
    assert out[0]["chunk_id"] == "chunk-1", "the citation stays so a human can inspect the mismatch"
    reasons = [entry["detail"]["reason"] for entry in trail]
    assert "entity_not_in_chunk" in reasons
    entity_entry = next(entry for entry in trail if entry["detail"]["reason"] == "entity_not_in_chunk")
    assert "USD 999,999.00" in entity_entry["detail"]["missing_entities"]


def test_supported_claim_survives_cite_check():
    claims = [
        {
            "text": "第464条 保函金额 USD 500,000.00 应当以书面形式约定",
            "chunk_id": "chunk-1",
            "kind": "applicable_rule",
            "support": "supported",
        }
    ]
    out, trail = cite_check(claims, [_chunk()])

    assert out[0]["support"] == "supported"
    assert out[0]["chunk_id"] == "chunk-1"
    assert trail == []


def test_paraphrased_claim_is_downgraded_but_kept():
    claims = [
        {
            "text": "保函必须以书面形式约定金额",
            "chunk_id": "chunk-1",
            "kind": "applicable_rule",
            "support": "supported",
        }
    ]
    out, trail = cite_check(claims, [_chunk()])

    assert len(out) == 1
    assert out[0]["support"] == "insufficient"
    assert out[0]["chunk_id"] == "chunk-1"
    assert trail[0]["detail"]["reason"] == "text_not_in_chunk"


def test_build_query_raw_is_never_empty_and_has_three_queries():
    queries, filters = build_query(_state(""), "raw")

    assert 3 <= len(queries) <= 5
    assert queries
    assert filters["as_of"] is None


def test_extract_entities_covers_contract_examples():
    entities = extract_entities(
        "USD 500,000.00 / USD 500K / 500000 美元，2026-03-15，CN，新加坡，URDG 758，第464条，§ 464"
    )

    for expected in (
        "USD 500,000.00",
        "USD 500K",
        "500000 美元",
        "2026-03-15",
        "CN",
        "新加坡",
        "URDG 758",
        "第464条",
        "§ 464",
    ):
        assert expected in entities
