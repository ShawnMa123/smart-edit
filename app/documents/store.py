"""SQLite storage for the local document host and the minimal automation contract.

One database (`runs/host.db` by default) holds documents, drafts, checkpoints, locks, audit,
outbox, idempotency records and automation proposals/receipts. Every mutation that spans tables
uses `BEGIN IMMEDIATE`; the host is a single-process, single-writer local adapter.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.documents.errors import HostNotFound, LockConflict, RevisionConflict
from app.documents.projection import plain_text_document, project_document, sha256_text

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  title TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_drafts (
  draft_id TEXT PRIMARY KEY, document_id TEXT NOT NULL UNIQUE, workspace_id TEXT NOT NULL,
  revision INTEGER NOT NULL, content_json TEXT NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL,
  variables_json TEXT NOT NULL DEFAULT '{}', variables_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  FOREIGN KEY (document_id) REFERENCES documents(document_id));
CREATE TABLE IF NOT EXISTS document_checkpoints (
  checkpoint_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
  content_json TEXT NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL, variables_json TEXT NOT NULL DEFAULT '{}',
  variables_version INTEGER NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (draft_id, revision),
  FOREIGN KEY (draft_id) REFERENCES document_drafts(draft_id));
CREATE TABLE IF NOT EXISTS document_locks (
  lock_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  session_id TEXT, lease_until TEXT NOT NULL, fencing_token INTEGER NOT NULL,
  released_at TEXT, created_at TEXT NOT NULL,
  FOREIGN KEY (draft_id) REFERENCES document_drafts(draft_id));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_lock ON document_locks(draft_id)
  WHERE released_at IS NULL;
CREATE TABLE IF NOT EXISTS host_audit (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox_events (
  id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, delivered_at TEXT);
CREATE TABLE IF NOT EXISTS idempotency_records (
  principal TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, key TEXT NOT NULL,
  request_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (principal, method, path, key));
CREATE TABLE IF NOT EXISTS automation_proposals (
  proposal_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, draft_id TEXT NOT NULL,
  owner_user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, context_json TEXT NOT NULL,
  operations_json TEXT NOT NULL, preview_json TEXT NOT NULL, risk_flags_json TEXT NOT NULL DEFAULT '[]',
  review_json TEXT NOT NULL, disposition TEXT NOT NULL DEFAULT 'open',
  application_status TEXT NOT NULL DEFAULT 'not_applied', revision INTEGER NOT NULL DEFAULT 1,
  expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
  FOREIGN KEY (draft_id) REFERENCES document_drafts(draft_id));
CREATE TABLE IF NOT EXISTS automation_proposal_events (
  event_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, decision TEXT NOT NULL,
  actor TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL,
  FOREIGN KEY (proposal_id) REFERENCES automation_proposals(proposal_id));
CREATE TABLE IF NOT EXISTS automation_applications (
  receipt_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, draft_id TEXT NOT NULL,
  actor_user_id TEXT NOT NULL, previous_revision INTEGER NOT NULL, new_revision INTEGER NOT NULL,
  new_checkpoint_id TEXT NOT NULL, content_sha256 TEXT NOT NULL, variables_version INTEGER NOT NULL,
  inverse_operations_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'applied',
  reversal_of_receipt_id TEXT, applied_at TEXT NOT NULL,
  FOREIGN KEY (proposal_id) REFERENCES automation_proposals(proposal_id));
CREATE UNIQUE INDEX IF NOT EXISTS one_applied_application ON automation_applications(proposal_id)
  WHERE status = 'applied';
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


class HostStore:
    def __init__(self, path: str | Path = "runs/host.db") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._check_schema_version()

    def _check_schema_version(self) -> None:
        row = self.one("SELECT value FROM schema_meta WHERE key = 'schema_version'")
        if row is None:
            with self.transaction() as conn:
                conn.execute(
                    "INSERT INTO schema_meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
                )
            return
        found = int(row["value"])
        if found > SCHEMA_VERSION:
            raise RuntimeError(
                f"host database schema v{found} is newer than this build (v{SCHEMA_VERSION})"
            )
        if found < SCHEMA_VERSION:
            with self.transaction() as conn:
                conn.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                    (str(SCHEMA_VERSION),),
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def schema_version(self) -> int:
        row = self.one("SELECT value FROM schema_meta WHERE key = 'schema_version'")
        return int(row["value"]) if row else 0

    # --- documents and drafts -----------------------------------------------------------------
    def create_document(
        self,
        *,
        workspace_id: str,
        owner_user_id: str,
        title: str,
        content: dict[str, Any] | None = None,
        text: str | None = None,
        variables: dict[str, Any] | None = None,
        document_id: str | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        document_id = document_id or new_id("doc")
        draft_id = new_id("draft")
        payload = content or plain_text_document(text or "")
        projection = project_document(payload)
        stamp = now_iso()
        variables_json = json.dumps(variables or {}, sort_keys=True, ensure_ascii=False)
        actor = created_by or owner_user_id
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?)",
                (document_id, workspace_id, owner_user_id, title, stamp),
            )
            conn.execute(
                "INSERT INTO document_drafts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    draft_id,
                    document_id,
                    workspace_id,
                    1,
                    json.dumps(payload, ensure_ascii=False),
                    projection.text,
                    sha256_text(projection.text),
                    variables_json,
                    1,
                    stamp,
                    stamp,
                ),
            )
            conn.execute(
                "INSERT INTO document_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("ckpt"),
                    draft_id,
                    1,
                    json.dumps(payload, ensure_ascii=False),
                    projection.text,
                    sha256_text(projection.text),
                    variables_json,
                    1,
                    actor,
                    stamp,
                ),
            )
            self._audit(conn, "", "document_created", actor, {"document_id": document_id, "draft_id": draft_id})
        return self.get_draft(draft_id) or {}

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM documents WHERE document_id = ?", (document_id,))

    def find_draft_by_document(self, document_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM document_drafts WHERE document_id = ?", (document_id,))

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM document_drafts WHERE draft_id = ?", (draft_id,))

    def get_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM document_checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))

    def list_checkpoints(self, draft_id: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM document_checkpoints WHERE draft_id = ? ORDER BY revision ASC", (draft_id,)
        )

    def save_draft(
        self,
        *,
        draft_id: str,
        expected_revision: int,
        content: dict[str, Any] | None = None,
        text: str | None = None,
        variables: dict[str, Any] | None = None,
        actor: str,
        request_id: str = "",
    ) -> dict[str, Any]:
        current = self.get_draft(draft_id)
        if not current:
            raise HostNotFound("draft not found")
        payload = content or plain_text_document(text or "")
        projection = project_document(payload)
        content_sha = sha256_text(projection.text)
        variables_json = json.dumps(variables or {}, sort_keys=True, ensure_ascii=False)

        if current["revision"] != expected_revision:
            raise RevisionConflict(current)
        if current["text_sha256"] == content_sha and current["variables_json"] == variables_json:
            return current

        stamp = now_iso()
        new_revision = expected_revision + 1
        checkpoint_id = new_id("ckpt")
        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE document_drafts SET revision=?, content_json=?, text=?, text_sha256=?,"
                " variables_json=?, variables_version=variables_version+1, updated_at=?"
                " WHERE draft_id=? AND revision=? AND text_sha256=? AND variables_json=?",
                (
                    new_revision,
                    json.dumps(payload, ensure_ascii=False),
                    projection.text,
                    content_sha,
                    variables_json,
                    stamp,
                    draft_id,
                    expected_revision,
                    current["text_sha256"],
                    current["variables_json"],
                ),
            )
            if updated.rowcount != 1:
                latest = self.get_draft(draft_id)
                if not latest:
                    raise HostNotFound("draft not found")
                raise RevisionConflict(latest)
            conn.execute(
                "INSERT INTO document_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    checkpoint_id,
                    draft_id,
                    new_revision,
                    json.dumps(payload, ensure_ascii=False),
                    projection.text,
                    content_sha,
                    variables_json,
                    int(current["variables_version"]) + 1,
                    actor,
                    stamp,
                ),
            )
            self._audit(
                conn,
                request_id,
                "draft_saved",
                actor,
                {"draft_id": draft_id, "revision": new_revision, "content_sha256": content_sha},
            )
            self._enqueue(conn, "draft.saved", {"draft_id": draft_id, "revision": new_revision})
        return self.get_draft(draft_id) or {}

    def restore_checkpoint(
        self,
        *,
        draft_id: str,
        checkpoint_id: str,
        expected_revision: int,
        actor: str,
        request_id: str = "",
    ) -> dict[str, Any]:
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint or checkpoint["draft_id"] != draft_id:
            raise HostNotFound("checkpoint not found")
        return self.save_draft(
            draft_id=draft_id,
            expected_revision=expected_revision,
            content=json.loads(checkpoint["content_json"]),
            variables=json.loads(checkpoint["variables_json"]),
            actor=actor,
            request_id=request_id,
        )

    # --- locks ---------------------------------------------------------------------------------
    def active_lock(self, draft_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM document_locks WHERE draft_id = ? AND released_at IS NULL", (draft_id,)
        )

    def acquire_lock(
        self,
        *,
        draft_id: str,
        owner_user_id: str,
        session_id: str | None = None,
        lease_seconds: int = 30,
    ) -> dict[str, Any]:
        draft = self.get_draft(draft_id)
        if not draft:
            raise HostNotFound("draft not found")
        now = now_iso()
        now_dt = _parse_time(now)
        with self.transaction() as conn:
            active = conn.execute(
                "SELECT * FROM document_locks WHERE draft_id = ? AND released_at IS NULL", (draft_id,)
            ).fetchone()
            if active:
                row = dict(active)
                if row["owner_user_id"] != owner_user_id:
                    raise LockConflict("another user holds this draft's lock")
                if _parse_time(row["lease_until"]) > now_dt:
                    return row
                conn.execute(
                    "UPDATE document_locks SET released_at = ? WHERE lock_id = ?",
                    (now, row["lock_id"]),
                )
            token_row = conn.execute(
                "SELECT COALESCE(MAX(fencing_token), 0) AS token FROM document_locks WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            token = int(token_row["token"]) + 1
            lock = {
                "lock_id": new_id("lock"),
                "draft_id": draft_id,
                "owner_user_id": owner_user_id,
                "session_id": session_id,
                "lease_until": (now_dt + timedelta(seconds=lease_seconds)).isoformat(),
                "fencing_token": token,
                "released_at": None,
                "created_at": now,
            }
            conn.execute(
                "INSERT INTO document_locks VALUES (:lock_id,:draft_id,:owner_user_id,:session_id,"
                ":lease_until,:fencing_token,:released_at,:created_at)",
                lock,
            )
        return lock

    def heartbeat_lock(
        self, *, lock_id: str, owner_user_id: str, lease_seconds: int = 30
    ) -> dict[str, Any]:
        now_dt = datetime.now(timezone.utc)
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as conn:
            result = conn.execute(
                "UPDATE document_locks SET lease_until=? WHERE lock_id=? AND owner_user_id=?"
                " AND released_at IS NULL",
                (lease, lock_id, owner_user_id),
            )
            if result.rowcount != 1:
                raise LockConflict("the lock is missing, released or owned by someone else")
        lock = self.one("SELECT * FROM document_locks WHERE lock_id = ?", (lock_id,))
        if not lock:
            raise LockConflict("the lock is missing")
        return lock

    def release_lock(self, *, lock_id: str, owner_user_id: str) -> dict[str, Any]:
        stamp = now_iso()
        with self.transaction() as conn:
            result = conn.execute(
                "UPDATE document_locks SET released_at=? WHERE lock_id=? AND owner_user_id=?"
                " AND released_at IS NULL",
                (stamp, lock_id, owner_user_id),
            )
            if result.rowcount != 1:
                raise LockConflict("the lock is missing, released or owned by someone else")
        lock = self.one("SELECT * FROM document_locks WHERE lock_id = ?", (lock_id,))
        if not lock:
            raise HostNotFound("lock not found")
        return lock

    def validate_lock(
        self, *, draft_id: str, lock_id: str, owner_user_id: str, fencing_token: int
    ) -> dict[str, Any]:
        lock = self.one("SELECT * FROM document_locks WHERE lock_id = ?", (lock_id,))
        if not lock or lock["draft_id"] != draft_id:
            raise LockConflict("the lock does not belong to this draft")
        if lock["released_at"] is not None:
            raise LockConflict("the lock was released")
        if lock["owner_user_id"] != owner_user_id:
            raise LockConflict("the lock is owned by another user")
        if _parse_time(lock["lease_until"]) <= datetime.now(timezone.utc):
            raise LockConflict("the lock lease expired")
        if int(lock["fencing_token"]) != int(fencing_token):
            raise LockConflict("the fencing token is stale")
        return lock

    # --- audit / outbox / idempotency ----------------------------------------------------------
    def _audit(
        self,
        conn: sqlite3.Connection,
        request_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO host_audit VALUES (?,?,?,?,?,?)",
            (
                new_id("audit"),
                request_id,
                event_type,
                actor,
                json.dumps(payload, ensure_ascii=False),
                now_iso(),
            ),
        )

    def _enqueue(self, conn: sqlite3.Connection, event_type: str, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO outbox_events VALUES (?,?,?,?,NULL)",
            (new_id("evt"), event_type, json.dumps(payload, ensure_ascii=False), now_iso()),
        )

    def append_audit(
        self, *, request_id: str, event_type: str, actor: str, payload: dict[str, Any]
    ) -> None:
        with self.transaction() as conn:
            self._audit(conn, request_id, event_type, actor, payload)

    def enqueue_event(self, event_type: str, payload: dict[str, Any]) -> None:
        with self.transaction() as conn:
            self._enqueue(conn, event_type, payload)

    def list_outbox(self) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM outbox_events ORDER BY created_at ASC")

    def get_idempotency(
        self, principal: str, method: str, path: str, key: str
    ) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM idempotency_records WHERE principal=? AND method=? AND path=? AND key=?",
            (principal, method, path, key),
        )

    def put_idempotency(
        self,
        principal: str,
        method: str,
        path: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO idempotency_records VALUES (?,?,?,?,?,?,?)",
                (
                    principal,
                    method,
                    path,
                    key,
                    request_hash,
                    json.dumps(response, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def put_idempotency_conn(
        self,
        conn: sqlite3.Connection,
        principal: str,
        method: str,
        path: str,
        key: str,
        request_hash: str,
        response: dict[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO idempotency_records VALUES (?,?,?,?,?,?,?)",
            (
                principal,
                method,
                path,
                key,
                request_hash,
                json.dumps(response, ensure_ascii=False),
                now_iso(),
            ),
        )


__all__ = ["HostStore", "SCHEMA_VERSION", "new_id", "now_iso"]