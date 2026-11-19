"""Pipeline use of `/v1/chat` + draft composition (`knowledge-statute-chat`)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.assistant.domain.query import analyze
from app.assistant.egress import demo_policy
from app.assistant.gateway import DoubaoGateway, ModelGatewayError
from app.assistant.pipeline import (
    CHAT_EVIDENCE_FALLBACK_EN,
    CHAT_STRUCTURE_FAILED_EN,
    FixtureComposer,
)
from app.assistant.ports import EvidenceBundle, EvidenceCandidate, Principal
from app.assistant.retrieval import FixtureWebSearch, WebPage
from app.assistant.schemas import RunCreate, SessionCreate
from app.assistant.settings import AssistantSettings
from app.assistant.statute import StatuteOutcome
from tests.assistant_helpers import WORKSPACE, make_service

QUESTION = "What does URDG 758 article 20 require for claims?"


def candidate() -> EvidenceCandidate:
    body = "第五条 独立保函载明适用《见索即付保函统一规则》等交易示范规则的，人民法院应予支持。"
    return EvidenceCandidate(
        citation_id="cite_chat_1",
        source_type="statute",
        title="最高人民法院关于审理独立保函纠纷案件若干问题的规定",
        source_version="第五条",
        excerpt=body,
        locator={
            "chunk_id": "chunk1",
            "doc_id": "cn-independent-guarantee-2020",
            "article_label": "第五条",
            "jurisdiction": "CN",
            "effective_from": "2020-12-29",
        },
        source_text=body,
        source_id="cn-independent-guarantee-2020",
        version_id="chunk1",
        chunk_id="chunk1",
    )


def chat_outcome(
    *,
    status: str = "answered",
    with_candidate: bool = True,
    coverage: dict | None = None,
) -> StatuteOutcome:
    return StatuteOutcome(
        [candidate()] if with_candidate else [],
        status="ok",
        reason=status,
        hits=1 if with_candidate else 0,
        draft="草稿：[chunk1]" if with_candidate and status in ("answered", "partial") else None,
        answer_status=status,
        cited_ids=("chunk1",) if with_candidate else (),
        coverage=coverage or {},
    )


class FakeChatStatute:
    def __init__(self, outcome: StatuteOutcome, *, delay: float = 0.0) -> None:
        self.outcome = outcome
        self.delay = delay
        self.chat_calls = 0
        self.retrieve_calls = 0

    def chat_detailed(self, principal, workspace_id, plan, applicable_on):
        self.chat_calls += 1
        if self.delay:
            time.sleep(self.delay)
        return self.outcome

    def search_detailed(self, principal, workspace_id, plan, applicable_on):
        self.retrieve_calls += 1
        return self.outcome

    def health(self):
        return {"reachable": True, "documents": 1, "chunks": 1, "index_version": "test"}


class DraftRecordingDoubao(DoubaoGateway):
    def __init__(self, *, error: str | None = None) -> None:
        super().__init__(api_key="k", base_url="https://ark.example/api/v3", model="seed-1")
        self.error = error
        self.calls = 0
        self.contexts: list[dict] = []

    def compose(self, plan, bundle, context):
        self.calls += 1
        self.contexts.append(dict(context))
        if self.error:
            raise ModelGatewayError(self.error)
        return FixtureComposer().compose(plan, bundle, context)


EXTERNAL = AssistantSettings(model="doubao:seed-1", api_key="k", approved_processor=True)


def run_once(
    tmp_path,
    *,
    statute,
    gateway=None,
    settings=None,
    question: str = QUESTION,
    web=None,
    web_search: bool = False,
):
    service = make_service(
        tmp_path,
        statute=statute,
        gateway=gateway,
        settings=settings,
        web=web,
        egress=demo_policy(),
    )
    principal = Principal("user_chat", WORKSPACE)
    session = service.create_session(
        principal, SessionCreate(workspace_id=WORKSPACE, locale="en"), "s", "r"
    )
    accepted = service.create_run(
        principal,
        session.id,
        RunCreate(question=question, web_search=web_search),
        "run",
        "req",
    )
    service.execute_run(accepted.id)
    return service, principal, service.get_run(principal, accepted.id)


def test_a_rule_question_uses_chat_only(tmp_path, caplog):
    statute = FakeChatStatute(chat_outcome())

    with caplog.at_level(logging.INFO, logger="smart_edit.assistant"):
        service, _, run = run_once(tmp_path, statute=statute)

    assert statute.chat_calls == 1
    assert statute.retrieve_calls == 0
    layers = {layer.layer: layer for layer in run.result.retrieval}
    assert layers["statute"].detail == "answered"
    assert run.result.route == "statute"
    assert "retrieval chat" in caplog.text
    audits = [
        json.loads(row["payload_json"])
        for row in service.store.list_audit(run.id)
        if row["event_type"] == "egress_allowed"
    ]
    assert any(
        payload.get("purpose") == "statute" and payload.get("endpoint") == "chat"
        for payload in audits
    )


def test_a_product_question_does_not_call_chat(tmp_path):
    statute = FakeChatStatute(chat_outcome())

    _, _, run = run_once(tmp_path, statute=statute, question="提交版本后编辑锁会释放吗？")

    assert statute.chat_calls == 0
    assert all(layer.layer != "statute" for layer in run.result.retrieval)
    assert all(citation.source_type != "statute" for citation in run.result.citations)


def test_the_chat_draft_reaches_the_composer(tmp_path):
    statute = FakeChatStatute(chat_outcome())
    gateway = DraftRecordingDoubao()

    _, _, run = run_once(tmp_path, statute=statute, gateway=gateway, settings=EXTERNAL)

    assert gateway.calls == 1
    context = gateway.contexts[0]
    assert context["draft"] == "草稿：[chunk1]"
    assert context["draft_cited_ids"] == ["chunk1"]
    assert context["draft_answer_status"] == "answered"
    assert run.result.route == "statute"


def test_unavailable_with_references_is_used_and_skips_the_web(tmp_path):
    statute = FakeChatStatute(chat_outcome(status="unavailable"))
    gateway = DraftRecordingDoubao()
    settings = replace(EXTERNAL, general_web=True)

    _, _, run = run_once(
        tmp_path, statute=statute, gateway=gateway, settings=settings, web_search=True
    )

    assert run.result.route == "statute"
    assert all(citation.source_type == "statute" for citation in run.result.citations)
    assert all(layer.detail != "general_web" for layer in run.result.retrieval)
    assert any(
        "own answer was unavailable" in note.lower() for note in run.result.limitations
    )


def test_evidence_only_reaches_the_composer_without_a_draft(tmp_path):
    statute = FakeChatStatute(chat_outcome(status="unavailable"))
    gateway = DraftRecordingDoubao()

    _, _, run = run_once(tmp_path, statute=statute, gateway=gateway, settings=EXTERNAL)

    context = gateway.contexts[0]
    assert context["draft"] is None, "a refusal text must not be sent as a draft"
    assert context["chat_evidence"] is True
    assert context["draft_answer_status"] == "unavailable"
    assert run.result.route == "statute"


def test_evidence_only_failure_quotes_and_explains(tmp_path):
    statute = FakeChatStatute(chat_outcome(status="unsupported"))
    gateway = DraftRecordingDoubao(error="MODEL_TIMEOUT")

    service, _, run = run_once(tmp_path, statute=statute, gateway=gateway, settings=EXTERNAL)

    assert run.result.citations
    assert any(
        CHAT_EVIDENCE_FALLBACK_EN.lower() in note.lower() for note in run.result.limitations
    )
    events = [row["event_type"] for row in service.store.list_audit(run.id)]
    assert "chat_structure_failed" in events


@pytest.mark.parametrize(
    "code", ["MODEL_OUTPUT_INVALID", "MODEL_REFUSED_EVIDENCE", "MODEL_TIMEOUT"]
)
def test_a_failed_structuring_pass_quotes_the_evidence(tmp_path, code):
    statute = FakeChatStatute(chat_outcome())
    gateway = DraftRecordingDoubao(error=code)

    service, _, run = run_once(tmp_path, statute=statute, gateway=gateway, settings=EXTERNAL)

    assert run.result.citations
    assert all(citation.source_type == "statute" for citation in run.result.citations)
    assert any(
        CHAT_STRUCTURE_FAILED_EN.lower() in note.lower() for note in run.result.limitations
    )
    events = [row["event_type"] for row in service.store.list_audit(run.id)]
    assert "chat_structure_failed" in events


def test_a_near_deadline_skips_the_polish(tmp_path):
    statute = FakeChatStatute(chat_outcome())
    gateway = DraftRecordingDoubao()
    service, _, _ = run_once(tmp_path, statute=statute, gateway=gateway, settings=EXTERNAL)
    plan = analyze(QUESTION)
    payload = RunCreate(question=QUESTION, web_search=False)
    bundle = EvidenceBundle([candidate()])
    deadline = (datetime.fromisoformat(service.clock.now()) + timedelta(seconds=5)).isoformat()

    gateway.calls = 0  # ignore the compose call made by the initial run
    composition = service._compose(
        plan,
        bundle,
        None,
        {},
        "run-deadline",
        payload,
        draft="草稿：[chunk1]",
        deadline_at=deadline,
    )

    assert gateway.calls == 0, "the polish must be skipped near the deadline"
    assert composition.answer.citations
    assert any(
        CHAT_STRUCTURE_FAILED_EN.lower() in note.lower()
        for note in composition.answer.limitations
    )
    events = [row["event_type"] for row in service.store.list_audit("run-deadline")]
    assert "chat_polish_skipped" in events


def test_partial_status_is_stated_as_incomplete(tmp_path):
    statute = FakeChatStatute(chat_outcome(status="partial"))

    _, _, run = run_once(tmp_path, statute=statute)

    assert any("partial answer" in note.lower() for note in run.result.limitations)
    assert run.result.citations


def test_unsupported_is_not_reported_as_no_rule(tmp_path):
    statute = FakeChatStatute(chat_outcome(status="unsupported", with_candidate=False))

    _, _, run = run_once(tmp_path, statute=statute)

    joined = " ".join(run.result.limitations).lower()
    assert "did not return a usable answer" in joined
    assert "no statute matched" not in joined


def test_coverage_notes_reach_the_limitations(tmp_path):
    statute = FakeChatStatute(chat_outcome(coverage={"notes": ["uncovered jurisdictions: SG"]}))

    _, _, run = run_once(tmp_path, statute=statute)

    assert any("uncovered jurisdictions: SG" in note for note in run.result.limitations)


def test_the_local_worker_budget_follows_the_chat_timeout(tmp_path):
    default = make_service(tmp_path, settings=AssistantSettings())
    short = make_service(tmp_path, settings=AssistantSettings(chat_timeout=12))

    assert default._local_layer_budget() == 70.0
    assert short._local_layer_budget() == 22.0


def test_a_chat_timeout_is_reported_while_the_web_layer_still_runs(tmp_path):
    statute = FakeChatStatute(chat_outcome(), delay=0.4)
    web = FixtureWebSearch(
        [WebPage(url="https://example.org/wto", title="WTO", text="guarantee rules")]
    )
    service = make_service(
        tmp_path,
        statute=statute,
        web=web,
        egress=demo_policy(),
        settings=AssistantSettings(chat_timeout=0.01),
    )
    service._local_layer_budget = lambda: 0.05  # shrink the worker budget for the test
    plan = analyze(QUESTION)
    payload = RunCreate(question=QUESTION, web_search=True)
    decision = service._search_decision(plan, payload, "run-timeout")

    bundle, layers, meta = service._retrieve_layers(
        Principal("u", WORKSPACE),
        {"workspace_id": WORKSPACE},
        plan,
        payload,
        "run-timeout",
        decision,
    )

    assert any(layer.layer == "local" and layer.detail == "timeout" for layer in layers)
    assert bundle.candidates, "the web layer must still complete"
    assert meta == {}
    time.sleep(0.5)  # let the abandoned chat worker finish before pytest closes the log stream