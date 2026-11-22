"""Best-effort redaction before the document text leaves the service.

This is the *simplified* policy the demo asks for: a fixed, documented set of financial-identifier
patterns is masked before the Doubao call, and the report lists what was masked (kind + count + a
masked sample), so a reviewer can see the step without ever seeing the original value.

It is deliberately not a compliance control:

- it does not touch names, amounts, addresses or free text (the model needs those to judge);
- it cannot catch every identifier shape;
- the authoritative control remains the egress policy (`EgressPolicy`) and the approved-processor
  gate, which run independently of this module.

Masking keeps the block index and the surrounding text intact, so a quote the model returns can
still be located in the redacted view (reports say so).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

ENV_MODE = "SMART_EDIT_CONFORMANCE_REDACT"
MODE_BASIC = "basic"
MODE_OFF = "off"

REDACTED = "[redacted]"

NOTE_BASIC = (
    "Best-effort pattern redaction: account/card numbers, IBAN/BIC, e-mail, phone and ID numbers "
    "are masked before the model call. Names, amounts and addresses still leave the service; the "
    "egress policy and the approved-processor gate remain the authoritative controls."
)
NOTE_OFF = (
    "Redaction is off (SMART_EDIT_CONFORMANCE_REDACT=off): the document text leaves the service "
    "unchanged. Enable it before using a non-demo deployment."
)


@dataclass(frozen=True)
class RedactionStep:
    kind: str
    count: int
    sample: str


@dataclass(frozen=True)
class RedactionOutcome:
    blocks: list[dict] = field(default_factory=list)
    applied: bool = False
    total: int = 0
    steps: tuple[RedactionStep, ...] = ()
    note: str = ""


def mode_from_env() -> str:
    raw = (os.environ.get(ENV_MODE) or "").strip().lower()
    return MODE_OFF if raw == MODE_OFF else MODE_BASIC


def _mask_digits(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 6:
        return "•" * len(digits)
    return f"{digits[:2]}{'•' * (len(digits) - 6)}{digits[-4:]}"


def _mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    head = local[:1] if local else ""
    return f"{head}{'•••'}@{domain}" if domain else "•••"


def _mask_keep_ends(value: str, head: int = 2, tail: int = 2) -> str:
    compact = re.sub(r"\s", "", value)
    if len(compact) <= head + tail:
        return "•" * len(compact)
    return f"{compact[:head]}{'•' * (len(compact) - head - tail)}{compact[-tail:]}"


# Ordered: the narrower identifier shapes run before the generic long-digit run, otherwise a
# 16-digit card would be reported as an "account" and the masking sample would be less useful.
_PATTERNS: tuple[tuple[str, re.Pattern[str], object], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), _mask_email),
    (
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9][ ]?){11,30}\b"),
        lambda value: _mask_keep_ends(value, 4, 2),
    ),
    (
        "bic",
        re.compile(r"\b(?=[A-Z]{6}[A-Z0-9]{2,5}\b)(?=[A-Z0-9]*\d)[A-Z]{6}[A-Z0-9]{2,5}\b"),
        lambda value: _mask_keep_ends(value, 2, 2),
    ),
    ("id_number", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), _mask_digits),
    (
        "card",
        re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
        lambda value: _mask_digits(value),
    ),
    (
        "account_or_phone",
        re.compile(r"(?<![\d-])\+?\d[\d -]{7,}\d(?![\d-])"),
        _mask_digits,
    ),
)


def _redact_text(text: str) -> tuple[str, list[RedactionStep]]:
    """Mask one text; returns the masked text and one step per kind that matched."""
    steps: list[RedactionStep] = []
    outbound = text
    for kind, pattern, mask in _PATTERNS:
        count = 0
        sample: str | None = None

        def _replace(match: re.Match[str], *, _mask=mask) -> str:
            nonlocal count, sample
            count += 1
            if sample is None:
                sample = _mask(match.group(0))  # type: ignore[operator]
            return REDACTED

        outbound = pattern.sub(_replace, outbound)
        if count:
            steps.append(RedactionStep(kind=kind, count=count, sample=sample or REDACTED))
    return outbound, steps


def redact_blocks(blocks: list[dict], *, mode: str | None = None) -> RedactionOutcome:
    """Redact the model payload, never the stored draft.

    `blocks` items keep any extra keys (e.g. `page`); only `text` is replaced.
    """
    resolved = (mode or mode_from_env()).strip().lower()
    if resolved == MODE_OFF:
        return RedactionOutcome(
            blocks=[dict(block) for block in blocks], applied=False, total=0, note=NOTE_OFF
        )

    outbound: list[dict] = []
    totals: dict[str, RedactionStep] = {}
    for block in blocks:
        text = str(block.get("text") or "")
        masked, steps = _redact_text(text)
        for step in steps:
            existing = totals.get(step.kind)
            if existing is None:
                totals[step.kind] = step
            else:
                totals[step.kind] = RedactionStep(
                    kind=step.kind, count=existing.count + step.count, sample=existing.sample
                )
        outbound.append({**block, "text": masked})

    ordered = tuple(totals[kind] for kind, _pattern, _mask in _PATTERNS if kind in totals)
    total = sum(step.count for step in ordered)
    return RedactionOutcome(
        blocks=outbound,
        applied=total > 0,
        total=total,
        steps=ordered,
        note=NOTE_BASIC,
    )


__all__ = [
    "ENV_MODE",
    "MODE_BASIC",
    "MODE_OFF",
    "NOTE_BASIC",
    "NOTE_OFF",
    "REDACTED",
    "RedactionOutcome",
    "RedactionStep",
    "mode_from_env",
    "redact_blocks",
]