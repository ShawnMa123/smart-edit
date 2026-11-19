"""General web channel (knowledge-general-web / design D2–D5)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.assistant.domain.query import analyze
from app.assistant.egress import EgressPolicy
from app.assistant.gateway import DoubaoGateway
from app.assistant.pipeline import (
    FixtureComposer,
    GENERAL_WEB_LIMITATION_EN,
    review_general_answer,
)
from app.assistant.ports import EvidenceCandidate
from app.assistant.schemas import Answer, Citation, Claim, RunCreate
from app.assistant.settings import AssistantSettings
from app.assistant.statute import StatuteOutcome
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


def client_for(tmp_path: Path, gateway, *, general: bool = True, retriever=None):
    services = make_services(
        tmp_path,
        gateway=gateway,
        egress=policy(),
        settings=settings(general=general),
        retriever=retriever,
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

def test_general_answer_keeps_any_linked_source_and_stays_unverified(tmp_path):
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
    # Any publicly reachable link is citable on this channel; the unverified label carries the trust.
    assert len(citations) == 2
    assert {citation["locator"]["domain"] for citation in citations} == {
        "iccwbo.org",
        "evil.example",
    }
    assert all(citation["source_type"] == "general_web" for citation in citations)
    assert citations[0]["locator"]["retrieved_at"]
    assert result["support_level"] == "qualified"  # never "strong" for web evidence
    assert GENERAL_WEB_LIMITATION_EN in result["limitations"]
    assert result["retrieval"][0]["status"] == "ok"
    assert result["retrieval"][0]["detail"] == "general_web"

    run_id = client.get(
        f"/assistant/sessions/{session_row['id']}/messages", headers=headers()
    ).json()["items"][-1]["run_id"]
    events = [row["event_type"] for row in services.store.list_audit(run_id)]
    # Nothing was dropped, so the drop audit is not written at all.
    assert "web_evidence_dropped" not in events


def test_general_answer_without_a_resolvable_link_is_insufficient(tmp_path):
    payload = {
        "outcome": "answered",
        "language": "en",
        "support_level": "qualified",
        "claims": [
            {"id": "c1", "text": "Escrow is a third-party holding arrangement.",
             "kind": "fact", "citation_ids": ["cite_1"]}
        ],
        "citations": [
            {"id": "cite_1", "source_type": "general_web", "title": "Some page",
             "source_version": "", "locator": {}}
        ],
        "limitations": [],
        "clarification_questions": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=prose_response(json.dumps(payload), []))

    client, services = client_for(tmp_path, doubao(handler))
    session_row = session(client)
    result = run(client, session_row["id"])["result"]

    assert result["outcome"] == "insufficient_evidence"
    assert result["support_level"] == "insufficient"
    assert result["claims"] == []
    assert result["citations"] == []
    assert any("no citation was produced" in note.lower() for note in result["limitations"])
    assert not any("approved domain" in note.lower() for note in result["limitations"])

    run_id = client.get(
        f"/assistant/sessions/{session_row['id']}/messages", headers=headers()
    ).json()["items"][-1]["run_id"]
    dropped = [
        json.loads(row["payload_json"])
        for row in services.store.list_audit(run_id)
        if row["event_type"] == "web_evidence_dropped"
    ]
    assert dropped and "<no-link>" in dropped[0]["hosts"]


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
    client, services = client_for(tmp_path, gateway, retriever=NoLocalRetriever())
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
    client, services = client_for(tmp_path, gateway, retriever=NoLocalRetriever())
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


def test_failed_fallback_is_reported_without_a_fake_conclusion(tmp_path):
    gateway = two_mode_gateway(
        httpx.Response(404, json={"error": {"code": "ToolNotOpen", "message": "not activated"}})
    )
    client, services = client_for(tmp_path, gateway, retriever=NoLocalRetriever())
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


# --- RAG-first fallback (`knowledge-rag-first-fallback`) ------------------------------------


class StubStatute:
    def __init__(self, outcome: StatuteOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def search(self, *args, **kwargs):
        return self.outcome.candidates

    def search_detailed(self, *args, **kwargs):
        self.calls += 1
        return self.outcome

    def chat_detailed(self, *args, **kwargs):
        return self.search_detailed(*args, **kwargs)

    def health(self):
        return {"reachable": True, "documents": 1, "chunks": 1, "index_version": "test"}


class HybridGateway:
    """Fixture composition plus the real (mocked) web tool, so local evidence is possible."""

    supports_tool_search = True

    def __init__(self, web: DoubaoGateway) -> None:
        self.web = web

    def compose(self, plan, bundle, context):
        return FixtureComposer().compose(plan, bundle, context)

    def general_web(self, question, *, max_keyword, language="en"):
        return self.web.general_web(question, max_keyword=max_keyword, language=language)


class NoLocalRetriever:
    def search(self, *args, **kwargs):
        return []


def statute_hit() -> EvidenceCandidate:
    body = "第五条 独立保函载明适用《见索即付保函统一规则》等交易示范规则的，人民法院应予支持。"
    return EvidenceCandidate(
        citation_id="cite_statute_1",
        source_type="statute",
        title="最高人民法院关于审理独立保函纠纷案件若干问题的规定",
        source_version="第五条",
        excerpt=body,
        locator={
            "doc_id": "cn-independent-guarantee-2020",
            "article_label": "第五条",
            "jurisdiction": "CN",
            "effective_from": "2020-12-29",
        },
        source_text=body,
        source_id="cn-independent-guarantee-2020",
        chunk_id="1008bee7f0c0b65f",
    )


def client_with_statute(tmp_path, *, outcome, web, egress=None, retriever=None):
    services = make_services(
        tmp_path,
        gateway=HybridGateway(web),
        egress=egress or policy(),
        settings=settings(),
        statute=StubStatute(outcome),
        retriever=retriever,
    )
    return make_client(tmp_path, services=services), services


def test_rag_empty_falls_back_to_web_even_when_local_answered(tmp_path):
    calls: list[str] = []
    web = two_mode_gateway(
        responses_with("Web answer", [allowed_page("https://iccwbo.org/news/2")]), calls=calls
    )
    client, services = client_with_statute(
        tmp_path, outcome=StatuteOutcome(status="ok", reason="zero:no_match"), web=web
    )

    run_result = run(client, session(client)["id"], question="What is a demand guarantee?")
    result = run_result["result"]

    assert calls == ["tools"]
    assert result["route"] == "general_web"
    assert result["web"]["reason"] == "rag_empty"
    assert [c["source_type"] for c in result["citations"]] == ["general_web"]
    allowed = [
        json.loads(row["payload_json"])
        for row in services.store.list_audit(run_result["id"])
        if row["event_type"] == "egress_allowed"
    ]
    assert any(payload.get("purpose") == "tool_search" for payload in allowed)


def test_rag_hits_suppress_the_web_search(tmp_path):
    calls: list[str] = []
    web = two_mode_gateway(
        responses_with("Web answer", [allowed_page("https://iccwbo.org/news/3")]), calls=calls
    )
    client, services = client_with_statute(
        tmp_path,
        outcome=StatuteOutcome([statute_hit()], status="ok", reason="low_confidence", hits=1),
        web=web,
    )

    result = run(client, session(client)["id"], question="What is a demand guarantee?")["result"]

    assert calls == []
    assert result["route"] == "statute"
    assert [c["source_type"] for c in result["citations"]] == ["statute"]
    assert any("reference only" in item.lower() for item in result["limitations"])


def test_an_empty_web_result_keeps_the_local_answer_and_says_so(tmp_path):
    calls: list[str] = []
    web = two_mode_gateway(responses_with(json.dumps(INSUFFICIENT_JSON)), calls=calls)
    client, services = client_with_statute(
        tmp_path, outcome=StatuteOutcome(status="ok", reason="zero:no_match"), web=web
    )

    result = run(client, session(client)["id"], question="What is a demand guarantee?")["result"]

    assert calls == ["tools"]
    assert result["route"] == "published"
    assert result["citations"], "the local answer must still be delivered"
    assert any(
        "web search returned no usable result" in item.lower() for item in result["limitations"]
    )


def test_no_evidence_anywhere_is_stated_without_citations(tmp_path):
    calls: list[str] = []
    web = two_mode_gateway(responses_with(json.dumps(INSUFFICIENT_JSON)), calls=calls)
    client, services = client_with_statute(
        tmp_path,
        outcome=StatuteOutcome(status="ok", reason="zero:no_match"),
        web=web,
        retriever=NoLocalRetriever(),
    )

    result = run(client, session(client)["id"], question="What is a demand guarantee?")["result"]

    assert result["route"] == "none"
    assert not result["citations"]
    assert any(
        "neither the knowledge base nor the web" in item.lower() for item in result["limitations"]
    )


def test_the_automatic_fallback_is_blocked_by_the_egress_policy(tmp_path):
    calls: list[str] = []
    web = two_mode_gateway(
        responses_with("Web answer", [allowed_page("https://iccwbo.org/news/4")]), calls=calls
    )
    client, services = client_with_statute(
        tmp_path,
        outcome=StatuteOutcome(status="ok", reason="zero:no_match"),
        web=web,
        egress=EgressPolicy.from_file(Path("/definitely/not/here.yaml")),
    )

    run_result = run(client, session(client)["id"], question="What is a demand guarantee?")
    result = run_result["result"]

    assert calls == []
    web_layers = [layer for layer in result["retrieval"] if layer["layer"] == "web"]
    assert web_layers and web_layers[0]["status"] == "blocked"
    assert any("blocked" in item.lower() for item in result["limitations"])
    blocked = [
        json.loads(row["payload_json"])
        for row in services.store.list_audit(run_result["id"])
        if row["event_type"] == "egress_blocked"
    ]
    assert any(payload.get("purpose") == "tool_search" for payload in blocked)
