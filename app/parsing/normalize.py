"""Value normalization + field mapping + three-way classification + business-type detection.

Sources: `openspec/changes/agent-normalize/design.md` §7.1-§7.7,
contract signatures: `openspec/changes/poc-skeleton/design.md` §6.

Three rules (breaking any of them breaks the seam):
1. Signatures never take `state` — this module is unit-testable without a graph, and trail
   entries are returned as `trail_entries`
2. `normalize_ws` / `MAX_SPAN_LEN` are defined **here and only here**; A's `extracted` decision,
   C's `provenance_check` and B's consistency comparison must all import them, never re-implement
3. This module makes **zero model calls** (the only model entry point is `extract`)

Single benchmark = `normalize_ws`. Once the rules diverge, every `extracted` field gets rejected by
Agent 4 and the cause is extremely hard to locate.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.state import FieldValue

# Shared with agent-audit's provenance_check (design §7.2 rule 4)
MAX_SPAN_LEN = 200

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-")
_SINGLE_QUOTES = dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b\u2032\u2035"), "'")
_DOUBLE_QUOTES = dict.fromkeys(
    map(ord, "\u201c\u201d\u201e\u201f\u2033\u2036\u00ab\u00bb\u300c\u300d\u300e\u300f"), '"'
)
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\ufeff]")
_WS = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    """The single layer-wide benchmark for "do these two strings point at the same source text".
    5 steps, order is not negotiable.

    1. `NFKC` compatibility normalization — full-width to half-width, compat chars to standard
       form (`：`->`:`、`１`->`1`、`Ⅳ`->`IV`)
    2. Strip zero-width and bidi control chars — U+200B-200F, U+202A-202E, U+FEFF
    3. Dash normalization                     — U+2010-U+2015, U+2212, U+FE58, U+FE63, U+FF0D -> `-`
    4. Quote normalization                    — ``''‚‛′‵``->`'`; `""„‟″‶«»「」『』`->`"`
    5. Whitespace collapse + strip            — every Unicode space (incl. U+3000, U+00A0,
       `\\n`, `\\t`) -> a single space

    **Explicitly not done** (equally important, otherwise the two ends diverge again):
    - Case folding (`lower()` / `casefold()`): the case of a name is a **fact**. If the model
      copies `ABC Trading` as `abc trading`, that is exactly what must be judged unlocatable —
      it did not copy verbatim
    - Punctuation / space removal: it would hide model stitching and rewriting, and
      `provenance_check` would lose its meaning
    - Synonyms, unit conversion, simplified/traditional conversion: business judgement (Agent 2),
      not "do these point at the same source text"
    - Regex stripping of HTML / headers / footers: that belongs in `parse`, not smuggled into the
      benchmark
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _INVISIBLE.sub("", s)
    s = s.translate(_DASHES).translate(_SINGLE_QUOTES).translate(_DOUBLE_QUOTES)
    return _WS.sub(" ", s).strip()


def locate_span(full_text: str, span: str) -> bool:
    """Whether `span` occurs in `full_text` (internally only via `normalize_ws`).

    The contract signature is in `poc-skeleton/design.md` §6. Note it is not the same function as
    the same-named `locate_span(doc, span)` in `app/parsing/extract.py`: that one backfills
    `page` / `bbox`, this one only answers "is it there". Both use `normalize_ws` only and must
    never grow their own rule set.
    """
    needle = normalize_ws(span)
    if not needle:
        return False
    return needle in normalize_ws(full_text)


def normalized_full_texts(docs: list[dict]) -> dict[str, str]:
    """Normalise each document's `full_text` **once** (design D12).

    Locating each span otherwise re-normalises the whole document; for a 48k-character file with 15
    fields that is 15 full normalisations (~285 ms measured) instead of one.
    """
    return {doc["file_id"]: normalize_ws(doc["full_text"]) for doc in docs or []}


