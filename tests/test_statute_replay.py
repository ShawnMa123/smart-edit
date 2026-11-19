"""Offline replay of recorded `/v1/retrieve` responses (knowledge-statute-live design D4).

The fixtures hold real service responses (see `_recording` in each file). No network and no tunnel
are involved: `httpx.MockTransport` serves the recording, so the request the adapter builds, the
availability judgement, the citation locators and the layer report are all still exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.assistant.egress import demo_policy
from app.assistant.ports import Composition, EvidenceBundle, Principal
from app.assistant.schemas import Answer, Citation, Claim, RunCreate, SessionCreate
from app.assistant.statute import StatuteRetriever
from tests.assistant_helpers import WORKSPACE, make_service

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


class ExcerptComposer:
    """Compose claims that quote the evidence verbatim.

    The stock `FixtureComposer` writes `<article>@<effective_from>` into every claim, and the
    reviewer then requires that date inside the article text. A statute carries its effective date
    as metadata, not in the article body, so the fixture composer rejects every dated statute even
    when the retrieval and the citation are correct (`test_a_statute_answer_is_routed_to_statute`
    avoids this by using a versionless label). These assertions are about the statute contract —
    request body, judgement, locator, layer — so the claims quote the excerpt and nothing else.
    """

    def compose(self, plan, bundle: EvidenceBundle, context: dict[str, Any]) -> Composition:
        selected = list(bundle.candidates[:3])
        claims = [
            Claim(
                id=f"claim_{index}",
                text=candidate.excerpt[:300],
                kind="fact",
                citation_ids=[candidate.citation_id],
            )
            for index, candidate in enumerate(selected, start=1)
        ]
        answer = Answer(
            outcome="answered",
            language=plan.language,
            support_level="qualified",
            claims=claims,
            citations=[Citation(**bundle.citation(candidate)) for candidate in selected],
        )
        return Composition(answer, {candidate.citation_id: candidate for candidate in selected})


def run_once(tmp_path: Path, *, statute: StatuteRetriever, gateway: Any = None):
    service = make_service(
        tmp_path,
        statute=statute,
        gateway=gateway,
        egress=demo_policy(),
    )
    principal = Principal("user_replay", WORKSPACE)
    session = service.create_session(
        principal,
        SessionCreate(workspace_id=WORKSPACE, locale="zh-CN"),
        "idem-session",
        "req-session",
    )
    accepted = service.create_run(
        principal,
        session.id,
        RunCreate(question=QUESTION, web_search=False),
        "idem-run",
        "req-run",
    )
    service.execute_run(accepted.id)
    return service, principal, service.get_run(principal, accepted.id)


def test_the_recorded_usable_answer_replays_end_to_end(tmp_path):
    fixture = recorded(USABLE)
    retriever, sent = replay(USABLE, expansions=EXPANSIONS)

    _, _, run = run_once(tmp_path, statute=retriever, gateway=ExcerptComposer())

    # 1. The adapter sends the expanded query and the filters derived from the payload.
    assert len(sent) == 1
    body = sent[0]
    assert body["queries"] == [
        f"{QUESTION} 独立保函 见索即付保函 demand guarantee URDG 758"
    ]
    assert body["top_k"] == 5
    assert body["filters"] == {}

    # 2. The judgement is the one the recording carries (`medium`, top score 0.847 -> usable).
    layers = {layer.layer: layer for layer in run.result.retrieval}
    assert run.result.outcome == "answered"
    assert layers["statute"].status == "ok"
    assert layers["statute"].detail == "ok"
    assert layers["statute"].hits == len(fixture["chunks"])

    # 3. The citation keeps every locator field the statute contract promises.
    citations = [item for item in run.result.citations if item.source_type == "statute"]
    assert citations, "a usable recording must produce a statute citation"
    locator = citations[0].locator
    top = fixture["chunks"][0]
    for key in ("doc_id", "article_label", "jurisdiction", "effective_from"):
        assert locator.get(key), f"statute locator must carry {key}"
    assert locator["doc_id"] == top["doc_id"]
    assert locator["article_label"] == top["articles"][0]
    assert locator["jurisdiction"] == top["jurisdictions"][0]
    assert locator["effective_from"] == top["effective_from"]

    # 4. The layer report and the route agree.
    assert run.result.route == "statute"
    assert not any("置信度低" in note for note in run.result.limitations)


def test_the_recorded_low_confidence_answer_is_used_with_a_caveat(tmp_path):
    fixture = recorded(LOW)
    retriever, sent = replay(LOW, expansions={})

    _, _, run = run_once(tmp_path, statute=retriever, gateway=ExcerptComposer())

    assert sent[0]["queries"] == [QUESTION]
    layers = {layer.layer: layer for layer in run.result.retrieval}
    assert layers["statute"].status == "ok"
    assert layers["statute"].detail == "low_confidence"
    assert layers["statute"].hits == len(fixture["chunks"])

    # The hits are used instead of discarded; the caveat says how far to trust them.
    assert run.result.route == "statute"
    assert [item.source_type for item in run.result.citations] == ["statute"] * len(
        run.result.citations
    )
    assert any("置信度低，仅供参考" in note for note in run.result.limitations)
    assert not any("未采用" in note for note in run.result.limitations)