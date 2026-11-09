"""Extraction (the only model entry point).

Sources: `openspec/changes/agent-normalize/design.md` §6,
contract signatures: `openspec/changes/poc-skeleton/design.md` §6.

Three rules:
1. **Pure function**: no `state` in the signature; trail entries are returned as `trail_entries`
   and written back by the node via `record_many()`
2. Candidate fields only (`_candidates`), **never `fields`** — values that have not been
   classified and normalized are unusable
3. Page info (`page` / `bbox`) is located back in the source by the system;
   **MUST NOT** be produced by the model
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from app.parsing.normalize import normalize_ws

PROMPT_HARD_RULES = """1. Only copy a source fragment verbatim as the span; never rewrite, never stitch across paragraphs.
2. The span is the smallest locatable fragment; do not include field labels such as "Applicant:".
3. Keep the original case and spelling of the value; do not correct it, do not upper-case it.
4. If a field cannot be found, do not guess and do not invent it — simply omit it."""

REQUIRED_CANDIDATE_KEYS = ("key", "raw_value", "span", "confidence")


@dataclass(frozen=True)
class ExtractResult:
    """Pure-function receipt of `extract` (contract §6)."""

    candidates: list[dict] = field(default_factory=list)
    trail_entries: list[dict] = field(default_factory=list)
    model_calls: int = 0
    failed_batches: list[str] = field(default_factory=list)


def locate_span(
    doc: dict,
    span: str,
    *,
    normalized_blocks: list[str] | None = None,
) -> tuple[int | None, list[float] | None]:
    """Locate `span` inside `doc.blocks` and return `(page, bbox)`; `(None, None)` if not found.

    Comparison uses `normalize_ws` (the same function as `provenance_check`).
    Only a hit **inside a single block** is accepted: a span crossing blocks is an overreach case,
    so return None and let it take the "not locatable" branch — never guess a bbox between two
    blocks.

    `normalized_blocks` lets one extraction pass normalise each block once instead of once per
    candidate (design D12).
    """
    needle = normalize_ws(span)
    if not needle:
        return None, None
    blocks = doc.get("blocks") or []
    texts = normalized_blocks or [normalize_ws(block["text"]) for block in blocks]
    for block, text in zip(blocks, texts):
        if needle in text:
            return block.get("page"), block.get("bbox")
    return None, None


def build_prompt(batch_text: str, field_keys: list[str]) -> str:
    """Build the prompt. The four hard rules go into the prompt, not into verbal agreements."""
    keys = "\n".join(f"- {key}" for key in field_keys)
    return (
        "You extract fields from trade documents. Copy only; do not interpret or rewrite.\n"
        "Hard rules:\n"
        f"{PROMPT_HARD_RULES}\n\n"
        "Fields to extract:\n"
        f"{keys}\n\n"
        "Output a JSON array; each item has key / raw_value / span / label / confidence / doc_type.\n"
        "Source text:\n"
        f"{batch_text}\n"
    )


def _as_candidates(payload: object) -> list[dict] | None:
    """Normalize the model output into a candidate list; `None` when it violates the schema (triggers retry)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if isinstance(payload, dict):
        payload = payload.get("candidates")
    if not isinstance(payload, list):
        return None
    out: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            return None
        if any(item.get(key) in (None, "") for key in REQUIRED_CANDIDATE_KEYS):
            return None
        if not isinstance(item.get("span"), str) or not isinstance(item.get("raw_value"), str):
            return None
        try:
            float(item["confidence"])
        except (TypeError, ValueError):
            return None
        out.append(item)
    return out


def _batches(doc: dict, batch_chars: int) -> list[tuple[int, int, bool]]:
    """Accumulate `blocks` into batches (**never splitting a block**). Returns `(start, end_exclusive, oversize)`."""
    blocks = doc.get("blocks") or []
    batches: list[tuple[int, int, bool]] = []
    start = 0
    size = 0
    for index, block in enumerate(blocks):
        length = len(block["text"])
        if index > start and size + length > batch_chars:
            batches.append((start, index, False))
            start, size = index, 0
        size += length
    if start < len(blocks):
        oversize = len(blocks) - start == 1 and size > batch_chars
        batches.append((start, len(blocks), oversize))
    return batches


def extract(
    docs: list[dict],
    field_keys: list[str],
    *,
    llm,
    model: str = "gpt-4o",
    batch_chars: int = 12000,
) -> ExtractResult:
    """Extract candidate fields. `llm` is a callable (production injects a structured-output model,
    tests inject a stub).

    - Output violating the schema -> **retry once**; a second failure lands in `failed_batches`
    - Files that failed to parse are not extracted, but they must record `op="pass"` +
      `detail.reason` (never a silent `continue`)
    - `confidence` is used for ranking here only and never reaches `FieldValue`
    """
    candidates: list[dict] = []
    trail_entries: list[dict] = []
    failed_batches: list[str] = []
    model_calls = 0

    for doc in docs or []:
        if doc.get("errors"):
            trail_entries.append(
                {
                    "op": "pass",
                    "before": None,
                    "after": None,
                    "ref": doc.get("file_id"),
                    "detail": {
                        "reason": "file failed to parse, not extracted",
                        "file_id": doc.get("file_id"),
                        "errors": doc.get("errors"),
                    },
                }
            )
            continue

        # One normalisation per block for the whole document, not one per candidate (design D12).
        normalized_blocks = [normalize_ws(block["text"]) for block in doc.get("blocks") or []]

        for batch_index, (start, end, oversize) in enumerate(_batches(doc, batch_chars)):
            blocks = doc["blocks"][start:end]
            batch_id = f"{doc['file_id']}#{batch_index}"
            prompt = build_prompt("\n".join(block["text"] for block in blocks), field_keys)
            prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
            detail = {
                "file_id": doc.get("file_id"),
                "index": batch_index,
                "range": [start, end - 1],
                "blocks": len(blocks),
            }
            if oversize:
                detail["oversize_block"] = True

            parsed, calls = _call_with_retry(llm, prompt)
            model_calls += calls
            trail_entries.append(
                {
                    "op": "llm_call",
                    "before": None,
                    "after": f"{batch_id}:{len(parsed or [])}",
                    "ref": doc.get("file_id"),
                    "model": model,
                    "prompt_hash": prompt_hash,
                    "detail": detail,
                }
            )
            if parsed is None:
                failed_batches.append(batch_id)
                continue

            for item in parsed:
                page, bbox = locate_span(doc, item["span"], normalized_blocks=normalized_blocks)
                candidates.append(
                    {
                        "key": item["key"],
                        "raw_value": item["raw_value"],
                        "label": item.get("label"),
                        "confidence": item.get("confidence"),
                        "doc_type": item.get("doc_type"),
                        "_source": {
                            "file_id": doc.get("file_id"),
                            "page": page,
                            "bbox": bbox,
                            "span": item["span"],
                            "form_label": None,
                        },
                    }
                )

    return ExtractResult(
        candidates=candidates,
        trail_entries=trail_entries,
        model_calls=model_calls,
        failed_batches=failed_batches,
    )


def _call_with_retry(llm, prompt: str) -> tuple[list[dict] | None, int]:
    """Call once; call again if the schema is violated. Returns `(candidates or None, call count)`."""
    for attempt in range(2):
        try:
            payload = llm(prompt)
        except Exception:  # model-side errors are treated like a schema violation: retry once
            if attempt == 0:
                continue
            return None, attempt + 1
        parsed = _as_candidates(payload)
        if parsed is not None:
            return parsed, attempt + 1
    return None, 2