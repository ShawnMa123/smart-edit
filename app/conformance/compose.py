"""Doubao composition for the template-conformance audit.

Two rules keep the model from inventing a verdict:

1. It may only return requirement ids that the config declared; anything else is dropped.
2. A `finding` must carry a verbatim quote that the server can locate in the (redacted) document.
   A finding whose quote is missing or not locatable is downgraded to `unable_to_assess` — it never
   reaches the panel as a defect of the customer's document.

Severity and the gate come from the config's `level`, never from the model: `must` is at most
`Warning` / `human_review`, everything else is `Info` / `advisory`. Nothing here can hard-block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.conformance.config import ConformanceConfig

PROMPT_VERSION = "conformance/1"

SYSTEM_PROMPT = """You audit one trade-finance document against a fixed desk checklist.

You receive `requirements` (the checklist), `document.blocks` (the document as numbered blocks) and
`known_fields` (values a deterministic extractor already found). Judge each requirement against the
document alone.

Answer with JSON only:
{"summary": "two or three sentences about what the document does and does not contain",
 "results": [{"id": "requirement id",
              "status": "pass | finding | unable_to_assess",
              "explanation": "why, in the document's language",
              "suggestion": "a concrete edit, or empty for pass",
              "quote": "the exact substring of one block that proves this",
              "block_index": 12,
              "confidence": "high | medium | low"}],
 "notes": ["anything you could not judge, and why"]}

Hard requirements:
- Answer every requirement id in `requirements`. Never invent an id.
- `quote` must be copied verbatim from one block. Never paraphrase, translate or join blocks.
- A `finding` without a verbatim quote is invalid. If you cannot quote it, use `unable_to_assess`.
- Never output a severity or a gate; the caller owns both.
- `[redacted]` marks a value removed before this request. It is not a missing field, a placeholder
  or a drafting defect: do not flag it, and do not guess the original value.
- Required-field presence is checked separately. Do not report a requirement as `finding` only
  because a field is absent; describe the clause or wording the document actually contains.
- If the requirement is not addressed anywhere in the document, say `unable_to_assess` and explain
  what is missing in your own words. Absence cannot be quoted.
- When `document.chunk_count` is greater than 1 you are looking at ONE chunk of a longer document.
  A requirement that is simply not visible in this chunk must be `unable_to_assess`, never
  `finding`: another chunk may contain it.
- Never claim the document is compliant, approved or risk-free. `pass` means "this requirement is
  met by the quoted text", nothing more.
- Write `summary`, `explanation` and `suggestion` in the language of the document.
"""

_ALLOWED_STATUS = ("pass", "finding", "unable_to_assess")
_STATUS_ALIASES = {
    "pass": "pass",
    "ok": "pass",
    "met": "pass",
    "finding": "finding",
    "fail": "finding",
    "failed": "finding",
    "missing": "finding",
    "unable_to_assess": "unable_to_assess",
    "unable": "unable_to_assess",
    "unknown": "unable_to_assess",
}
_CONFIDENCE = ("high", "medium", "low")


class ComposeError(RuntimeError):
    """The composer could not produce a validated answer; callers map it to a report limitation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ComposedResult:
    id: str
    status: str
    explanation: str
    suggestion: str | None = None
    quote: str | None = None
    block_index: int | None = None
    confidence: str = "medium"
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Composition:
    summary: str
    results: tuple[ComposedResult, ...]
    notes: tuple[str, ...]
    model: str | None
    calls: int


def _text(value: Any, limit: int = 1200) -> str:
    return str(value or "").strip()[:limit]


def locate_quote(quote: str, blocks: list[dict]) -> int | None:
    """Block index whose text contains `quote`, tolerating whitespace differences only."""
    parts = quote.split()
    if not parts:
        return None
    pattern = re.compile(r"\s+".join(re.escape(part) for part in parts), re.IGNORECASE)
    for block in blocks:
        if pattern.search(str(block.get("text") or "")):
            try:
                return int(block.get("i"))
            except (TypeError, ValueError):
                return None
    return None


