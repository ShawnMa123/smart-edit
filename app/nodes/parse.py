"""`parse` node: calls the shared-layer `parse()`, writes the stage report and the trail.

Parse reuse (design §5.3): when `docs` already exist and the `(file_id, sha256)` sets match
exactly, they MUST be reused, **never re-parsed**. The stage status on reuse is `done`, not
`skipped` — writing `skipped` makes `require()` / the gate believe "parse never ran", and the user
sees "parse incomplete" with no way to find out why.
"""

from __future__ import annotations

from app.parsing.parse import parse
from app.stages import stage_report
from app.state import SHARED_STAGE_OWNER
from app.trail import record, record_many

PARSE_STAGE = "parse"


def _can_reuse(state: dict) -> bool:
    existing = state.get("docs") or []
    files = state.get("files") or []
    if not existing or not files:
        return False
    existing_keys = {(d.get("file_id"), d.get("sha256")) for d in existing}
    file_keys = {(f.get("file_id"), f.get("sha256")) for f in files}
    return existing_keys == file_keys


def parse_node(state: dict) -> dict:
    files = state.get("files") or []
    if not files:
        # A missing prerequisite is refused, never answered with an empty result
        return {
            "stages": [
                stage_report(
                    PARSE_STAGE, status="failed", reason="missing `files` prerequisite, refusing to run"
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=PARSE_STAGE,
                op="pass",
                detail={"reason": "no files, nothing parsed"},
            ),
        }

    if _can_reuse(state):
        return {
            "stages": [
                stage_report(
                    PARSE_STAGE,
                    status="done",
                    reason="reused: file sha256 unchanged",
                    produced=len(state.get("docs") or []),
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=PARSE_STAGE,
                op="pass",
                detail={"reuse": True, "reason": "file sha256 unchanged"},
            ),
        }

    docs, entries, model_calls = parse(files)
    failed = [doc["file_id"] for doc in docs if doc["errors"]]
    produced = len(docs) - len(failed)

    if produced == 0:
        report = stage_report(
            PARSE_STAGE,
            status="failed",
            reason="all files failed to parse",
            produced=0,
            model_calls=model_calls,
        )
    elif failed:
        report = stage_report(
            PARSE_STAGE,
            status="partial",
            reason=f"{len(failed)} file(s) failed to parse: {','.join(failed)}",
            produced=produced,
            model_calls=model_calls,
        )
    else:
        report = stage_report(PARSE_STAGE, status="done", produced=produced)

    return {
        "docs": docs,
        "stages": [report],
        **record_many(state, agent=SHARED_STAGE_OWNER, stage=PARSE_STAGE, entries=entries),
    }