def span_locatable(src: dict, docs: list, *, normalized: dict[str, str] | None = None) -> bool:
    """Whether the span can be located in **the file it itself declares**.

    [Why a single file only] `provenance_check` compares against the full text fetched by
    `file_id`. If cross-file search were allowed here, Agent 1 would mark `extracted` while
    Agent 4 fails it — two verdicts on the same data.

    [Why `normalized`] Callers that check many spans against the same documents should pass
    `normalized_full_texts(docs)` so each document is normalised once (design D12). The fast path is
    exactly equivalent to the default one.
    """
    file_id = (src or {}).get("file_id", "")
    index = normalized if normalized is not None else normalized_full_texts(docs)
    text = index.get(file_id)
    needle = normalize_ws((src or {}).get("span", ""))
    return bool(needle) and text is not None and needle in text


# Any of these notes downgrades the field to `inferred` (design §7.4)
DOWNGRADING_NOTES = frozenset(
    {
        "date_ambiguous",
        "amount_not_numeric",
        "currency_not_iso4217",
        "country_not_iso3166",
        "not_numeric",
        "span_oversize",
        "merged_across_pages",
        "value_truncated",
    }
)


def classify(value: str | None, locatable: bool, notes: list[str]) -> str:
    """Three-way classification. **Only these three branches**; any special case needs a spec change first."""
    if value is None or value == "":
        return "missing"
    if locatable and not (DOWNGRADING_NOTES & set(notes)):
        return "extracted"
    return "inferred"


# --------------------------------------------------------------------------
# §7.3 value normalization
# --------------------------------------------------------------------------

# design §7.3 splits `string` into "name-like" (strip leading/trailing whitespace only) and
# "address/clause-like" (collapse runs of whitespace). In the POC only free-text clause fields
# belong to the latter, so they are listed explicitly instead of being guessed from the key.
FREEFORM_TEXT_KEYS = frozenset({"payment_terms"})

_SENTENCE_ENDS = "。！？；!?;."
_CURRENCY_PREFIX = re.compile(r"^[^\d\-(+]*")
_MULTIPLIER = re.compile(r"(?i)\s*(k|m|mn|bn|b)$")


def shrink_span(span: str) -> str | None:
    """Cut an over-long span at a sentence boundary so it fits inside `MAX_SPAN_LEN`
    (design §7.2 rule 4).

    Returns `None` when no cut is possible (a single sentence longer than 200). The caller must
    then record `span_oversize` and downgrade to `inferred`.
    **Never** hard-truncate the span here — a truncated source fragment either still matches or it
    does not, and both outcomes are wrong.
    """
    if len(span) <= MAX_SPAN_LEN:
        return span
    cut = 0
    for index, char in enumerate(span):
        if index >= MAX_SPAN_LEN:
            break
        if char in _SENTENCE_ENDS:
            cut = index + 1
    if cut:
        return span[:cut].strip()
    return None


def cross_page_span(doc: dict, span: str) -> list[int] | None:
    """Detect a span that only exists by stitching several blocks together.

    A non-`None` return is the list of page numbers involved (deduped, ascending), i.e. a
    cross-page span; inside a single block, or not found at all, returns `None`.
    Cross-page stitching changes the layout fact, so it must be downgraded to `inferred` for
    human confirmation (design §7.2 rule 5).
    """
    needle = normalize_ws(span)
    if not needle:
        return None
    blocks = doc.get("blocks") or []
    for start in range(len(blocks)):
        acc = ""
        pages: list[int] = []
        for end in range(start, len(blocks)):
            acc = normalize_ws(f"{acc} {blocks[end]['text']}")
            page = blocks[end].get("page")
            if isinstance(page, int) and page not in pages:
                pages.append(page)
            if needle in acc:
                if end > start and len(pages) > 1:
                    return sorted(pages)
                return None
            if len(acc) > len(needle) + 1000:
                break
    return None


