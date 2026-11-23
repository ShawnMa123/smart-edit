"""SQLite persistence for legal runs and reports.

The L1 slice kept reports in an ``OrderedDict``; a document scan is asynchronous and must survive a
page reload, so runs and reports are written to disk. One connection plus a lock: the scan runs in a
background thread while requests read, and SQLite's default thread check would otherwise trip.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.legal_review.contracts import ReviewReport, ReviewRun

DEFAULT_DB = Path("runs/legal.db")
MAX_RUNS = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS legal_runs (
    run_id TEXT PRIMARY KEY,
    workspace_id TEXT,
    document_id TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS legal_reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT,
    workspace_id TEXT,
    document_id TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS legal_idempotency (
    key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS legal_runs_created ON legal_runs(created_at);
CREATE INDEX IF NOT EXISTS legal_reports_created ON legal_reports(created_at);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class LegalStore:
    """Run/report cache with an idempotency table; safe to share across threads."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_DB)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # --- runs -------------------------------------------------------------------------------
    def save_run(
        self, run: ReviewRun, *, workspace_id: str = "", document_id: str = ""
    ) -> None:
        payload = json.dumps(run.model_dump(), ensure_ascii=False)
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO legal_runs (run_id, workspace_id, document_id, payload, created_at, "
                "updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (run.run_id, workspace_id, document_id, payload, now, now),
            )
            self._conn.execute(
                "DELETE FROM legal_runs WHERE run_id IN ("
                "SELECT run_id FROM legal_runs ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                (MAX_RUNS,),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> ReviewRun | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM legal_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return ReviewRun.model_validate(json.loads(row["payload"]))

    # --- reports ----------------------------------------------------------------------------
    def save_report(
        self, report: ReviewReport, *, workspace_id: str = "", document_id: str = ""
    ) -> None:
        payload = json.dumps(report.model_dump(), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO legal_reports (report_id, run_id, workspace_id, document_id, payload, "
                "created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(report_id) DO UPDATE SET "
                "payload=excluded.payload",
                (report.report_id, report.run_id, workspace_id, document_id, payload, _utcnow()),
            )
            self._conn.execute(
                "DELETE FROM legal_reports WHERE report_id IN ("
                "SELECT report_id FROM legal_reports ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                (MAX_RUNS,),
            )
            self._conn.commit()

    def get_report(self, report_id: str) -> ReviewReport | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM legal_reports WHERE report_id=?", (report_id,)
            ).fetchone()
        if row is None:
            return None
        return ReviewReport.model_validate(json.loads(row["payload"]))

    def report_workspace(self, report_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT workspace_id FROM legal_reports WHERE report_id=?", (report_id,)
            ).fetchone()
        return row["workspace_id"] if row else None

    # --- idempotency ------------------------------------------------------------------------
    def get_by_key(self, key: str) -> ReviewRun | None:
        """Read-only lookup; `None` means the key has not been bound yet."""
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id FROM legal_idempotency WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                return None
            existing = self._conn.execute(
                "SELECT payload FROM legal_runs WHERE run_id=?", (row["run_id"],)
            ).fetchone()
        if existing is None:
            return None
        return ReviewRun.model_validate(json.loads(existing["payload"]))

    def remember(self, key: str, run_id: str) -> ReviewRun | None:
        """Bind `key` to `run_id`; returns the already-bound run when the key was seen."""
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id FROM legal_idempotency WHERE key=?", (key,)
            ).fetchone()
            if row is not None:
                existing = self._conn.execute(
                    "SELECT payload FROM legal_runs WHERE run_id=?", (row["run_id"],)
                ).fetchone()
                return (
                    ReviewRun.model_validate(json.loads(existing["payload"]))
                    if existing is not None
                    else None
                )
            self._conn.execute(
                "INSERT INTO legal_idempotency (key, run_id, created_at) VALUES (?,?,?)",
                (key, run_id, _utcnow()),
            )
            self._conn.commit()
        return None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["DEFAULT_DB", "LegalStore"]