"""Outbound egress policy (knowledge-egress-policy / design D3–D4).

The policy decides what may leave the service *before* any external call. It is deliberately
conservative: unknown policy configuration denies, and every redaction is reported so the UI can
show what will actually be sent.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Purpose = Literal["search", "compose", "tool_search", "statute"]
Action = Literal["allow", "redact", "deny"]

REDACTED = "[redacted]"

# Guardrails for the configurable presets (`knowledge-simple-ask`). They keep a bad config from
# either silently weakening redaction or hanging the request with a catastrophic pattern.
MAX_REDACTION_RULES = 32
MAX_PATTERN_CHARS = 512
DEFAULT_REDACTION_BUDGET_MS = 250
# Query-expansion caps (`statute-recall`): enough to disambiguate, few enough that the query keeps
# its meaning. Excess terms are dropped, never an error.
MAX_EXPANSION_TERMS_PER_KEY = 4
MAX_EXPANSION_TERMS = 12
MAX_EXPANSION_CHARS = 120
CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
SAMPLE_CONFIG_NAME = "knowledge.sample.json"
LEGACY_CONFIG_NAME = "egress.yaml"

# Used when a config omits `redactions` entirely: the safe direction is to keep redacting.
_DEFAULT_REDACTIONS: tuple[tuple[str, str], ...] = (
    ("amount_present", r"(?i)(?:USD|EUR|CNY|HKD|GBP|JPY|SGD|AUD)\s?[\d,]+(?:\.\d+)?|[\d,]{3,}(?:\.\d+)?\s?(?:USD|EUR|CNY|HKD|GBP|JPY|SGD|AUD)"),
    ("reference_present", r"\b[A-Z]{2,6}-\d{3,}(?:-\d+)?\b"),
    ("account_number_present", r"\b\d{8,}\b"),
    ("email_present", r"[\w.+-]+@[\w-]+\.[\w.]+"),
    ("url_present", r"https?://\S+"),
    ("variable_placeholder", r"\{\{[^{}]+\}\}"),
)


def compile_redactions(raw: list[Any] | None) -> list[tuple[str, re.Pattern[str]]]:
    """Compile the configured redaction presets; any problem fails loudly at startup.

    A rule that cannot compile must never be skipped silently — that would be a silent leak.
    """
    if not raw:
        return [(reason, re.compile(pattern)) for reason, pattern in _DEFAULT_REDACTIONS]
    if len(raw) > MAX_REDACTION_RULES:
        raise ValueError(
            f"egress.redactions has {len(raw)} rules; at most {MAX_REDACTION_RULES} are allowed"
        )
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"egress.redactions[{index}] must be an object with reason and pattern")
        reason = str(item.get("reason") or "").strip()
        pattern = str(item.get("pattern") or "")
        if not reason or not pattern:
            raise ValueError(f"egress.redactions[{index}] needs both reason and pattern")
        if len(pattern) > MAX_PATTERN_CHARS:
            raise ValueError(
                f"egress.redactions[{index}] pattern is {len(pattern)} chars; "
                f"the limit is {MAX_PATTERN_CHARS}"
            )
        try:
            compiled.append((reason, re.compile(pattern)))
        except re.error as exc:
            raise ValueError(f"egress.redactions[{index}] ({reason}) is not a valid regex: {exc}") from exc
    return compiled


def normalise_expansions(raw: Any) -> dict[str, tuple[str, ...]]:
    """Validate and clip the query-expansion table (`statute-recall`).

    Structure errors raise; over-long tables are clipped, because the caps exist to protect the
    query, not to reject a config.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("query_expansion must be an object of term -> [terms]")
    table: dict[str, tuple[str, ...]] = {}
    for key, values in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        if not isinstance(values, list):
            raise ValueError(f"query_expansion[{name!r}] must be a list of terms")
        terms: list[str] = []
        for value in values:
            term = str(value or "").strip()
            if not term or term.lower() == name.lower() or term in terms:
                continue
            terms.append(term)
            if len(terms) >= MAX_EXPANSION_TERMS_PER_KEY:
                break
        if terms:
            table[name.lower()] = tuple(terms)
    return table


