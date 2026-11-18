"""Outbound egress policy (knowledge-egress-policy / design D3–D4).

The policy decides what may leave the service *before* any external call. It is deliberately
conservative: unknown policy configuration denies, and every redaction is reported so the UI can
show what will actually be sent.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Purpose = Literal["search", "compose", "tool_search"]
Action = Literal["allow", "redact", "deny"]

REDACTED = "[redacted]"

# Public rule identifiers (URDG 758, ISP98, UCP 600) must survive redaction: they are the search key.
_RULE_ID = re.compile(r"\b(?:URDG|ISP|UCP|ISBP|URC|URR)\s?\d{2,4}\b", re.IGNORECASE)
_AMOUNT = re.compile(
    r"(?:USD|EUR|CNY|HKD|GBP|JPY|SGD|AUD)\s?[\d,]+(?:\.\d+)?"
    r"|[\d,]{3,}(?:\.\d+)?\s?(?:USD|EUR|CNY|HKD|GBP|JPY|SGD|AUD)",
    re.IGNORECASE,
)
_REFERENCE = re.compile(r"\b[A-Z]{2,6}-\d{3,}(?:-\d+)?\b")
_LONG_DIGITS = re.compile(r"\b\d{8,}\b")
_VARIABLE = re.compile(r"\{\{[^{}]+\}\}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_URL = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class EgressInput:
    purpose: Purpose
    question: str
    candidate_query: str
    selection_text: str | None = None
    entities: tuple[str, ...] = ()
    provider: str | None = None
    provider_host: str | None = None
    provider_approved: bool = False
    # General web channel (knowledge-general-web): a second, explicit opt-in.
    tool_search_enabled: bool = False


@dataclass(frozen=True)
class EgressDecision:
    action: Action
    reason_code: str
    outbound_query: str | None = None
    policy_version: str = "unset"
    redactions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return self.action in ("allow", "redact")


class EgressPolicy:
    """Rule-first policy. A missing or broken configuration denies every search request."""

    def __init__(
        self,
        *,
        version: str = "unset",
        allowed_domains: list[str] | None = None,
        max_query_chars: int = 400,
        selection_overlap_chars: int = 40,
        extra_sensitive_terms: list[str] | None = None,
        loaded: bool = True,
    ) -> None:
        self.version = version
        self.allowed_domains = [domain.lower().strip(".") for domain in (allowed_domains or [])]
        self.max_query_chars = max_query_chars
        self.selection_overlap_chars = selection_overlap_chars
        self.extra_sensitive_terms = [term for term in (extra_sensitive_terms or []) if term]
        self.loaded = loaded

    @classmethod
    def from_file(cls, path: str | Path | None) -> "EgressPolicy":
        if not path:
            return cls(loaded=False)
        policy_path = Path(path)
        if not policy_path.is_file():
            return cls(loaded=False)
        try:
            payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return cls(loaded=False)
        if not isinstance(payload, dict):
            return cls(loaded=False)
        return cls(
            version=str(payload.get("version") or "unset"),
            allowed_domains=list(payload.get("allowed_domains") or []),
            max_query_chars=int(payload.get("max_query_chars") or 400),
            selection_overlap_chars=int(payload.get("selection_overlap_chars") or 40),
            extra_sensitive_terms=list(payload.get("extra_sensitive_terms") or []),
            loaded=True,
        )

    def check(self, payload: EgressInput) -> EgressDecision:
        try:
            return self._decide(payload)
        except Exception:  # noqa: BLE001 - fail closed on any policy failure
            return EgressDecision("deny", "policy_unavailable", None, self.version)

    # --- rules ----------------------------------------------------------------------------
    def _decide(self, payload: EgressInput) -> EgressDecision:
        query = (payload.candidate_query or payload.question or "").strip()

        if payload.purpose == "compose":
            if not payload.provider_approved:
                return EgressDecision("deny", "processor_not_approved", None, self.version)
            # Approved processors may receive the question and the evidence bundle; identity and
            # attachments are never part of this payload (enforced by the caller).
            return EgressDecision("allow", "approved_processor", query, self.version)

        if payload.purpose == "tool_search":
            if not payload.tool_search_enabled:
                return EgressDecision("deny", "tool_search_disabled", None, self.version)
            if not payload.provider_approved:
                return EgressDecision("deny", "processor_not_approved", None, self.version)
            # Approved tool search keeps the same redaction/selection rules as a search request.

        if not self.loaded:
            return EgressDecision("deny", "policy_unavailable", None, self.version)

        if payload.provider_host and self.allowed_domains:
            host = payload.provider_host.lower()
            if not any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains):
                return EgressDecision("deny", "domain_not_allowed", None, self.version)

        if payload.selection_text and self._overlaps(query, payload.selection_text):
            return EgressDecision("deny", "contains_selection", None, self.version)

        if len(query) > self.max_query_chars:
            return EgressDecision("deny", "query_too_long", None, self.version)

        redacted, reasons = self._redact(query, payload.entities)
        if not reasons:
            return EgressDecision("allow", "allowed", query, self.version)
        residual = re.sub(r"\[redacted\]", "", redacted).strip(" [](){}.,;:!?-_/")
        if len(residual) < 4:
            return EgressDecision("deny", "query_empty_after_redaction", None, self.version)
        return EgressDecision("redact", reasons[0], redacted, self.version, tuple(reasons))

    # --- helpers --------------------------------------------------------------------------
    def _overlaps(self, query: str, selection: str) -> bool:
        if not query or not selection:
            return False
        matcher = difflib.SequenceMatcher(a=query, b=selection, autojunk=False)
        match = matcher.find_longest_match(0, len(query), 0, len(selection))
        return match.size >= self.selection_overlap_chars

    def _redact(self, query: str, entities: tuple[str, ...]) -> tuple[str, list[str]]:
        reasons: list[str] = []
        text = query

        def replace(pattern: re.Pattern[str], reason: str) -> None:
            nonlocal text
            replaced = pattern.sub(REDACTED, text)
            if replaced != text:
                text = replaced
                reasons.append(reason)

        for term in self.extra_sensitive_terms:
            replaced = re.sub(re.escape(term), REDACTED, text, flags=re.IGNORECASE)
            if replaced != text:
                text = replaced
                reasons.append("sensitive_term")

        for entity in entities:
            entity = (entity or "").strip()
            if not entity or _RULE_ID.fullmatch(entity):
                continue
            replaced = re.sub(re.escape(entity), REDACTED, text, flags=re.IGNORECASE)
            if replaced != text:
                text = replaced
                reasons.append("entity_removed")

        replace(_AMOUNT, "amount_present")
        replace(_REFERENCE, "reference_present")
        replace(_LONG_DIGITS, "account_number_present")
        replace(_EMAIL, "email_present")
        replace(_URL, "url_present")
        replace(_VARIABLE, "variable_placeholder")

        # `[redacted]` markers are stable output; collapse accidental doubles.
        text = re.sub(r"(?:\[redacted\]\s*){2,}", f"{REDACTED} ", text)

        # A public rule id must survive: if a rule ate one, append it back for the search to work.
        for rule_id in _RULE_ID.findall(query):
            if rule_id.lower() not in text.lower() and REDACTED in text:
                text = f"{text} {rule_id}".strip()
        return text.strip(), list(dict.fromkeys(reasons))


def demo_policy(**overrides: Any) -> EgressPolicy:
    """Test helper: an explicit policy for unit tests (never used in the app default path)."""
    values: dict[str, Any] = {"version": "test-1", "allowed_domains": ["example.org"]}
    values.update(overrides)
    return EgressPolicy(**values)


__all__ = ["EgressDecision", "EgressInput", "EgressPolicy", "REDACTED", "demo_policy"]
