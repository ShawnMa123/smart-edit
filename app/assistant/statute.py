"""Statute evidence from an external legal-corpus service (`knowledge-statute-retrieval`).

The service returns its own diagnostics; this module turns them into a decision
("usable", or "not usable — here is why") so the rest of the pipeline can keep treating
"no candidates" as "no evidence" and let the existing general-web fallback take over.

Nothing here decides to search the web. It only reports outcomes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.assistant.domain.evidence import stable_citation_id
from app.assistant.egress import MAX_EXPANSION_CHARS, MAX_EXPANSION_TERMS
from app.assistant.ports import EvidenceCandidate, Principal

MAX_SOURCE_TEXT = 8000
DEFAULT_TOP_K = 5
# Availability thresholds (design D2). Calibrate with >=10 real questions on a +-0.1 grid;
# the measured sample scored 1.0 with confidence "medium", so these must not be guessed lower.
MIN_TOP_SCORE = 0.6
HEALTH_TTL_SECONDS = 30.0
_EXCERPT_CHARS = 240
_SENTENCE_END = "。！？；\n.!?;"


@dataclass(frozen=True)
class StatuteOutcome:
    """One retrieval attempt, translated into something the caller can record."""

    candidates: list[EvidenceCandidate] = field(default_factory=list)
    status: str = "ok"  # ok | failed
    reason: str = "ok"  # ok | superseded | degraded:keyword_only | empty | zero:<r> | ...
    # How many chunks the service returned, so callers can say "3 matches, not used".
    hits: int = 0
    # Which controlled terms were appended to the query (`statute-recall`).
    expansions: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        # Any returned text is usable evidence; confidence is a caveat, not a discard rule
        # (`knowledge-rag-first-fallback` D2).
        return bool(self.candidates)


def expand_terms(question: str, table: dict[str, tuple[str, ...]] | None) -> list[str]:
    """Rewrite generic words into controlled terms. Deterministic, order-preserving, capped.

    Substring matching on purpose: Chinese has no word boundaries, and the table is a small,
    reviewed list rather than a tokenizer.
    """
    if not table:
        return []
    lowered = (question or "").lower()
    gathered: list[str] = []
    for key, values in table.items():
        if key and key in lowered:
            gathered.extend(values)
    deduped = list(dict.fromkeys(term for term in gathered if term))
    capped: list[str] = []
    budget = 0
    for term in deduped[:MAX_EXPANSION_TERMS]:
        if budget + len(term) > MAX_EXPANSION_CHARS:
            break
        capped.append(term)
        budget += len(term)
    return capped


class _StatuteFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _sentence_around(text: str, start: int, end: int) -> str:
    """Grow a window to sentence boundaries; the result is always a slice of `text`."""
    left = max(0, min(len(text), start))
    right = max(left, min(len(text), end))
    while left > 0 and text[left - 1] not in _SENTENCE_END:
        left -= 1
    while right < len(text) and text[right] not in _SENTENCE_END:
        right += 1
    if right < len(text) and text[right] in _SENTENCE_END:
        right += 1
    if right - left > _EXCERPT_CHARS:
        left = max(0, start - _EXCERPT_CHARS // 2)
        right = min(len(text), left + _EXCERPT_CHARS)
    return text[left:right].strip()


def _cut_excerpt(text: str, matched: list[dict[str, Any]], terms: set[str]) -> str:
    """Return a sentence-sized slice containing a match; always a real substring of `text`.

    `excerpt_for` is deliberately not used here: it normalises the text (e.g. `。` -> `. `), so its
    output is not a substring of the source and the reviewer would reject every statute claim.
    """
    if not text:
        return ""
    if matched:
        item = min(matched, key=lambda value: int(value.get("start") or 0))
        start = int(item.get("start") or 0)
        return _sentence_around(text, start, int(item.get("end") or start)) or text[:_EXCERPT_CHARS]
    for term in sorted(terms):
        index = text.find(term)
        if index >= 0:
            return _sentence_around(text, index, index + len(term)) or text[:_EXCERPT_CHARS]
    return text[:_EXCERPT_CHARS]


def build_filters(plan: Any, applicable_on: str | None) -> dict[str, Any]:
    """Map the query context onto the service's filters; never substitute "today" for the trade date."""
    filters: dict[str, Any] = {}
    jurisdictions = list(getattr(plan, "jurisdictions", None) or [])
    if jurisdictions:
        filters["jurisdictions"] = jurisdictions
    as_of = applicable_on or getattr(plan, "applicable_on", None)
    if as_of:
        filters["as_of"] = as_of
    return filters


