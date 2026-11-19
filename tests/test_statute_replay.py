"""Offline replay of recorded `/v1/retrieve` responses (adapter contract, `knowledge-statute-chat`).

The fixtures hold real service responses (see `_recording` in each file). The pipeline now calls
`/v1/chat`, so these tests exercise the retained retrieval adapter directly: request body,
judgement and locator mapping, with no network and no tunnel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.assistant.domain.query import analyze
from app.assistant.ports import Principal
from app.assistant.statute import StatuteRetriever
from tests.assistant_helpers import WORKSPACE

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "assistant"
USABLE = FIXTURES / "mercatoria_guarantee.json"
LOW = FIXTURES / "mercatoria_guarantee_low.json"
QUESTION = "什么是guarantee"
# The same table `app/configs/knowledge.sample.json` ships with.
EXPANSIONS = {
    "guarantee": ("独立保函", "见索即付保函", "demand guarantee", "URDG 758"),
}


def recorded(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replay(
    path: Path, *, expansions: dict[str, tuple[str, ...]] | None
) -> tuple[StatuteRetriever, list[dict[str, Any]]]:
    """Build a retriever that answers from `path` and records every request body it sends."""
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=recorded(path))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    retriever = StatuteRetriever(
        base_url="http://statute.test",
        api_token="replay-token",
        client=client,
        expansions=expansions,
    )
    return retriever, sent


def test_the_recorded_usable_response_maps_to_evidence():
    fixture = recorded(USABLE)
    retriever, sent = replay(USABLE, expansions=EXPANSIONS)

    outcome = retriever.search_detailed(
        Principal("user_replay", WORKSPACE), WORKSPACE, analyze(QUESTION), None
    )

    # 1. The adapter sends the expanded query and the filters derived from the plan.
    assert len(sent) == 1
    body = sent[0]
    assert body["queries"] == [f"{QUESTION} 独立保函 见索即付保函 demand guarantee URDG 758"]
    assert body["top_k"] == 5
    assert body["filters"] == {}

    # 2. The judgement is the one the recording carries (`medium`, top score 0.847 -> usable).
    assert outcome.reason == "ok"
    assert outcome.hits == len(fixture["chunks"])
    assert outcome.candidates

    # 3. The citation keeps every locator field the statute contract promises.
    candidate = outcome.candidates[0]
    locator = candidate.locator
    top = fixture["chunks"][0]
    for key in ("doc_id", "article_label", "jurisdiction", "effective_from"):
        assert locator.get(key), f"statute locator must carry {key}"
    assert locator["doc_id"] == top["doc_id"]
    assert locator["article_label"] == top["articles"][0]
    assert locator["jurisdiction"] == top["jurisdictions"][0]
    assert locator["effective_from"] == top["effective_from"]


def test_the_recorded_low_confidence_response_stays_usable():
    fixture = recorded(LOW)
    retriever, sent = replay(LOW, expansions={})

    outcome = retriever.search_detailed(
        Principal("user_replay", WORKSPACE), WORKSPACE, analyze(QUESTION), None
    )

    assert sent[0]["queries"] == [QUESTION]
    assert outcome.reason == "low_confidence"
    assert outcome.hits == len(fixture["chunks"])
    assert outcome.candidates, "low-confidence hits must still be evidence"