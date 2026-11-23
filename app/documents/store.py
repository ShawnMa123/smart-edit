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

SCHEMA_VERSION = 13

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  title TEXT NOT NULL, created_at TEXT NOT NULL, department_id TEXT,
  template_id TEXT, template_name TEXT);
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
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, decided_at TEXT,
  route TEXT NOT NULL DEFAULT 'bank_first');
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
CREATE TABLE IF NOT EXISTS automation_templates (
  template_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
  version TEXT NOT NULL, source_kind TEXT NOT NULL, source_note TEXT,
  text TEXT NOT NULL, content_json TEXT, variables_json TEXT NOT NULL DEFAULT '[]',
  variables_source TEXT, document_id TEXT, created_by TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, department_id TEXT,
  UNIQUE (workspace_id, name, version));
CREATE TABLE IF NOT EXISTS automation_connectors (
  connector_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
  base_url TEXT NOT NULL, method TEXT NOT NULL DEFAULT 'POST', path TEXT NOT NULL,
  auth_kind TEXT NOT NULL DEFAULT 'none', auth_header TEXT, secret_env TEXT,
  timeout_seconds INTEGER NOT NULL DEFAULT 10, extra_headers_json TEXT NOT NULL DEFAULT '{}',
  spec_json TEXT, operation TEXT, body_map_json TEXT NOT NULL DEFAULT '{}',
  body_map_configured INTEGER NOT NULL DEFAULT 0, fields_json TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, disabled_at TEXT,
  department_id TEXT);
CREATE TABLE IF NOT EXISTS automation_dispatches (
  dispatch_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, template_id TEXT,
  connector_id TEXT NOT NULL, document_id TEXT, status TEXT NOT NULL, status_code INTEGER,
  latency_ms INTEGER, request_json TEXT NOT NULL, response_json TEXT, error_code TEXT,
  idempotency_key TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
  job_id TEXT, rule_id TEXT, trigger TEXT, submission_id TEXT);
CREATE TABLE IF NOT EXISTS automation_jobs (
  job_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, rule_id TEXT NOT NULL,
  document_id TEXT NOT NULL, submission_id TEXT NOT NULL, template_id TEXT NOT NULL,
  connector_id TEXT NOT NULL, status TEXT NOT NULL, mode TEXT NOT NULL, required INTEGER NOT NULL DEFAULT 1,
  idempotency_key TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT, request_json TEXT, response_excerpt TEXT, error_code TEXT,
  receipt_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (workspace_id, idempotency_key));
