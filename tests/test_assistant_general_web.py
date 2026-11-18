"""General web channel (knowledge-general-web / design D2–D5)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.assistant.domain.query import analyze
from app.assistant.egress import EgressPolicy
from app.assistant.gateway import DoubaoGateway
from app.assistant.pipeline import GENERAL_WEB_LIMITATION_EN, review_general_answer
from app.assistant.schemas import Answer, Citation, Claim, RunCreate
from app.assistant.settings import AssistantSettings
from tests.assistant_helpers import WORKSPACE, headers, make_client, make_service, make_services

QUESTION = "What happened in the trade finance market today?"


def allowed_page(url: str, title: str = "Today's trade update") -> dict:
    return {"type": "url_citation", "url": url, "title": title, "start_index": 0, "end_index": 10}


def prose_response(text: str, annotations: list[dict]) -> dict:
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text, "annotations": annotations}],
            }
        ]
    }


def doubao(handler, *, search_timeout: float = 1.0) -> DoubaoGateway:
    return DoubaoGateway(
        api_key="k",
        base_url="https://ark.example/api/v3",
        model="seed-1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        timeout=1.0,
        search_timeout=search_timeout,
    )


def settings(*, general: bool = True) -> AssistantSettings:
    return AssistantSettings(
        model="doubao:seed-1",
        api_key="k",
        approved_processor=True,
        general_web=general,
        web_search_max_keyword=3,
    )


def policy() -> EgressPolicy:
    return EgressPolicy(version="general-test", allowed_domains=["iccwbo.org"])


def client_for(tmp_path: Path, gateway, *, general: bool = True):
    services = make_services(
        tmp_path, gateway=gateway, egress=policy(), settings=settings(general=general)
    )
    return make_client(tmp_path, services=services), services


def session(client) -> dict:
    response = client.post(
        "/assistant/sessions",
        json={"workspace_id": WORKSPACE, "locale": "en"},
        headers=headers("user_a", "sess"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def run(client, session_id: str, *, web: bool = True, question: str = QUESTION) -> dict:
    accepted = client.post(
        f"/assistant/sessions/{session_id}/runs",
        json={"question": question, "web_search": web},
        headers=headers("user_a", "run-1"),
    )
    assert accepted.status_code == 202, accepted.text
    return client.get(f"/assistant/runs/{accepted.json()['id']}", headers=headers()).json()


def test_general_route_requires_every_condition(tmp_path):
    service = make_service(
        tmp_path,
        gateway=doubao(lambda request: httpx.Response(200, json=prose_response("x", []))),
        egress=policy(),
        settings=settings(),
    )
    scope = analyze(QUESTION)
    handoff = analyze("帮我改写这段条款")
    rule = analyze("What does URDG 758 require for claims?")
    on = RunCreate(question=QUESTION, web_search=True)
    off = RunCreate(question=QUESTION)

    assert scope.intent == "out_of_scope" and scope.handoff_target is None
    assert service._general_route(scope, on) is True
    assert service._general_route(scope, off) is False
    assert service._general_route(handoff, on) is False
    assert service._general_route(rule, on) is False

    disabled = make_service(
        tmp_path,
        gateway=doubao(lambda request: httpx.Response(200, json=prose_response("x", []))),
        egress=policy(),
        settings=settings(general=False),
    )
    assert disabled._general_route(scope, on) is False

def test_general_answer_keeps_only_approved_domains_and_is_capped(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"] == [{"type": "web_search", "max_keyword": 3}]
        return httpx.Response(
            200,
            json=prose_response(
                "Two market updates were published today.",
                [
                    allowed_page("https://iccwbo.org/news/1"),
                    allowed_page("https://evil.example/news/2", "Unapproved page"),
                ],
            ),
        )

    client, services = client_for(tmp_path, doubao(handler))
    session_row = session(client)
    result = run(client, session_row["id"])["result"]

    citations = result["citations"]
    assert len(citations) == 1
    assert citations[0]["source_type"] == "general_web"
    assert citations[0]["locator"]["domain"] == "iccwbo.org"
    assert citations[0]["locator"]["retrieved_at"]
    assert result["support_level"] == "qualified"
    assert GENERAL_WEB_LIMITATION_EN in result["limitations"]
    assert result["retrieval"][0]["status"] == "ok"
    assert result["retrieval"][0]["detail"] == "general_web"

    run_id = client.get(
        f"/assistant/sessions/{session_row['id']}/messages", headers=headers()
    ).json()["items"][-1]["run_id"]
    events = [row["event_type"] for row in services.store.list_audit(run_id)]
    assert "web_evidence_dropped" in events


def test_general_answer_without_approved_citation_is_insufficient(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=prose_response(
                "Only unapproved sources were found.",
                [allowed_page("https://evil.example/news/2", "Unapproved page")],
            ),
        )

    client, _ = client_for(tmp_path, doubao(handler))
    result = run(client, session(client)["id"])["result"]

    assert result["outcome"] == "insufficient_evidence"
    assert result["support_level"] == "insufficient"
    assert result["claims"] == []
    assert result["citations"] == []
    assert any("approved domain" in limitation.lower() for limitation in result["limitations"])


def test_general_web_failure_is_stated_not_faked(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client, _ = client_for(tmp_path, doubao(handler))
    result = run(client, session(client)["id"])["result"]

    assert result["outcome"] == "unable_to_assess"
    assert result["retrieval"][0]["status"] == "failed"
    assert any("did not complete" in limitation.lower() for limitation in result["limitations"])


def test_minimal_review_drops_claims_with_unknown_citations():
    answer = Answer(
        outcome="answered",
        language="en",
        support_level="qualified",
        claims=[
            Claim(id="c1", text="known", kind="fact", citation_ids=["web_1"]),
            Claim(id="c2", text="unknown", kind="fact", citation_ids=["web_9"]),
        ],
        citations=[
            Citation(
                id="web_1",
                source_type="general_web",
                title="t",
                source_version="v",
                locator={"url": "https://iccwbo.org/x"},
            )
        ],
    )

    reviewed, removed = review_general_answer(answer, {"web_1"})

    assert removed == 1
    assert [claim.id for claim in reviewed.claims] == ["c1"]
    assert [citation.id for citation in reviewed.citations] == ["web_1"]

INSUFFICIENT_JSON = {
    "outcome": "insufficient_evidence",
    "language": "en",
    "support_level": "insufficient",
    "claims": [],
    "citations": [],
    "limitations": ["The published corpus does not define this term."],
    "clarification_questions": [],
}

HANDOFF_JSON = {
    "outcome": "needs_handoff",
    "language": "en",
    "support_level": "not_applicable",
    "claims": [],
    "citations": [],
    "limitations": ["This request must be handed off to automation."],
    "clarification_questions": [],
    "handoff_target": "automation",
}


def responses_with(text: str, annotations: list[dict] | None = None) -> dict:
    content = {"type": "output_text", "text": text}
    if annotations is not None:
        content["annotations"] = annotations
    return {"output": [{"type": "message", "content": [content]}]}


def two_mode_gateway(tools_response, *, compose_answer=INSUFFICIENT_JSON, calls=None):
    """Compose returns a fixed answer; the tool call returns `tools_response`."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls is not None:
            calls.append("tools" if body.get("tools") else "compose")
        if body.get("tools"):
            if isinstance(tools_response, httpx.Response):
                return tools_response
            return httpx.Response(200, json=tools_response)
        return httpx.Response(200, json=responses_with(json.dumps(compose_answer)))

    return doubao(handler)


