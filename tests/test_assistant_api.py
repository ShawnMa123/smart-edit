"""Tasks 4.1-4.3 (and the 1.2/6.1 acceptance paths) over real HTTP."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.assistant.bootstrap import build_services
from app.assistant.domain.query import analyze
from app.assistant.ports import Principal
from app.assistant.store import SessionBusy, new_id, now_iso
from tests.assistant_helpers import (
    WORKSPACE,
    headers,
    make_client,
    make_services,
    register_snapshot,
)


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as test_client:
        yield test_client


def _session(client, *, user: str = "user_a", key: str = "sess-1", body: dict | None = None) -> dict:
    payload = body or {"workspace_id": WORKSPACE, "locale": "zh-CN"}
    response = client.post("/assistant/sessions", json=payload, headers=headers(user, key))
    assert response.status_code == 201, response.text
    return response.json()


def _run(client, session_id: str, question: str, *, user: str = "user_a", key: str = "run-1", **kwargs):
    payload = {"question": question, **kwargs}
    response = client.post(
        f"/assistant/sessions/{session_id}/runs", json=payload, headers=headers(user, key)
    )
    return response


def _poll(client, run_id: str, *, user: str = "user_a") -> dict:
    response = client.get(f"/assistant/runs/{run_id}", headers=headers(user))
    assert response.status_code == 200, response.text
    return response.json()


# --- 4.1 session / run / messages -------------------------------------------------------------


def test_session_idempotency_and_conflict(client):
    first = _session(client, key="same")
    retry = _session(client, key="same")
    assert retry["id"] == first["id"]

    conflict = client.post(
        "/assistant/sessions",
        json={"workspace_id": WORKSPACE, "locale": "en"},
        headers=headers("user_a", "same"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    missing = client.post(
        "/assistant/sessions", json={"workspace_id": WORKSPACE, "locale": "zh-CN"},
        headers=headers("user_a"),
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "INVALID_REQUEST"


def test_run_idempotency_returns_the_same_run_without_duplicate_messages(client):
    session = _session(client)
    first = _run(client, session["id"], "提交版本后编辑锁会释放吗？", key="dup-run")
    assert first.status_code == 202, first.text
    first_run = _poll(client, first.json()["id"])

    retry = _run(client, session["id"], "提交版本后编辑锁会释放吗？", key="dup-run")
    assert retry.status_code == 202
    assert retry.json()["id"] == first_run["id"]

    messages = client.get(
        f"/assistant/sessions/{session['id']}/messages", headers=headers()
    ).json()["items"]
    assert len(messages) == 2, "a retry must not add a user or assistant message"

    conflict = _run(client, session["id"], "另一个问题？", key="dup-run")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_faq_run_lifecycle_citation_feedback_and_audit(client):
    session = _session(client)
    accepted = _run(client, session["id"], "提交版本后编辑锁会释放吗？")
    assert accepted.status_code == 202, accepted.text
    assert accepted.headers["Location"] == f"/assistant/runs/{accepted.json()['id']}"
    assert accepted.json()["poll_after_ms"] > 0

    run = _poll(client, accepted.json()["id"])
    assert run["status"] == "succeeded"
    assert run["stage"] == "completed"
    assert run["assistant_message_id"]
    answer = run["result"]
    assert answer["outcome"] == "answered"
    assert answer["support_level"] in ("strong", "qualified")
    assert answer["claims"] and answer["citations"]
    assert any("合成" in limitation for limitation in answer["limitations"])

    messages = client.get(
        f"/assistant/sessions/{session['id']}/messages", headers=headers()
    ).json()["items"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    citation_id = answer["citations"][0]["id"]
    detail = client.get(
        f"/assistant/messages/{messages[1]['id']}/citations/{citation_id}", headers=headers()
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["excerpt"] and detail.json()["locator"].get("section")

    first_feedback = client.put(
        f"/assistant/messages/{messages[1]['id']}/feedback",
        json={"rating": "helpful", "categories": [], "comment": "ok"},
        headers=headers(),
    )
    assert first_feedback.status_code == 200
    replaced = client.put(
        f"/assistant/messages/{messages[1]['id']}/feedback",
        json={"rating": "not_helpful", "categories": ["unclear"]},
        headers=headers(),
    )
    assert replaced.status_code == 200
    assert replaced.json()["id"] == first_feedback.json()["id"]
    assert replaced.json()["rating"] == "not_helpful"

    on_user_message = client.put(
        f"/assistant/messages/{messages[0]['id']}/feedback",
        json={"rating": "helpful"}, headers=headers(),
    )
    assert on_user_message.status_code == 400

    audit_rows = client.app.state.assistant.store._all("SELECT * FROM assistant_audit")
    assert any(row["event_type"] == "run_succeeded" for row in audit_rows)
    assert not any(
        "reasoning" in row["payload_json"] or "thoughts" in row["payload_json"]
        for row in audit_rows
    )


def test_snapshot_binding_staleness_and_selection_anchor(client):
    text = "保函文本：本保函适用 URDG 758。到期日为 2027-01-01。"
    snapshot = register_snapshot(client, text=text)
    session = _session(
        client,
        body={
            "workspace_id": WORKSPACE,
            "locale": "zh-CN",
            "document_id": "doc-1",
            "snapshot_id": snapshot["id"],
        },
    )
    assert session["context_stale"] is False

    register_snapshot(client, text=text + " 追加一段。")
    stale = client.get(f"/assistant/sessions/{session['id']}", headers=headers()).json()
    assert stale["context_stale"] is True

    start = text.index("URDG 758")
    selection = {
        "node_id": "block_0",
        "start_offset": start,
        "end_offset": start + len("URDG 758"),
        "selected_text": "URDG 758",
    }
    mismatch = _run(
        client, session["id"], "这段规则是什么意思？", key="run-bad",
        selection={**selection, "selected_text": "XXXX"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "ANCHOR_MISMATCH"

    accepted = _run(
        client, session["id"], "这段规则是什么意思？", key="run-ok", selection=selection
    )
    assert accepted.status_code == 202, accepted.text
    run = _poll(client, accepted.json()["id"])
    assert run["status"] == "succeeded"
    citation = run["result"]["citations"][0]
    assert citation["source_type"] == "document_snapshot"
    detail = client.get(
        f"/assistant/messages/{run['assistant_message_id']}/citations/{citation['id']}",
        headers=headers(),
    ).json()
    assert detail["locator"]["node_id"] == selection["node_id"]
    assert detail["locator"]["start_offset"] == selection["start_offset"]
    assert detail["locator"]["end_offset"] == selection["end_offset"]
    assert detail["excerpt"] == "URDG 758"


def test_validation_errors_are_structured_and_echo_the_request_id(client):
    response = client.post(
        "/assistant/sessions",
        json={"workspace_id": WORKSPACE, "locale": "zh-CN", "document_id": "doc-1"},
        headers={**headers(), "X-Request-ID": "req-client-1"},
    )
    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == "req-client-1"
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert body["request_id"] == "req-client-1"
    assert body["retryable"] is False
    assert body["field_errors"]

    extra = client.post(
        "/assistant/sessions",
        json={"workspace_id": WORKSPACE, "locale": "zh-CN", "owner_user_id": "user_b"},
        headers=headers("user_a", "extra-field"),
    )
    assert extra.status_code == 422
    extra_body = extra.json()["error"]
    assert extra_body["code"] == "VALIDATION_ERROR"
    assert any(
        field["field"].endswith("owner_user_id") for field in extra_body["field_errors"]
    )


# --- 1.2 / 4.3 owner isolation ----------------------------------------------------------------


def test_cross_user_access_is_a_consistent_404(client):
    session = _session(client, user="user_a")
    run = _run(client, session["id"], "提交版本后编辑锁会释放吗？").json()
    _poll(client, run["id"])
    messages = client.get(
        f"/assistant/sessions/{session['id']}/messages", headers=headers("user_a")
    ).json()["items"]
    assistant_message = messages[-1]
    citation_id = assistant_message["answer"]["citations"][0]["id"]

    other = headers("user_b")
    assert client.get(f"/assistant/sessions/{session['id']}", headers=other).status_code == 404
    assert client.get(f"/assistant/runs/{run['id']}", headers=other).status_code == 404
    assert client.get(
        f"/assistant/sessions/{session['id']}/messages", headers=other
    ).status_code == 404
    assert client.get(
        f"/assistant/messages/{assistant_message['id']}/citations/{citation_id}", headers=other
    ).status_code == 404
    assert client.put(
        f"/assistant/messages/{assistant_message['id']}/feedback",
        json={"rating": "helpful"}, headers=other,
    ).status_code == 404
    assert client.post(
        f"/assistant/sessions/{session['id']}/runs", json={"question": "hi"},
        headers=headers("user_b", "intruder"),
    ).status_code == 404
    assert client.get(
        f"/assistant/sessions?workspace_id={WORKSPACE}", headers=other
    ).json()["items"] == []


# --- 4.2 executor: busy, cancel, timeout ------------------------------------------------------


def test_busy_session_cancel_is_idempotent_and_terminal_runs_refuse_cancel(client):
    session = _session(client)
    store = client.app.state.assistant.store
    queued_message = store.create_user_message(session["id"], new_id("run"), "占用中")
    queued = store.create_run(
        session["id"], queued_message["id"], "2999-01-01T00:00:00+00:00", "{}"
    )

    busy = _run(client, session["id"], "提交版本后编辑锁会释放吗？", key="busy")
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "SESSION_BUSY"

    cancelled = client.post(
        f"/assistant/runs/{queued['id']}/cancel", headers=headers("user_a", "cancel-1")
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    again = client.post(
        f"/assistant/runs/{queued['id']}/cancel", headers=headers("user_a", "cancel-2")
    )
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"

    accepted = _run(client, session["id"], "提交版本后编辑锁会释放吗？", key="after-cancel")
    succeeded = _poll(client, accepted.json()["id"])
    assert succeeded["status"] == "succeeded"
    late_cancel = client.post(
        f"/assistant/runs/{succeeded['id']}/cancel", headers=headers("user_a", "cancel-3")
    )
    assert late_cancel.status_code == 409
    assert late_cancel.json()["error"]["code"] == "RUN_TERMINAL"


def test_timeout_terminal_state_is_not_overwritten_by_a_late_result(client):
    session = _session(client)
    store = client.app.state.assistant.store
    message = store.create_user_message(session["id"], new_id("run"), "提交版本后编辑锁会释放吗？")
    run = store.create_run(session["id"], message["id"], "2000-01-01T00:00:00+00:00", json.dumps({
        "question": "提交版本后编辑锁会释放吗？"
    }))

    client.app.state.assistant.execute_run(run["id"])
    assert _poll(client, run["id"])["status"] == "timed_out"
    assert store.commit_answer(
        run_id=run["id"], answer={}, citations=[], dependencies=[],
        audit={"event_type": "run_succeeded"}, finished_at=now_iso(),
    ) is None
    assert _poll(client, run["id"])["status"] == "timed_out"


# --- 4.3 redaction + answer outcomes ----------------------------------------------------------


def test_withdrawing_a_source_redacts_history_and_blocks_new_citations(client):
    session = _session(client)
    accepted = _run(client, session["id"], "编辑锁在提交失败后会释放吗？")
    run = _poll(client, accepted.json()["id"])
    assert run["status"] == "succeeded"
    citation_id = run["result"]["citations"][0]["id"]

    client.app.state.assistant.store.withdraw_knowledge_source(
        "KS-PRODUCT-001", "retired by reviewer", "user_reviewer"
    )

    messages = client.get(
        f"/assistant/sessions/{session['id']}/messages", headers=headers()
    ).json()["items"]
    assert messages[-1]["visibility"] == "redacted"
    assert messages[-1]["answer"] is None
    detail = client.get(
        f"/assistant/messages/{run['assistant_message_id']}/citations/{citation_id}",
        headers=headers(),
    )
    assert detail.status_code == 404

    follow_up = _run(client, session["id"], "编辑锁在提交失败后会释放吗？", key="after-withdraw")
    follow_up_run = _poll(client, follow_up.json()["id"])
    assert follow_up_run["status"] == "succeeded"
    assert follow_up_run["result"]["outcome"] == "insufficient_evidence"


def test_handoff_clarification_and_out_of_scope_outcomes(client):
    session = _session(client)

    handoff = _poll(client, _run(
        client, session["id"], "帮我改写这段条款", key="handoff"
    ).json()["id"])
    assert handoff["result"]["outcome"] == "needs_handoff"
    assert handoff["result"]["handoff_target"] == "automation"
    assert handoff["result"]["citations"] == []

    clarification = _poll(client, _run(
        client, session["id"], "URDG 758 是否适用于德国？", key="clarify"
    ).json()["id"])
    assert clarification["result"]["outcome"] == "needs_clarification"
    assert 1 <= len(clarification["result"]["clarification_questions"]) <= 3

    no_evidence = _poll(client, _run(
        client, session["id"], "How do I enable dark mode in the toolbar?", key="no-evidence"
    ).json()["id"])
    assert no_evidence["result"]["outcome"] == "insufficient_evidence"
    assert no_evidence["result"]["support_level"] == "insufficient"


def test_publish_rechecks_source_status_and_writes_no_partial_message(tmp_path):
    services = make_services(tmp_path)
    inner = services.retriever

    class WithdrawingRetriever:
        """Simulates a source撤回 between retrieval and publish."""

        def search(self, *args, **kwargs):
            results = inner.search(*args, **kwargs)
            if results:
                services.store.withdraw_knowledge_source(
                    results[0].source_id, "withdrawn during the run", "user_reviewer"
                )
            return results

    with make_client(
        tmp_path, services=replace(services, retriever=WithdrawingRetriever())
    ) as client:
        session = _session(client)
        accepted = _run(client, session["id"], "提交版本后编辑锁会释放吗？")
        run = _poll(client, accepted.json()["id"])
        messages = client.get(
            f"/assistant/sessions/{session['id']}/messages", headers=headers()
        ).json()["items"]

    assert run["status"] == "failed"
    assert run["error"]["code"] == "CONTEXT_NOT_READY"
    assert run["result"] is None
    assert [message["role"] for message in messages] == ["user"]


def test_english_help_answers_are_english_and_cited(client):
    session = _session(client)
    accepted = _run(client, session["id"], "What can you do?", key="help-en")
    run = _poll(client, accepted.json()["id"])

    assert run["status"] == "succeeded"
    assert run["result"]["language"] == "en"
    assert run["result"]["claims"]
    assert run["result"]["citations"]
    assert any("product" in claim["text"].lower() for claim in run["result"]["claims"])
    assert any("synthetic demo corpus" in limitation.lower() for limitation in run["result"]["limitations"])

    cannot = _run(client, session["id"], "What can this assistant not do?", key="cannot-en")
    cannot_run = _poll(client, cannot.json()["id"])
    assert cannot_run["result"]["language"] == "en"
    assert any(
        "not do" in claim["text"].lower() or "does not edit" in claim["text"].lower()
        for claim in cannot_run["result"]["claims"]
    )


def test_missing_help_source_fails_with_a_diagnostic_instead_of_insufficient(tmp_path):
    services = build_services(db_path=tmp_path / "empty.db", mode="test", seed=False)
    with make_client(tmp_path, services=services) as client:
        session = _session(client)
        accepted = _run(client, session["id"], "What can you do?", key="help-missing")
        run = _poll(client, accepted.json()["id"])

    assert run["status"] == "failed"
    assert run["result"] is None
    assert run["error"]["code"] == "HELP_SOURCE_UNAVAILABLE"


def test_retrieval_failure_fails_the_run_instead_of_claiming_no_evidence(tmp_path):
    class BrokenRetriever:
        def search(self, *args, **kwargs):
            raise RuntimeError("retrieval backend down")

    with make_client(tmp_path, services=make_services(tmp_path, retriever=BrokenRetriever())) as bad:
        session = _session(bad)
        accepted = _run(bad, session["id"], "提交版本后编辑锁会释放吗？")
        assert accepted.status_code == 202
        run = _poll(bad, accepted.json()["id"])

    assert run["status"] == "failed"
    assert run["result"] is None
    assert run["error"]["code"] == "ASSISTANT_FAILED"
    assert run["error"]["retryable"] is False


def test_production_mode_refuses_to_build_with_fake_adapters(monkeypatch):
    from app.api.main import create_app

    monkeypatch.setenv("SMART_EDIT_ASSISTANT_MODE", "production")
    with pytest.raises(RuntimeError):
        create_app(llm=None)