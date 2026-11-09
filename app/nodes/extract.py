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

    if llm is None:
        # Design D6: no provider fails the stage loudly. Inventing candidates here would make a
        # missing API key indistinguishable from a real extraction.
        return {
            "_candidates": [],  # nothing extracted: never leave a stale value from an earlier run
            "stages": [
                stage_report(
                    EXTRACT_STAGE,
                    status="failed",
                    reason="no model provider configured (set SMART_EDIT_LLM)",
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=EXTRACT_STAGE,
                op="pass",
                detail={"reason": "no model provider configured, nothing extracted"},
            ),
        }

    result = extract(docs, list(field_keys or []), llm=llm, model=model)
    provider = getattr(llm, "provider", None)
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
            # A fixture-backed run must be distinguishable from a provider run by this field alone.
            reason=f"candidates from {provider}" if provider else None,
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