class ConformanceComposer:
    """Thin wrapper around the approved Doubao gateway; validation lives here, not in the model."""

    def __init__(
        self,
        gateway: Any,
        *,
        approved: bool,
        timeout: float = 60.0,
        model_label: str | None = None,
    ) -> None:
        self.gateway = gateway
        self.approved = bool(approved)
        self.timeout = float(timeout)
        self.model_label = model_label

    @property
    def available(self) -> bool:
        return bool(self.approved and callable(getattr(self.gateway, "compose_json", None)))

    def label(self) -> str | None:
        if self.model_label:
            return self.model_label
        label = getattr(self.gateway, "label", None)
        return str(label) if label else None

    def review(
        self,
        *,
        config: ConformanceConfig,
        blocks: list[dict],
        known_fields: dict[str, Any],
        language: str,
        document: dict[str, Any],
    ) -> Composition:
        if not self.available:
            raise ComposeError("composer_unavailable")
        requirements = [item.prompt_payload() for item in config.requirements]
        if not requirements:
            # Nothing for the model to judge; the deterministic layer alone forms the report.
            return Composition(
                summary="",
                results=(),
                notes=("This config declares no model requirement.",),
                model=self.label(),
                calls=0,
            )
        payload = {
            "config": {
                "config_id": config.config_id,
                "version": config.version,
                "name": config.name,
                "language": language,
            },
            "requirements": requirements,
            "document": {
                "blocks": blocks,
                "block_count": len(blocks),
                "truncated": bool(document.get("truncated")),
                "chunk_index": document.get("chunk_index"),
                "chunk_count": document.get("chunk_count"),
            },
            "known_fields": known_fields,
            "constraints": {
                "allowed_status": list(_ALLOWED_STATUS),
                "require_verbatim_quote": True,
                "max_findings": config.generation.max_findings,
                "language": language,
            },
        }
        try:
            raw = self.gateway.compose_json(SYSTEM_PROMPT, payload, timeout=self.timeout)
        except ComposeError:
            raise
        except Exception as exc:  # noqa: BLE001 - the gateway owns its error codes
            code = str(getattr(exc, "code", "") or "model_error")
            raise ComposeError(code) from exc
        return self._validate(raw, config, blocks)

    def _validate(self, raw: Any, config: ConformanceConfig, blocks: list[dict]) -> Composition:
        if not isinstance(raw, dict):
            raise ComposeError("composer_invalid")
        items = raw.get("results")
        if not isinstance(items, list):
            items = raw.get("requirements")
        if not isinstance(items, list):
            raise ComposeError("composer_invalid")

        summary = _text(raw.get("summary"), config.generation.summary_max_chars)
        notes = tuple(_text(item, 400) for item in (raw.get("notes") or []) if _text(item, 400))

        by_id: dict[str, dict] = {}
        for item in items:
            if isinstance(item, dict):
                requirement_id = _text(item.get("id"), 80)
                if requirement_id and requirement_id not in by_id:
                    by_id[requirement_id] = item

        results: list[ComposedResult] = []
        findings = 0
        for requirement in config.requirements:
            item = by_id.get(requirement.id)
            if item is None:
                results.append(
                    ComposedResult(
                        id=requirement.id,
                        status="unable_to_assess",
                        explanation="The model did not answer this requirement.",
                        reason_codes=("model_omitted",),
                        confidence="low",
                    )
                )
                continue

            raw_status = _text(item.get("status"), 40).lower()
            status = _STATUS_ALIASES.get(raw_status, "unable_to_assess")
            reason_codes: list[str] = []
            if raw_status == "missing":
                reason_codes.append("missing_in_document")
            explanation = _text(item.get("explanation"))
            suggestion = _text(item.get("suggestion"), 600) or None
            confidence = _text(item.get("confidence"), 20).lower()
            if confidence not in _CONFIDENCE:
                confidence = "medium"
            quote = _text(item.get("quote"), config.generation.max_quote_chars) or None

            block_index = locate_quote(quote, blocks) if quote else None
            if block_index is None and isinstance(item.get("block_index"), int):
                candidate = int(item["block_index"])
                if any(int(block.get("i", -1)) == candidate for block in blocks):
                    block_index = candidate

            if status == "finding":
                if not quote:
                    status = "unable_to_assess"
                    reason_codes.append("no_quote")
                elif block_index is None:
                    status = "unable_to_assess"
                    reason_codes.append("evidence_not_locatable")
                elif findings >= config.generation.max_findings:
                    status = "unable_to_assess"
                    reason_codes.append("finding_limit_reached")
                else:
                    findings += 1
            elif status == "pass" and quote and block_index is None:
                # A quote is optional for a pass, but keep it only when it is real.
                quote = None

            if not explanation:
                explanation = "The model returned no explanation for this requirement."

            results.append(
                ComposedResult(
                    id=requirement.id,
                    status=status,
                    explanation=explanation,
                    suggestion=suggestion,
                    quote=quote,
                    block_index=block_index,
                    confidence=confidence,
                    reason_codes=tuple(reason_codes),
                )
            )

        return Composition(
            summary=summary,
            results=tuple(results),
            notes=notes,
            model=self.label(),
            calls=1,
        )


