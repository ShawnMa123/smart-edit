"""`extract` node: calls the shared-layer `extract()` and stores candidates in `_candidates`.

**MUST NOT write `fields`** — candidate values are not normalized, not classified, and have no
provenance check; writing them into `fields` hands downstream data that only *looks* usable
(design §10).
"""

from __future__ import annotations

from app.parsing.extract import extract
from app.stages import stage_report
from app.state import SHARED_STAGE_OWNER
from app.trail import record, record_many

EXTRACT_STAGE = "extract"


def extract_node(
    state: dict,
    *,
    llm=None,
    model: str = "gpt-4o",
    field_keys: list[str] | None = None,
) -> dict:
    docs = state.get("docs") or []
    if not docs:
        return {
            "stages": [
                stage_report(
                    EXTRACT_STAGE, status="failed", reason="missing `docs` prerequisite, refusing to run"
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=EXTRACT_STAGE,
                op="pass",
                detail={"reason": "no docs, nothing extracted"},
            ),
        }

    result = extract(docs, list(field_keys or []), llm=llm, model=model)
    if result.failed_batches:
        report = stage_report(
            EXTRACT_STAGE,
            status="partial",
            reason=f"{len(result.failed_batches)} batch(es) failed",
            produced=len(result.candidates),
            model_calls=result.model_calls,
        )
    else:
        report = stage_report(
            EXTRACT_STAGE,
            status="done",
            produced=len(result.candidates),
            model_calls=result.model_calls,
        )

    return {
        "_candidates": result.candidates,
        "stages": [report],
        **record_many(
            state, agent=SHARED_STAGE_OWNER, stage=EXTRACT_STAGE, entries=result.trail_entries
        ),
    }