def test_in_scope_insufficient_falls_back_to_general_web(tmp_path):
    calls: list[str] = []
    gateway = two_mode_gateway(
        responses_with(
            "A demand guarantee is a bank undertaking to pay on a compliant demand.",
            [allowed_page("https://iccwbo.org/news/guarantee")],
        ),
        calls=calls,
    )
    client, services = client_for(tmp_path, gateway)
    result = run(client, session(client)["id"], question="What is a demand guarantee?")["result"]

    assert calls == ["compose", "tools"]
    assert result["route"] == "general_web"
    assert result["web"]["status"] == "ok"
    assert [c["source_type"] for c in result["citations"]] == ["general_web"]
    assert any("published corpus could not answer" in item.lower() for item in result["limitations"])


def test_fallback_is_not_used_without_the_toggle(tmp_path):
    calls: list[str] = []
    gateway = two_mode_gateway(
        responses_with("web answer", [allowed_page("https://iccwbo.org/news/1")]),
        calls=calls,
    )
    client, services = client_for(tmp_path, gateway)
    result = run(
        client, session(client)["id"], web=False, question="What is a demand guarantee?"
    )["result"]

    assert calls == ["compose"]
    assert result["outcome"] == "insufficient_evidence"
    assert result["web"]["status"] == "off"


def test_handoff_questions_never_fall_back(tmp_path):
    calls: list[str] = []
    gateway = two_mode_gateway(
        responses_with("web answer", [allowed_page("https://iccwbo.org/news/1")]),
        compose_answer=HANDOFF_JSON,
        calls=calls,
    )
    client, services = client_for(tmp_path, gateway)
    result = run(client, session(client)["id"], web=True, question="帮我改写这段条款")["result"]

    assert "tools" not in calls
    assert result["route"] == "handoff"


def test_routing_outcomes_ignore_the_external_model(tmp_path):
    calls: list[str] = []
    gateway = two_mode_gateway(
        responses_with(json.dumps(INSUFFICIENT_JSON)), calls=calls
    )
    client, services = client_for(tmp_path, gateway)
    session_id = session(client)["id"]

    cases = (
        ("route-handoff", "帮我改写这段条款", "needs_handoff"),
        ("route-clarify", "URDG 758 是否适用于德国？", "needs_clarification"),
        ("route-scope", "今天天气怎么样", "unable_to_assess"),
    )
    for key, question, expected in cases:
        accepted = client.post(
            f"/assistant/sessions/{session_id}/runs",
            json={"question": question, "web_search": False},
            headers=headers("user_a", key),
        )
        assert accepted.status_code == 202, accepted.text
        result = client.get(
            f"/assistant/runs/{accepted.json()['id']}", headers=headers()
        ).json()["result"]

        assert result["outcome"] == expected, (question, result)
        if expected == "needs_handoff":
            assert result["handoff_target"] == "automation"
            assert result["route"] == "handoff"
        if expected == "needs_clarification":
            assert result["clarification_questions"]

    assert calls == []


def test_failed_fallback_keeps_the_corpus_answer_and_reports_why(tmp_path):
    gateway = two_mode_gateway(
        httpx.Response(404, json={"error": {"code": "ToolNotOpen", "message": "not activated"}})
    )
    client, services = client_for(tmp_path, gateway)
    result = run(client, session(client)["id"], web=True, question="What is a demand guarantee?")[
        "result"
    ]

    assert result["outcome"] == "insufficient_evidence"
    assert result["route"] == "none"
    web_layers = [layer for layer in result["retrieval"] if layer["layer"] == "web"]
    assert web_layers and web_layers[0]["status"] == "failed"
    assert result["web"]["reason"] == "TOOL_NOT_OPEN"
    assert any("not enabled for this account" in item.lower() for item in result["limitations"])
    assert all("skipped for this request" not in item.lower() for item in result["limitations"])
