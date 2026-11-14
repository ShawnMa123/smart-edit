"""Task 6.1 — acceptance over a real HTTP socket (uvicorn in a thread, httpx client).

The in-process TestClient tests cover the contract; this file proves the same paths survive a real
server: snapshot/session/run/poll, citation detail, clarification, no-evidence, cross-user 404,
withdraw → redacted, and cancel/timeout terminal states.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.api.main import create_app
from app.assistant.store import new_id
from tests.assistant_helpers import WORKSPACE, headers, make_services


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    directory = tmp_path_factory.mktemp("assistant-e2e")
    services = make_services(directory)
    app = create_app(llm=None, runs_dir=directory / "runs", assistant_services=services)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    try:
        yield f"http://127.0.0.1:{port}", app
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _session(client: httpx.Client, *, key: str = "e2e-session", user: str = "user_a") -> dict:
    response = client.post(
        "/assistant/sessions",
        json={"workspace_id": WORKSPACE, "locale": "zh-CN"},
        headers=headers(user, key),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _wait_for_run(
    client: httpx.Client, run_id: str, *, user: str = "user_a", timeout: float = 15.0
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/assistant/runs/{run_id}", headers=headers(user))
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in ("succeeded", "failed", "cancelled", "timed_out"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach a terminal state")


def test_faq_question_returns_a_cited_answer_over_http(live):
    base, _ = live
    with httpx.Client(base_url=base) as client:
        session = _session(client)
        accepted = client.post(
            f"/assistant/sessions/{session['id']}/runs",
            json={"question": "提交版本后编辑锁会释放吗？"},
            headers=headers("user_a", "e2e-run-1"),
        )
        assert accepted.status_code == 202, accepted.text
        assert accepted.headers["Location"].startswith("/assistant/runs/")

        run = _wait_for_run(client, accepted.json()["id"])
        assert run["status"] == "succeeded"
        answer = run["result"]
        assert answer["outcome"] == "answered"
        assert answer["support_level"] in ("strong", "qualified")
        assert answer["claims"] and answer["citations"]

        citation = answer["citations"][0]
        detail = client.get(
            f"/assistant/messages/{run['assistant_message_id']}/citations/{citation['id']}",
            headers=headers(),
        )
        assert detail.status_code == 200
        assert detail.json()["excerpt"]


def test_clarification_and_no_evidence_over_http(live):
    base, _ = live
    with httpx.Client(base_url=base) as client:
        session = _session(client, key="e2e-session-2")

        question = client.post(
            f"/assistant/sessions/{session['id']}/runs",
            json={"question": "URDG 758 是否适用于德国？"},
            headers=headers("user_a", "e2e-run-2"),
        )
        clarification = _wait_for_run(client, question.json()["id"])
        assert clarification["result"]["outcome"] == "needs_clarification"
        assert 1 <= len(clarification["result"]["clarification_questions"]) <= 3

        no_evidence = client.post(
            f"/assistant/sessions/{session['id']}/runs",
            json={"question": "How do I enable dark mode in the toolbar?"},
            headers=headers("user_a", "e2e-run-3"),
        )
        insufficient = _wait_for_run(client, no_evidence.json()["id"])
        assert insufficient["result"]["outcome"] == "insufficient_evidence"
        assert insufficient["result"]["citations"] == []


def test_document_selection_and_anchor_mismatch_over_http(live):
    base, _ = live
    with httpx.Client(base_url=base) as client:
        text = "保函文本：本保函适用 URDG 758。"
        snapshot = client.post(
            "/assistant/snapshots",
            json={
                "document_id": "doc-e2e",
                "text": text,
                "content_sha256": "b" * 64,
                "version_label": "v1",
            },
            headers=headers(),
        ).json()
        session = client.post(
            "/assistant/sessions",
            json={
                "workspace_id": WORKSPACE,
                "locale": "zh-CN",
                "document_id": "doc-e2e",
                "snapshot_id": snapshot["id"],
            },
            headers=headers("user_a", "e2e-session-3"),
        ).json()

        start = text.index("URDG 758")
        bad = client.post(
            f"/assistant/sessions/{session['id']}/runs",
            json={
                "question": "这段规则是什么意思？",
                "selection": {
                    "node_id": "block_0",
                    "start_offset": start,
                    "end_offset": start + 8,
                    "selected_text": "XXXX",
                },
            },
            headers=headers("user_a", "e2e-run-4"),
        )
        assert bad.status_code == 409
        assert bad.json()["error"]["code"] == "ANCHOR_MISMATCH"

        good = client.post(
            f"/assistant/sessions/{session['id']}/runs",
            json={
                "question": "这段规则是什么意思？",
                "selection": {
                    "node_id": "block_0",
                    "start_offset": start,
                    "end_offset": start + 8,
                    "selected_text": "URDG 758",
                },
            },
            headers=headers("user_a", "e2e-run-5"),
        )
        run = _wait_for_run(client, good.json()["id"])
        assert run["result"]["outcome"] == "answered"
        assert run["result"]["citations"][0]["source_type"] == "document_snapshot"


def test_cross_user_isolation_and_redaction_over_http(live):
    base, app = live
    with httpx.Client(base_url=base) as client:
        session = _session(client, key="e2e-session-4")
        accepted = client.post(
            f"/assistant/sessions/{session['id']}/runs",
            json={"question": "编辑锁在提交失败后会释放吗？"},
            headers=headers("user_a", "e2e-run-6"),
        )
        run = _wait_for_run(client, accepted.json()["id"])
        citation_id = run["result"]["citations"][0]["id"]

        assert client.get(
            f"/assistant/sessions/{session['id']}", headers=headers("user_b")
        ).status_code == 404
        assert client.get(
            f"/assistant/runs/{run['id']}", headers=headers("user_b")
        ).status_code == 404
        assert client.get(
            f"/assistant/messages/{run['assistant_message_id']}/citations/{citation_id}",
            headers=headers("user_b"),
        ).status_code == 404

        app.state.assistant.store.withdraw_knowledge_source(
            "KS-PRODUCT-001", "retired in e2e", "user_reviewer"
        )
        messages = client.get(
            f"/assistant/sessions/{session['id']}/messages", headers=headers("user_a")
        ).json()["items"]
        assert messages[-1]["visibility"] == "redacted"
        assert messages[-1]["answer"] is None
        assert client.get(
            f"/assistant/messages/{run['assistant_message_id']}/citations/{citation_id}",
            headers=headers("user_a"),
        ).status_code == 404


def test_cancel_and_timeout_are_terminal_over_http(live):
    base, app = live
    with httpx.Client(base_url=base) as client:
        session = _session(client, key="e2e-session-5")
        store = app.state.assistant.store
        message = store.create_user_message(session["id"], new_id("run"), "占用中")
        queued = store.create_run(
            session["id"], message["id"], "2999-01-01T00:00:00+00:00", "{}"
        )

        cancelled = client.post(
            f"/assistant/runs/{queued['id']}/cancel", headers=headers("user_a", "e2e-cancel-1")
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert _wait_for_run(client, queued["id"])["status"] == "cancelled"

        timed_session = _session(client, key="e2e-session-6")
        slow_message = store.create_user_message(
            timed_session["id"], new_id("run"), "提交版本后编辑锁会释放吗？"
        )
        slow = store.create_run(
            timed_session["id"],
            slow_message["id"],
            "2000-01-01T00:00:00+00:00",
            '{"question": "提交版本后编辑锁会释放吗？"}',
        )
        app.state.assistant.execute_run(slow["id"])
        assert _wait_for_run(client, slow["id"])["status"] == "timed_out"