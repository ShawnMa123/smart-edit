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

from app.documents.errors import HostError, HostNotFound, LockConflict, RevisionConflict
from app.documents.projection import plain_text_document, project_document, sha256_text

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  title TEXT NOT NULL, created_at TEXT NOT NULL, department_id TEXT);
CREATE TABLE IF NOT EXISTS document_drafts (
  draft_id TEXT PRIMARY KEY, document_id TEXT NOT NULL UNIQUE, workspace_id TEXT NOT NULL,
  revision INTEGER NOT NULL, content_json TEXT NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL,
  variables_json TEXT NOT NULL DEFAULT '{}', variables_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  department_id TEXT,
  FOREIGN KEY (document_id) REFERENCES documents(document_id));
CREATE TABLE IF NOT EXISTS document_checkpoints (
  checkpoint_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
  content_json TEXT NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL, variables_json TEXT NOT NULL DEFAULT '{}',
  variables_version INTEGER NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE (draft_id, revision, variables_version),
  FOREIGN KEY (draft_id) REFERENCES document_drafts(draft_id));
CREATE TABLE IF NOT EXISTS document_locks (
  lock_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  session_id TEXT, lease_until TEXT NOT NULL, fencing_token INTEGER NOT NULL,
  released_at TEXT, created_at TEXT NOT NULL,
  FOREIGN KEY (draft_id) REFERENCES document_drafts(draft_id));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_lock ON document_locks(draft_id)
  WHERE released_at IS NULL;
