"""Explicit search scope (`knowledge-scope-inputs`): catalogue, intent boost and routing order."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.assistant.domain.query import analyze
from app.assistant.egress import EgressPolicy
from app.assistant.pipeline import FixtureComposer
from app.assistant.ports import Composition, EvidenceCandidate, Principal
from app.assistant.schemas import Answer, Citation, Claim, RunCreate, SessionCreate
from app.assistant.settings import AssistantSettings
from app.assistant.statute import StatuteOutcome, StatuteRetriever
from tests.assistant_helpers import WORKSPACE, make_service

BASE = "https://statute.example"
OUT_OF_SCOPE_QUESTION = "What are the rules on the origin of goods?"
RULE_QUESTION = "What does URDG 758 article 20 require for claims?"
PRODUCT_QUESTION = "提交版本后编辑锁会释放吗？"
HANDOFF_QUESTION = "Please replace the amount in this guarantee with 100"
PRINCIPAL = Principal("user_scope", WORKSPACE)


# --- task 1.1: the catalogue is measured, never guessed -------------------------------------


def probe(handler) -> StatuteRetriever:
    return StatuteRetriever(
        base_url=BASE, api_token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_the_catalogue_reports_measured_jurisdictions():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ready", "documents": 143, "chunks": 11562})
        if request.url.path == "/v1/corpus/documents":
            return httpx.Response(200, json={"jurisdictions": ["US", "CN", "EU"]})
        return httpx.Response(404)

    info = probe(handler).health()

    assert info["reachable"] is True
    assert info["jurisdictions"] == ["CN", "EU", "US"]


def test_a_failed_catalogue_is_not_measured_rather_than_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ready", "documents": 1, "chunks": 1})
        return httpx.Response(500)

    info = probe(handler).health()

    assert info["reachable"] is True
    assert info["jurisdictions"] is None


def test_an_unreachable_service_is_not_measured():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    info = probe(handler).health()

    assert info["reachable"] is False
    assert info["jurisdictions"] is None


# --- task 2.1: explicit scope boosts the statute attempt ------------------------------------


class StubStatute:
    def __init__(self, outcome: StatuteOutcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def search(self, principal, workspace_id, plan, applicable_on):
        return self.search_detailed(principal, workspace_id, plan, applicable_on).candidates

    def search_detailed(self, principal, workspace_id, plan, applicable_on):
        self.calls += 1
        return self.outcome

    def chat_detailed(self, principal, workspace_id, plan, applicable_on):
        return self.search_detailed(principal, workspace_id, plan, applicable_on)

    def health(self):
        return {
            "reachable": True,
            "documents": 143,
            "chunks": 11562,
            "index_version": "idx",
            "jurisdictions": ["CN", "WTO"],
        }


class EmptyRetriever:
    def search(self, principal, workspace_id, plan, applicable_on):
        return []


@pytest.mark.parametrize(
    "question, scope, expected",
    [
        (RULE_QUESTION, False, True),        # rule intent, no scope
        (PRODUCT_QUESTION, True, True),      # product intent, explicit scope
        (PRODUCT_QUESTION, False, False),    # product intent, no scope: local corpus only
        (HANDOFF_QUESTION, True, False),     # handoff, even with scope
    ],
    ids=["rule-no-scope", "product-scope", "product-no-scope", "handoff-scope"],
)
def test_statute_is_attempted_only_for_rule_or_scoped_questions(tmp_path, question, scope, expected):
    service = make_service(tmp_path, statute=StubStatute(StatuteOutcome([], "ok", "ok")))
    plan = analyze(question)

    assert service._should_try_statute(plan, scope_declared=scope) is expected


def test_statute_is_never_attempted_without_a_source(tmp_path):
    service = make_service(tmp_path)
    plan = analyze(RULE_QUESTION)

    assert service._should_try_statute(plan, scope_declared=True) is False


# --- tasks 2.2 / 2.3 / 2.4: routing order --------------------------------------------------


class StubWebGateway:
    """Evidence-aware composer + a counting general-web channel.

    The real model builds claims from whatever evidence it is given, so the routing assertions below
    must not depend on what the *fixture* composer can do with a synthetic statute excerpt.
    """

    supports_tool_search = True

    def __init__(self) -> None:
        self.calls = 0
        self.compose_calls = 0

    def compose(self, plan, bundle, context):
        self.compose_calls += 1
        candidates = bundle.candidates
        if not candidates:
            return Composition(
                Answer(
                    outcome="insufficient_evidence",
                    language=plan.language,
                    support_level="insufficient",
                    limitations=["no evidence"],
                ),
                {},
            )
        first = candidates[0]
        return Composition(
            Answer(
                outcome="answered",
                language=plan.language,
                support_level="strong",
                claims=[
                    Claim(
                        id="claim_1",
                        text=first.excerpt,
                        kind="fact",
                        citation_ids=[first.citation_id],
                    )
                ],
                citations=[Citation(**bundle.citation(first))],
            ),
            {first.citation_id: first},
        )

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


def statute_evidence() -> EvidenceCandidate:
    body = "Article VII The customs value of imported goods shall be the transaction value."
    return EvidenceCandidate(
        citation_id="cite_statute_wto",
        source_type="statute",
        title="Agreement on Implementation of Article VII",
        source_version="Article VII@1995-01-01",
        excerpt=body,
        locator={"jurisdiction": "WTO", "article_label": "Article VII"},
        source_text=body,
        source_id="wto-valuation",
        chunk_id="chunk_wto_7",
    )


def web_settings() -> AssistantSettings:
    return AssistantSettings(
        model="doubao:seed-1",
        api_key="k",
        approved_processor=True,
        general_web=True,
    )


def scoped_run(tmp_path: Path, *, statute, gateway=None, web_search: bool, retriever=None):
    service = make_service(
        tmp_path,
        statute=statute,
        retriever=retriever,
        gateway=gateway,
        egress=EgressPolicy(version="t", allowed_domains=["iccwbo.org"]),
        settings=web_settings(),
    )
    session = service.create_session(
        PRINCIPAL, SessionCreate(workspace_id=WORKSPACE, locale="en"), "scope-s", "scope-s"
    )
    accepted = service.create_run(
        PRINCIPAL,
        session.id,
        RunCreate(
            question=OUT_OF_SCOPE_QUESTION,
            jurisdiction_codes=["WTO"],
            web_search=web_search,
        ),
        "scope-r",
        "scope-r",
    )
    service.execute_run(accepted.id)
    return service.get_run(PRINCIPAL, accepted.id)


def test_scoped_out_of_scope_question_prefers_statutes_over_the_web(tmp_path):
    stub = StubStatute(StatuteOutcome([statute_evidence()], "ok", "ok"))
    gateway = StubWebGateway()

    run = scoped_run(tmp_path, statute=stub, gateway=gateway, web_search=True)

    layers = {layer.layer: layer for layer in run.result.retrieval}
    assert stub.calls == 1
    assert gateway.calls == 0, "an explicitly scoped question must try statutes before the web"
    assert layers["statute"].status == "ok"
    # A `web` entry may still exist as `skipped` (no provider configured); what matters is that the
    # general channel was never asked to search.
    assert "web" not in layers or layers["web"].status == "skipped"


def test_scoped_question_still_reaches_the_web_when_statutes_are_unusable(tmp_path):
    stub = StubStatute(StatuteOutcome(status="failed", reason="corpus_updating"))
    gateway = StubWebGateway()

    run = scoped_run(
        tmp_path, statute=stub, gateway=gateway, web_search=True, retriever=EmptyRetriever()
    )

    layers = {layer.layer: layer for layer in run.result.retrieval}
    assert stub.calls == 1
    assert gateway.calls == 1
    assert "web" in layers


def test_scoped_question_never_goes_online_without_the_toggle(tmp_path):
    stub = StubStatute(StatuteOutcome(status="failed", reason="corpus_updating"))
    gateway = StubWebGateway()

    run = scoped_run(
        tmp_path, statute=stub, gateway=gateway, web_search=False, retriever=EmptyRetriever()
    )

    assert gateway.calls == 0
    assert all(layer.layer != "web" for layer in run.result.retrieval)


def test_unscoped_out_of_scope_question_still_routes_straight_to_the_web(tmp_path):
    stub = StubStatute(StatuteOutcome([statute_evidence()], "ok", "ok"))
    gateway = StubWebGateway()
    service = make_service(
        tmp_path,
        statute=stub,
        gateway=gateway,
        egress=EgressPolicy(version="t", allowed_domains=["iccwbo.org"]),
        settings=web_settings(),
    )
    session = service.create_session(
        PRINCIPAL, SessionCreate(workspace_id=WORKSPACE, locale="en"), "plain-s", "plain-s"
    )
    accepted = service.create_run(
        PRINCIPAL,
        session.id,
        RunCreate(question=OUT_OF_SCOPE_QUESTION, web_search=True),
        "plain-r",
        "plain-r",
    )
    service.execute_run(accepted.id)

    assert gateway.calls == 1
    assert stub.calls == 0, "without an explicit scope the statute leg must not run"


# --- task 3.4: the rule version only removes the applicability question ---------------------


def test_a_rule_version_removes_the_applicability_clarification():
    question = "Is URDG 758 applicable to this guarantee?"

    without = analyze(question)
    with_rule = analyze(question, rule_version="URDG 758")

    assert without.clarification_questions
    assert with_rule.clarification_questions == []


# --- citations are server-derived, not model-authored ----------------------------------------


class SloppyGateway(StubWebGateway):
    """Composes a valid answer but fills the citation with model-made text and an empty locator."""

    def compose(self, plan, bundle, context):
        first = bundle.candidates[0]
        return Composition(
            Answer(
                outcome="answered",
                language=plan.language,
                support_level="strong",
                claims=[
                    Claim(
                        id="claim_1",
                        text=first.excerpt,
                        kind="fact",
                        citation_ids=["cite_statute_wto"],
                    )
                ],
                citations=[
                    Citation(
                        id="cite_statute_wto",
                        source_type="statute",
                        title="model-written title",
                        source_version="model-written version",
                        locator={},
                    )
                ],
            ),
            {"cite_statute_wto": first},
        )


def test_a_composed_citation_takes_its_locator_from_the_evidence(tmp_path):
    stub = StubStatute(StatuteOutcome([statute_evidence()], "ok", "ok"))

    run = scoped_run(tmp_path, statute=stub, gateway=SloppyGateway(), web_search=False)

    citation = run.result.citations[0]
    assert citation.locator["jurisdiction"] == "WTO"
    assert citation.locator["article_label"] == "Article VII"
    assert citation.title == "Agreement on Implementation of Article VII"
    assert citation.source_version == "Article VII@1995-01-01"