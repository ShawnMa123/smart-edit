"""Deterministic extraction: read the *current* document, never replay a fixture.

Sources: `openspec/changes/config-driven-audit-extraction/design.md` D2-D4,
spec: `specs/audit-extraction/spec.md`.

The module locates a value by label/alias inside ≤2 adjacent blocks, then asks
`app/parsing/normalize.py` to normalize it. It never re-implements amount, date or currency parsing,
and it never decides which of two conflicting values is "right" — a conflict is returned as an
explicit `conflicted` candidate so `normalize` downgrades the field to `inferred` and an audit rule
cannot pass on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from functools import lru_cache

from app.parsing.extraction_profile import ExtractionProfile, ProfileField
from app.parsing.normalize import normalize_field_value, normalize_ws

# Characters between a label and its value. `-` is deliberately absent: it may be the sign of a
# negative amount, and `normalize` must see that sign to produce `-500.00` instead of `500.00`.
_LEADING = " \t:=|·为"
# Only a colon-like separator (or the Chinese copula `为`) makes a "label: value" pair explicit.
# Plain prose after a label word (`Payment shall be made …`) is not a value — free-text kinds require
# this confirmation.
_EXPLICIT_SEPARATORS = ":=|为"
_TEXT_KINDS = frozenset({"text", "clause_text"})

# Tokenizers are internal, tested and *not* configurable: the profile chooses a `value_kind`, it
# cannot inject a pattern. Each one is anchored at the start of the text after the label.
_AMOUNT_BODY_RE = re.compile(
    r"[+-]?\d[\d,\s]*(?:\.\d+)?(?:\s*(?:K|M|MN|BN|B)(?![A-Za-z]))?",
    re.IGNORECASE,
)
# A currency code written immediately before the number belongs to the value (`USD 500,000.00`),
# so the span stays a real source fragment. Chinese copulas and other prose do not.
_AMOUNT_CURRENCY_RE = re.compile(r"([A-Za-z]{3})\s*$")
_DATE_YMD_RE = re.compile(r"\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?")
_DATE_DMY_RE = re.compile(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}")
_CURRENCY_RE = re.compile(r"[A-Za-z]{3}(?![A-Za-z])")
_INTEGER_RE = re.compile(r"[+-]?\d[\d,\s]*")


def _amount_token(text: str) -> str | None:
    hit = _AMOUNT_BODY_RE.search(text)
    if hit is None:
        return None
    value = hit.group(0).strip()
    prefix = _AMOUNT_CURRENCY_RE.search(text[: hit.start()])
    return f"{prefix.group(1)} {value}" if prefix else value


_TOKENIZERS = {
    "amount": _amount_token,
    "date": lambda text: _first(_DATE_YMD_RE, text) or _first(_DATE_DMY_RE, text),
    "currency": lambda text: _first(_CURRENCY_RE, text),
    "integer": lambda text: _first(_INTEGER_RE, text),
    "text": lambda text: text.strip() or None,
    "clause_text": lambda text: text.strip() or None,
}


@dataclass(frozen=True)
class DeterministicResult:
    """Receipt of the deterministic path. `model_calls` is fixed at 0 by construction."""

    candidates: list[dict] = dataclass_field(default_factory=list)
    trail_entries: list[dict] = dataclass_field(default_factory=list)
    found: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    model_calls: int = 0


def _first(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.match(text)
    return match.group(0).strip() if match else None


def _cut(text: str, max_chars: int) -> str:
    """Trim the candidate window *before* tokenizing, so no locator scans an unbounded fragment."""
    return normalize_ws(text)[:max_chars]


@lru_cache(maxsize=512)
def _label_pattern(needle: str) -> re.Pattern:
    """Word-bounded, case-insensitive label match.

    The boundary keeps `AMOUNT` from matching inside `TOTALAMOUNT`. CJK labels still match next to
    CJK prose, because CJK characters are not `[0-9A-Za-z]`.
    """
    return re.compile(
        rf"(?<![0-9A-Za-z]){re.escape(needle)}(?![0-9A-Za-z])", re.IGNORECASE
    )


def _locate_label(block_text: str, rule: ProfileField) -> tuple[str, int, str] | None:
    """Return `(matched_label, label_rank, text_after_label)` for the best label in this block.

    The first entry in `labels` is the exact field label; later entries are aliases. Ranking is
    `rank asc`, then longest label, then earliest position, which keeps the order reproducible.

    A free-text value (`text` / `clause_text`) is only accepted after an explicit separator
    (`label: value`). Otherwise a prose sentence that happens to start with an alias word
    (`PAYMENT` in "Payment shall be made …") would be read as a second value for the field.
    """
    text = normalize_ws(block_text)
    best: tuple[int, int, int, str, str] | None = None
    for rank, label in enumerate(rule.labels):
        needle = normalize_ws(label)
        if not needle:
            continue
        hit = _label_pattern(needle).search(text)
        if hit is None:
            continue
        cursor = hit.end()
        explicit = False
        while cursor < len(text) and text[cursor] in _LEADING:
            if text[cursor] in _EXPLICIT_SEPARATORS:
                explicit = True
            cursor += 1
        rest = text[cursor:]
        if rest and rule.value_kind in _TEXT_KINDS and not explicit:
            # Prose, not a labeled field: try the next alias/block instead of inventing a value.
            continue
        key = (rank, -len(needle), hit.start())
        if best is None or key < best[:3]:
            best = (*key, label, rest)
    if best is None:
        return None
    rank, _, _start, label, rest = best
    return label, rank, rest


def _value(rule: ProfileField, text: str) -> str | None:
    tokenizer = _TOKENIZERS[rule.value_kind]
    return tokenizer(_cut(text, rule.max_chars))


def _confidence(rule: ProfileField, rank: int, via: str) -> float:
    """Same-block exact label > alias > next block (design D4); rounded for stable reports."""
    value = rule.confidence
    if rank > 0:
        value *= 0.95
    if via == "next_block":
        value *= 0.9
    return round(value, 3)


def _receipt(op: str, value: str | None, source: dict, detail: dict) -> dict:
    ref = f"{source.get('file_id')}/{source.get('page') if source.get('page') is not None else '-'}/{value or ''}"
    return {"op": op, "before": value, "after": None, "ref": ref, "detail": detail}


def _lines(block: dict) -> list[str]:
    """Non-empty visual lines inside one block.

    `parse` merges consecutive plain-text lines into one paragraph block (joined with `\\n`), and a
    PDF block contains several visual rows. A value belongs to the line its label is on — scanning the
    whole block would make `适用规则：URDG 758` swallow every following line up to `max_chars`.
    """
    return [line for line in (block.get("text") or "").splitlines() if line.strip()]


def _next_value(
    blocks: list[dict],
    index: int,
    line_index: int,
    lines: list[str],
    rule: ProfileField,
    trail: list[dict],
    doc: dict,
) -> tuple[str | None, dict | None, bool]:
    """Value on the next line (same block) or first line of the next block, never across pages.

    Returns `(raw, source_block, cross_page_skipped)`.
    """
    block = blocks[index]
    if line_index + 1 < len(lines):
        return _value(rule, lines[line_index + 1]), block, False
    if index + 1 >= len(blocks):
        return None, None, False
    following = blocks[index + 1]
    if following.get("page") != block.get("page"):
        # Never stitch a label to a value on another page: the layout fact would change.
        trail.append(
            _receipt(
                "pass",
                None,
                {"file_id": doc.get("file_id"), "page": block.get("page")},
                {"key": rule.key, "reason": "cross_page_label_value_skipped"},
            )
        )
        return None, None, True
    following_lines = _lines(following)
    if not following_lines:
        return None, None, False
    return _value(rule, following_lines[0]), following, False


def _read_document(doc: dict, rule: ProfileField, trail: list[dict]) -> list[dict]:
    """All label/value hits for one rule in one document. Missing labels produce nothing."""
    candidates: list[dict] = []
    blocks = doc.get("blocks") or []
    for index, block in enumerate(blocks):
        lines = _lines(block)
        for line_index, line in enumerate(lines):
            located = _locate_label(line, rule)
            if located is None:
                continue
            label, rank, rest = located
            raw = _value(rule, rest)
            source_block, via = block, "same_block"

            if raw is None and rule.search == "same_or_next_block":
                raw, source_block, skipped = _next_value(
                    blocks, index, line_index, lines, rule, trail, doc
                )
                if skipped:
                    continue
                if raw is not None:
                    via = "next_block"

            if raw is None:
                # The label exists but the value did not tokenize. Say so; never invent a value.
                trail.append(
                    _receipt(
                        "pass",
                        None,
                        {"file_id": doc.get("file_id"), "page": block.get("page")},
                        {"key": rule.key, "label": label, "reason": "label_without_value"},
                    )
                )
                continue

            source = {
                "file_id": doc.get("file_id"),
                "page": source_block.get("page"),
                "bbox": source_block.get("bbox"),
                "span": raw,
                "form_label": label,
            }
            candidate = {
                "key": rule.key,
                "raw_value": raw,
                "label": label,
                "confidence": _confidence(rule, rank, via),
                "doc_type": None,
                "_source": source,
                "_match": {"label_rank": rank, "via": via, "block_index": index},
            }
            candidates.append(candidate)
            trail.append(
                _receipt(
                    "read",
                raw,
                source,
                {
                    "key": rule.key,
                    "label": label,
                    "value_kind": rule.value_kind,
                    "search": rule.search,
                    "via": via,
                },
            )
        )
    return candidates



def _resolve_conflicts(
    profile: ExtractionProfile,
    candidates: list[dict],
    fields_config: dict[str, dict],
    trail: list[dict],
) -> list[dict]:
    """De-duplicate equal values; keep different values as one `conflicted` candidate.

    A conflict is never settled by "highest confidence": both values are recorded in the trail and
    the field is downgraded by `normalize`, so the audit sees `unconfirmed` rather than a guess.
    """
    grouped: dict[str, list[dict]] = {key: [] for key in profile.fields}
    for candidate in candidates:
        grouped[candidate["key"]].append(candidate)

    resolved: list[dict] = []
    for key, group in grouped.items():
        if not group:
            continue
        group.sort(
            key=lambda item: (
                -float(item.get("confidence") or 0),
                (item.get("_match") or {}).get("label_rank", 0),
                (item.get("_match") or {}).get("block_index", 0),
            )
        )
        ranked = []
        for item in group:
            normalized, notes = normalize_field_value(key, item["raw_value"], fields_config.get(key))
            ranked.append({"candidate": item, "normalized": normalized, "notes": notes})
        distinct = {entry["normalized"] for entry in ranked}

        best = group[0]
        if len(distinct) > 1:
            # Spec: two different values must be marked unconfirmed, never silently settled. The
            # `status` is repeated here so every downstream consumer sees it without re-deriving
            # the rule from `conflicted`.
            best["conflicted"] = True
            best["status"] = "unconfirmed"
            best["conflict_values"] = [
                {
                    "raw_value": entry["candidate"]["raw_value"],
                    "normalized": entry["normalized"],
                    "confidence": entry["candidate"].get("confidence"),
                    "_source": entry["candidate"].get("_source"),
                }
                for entry in ranked
            ]
            trail.append(
                _receipt(
                    "pass",
                    None,
                    best.get("_source") or {},
                    {
                        "key": key,
                        "reason": "ambiguous_extraction",
                        "values": [entry["normalized"] for entry in ranked],
                        "sources": [entry["candidate"].get("_source") for entry in ranked],
                    },
                )
            )
        else:
            for entry in ranked[1:]:
                dropped = entry["candidate"]
                trail.append(
                    _receipt(
                        "pass",
                        dropped.get("raw_value"),
                        dropped.get("_source") or {},
                        {"key": key, "reason": "duplicate_value_ignored"},
                    )
                )
        resolved.append(best)
    return resolved


def extract_deterministic(
    docs: list[dict],
    profile: ExtractionProfile,
    fields_config: dict[str, dict],
) -> DeterministicResult:
    """Locate every profile field in the current `docs.blocks` (no model, `model_calls=0`)."""
    trail: list[dict] = []
    candidates: list[dict] = []
    for rule in profile.fields.values():
        for doc in docs or []:
            if doc.get("errors"):
                trail.append(
                    _receipt(
                        "pass",
                        None,
                        {"file_id": doc.get("file_id"), "page": None},
                        {
                            "key": rule.key,
                            "reason": "file failed to parse, not extracted",
                            "errors": doc.get("errors"),
                        },
                    )
                )
                continue
            candidates.extend(_read_document(doc, rule, trail))

    resolved = _resolve_conflicts(profile, candidates, fields_config, trail)
    found = tuple(key for key in profile.fields if any(item["key"] == key for item in resolved))
    missing = tuple(key for key in profile.fields if key not in found)
    return DeterministicResult(
        candidates=resolved,
        trail_entries=trail,
        found=found,
        missing=missing,
        model_calls=0,
    )

