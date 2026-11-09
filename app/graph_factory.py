"""Graph construction and checkpointer wiring.

Spec: `poc-skeleton/tasks.md` 8.4. A compiled graph without a checkpointer cannot pause at
`hitl` and resume in another request, so the production path always uses SQLite. Tests that do
not care about persistence pass `checkpointer=InMemorySaver()`.

The connection is opened with `check_same_thread=False` because FastAPI runs endpoints on worker
threads; callers serialise graph invocation with the per-run lock in `app/runs.py` / `Runner`.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from app.graph import build_graph

DEFAULT_CHECKPOINT_DB = "runs/checkpoints.sqlite"


def default_checkpoint_path() -> Path:
    return Path(os.environ.get("SMART_EDIT_CHECKPOINT_DB") or DEFAULT_CHECKPOINT_DB)


def make_checkpointer(path: str | Path | None = None):
    """Return a saver. `None` / `:memory:` means in-process memory (tests only)."""
    if path is None or str(path) == ":memory:":
        return InMemorySaver()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), check_same_thread=False)
    return SqliteSaver(connection)


def compile_graph(
    *,
    checkpointer=None,
    checkpointer_path: str | Path | None = None,
    **graph_kwargs,
):
    """Compile the main graph; without an explicit saver the SQLite default is used."""
    saver = checkpointer
    if saver is None:
        saver = make_checkpointer(checkpointer_path or default_checkpoint_path())
    return build_graph(**graph_kwargs).compile(checkpointer=saver)


__all__ = [
    "DEFAULT_CHECKPOINT_DB",
    "compile_graph",
    "default_checkpoint_path",
    "make_checkpointer",
]
