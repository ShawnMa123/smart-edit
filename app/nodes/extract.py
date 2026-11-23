"""`extract` node: chooses the deterministic profile path or the shared-layer model path.

**MUST NOT write `fields`** — candidate values are not normalized, not classified, and have no
provenance check; writing them into `fields` hands downstream data that only *looks* usable
(design §10).

Deterministic path (change `config-driven-audit-extraction` D3): when a validated extraction
profile is supplied, candidates come from `app/parsing/deterministic_extract.py`, `model_calls` is 0
and a missing LLM is not an error. Without a profile the existing fixture/LLM path is unchanged, so
a missing provider still fails loudly.
"""

from __future__ import annotations

from app.config import FieldsConfigError, load_fields_config
from app.parsing.deterministic_extract import extract_deterministic
from app.parsing.extract import extract
from app.stages import stage_report
from app.state import SHARED_STAGE_OWNER
from app.trail import record, record_many

EXTRACT_STAGE = "extract"

_FIXTURE_PREFIX = "fixture:"


def extract_node(
    state: dict,
    *,
    llm=None,
    model: str = "gpt-4o",
    field_keys: list[str] | None = None,
    profile=None,
    fields_yaml: dict[str, dict] | None = None,
) -> dict:
    docs = state.get("docs") or []
    if not docs:
        return {
            "_candidates": [],
            "_extraction": None,
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

    if profile is not None:
        return _deterministic(
            state, docs, profile, llm=llm, model=model, fields_yaml=fields_yaml
        )

    if llm is None:
        # Design D6: no provider fails the stage loudly. Inventing candidates here would make a
        # missing API key indistinguishable from a real extraction.
        return {
            "_candidates": [],  # nothing extracted: never leave a stale value from an earlier run
            "_extraction": None,
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

    if all(doc.get("errors") for doc in docs):
        # `errors` is per-file; if every file failed, there is no text to extract from. Reporting
        # `done` with zero candidates would let the next stage write missing-field placeholders and
        # make a broken import look like a successful check.
        return {
            "_candidates": [],
            "stages": [
                stage_report(
                    EXTRACT_STAGE,
                    status="failed",
                    reason="all files failed to parse; nothing to extract",
                    model_calls=0,
                )
            ],
            **record(
                state,
                agent=SHARED_STAGE_OWNER,
                stage=EXTRACT_STAGE,
                op="pass",
                detail={"reason": "all files failed to parse, nothing extracted"},
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
        "_extraction": _model_provenance(result, field_keys, provider),
        "stages": [report],
        **record_many(
            state, agent=SHARED_STAGE_OWNER, stage=EXTRACT_STAGE, entries=result.trail_entries
        ),
    }


def _model_provenance(result, field_keys: list[str] | None, provider: str | None) -> dict:
    """Provenance for the fixture/LLM path: the source is named, never `deterministic`."""
    found = {candidate.get("key") for candidate in result.candidates if candidate.get("key")}
    requested = set(field_keys or []) or found
    return {
        "source": "fixture" if (provider or "").startswith(_FIXTURE_PREFIX) else "llm",
        "profile_id": None,
        "version": None,
        "content_sha256": None,
        "fields_found": len(found),
        "fields_missing": len(requested - found),
    }


def _deterministic(
    state: dict,
    docs: list[dict],
    profile,
    *,
    llm,
    model: str,
    fields_yaml: dict[str, dict] | None,
) -> dict:
    """Deterministic extraction, with an explicit opt-in model fallback for missing fields only."""
    if fields_yaml is None:
        try:
            fields_yaml = load_fields_config()
        except FieldsConfigError as exc:
            return {
                "_candidates": [],
                "_extraction": None,
                "stages": [
                    stage_report(
                        EXTRACT_STAGE, status="failed", reason=f"fields.yaml unavailable: {exc}"
                    )
                ],
                **record(
                    state,
                    agent=SHARED_STAGE_OWNER,
                    stage=EXTRACT_STAGE,
                    op="pass",
                    detail={"reason": "fields.yaml unavailable, deterministic extraction refused"},
                ),
            }

    result = extract_deterministic(docs, profile, fields_yaml)
    candidates = list(result.candidates)
    trail_entries = list(result.trail_entries)
    model_calls = 0
    fallback_used = False

    fallback_enabled = bool((profile.llm_fallback or {}).get("enabled"))
    if fallback_enabled and llm is not None and result.missing:
        # Only fields the deterministic pass could not read are candidates for the fallback. A
        # deterministic hit is final (spec: model fallback never overrides deterministic hits).
        fallback_used = True
        extra = extract(docs, list(result.missing), llm=llm, model=model)
        model_calls = extra.model_calls
        trail_entries.extend(extra.trail_entries)
        for candidate in extra.candidates:
            if candidate.get("key") not in result.missing:
                # A model answer for a field the deterministic pass already read is discarded:
                # model output never overrides a deterministic hit.
                continue
            fallback = {**candidate, "status": "unconfirmed", "confidence": 0.3}
            candidates.append(fallback)
            trail_entries.append(
                {
                    "op": "pass",
                    "before": fallback.get("raw_value"),
                    "after": None,
                    "ref": ((fallback.get("_source") or {}).get("file_id") or ""),
                    "detail": {
                        "key": fallback.get("key"),
                        "reason": "model_fallback_candidate_unconfirmed",
                    },
                }
            )

    provenance = {
        **profile.identity,
        "source": "deterministic",
        "fields_found": len(result.found),
        "fields_missing": len(result.missing),
        "llm_fallback": fallback_used,
    }
    reason = f"deterministic profile {profile.profile_id}@{profile.version}"
    if fallback_used:
        reason += " (+llm fallback, unconfirmed)"
    report = stage_report(
        EXTRACT_STAGE,
        status="done",
        reason=reason,
        produced=len(candidates),
        model_calls=model_calls,
    )
    return {
        "_candidates": candidates,
        "_extraction": provenance,
        "stages": [report],
        **record_many(
            state, agent=SHARED_STAGE_OWNER, stage=EXTRACT_STAGE, entries=trail_entries
        ),
    }