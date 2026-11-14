"""SQLite repositories for the assistant (task 1.1).

Tables and columns mirror the future PostgreSQL schema (design D3). Every access goes through this
class; the service layer never writes SQL.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS assistant_snapshots (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, document_id TEXT NOT NULL,
  content_sha256 TEXT NOT NULL, text TEXT NOT NULL, version_label TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS snapshots_document ON assistant_snapshots(document_id, created_at);
CREATE TABLE IF NOT EXISTS assistant_sessions (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
  document_id TEXT, snapshot_id TEXT, attachment_ids_json TEXT NOT NULL DEFAULT '[]',
  locale TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_owner ON assistant_sessions(owner_user_id, workspace_id);
CREATE TABLE IF NOT EXISTS assistant_messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT NOT NULL, role TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'visible', question TEXT, answer_json TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_session ON assistant_messages(session_id, created_at);
CREATE TABLE IF NOT EXISTS assistant_runs (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_message_id TEXT NOT NULL,
  status TEXT NOT NULL, stage TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, deadline_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  assistant_message_id TEXT, result_json TEXT, error_json TEXT, request_json TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON assistant_runs(session_id)
  WHERE status IN ('queued', 'running');
CREATE TABLE IF NOT EXISTS assistant_citations (
  message_id TEXT NOT NULL, citation_id TEXT NOT NULL, source_type TEXT NOT NULL,
  title TEXT NOT NULL, source_version TEXT NOT NULL, locator_json TEXT NOT NULL DEFAULT '{}',
  excerpt TEXT NOT NULL, source_id TEXT, version_id TEXT, chunk_id TEXT,
  effective_from TEXT, effective_to TEXT, synthetic INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (message_id, citation_id));
CREATE TABLE IF NOT EXISTS assistant_dependencies (
  message_id TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
  resource_version TEXT, authorized_at TEXT NOT NULL,
  PRIMARY KEY (message_id, resource_type, resource_id));
CREATE TABLE IF NOT EXISTS assistant_feedback (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL, message_id TEXT NOT NULL, rating TEXT NOT NULL,
  categories_json TEXT NOT NULL DEFAULT '[]', comment TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (user_id, message_id));
CREATE TABLE IF NOT EXISTS assistant_audit (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL, run_id TEXT, event_type TEXT NOT NULL,
  actor TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_sources (
  source_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, publisher TEXT NOT NULL,
  language TEXT NOT NULL, scope TEXT NOT NULL, organization_id TEXT,
  jurisdictions_json TEXT NOT NULL DEFAULT '[]', license_reference TEXT NOT NULL,
  synthetic INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_versions (
  version_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
  version_label TEXT NOT NULL, status TEXT NOT NULL, effective_from TEXT, effective_to TEXT,
  submitted_by TEXT NOT NULL, reviewed_by TEXT, review_reason TEXT, created_at TEXT NOT NULL,
  reviewed_at TEXT, published_at TEXT, withdrawn_at TEXT,
  FOREIGN KEY (source_id) REFERENCES knowledge_sources(source_id));
CREATE INDEX IF NOT EXISTS versions_status ON knowledge_versions(status, source_id);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
  chunk_id TEXT NOT NULL, source_id TEXT NOT NULL, version_id TEXT NOT NULL,
  section TEXT, page INTEGER, title_path TEXT NOT NULL DEFAULT '', text TEXT NOT NULL,
  locator_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (version_id, chunk_id),
  FOREIGN KEY (version_id) REFERENCES knowledge_versions(version_id));
CREATE INDEX IF NOT EXISTS chunks_version ON knowledge_chunks(version_id);
CREATE TABLE IF NOT EXISTS idempotency_records (
  principal TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, key TEXT NOT NULL,
  request_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (principal, method, path, key));
CREATE TABLE IF NOT EXISTS outbox_events (
  id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL, delivered_at TEXT);
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Version 1 is the initial mirrored schema; version 2 scopes chunk ids to their version so a newer
# version of a source may reuse the same chunk ids. C's PostgreSQL migration keeps the table/column
# names, so bumping this is only needed when an A-side column/constraint changes.
SCHEMA_VERSION = 2


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class SessionBusy(RuntimeError):
    """A session already has a queued/running run."""


class SQLiteStore:
    def __init__(self, path: str | Path = "runs/assistant.db", *, recover: bool = True) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._check_schema_version()
        if recover:
            self.recover_stale()

    def _check_schema_version(self) -> None:
        """Migrate known older schemas; refuse to open a database newer than this binary."""
        row = self._one("SELECT value FROM schema_meta WHERE key = 'schema_version'")
        if row is None:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO schema_meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
                )
            return
        found = int(row["value"])
        if found > SCHEMA_VERSION:
            raise RuntimeError(
                f"assistant database schema v{found} is newer than this build (v{SCHEMA_VERSION})"
            )
        if found < SCHEMA_VERSION:
            self._migrate(found)

    def _migrate(self, found: int) -> None:
        with self._lock, self._conn:
            if found < 2:
                # v1 keyed chunks by `chunk_id` alone, which blocks a v2 that reuses chunk ids.
                self._conn.execute("ALTER TABLE knowledge_chunks RENAME TO knowledge_chunks_v1")
                self._conn.execute(
                    "CREATE TABLE knowledge_chunks ("
                    " chunk_id TEXT NOT NULL, source_id TEXT NOT NULL, version_id TEXT NOT NULL,"
                    " section TEXT, page INTEGER, title_path TEXT NOT NULL DEFAULT '',"
                    " text TEXT NOT NULL, locator_json TEXT NOT NULL DEFAULT '{}',"
                    " PRIMARY KEY (version_id, chunk_id),"
                    " FOREIGN KEY (version_id) REFERENCES knowledge_versions(version_id))"
                )
                self._conn.execute(
                    "INSERT INTO knowledge_chunks SELECT chunk_id, source_id, version_id, section,"
                    " page, title_path, text, locator_json FROM knowledge_chunks_v1"
                )
                self._conn.execute("DROP TABLE knowledge_chunks_v1")
            self._conn.execute("UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                               (str(SCHEMA_VERSION),))

    def schema_version(self) -> int:
        row = self._one("SELECT value FROM schema_meta WHERE key = 'schema_version'")
        return int(row["value"]) if row else 0

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # --- snapshots / sessions ---------------------------------------------------------------
    def create_snapshot(
        self, workspace_id: str, document_id: str, text: str, content_sha256: str,
        created_by: str, version_label: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": new_id("snap"), "workspace_id": workspace_id, "document_id": document_id,
            "content_sha256": content_sha256, "text": text, "version_label": version_label,
            "created_by": created_by, "created_at": now_iso(),
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO assistant_snapshots VALUES (:id,:workspace_id,:document_id,:content_sha256,"
                ":text,:version_label,:created_by,:created_at)", item,
            )
        return item

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM assistant_snapshots WHERE id = ?", (snapshot_id,))

    def latest_snapshot(self, document_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM assistant_snapshots WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
            (document_id,),
        )

    def create_session(
        self, *, workspace_id: str, owner_user_id: str, document_id: str | None,
        snapshot_id: str | None, attachment_ids: list[str], locale: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": new_id("sess"), "workspace_id": workspace_id, "owner_user_id": owner_user_id,
            "document_id": document_id, "snapshot_id": snapshot_id,
            "attachment_ids_json": json.dumps(attachment_ids, ensure_ascii=False),
            "locale": locale, "status": "active", "created_at": created_at or now_iso(),
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO assistant_sessions VALUES (:id,:workspace_id,:owner_user_id,:document_id,"
                ":snapshot_id,:attachment_ids_json,:locale,:status,:created_at)", item,
            )
        return item

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM assistant_sessions WHERE id = ?", (session_id,))

    def list_sessions(self, owner_user_id: str, workspace_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM assistant_sessions WHERE owner_user_id = ? AND workspace_id = ? "
            "ORDER BY created_at DESC", (owner_user_id, workspace_id),
        )

    # --- messages / runs --------------------------------------------------------------------
    def create_user_message(
        self, session_id: str, run_id: str, question: str, message_id: str | None = None
    ) -> dict[str, Any]:
        item = {
            "id": message_id or new_id("msg"), "session_id": session_id, "run_id": run_id,
            "role": "user", "visibility": "visible", "question": question, "answer_json": None,
            "created_at": now_iso(),
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO assistant_messages VALUES (:id,:session_id,:run_id,:role,:visibility,"
                ":question,:answer_json,:created_at)", item,
            )
        return item

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM assistant_messages WHERE id = ?", (message_id,))

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM assistant_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )

    def create_run(
        self, session_id: str, user_message_id: str, deadline_at: str, request_json: str = "{}",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            active = self._conn.execute(
                "SELECT id FROM assistant_runs WHERE session_id = ? AND status IN ('queued','running')",
                (session_id,),
            ).fetchone()
            if active:
                raise SessionBusy("this session already has an active run")
            item = {
                "id": run_id or new_id("run"), "session_id": session_id,
                "user_message_id": user_message_id, "status": "queued", "stage": "queued",
                "attempt": 0, "created_at": now_iso(), "deadline_at": deadline_at,
                "request_json": request_json,
            }
            with self._conn:
                self._conn.execute(
                    "INSERT INTO assistant_runs (id,session_id,user_message_id,status,stage,attempt,created_at,"
                    "deadline_at,request_json) VALUES (:id,:session_id,:user_message_id,:status,:stage,"
                    ":attempt,:created_at,:deadline_at,:request_json)", item,
                )
        return self.get_run(item["id"]) or item

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM assistant_runs WHERE id = ?", (run_id,))

    def transition_run(
        self, run_id: str, from_statuses: tuple[str, ...], to_status: str, **fields: Any
    ) -> bool:
        allowed = {"stage", "started_at", "finished_at", "attempt", "assistant_message_id", "result_json", "error_json"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        updates["status"] = to_status
        assignments = ", ".join(f"{key} = ?" for key in updates)
        placeholders = ", ".join("?" for _ in from_statuses)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"UPDATE assistant_runs SET {assignments} WHERE id = ? AND status IN ({placeholders})",
                (*updates.values(), run_id, *from_statuses),
            )
        return cursor.rowcount == 1

    def cancel_run(self, run_id: str, cancelled_at: str) -> bool:
        return self.transition_run(
            run_id, ("queued", "running"), "cancelled", stage="cancelled", finished_at=cancelled_at
        )

    def fail_run(self, run_id: str, code: str, message: str, finished_at: str) -> bool:
        error = json.dumps({"code": code, "message": message, "request_id": "", "retryable": False})
        return self.transition_run(
            run_id, ("queued", "running"), "failed", stage="failed", finished_at=finished_at,
            error_json=error,
        )

    def commit_answer(
        self, *, run_id: str, answer: dict[str, Any], citations: list[dict[str, Any]],
        dependencies: list[dict[str, Any]], audit: dict[str, Any], finished_at: str,
    ) -> dict[str, Any] | None:
        """Atomically write the assistant message, citations, dependencies, run terminal and audit."""
        with self._lock:
            run = self._one("SELECT * FROM assistant_runs WHERE id = ?", (run_id,))
            if not run or run["status"] != "running":
                return None
            message_id = new_id("msg")
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO assistant_messages VALUES (?,?,?,?,?,?,?,?)",
                    (message_id, run["session_id"], run_id, "assistant", "visible", None,
                     json.dumps(answer, ensure_ascii=False), finished_at),
                )
                for citation in citations:
                    self._conn.execute(
                        "INSERT INTO assistant_citations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (message_id, citation["citation_id"], citation["source_type"], citation["title"],
                         citation["source_version"], json.dumps(citation.get("locator") or {}, ensure_ascii=False),
                         citation["excerpt"], citation.get("source_id"), citation.get("version_id"),
                         citation.get("chunk_id"), citation.get("effective_from"), citation.get("effective_to"),
                         int(bool(citation.get("synthetic")))),
                    )
                for dependency in dependencies:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO assistant_dependencies VALUES (?,?,?,?,?)",
                        (message_id, dependency["resource_type"], dependency["resource_id"],
                         dependency.get("resource_version"), finished_at),
                    )
                self._conn.execute(
                    "UPDATE assistant_runs SET status='succeeded', stage='completed', assistant_message_id=?,"
                    " result_json=?, finished_at=? WHERE id=? AND status='running'",
                    (message_id, json.dumps(answer, ensure_ascii=False), finished_at, run_id),
                )
                self._conn.execute(
                    "INSERT INTO assistant_audit VALUES (?,?,?,?,?,?,?)",
                    (new_id("audit"), audit.get("request_id", ""), run_id, audit["event_type"],
                     audit.get("actor", ""), json.dumps(audit.get("payload") or {}, ensure_ascii=False), finished_at),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return self.get_message(message_id)

    # --- citations / feedback / audit / idempotency ------------------------------------------
    def get_citation(self, message_id: str, citation_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM assistant_citations WHERE message_id = ? AND citation_id = ?",
            (message_id, citation_id),
        )

    def list_citations(self, message_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM assistant_citations WHERE message_id = ?", (message_id,))

    def upsert_feedback(
        self, *, user_id: str, message_id: str, rating: str, categories: list[str], comment: str | None
    ) -> dict[str, Any]:
        existing = self._one(
            "SELECT * FROM assistant_feedback WHERE user_id = ? AND message_id = ?",
            (user_id, message_id),
        )
        stamp = now_iso()
        if existing:
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE assistant_feedback SET rating=?, categories_json=?, comment=?, updated_at=?"
                    " WHERE id=?", (rating, json.dumps(categories, ensure_ascii=False), comment, stamp, existing["id"]),
                )
            return self._one("SELECT * FROM assistant_feedback WHERE id = ?", (existing["id"],)) or {}
        item = {
            "id": new_id("fb"), "user_id": user_id, "message_id": message_id, "rating": rating,
            "categories_json": json.dumps(categories, ensure_ascii=False), "comment": comment,
            "created_at": stamp, "updated_at": stamp,
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO assistant_feedback VALUES (:id,:user_id,:message_id,:rating,"
                ":categories_json,:comment,:created_at,:updated_at)", item,
            )
        return item

    def get_feedback(self, user_id: str, message_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM assistant_feedback WHERE user_id = ? AND message_id = ?",
            (user_id, message_id),
        )

    def append_audit(
        self, *, request_id: str, run_id: str | None, event_type: str, actor: str, payload: dict[str, Any]
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO assistant_audit VALUES (?,?,?,?,?,?,?)",
                (new_id("audit"), request_id, run_id, event_type, actor,
                 json.dumps(payload, ensure_ascii=False), now_iso()),
            )

    def get_idempotency(
        self, principal: str, method: str, path: str, key: str
    ) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM idempotency_records WHERE principal=? AND method=? AND path=? AND key=?",
            (principal, method, path, key),
        )

    def put_idempotency(
        self, principal: str, method: str, path: str, key: str, request_hash: str,
        response: dict[str, Any],
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO idempotency_records VALUES (?,?,?,?,?,?,?)",
                (principal, method, path, key, request_hash,
                 json.dumps(response, ensure_ascii=False), now_iso()),
            )

    # --- knowledge sources / versions / chunks -------------------------------------------------
    def create_knowledge_source(
        self, *, source_id: str, source_type: str, publisher: str, language: str, scope: str,
        organization_id: str | None, license_reference: str, synthetic: bool = True,
        jurisdictions: list[str] | None = None,
    ) -> dict[str, Any]:
        item = {
            "source_id": source_id, "source_type": source_type, "publisher": publisher,
            "language": language, "scope": scope, "organization_id": organization_id,
            "jurisdictions_json": json.dumps(jurisdictions or [], ensure_ascii=False),
            "license_reference": license_reference, "synthetic": int(synthetic), "created_at": now_iso(),
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO knowledge_sources VALUES (:source_id,:source_type,:publisher,"
                ":language,:scope,:organization_id,:jurisdictions_json,:license_reference,"
                ":synthetic,:created_at)", item,
            )
        return self.get_knowledge_source(source_id) or item

    def get_knowledge_source(self, source_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM knowledge_sources WHERE source_id = ?", (source_id,))

    def create_knowledge_version(
        self, *, version_id: str, source_id: str, title: str, version_label: str,
        effective_from: str | None, effective_to: str | None, submitted_by: str,
    ) -> dict[str, Any]:
        item = {
            "version_id": version_id, "source_id": source_id, "title": title,
            "version_label": version_label, "status": "processing",
            "effective_from": effective_from, "effective_to": effective_to,
            "submitted_by": submitted_by, "reviewed_by": None, "review_reason": None,
            "created_at": now_iso(), "reviewed_at": None, "published_at": None, "withdrawn_at": None,
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO knowledge_versions VALUES (:version_id,:source_id,:title,:version_label,"
                ":status,:effective_from,:effective_to,:submitted_by,:reviewed_by,:review_reason,"
                ":created_at,:reviewed_at,:published_at,:withdrawn_at)", item,
            )
        return self.get_knowledge_version(version_id) or item

    def add_knowledge_chunks(self, version_id: str, source_id: str, chunks: list[dict[str, Any]]) -> None:
        with self._lock, self._conn:
            for chunk in chunks:
                self._conn.execute(
                    "INSERT INTO knowledge_chunks VALUES (?,?,?,?,?,?,?,?)",
                    (chunk["chunk_id"], source_id, version_id, chunk.get("section"), chunk.get("page"),
                     chunk.get("title_path", ""), chunk["text"],
                     json.dumps(chunk.get("locator") or {}, ensure_ascii=False)),
                )

    def get_knowledge_version(self, version_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT v.*, s.source_type, s.publisher, s.language, s.scope, s.organization_id,"
            " s.license_reference, s.synthetic FROM knowledge_versions v"
            " JOIN knowledge_sources s ON s.source_id = v.source_id WHERE v.version_id = ?",
            (version_id,),
        )

    def list_knowledge_versions(self, source_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM knowledge_versions WHERE source_id = ? ORDER BY created_at DESC",
            (source_id,),
        )

    def list_knowledge_versions_all(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM knowledge_versions ORDER BY created_at DESC")

    def knowledge_count(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM knowledge_sources")
        return int(row["n"]) if row else 0

    def review_knowledge_version(
        self, version_id: str, decision: str, reviewer: str, reason: str
    ) -> dict[str, Any]:
        with self._lock:
            version = self._one("SELECT * FROM knowledge_versions WHERE version_id = ?", (version_id,))
            if not version:
                raise KeyError("unknown knowledge version")
            if version["status"] != "pending_review":
                raise ValueError("version is not pending_review")
            if version["submitted_by"] == reviewer:
                raise PermissionError("submitter cannot review their own version")
            stamp = now_iso()
            with self._conn:
                if decision == "publish":
                    self._conn.execute(
                        "UPDATE knowledge_versions SET status='superseded' WHERE source_id=? AND status='published'"
                        " AND version_id<>?", (version["source_id"], version_id),
                    )
                    self._conn.execute(
                        "UPDATE knowledge_versions SET status='published', reviewed_by=?, review_reason=?,"
                        " reviewed_at=?, published_at=? WHERE version_id=?",
                        (reviewer, reason, stamp, stamp, version_id),
                    )
                    event = "knowledge_published"
                elif decision == "reject":
                    self._conn.execute(
                        "UPDATE knowledge_versions SET status='rejected', reviewed_by=?, review_reason=?,"
                        " reviewed_at=? WHERE version_id=?", (reviewer, reason, stamp, version_id),
                    )
                    event = "knowledge_rejected"
                else:
                    raise ValueError("decision must be publish or reject")
                self._conn.execute(
                    "INSERT INTO assistant_audit VALUES (?,?,?,?,?,?,?)",
                    (new_id("audit"), "", None, event, reviewer,
                     json.dumps({"source_id": version["source_id"], "version_id": version_id,
                                 "reason": reason}, ensure_ascii=False), stamp),
                )
        return self.get_knowledge_version(version_id) or {}

    def withdraw_knowledge_version(
        self, source_id: str, version_id: str, reason: str, actor: str
    ) -> dict[str, Any]:
        with self._lock:
            version = self._one(
                "SELECT * FROM knowledge_versions WHERE version_id = ? AND source_id = ?",
                (version_id, source_id),
            )
            if not version:
                raise KeyError("unknown knowledge version")
            if version["status"] not in ("published", "superseded"):
                raise ValueError("only published/superseded versions can be withdrawn")
            stamp = now_iso()
            with self._conn:
                self._conn.execute(
                    "UPDATE knowledge_versions SET status='withdrawn', review_reason=?, withdrawn_at=?"
                    " WHERE version_id=?", (reason, stamp, version_id),
                )
                self._conn.execute(
                    "INSERT INTO assistant_audit VALUES (?,?,?,?,?,?,?)",
                    (new_id("audit"), "", None, "knowledge_withdrawn", actor,
                     json.dumps({"source_id": source_id, "version_id": version_id, "reason": reason},
                                ensure_ascii=False), stamp),
                )
        return self.get_knowledge_version(version_id) or {}

    def mark_pending_review(self, version_id: str) -> dict[str, Any]:
        """`processing -> pending_review` only after every chunk is stored (atomic publish input)."""
        with self._lock:
            version = self._one("SELECT * FROM knowledge_versions WHERE version_id = ?", (version_id,))
            if not version:
                raise KeyError("unknown knowledge version")
            if version["status"] != "processing":
                raise ValueError("version is not processing")
            chunks = self._one(
                "SELECT COUNT(*) AS n FROM knowledge_chunks WHERE version_id = ?", (version_id,)
            )
            if not chunks or int(chunks["n"]) == 0:
                raise ValueError("a version without chunks cannot enter review")
            with self._conn:
                self._conn.execute(
                    "UPDATE knowledge_versions SET status='pending_review' WHERE version_id=?",
                    (version_id,),
                )
        return self.get_knowledge_version(version_id) or {}

    def published_chunks(
        self,
        applicable_on: str | None = None,
        *,
        allowed_scopes: tuple[str, ...] = ("public", "organization", "bank_internal"),
        organization_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Only published, currently effective, scope-allowed versions may be retrieved."""
        ready = applicable_on or datetime.now(timezone.utc).date().isoformat()
        scopes = tuple(allowed_scopes)
        if not scopes:
            return []
        scope_slots = ", ".join("?" for _ in scopes)
        sql = (
            "SELECT c.chunk_id, c.source_id, c.version_id, c.section, c.page, c.title_path, c.text,"
            " c.locator_json, v.title, v.version_label, v.effective_from, v.effective_to,"
            " s.source_type, s.publisher, s.language, s.scope, s.organization_id, s.license_reference,"
            " s.synthetic FROM knowledge_chunks c"
            " JOIN knowledge_versions v ON v.version_id = c.version_id"
            " JOIN knowledge_sources s ON s.source_id = c.source_id"
            " WHERE v.status = 'published'"
            " AND (v.effective_from IS NULL OR v.effective_from <= ?)"
            " AND (v.effective_to IS NULL OR ? < v.effective_to)"
            f" AND s.scope IN ({scope_slots})"
        )
        params: list[Any] = [ready, ready, *scopes]
        if organization_id is not None:
            sql += " AND (s.organization_id IS NULL OR s.organization_id = ?)"
            params.append(organization_id)
        rows = self._all(sql, tuple(params))
        for row in rows:
            row["locator"] = json.loads(row.pop("locator_json") or "{}")
        return rows

    def withdraw_knowledge_source(
        self, source_id: str, reason: str, actor: str
    ) -> list[dict[str, Any]]:
        """Withdraw every published/superseded version of a source in one transaction."""
        with self._lock:
            versions = self._all(
                "SELECT * FROM knowledge_versions WHERE source_id = ?"
                " AND status IN ('published','superseded')", (source_id,),
            )
            if not versions:
                raise KeyError("no withdrawable knowledge version")
            stamp = now_iso()
            with self._conn:
                self._conn.execute(
                    "UPDATE knowledge_versions SET status='withdrawn', review_reason=?, withdrawn_at=?"
                    " WHERE source_id=? AND status IN ('published','superseded')",
                    (reason, stamp, source_id),
                )
                self._conn.execute(
                    "INSERT INTO assistant_audit VALUES (?,?,?,?,?,?,?)",
                    (new_id("audit"), "", None, "knowledge_source_withdrawn", actor,
                     json.dumps({"source_id": source_id, "reason": reason}, ensure_ascii=False), stamp),
                )
        return versions

    def recover_stale(self) -> None:
        """Runs left by a previous process cannot be resumed by the in-process runner."""
        stamp = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE assistant_runs SET status='timed_out', stage='timed_out', finished_at=?,"
                " error_json=? WHERE status IN ('queued','running') AND deadline_at < ?",
                (stamp, json.dumps({"code": "RUN_TIMEOUT", "message": "deadline passed",
                                    "request_id": "", "retryable": True}), stamp),
            )
            self._conn.execute(
                "UPDATE assistant_runs SET status='failed', stage='failed', finished_at=?,"
                " error_json=? WHERE status IN ('queued','running')",
                (stamp, json.dumps({"code": "RUN_INTERRUPTED", "message": "worker interrupted",
                                    "request_id": "", "retryable": True})),
            )