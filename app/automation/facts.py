"""Deterministic protected-fact checks for automation proposals.

No model is involved: amounts, currencies, dates, percentages, identifiers, legal references,
negation/obligation terms and proper-noun sequences are extracted with conservative rules. A change
in any of them becomes a risk flag; polish/clarify cannot silently change facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

FactKind = Literal[
    "amount",
    "currency",
    "percentage",
    "date",
    "identifier",
    "legal_reference",
    "negation",
    "obligation",
    "party",
]

_CURRENCY = r"(?:USD|EUR|GBP|CNY|RMB|SGD|HKD|JPY|AUD|CAD|CHF)"
_AMOUNT = re.compile(rf"(?P<currency>{_CURRENCY})\s?(?P<number>\d[\d,]*\.\d{{2}})", re.IGNORECASE)
_AMOUNT_REVERSED = re.compile(rf"(?P<number>\d[\d,]*\.\d{{2}})\s?(?P<currency>{_CURRENCY})", re.IGNORECASE)
_PERCENT = re.compile(r"\d+(?:\.\d+)?%")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b")
_IDENTIFIER = re.compile(r"\b[A-Z]{2,}-\d{2,}\b")
_LEGAL = re.compile(r"\b(?:URDG|UCP|ISP|ISBP)\s?\d+\b", re.IGNORECASE)
_PROPER = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,}\b")
_NEGATION = ("not", "no", "never", "neither", "不得", "不得为", "不", "无", "禁止")
_OBLIGATION = ("shall", "must", "may not", "required", "obligation", "必须", "应当", "应", "可以", "无权")
_STOP_PROPER = {"The", "This", "That", "These", "Those", "Amount", "Guarantee"}


@dataclass(frozen=True)
class FactToken:
    kind: FactKind
    value: str


def _decimal(value: str) -> str:
    try:
        return format(Decimal(value.replace(",", "")), "f")
    except (InvalidOperation, ValueError):
        return value.replace(",", "")


def extract_facts(text: str) -> frozenset[FactToken]:
    tokens: set[FactToken] = set()
    for pattern in (_AMOUNT, _AMOUNT_REVERSED):
        for match in pattern.finditer(text):
            tokens.add(FactToken("amount", _decimal(match.group("number"))))
            tokens.add(FactToken("currency", match.group("currency").upper()))
    for match in _PERCENT.finditer(text):
        tokens.add(FactToken("percentage", match.group(0)))
    for match in _DATE.finditer(text):
        tokens.add(FactToken("date", match.group(0)))
    for match in _IDENTIFIER.finditer(text):
        tokens.add(FactToken("identifier", match.group(0)))
    for match in _LEGAL.finditer(text):
        tokens.add(FactToken("legal_reference", match.group(0).upper().replace(" ", "")))
    lowered = text.casefold()
    for term in _NEGATION:
        if term.casefold() in lowered:
            tokens.add(FactToken("negation", term.casefold()))
    for term in _OBLIGATION:
        if term.casefold() in lowered:
            tokens.add(FactToken("obligation", term.casefold()))
    for match in _PROPER.finditer(text):
        value = match.group(0)
        if value.split()[0] not in _STOP_PROPER:
            tokens.add(FactToken("party", value))
    return frozenset(tokens)


@dataclass(frozen=True)
class FactAssessment:
    changed: bool
    risk_flags: tuple[str, ...]
    requires_clarification: bool


def assess_facts(before: str, after: str, *, intent: str = "replace_text") -> FactAssessment:
    before_tokens = extract_facts(before)
    after_tokens = extract_facts(after)
    if before_tokens == after_tokens:
        return FactAssessment(False, (), False)

    changed_kinds = {token.kind for token in before_tokens.symmetric_difference(after_tokens)}
    mapping = {
        "amount": "changed_amount",
        "currency": "changed_currency",
        "percentage": "changed_percentage",
        "date": "changed_date",
        "identifier": "changed_identifier",
        "legal_reference": "changed_legal_reference",
        "negation": "changed_negation",
        "obligation": "changed_obligation",
        "party": "changed_party",
    }
    flags = [mapping[kind] for kind in sorted(changed_kinds)]
    requires_clarification = intent in ("polish", "clarify")
    if not requires_clarification:
        flags.insert(0, "substantive_change")
    return FactAssessment(True, tuple(flags), requires_clarification)


__all__ = ["FactAssessment", "FactToken", "assess_facts", "extract_facts"]