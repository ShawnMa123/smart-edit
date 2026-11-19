"""Term normalisation and "searched but rejected" transparency (`statute-recall`)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.assistant.domain.query import analyze
from app.assistant.egress import (
    MAX_EXPANSION_CHARS,
    MAX_EXPANSION_TERMS,
    MAX_EXPANSION_TERMS_PER_KEY,
    EgressPolicy,
    demo_policy,
    normalise_expansions,
)
from app.assistant.ports import EvidenceCandidate, Principal
from app.assistant.schemas import RunCreate, SessionCreate
from app.assistant.statute import StatuteOutcome, StatuteRetriever, expand_terms
from tests.assistant_helpers import WORKSPACE, make_service

TABLE = {"guarantee": ("独立保函", "见索即付保函", "demand guarantee")}
PRINCIPAL = Principal("user_recall", WORKSPACE)
QUESTION = "guarantee是什么"


# --- expansion table ------------------------------------------------------------------------


def test_the_table_is_normalised_and_ordered():
    table = normalise_expansions({"Guarantee": ["独立保函", "独立保函", "见索即付保函"]})

    assert list(table) == ["guarantee"]  # keys are lower-cased for substring matching
    assert table["guarantee"] == ("独立保函", "见索即付保函")  # deduped, order kept


def test_per_key_terms_are_capped():
    table = normalise_expansions({"guarantee": [f"t{index}" for index in range(10)]})

    assert len(table["guarantee"]) == MAX_EXPANSION_TERMS_PER_KEY


def test_a_malformed_table_is_a_config_error():
    with pytest.raises(ValueError, match="list of terms"):
        normalise_expansions({"guarantee": "独立保函"})


def test_the_config_file_carries_the_expansion_table():
    policy = EgressPolicy.load(None)

    assert policy.loaded is True
    assert "guarantee" in policy.query_expansion
    assert "独立保函" in policy.query_expansion["guarantee"]


# --- expansion behaviour ---------------------------------------------------------------------


def test_a_generic_word_is_rewritten_into_controlled_terms():
    assert expand_terms(QUESTION, TABLE) == list(TABLE["guarantee"])


def test_an_unmatched_question_is_unchanged():
    assert expand_terms("What is the filing deadline?", TABLE) == []


def test_the_result_is_capped():
    table = {"guarantee": tuple(f"term-{index}" for index in range(MAX_EXPANSION_TERMS + 5))}

    terms = expand_terms(QUESTION, table)

    assert len(terms) <= MAX_EXPANSION_TERMS
    assert sum(len(term) for term in terms) <= MAX_EXPANSION_CHARS


# --- the retriever sends the expanded query --------------------------------------------------


def capturing_client(seen: list[dict], chunks: list[dict]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "chunks": chunks,
                "diagnostics": {"confidence": "medium", "zero_reason": None, "degraded": []},
                "corpus": {"precision": {"CN": "exact"}},
                "field_matches": {"requested_uncovered": {}},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def a_chunk() -> dict:
    return {
        "chunk_id": "chunk_1",
        "doc_id": "cn-independent-guarantee-2020",
        "source_doc": "最高人民法院关于审理独立保函纠纷案件若干问题的规定",
        "text": "第一条 本规定所称的独立保函，是指银行出具的付款承诺。",
        "score": 0.9,
        "articles": ["第一条"],
        "article_ids": ["cn-independent-guarantee-2020:1"],
        "jurisdictions": ["CN"],
        "effective_from": "2020-01-01",
        "effective_to": None,
        "superseded_by": None,
        "matched_terms": [{"term": "独立保函", "start": 20, "end": 24}],
    }


def test_the_query_keeps_the_original_and_appends_the_terms():
    seen: list[dict] = []
    retriever = StatuteRetriever(
        base_url="https://s.example",
        api_token="t",
        client=capturing_client(seen, [a_chunk()]),
        expansions=TABLE,
    )

    outcome = retriever.search_detailed(PRINCIPAL, WORKSPACE, analyze(QUESTION), None)

    sent = seen[0]["queries"][0]
    assert sent.startswith(QUESTION)
    assert "独立保函" in sent
    assert outcome.expansions == TABLE["guarantee"]
    assert outcome.hits == 1


def test_without_a_table_the_query_is_byte_identical():
    seen: list[dict] = []
    retriever = StatuteRetriever(
        base_url="https://s.example", api_token="t", client=capturing_client(seen, [a_chunk()])
    )

    outcome = retriever.search_detailed(PRINCIPAL, WORKSPACE, analyze(QUESTION), None)

    assert seen[0]["queries"] == [QUESTION]
    assert outcome.expansions == ()


# --- "searched but rejected" is stated -------------------------------------------------------


class StubStatute:
    def __init__(self, outcome: StatuteOutcome) -> None:
        self.outcome = outcome

    def search(self, principal, workspace_id, plan, applicable_on):
        return self.outcome.candidates

    def search_detailed(self, principal, workspace_id, plan, applicable_on):
        return self.outcome

    def health(self):
        return {
            "reachable": True,
            "documents": 1,
            "chunks": 1,
            "index_version": "i",
            "jurisdictions": None,
        }


class LocalRetriever:
    def search(self, principal, workspace_id, plan, applicable_on):
        body = "A demand guarantee is independent of the underlying contract."
        return [
            EvidenceCandidate(
                citation_id="cite_local",
                source_type="trade_rule",
                title="Synthetic Trade Rules Summary",
                source_version="demo-2",
                excerpt=body,
                locator={},
                source_text=body,
                source_id="KS-RULES-001",
                chunk_id="chunk_local",
            )
        ]


def run_with(tmp_path: Path, outcome: StatuteOutcome):
    service = make_service(
        tmp_path,
        statute=StubStatute(outcome),
        retriever=LocalRetriever(),
        egress=demo_policy(),
    )
    session = service.create_session(
        PRINCIPAL, SessionCreate(workspace_id=WORKSPACE, locale="en"), "recall-s", "recall-s"
    )
    accepted = service.create_run(
        PRINCIPAL, session.id, RunCreate(question="guarantee 是什么"), "recall-r", "recall-r"
    )
    service.execute_run(accepted.id)
    return service.get_run(PRINCIPAL, accepted.id), service


def test_a_low_confidence_statute_search_is_stated_even_when_local_answered(tmp_path):
    run, _ = run_with(tmp_path, StatuteOutcome(status="ok", reason="low_confidence", hits=3))

    layers = {layer.layer: layer for layer in run.result.retrieval}
    assert layers["statute"].hits == 3
    # The question is Chinese, so the notes are too; the point is that they exist with the count.
    joined = " ".join(run.result.limitations)
    assert "3 条" in joined
    assert "仅供参考" in joined
    assert "内部来源" in joined
    assert run.result.citations, "the local answer must still be delivered"


def test_zero_hits_says_no_statute_matched(tmp_path):
    run, _ = run_with(tmp_path, StatuteOutcome(status="ok", reason="zero:no_match", hits=0))

    assert "没有匹配到相关法规" in " ".join(run.result.limitations)


def test_the_used_expansions_are_audited(tmp_path):
    run, service = run_with(
        tmp_path,
        StatuteOutcome(
            [], status="ok", reason="low_confidence", hits=1,
            expansions=("独立保函", "见索即付保函"),
        ),
    )

    events = {
        row["event_type"]: json.loads(row["payload_json"])
        for row in service.store.list_audit(run.id)
    }
    assert events["statute_expanded"]["expansions"] == ["独立保函", "见索即付保函"]