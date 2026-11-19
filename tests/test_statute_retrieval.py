"""Statute evidence source (knowledge-statute-retrieval)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.assistant.domain.evidence import detect_conflicts
from app.assistant.domain.query import analyze
from app.assistant.domain.state_machine import validate_answer
from app.assistant.egress import EgressPolicy, demo_policy
from app.assistant.gateway import DoubaoGateway, ModelGatewayError
from app.assistant.pipeline import FixtureComposer
from app.assistant.ports import EvidenceBundle, EvidenceCandidate, Principal
from app.assistant.schemas import Answer, Citation, Claim, RunCreate, SessionCreate
from app.assistant.settings import (
    STATUTE_BASE_URL_ENV,
    STATUTE_ENV,
    STATUTE_TOKEN_ENV,
    AssistantSettings,
)
from app.assistant.statute import StatuteOutcome, StatuteRetriever, build_filters
from tests.assistant_helpers import (
    WORKSPACE,
    headers,
    make_client,
    make_service,
    make_services,
    register_snapshot,
)

QUESTION = "What does URDG 758 article 20 require for claims?"
BASE = "https://statute.example"


# --- settings (task 1.1) -------------------------------------------------------------------


def test_statute_is_off_by_default():
    settings = AssistantSettings.from_env({})

    assert settings.statute is False
    assert settings.statute_base_url is None
    assert settings.statute_api_token is None


def test_statute_requires_a_base_url():
    with pytest.raises(ValueError, match=STATUTE_BASE_URL_ENV):
        AssistantSettings.from_env({STATUTE_ENV: "on", STATUTE_TOKEN_ENV: "t"})


def test_statute_requires_a_token():
    with pytest.raises(ValueError, match=STATUTE_TOKEN_ENV):
        AssistantSettings.from_env({STATUTE_ENV: "on", STATUTE_BASE_URL_ENV: BASE})


def test_statute_accepts_a_complete_configuration():
    settings = AssistantSettings.from_env(
        {STATUTE_ENV: "on", STATUTE_BASE_URL_ENV: BASE + "/", STATUTE_TOKEN_ENV: "t"}
    )

    assert settings.statute is True
    assert settings.statute_base_url == BASE  # trailing slash trimmed once
    assert settings.statute_api_token == "t"


# --- filters (task 3.3) --------------------------------------------------------------------


def test_filters_carry_jurisdiction_and_trade_date():
    plan = analyze(QUESTION)
    plan = plan.__class__(**{**plan.__dict__, "jurisdictions": ["CN"], "applicable_on": "2026-03-01"})

    assert build_filters(plan, None) == {"jurisdictions": ["CN"], "as_of": "2026-03-01"}


def test_filters_omit_as_of_when_there_is_no_trade_date():
    plan = analyze(QUESTION)

    assert "as_of" not in build_filters(plan, None)
    assert build_filters(plan, "2026-03-01") == {"as_of": "2026-03-01"}


# --- payload helpers -----------------------------------------------------------------------


def chunk(
    text: str,
    *,
    score: float = 0.9,
    matched: list[dict] | None = None,
    superseded: str | None = None,
) -> dict:
    return {
        "chunk_id": "f583078a58c014ca",
        "doc_id": "cn-customs-law-2021",
        "source_doc": "中华人民共和国海关法",
        "text": text,
        "score": score,
        "articles": ["第五十五条"],
        "article_ids": ["cn-customs-law-2021:55"],
        "jurisdictions": ["CN"],
        "effective_from": "2021-04-29",
        "effective_to": None,
        "superseded_by": superseded,
        "matched_terms": matched or [],
    }


def payload(
    chunks: list[dict] | None = None,
    *,
    confidence: str = "high",
    zero: str | None = None,
    degraded: list[str] | None = None,
    uncovered: dict | None = None,
) -> dict:
    return {
        "chunks": chunks or [],
        "diagnostics": {
            "confidence": confidence,
            "zero_reason": zero,
            "degraded": degraded or [],
        },
        "corpus": {"precision": {"CN": "exact"}},
        "field_matches": {"requested_uncovered": uncovered or {}},
    }


def retriever(**kwargs) -> StatuteRetriever:
    return StatuteRetriever(base_url=BASE, api_token="t", **kwargs)


TEXT = (
    "第五十五条 进出口货物的完税价格，由海关以该货物的成交价格为基础审查确定。"
    "成交价格不能确定时，完税价格由海关依法估定。"
)


# --- mapping (task 3.1) --------------------------------------------------------------------


def test_a_statute_hit_maps_every_locator_field():
    outcome = retriever().judge(
        payload([chunk(TEXT, matched=[{"term": "完税", "start": 12, "end": 14}])]),
        terms={"完税"},
    )

    assert outcome.status == "ok"
    assert outcome.reason == "ok"
    assert len(outcome.candidates) == 1
    candidate = outcome.candidates[0]
    assert candidate.source_type == "statute"
    assert candidate.title == "中华人民共和国海关法"
    assert candidate.chunk_id == "f583078a58c014ca"
    assert candidate.source_version == "第五十五条@2021-04-29"
    locator = candidate.locator
    assert locator["chunk_id"] == "f583078a58c014ca"
    assert locator["doc_id"] == "cn-customs-law-2021"
    assert locator["article_id"] == "cn-customs-law-2021:55"
    assert locator["article_label"] == "第五十五条"
    assert locator["jurisdiction"] == "CN"
    assert locator["effective_from"] == "2021-04-29"
    assert locator["effective_to"] is None
    assert locator["precision"] == "exact"


def test_rank_derives_the_score_so_scales_never_mix():
    outcome = retriever().judge(
        payload([chunk(TEXT, score=1.0), chunk(TEXT, score=0.7)]), terms=set()
    )

    scores = [candidate.score for candidate in outcome.candidates]
    assert scores == [1.0, 0.99]


# --- excerpt (task 3.2) --------------------------------------------------------------------


@pytest.mark.parametrize(
    "start",
    [0, 10, len(TEXT) - 4],
    ids=["at-the-start", "mid-sentence", "at-the-end"],
)
def test_the_excerpt_is_always_a_real_substring(start: int):
    matched = [{"term": TEXT[start : start + 3], "start": start, "end": start + 3}]

    candidate = retriever().judge(payload([chunk(TEXT, matched=matched)]), terms=set()).candidates[0]

    assert candidate.excerpt in candidate.source_text
    assert TEXT[start : start + 3] in candidate.excerpt


def test_a_term_in_the_second_sentence_does_not_drag_in_the_first():
    start = TEXT.index("成交价格不能确定")
    matched = [{"term": "成交价格", "start": start, "end": start + 4}]

    candidate = retriever().judge(payload([chunk(TEXT, matched=matched)]), terms=set()).candidates[0]

    assert candidate.excerpt.startswith("成交价格不能确定")
    assert "第五十五条" not in candidate.excerpt


def test_without_matched_terms_the_excerpt_still_comes_from_the_source_text():
    candidate = retriever().judge(payload([chunk(TEXT)]), terms={"完税价格"}).candidates[0]

    assert candidate.excerpt
    assert candidate.excerpt in candidate.source_text


# --- availability judgement (task 4.1) ------------------------------------------------------


def test_an_empty_result_is_not_usable():
    outcome = retriever().judge(payload([], zero="no_match"), terms=set())

    assert outcome.status == "ok"
    assert outcome.usable is False
    assert outcome.reason == "zero:no_match"


def test_an_uncovered_jurisdiction_is_kept_with_a_caveat():
    outcome = retriever().judge(
        payload([chunk(TEXT)], uncovered={"jurisdictions": ["SG"]}),
        terms=set(),
    )

    assert outcome.usable is True
    assert len(outcome.candidates) == 1
    assert outcome.reason == "uncovered:SG"


def test_low_confidence_with_a_low_score_is_kept_with_a_caveat():
    outcome = retriever().judge(
        payload([chunk(TEXT, score=0.2)], confidence="low"), terms=set()
    )

    assert outcome.usable is True
    assert len(outcome.candidates) == 1
    assert outcome.reason == "low_confidence"


def test_low_confidence_is_kept_even_with_a_perfect_relative_score():
    """A 1.0 *relative* score must not hide the service saying it is unsure."""
    outcome = retriever().judge(
        payload([chunk(TEXT, score=1.0), chunk(TEXT, score=0.65)], confidence="low"), terms=set()
    )

    assert outcome.usable is True
    assert len(outcome.candidates) == 2
    assert outcome.reason == "low_confidence"


def test_a_score_below_the_floor_is_kept_with_a_caveat():
    outcome = retriever().judge(payload([chunk(TEXT, score=0.4)]), terms=set())

    assert outcome.usable is True
    assert len(outcome.candidates) == 1
    assert outcome.reason == "low_confidence"


def test_a_degraded_embedding_path_keeps_two_hits_and_says_so():
    outcome = retriever().judge(
        payload([chunk(TEXT), chunk(TEXT), chunk(TEXT)], degraded=["embedding"]), terms=set()
    )

    assert outcome.usable is True
    assert outcome.reason == "degraded:keyword_only"
    assert len(outcome.candidates) == 2


def test_a_superseded_hit_stays_usable_but_is_flagged():
    outcome = retriever().judge(
        payload([chunk(TEXT, superseded="cn-customs-law-2026:55")]), terms=set()
    )

    assert outcome.usable is True
    assert outcome.reason == "superseded"
    assert outcome.candidates[0].locator["superseded_by"] == "cn-customs-law-2026:55"


def test_a_high_scoring_hit_is_usable():
    outcome = retriever().judge(payload([chunk(TEXT, score=1.0)]), terms=set())

    assert outcome.usable is True
    assert outcome.reason == "ok"


# --- transport failures (task 4.4) ----------------------------------------------------------


def failing(status_code: int) -> StatuteRetriever:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
    return retriever(client=httpx.Client(transport=transport))


def test_a_rebuild_is_a_failed_layer_not_zero_hits():
    outcome = failing(503).search_detailed(Principal("u", WORKSPACE), WORKSPACE, analyze(QUESTION), None)

    assert outcome.status == "failed"
    assert outcome.reason == "corpus_updating"
    assert outcome.candidates == []


def test_a_rejected_token_is_a_failure_not_an_empty_corpus():
    outcome = failing(401).search_detailed(Principal("u", WORKSPACE), WORKSPACE, analyze(QUESTION), None)

    assert outcome.status == "failed"
    assert outcome.reason == "unauthorized"


# --- conflicts stay inside one source type (task 5.1) ----------------------------------------


def candidate(source_type: str, source_id: str, excerpt: str) -> EvidenceCandidate:
    return EvidenceCandidate(
        citation_id=f"cite_{source_type}_{source_id}",
        source_type=source_type,
        title="URDG 758",
        source_version="v1",
        excerpt=excerpt,
        locator={},
        source_text=excerpt,
        source_id=source_id,
    )


def test_a_statute_and_a_summary_are_not_a_conflict():
    statute = candidate("statute", "cn-law", "URDG 758 requires a claim within five days.")
    summary = candidate("trade_rule", "kc-rules", "URDG 758 requires a claim within 5 working days.")

    assert detect_conflicts([statute, summary]) == []


def test_two_sources_of_the_same_type_still_conflict():
    first = candidate("trade_rule", "src-a", "URDG 758 requires a claim within five days.")
    second = candidate("trade_rule", "src-b", "URDG 758 requires a claim within ten days.")

    conflicts = detect_conflicts([first, second])

    assert len(conflicts) == 1
    assert sorted(conflicts[0]["source_ids"]) == ["src-a", "src-b"]


# --- service wiring (tasks 4.2, 4.3, 5.2) ---------------------------------------------------


class StubStatute:
    """Minimal statute leg: reports a prepared outcome and counts calls."""

    def __init__(self, outcome: StatuteOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def search(self, principal, workspace_id, plan, applicable_on):
        return self.search_detailed(principal, workspace_id, plan, applicable_on).candidates

    def search_detailed(self, principal, workspace_id, plan, applicable_on):
        self.calls += 1
        return self.outcome

    def chat_detailed(self, principal, workspace_id, plan, applicable_on):
        # The pipeline now uses `/v1/chat`; these stubs keep the old outcome shape.
        return self.search_detailed(principal, workspace_id, plan, applicable_on)

    def health(self):
        return {"reachable": True, "documents": 143, "chunks": 11562, "index_version": "idx-1"}


class EmptyRetriever:
    def search(self, principal, workspace_id, plan, applicable_on):
        return []


class StubWebGateway:
    """Declares the tool capability and answers every general-web call with an empty result."""

    supports_tool_search = True

    def __init__(self) -> None:
        self.calls = 0
        self._composer = FixtureComposer()

    def compose(self, plan, bundle, context):
        # The first pass still composes; only the *evidence* is empty, so the answer has no claims.
        return self._composer.compose(plan, bundle, context)

    def general_web(self, query, *, max_keyword, language):
        self.calls += 1
        return SimpleNamespace(
            answer=Answer(
                outcome="answered",
                language=language,
                support_level="qualified",
                limitations=["Web evidence is unverified third-party content."],
            ),
            annotations=[],
        )


def _run_service(
    tmp_path: Path,
    *,
    statute=None,
    retriever=None,
    web_search: bool = True,
    question: str = QUESTION,
    egress=None,
    **kwargs,
):
    service = make_service(
        tmp_path,
        statute=statute,
        retriever=retriever,
        egress=egress if egress is not None else demo_policy(),
        **kwargs,
    )
    principal = Principal("user_eval", WORKSPACE)
    session = service.create_session(
        principal, SessionCreate(workspace_id=WORKSPACE, locale="en"), "idem-session", "req-session"
    )
    accepted = service.create_run(
        principal,
        session.id,
        RunCreate(question=question, web_search=web_search),
        "idem-run",
        "req-run",
    )
    service.execute_run(accepted.id)
    return service, principal, service.get_run(principal, accepted.id)


def run_once(tmp_path: Path, **kwargs):
    return _run_service(tmp_path, **kwargs)[2]


def test_the_layer_records_why_the_statute_leg_was_unusable(tmp_path):
    stub = StubStatute(StatuteOutcome(status="ok", reason="zero:no_match"))
    run = run_once(tmp_path, statute=stub, retriever=EmptyRetriever(), web_search=False)

    layers = {layer.layer: layer for layer in run.result.retrieval}

    assert stub.calls == 1
    assert layers["statute"].status == "ok"
    assert layers["statute"].detail == "zero:no_match"
    assert layers["local"].detail == "statute_unavailable"


class RecordingComposer:
    """Records which source types reached the composer, then composes as the fixture does."""

    def __init__(self) -> None:
        self.bundle_types: list[str] = []

    def compose(self, plan, bundle, context):
        self.bundle_types = [candidate.source_type for candidate in bundle.candidates]
        return FixtureComposer().compose(plan, bundle, context)


def test_a_product_question_never_calls_chat(tmp_path):
    stub = StubStatute(StatuteOutcome([statute_candidate()], status="ok", reason="ok", hits=1))

    run = run_once(
        tmp_path,
        statute=stub,
        web_search=False,
        question="提交版本后编辑锁会释放吗？",
    )

    assert stub.calls == 0
    assert all(layer.layer != "statute" for layer in run.result.retrieval)
    assert run.result.citations
    assert all(citation.source_type != "statute" for citation in run.result.citations)


def test_an_unusable_statute_leg_falls_through_to_the_existing_web_channel(tmp_path):
    stub = StubStatute(StatuteOutcome(status="failed", reason="corpus_updating"))
    gateway = StubWebGateway()
    settings = AssistantSettings(
        model="doubao:seed-1",
        api_key="k",
        approved_processor=True,
        general_web=True,
    )

    run = run_once(
        tmp_path,
        statute=stub,
        retriever=EmptyRetriever(),
        gateway=gateway,
        egress=EgressPolicy(version="t", allowed_domains=["iccwbo.org"]),
        settings=settings,
    )

    layers = {layer.layer: layer for layer in run.result.retrieval}

    assert gateway.calls == 1
    assert "web" in layers
    assert any("statute" in note.lower() or "法规" in note for note in run.result.limitations)


def test_a_superseded_statute_downgrades_the_answer(tmp_path):
    body = "第五十五条 进出口货物的完税价格，由海关以该货物的成交价格为基础审查确定。"
    superseded = EvidenceCandidate(
        citation_id="cite_statute_1",
        source_type="statute",
        title="中华人民共和国海关法",
        source_version="第五十五条@2021-04-29",
        excerpt=body,
        locator={"superseded_by": "cn-customs-law-2026:55", "jurisdiction": "CN"},
        source_text=body,
        source_id="cn-customs-law-2021",
        chunk_id="f583078a58c014ca",
    )
    stub = StubStatute(StatuteOutcome([superseded], status="ok", reason="superseded"))

    run = run_once(tmp_path, statute=stub, web_search=False)

    assert run.result is not None, "a statute citation must persist (no local knowledge-version check)"
    assert any("superseded" in note.lower() or "替代" in note for note in run.result.limitations)


# --- outbound screening and provenance (`knowledge-statute-live`) ----------------------------


class RecordingStatute(StubStatute):
    """Records the plan the service actually hands to the adapter."""

    def __init__(self, outcome: StatuteOutcome) -> None:
        super().__init__(outcome)
        self.questions: list[str] = []

    def search_detailed(self, principal, workspace_id, plan, applicable_on):
        self.questions.append(plan.question)
        return super().search_detailed(principal, workspace_id, plan, applicable_on)


def test_the_statute_question_is_screened_before_it_is_sent(tmp_path):
    stub = RecordingStatute(StatuteOutcome(status="ok", reason="low_confidence", hits=0))

    _run_service(
        tmp_path,
        statute=stub,
        web_search=False,
        question="USD 500,000.00 的保函索赔按 URDG 758 需要什么材料？",
    )

    assert stub.calls == 1
    assert stub.questions, "the adapter must be called"
    assert "500,000" not in stub.questions[0]
    assert "[redacted]" in stub.questions[0]
    # The public rule id is the search key and must survive screening.
    assert "URDG 758" in stub.questions[0]


def test_a_blocked_statute_call_is_not_sent_and_says_why(tmp_path):
    stub = StubStatute(StatuteOutcome([], status="ok", reason="ok"))

    run = run_once(
        tmp_path,
        statute=stub,
        web_search=False,
        egress=EgressPolicy.from_file(Path("/definitely/not/here.yaml")),
    )

    layers = {layer.layer: layer for layer in run.result.retrieval}
    assert stub.calls == 0
    assert layers["statute"].status == "blocked"
    assert layers["statute"].detail == "policy_unavailable"
    assert any("outbound screening" in note for note in run.result.limitations)


def test_the_statute_egress_decision_is_audited_without_the_question(tmp_path):
    stub = StubStatute(StatuteOutcome(status="ok", reason="low_confidence", hits=0))

    service, _, run = _run_service(tmp_path, statute=stub, web_search=False)

    payloads = [
        json.loads(row["payload_json"])
        for row in service.store.list_audit(run.id)
        if row["event_type"] in ("egress_allowed", "egress_blocked")
    ]
    statute_payloads = [
        payload for payload in payloads if payload.get("purpose") == "statute"
    ]
    assert len(statute_payloads) == 1
    payload = statute_payloads[0]
    assert payload["action"] == "allow"
    assert payload["reason"]
    assert payload["policy_version"]
    assert payload["query_digest"]
    assert QUESTION not in json.dumps(payload, ensure_ascii=False)


def test_a_statute_answer_is_routed_to_statute(tmp_path):
    body = "第五十五条 进出口货物的完税价格，由海关以该货物的成交价格为基础审查确定。"
    # No date in the version label: the fixture composer echoes it into the claim text, and the
    # reviewer already treats a date there as an entity that must appear in the source text.
    candidate = EvidenceCandidate(
        citation_id="cite_statute_1",
        source_type="statute",
        title="中华人民共和国海关法",
        source_version="第五十五条",
        excerpt=body,
        locator={
            "doc_id": "cn-customs-law-2021",
            "article_label": "第五十五条",
            "jurisdiction": "CN",
            "effective_from": "2021-04-29",
        },
        source_text=body,
        source_id="cn-customs-law-2021",
        chunk_id="f583078a58c014ca",
    )
    stub = StubStatute(StatuteOutcome([candidate], status="ok", reason="ok"))

    run = run_once(tmp_path, statute=stub, web_search=False)

    assert run.result.outcome == "answered"
    assert run.result.route == "statute"
    assert run.result.citations[0].source_type == "statute"


def test_a_rejected_statute_leg_keeps_the_published_route(tmp_path):
    # No candidates: the service returned no text at all, so the local corpus answers.
    stub = StubStatute(StatuteOutcome(status="ok", reason="zero:no_match", hits=0))

    run = run_once(tmp_path, statute=stub, web_search=False)

    assert run.result.route == "published"
    assert all(citation.source_type != "statute" for citation in run.result.citations)


def statute_candidate() -> EvidenceCandidate:
    """A statute candidate whose version label carries no date (the fixture composer echoes it)."""
    body = "第五条 独立保函载明适用《见索即付保函统一规则》等交易示范规则的，人民法院应予支持。"
    return EvidenceCandidate(
        citation_id="cite_statute_low",
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


def test_a_low_confidence_hit_is_used_and_caveated(tmp_path):
    stub = StubStatute(StatuteOutcome([statute_candidate()], status="ok", reason="low_confidence", hits=1))

    run = run_once(tmp_path, statute=stub, web_search=False)

    assert run.result.route == "statute"
    assert any("reference only" in note for note in run.result.limitations)
    assert not any("not used" in note for note in run.result.limitations)


def test_an_uncovered_jurisdiction_is_used_and_caveated(tmp_path):
    stub = StubStatute(
        StatuteOutcome([statute_candidate()], status="ok", reason="uncovered:SG", hits=1)
    )

    run = run_once(tmp_path, statute=stub, web_search=False)

    assert run.result.route == "statute"
    assert any("not covered by the statute corpus" in note for note in run.result.limitations)


class CountingLocalRetriever(EmptyRetriever):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, *args, **kwargs):
        self.calls += 1
        return []


def test_a_rule_answer_does_not_search_local_when_rag_has_hits(tmp_path, caplog):
    local = CountingLocalRetriever()
    stub = StubStatute(StatuteOutcome([statute_candidate()], status="ok", reason="ok", hits=1))

    with caplog.at_level(logging.INFO, logger="smart_edit.assistant"):
        run = run_once(tmp_path, statute=stub, retriever=local, web_search=False)

    assert local.calls == 0
    assert run.result.route == "statute"
    assert "retrieval chat" in caplog.text
    assert "answer_status=" in caplog.text
    assert "hits=1" in caplog.text


def test_a_selected_passage_question_never_calls_the_statute_service(tmp_path):
    stub = StubStatute(StatuteOutcome([statute_candidate()], status="ok", reason="ok", hits=1))
    text = "保函文本：本保函适用 URDG 758。"
    with make_client(
        tmp_path, services=make_services(tmp_path, statute=stub, egress=demo_policy())
    ) as client:
        snapshot = register_snapshot(client, text=text)
        session = client.post(
            "/assistant/sessions",
            json={
                "workspace_id": WORKSPACE,
                "locale": "zh-CN",
                "document_id": "doc-1",
                "snapshot_id": snapshot["id"],
            },
            headers=headers("user_a", "sess-select"),
        ).json()
        start = text.index("URDG 758")
        accepted = client.post(
            f"/assistant/sessions/{session['id']}/runs",
            json={
                "question": "这段规则是什么意思？",
                "selection": {
                    "node_id": "block_0",
                    "start_offset": start,
                    "end_offset": start + len("URDG 758"),
                    "selected_text": "URDG 758",
                },
            },
            headers=headers("user_a", "run-select"),
        )
        assert accepted.status_code == 202, accepted.text
        run = client.get(
            f"/assistant/runs/{accepted.json()['id']}", headers=headers()
        ).json()

    assert stub.calls == 0
    assert run["result"]["citations"][0]["source_type"] == "document_snapshot"


class RefusingDoubao(DoubaoGateway):
    """A real gateway subclass whose model refuses despite non-empty evidence."""

    def compose(self, plan, bundle, context):
        raise ModelGatewayError("MODEL_REFUSED_EVIDENCE")


def test_a_model_refusal_with_evidence_falls_back_to_quoting_it(tmp_path):
    stub = StubStatute(StatuteOutcome([statute_candidate()], status="ok", reason="ok", hits=1))
    settings = AssistantSettings(model="doubao:seed-1", api_key="k", approved_processor=True)
    gateway = RefusingDoubao(api_key="k", base_url="https://ark.example/api/v3", model="seed-1")

    service, _, run = _run_service(
        tmp_path, statute=stub, gateway=gateway, settings=settings, web_search=False
    )

    assert run.result.outcome == "answered"
    assert [citation.source_type for citation in run.result.citations] == ["statute"]
    assert any("model declined to answer" in note.lower() for note in run.result.limitations)
    events = [row["event_type"] for row in service.store.list_audit(run.id)]
    assert "model_refused_evidence" in events


def test_canonical_citations_complete_a_claimed_but_omitted_citation(tmp_path):
    service = make_service(tmp_path)
    candidate = statute_candidate()
    bundle = EvidenceBundle([candidate])
    answer = Answer(
        outcome="answered",
        language="zh-CN",
        support_level="qualified",
        claims=[
            Claim(
                id="c1",
                text=candidate.excerpt,
                kind="fact",
                citation_ids=[candidate.citation_id],
            )
        ],
        citations=[],
    )

    fixed = service._canonical_citations(answer, bundle)

    assert [citation.id for citation in fixed.citations] == [candidate.citation_id]
    assert validate_answer(fixed) == []


def test_route_follows_citations_not_the_outcome_flag(tmp_path):
    service = make_service(tmp_path)
    plan = analyze(QUESTION)
    payload = RunCreate(question=QUESTION)

    def citation(source_type: str) -> Citation:
        return Citation(
            id=f"cite_{source_type}",
            source_type=source_type,
            title="source",
            source_version="v1",
            locator={},
        )

    def answer(*, outcome: str = "insufficient_evidence", citations=()) -> Answer:
        return Answer(
            outcome=outcome,
            language="en",
            support_level="insufficient",
            citations=list(citations),
        )

    assert (
        service._route_for(
            plan, False, None, payload,
            answer(outcome="answered", citations=[citation("statute")]),
        )
        == "statute"
    )
    assert (
        service._route_for(
            plan, False, None, payload,
            answer(citations=[citation("trade_rule")]),
        )
        == "published"
    )
    assert service._route_for(plan, False, None, payload, answer(citations=[])) == "none"
    assert (
        service._route_for(
            plan, True, None, payload,
            answer(citations=[citation("general_web")]),
        )
        == "general_web"
    )