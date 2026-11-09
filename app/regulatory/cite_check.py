"""Citation downgrade rules. A claim is never deleted; unsupported text stays visible for a human.

Rules, in order (docs/agent3-regulatory-handoff.md §6.6):

1. `chunk_id` not in this retrieval -> `chunk_id=None`, `support="insufficient"`.
2. `support="insufficient"` with a non-null `chunk_id` -> `chunk_id=None`.
3. valid `chunk_id`: the claim text must be a verbatim (whitespace-normalised) fragment of the
   cited chunk; a paraphrase downgrades but **keeps** the citation so a human can inspect it.
4. valid `chunk_id`: every entity extracted from the claim must appear in the cited chunk
   (whitespace-normalised); a missing entity downgrades but keeps the citation.
5. No semantic entailment: this is an entity/text-coverage check, not NLI, and the trail says so.
"""

from __future__ import annotations

import re

from app.regulatory.entities import extract_entities


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold() or _compact(needle) in _compact(haystack)


def _trail(claim: dict, reason: str, *, ref: str | None, detail: dict | None = None) -> dict:
    return {
        "op": "transform",
        "before": claim.get("text"),
        "after": claim.get("support"),
        "ref": ref,
        "model": None,
        "prompt_hash": None,
        "detail": {"reason": reason, **(detail or {})},
    }


def cite_check(claims: list[dict], retrieved: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return `(claims, trail_entries)`; every downgrade is recorded with a non-empty reason."""
    chunks = {
        str(chunk.get("chunk_id")): chunk
        for chunk in retrieved
        if chunk.get("chunk_id") is not None
    }
    out: list[dict] = []
    trail: list[dict] = []

    for claim in claims or []:
        current = dict(claim)
        chunk_id = current.get("chunk_id")
        support = current.get("support")

        if chunk_id is not None and str(chunk_id) not in chunks:
            trail.append(
                _trail(
                    current,
                    "chunk_id_not_in_retrieved",
                    ref=str(chunk_id),
                    detail={"chunk_id": str(chunk_id)},
                )
            )
            current["chunk_id"] = None
            current["support"] = "insufficient"
            chunk_id = None
            support = "insufficient"

        if support == "insufficient" and chunk_id is not None:
            trail.append(
                _trail(
                    current,
                    "insufficient_with_citation",
                    ref=str(chunk_id),
                    detail={"chunk_id": str(chunk_id)},
                )
            )
            current["chunk_id"] = None
            chunk_id = None

        if chunk_id is not None:
            chunk = chunks[str(chunk_id)]
            text = _normalize_ws(str(chunk.get("text") or ""))
            claim_text = _normalize_ws(str(current.get("text") or ""))
            if claim_text and not _contains(text, claim_text):
                trail.append(
                    _trail(
                        current,
                        "text_not_in_chunk",
                        ref=str(chunk_id),
                        detail={
                            "chunk_id": str(chunk_id),
                            "explanation": "claim text is not a verbatim fragment of the cited chunk",
                        },
                    )
                )
                current["support"] = "insufficient"
            missing = [
                entity
                for entity in extract_entities(str(current.get("text") or ""))
                if not _contains(text, entity)
            ]
            if missing:
                trail.append(
                    _trail(
                        current,
                        "entity_not_in_chunk",
                        ref=str(chunk_id),
                        detail={
                            "chunk_id": str(chunk_id),
                            "missing_entities": missing,
                            "semantic_entailment": False,
                        },
                    )
                )
                current["support"] = "insufficient"
                # Keep the citation: the reader needs to see which source was claimed.

        out.append(current)
    return out, trail