def merge_compositions(compositions: list[Composition]) -> Composition:
    """Merge per-chunk answers: a finding anywhere wins, then a pass, then unable to assess.

    A chunk can only see its own text, so "finding" is evidence and travels with its quote; a
    "pass" is accepted only when no chunk found a defect. Requirements absent from every chunk stay
    `unable_to_assess`.
    """
    if not compositions:
        raise ComposeError("composer_invalid")
    if len(compositions) == 1:
        return compositions[0]

    ordered_ids: list[str] = []
    by_id: dict[str, list[ComposedResult]] = {}
    for composition in compositions:
        for result in composition.results:
            if result.id not in by_id:
                by_id[result.id] = []
                ordered_ids.append(result.id)
            by_id[result.id].append(result)

    merged: list[ComposedResult] = []
    for requirement_id in ordered_ids:
        items = by_id[requirement_id]
        findings = [item for item in items if item.status == "finding"]
        passes = [item for item in items if item.status == "pass"]
        if findings:
            chosen = findings[0]
            reasons = tuple(dict.fromkeys(code for item in findings for code in item.reason_codes))
            merged.append(
                ComposedResult(
                    id=requirement_id,
                    status="finding",
                    explanation=chosen.explanation,
                    suggestion=next((i.suggestion for i in findings if i.suggestion), None),
                    quote=chosen.quote,
                    block_index=chosen.block_index,
                    confidence=chosen.confidence,
                    reason_codes=reasons,
                )
            )
        elif passes:
            chosen = passes[0]
            merged.append(
                ComposedResult(
                    id=requirement_id,
                    status="pass",
                    explanation=chosen.explanation,
                    suggestion=None,
                    quote=chosen.quote,
                    block_index=chosen.block_index,
                    confidence=chosen.confidence,
                    reason_codes=(),
                )
            )
        else:
            chosen = items[0]
            reasons = tuple(
                dict.fromkeys(
                    code
                    for item in items
                    for code in (item.reason_codes or ("not_visible_in_any_chunk",))
                )
            )
            merged.append(
                ComposedResult(
                    id=requirement_id,
                    status="unable_to_assess",
                    explanation=chosen.explanation,
                    suggestion=None,
                    quote=None,
                    block_index=None,
                    confidence="low",
                    reason_codes=reasons,
                )
            )

    summary = next((item.summary for item in compositions if item.summary), "")
    notes: list[str] = []
    for composition in compositions:
        for note in composition.notes:
            if note not in notes:
                notes.append(note)
    return Composition(
        summary=summary,
        results=tuple(merged),
        notes=tuple(notes[:10]),
        model=compositions[0].model,
        calls=sum(item.calls for item in compositions),
    )


__all__ = [
    "ComposeError",
    "ComposedResult",
    "Composition",
    "ConformanceComposer",
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "locate_quote",
    "merge_compositions",
]