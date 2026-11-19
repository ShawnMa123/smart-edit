"""Mercatoria `/v1/chat` adapter (`knowledge-statute-chat`)."""

from __future__ import annotations

import json

import httpx

from app.assistant.domain.query import analyze
from app.assistant.ports import Principal
from app.assistant.statute import StatuteRetriever

BASE = "https://statute.test"
TEXT = "第一条 独立保函是指银行或非银行金融机构作为开立人出具的付款承诺。"


def reference(index: int, *, cited: bool) -> dict:
    return {
        "chunk_id": f"chunk{index}",
        "rank": index,
        "doc_id": "cn-independent-guarantee-2020",
        "source_doc": "最高人民法院关于审理独立保函纠纷案件若干问题的规定",
        "article_id": f"cn-independent-guarantee-2020:{index}",
        "article_label": f"第{index}条",
        "jurisdiction": "CN",
        "effective_from": "2020-12-29",
        "effective_to": None,
        "score": round(1.0 - 0.1 * (index - 1), 4),
        "cited": cited,
        "text": TEXT,
    }


def chat_payload(
    *,
    status: str = "answered",
    references: int = 2,
    citations: int = 1,
    answer: str = "独立保函的定义见第一条。[chunk1]",
    coverage: dict | None = None,
) -> dict:
    refs = [reference(index, cited=index <= citations) for index in range(1, references + 1)]
    cites = [reference(index, cited=True) for index in range(1, citations + 1)]
    return {
        "answer_status": status,
        "answer": answer,
        "references": refs,
        "citations": cites,
        "chunks": [
            {"chunk_id": item["chunk_id"], "text": item["text"], "score": item["score"]}
            for item in refs
        ],
        "coverage": coverage or {"unavailable": False, "notes": []},
        "diagnostics": {"confidence": "medium", "zero_reason": None},
    }


def retriever(handler=None) -> StatuteRetriever:
    transport = httpx.MockTransport(handler or (lambda request: httpx.Response(200, json=chat_payload())))
    return StatuteRetriever(
        base_url=BASE,
        api_token="token",
        client=httpx.Client(transport=transport),
        expansions={"guarantee": ("独立保函", "URDG 758")},
    )


def test_chat_request_shape_and_mapping():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat_payload())

    plan = analyze("什么是guarantee", jurisdiction_codes=["WTO"], applicable_on="2026-01-01")
    outcome = retriever(handler).chat_detailed(Principal("u", "w"), "w", plan, None)

    assert seen["url"].endswith("/v1/chat")
    body = seen["body"]
    assert body["question"] == "什么是guarantee"
    assert "独立保函" in body["retrieval_query"] and "URDG 758" in body["retrieval_query"]
    assert body["rewrite_query"] is False
    assert body["filters"] == {"jurisdictions": ["WTO"], "as_of": "2026-01-01"}
    assert body["answer"] == {"enabled": True}
    assert body["top_k"] == 5

    assert outcome.answer_status == "answered"
    assert outcome.reason == "answered"
    assert outcome.draft and "[chunk1]" in outcome.draft
    assert outcome.cited_ids == ("chunk1",)
    assert outcome.hits == 2
    assert len(outcome.candidates) == 2

    candidate = outcome.candidates[0]
    assert candidate.source_type == "statute"
    assert candidate.chunk_id == "chunk1"
    assert candidate.locator["chunk_id"] == "chunk1"
    assert candidate.locator["doc_id"] == "cn-independent-guarantee-2020"
    assert candidate.locator["article_label"] == "第1条"
    assert candidate.locator["jurisdiction"] == "CN"
    assert candidate.locator["effective_from"] == "2020-12-29"
    assert candidate.source_version == "第1条@2020-12-29"


def test_partial_status_is_usable_with_a_caveat_status():
    outcome = retriever(lambda request: httpx.Response(200, json=chat_payload(status="partial"))).chat_detailed(
        Principal("u", "w"), "w", analyze("独立保函是什么"), None
    )

    assert outcome.answer_status == "partial"
    assert outcome.reason == "partial"
    assert outcome.candidates
    assert outcome.draft


def test_non_answered_statuses_keep_their_references_as_evidence():
    for status in ("unsupported", "unavailable", "error"):
        outcome = retriever(
            lambda request, status=status: httpx.Response(200, json=chat_payload(status=status))
        ).chat_detailed(Principal("u", "w"), "w", analyze("独立保函是什么"), None)

        assert outcome.answer_status == status
        assert outcome.reason == status
        assert outcome.candidates, "references are evidence even when the service refused"
        assert outcome.draft is None, "a refusal text must not be used as a draft"


def test_answered_without_a_reference_is_unsupported():
    outcome = retriever(
        lambda request: httpx.Response(200, json=chat_payload(references=0, citations=0))
    ).chat_detailed(Principal("u", "w"), "w", analyze("独立保函是什么"), None)

    assert outcome.answer_status == "unsupported"
    assert outcome.candidates == []


def test_transport_errors_are_mapped():
    cases = {
        401: "unauthorized",
        403: "unauthorized",
        503: "corpus_updating",
        500: "http_500",
    }
    for status, expected in cases.items():
        outcome = retriever(lambda request, status=status: httpx.Response(status)).chat_detailed(
            Principal("u", "w"), "w", analyze("独立保函是什么"), None
        )
        assert outcome.status == "failed"
        assert outcome.reason == expected
        assert outcome.answer_status == "error"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    outcome = retriever(timeout).chat_detailed(
        Principal("u", "w"), "w", analyze("独立保函是什么"), None
    )
    assert outcome.status == "failed"
    assert outcome.reason == "timeout"