"""Evidence-bound composition for a document risk scan (`legal-document-risk-scan` D3/D4).

Two rules keep the model from inventing a legal opinion:

1. It may only cite evidence ids that were actually retrieved; unknown ids are dropped here.
2. It may not raise severity or the gate: a composed finding is at most `Warning` /
   `human_review`. `Critical` / `hard_block` belong to the deterministic checks, which do not
   depend on a model at all.

The web leg is a separate, user-chosen call. Its citations are always marked unverified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

SYSTEM_PROMPT = """You are a trade-finance document reviewer. You receive one clause of a draft,
the deterministic rule hits for that clause, and statute evidence retrieved for it.

Answer with JSON only:
{"findings": [{
  "rule_id": "one of rules[].rule_id, or LEGAL-RISK-NEW",
  "title": "short risk name (same language as the clause)",
  "explanation": "why this clause is risky, citing only the given evidence",
  "suggestion": "a concrete edit",
  "evidence_ids": ["E1"],
  "support_level": "strong | qualified | insufficient",
  "quote": "the exact risky substring, copied from clause_text, or empty"
}], "no_finding_reason": "why nothing was flagged"}

Hard requirements:
- Only cite ids from `evidence`. An unsupported claim must say support_level=insufficient and
  cite nothing.
- `quote` must be copied verbatim from clause_text. Never paraphrase it.
- In `explanation`, name the source by its `article_label`/`title` (e.g. “第三条”), never by its
  evidence id: ids are internal bookkeeping.
- `[redacted]` marks a value removed before this request. Do not treat it as a missing field, a
  placeholder, or a drafting defect: presence of amounts, accounts and names is checked separately.
- Also look for substantive compliance red flags, not just drafting gaps: sanctions/embargoed
  destinations and state entities; export-controlled or military items with no licence,
  classification or end user; circumvention wording (third-country routing, split payments, cash,
  opaque end user); bribery or facilitation payments; money-laundering indicators. When relevant,
  name the regime to check (EAR/ITAR, OFAC, EU/UN measures) without pretending to decide it.
- If the evidence does not decide the question, return no finding and explain why in
  `no_finding_reason`. Do not guess, and do not call the clause compliant.
- Never output a severity; the caller owns severity and the gate.
"""

WEB_PROMPT = """You check whether a trade-finance clause conflicts with currently published rules.
Search the web, answer in one short paragraph, and cite the pages you used. If you cannot find a
reliable source, say so plainly. Never invent a citation."""

_SUPPORT = ("strong", "qualified", "insufficient")
MAX_FINDINGS = 6
MAX_QUOTE_CHARS = 400


class ComposeError(RuntimeError):
    """The composer could not produce validated findings; callers map it to a check status."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ComposedFinding:
    rule_id: str
    title: str
    explanation: str
    suggestion: str | None
    evidence_ids: tuple[str, ...]
    severity: str
    gate_type: str
    support_level: str
    quote_start: int | None = None
    quote_end: int | None = None


@dataclass(frozen=True)
class WebEvidence:
    title: str
    url: str
    excerpt: str = ""


@dataclass(frozen=True)
class WebCheck:
    attempted: bool
    usable: tuple[WebEvidence, ...] = ()
    note: str | None = None


def _text(value: object, limit: int = 1200) -> str:
    return str(value or "").strip()[:limit]


def _flexible_find(quote: str, text: str) -> re.Match[str] | None:
    """Locate a quote in the clause, tolerating whitespace differences (never paraphrase)."""
    parts = quote.split()
    if not parts:
        return None
    pattern = r"\s+".join(re.escape(part) for part in parts)
    return re.search(pattern, text, re.IGNORECASE)


