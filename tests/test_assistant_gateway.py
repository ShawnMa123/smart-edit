"""Approved model gateway — Ark Responses API (knowledge-general-web / design D1)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.assistant.domain.query import analyze
from app.assistant.gateway import DoubaoGateway, ModelGatewayError
from app.assistant.ports import EvidenceBundle, EvidenceCandidate

CANDIDATE = EvidenceCandidate(
    citation_id="cite_1",
    source_type="trade_rule",
    title="URDG 758",
    source_version="v1",
    excerpt="A demand must be supported by a statement.",
    locator={"section": "20"},
    source_text="A demand must be supported by a statement.",
    source_id="KS-1",
    chunk_id="c1",
    score=3.0,
)

VALID_ANSWER = {
    "outcome": "answered",
    "language": "en",
    "support_level": "qualified",
    "claims": [
        {"id": "c1", "text": "A demand must be supported.", "kind": "fact", "citation_ids": ["cite_1"]}
    ],
    "citations": [
        {
            "id": "cite_1",
            "source_type": "trade_rule",
            "title": "URDG 758",
            "source_version": "v1",
            "locator": {"section": "20"},
        }
    ],
    "limitations": ["Synthetic demo source."],
    "clarification_questions": [],
}


def gateway(handler, model: str = "seed-1") -> DoubaoGateway:
    return DoubaoGateway(
        api_key="test-key",
        base_url="https://ark.example/api/v3",
        model=model,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        timeout=1.0,
        search_timeout=1.0,
    )


def responses_body(payload: dict) -> dict:
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(payload)}],
            }
        ]
    }


def bundle() -> EvidenceBundle:
    return EvidenceBundle([CANDIDATE])


def test_compose_uses_responses_api_without_tools():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=responses_body(VALID_ANSWER))

    composition = gateway(handler).compose(analyze("What does URDG 758 require?"), bundle(), {})

    assert seen["path"] == "/api/v3/responses"
    body = seen["body"]
    assert body["stream"] is False
    assert "tools" not in body and "tool_choice" not in body
    assert body["input"][0]["role"] == "user"
    assert all(part["type"] == "input_text" for part in body["input"][0]["content"])
    user_payload = json.loads(body["input"][0]["content"][1]["text"])
    assert user_payload["evidence"][0]["id"] == "cite_1"
    assert "source_text" not in json.dumps(user_payload)

    assert composition.answer.support_level == "qualified"
    assert composition.answer.citations[0].id == "cite_1"


def test_compose_accepts_top_level_output_text():
    body = {"output_text": json.dumps(VALID_ANSWER)}

    composition = gateway(lambda request: httpx.Response(200, json=body)).compose(
        analyze("q"), bundle(), {}
    )

    assert composition.answer.claims


def test_invalid_schema_is_a_failure_not_a_best_effort_answer():
    broken = {key: value for key, value in VALID_ANSWER.items() if key != "outcome"}

    with pytest.raises(ModelGatewayError) as error:
        gateway(lambda request: httpx.Response(200, json=responses_body(broken))).compose(
            analyze("q"), bundle(), {}
        )

    assert error.value.code == "MODEL_OUTPUT_INVALID"


def test_unknown_citation_ids_are_rejected():
    payload = json.loads(json.dumps(VALID_ANSWER))
    payload["citations"][0]["id"] = "cite_invented"
    payload["claims"][0]["citation_ids"] = ["cite_invented"]

    with pytest.raises(ModelGatewayError):
        gateway(lambda request: httpx.Response(200, json=responses_body(payload))).compose(
            analyze("q"), bundle(), {}
        )


def test_http_and_timeout_failures_are_explicit():
    with pytest.raises(ModelGatewayError) as http_error:
        gateway(lambda request: httpx.Response(500)).compose(analyze("q"), bundle(), {})
    assert http_error.value.code == "PROVIDER_HTTP_500"

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow", request=request)

    with pytest.raises(ModelGatewayError) as timeout_error:
        gateway(timeout).compose(analyze("q"), bundle(), {})
    assert timeout_error.value.code == "MODEL_TIMEOUT"


GENERAL_ANSWER = {
    "outcome": "answered",
    "language": "en",
    "support_level": "qualified",
    "claims": [
        {
            "id": "c1",
            "text": "Trading updates were published today.",
            "kind": "fact",
            "citation_ids": ["src_1"],
        }
    ],
    "citations": [
        {
            "id": "src_1",
            "source_type": "general_web",
            "title": "Example page",
            "source_version": "2026-11-16",
            "locator": {"url": "https://example.org/news"},
        }
    ],
    "limitations": [],
    "clarification_questions": [],
}


def test_general_web_uses_exactly_one_read_only_tool():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Trading updates were published today.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://example.org/news",
                                        "title": "Example page",
                                        "start_index": 0,
                                        "end_index": 12,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        )

    result = gateway(handler).general_web("今天有什么热点新闻", max_keyword=3, language="zh-CN")

    body = seen["body"]
    assert seen["path"] == "/api/v3/responses"
    assert body["tools"] == [{"type": "web_search", "max_keyword": 3}]
    assert body["stream"] is False
    assert len(result.annotations) == 1
    assert result.annotations[0]["url"] == "https://example.org/news"
    # Prose plus annotations is the real shape: one claim, citations from annotations.
    assert result.answer.outcome == "answered"
    assert result.answer.citations[0].source_type == "general_web"
    assert result.answer.citations[0].locator["url"] == "https://example.org/news"
    assert result.answer.claims[0].citation_ids == ["web_1"]


def test_general_web_accepts_a_json_answer_when_provided():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(GENERAL_ANSWER)},
                            {
                                "type": "output_text",
                                "text": "Cited text.",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://example.org/news",
                                        "title": "Example page",
                                    }
                                ],
                            },
                        ],
                    }
                ]
            },
        )

    result = gateway(handler).general_web("q", max_keyword=2)

    assert result.answer.claims[0].id == "c1"
    assert result.answer.citations[0].id == "src_1"


def test_provider_label_is_reported_for_audit():
    assert gateway(lambda request: httpx.Response(200, json=responses_body(VALID_ANSWER))).label == (
        "doubao:seed-1"
    )


def test_answer_json_wrapped_in_fences_or_prose_is_still_parsed():
    wrapped = "Here is the answer:\n\n```json\n" + json.dumps(VALID_ANSWER) + "\n```\n"

    composition = gateway(
        lambda request: httpx.Response(200, json={"output_text": wrapped})
    ).compose(analyze("q"), bundle(), {})

    assert composition.answer.claims


def test_tool_not_open_maps_to_its_own_error_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={'error': {'code': 'ToolNotOpen', 'message': 'not activated'}},
        )

    with pytest.raises(ModelGatewayError) as error:
        gateway(handler).general_web('q', max_keyword=3)

    assert error.value.code == 'TOOL_NOT_OPEN'