class StatuteRetriever:
    """`RetrieverPort` over the legal-corpus service, plus the reason behind each result."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout: float = 2.5,
        client: httpx.Client | None = None,
        top_k: int = DEFAULT_TOP_K,
        expansions: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self.top_k = max(1, int(top_k))
        self.client = client or httpx.Client(timeout=timeout)
        self.expansions = dict(expansions or {})
        self._health: dict[str, Any] | None = None
        self._health_at = 0.0

    # --- RetrieverPort ---------------------------------------------------------------------
    def search(
        self, principal: Principal, workspace_id: str, plan: Any, applicable_on: str | None
    ) -> list[EvidenceCandidate]:
        return self.search_detailed(principal, workspace_id, plan, applicable_on).candidates

    def search_detailed(
        self, principal: Principal, workspace_id: str, plan: Any, applicable_on: str | None
    ) -> StatuteOutcome:
        question = str(getattr(plan, "question", "") or "").strip()
        if not question:
            return StatuteOutcome(status="ok", reason="empty")
        # Generic words are rewritten into controlled terms so the corpus can find the right article
        # (`statute-recall`); the original wording is kept so nothing is lost.
        terms = expand_terms(question, self.expansions)
        query = f"{question} {' '.join(terms)}" if terms else question
        body = {
            "queries": [query],
            "top_k": self.top_k,
            "filters": build_filters(plan, applicable_on),
        }
        try:
            payload = self._post(body)
        except _StatuteFailure as exc:
            return StatuteOutcome(status="failed", reason=exc.reason, expansions=tuple(terms))
        outcome = self.judge(payload, terms=set(getattr(plan, "retrieval_terms", None) or []))
        return StatuteOutcome(
            outcome.candidates,
            status=outcome.status,
            reason=outcome.reason,
            hits=self._hit_count(payload),
            expansions=tuple(terms),
        )

    @staticmethod
    def _hit_count(payload: dict[str, Any]) -> int:
        return len([chunk for chunk in (payload.get("chunks") or []) if isinstance(chunk, dict)])

    # --- decision --------------------------------------------------------------------------
    def judge(self, payload: dict[str, Any], *, terms: set[str]) -> StatuteOutcome:
        """Turn the service's diagnostics into candidates plus a caveat.

        Every returned chunk becomes evidence (`knowledge-rag-first-fallback` D2). Confidence,
        coverage and supersession annotate how far the evidence can be trusted; they never discard
        it. Only a response with no chunks at all means "nothing found".
        """
        chunks = [chunk for chunk in (payload.get("chunks") or []) if isinstance(chunk, dict)]
        diagnostics = payload.get("diagnostics") or {}
        field_matches = payload.get("field_matches") or {}
        uncovered_block = field_matches.get("requested_uncovered") or {}
        uncovered = [str(value) for value in (uncovered_block.get("jurisdictions") or [])]
        uncovered += [str(value) for value in (uncovered_block.get("applies_to") or [])]
        if not chunks:
            zero = str(diagnostics.get("zero_reason") or "empty")
            return StatuteOutcome(status="ok", reason=f"zero:{zero}")

        degraded = [str(value) for value in (diagnostics.get("degraded") or [])]
        limit = 2 if "embedding" in degraded else self.top_k
        used = chunks[:limit]
        precision = (payload.get("corpus") or {}).get("precision") or {}
        candidates = [
            self._candidate(chunk, rank, terms, precision)
            for rank, chunk in enumerate(used, start=1)
        ]
        confidence = str(diagnostics.get("confidence") or "").lower()
        top_score = self._score(chunks[0])
        if uncovered:
            reason = f"uncovered:{','.join(uncovered)}"
        elif confidence == "low" or top_score < MIN_TOP_SCORE:
            # `confidence: low` and a weak top score are the service saying it is unsure. The
            # answer keeps the hits and states that caveat instead of handing the question back
            # with no evidence at all.
            reason = "low_confidence"
        elif any(chunk.get("superseded_by") for chunk in used):
            reason = "superseded"
        elif "embedding" in degraded:
            reason = "degraded:keyword_only"
        else:
            reason = "ok"
        return StatuteOutcome(candidates, status="ok", reason=reason)

    @staticmethod
    def _score(chunk: dict[str, Any]) -> float:
        try:
            return float(chunk.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _candidate(
        self,
        chunk: dict[str, Any],
        rank: int,
        terms: set[str],
        precision: dict[str, Any],
    ) -> EvidenceCandidate:
        source_text = str(chunk.get("text") or "")[:MAX_SOURCE_TEXT]
        article_ids = [str(value) for value in (chunk.get("article_ids") or [])]
        articles = [str(value) for value in (chunk.get("articles") or [])]
        jurisdictions = [str(value) for value in (chunk.get("jurisdictions") or [])]
        doc_id = str(chunk.get("doc_id") or "")
        chunk_id = str(chunk.get("chunk_id") or "")
        locator: dict[str, Any] = {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "article_id": article_ids[0] if article_ids else None,
            "article_label": articles[0] if articles else None,
            "jurisdiction": jurisdictions[0] if jurisdictions else None,
            "effective_from": chunk.get("effective_from"),
            "effective_to": chunk.get("effective_to"),
        }
        if jurisdictions and jurisdictions[0] in (precision or {}):
            locator["precision"] = precision[jurisdictions[0]]
        if chunk.get("superseded_by"):
            locator["superseded_by"] = str(chunk["superseded_by"])
        label = str(locator["article_label"] or "")
        effective = locator["effective_from"]
        version = f"{label}@{effective}" if label and effective else (label or str(effective or "unknown"))
        return EvidenceCandidate(
            citation_id=stable_citation_id("statute", doc_id, chunk_id),
            source_type="statute",
            title=str(chunk.get("source_doc") or doc_id or "statute"),
            source_version=version,
            excerpt=_cut_excerpt(source_text, list(chunk.get("matched_terms") or []), terms),
            locator=locator,
            source_text=source_text,
            source_id=doc_id or None,
            version_id=chunk_id or None,
            chunk_id=chunk_id or None,
            effective_from=chunk.get("effective_from"),
            effective_to=chunk.get("effective_to"),
            # Rank-derived so it never competes with the lexical score scale (design D2).
            score=round(1.0 - 0.01 * (rank - 1), 4),
        )

    # --- transport -------------------------------------------------------------------------
    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(
                f"{self.base_url}/v1/retrieve",
                json=body,
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise _StatuteFailure("timeout") from exc
        except httpx.HTTPError as exc:
            raise _StatuteFailure("service_error") from exc
        if response.status_code in (401, 403):
            raise _StatuteFailure("unauthorized")
        if response.status_code == 503:
            # A rebuild is not "zero hits": the caller must record the layer as failed.
            raise _StatuteFailure("corpus_updating")
        if response.status_code != 200:
            raise _StatuteFailure(f"http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise _StatuteFailure("invalid_json") from exc
        if not isinstance(payload, dict):
            raise _StatuteFailure("invalid_payload")
        return payload

    def health(self) -> dict[str, Any]:
        """Best-effort corpus snapshot for the capability view; never raises.

        Both the health probe and the corpus catalogue share one 30-second cache: the UI must not be
        able to claim coverage it has not measured, but it also must not issue two cross-service calls
        per panel open.
        """
        now = time.monotonic()
        if self._health is not None and now - self._health_at < HEALTH_TTL_SECONDS:
            return self._health
        info: dict[str, Any] = {
            "reachable": False,
            "documents": None,
            "chunks": None,
            "index_version": None,
            # `None` means "not measured"; an empty list would read as "covers nothing".
            "jurisdictions": None,
        }
        try:
            response = self.client.get(f"{self.base_url}/health", timeout=min(self.timeout, 1.5))
            if response.status_code == 200:
                data = response.json() or {}
                info = {
                    "reachable": str(data.get("status")) == "ready",
                    "documents": data.get("documents"),
                    "chunks": data.get("chunks"),
                    "index_version": data.get("index_version"),
                    "jurisdictions": None,
                }
        except Exception:  # noqa: BLE001 - the capability view must never fail the request
            pass
        try:
            response = self.client.get(
                f"{self.base_url}/v1/corpus/documents",
                params={"limit": 1},
                headers={"Authorization": f"Bearer {self.api_token}"},
                timeout=min(self.timeout, 1.5),
            )
            if response.status_code == 200:
                payload = response.json() or {}
                values = [str(value) for value in (payload.get("jurisdictions") or [])]
                info["jurisdictions"] = sorted(values) or None
        except Exception:  # noqa: BLE001 - a failed catalogue is "not measured", not "empty"
            pass
        self._health = info
        self._health_at = now
        return info


__all__ = [
    "DEFAULT_TOP_K",
    "MIN_TOP_SCORE",
    "StatuteOutcome",
    "StatuteRetriever",
    "build_filters",
    "expand_terms",
]