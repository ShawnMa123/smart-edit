"""Durable control-plane ledger (SQLite).

Spec: `poc-skeleton/tasks.md` 8.7. This is **not** the process-scoped run cache in
`app/runs.py`; it is the small durable layer the graph needs:

- `resume_keys` makes `POST /runs/{id}/resume` idempotent across retries;
- `events` stores the replay timeline for `GET /runs/{id}/events`;
- `runs` stores the last state snapshot so a restart can still answer "this run existed" even
  though the API's in-memory state is gone (the API still returns `unknown_run` for execution —
  the snapshot is for the operator, not a resurrection promise).

One connection + one lock is enough for the POC; the SQLite saver already serialises checkpoints.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LEDGER_DB = "runs/ledger.sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    """Append-only events, idempotency keys and last-known state."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("SMART_EDIT_LEDGER_DB") or DEFAULT_LEDGER_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    thread_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resume_keys (
                    thread_id TEXT NOT NULL,
                    resume_key TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY (thread_id, resume_key)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    thread_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    at TEXT NOT NULL,
                    PRIMARY KEY (thread_id, seq)
                )
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save_state(self, thread_id: str, state: dict) -> None:
        encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO runs (thread_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (thread_id, encoded, _now()),
            )

    def load_state(self, thread_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM runs WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def claim_resume(self, thread_id: str, resume_key: str) -> bool:
        """True the first time this `(thread_id, resume_key)` is seen; False on a retry."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO resume_keys (thread_id, resume_key, applied_at) VALUES (?, ?, ?)",
                (thread_id, resume_key, _now()),
            )
        return cursor.rowcount == 1

    def resume_seen(self, thread_id: str, resume_key: str) -> bool:
        """Read-only idempotency check; the mark is written only after a successful apply."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM resume_keys WHERE thread_id = ? AND resume_key = ?",
                (thread_id, resume_key),
            ).fetchone()
        return row is not None

    def mark_resume(self, thread_id: str, resume_key: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO resume_keys (thread_id, resume_key, applied_at) VALUES (?, ?, ?)",
                (thread_id, resume_key, _now()),
            )

    def record_event(self, thread_id: str, kind: str, payload: dict) -> int:
        """Append one event; returns its per-run sequence number."""
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            seq = int(row[0])
            self._conn.execute(
                "INSERT INTO events (thread_id, seq, kind, payload_json, at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, seq, kind, encoded, _now()),
            )
        return seq

    def events(self, thread_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, kind, payload_json, at FROM events WHERE thread_id = ? ORDER BY seq",
                (thread_id,),
            ).fetchall()
        return [
            {"seq": seq, "kind": kind, "at": at, **json.loads(payload)}
            for seq, kind, payload, at in rows
        ]


__all__ = ["DEFAULT_LEDGER_DB", "RunStore"]