def _normalize_amount(raw: str, fdef: dict, notes: list[str]) -> str:
    """Amount -> `Decimal` with 2 decimals, dropping thousands separators and currency prefixes
    (design §7.3).

    `Decimal` is mandatory, `float` is not allowed: `0.1+0.2` would show up as
    `0.30000000000000004` at the gate and in the UI, and that number appearing in front of a
    customer costs far more than writing one extra `Decimal`.
    """
    text = normalize_ws(raw)
    body = _CURRENCY_PREFIX.sub("", text)
    # Thousands separators can be `,` or a space (both show up in PDFs)
    body = re.sub(r"[,\s]", "", body)
    multiplier = Decimal(1)
    hit = _MULTIPLIER.search(body)
    if hit:
        factor = {"k": "1000", "m": "1000000", "mn": "1000000", "bn": "1000000000", "b": "1000000000"}
        multiplier = Decimal(factor[hit.group(1).lower()])
        body = body[: hit.start()].strip()
    try:
        amount = Decimal(body) * multiplier
    except (InvalidOperation, ValueError):
        notes.append("amount_not_numeric")
        return raw.strip()
    precision = int(fdef.get("precision", 2) or 2) if fdef else 2
    quantum = Decimal(1).scaleb(-precision)
    return f"{amount.quantize(quantum, rounding=ROUND_HALF_UP):f}"


def _normalize_currency(raw: str, notes: list[str]) -> str:
    text = normalize_ws(raw).upper()
    if re.fullmatch(r"[A-Z]{3}", text):
        return text
    notes.append("currency_not_iso4217")
    return raw.strip()


