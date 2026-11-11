"""`ingest` node: give every source file a stable identity exactly once.

Contract: `openspec/changes/poc-skeleton/design.md` §9.

The node is deliberately boring: it never parses, never guesses `business_type`, and never
rewrites a file the caller already identified. It exists so the rest of the graph can rely on
`run_id` / `file_id` / `sha256` being present and stable, and so the gate has an `ingest`
`StageReport` to read instead of inferring "it must have run".
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from app.parsing.parse import sha256_of
from app.stages import stage_report
from app.state import SHARED_STAGE_OWNER
from app.trail import record

INGEST_STAGE = "ingest"


def _new_run_id() -> str:
    return f"R-{uuid.uuid4().hex[:12]}"


def _file_sha256(item: dict) -> str:
    existing = item.get("sha256")
    if existing:
        return str(existing)
    path = item.get("path")
    if path:
        digest = sha256_of(str(path))
        if digest:
            return digest
        # A missing file is still a stable identity: hash its declared path, never an empty string.
        return hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return hashlib.sha256(
        f"{item.get('filename') or ''}:{item.get('file_id') or ''}".encode("utf-8")
    ).hexdigest()


def ingest_node(state: dict) -> dict:
    """Return the canonical `run_id` + `files` list and one `done` `ingest` report."""
    run_id = state.get("run_id") or _new_run_id()
    files: list[dict] = []
    for index, raw in enumerate(state.get("files") or []):
        item = dict(raw)
        digest = _file_sha256(item)
        item["sha256"] = digest
        item.setdefault("file_id", f"F-{digest[:8]}")
        if not item.get("filename"):
            item["filename"] = Path(str(item.get("path") or f"file-{index}")).name
        item.setdefault("mime", "application/octet-stream")
        item.setdefault("path", "")
        files.append(item)

    if not files:
        return {
            "run_id": run_id,
            "files": [],
            "stages": [
                stage_report(
                    INGEST_STAGE,
                    status="failed",
                    reason="missing `files` prerequisite, refusing to run",
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=INGEST_STAGE,
                op="pass",
                detail={"reason": "no files submitted"},
            ),
        }

    return {
        "run_id": run_id,
        "files": files,
        "stages": [
            stage_report(INGEST_STAGE, status="done", produced=len(files), model_calls=0)
        ],
        **record(
            state,
            agent=SHARED_STAGE_OWNER,
            stage=INGEST_STAGE,
            op="read",
            after=f"{len(files)} file(s)",
            detail={"file_ids": [item["file_id"] for item in files]},
        ),
    }


__all__ = ["INGEST_STAGE", "ingest_node"]
