"""Retrieval layers + egress wiring (knowledge-retrieval-layers / knowledge-egress-policy)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.assistant.audit_events import EGRESS_ALLOWED, WEB_SEARCH_FAILED
from app.assistant.domain.query import analyze
from app.assistant.egress import EgressPolicy
from app.assistant.pipeline import WEB_BLOCKED_EN, WEB_INCOMPLETE_EN, apply_layer_policy
from app.assistant.ports import EvidenceBundle, EvidenceCandidate, Principal
from app.assistant.retrieval import (
    FixtureWebSearch,
    RagHttpAdapter,
    RetrievalError,
    WebPage,
    merge_layers,
    web_candidates,
)
from app.assistant.schemas import Answer, Citation, Claim
from app.assistant.settings import AssistantSettings
from tests.assistant_helpers import (
    WORKSPACE,
    headers,
    make_client,
    make_services,
    register_snapshot,
)

QUESTION = "What does URDG 758 article 20 require for claims?"

PAGE = WebPage(
    url="https://iccwbo.org/opinions/demand-guarantee-claims",
    title="ICC guidance on demand guarantee claims",
    text=(
        "An ICC guidance note states that a claim under a demand guarantee must be examined "
        "within five business days of presentation, and that the beneficiary must be told of any "
        "discrepancy in writing."
    ),
    rank=1,
    provider="fixture",
)


def policy(**overrides) -> EgressPolicy:
    values = {"version": "layers-test", "allowed_domains": ["iccwbo.org"]}
    values.update(overrides)
    return EgressPolicy(**values)


def settings() -> AssistantSettings:
    return AssistantSettings(web="fixture", approved_processor=False)


def _client(tmp_path: Path, **kwargs):
    services = make_services(tmp_path, egress=policy(), settings=settings(), **kwargs)
    return make_client(tmp_path, services=services), services


def _session(client, body: dict | None = None, key: str = "sess") -> dict:
    response = client.post(
        "/assistant/sessions",
        json=body or {"workspace_id": WORKSPACE, "locale": "en"},
        headers=headers("user_a", key),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run(client, session_id: str, question: str, key: str = "run-1", **kwargs) -> dict:
    response = client.post(
        f"/assistant/sessions/{session_id}/runs",
        json={"question": question, **kwargs},
        headers=headers("user_a", key),
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    return client.get(f"/assistant/runs/{run_id}", headers=headers()).json()


def _events(store, run_id: str) -> list[str]:
    return [row["event_type"] for row in store.list_audit(run_id)]


def test_web_layer_is_off_by_default(tmp_path):
    client, services = _client(tmp_path, web=FixtureWebSearch([PAGE]))
    session = _session(client)
    run = _run(client, session["id"], QUESTION)

    result = run["result"]
    assert [layer["layer"] for layer in result["retrieval"]] == ["local"]
    assert all(citation["source_type"] != "approved_web" for citation in result["citations"])
    assert EGRESS_ALLOWED not in _events(services.store, run["id"])


def test_approved_web_evidence_carries_its_metadata_and_redacts_the_message(tmp_path):
    client, services = _client(tmp_path, web=FixtureWebSearch([PAGE]))
    session = _session(client)
    run = _run(client, session["id"], QUESTION, web_search=True)

    result = run["result"]
    layers = {layer["layer"]: layer for layer in result["retrieval"]}
    assert layers["web"]["status"] == "ok"
    assert layers["web"]["retrieved_at"] == "2026-11-16T00:00:00Z"

    web_citations = [c for c in result["citations"] if c["source_type"] == "approved_web"]
    assert web_citations, result["citations"]
    locator = web_citations[0]["locator"]
    assert locator["domain"] == "iccwbo.org"
    assert locator["url"] == PAGE.url
    assert locator["retrieved_at"] == "2026-11-16T00:00:00Z"
    assert EGRESS_ALLOWED in _events(services.store, run["id"])

    messages = client.get(
        f"/assistant/sessions/{session['id']}/messages", headers=headers()
    ).json()["items"]
    assert messages[0]["role"] == "user"
    assert messages[0]["visibility"] == "redacted"


def test_unapproved_domains_are_dropped_not_cited(tmp_path):
    rogue = WebPage(
        url="https://evil.example/urdg-758",
        title="URDG 758 claims advice",
        text="URDG 758 article 20 claims advice from an unapproved domain.",
    )
    client, services = _client(tmp_path, web=FixtureWebSearch([rogue]))
    session = _session(client)
    run = _run(client, session["id"], QUESTION, web_search=True)

    assert all(citation["source_type"] != "approved_web" for citation in run["result"]["citations"])


def test_an_incidental_word_selection_still_reads_the_published_definition(tmp_path):
    """Regression for run_c12c9af814d5.

    The demo asked "guarantee 在贸易里说什么" while the word "guarantee" was selected. The run
    was routed to document_explanation, so the only evidence was that nine-character slice, the
    corpus definition was never retrieved, and the answer could only be insufficient_evidence.
    """
    text = (
        "Payment terms: the buyer shall provide a guarantee from an issuing bank before shipment."
    )
    client, _ = _client(tmp_path, web=FixtureWebSearch([PAGE]))
    snapshot = register_snapshot(client, text=text)
    session = _session(
        client,
        {
            "workspace_id": WORKSPACE,
            "locale": "zh-CN",
            "document_id": "doc-1",
            "snapshot_id": snapshot["id"],
        },
    )
    start = text.index("guarantee")
    selection = {
        "node_id": "block_0",
        "start_offset": start,
        "end_offset": start + len("guarantee"),
        "selected_text": "guarantee",
    }
    run = _run(client, session["id"], "guarantee 在贸易里说什么", selection=selection)

    result = run["result"]
    assert result["outcome"] == "answered"
    assert result["citations"], result["limitations"]
    assert all(citation["source_type"] == "trade_rule" for citation in result["citations"])
    assert all(layer["detail"] != "document_snapshot" for layer in result["retrieval"])
    assert any("保函" in claim["text"] for claim in result["claims"])


def test_selection_text_blocks_the_web_layer(tmp_path):
    text = (
        "This guarantee is governed by URDG 758 and payable on first written demand at the "
        "counter of the issuing bank."
    )
    client, services = _client(tmp_path, web=FixtureWebSearch([PAGE]))
    snapshot = register_snapshot(client, text=text)
    session = _session(
        client,
        {
            "workspace_id": WORKSPACE,
            "locale": "en",
            "document_id": "doc-1",
            "snapshot_id": snapshot["id"],
        },
    )
    start = text.index("URDG 758 and payable")
    selection = {
        "node_id": "block_0",
        "start_offset": start,
        "end_offset": start + 58,
        "selected_text": text[start : start + 58],
    }
    run = _run(
        client,
        session["id"],
        f"Explain this passage: {selection['selected_text']}",
        selection=selection,
        web_search=True,
    )

    layers = {layer["layer"]: layer for layer in run["result"]["retrieval"]}
    assert layers["web"]["status"] == "blocked"
    assert layers["web"]["detail"] == "contains_selection"
    assert WEB_BLOCKED_EN in run["result"]["limitations"]
    assert all(citation["source_type"] != "approved_web" for citation in run["result"]["citations"])


def test_web_failure_is_reported_instead_of_claiming_verification(tmp_path):
    client, services = _client(
        tmp_path, web=FixtureWebSearch([PAGE], error=RetrievalError("web_search_timeout"))
    )
    session = _session(client)
    run = _run(client, session["id"], QUESTION, web_search=True)

    layers = {layer["layer"]: layer for layer in run["result"]["retrieval"]}
    assert layers["web"]["status"] == "failed"
    assert layers["web"]["detail"] == "web_search_timeout"
    assert WEB_INCOMPLETE_EN in run["result"]["limitations"]
    assert WEB_SEARCH_FAILED in _events(services.store, run["id"])


def test_merge_layers_dedupes_the_same_source():
    candidate = EvidenceCandidate(
        citation_id="cite_a",
        source_type="approved_web",
        title="t",
        source_version="v",
        excerpt="e",
        locator={"url": "https://iccwbo.org/x"},
        source_id="https://iccwbo.org/x",
        chunk_id="c1",
        score=1.0,
    )
    duplicate = EvidenceCandidate(**{**candidate.__dict__, "score": 2.0})
    local = EvidenceCandidate(
        citation_id="cite_b",
        source_type="trade_rule",
        title="rule",
        source_version="v1",
        excerpt="e",
        locator={},
        source_id="KS-1",
        chunk_id="k1",
        score=3.0,
    )

    merged = merge_layers([local], [candidate, duplicate])

    assert len(merged) == 2
    assert merged[0].source_type == "trade_rule"  # local first on ties/authority
    assert merged[1].score == 2.0  # the higher-scoring duplicate wins


def test_web_candidates_only_keep_allowed_domains():
    outcome = web_candidates(
        [PAGE],
        {"urdg", "claims"},
        allowed_domains=["example.org"],
        retrieved_at="2026-01-01T00:00:00Z",
    )

    assert outcome.candidates == []
    assert outcome.dropped and outcome.dropped[0].startswith("domain_not_allowed")
def test_rag_adapter_maps_results_and_raises_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "source_id": "KS-RAG-1",
                        "version_id": "kv1",
                        "chunk_id": "c9",
                        "title": "RAG rule",
                        "text": "URDG 758 article 20 claims must be supported.",
                        "source_type": "trade_rule",
                        "score": 0.9,
                    }
                ]
            },
        )

    adapter = RagHttpAdapter(
        endpoint="https://rag.internal/search",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    plan = analyze("What does URDG 758 require for claims?")
    candidates = adapter.search(Principal("user_a", WORKSPACE), WORKSPACE, plan, None)
    assert len(candidates) == 1
    assert candidates[0].source_type == "trade_rule"
    assert candidates[0].citation_id.startswith("cite_")

    failing = RagHttpAdapter(
        endpoint="https://rag.internal/search",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))),
    )
    with pytest.raises(RetrievalError):
        failing.search(Principal("user_a", WORKSPACE), WORKSPACE, plan, None)


def test_web_only_evidence_never_reaches_strong_support():
    candidate = EvidenceCandidate(
        citation_id="cite_web",
        source_type="approved_web",
        title="web",
        source_version="v",
        excerpt="URDG 758 claims",
        locator={},
        source_text="URDG 758 claims",
        source_id="https://iccwbo.org/x",
        score=1.0,
    )
    answer = Answer(
        outcome="answered",
        language="en",
        support_level="strong",
        claims=[Claim(id="c1", text="URDG 758 claims", kind="fact", citation_ids=["cite_web"])],
        citations=[
            Citation(
                id="cite_web",
                source_type="approved_web",
                title="web",
                source_version="v",
                locator={},
            )
        ],
    )
    plan = analyze("How do I submit a version and release the lock?")
    assert plan.intent == "product_faq"
    capped = apply_layer_policy(answer, plan, EvidenceBundle([candidate]))

    assert capped.support_level == "qualified"
    assert any("unverified" in limitation.lower() for limitation in capped.limitations)


def test_trade_rule_question_answered_only_by_web_is_unable_to_assess():
    candidate = EvidenceCandidate(
        citation_id="cite_web",
        source_type="approved_web",
        title="web",
        source_version="v",
        excerpt="URDG 758 claims",
        locator={},
        source_text="URDG 758 claims",
        source_id="https://iccwbo.org/x",
        score=1.0,
    )
    answer = Answer(
        outcome="answered",
        language="en",
        support_level="qualified",
        claims=[Claim(id="c1", text="URDG 758 claims", kind="fact", citation_ids=["cite_web"])],
        citations=[
            Citation(
                id="cite_web",
                source_type="approved_web",
                title="web",
                source_version="v",
                locator={},
            )
        ],
    )
    plan = analyze("What does URDG 758 require for claims?")
    assert plan.intent == "trade_rule_explanation"

    capped = apply_layer_policy(answer, plan, EvidenceBundle([candidate]))

    assert capped.outcome == "unable_to_assess"
    assert capped.support_level == "insufficient"
    assert capped.claims == []