class _OverBudget(RuntimeError):
    """Redaction exceeded its time budget; treated as a policy failure, never as "clean"."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Public rule identifiers (URDG 758, ISP98, UCP 600) must survive redaction: they are the search key.
# This exemption is fixed in code on purpose: a config must never be able to whitelist an amount.
_RULE_ID = re.compile(r"\b(?:URDG|ISP|UCP|ISBP|URC|URR)\s?\d{2,4}\b", re.IGNORECASE)


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
        redactions: list[tuple[str, re.Pattern[str]]] | None = None,
        redaction_budget_ms: int = DEFAULT_REDACTION_BUDGET_MS,
        jurisdictions: list[str] | None = None,
        suggested_questions: list[str] | None = None,
        query_expansion: dict[str, tuple[str, ...]] | None = None,
        loaded: bool = True,
    ) -> None:
        self.version = version
        self.allowed_domains = [domain.lower().strip(".") for domain in (allowed_domains or [])]
        self.max_query_chars = max_query_chars
        self.selection_overlap_chars = selection_overlap_chars
        self.extra_sensitive_terms = [term for term in (extra_sensitive_terms or []) if term]
        self.redactions = redactions if redactions is not None else compile_redactions(None)
        self.redaction_budget_ms = redaction_budget_ms
        # UI presets travel with the same file; `None` means "not configured" (never a fake list).
        self.jurisdictions = list(jurisdictions) if jurisdictions else None
        self.suggested_questions = list(suggested_questions) if suggested_questions else None
        # Term normalisation for statute retrieval (`statute-recall`); empty means "no expansion".
        self.query_expansion = dict(query_expansion or {})
        self.loaded = loaded

    @classmethod
    def from_file(cls, path: str | Path | None) -> "EgressPolicy":
        """Load `.json` or `.yaml`. A file that exists but cannot be read or parsed denies everything."""
        if not path:
            return cls(loaded=False)
        policy_path = Path(path)
        if not policy_path.is_file():
            return cls(loaded=False)
        try:
            text = policy_path.read_text(encoding="utf-8")
            raw = json.loads(text) if policy_path.suffix.lower() == ".json" else yaml.safe_load(text)
        except (OSError, ValueError, yaml.YAMLError):
            return cls(loaded=False)
        if not isinstance(raw, dict):
            return cls(loaded=False)
        # The knowledge config keeps egress settings under `egress`; the legacy file is flat.
        payload = raw.get("egress") if isinstance(raw.get("egress"), dict) else raw
        if not isinstance(payload, dict):
            return cls(loaded=False)
        # Anything structurally wrong with the redaction presets raises here: a config that cannot
        # be compiled must fail at start-up, never serve with one rule silently missing.
        return cls(
            version=str(raw.get("version") or payload.get("version") or "unset"),
            allowed_domains=list(payload.get("allowed_domains") or []),
            max_query_chars=int(payload.get("max_query_chars") or 400),
            selection_overlap_chars=int(payload.get("selection_overlap_chars") or 40),
            extra_sensitive_terms=list(payload.get("extra_sensitive_terms") or []),
            redactions=compile_redactions(payload.get("redactions")),
            redaction_budget_ms=int(
                payload.get("redaction_budget_ms") or DEFAULT_REDACTION_BUDGET_MS
            ),
            jurisdictions=list((raw.get("scope_presets") or {}).get("jurisdictions") or []),
            suggested_questions=list(raw.get("suggested_questions") or []),
            query_expansion=normalise_expansions(raw.get("query_expansion")),
            loaded=True,
        )

    @classmethod
    def load(cls, explicit_path: str | Path | None = None) -> "EgressPolicy":
        """Resolve the config by priority: explicit path → knowledge.json → sample JSON → YAML → deny.

        Fallback happens only when a file is **absent**. A file that exists but is invalid raises
        (at start-up) or denies (when loaded defensively by a caller) — never a silent downgrade to
        a different file's rules.
        """
        candidates = [
            Path(explicit_path) if explicit_path else None,
            CONFIG_DIR / "knowledge.json",
            CONFIG_DIR / SAMPLE_CONFIG_NAME,
            CONFIG_DIR / LEGACY_CONFIG_NAME,
        ]
        for candidate in candidates:
            if candidate is not None and candidate.is_file():
                return cls.from_file(candidate)
        return cls(loaded=False)

    def check(self, payload: EgressInput) -> EgressDecision:
        try:
            return self._decide(payload)
        except _OverBudget:
            # A pattern that blows the budget is a policy failure, not a clean query.
            return EgressDecision("deny", "pattern_timeout", None, self.version)
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

        if payload.purpose == "statute":
            # The statute corpus is an approved internal service, usually reached through a loopback
            # tunnel, so the public domain allowlist cannot meaningfully apply to it. The redaction
            # and selection rules still do: what leaves the service is the question, never the
            # document text (`knowledge-statute-live` D2).
            if not self.loaded:
                return EgressDecision("deny", "policy_unavailable", None, self.version)
            return self._screen(payload, query)

        if not self.loaded:
            return EgressDecision("deny", "policy_unavailable", None, self.version)

        if payload.provider_host and self.allowed_domains:
            host = payload.provider_host.lower()
            if not any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains):
                return EgressDecision("deny", "domain_not_allowed", None, self.version)

        return self._screen(payload, query)

    def _screen(self, payload: EgressInput, query: str) -> EgressDecision:
        """Rules shared by every outbound purpose that carries user text."""
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
    def redact(
        self, text: str, *, entities: tuple[str, ...] = ()
    ) -> tuple[str, tuple[str, ...]] | None:
        """Apply the configured presets to one outbound payload.

        Returns `None` when the redaction budget is exhausted: the caller must treat that as a
        policy failure (deny), never as "clean text". Used by the legal document scan, whose payload
        (a clause) is far longer than a search query and therefore not screened by `check()`.
        """
        try:
            redacted, reasons = self._redact(text, entities)
        except _OverBudget:
            return None
        return redacted, tuple(reasons)

    def _overlaps(self, query: str, selection: str) -> bool:
        if not query or not selection:
            return False
        matcher = difflib.SequenceMatcher(a=query, b=selection, autojunk=False)
        match = matcher.find_longest_match(0, len(query), 0, len(selection))
        return match.size >= self.selection_overlap_chars

    def _redact(self, query: str, entities: tuple[str, ...]) -> tuple[str, list[str]]:
        reasons: list[str] = []
        text = query

        for term in self.extra_sensitive_terms:
            replaced = re.sub(re.escape(term), REDACTED, text, flags=re.IGNORECASE)
            if replaced != text:
                text = replaced
                if "sensitive_term" not in reasons:
                    reasons.append("sensitive_term")

        for entity in entities:
            entity = (entity or "").strip()
            if not entity or _RULE_ID.fullmatch(entity):
                continue
            replaced = re.sub(re.escape(entity), REDACTED, text, flags=re.IGNORECASE)
            if replaced != text:
                text = replaced
                if "entity_removed" not in reasons:
                    reasons.append("entity_removed")

        # Configured presets (`knowledge-simple-ask`). The budget guards against a catastrophic
        # pattern turning one question into an unbounded request.
        started = time.monotonic()
        for reason, pattern in self.redactions:
            replaced = pattern.sub(REDACTED, text)
            if replaced != text:
                text = replaced
                if reason not in reasons:
                    reasons.append(reason)
            if (time.monotonic() - started) * 1000 > self.redaction_budget_ms:
                raise _OverBudget(reason)

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
