"""Optional live-model smoke (skipped unless explicitly enabled).

The default suite is deterministic and offline. This test exists for the one question a fake cannot
answer: "is the OpenAI-compatible wiring actually correct against the provider the operator uses?"

    SMART_EDIT_LIVE_LLM=1 \
    SMART_EDIT_ANSWER_BASE=http://localhost:3425/v1 \
    SMART_EDIT_ANSWER_MODEL=my-local-2k/deepseek-v4.1-flash-1017 \
    .venv/Scripts/python.exe -m pytest tests/test_live_llm_optional.py -q

It is **not** a regression test: provider drift, latency and model wording are outside this repo's
control. It asserts only contract properties (a parsed answer, citations from this retrieval, no
forbidden legal conclusion).
"""

from __future__ import annotations

import os

import pytest

from app.regulatory.answer import LLMAnswerer, OpenAIChat
from app.regulatory.node import regulatory_node
from app.regulatory.retriever import FakeRetriever

pytestmark = pytest.mark.skipif(
    os.environ.get("SMART_EDIT_LIVE_LLM") != "1",
    reason="set SMART_EDIT_LIVE_LLM=1 to call the configured provider",
)

BASE = os.environ.get("SMART_EDIT_ANSWER_BASE", "http://localhost:3425/v1")
MODEL = os.environ.get("SMART_EDIT_ANSWER_MODEL", "my-local-2k/deepseek-v4.1-flash-1017")

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
CORPUS = {
    "version": "2026-11-09.1",
    "documents": 92,
    "jurisdictions": ["AU", "CN", "US"],
    "built_at": "2026-11-09T00:00:00Z",
}


def _state() -> dict:
    return {
        "docs": [
            {
                "file_id": "F-1",
                "filename": "F-1.txt",
                "form": "plain_text",
                "blocks": [],
                "full_text": "保函编号 BG-2026-0001，金额 USD 500,000.00，适用 URDG 758。",
                "errors": [],
            }
        ],
        "fields": {
            "guarantee_amount": {"value": "USD 500,000.00"},
            "applicant_country": {"value": "CN"},
            "transaction_date": {"value": "2026-03-15"},
        },
        "business_type": "guarantee",
        "findings": [],
        "trail": [],
        "stages": [{"stage": "normalize", "agent": "agent1", "status": "done", "reason": None,
                    "produced": 3, "model_calls": 0}],
    }


def test_live_answerer_returns_supported_citations_without_a_legal_conclusion():
    answerer = LLMAnswerer(OpenAIChat(BASE, MODEL), model=MODEL)
    update = regulatory_node(
        _state(), retriever=FakeRetriever([CHUNK], CORPUS), answerer=answerer
    )

    legal = update["legal"]
    assert update["stages"][0]["status"] in {"done", "partial"}
    assert update["stages"][0]["model_calls"] == 1
    assert legal["claims"], "the provider should return at least one claim for this chunk"
    for claim in legal["claims"]:
        if claim["support"] == "supported":
            assert claim["chunk_id"] == "chunk-1"
    rendered = legal["summary"] + "\n" + "\n".join(claim["text"] for claim in legal["claims"])
    for forbidden in ("未发现问题", "无适用规则", "合法合规"):
        assert forbidden not in rendered
