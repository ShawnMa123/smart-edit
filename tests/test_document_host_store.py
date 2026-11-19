"""Document-host store: schema, drafts, checkpoints, locks and the production guard."""

from __future__ import annotations

import sqlite3

import pytest

from app.documents.bootstrap import build_host_services
from app.documents.errors import LockConflict, RevisionConflict
from app.documents.store import HostStore


def _store(tmp_path) -> HostStore:
    return HostStore(tmp_path / "host.db")


def _doc(store: HostStore, text: str = "Amount: USD 500,000.00") -> dict:
    return store.create_document(
        workspace_id="ws_demo_01", owner_user_id="user_a", title="Guarantee", text=text
    )


def test_schema_tables_and_version(tmp_path):
    store = _store(tmp_path)
    tables = {
        row["name"]
        for row in store.all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {
        "documents",
        "document_drafts",
        "document_checkpoints",
        "document_locks",
        "host_audit",
        "outbox_events",
        "idempotency_records",
        "automation_proposals",
        "automation_applications",
        "automation_runs",
        "automation_results",
        "automation_dependencies",
        "automation_reviews",
    } <= tables
    assert store.schema_version() == 3
    for table in ("documents", "document_drafts", "automation_proposals"):
        columns = {row["name"] for row in store.all(f"PRAGMA table_info({table})")}
        assert "department_id" in columns

    newer = sqlite3.connect(tmp_path / "host.db")
    newer.execute("UPDATE schema_meta SET value = '99' WHERE key = 'schema_version'")
    newer.commit()
    newer.close()
    with pytest.raises(RuntimeError):
        HostStore(tmp_path / "host.db")


def test_department_id_migration_is_idempotent_and_keeps_old_data(tmp_path):
    store = _store(tmp_path)
    document = store.create_document(
        workspace_id="ws_demo_01", owner_user_id="u1", title="Old", text="keep me"
    )
    # Simulate a v2 database: remove the new column from all three tables and lower the version.
    with store.transaction() as conn:
        for table in ("automation_proposals", "document_drafts", "documents"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN department_id")
        conn.execute("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'")
    store._conn.close()

    reopened = HostStore(tmp_path / "host.db")
    assert reopened.schema_version() == 3
    for table in ("documents", "document_drafts", "automation_proposals"):
        columns = {row["name"] for row in reopened.all(f"PRAGMA table_info({table})")}
        assert "department_id" in columns
    old = reopened.get_document(document["document_id"])
    assert old["title"] == "Old" and old["department_id"] is None
    assert reopened.get_draft(document["draft_id"])["text"] == "keep me"


def test_create_save_noop_and_checkpoint(tmp_path):
    store = _store(tmp_path)
    draft = _doc(store)
    assert draft["revision"] == 1
    assert draft["text"] == "Amount: USD 500,000.00"

    same = store.save_draft(
        draft_id=draft["draft_id"], expected_revision=1, text="Amount: USD 500,000.00", actor="user_a"
    )
    assert same["revision"] == 1
    assert len(store.list_checkpoints(draft["draft_id"])) == 1

    saved = store.save_draft(
        draft_id=draft["draft_id"], expected_revision=1, text="Amount: USD 600,000.00", actor="user_a"
    )
    assert saved["revision"] == 2
    assert saved["text"] == "Amount: USD 600,000.00"
    checkpoints = store.list_checkpoints(draft["draft_id"])
    assert [row["revision"] for row in checkpoints] == [1, 2]
    assert checkpoints[0]["text"] == "Amount: USD 500,000.00"


def test_stale_revision_is_rejected_without_a_write(tmp_path):
    store = _store(tmp_path)
    draft = _doc(store)
    store.save_draft(draft_id=draft["draft_id"], expected_revision=1, text="two", actor="user_a")
    with pytest.raises(RevisionConflict) as error:
        store.save_draft(
            draft_id=draft["draft_id"], expected_revision=1, text="three", actor="user_a"
        )
    assert error.value.status == 412
    assert error.value.detail["current_revision"] == 2
    assert store.get_draft(draft["draft_id"])["text"] == "two"


def test_variables_are_independent_and_checkpointed(tmp_path):
    store = _store(tmp_path)
    draft = store.create_document(
        workspace_id="ws_demo_01",
        owner_user_id="user_a",
        title="G",
        text="Amount: USD 500,000.00",
        variables={"guarantee_amount": "500000.00"},
    )
    checkpoint_before = store.list_checkpoints(draft["draft_id"])[0]
    store.save_draft(
        draft_id=draft["draft_id"], expected_revision=1, text="Amount: USD 600,000.00", actor="user_a"
    )
    after_text = store.get_draft(draft["draft_id"])
    assert after_text["variables_version"] == 1
    assert after_text["variables_json"] == '{"guarantee_amount": "500000.00"}'
    assert store.get_checkpoint(checkpoint_before["checkpoint_id"])["text"] == "Amount: USD 500,000.00"

    updated = store.update_variables(
        draft_id=draft["draft_id"],
        expected_variables_version=1,
        variables={"guarantee_amount": "600000.00"},
        actor="user_a",
    )
    assert updated["revision"] == 2
    assert updated["variables_version"] == 2
    latest = store.list_checkpoints(draft["draft_id"])[-1]
    assert latest["revision"] == 2
    assert latest["variables_version"] == 2
    assert latest["variables_json"] == '{"guarantee_amount": "600000.00"}'


def test_restore_creates_a_new_revision(tmp_path):
    store = _store(tmp_path)
    draft = _doc(store)
    store.save_draft(draft_id=draft["draft_id"], expected_revision=1, text="two", actor="user_a")
    first_checkpoint = store.list_checkpoints(draft["draft_id"])[0]
    restored = store.restore_checkpoint(
        draft_id=draft["draft_id"],
        checkpoint_id=first_checkpoint["checkpoint_id"],
        expected_revision=2,
        actor="user_a",
    )
    assert restored["revision"] == 3
    assert restored["text"] == "Amount: USD 500,000.00"
    assert store.get_checkpoint(first_checkpoint["checkpoint_id"])["text"] == "Amount: USD 500,000.00"


def test_locks_single_active_lease_and_fencing(tmp_path):
    store = _store(tmp_path)
    draft = _doc(store)
    lock = store.acquire_lock(draft_id=draft["draft_id"], owner_user_id="user_a", lease_seconds=30)
    assert lock["fencing_token"] == 1
    with pytest.raises(LockConflict):
        store.acquire_lock(draft_id=draft["draft_id"], owner_user_id="user_b")

    store.validate_lock(
        draft_id=draft["draft_id"], lock_id=lock["lock_id"], owner_user_id="user_a", fencing_token=1
    )
    with pytest.raises(LockConflict):
        store.validate_lock(
            draft_id=draft["draft_id"], lock_id=lock["lock_id"], owner_user_id="user_a", fencing_token=2
        )

    store.release_lock(lock_id=lock["lock_id"], owner_user_id="user_a")
    second = store.acquire_lock(draft_id=draft["draft_id"], owner_user_id="user_b", lease_seconds=30)
    assert second["fencing_token"] == 2
    store.release_lock(lock_id=second["lock_id"], owner_user_id="user_b")
    expired = store.acquire_lock(draft_id=draft["draft_id"], owner_user_id="user_a", lease_seconds=0)
    assert expired["fencing_token"] == 3


def test_production_uses_no_local_adapter(tmp_path):
    with pytest.raises(RuntimeError):
        build_host_services(db_path=tmp_path / "host.db", mode="production")