CREATE INDEX IF NOT EXISTS automation_jobs_due
  ON automation_jobs(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS automation_jobs_doc
  ON automation_jobs(document_id, created_at);
CREATE TABLE IF NOT EXISTS automation_job_events (
  event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, from_status TEXT,
  to_status TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS automation_job_events_job
  ON automation_job_events(job_id, created_at);
CREATE INDEX IF NOT EXISTS automation_templates_ws ON automation_templates(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS automation_connectors_ws ON automation_connectors(workspace_id, created_at);
CREATE TABLE IF NOT EXISTS automation_mappings (
  template_id TEXT NOT NULL, connector_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
  body_map_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
  PRIMARY KEY (template_id, connector_id));
CREATE INDEX IF NOT EXISTS automation_dispatches_ws ON automation_dispatches(workspace_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS automation_dispatches_idem
  ON automation_dispatches(workspace_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS automation_rules (
  rule_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, department_id TEXT,
  name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, priority INTEGER NOT NULL DEFAULT 100,
  required INTEGER NOT NULL DEFAULT 1, template_name TEXT NOT NULL, connector_id TEXT NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'final_approval', mode TEXT NOT NULL DEFAULT 'shadow',
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, disabled_at TEXT);
CREATE INDEX IF NOT EXISTS automation_rules_ws
  ON automation_rules(workspace_id, template_name, enabled);
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
            if found < 5:
                # OpenAPI-driven dispatch (automation-template-registry D6): the connector carries the
                # downstream's own schema, the chosen operation and the field -> variable mapping.
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(automation_connectors)").fetchall()
                }
                for name, ddl in (
                    ("spec_json", "ALTER TABLE automation_connectors ADD COLUMN spec_json TEXT"),
                    ("operation", "ALTER TABLE automation_connectors ADD COLUMN operation TEXT"),
                    (
                        "body_map_json",
                        "ALTER TABLE automation_connectors ADD COLUMN body_map_json "
                        "TEXT NOT NULL DEFAULT '{}'",
                    ),
                ):
                    if name not in columns:
                        conn.execute(ddl)
            if found < 6:
                # "Never configured" (auto-suggest) must be distinguishable from "configured as empty"
                # (the user cleared every field), so the mapping carries its own flag.
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(automation_connectors)").fetchall()
                }
                if "body_map_configured" not in columns:
                    conn.execute(
                        "ALTER TABLE automation_connectors ADD COLUMN body_map_configured "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
            if found < 7:
                # Hand-written request fields for downstreams that publish no OpenAPI document.
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(automation_connectors)").fetchall()
                }
                if "fields_json" not in columns:
                    conn.execute("ALTER TABLE automation_connectors ADD COLUMN fields_json TEXT")
            if found < 8:
                # Field mappings become per (template, connector): one connector can serve several
                # templates without their mappings overwriting each other.
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS automation_mappings ("
                    " template_id TEXT NOT NULL, connector_id TEXT NOT NULL,"
                    " workspace_id TEXT NOT NULL, body_map_json TEXT NOT NULL DEFAULT '{}',"
                    " updated_at TEXT NOT NULL, PRIMARY KEY (template_id, connector_id))"
                )
            if found < 9:
                # Template binding decides "same kind of document" (automation-auto-dispatch D3);
                # templates/connectors carry a department so `dept_admin` stays inside its scope.
                documents_columns = {
                    row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()
                }
                for name in ("template_id", "template_name"):
                    if name not in documents_columns:
                        conn.execute(f"ALTER TABLE documents ADD COLUMN {name} TEXT")
                for table in ("automation_templates", "automation_connectors"):
                    columns = {
                        row["name"]
                        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    }
                    if "department_id" not in columns:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN department_id TEXT")
            if found < 10:
                # Bank Ops rules: "this template kind → this downstream, at this trust level".
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS automation_rules ("
                    " rule_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, department_id TEXT,"
                    " name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,"
                    " priority INTEGER NOT NULL DEFAULT 100, required INTEGER NOT NULL DEFAULT 1,"
                    " template_name TEXT NOT NULL, connector_id TEXT NOT NULL,"
                    " trigger TEXT NOT NULL DEFAULT 'final_approval',"
                    " mode TEXT NOT NULL DEFAULT 'shadow', created_by TEXT NOT NULL,"
                    " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, disabled_at TEXT)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS automation_rules_ws "
                    "ON automation_rules(workspace_id, template_name, enabled)"
                )
            if found < 11:
                # Automatic dispatch: one job per (rule, submission) plus its state timeline, and the
                # receipt carries the job/rule/submission it belongs to (design D5/D7).
                dispatch_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(automation_dispatches)").fetchall()
                }
                for name in ("job_id", "rule_id", "trigger", "submission_id"):
                    if name not in dispatch_columns:
                        conn.execute(f"ALTER TABLE automation_dispatches ADD COLUMN {name} TEXT")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS automation_jobs ("
                    " job_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, rule_id TEXT NOT NULL,"
                    " document_id TEXT NOT NULL, submission_id TEXT NOT NULL,"
                    " template_id TEXT NOT NULL, connector_id TEXT NOT NULL,"
                    " status TEXT NOT NULL, mode TEXT NOT NULL, idempotency_key TEXT NOT NULL,"
                    " attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT,"
                    " request_json TEXT, response_excerpt TEXT, error_code TEXT, receipt_id TEXT,"
                    " created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
                    " UNIQUE (workspace_id, idempotency_key))"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS automation_jobs_due "
                    "ON automation_jobs(status, next_attempt_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS automation_jobs_doc "
                    "ON automation_jobs(document_id, created_at)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS automation_job_events ("
                    " event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, from_status TEXT,"
                    " to_status TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}',"
                    " created_at TEXT NOT NULL)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS automation_job_events_job "
                    "ON automation_job_events(job_id, created_at)"
                )
            if found < 12:
                # `required` is snapshotted on the job: an optional downstream failing keeps the
                # document-level delivery status `sent`, a required failure makes it `needs_attention`.
                job_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(automation_jobs)").fetchall()
                }
                if "required" not in job_columns:
                    conn.execute(
                        "ALTER TABLE automation_jobs ADD COLUMN required INTEGER NOT NULL DEFAULT 1"
                    )
            if found < 13:
                # Approval routing: bank-originated submissions are first reviewed by the
                # counterparty, applicant-originated ones by Bank Operations (shared editing).
                request_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(approval_requests)").fetchall()
                }
                if "route" not in request_columns:
                    conn.execute(
                        "ALTER TABLE approval_requests ADD COLUMN route TEXT NOT NULL DEFAULT 'bank_first'"
                    )
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
        template_id: str | None = None,
        template_name: str | None = None,
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
                "department_id, template_id, template_name) VALUES (?,?,?,?,?,?,?,?)",
                (
                    document_id,
                    workspace_id,
                    owner_user_id,
                    title,
                    stamp,
                    department_id,
                    template_id,
                    template_name,
                ),
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

    def list_documents(self, workspace_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Workspace documents with their draft revision and latest submission status."""
        return self.all(
            "SELECT d.document_id, d.workspace_id, d.owner_user_id, d.title, d.created_at,"
            " d.department_id, dr.draft_id, dr.revision, dr.updated_at AS draft_updated_at,"
            " (SELECT s.status FROM document_submissions s WHERE s.document_id = d.document_id"
            "  ORDER BY s.created_at DESC, s.rowid DESC LIMIT 1) AS submission_status"
            " FROM documents d LEFT JOIN document_drafts dr ON dr.document_id = d.document_id"
            " WHERE d.workspace_id = ?"
            " ORDER BY COALESCE(dr.updated_at, d.created_at) DESC LIMIT ?",
            (workspace_id, limit),
        )

    def bind_document_template(
        self,
        *,
        document_id: str,
        workspace_id: str,
        template_id: str,
        template_name: str,
        actor: str,
        request_id: str = "",
    ) -> dict[str, Any]:
        """Bind a document to a template (the "same kind of document" key) and audit the change."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE document_id = ? AND workspace_id = ?",
                (document_id, workspace_id),
            ).fetchone()
            if row is None:
                raise HostNotFound("document not found")
            previous = row["template_id"] if "template_id" in row.keys() else None
            conn.execute(
                "UPDATE documents SET template_id = ?, template_name = ? WHERE document_id = ?",
                (template_id, template_name, document_id),
            )
            self._audit(
                conn,
                request_id,
                "document_template_bound",
                actor,
                {
                    "document_id": document_id,
                    "template_id": template_id,
                    "template_name": template_name,
                    "previous_template_id": previous,
                },
            )
        return self.get_document(document_id) or {}

    def document_template(self, document_id: str) -> dict[str, Any] | None:
        row = self.get_document(document_id)
        if row is None:
            return None
        return {
            "document_id": row["document_id"],
            "template_id": row.get("template_id"),
            "template_name": row.get("template_name"),
        }

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

    def list_submissions_for_user(
        self, workspace_id: str, user_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """The caller's submissions across every document in the workspace (with document title)."""
        return self.all(
            "SELECT s.*, d.title FROM document_submissions s"
            " JOIN documents d ON d.document_id = s.document_id"
            " WHERE s.workspace_id = ? AND s.submitted_by = ?"
            " ORDER BY s.created_at DESC, s.rowid DESC LIMIT ?",
            (workspace_id, user_id, limit),
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
        route: str = "bank_first",
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
                "route": route,
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
                ":created_at,:updated_at,:decided_at,:route)",
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
                # An expired lease is free, whoever took it: otherwise a crashed or abandoned tab
                # would block every other user forever (409 on every acquire).
                if _parse_time(row["lease_until"]) > now_dt:
                    if row["owner_user_id"] != owner_user_id:
                        raise LockConflict("another user holds this draft's lock")
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

    def active_lock(self, draft_id: str) -> dict[str, Any] | None:
        """The unreleased lock on a draft, if any (expired or not: the caller decides)."""
        return self.one(
            "SELECT * FROM document_locks WHERE draft_id = ? AND released_at IS NULL", (draft_id,)
        )

    def force_release_lock(self, *, lock_id: str) -> dict[str, Any]:
        """Release a lock regardless of owner (used only after the caller proves it is expired)."""
        stamp = now_iso()
        with self.transaction() as conn:
            result = conn.execute(
                "UPDATE document_locks SET released_at=? WHERE lock_id=? AND released_at IS NULL",
                (stamp, lock_id),
            )
            if result.rowcount != 1:
                raise LockConflict("the lock is missing or already released")
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
    def record_audit(
        self,
        *,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        request_id: str = "",
    ) -> None:
        """Public audit entry for services that are not inside a store transaction."""
        with self.transaction() as conn:
            self._audit(conn, request_id, event_type, actor, payload)

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

    def pending_outbox(self, limit: int = 50) -> list[dict[str, Any]]:
        """Events the automation worker has not consumed yet (approval events drive auto-dispatch)."""
        return self.all(
            "SELECT * FROM outbox_events WHERE delivered_at IS NULL ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )

    def pending_approval_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Only the final-approval events, so other outbox consumers keep their own events."""
        return self.all(
            "SELECT * FROM outbox_events WHERE delivered_at IS NULL "
            "AND event_type = 'approval.second.approve' ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )

    def mark_outbox_delivered(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE outbox_events SET delivered_at = ? WHERE id IN ({placeholders})",
                (now_iso(), *event_ids),
            )

    # --- automation jobs ----------------------------------------------------------------------
    def find_automation_job(
        self, workspace_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM automation_jobs WHERE workspace_id = ? AND idempotency_key = ?",
            (workspace_id, idempotency_key),
        )

    def automation_job(self, job_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM automation_jobs WHERE job_id = ?", (job_id,))

    def create_automation_job(self, **fields: Any) -> dict[str, Any]:
        """Insert once per `(workspace, idempotency_key)`; a replay returns the existing row."""
        existing = self.find_automation_job(fields["workspace_id"], fields["idempotency_key"])
        if existing is not None:
            return existing
        columns = (
            "job_id",
            "workspace_id",
            "rule_id",
            "document_id",
            "submission_id",
            "template_id",
            "connector_id",
            "status",
            "mode",
            "required",
            "idempotency_key",
            "attempts",
            "next_attempt_at",
            "request_json",
            "error_code",
            "created_at",
            "updated_at",
        )
        values = {name: fields.get(name) for name in columns}
        values["attempts"] = int(values.get("attempts") or 0)
        values["required"] = 1 if values.get("required") is None else int(bool(values["required"]))
        values["created_at"] = values.get("created_at") or now_iso()
        values["updated_at"] = values.get("updated_at") or values["created_at"]
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO automation_jobs ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(values[name] for name in columns),
            )
        row = self.find_automation_job(fields["workspace_id"], fields["idempotency_key"])
        assert row is not None
        if row["job_id"] != fields["job_id"]:
            return row
        self.append_automation_job_event(
            row["job_id"], None, str(row["status"]), {"mode": row["mode"]}
        )
        return row

    def update_automation_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "mode",
            "attempts",
            "next_attempt_at",
            "request_json",
            "response_excerpt",
            "error_code",
            "receipt_id",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown automation job fields: {sorted(unknown)}")
        fields["updated_at"] = now_iso()
        assignments = ",".join(f"{name} = ?" for name in fields)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE automation_jobs SET {assignments} WHERE job_id = ?",
                (*fields.values(), job_id),
            )
        row = self.automation_job(job_id)
        assert row is not None
        return row

    def append_automation_job_event(
        self,
        job_id: str,
        from_status: str | None,
        to_status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO automation_job_events (event_id, job_id, from_status, to_status, "
                "detail_json, created_at) VALUES (?,?,?,?,?,?)",
                (
                    new_id("jev"),
                    job_id,
                    from_status,
                    to_status,
                    json.dumps(detail or {}, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def automation_jobs(
        self,
        workspace_id: str,
        *,
        document_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM automation_jobs WHERE workspace_id = ?"
        params: list[Any] = [workspace_id]
        if document_id:
            sql += " AND document_id = ?"
            params.append(document_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return self.all(sql, tuple(params))

    def due_automation_jobs(self, now: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM automation_jobs WHERE status = 'queued' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY created_at ASC LIMIT ?",
            (now, limit),
        )

    def automation_job_events(self, job_id: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT * FROM automation_job_events WHERE job_id = ? ORDER BY created_at ASC",
            (job_id,),
        )

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