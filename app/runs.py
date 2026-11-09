"""Process-scoped run store.

Design: `openspec/changes/frontend-console/design.md` D3.

There is no checkpointer yet, so runs live in this process only. Two consequences the API must own:

1. A vanished run is an **error** (`UnknownRun` → `404 unknown_run`), never an empty run.
2. One `asyncio.Lock` per run, so two concurrent stage triggers cannot interleave appends into
   `trail` / `stages` (which are reducer keys) and make a run unreproducible.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path

DEFAULT_RUNS_DIR = Path("runs")


class UnknownRun(KeyError):
    """Raised when a `thread_id` is not held by this process."""

    def __init__(self, thread_id: str) -> None:
        super().__init__(thread_id)
        self.thread_id = thread_id


class RunStore:
    """In-memory `thread_id` → state map with per-run files and locks."""

    def __init__(self, runs_dir: str | Path | None = None) -> None:
        self.runs_dir = Path(runs_dir) if runs_dir is not None else DEFAULT_RUNS_DIR
        self._states: dict[str, dict] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def __len__(self) -> int:
        return len(self._states)

    def create(self) -> tuple[str, dict]:
        """Create a run and return `(thread_id, state)`."""
        thread_id = f"R-{uuid.uuid4().hex[:12]}"
        self.workdir(thread_id).mkdir(parents=True, exist_ok=True)
        state: dict = {
            "run_id": thread_id,
            "files": [],
            "trail": [],
            "stages": [],
            "findings": [],
            "dispositions": [],
            "_candidates": [],
        }
        self._states[thread_id] = state
        self._locks[thread_id] = asyncio.Lock()
        return thread_id, state

    def get(self, thread_id: str) -> dict:
        try:
            return self._states[thread_id]
        except KeyError:
            raise UnknownRun(thread_id) from None

    def lock(self, thread_id: str) -> asyncio.Lock:
        self.get(thread_id)
        return self._locks[thread_id]

    def workdir(self, thread_id: str) -> Path:
        return self.runs_dir / thread_id

    def store_upload(self, thread_id: str, filename: str, data: bytes) -> tuple[Path, str]:
        """Persist an upload under the run directory; returns `(path, sha256)`."""
        safe_name = Path(filename or "upload.bin").name or "upload.bin"
        target = self.workdir(thread_id) / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target, hashlib.sha256(data).hexdigest()

    def dispose(self, thread_id: str, *, remove_files: bool = True) -> None:
        self.get(thread_id)
        self._states.pop(thread_id, None)
        self._locks.pop(thread_id, None)
        if remove_files:
            shutil.rmtree(self.workdir(thread_id), ignore_errors=True)