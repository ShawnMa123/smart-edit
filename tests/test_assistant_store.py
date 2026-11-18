"""Tasks 1.1-1.3 — SQLite repositories, fake isolation primitives, recovery and CAS."""

from __future__ import annotations

import sqlite3

import pytest

from app.assistant.bootstrap import build_services
from app.assistant.schemas import Answer
from app.assistant.store import SCHEMA_VERSION, SessionBusy, SQLiteStore, new_id, now_iso
from app.knowledge.seed import seed_knowledge


def _session(store: SQLiteStore, owner: str = "user_a") -> dict:
    return store.create_session(
        workspace_id="ws_demo_01", owner_user_id=owner, document_id=None,
        snapshot_id=None, attachment_ids=[], locale="zh-CN",
    )


def _queued_run(store: SQLiteStore, session_id: str, *, deadline: str) -> dict:
    message = store.create_user_message(session_id, new_id("run"), "问题")
    return store.create_run(session_id, message["id"], deadline, "{}")


def _answer() -> dict:
    return Answer(
        outcome="insufficient_evidence",
        language="zh-CN",
        support_level="insufficient",
        limitations=["没有证据"],
    ).model_dump(mode="json")


# --- 1.1 repositories -------------------------------------------------------------------------


def test_schema_version_and_mirrored_tables(tmp_path):
    store = SQLiteStore(tmp_path / "a.db")
    assert store.schema_version() == SCHEMA_VERSION
    tables = {
        row["name"] for row in store._all("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "assistant_sessions",
        "assistant_messages",
        "assistant_runs",
        "assistant_dependencies",
        "assistant_citations",
        "assistant_feedback",
        "knowledge_sources",
        "knowledge_versions",
        "knowledge_chunks",
        "idempotency_records",
        "outbox_events",
        "schema_meta",
    } <= tables


def test_a_newer_database_is_never_opened_by_an_older_binary(tmp_path):
    path = tmp_path / "a.db"
    SQLiteStore(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schema_meta SET value='99' WHERE key='schema_version'")
    with pytest.raises(RuntimeError):
        SQLiteStore(path)


def test_snapshots_are_immutable_and_ordered(tmp_path):
    store = SQLiteStore(tmp_path / "a.db")
    first = store.create_snapshot("ws", "doc-1", "first", "a" * 64, "user_a", "v1")
    second = store.create_snapshot("ws", "doc-1", "second", "b" * 64, "user_a", "v2")

    assert store.get_snapshot(first["id"])["text"] == "first"
    assert store.latest_snapshot("doc-1")["id"] == second["id"]
    assert not hasattr(store, "update_snapshot")


def test_session_message_and_citation_roundtrip(tmp_path):
    store = SQLiteStore(tmp_path / "a.db")
    session = _session(store)
    run = _queued_run(store, session["id"], deadline="2999-01-01T00:00:00+00:00")
    assert store.get_session(session["id"])["owner_user_id"] == "user_a"
    assert [row["id"] for row in store.list_messages(session["id"])] == [run["user_message_id"]]
    assert store.transition_run(run["id"], ("queued",), "running", stage="running")

    message = store.commit_answer(
        run_id=run["id"], answer=_answer(), citations=[], dependencies=[],
        audit={"event_type": "run_succeeded", "payload": {}}, finished_at=now_iso(),
    )
    assert message and store.get_run(run["id"])["status"] == "succeeded"
    assert store.list_messages(session["id"])[-1]["role"] == "assistant"
    assert store.commit_answer(
        run_id=run["id"], answer=_answer(), citations=[], dependencies=[],
        audit={"event_type": "run_succeeded"}, finished_at=now_iso(),
    ) is None


def test_one_active_run_per_session(tmp_path):
    store = SQLiteStore(tmp_path / "a.db")
    session = _session(store)
    _queued_run(store, session["id"], deadline="2999-01-01T00:00:00+00:00")
    with pytest.raises(SessionBusy):
        _queued_run(store, session["id"], deadline="2999-01-01T00:00:00+00:00")


def test_cas_transitions_reject_terminal_overwrite(tmp_path):
    store = SQLiteStore(tmp_path / "a.db")
    session = _session(store)
    run = _queued_run(store, session["id"], deadline="2999-01-01T00:00:00+00:00")
    assert store.transition_run(run["id"], ("queued",), "running", stage="running")
    assert store.cancel_run(run["id"], "2026-01-01T00:00:01+00:00")
    assert not store.cancel_run(run["id"], "2026-01-01T00:00:02+00:00")
    assert not store.transition_run(run["id"], ("running",), "succeeded", stage="completed")
    assert store.get_run(run["id"])["status"] == "cancelled"


def test_idempotency_records_are_per_principal(tmp_path):
    store = SQLiteStore(tmp_path / "a.db")
    store.put_idempotency("user_a", "POST", "/assistant/sessions", "k1", "hash", {"id": "s1"})
    assert store.get_idempotency("user_a", "POST", "/assistant/sessions", "k1")["request_hash"] == "hash"
    assert store.get_idempotency("user_b", "POST", "/assistant/sessions", "k1") is None


# --- 1.3 recovery -----------------------------------------------------------------------------


def test_restart_marks_overdue_runs_timed_out_and_active_runs_interrupted(tmp_path):
    path = tmp_path / "a.db"
    store = SQLiteStore(path)
    session = _session(store)
    overdue = _queued_run(store, session["id"], deadline="2000-01-01T00:00:00+00:00")
    future = _queued_run(
        store, _session(store, "user_b")["id"], deadline="2999-01-01T00:00:00+00:00"
    )

    reopened = SQLiteStore(path)
    assert reopened.get_run(overdue["id"])["status"] == "timed_out"
    assert reopened.get_run(future["id"])["status"] == "failed"
    assert "RUN_INTERRUPTED" in reopened.get_run(future["id"])["error_json"]


def test_seed_is_idempotent_and_only_published_versions_are_retrievable(tmp_path):
    store = SQLiteStore(tmp_path / "a.db")
    first = seed_knowledge(store)
    second = seed_knowledge(store)

    assert first == {"imported": 8, "published": 8}
    assert second == {"imported": 0, "published": 0}
    versions = store.list_knowledge_versions_all()
    assert {row["status"] for row in versions} == {"published"}
    assert all(row["reviewed_by"] != row["submitted_by"] for row in versions)
    assert {row["source_type"] for row in store.published_chunks()} == {
        "product_manual",
        "trade_rule",
        "internal_policy",
    }


def test_build_services_reconciles_an_older_local_database(tmp_path):
    path = tmp_path / "old.db"
    store = SQLiteStore(path)
    seed_knowledge(store)
    removed = (
        "KS-HELP-001",
        "KS-HELP-002",
        "KS-PRODUCT-001-EN",
        "KS-RULES-001-EN",
        "KS-POLICY-001-EN",
    )
    with store._lock, store._conn:
        for source_id in removed:
            store._conn.execute("DELETE FROM knowledge_chunks WHERE source_id = ?", (source_id,))
            store._conn.execute("DELETE FROM knowledge_versions WHERE source_id = ?", (source_id,))
            store._conn.execute("DELETE FROM knowledge_sources WHERE source_id = ?", (source_id,))

    services = build_services(db_path=path, mode="test")
    assert len(services.store.published_chunks()) == 74
    assert len(services.store.list_knowledge_versions_all()) == 8

    # Restarting again must not publish duplicates.
    build_services(db_path=path, mode="test")
    assert len(services.store.published_chunks()) == 74