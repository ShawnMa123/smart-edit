"""`normalize` node: calls `build_fields()`, numbers findings, writes the stage report,
and clears `_candidates`.

Three things must happen:
1. `fields.yaml` missing / unusable -> all three stages `failed`, **never** continue with an empty dict
2. Finding drafts are numbered by `app/findings.py` (`N-` prefix, no collisions on rerun)
3. `_candidates` is cleared right after use (`Overwrite([])`), never left in the checkpoint
"""

from __future__ import annotations

from app.config import FieldsConfigError, load_fields_config
from app.findings import materialize_findings
from app.nodes import clear_candidates
from app.parsing.normalize import build_fields
from app.stages import stage_report
from app.state import SHARED_STAGE_OWNER
from app.trail import record, record_many

NORMALIZE_STAGE = "normalize"


def _fields_config_unavailable(state: dict, reason: str) -> dict:
    """A config incident is not "the material did not say it": all three stages `failed`,
    and the whole run is `fail`."""
    reports = [
        stage_report(stage, status="failed", reason=f"fields.yaml unavailable: {reason}")
        for stage in ("parse", "extract", "normalize")
    ]
    return {
        "stages": reports,
        **record(
            state,
            agent=SHARED_STAGE_OWNER,
            stage=NORMALIZE_STAGE,
            op="pass",
            detail={"reason": "fields.yaml unavailable, refusing to run", "error": reason},
        ),
    }


def normalize_node(state: dict, *, fields_yaml: dict[str, dict] | None = None) -> dict:
    if fields_yaml is None:
        try:
            fields_yaml = load_fields_config()
        except FieldsConfigError as exc:
            return _fields_config_unavailable(state, str(exc))

    docs = state.get("docs") or []
    if not docs:
        return {
            "stages": [
                stage_report(
                    NORMALIZE_STAGE, status="failed", reason="missing `docs` prerequisite, refusing to run"
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=NORMALIZE_STAGE,
                op="pass",
                detail={"reason": "no docs, nothing normalized"},
            ),
        }

    if all(doc.get("errors") for doc in docs):
        # Nothing was read: do not turn every required field into a `missing` placeholder, which
        # would make "the file could not be parsed" look like "the field was checked and is absent".
        return {
            "fields": {},
            "extra_fields": {},
            "business_type": None,
            "_candidates": clear_candidates(),
            "stages": [
                stage_report(
                    NORMALIZE_STAGE,
                    status="failed",
                    reason="all files failed to parse; nothing to normalize",
                    model_calls=0,
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=NORMALIZE_STAGE,
                op="pass",
                detail={"reason": "all files failed to parse, nothing normalized"},
            ),
        }

    result = build_fields(state.get("_candidates") or [], docs, fields_yaml=fields_yaml)
    materialized = materialize_findings(state, result.findings)

    return {
        "fields": result.fields,
        "extra_fields": result.extra_fields,
        "business_type": result.business_type,
        "_candidates": clear_candidates(),
        "stages": [
            stage_report(
                NORMALIZE_STAGE,
                status="done",
                produced=len(result.fields) + len(result.extra_fields),
            )
        ],
        "findings": materialized["findings"],
        **record_many(
            state,
            agent=SHARED_STAGE_OWNER,
            stage=NORMALIZE_STAGE,
            entries=result.trail_entries + materialized["trail"],
        ),
    }