CREATE TABLE IF NOT EXISTS document_submissions (
  submission_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, draft_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL, department_id TEXT, submitted_by TEXT NOT NULL,
  revision INTEGER NOT NULL, content_sha256 TEXT NOT NULL, content_json TEXT NOT NULL,
  text TEXT NOT NULL, variables_json TEXT NOT NULL DEFAULT '{}', variables_version INTEGER NOT NULL,
  status TEXT NOT NULL, request_id TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS document_submissions_document_idx
  ON document_submissions(document_id, created_at DESC);
CREATE TABLE IF NOT EXISTS approval_requests (
  request_id TEXT PRIMARY KEY, submission_id TEXT NOT NULL UNIQUE, document_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL, department_id TEXT, submitted_by TEXT NOT NULL,
  status TEXT NOT NULL, current_stage TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, decided_at TEXT);
CREATE INDEX IF NOT EXISTS approval_requests_pending_idx
  ON approval_requests(workspace_id, status, created_at);
CREATE TABLE IF NOT EXISTS approval_steps (
  step_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, stage TEXT NOT NULL,
  decision TEXT NOT NULL, actor_user_id TEXT NOT NULL, comment TEXT,
  expected_revision INTEGER NOT NULL, created_at TEXT NOT NULL, decided_at TEXT NOT NULL,
  UNIQUE (request_id, stage),
  FOREIGN KEY (request_id) REFERENCES approval_requests(request_id) ON DELETE CASCADE);
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
  expires_at TEXT NOT NULL, created_at TEXT NOT NULL, department_id TEXT,
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
CREATE TABLE IF NOT EXISTS automation_runs (
  run_id TEXT PRIMARY KEY, task_type TEXT NOT NULL, document_id TEXT NOT NULL, draft_id TEXT NOT NULL,
  owner_user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, deadline_at TEXT NOT NULL,
  started_at TEXT, finished_at TEXT, result_id TEXT, request_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT);
CREATE TABLE IF NOT EXISTS automation_results (
  result_id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, completion TEXT NOT NULL,
  outcome TEXT NOT NULL, payload_json TEXT NOT NULL, limitations_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES automation_runs(run_id));
CREATE TABLE IF NOT EXISTS automation_dependencies (
  owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL, version TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (owner_type, owner_id, resource_type, resource_id));
CREATE TABLE IF NOT EXISTS automation_reviews (
  review_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, context_hash TEXT NOT NULL,
  verdict TEXT NOT NULL, validator_version TEXT NOT NULL, issues_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  FOREIGN KEY (proposal_id) REFERENCES automation_proposals(proposal_id));
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
            self._migrate(found)

    def _migrate(self, found: int) -> None:
        with self.transaction() as conn:
            if found < 2:
                conn.execute("ALTER TABLE document_checkpoints RENAME TO document_checkpoints_v1")
                conn.execute(
                    "CREATE TABLE document_checkpoints ("
                    " checkpoint_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,"
                    " content_json TEXT NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL,"
                    " variables_json TEXT NOT NULL DEFAULT '{}', variables_version INTEGER NOT NULL,"
                    " created_by TEXT NOT NULL, created_at TEXT NOT NULL,"
                    " UNIQUE (draft_id, revision, variables_version),"
                    " FOREIGN KEY (draft_id) REFERENCES document_drafts(draft_id))"
                )
                conn.execute(
                    "INSERT INTO document_checkpoints SELECT checkpoint_id, draft_id, revision,"
                    " content_json, text, text_sha256, variables_json, variables_version, created_by,"
                    " created_at FROM document_checkpoints_v1"
                )
                conn.execute("DROP TABLE document_checkpoints_v1")
            if found < 3:
                # `department_id` is nullable on purpose: NULL means organisation-level (design D4).
                # The guard makes the migration idempotent even after a partial manual run.
                for table in ("documents", "document_drafts", "automation_proposals"):
                    columns = {
                        row["name"]
                        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    }
                    if "department_id" not in columns:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN department_id TEXT")
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
        department_id: str | None = None,
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
                "INSERT INTO documents (document_id, workspace_id, owner_user_id, title, created_at, "
                "department_id) VALUES (?,?,?,?,?,?)",
                (document_id, workspace_id, owner_user_id, title, stamp, department_id),
            )
            conn.execute(
                "INSERT INTO document_drafts (draft_id, document_id, workspace_id, revision, "
                "content_json, text, text_sha256, variables_json, variables_version, created_at, "
                "updated_at, department_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    department_id,
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
        current_variables_json = current["variables_json"]
        variables_json = (
            current_variables_json
            if variables is None
            else json.dumps(variables, sort_keys=True, ensure_ascii=False)
        )
        variables_changed = variables_json != current_variables_json
        new_variables_version = int(current["variables_version"]) + (1 if variables_changed else 0)

        if current["revision"] != expected_revision:
            raise RevisionConflict(current)
        if current["text_sha256"] == content_sha and not variables_changed:
            return current

        stamp = now_iso()
        new_revision = expected_revision + 1
        checkpoint_id = new_id("ckpt")
        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE document_drafts SET revision=?, content_json=?, text=?, text_sha256=?,"
                " variables_json=?, variables_version=?, updated_at=?"
                " WHERE draft_id=? AND revision=? AND text_sha256=? AND variables_json=?",
                (
                    new_revision,
                    json.dumps(payload, ensure_ascii=False),
                    projection.text,
                    content_sha,
                    variables_json,
                    new_variables_version,
                    stamp,
                    draft_id,
                    expected_revision,
                    current["text_sha256"],
                    current_variables_json,
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
                    new_variables_version,
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

    def update_variables(
        self,
        *,
        draft_id: str,
        expected_variables_version: int,
        variables: dict[str, Any],
        actor: str,
        request_id: str = "",
    ) -> dict[str, Any]:
        current = self.get_draft(draft_id)
        if not current:
            raise HostNotFound("draft not found")
        variables_json = json.dumps(variables, sort_keys=True, ensure_ascii=False)
        if int(current["variables_version"]) != int(expected_variables_version):
            raise HostError(
                412,
                "stale_variables",
                "the variables moved since this update was based on them",
                {"current_variables_version": int(current["variables_version"])},
            )
        if current["variables_json"] == variables_json:
            return current

        stamp = now_iso()
        new_version = int(current["variables_version"]) + 1
        checkpoint_id = new_id("ckpt")
        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE document_drafts SET variables_json=?, variables_version=?, updated_at=?"
                " WHERE draft_id=? AND variables_version=?",
                (variables_json, new_version, stamp, draft_id, expected_variables_version),
            )
            if updated.rowcount != 1:
                latest = self.get_draft(draft_id)
                raise HostError(
                    412,
                    "stale_variables",
                    "the variables moved during this update",
                    {"current_variables_version": int((latest or current)["variables_version"])},
                )
            conn.execute(
                "INSERT INTO document_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    checkpoint_id,
                    draft_id,
                    int(current["revision"]),
                    current["content_json"],
                    current["text"],
                    current["text_sha256"],
                    variables_json,
                    new_version,
                    actor,
                    stamp,
                ),
            )
            self._audit(
                conn,
                request_id,
                "variables_saved",
                actor,
                {"draft_id": draft_id, "variables_version": new_version},
            )
            self._enqueue(
                conn, "draft.variables_saved", {"draft_id": draft_id, "variables_version": new_version}
            )
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

    # --- submissions and approvals -------------------------------------------------------------
    def latest_submission(self, document_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM document_submissions WHERE document_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (document_id,),
        )

    def blocking_submission(self, document_id: str) -> dict[str, Any] | None:
        """A submission that makes the document read-only for the applicant."""
        return self.one(
            "SELECT * FROM document_submissions WHERE document_id = ? "
            "AND status IN ('pending_first', 'pending_second', 'approved') "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (document_id,),
        )

    def list_submissions(self, document_id: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM document_submissions WHERE document_id = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (document_id,),
        )

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM document_submissions WHERE submission_id = ?", (submission_id,)
        )

    def latest_request(self, document_id: str) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM approval_requests WHERE document_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (document_id,),
        )

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,))

    def list_steps(self, request_id: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM approval_steps WHERE request_id = ? ORDER BY created_at ASC", (request_id,)
        )

    def list_pending_approvals(
        self, workspace_id: str, statuses: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        return self.all(
            "SELECT r.*, s.revision AS snapshot_revision, s.content_sha256 AS snapshot_sha256, "
            "s.submitted_by AS snapshot_submitted_by, d.title, d.department_id "
            "FROM approval_requests r "
            "JOIN document_submissions s ON s.submission_id = r.submission_id "
            "JOIN documents d ON d.document_id = r.document_id "
            f"WHERE r.workspace_id = ? AND r.status IN ({placeholders}) "
            "ORDER BY r.created_at ASC",
            (workspace_id, *statuses),
        )

    def create_submission(
        self,
        *,
        document_id: str,
        draft_id: str,
        submitted_by: str,
        lock_id: str,
        fencing_token: int,
        expected_revision: int,
        expected_sha256: str | None,
        audit_request_id: str = "",
    ) -> dict[str, Any]:
        stamp = now_iso()
        with self.transaction() as conn:
            document = conn.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            draft = conn.execute(
                "SELECT * FROM document_drafts WHERE draft_id = ? AND document_id = ?",
                (draft_id, document_id),
            ).fetchone()
            if document is None or draft is None:
                raise HostNotFound("document or draft not found")
            if int(draft["revision"]) != int(expected_revision):
                raise HostError(
                    409,
                    "stale_revision",
                    "the draft moved since the submission was prepared",
                    {"current_revision": int(draft["revision"])},
                )
            if expected_sha256 and draft["text_sha256"] != expected_sha256:
                raise HostError(409, "stale_content", "the draft content changed before submission")
            lock = conn.execute(
                "SELECT * FROM document_locks WHERE lock_id = ? AND draft_id = ?",
                (lock_id, draft_id),
            ).fetchone()
            if lock is None:
                raise LockConflict("the lock does not belong to this draft")
            if lock["released_at"] is not None:
                raise LockConflict("the lock was released")
            if lock["owner_user_id"] != submitted_by:
                raise LockConflict("the lock is owned by another user")
            if _parse_time(lock["lease_until"]) <= _parse_time(stamp):
                raise LockConflict("the lock lease expired")
            if int(lock["fencing_token"]) != int(fencing_token):
                raise LockConflict("the fencing token is stale")
            active = conn.execute(
                "SELECT status FROM document_submissions WHERE document_id = ? "
                "AND status IN ('pending_first', 'pending_second', 'approved') LIMIT 1",
                (document_id,),
            ).fetchone()
            if active is not None:
                raise HostError(
                    409,
                    "submission_pending",
                    "this document already has an active submission",
                    {"status": active["status"]},
                )
            submission_id = new_id("sub")
            request_id = new_id("apr")
            submission = {
                "submission_id": submission_id,
                "document_id": document_id,
                "draft_id": draft_id,
                "workspace_id": document["workspace_id"],
                "department_id": document["department_id"],
                "submitted_by": submitted_by,
                "revision": int(draft["revision"]),
                "content_sha256": draft["text_sha256"],
                "content_json": draft["content_json"],
                "text": draft["text"],
                "variables_json": draft["variables_json"],
                "variables_version": int(draft["variables_version"]),
                "status": "pending_first",
                "request_id": request_id,
                "created_at": stamp,
            }
            request = {
                "request_id": request_id,
                "submission_id": submission_id,
                "document_id": document_id,
                "workspace_id": document["workspace_id"],
                "department_id": document["department_id"],
                "submitted_by": submitted_by,
                "status": "pending_first",
                "current_stage": "first",
                "revision": 1,
                "created_at": stamp,
                "updated_at": stamp,
                "decided_at": None,
            }
            conn.execute(
                "INSERT INTO document_submissions VALUES (:submission_id,:document_id,:draft_id,"
                ":workspace_id,:department_id,:submitted_by,:revision,:content_sha256,"
                ":content_json,:text,:variables_json,:variables_version,:status,:request_id,:created_at)",
                submission,
            )
            conn.execute(
                "INSERT INTO approval_requests VALUES (:request_id,:submission_id,:document_id,"
                ":workspace_id,:department_id,:submitted_by,:status,:current_stage,:revision,"
                ":created_at,:updated_at,:decided_at)",
                request,
            )
            released = conn.execute(
                "UPDATE document_locks SET released_at = ? WHERE lock_id = ? "
                "AND owner_user_id = ? AND released_at IS NULL",
                (stamp, lock_id, submitted_by),
            )
            if released.rowcount != 1:
                raise LockConflict("the lock could not be released")
            self._audit(
                conn,
                audit_request_id,
                "submission_created",
                submitted_by,
                {
                    "submission_id": submission_id,
                    "request_id": request_id,
                    "document_id": document_id,
                    "revision": int(draft["revision"]),
                    "status": "pending_first",
                },
            )
            self._enqueue(
                conn,
                "submission.created",
                {"submission_id": submission_id, "request_id": request_id},
            )
        return {"submission": submission, "request": request}

    def decide_approval(
        self,
        *,
        request_id: str,
        stage: str,
        decision: str,
        actor_user_id: str,
        comment: str | None,
        expected_revision: int,
        audit_request_id: str = "",
    ) -> dict[str, Any]:
        stamp = now_iso()
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise HostNotFound("approval request not found")
            request = dict(row)
            if request["status"] in ("approved", "returned", "rejected"):
                raise HostError(409, "approval_closed", "this approval request is already closed")
            if request["current_stage"] != stage or request["status"] != f"pending_{stage}":
                raise HostError(
                    409,
                    "wrong_stage",
                    "this decision does not belong to the current approval stage",
                    {"stage": request["current_stage"]},
                )
            if int(request["revision"]) != int(expected_revision):
                raise HostError(
                    409,
                    "stale_approval",
                    "the approval request moved since it was loaded",
                    {"current_revision": int(request["revision"])},
                )
            if actor_user_id == request["submitted_by"]:
                raise HostError(403, "self_approval", "you cannot decide your own submission")
            if decision in ("return", "reject") and not (comment or "").strip():
                raise HostError(422, "comment_required", "a comment is required for return/reject")
            if decision == "approve":
                if stage == "first":
                    status, current_stage = "pending_second", "second"
                else:
                    status, current_stage = "approved", "second"
            elif decision == "return":
                status, current_stage = "returned", stage
            elif decision == "reject":
                status, current_stage = "rejected", stage
            else:
                raise HostError(422, "invalid_decision", "decision must be approve, return or reject")
            closed_at = stamp if status in ("approved", "returned", "rejected") else None
            step = {
                "step_id": new_id("step"),
                "request_id": request_id,
                "stage": stage,
                "decision": decision,
                "actor_user_id": actor_user_id,
                "comment": (comment or "").strip() or None,
                "expected_revision": int(expected_revision),
                "created_at": stamp,
                "decided_at": stamp,
            }
            conn.execute(
                "INSERT INTO approval_steps VALUES (:step_id,:request_id,:stage,:decision,"
                ":actor_user_id,:comment,:expected_revision,:created_at,:decided_at)",
                step,
            )
            updated = conn.execute(
                "UPDATE approval_requests SET status=?, current_stage=?, revision=revision+1, "
                "updated_at=?, decided_at=? WHERE request_id=? AND revision=?",
                (status, current_stage, stamp, closed_at, request_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise HostError(
                    409,
                    "stale_approval",
                    "the approval request moved during the decision",
                    {"current_revision": int(request["revision"]) + 1},
                )
            conn.execute(
                "UPDATE document_submissions SET status = ? WHERE submission_id = ?",
                (status, request["submission_id"]),
            )
            self._audit(
                conn,
                audit_request_id,
                f"approval_{decision}",
                actor_user_id,
                {
                    "request_id": request_id,
                    "stage": stage,
                    "decision": decision,
                    "status": status,
                },
            )
            self._enqueue(
                conn,
                f"approval.{stage}.{decision}",
                {"request_id": request_id, "status": status},
            )
        return {"request": self.get_request(request_id) or {}, "step": step}
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