class LegalComposer:
    def __init__(
        self,
        gateway,
        *,
        approved: bool,
        timeout: float = 45.0,
        max_evidence: int = 5,
        redact: Callable[[str], tuple[str, tuple[str, ...]] | None] | None = None,
    ) -> None:
        self.gateway = gateway
        self.approved = bool(approved)
        self.timeout = float(timeout)
        self.max_evidence = max(1, int(max_evidence))
        # Applied to the clause before it leaves the service; `None` means the policy failed.
        self.redact = redact

    @property
    def available(self) -> bool:
        return bool(self.approved and callable(getattr(self.gateway, "compose_json", None)))

    def review_clause(
        self,
        *,
        clause_id: str,
        clause_text: str,
        rules: list[dict],
        evidence: list[dict],
        language: str = "zh-CN",
    ) -> list[ComposedFinding]:
        if not self.available:
            raise ComposeError("composer_unavailable")
        evidence = evidence[: self.max_evidence]
        known_evidence = {str(item["id"]) for item in evidence}
        catalogue = {str(item["rule_id"]): item for item in rules}
        outbound = clause_text
        if self.redact is not None:
            cleaned = self.redact(clause_text)
            if cleaned is None:
                # A policy failure must stop the call, not silently send the raw clause.
                raise ComposeError("redaction_unavailable")
            outbound = cleaned[0]
        payload = {
            "clause_id": clause_id,
            "language": language,
            "clause_text": outbound[:1200],
            "rules": rules,
            "evidence": evidence,
            "evidence_rule": (
                "Only cite ids from `evidence`. An empty list means no statute evidence was found."
            ),
        }
        raw = self.gateway.compose_json(SYSTEM_PROMPT, payload, timeout=self.timeout)
        return self._validate(raw, clause_text, known_evidence, catalogue)

    def web_check(
        self, question: str, *, language: str = "zh-CN", max_keyword: int = 3
    ) -> WebCheck:
        general_web = getattr(self.gateway, "general_web", None)
        if not callable(general_web):
            raise ComposeError("web_search_unavailable")
        result = general_web(question, max_keyword=max(1, int(max_keyword)), language=language)
        usable: list[WebEvidence] = []
        seen: set[str] = set()
        for citation in getattr(result.answer, "citations", []) or []:
            locator = dict(getattr(citation, "locator", None) or {})
            url = str(locator.get("url") or "")
            if not url.startswith(("http://", "https://")):
                # A citation without a resolvable link is not evidence (same rule as the assistant).
                continue
            if url in seen:
                # Providers often cite the same page several times; keep one card per URL.
                continue
            seen.add(url)
            usable.append(
                WebEvidence(
                    title=str(getattr(citation, "title", "") or url)[:200],
                    url=url,
                )
            )
        notes = list(getattr(result.answer, "limitations", []) or [])
        note = "; ".join(str(item) for item in notes) if notes else None
        if not usable and note is None:
            note = "The web search returned no citable link."
        return WebCheck(attempted=True, usable=tuple(usable), note=note)

    def _validate(
        self,
        raw: dict,
        clause_text: str,
        known_evidence: set[str],
        catalogue: dict[str, dict],
    ) -> list[ComposedFinding]:
        items = raw.get("findings") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise ComposeError("composer_invalid")
        findings: list[ComposedFinding] = []
        for item in items[:MAX_FINDINGS]:
            if not isinstance(item, dict):
                continue
            rule_id = _text(item.get("rule_id"), 80)
            spec = catalogue.get(rule_id)
            if rule_id != "LEGAL-RISK-NEW" and spec is None:
                continue  # an invented rule id is not evidence of anything
            explanation = _text(item.get("explanation"))
            if not explanation:
                continue
            cited = tuple(
                dict.fromkeys(
                    str(value)
                    for value in (item.get("evidence_ids") or [])
                    if str(value) in known_evidence
                )
            )
            support = _text(item.get("support_level"), 20).lower()
            if support not in _SUPPORT or not cited:
                support = "insufficient"
            severity = str((spec or {}).get("severity") or "Warning")
            if severity not in ("Warning", "Info"):
                severity = "Warning"  # the composer never escalates to Critical
            gate = str((spec or {}).get("gate_type") or "human_review")
            if gate not in ("advisory", "human_review"):
                gate = "human_review"  # the composer never hard-blocks
            quote = _text(item.get("quote"), MAX_QUOTE_CHARS)
            match = _flexible_find(quote, clause_text) if quote else None
            findings.append(
                ComposedFinding(
                    rule_id=rule_id or "LEGAL-RISK-NEW",
                    title=_text(item.get("title"), 160)
                    or str((spec or {}).get("label") or "Legal risk"),
                    explanation=explanation,
                    suggestion=_text(item.get("suggestion")) or None,
                    evidence_ids=cited,
                    severity=severity,
                    gate_type=gate,
                    support_level=support,
                    quote_start=match.start() if match else None,
                    quote_end=match.end() if match else None,
                )
            )
        return findings


__all__ = [
    "ComposeError",
    "ComposedFinding",
    "LegalComposer",
    "SYSTEM_PROMPT",
    "WEB_PROMPT",
    "WebCheck",
    "WebEvidence",
]