def _normalize_date(raw: str, fdef: dict, notes: list[str]) -> str:
    """Date -> ISO 8601; ambiguous input is resolved by the field's `date_order`, and when that is
    not declared the raw value is kept and the field downgraded."""
    text = normalize_ws(raw)
    ym = re.fullmatch(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?", text)
    if ym:
        return _iso_or_downgrade(raw, ym.group(1), ym.group(2), ym.group(3), notes)
    parts = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
    if parts:
        first, second, third = parts.groups()
        order = (fdef or {}).get("date_order")
        if order == "DMY":
            return _iso_or_downgrade(raw, third, second, first, notes)
        if order == "MDY":
            return _iso_or_downgrade(raw, third, first, second, notes)
        # With a null date_order we **must not pick an interpretation** (spec: ambiguous date)
        notes.append("date_ambiguous")
        return raw.strip()
    notes.append("date_ambiguous")
    return raw.strip()


def _iso_or_downgrade(raw: str, year: str, month: str, day: str, notes: list[str]) -> str:
    full_year = int(year) + 2000 if len(year) == 2 else int(year)
    try:
        return date(full_year, int(month), int(day)).isoformat()
    except ValueError:
        notes.append("date_ambiguous")
        return raw.strip()


def _normalize_integer(raw: str, notes: list[str]) -> str:
    """Integer fields drop the unit suffix (`720 DAYS` -> `720`).

    Any trailing alphabetic suffix is stripped: in the POC `type: integer` is only used for
    day-count fields (`tenor_days`). Before adding any unit-sensitive integer field, extend
    `fields.yaml` with a `unit` declaration and revisit this function.
    """
    text = normalize_ws(raw)
    hit = re.match(r"[+-]?\d[\d,\s]*", text)
    if not hit:
        notes.append("not_numeric")
        return raw.strip()
    return str(int(re.sub(r"[,\s]", "", hit.group(0))))


def _normalize_country(raw: str, notes: list[str]) -> str:
    text = normalize_ws(raw).upper()
    if re.fullmatch(r"[A-Z]{2}", text):
        return text
    notes.append("country_not_iso3166")
    return raw.strip()


def _normalize_string(raw: str, key: str) -> str:
    """`string`: name-like fields **only strip leading/trailing whitespace**, preserving the
    original case and spelling (seam one)."""
    if key in FREEFORM_TEXT_KEYS:
        return _WS.sub(" ", raw).strip()
    return raw.strip()


def _normalize_value(ftype: str, raw: str, key: str, fdef: dict, notes: list[str]) -> str:
    if ftype == "amount":
        return _normalize_amount(raw, fdef, notes)
    if ftype == "currency":
        return _normalize_currency(raw, notes)
    if ftype == "date":
        return _normalize_date(raw, fdef, notes)
    if ftype == "integer":
        return _normalize_integer(raw, notes)
    if ftype == "country":
        return _normalize_country(raw, notes)
    return _normalize_string(raw, key)


# --------------------------------------------------------------------------
# §7.4 / §7.5 three-way classification + truncation + `N-` Finding drafts
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizeResult:
    """Pure-function receipt of the `normalize` stage (contract §6).

    `findings` holds **drafts**: the contract writes it as `list[Finding]`, but `Finding.id` can
    only be assigned by the node through `app/findings.py::materialize_findings()` (design §7.5),
    so what lives here is a "Finding body without an id" — same fields as `Finding`, minus `id`.
    """

    fields: dict[str, FieldValue] = field(default_factory=dict)
    extra_fields: dict[str, FieldValue] = field(default_factory=dict)
    business_type: str | None = None
    findings: list[dict] = field(default_factory=list)
    trail_entries: list[dict] = field(default_factory=list)


def _truncation_finding(key: str, original: str, max_length: int) -> dict:
    """Finding draft for an over-long value (design §7.5, **without an id**)."""
    return {
        "source": "normalization",
        "kind": "invalid_value",
        "rule_id": f"F-{key}-max_length",
        "severity": "warn",
        "blocking": False,  # always False: blocking is declared by requirements.yaml only
        "resolved": False,
        "resolution": None,
        "field_keys": [key],
        "message": (
            f"{key} value length {len(original)} exceeds the fields.yaml limit "
            f"{max_length}; it was truncated, please confirm manually"
        ),
        "evidence": original[:80],
        "citation": None,
        "suggestion": "Check whether this field really is that long in the source, "
        "and correct it in the review console if needed",
    }


def _build_field(
    key: str,
    candidate: dict,
    fdef: dict | None,
    docs_by_file: dict[str, dict],
) -> tuple[FieldValue, list[dict], dict | None]:
    """One candidate -> `FieldValue` + trail receipts + (optional) Finding draft."""
    notes: list[str] = []
    raw_value = str(candidate.get("raw_value") or "")
    src = dict(candidate.get("_source") or {})
    trail: list[dict] = []

    span = str(src.get("span") or "")
    if len(span) > MAX_SPAN_LEN:
        shrunk = shrink_span(span)
        if shrunk is None:
            # No cut possible: keep the whole span but it must be downgraded, and never truncate the span itself
            notes.append("span_oversize")
        else:
            span = shrunk
    src["span"] = span

    ftype = (fdef or {}).get("type") or "string"
    value = _normalize_value(ftype, raw_value, key, fdef or {}, notes)

    # §7.5 truncation: the value may be truncated, the provenance never
    max_length = (fdef or {}).get("max_length")
    finding = None
    if max_length and len(value) > int(max_length):
        original = value
        value = value[: int(max_length)]
        notes.append("value_truncated")
        finding = _truncation_finding(key, original, int(max_length))

    doc = docs_by_file.get(src.get("file_id", ""))
    page = src.get("page")
    page_ref = str(page) if page is not None else "-"
    pages = cross_page_span(doc, span) if doc else None
    if pages:
        notes.append("merged_across_pages")
        trail.append(
            {
                "op": "transform",
                "before": span,
                "after": value,
                "ref": f"{src.get('file_id')}/{'-'.join(str(p) for p in pages)}/{span}",
                "detail": {"key": key, "cross_page": True, "pages": pages},
            }
        )

    locatable = span_locatable(src, [doc] if doc else [])
    status = classify(value, locatable, notes)
    source = None
    if locatable:
        source = {
            "file_id": src.get("file_id", ""),
            "page": src.get("page"),
            "bbox": src.get("bbox"),
            "span": span,
            "form_label": src.get("form_label"),
        }

    trail.append(
        {
            "op": "transform",
            "before": span or raw_value,
            "after": value,
            "ref": f"{src.get('file_id')}/{page_ref}/{span}",
            "detail": {"key": key, "notes": notes, "status": status},
        }
    )

    field_value: FieldValue = {
        "key": key,
        "value": value,
        "status": status,  # type: ignore[typeddict-item]
        "confirmed": False,
        "edited_by_user": False,
        "source": source,  # type: ignore[typeddict-item]
        "normalized_from": raw_value or None,
        "label": candidate.get("label") or (fdef or {}).get("label"),
        "doc_type": candidate.get("doc_type"),
        "notes": notes,
        # `confidence` stops here: the contract has no such field (tasks 4.8)
    }
    return field_value, trail, finding


def _pick_candidates(candidates: list[dict]) -> tuple[dict[str, dict], list[tuple[str, dict]]]:
    """Keep only the highest-`confidence` candidate per key.

    `confidence` is used for ranking in this stage only and **never** reaches `FieldValue`
    (the contract has no such field).
    A discarded candidate must not vanish silently: each one gets `op="pass"` + a reason
    (spec: scope-based skipping is not overreach).
    """
    picked: dict[str, dict] = {}
    dropped: list[tuple[str, dict]] = []
    for candidate in candidates:
        key = candidate.get("key")
        if not key:
            continue
        current = picked.get(key)
        if current is None:
            picked[key] = candidate
            continue
        if float(candidate.get("confidence") or 0) > float(current.get("confidence") or 0):
            dropped.append((key, current))
            picked[key] = candidate
        else:
            dropped.append((key, candidate))
    return picked, dropped


def _missing_placeholder(key: str, fdef: dict) -> FieldValue:
    """Placeholder for a `required` field with no candidate (design §7.4)."""
    return {
        "key": key,
        "value": None,
        "status": "missing",
        "confirmed": False,
        "edited_by_user": False,
        "source": None,
        "normalized_from": None,
        "label": fdef.get("label"),
        "doc_type": None,
        "notes": ["not_in_source"],
    }


def build_fields(
    candidates: list[dict],
    docs: list[dict],
    *,
    fields_yaml: dict[str, dict],
) -> NormalizeResult:
    """Candidates -> `fields` / `extra_fields` / Finding drafts / trail receipts.

    - Only `stage=normalize` constraints are executed; `required` is **read** (to decide whether a
      placeholder is needed) and never used to decide blocking
    - Fields outside the dictionary go to `extra_fields` only, **never** mixed into `fields`
    - A `required` field without candidates must get a `missing` placeholder, otherwise `missing`
      is a dead enum value
    """
    docs_by_file = {d["file_id"]: d for d in docs or []}
    fields_out: dict[str, FieldValue] = {}
    extra_out: dict[str, FieldValue] = {}
    trail: list[dict] = []
    findings: list[dict] = []

    picked, dropped = _pick_candidates(candidates or [])
    for key, candidate in dropped:
        src = candidate.get("_source") or {}
        trail.append(
            {
                "op": "pass",
                "before": str(candidate.get("raw_value") or ""),
                "after": None,
                "ref": f"{src.get('file_id')}/-/{src.get('span')}",
                "detail": {
                    "key": key,
                    "reason": "duplicate_candidate_lower_confidence",
                    "confidence": candidate.get("confidence"),
                },
            }
        )

    for key, candidate in picked.items():
        fdef = fields_yaml.get(key)
        field_value, entries, finding = _build_field(key, candidate, fdef, docs_by_file)
        if fdef is None:
            extra_out[key] = field_value
        else:
            fields_out[key] = field_value
        trail.extend(entries)
        if finding:
            findings.append(finding)

    # required field without candidates -> placeholder; optional fields are not padded
    # (placeholders would flood the review console)
    for key, fdef in fields_yaml.items():
        if key in fields_out or not fdef.get("required"):
            continue
        fields_out[key] = _missing_placeholder(key, fdef)
        trail.append(
            {
                "op": "pass",
                "before": None,
                "after": None,
                "ref": None,
                "detail": {"key": key, "reason": "field not present in source"},
            }
        )

    decision = decide_business_type(docs or [])
    trail.append(decision.trail_entry)

    return NormalizeResult(
        fields=fields_out,
        extra_fields=extra_out,
        business_type=decision.business_type,
        findings=findings,
        trail_entries=trail,
    )


# --------------------------------------------------------------------------
# §7.6 business_type detection (single writer = normalize)
# --------------------------------------------------------------------------

STRONG_INDICATORS = ("URDG 758", "URDG758", "独立保函", "见索即付", "BANK GUARANTEE")
GENERAL_KEYWORDS = ("保函", "GUARANTEE")
OTHER_TYPE_KEYWORDS = ("INVOICE", "发票", "CONTRACT", "合同", "BILL OF LADING", "提单")


@dataclass(frozen=True)
class BusinessTypeDecision:
    """Decision result + evidence + the mandatory `pass` trail entry (design §7.6)."""

    business_type: str  # "guarantee" / "unsupported"
    reason: str
    evidence: str | None = None
    file_id: str | None = None

    @property
    def trail_entry(self) -> dict:
        return {
            "op": "pass",
            "before": self.evidence,
            "after": self.business_type,
            "ref": self.file_id,
            "detail": {
                "business_type": self.business_type,
                "evidence": self.evidence,
                "file_id": self.file_id,
                "reason": self.reason,
            },
        }


def _find_keyword(docs: list[dict], keywords: tuple[str, ...]) -> tuple[str, str] | None:
    """Return `(evidence <= 80 chars, file_id)`.

    Keyword matching uses `re.IGNORECASE` and leaves `normalize_ws` untouched (that is the
    location benchmark and MUST NOT fold case). `normalize_ws` is used only to squeeze the
    evidence fragment onto one line for display.
    """
    for doc in docs:
        text = doc.get("full_text") or ""
        for keyword in keywords:
            hit = re.search(re.escape(keyword), text, re.IGNORECASE)
            if not hit:
                continue
            start = max(0, hit.start() - 20)
            end = min(len(text), hit.end() + 20)
            return normalize_ws(text[start:end]), doc.get("file_id")
    return None


def decide_business_type(docs: list[dict]) -> BusinessTypeDecision:
    """Four-step decision table, executed in order, first hit wins (design §7.6).

    The `unsupported` outcome of step 4 is a **correct result**, not a failure: when the type is
    uncertain downstream should take the "business type uncertain" branch, and we MUST NOT invent a
    type just to keep the pipeline running.
    A step-1 hit is never overridden by step 2/3 (a contract mentioning the guarantee keyword is
    normal and belongs to the same business).
    """
    hit = _find_keyword(docs, STRONG_INDICATORS)
    if hit:
        return BusinessTypeDecision("guarantee", "explicit_independence_clause", *hit)

    hit = _find_keyword(docs, GENERAL_KEYWORDS)
    if hit:
        return BusinessTypeDecision("guarantee", "explicit_keyword", *hit)

    hit = _find_keyword(docs, OTHER_TYPE_KEYWORDS)
    if hit:
        # Distinguish "type not supported" from "no evidence": here there is evidence, but the type
        # is outside the POC's supported range
        return BusinessTypeDecision("unsupported", "business_type_not_supported", *hit)

    return BusinessTypeDecision("unsupported", "no_evidence")


def detect_business_type(docs: list[dict]) -> str:
    """Contract signature (`poc-skeleton/design.md` §6): answers the type only.

    Use `decide_business_type()` when evidence and a trail entry are needed — the contract
    signature cannot return `evidence`, while the spec requires a `pass` entry on every branch.
    """
    return decide_business_type(docs).business_type