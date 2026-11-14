"""Deterministic text helpers shared by the query analyzer and the lexical retriever."""

from __future__ import annotations

import re
import unicodedata

RULE_RE = re.compile(r"\b(?:URDG|UCP|ISP|ISBP)\s*\d+\b", re.IGNORECASE)
AMOUNT_RE = re.compile(r"\b(?:USD|EUR|GBP|CNY|RMB)\s*[\d,]+(?:\.\d+)?\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9._/-]*")
_STOP = {
    "the", "a", "an", "of", "to", "and", "or", "is", "are", "was", "were", "be", "been",
    "what", "which", "who", "how", "why", "when", "where", "does", "do", "did", "can",
    "could", "should", "would", "please", "tell", "me", "about", "for", "in", "on", "at",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).strip()


def tokens(text: str) -> list[str]:
    normalized = normalize(text).lower()
    result: list[str] = []
    for match in _WORD_RE.finditer(normalized):
        token = match.group(0)
        if len(token) >= 2 and token not in _STOP:
            result.append(token)
    for match in _CJK_RE.finditer(normalized):
        chars = match.group(0)
        for size in (2, 3):
            for index in range(max(0, len(chars) - size + 1)):
                pair = chars[index : index + size]
                if pair not in _STOP:
                    result.append(pair)
    # Keep rule codes as a single token too (URDG 758 -> urdg 758 + urdg, 758).
    for match in RULE_RE.finditer(normalized):
        result.append(re.sub(r"\s+", "", match.group(0).lower()))
    return list(dict.fromkeys(result))


def entities(text: str) -> list[str]:
    values = [match.group(0) for match in RULE_RE.finditer(text or "")]
    values += [match.group(0) for match in AMOUNT_RE.finditer(text or "")]
    values += [match.group(0) for match in DATE_RE.finditer(text or "")]
    return list(dict.fromkeys(values))


def supports_entities(claim: str, evidence: str) -> bool:
    evidence_normalized = normalize(evidence).lower()
    return all(value.lower() in evidence_normalized for value in entities(claim))