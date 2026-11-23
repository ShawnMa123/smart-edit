"""Retrieval layer adapters (knowledge-retrieval-layers / design D1, D7).

Every layer produces `EvidenceCandidate`s so the composer, the citation contract and the review step
stay unchanged. The web layer never forwards anything itself: callers must run the egress policy
first and pass the already-redacted query.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

from app.assistant.domain.evidence import excerpt_for, stable_citation_id
from app.assistant.ports import EvidenceCandidate, Principal

MAX_EVIDENCE = 8
MAX_WEB_RESULTS = 5
MAX_SOURCE_TEXT = 8000


class RetrievalError(RuntimeError):
    """A retrieval layer failed; the caller marks the layer failed and continues."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WebPage:
    url: str
    title: str
    text: str
    rank: int = 1
    published_at: str | None = None
    provider: str = "fixture"

    @property
    def domain(self) -> str:
        without_scheme = self.url.split("://", 1)[-1]
        return without_scheme.split("/", 1)[0].lower()


class FixtureWebSearch:
    """Deterministic provider for local runs and tests; no network."""

    def __init__(
        self,
        pages: Iterable[WebPage] | None = None,
        *,
        retrieved_at: str = "2026-11-16T00:00:00Z",
        error: Exception | None = None,
        limit: int = MAX_WEB_RESULTS,
    ) -> None:
        self._pages = list(pages or [])
        self.retrieved_at = retrieved_at
        self._error = error
        self.limit = limit

    def search(self, query: str, *, host: str | None = None) -> tuple[list[WebPage], str]:
        if self._error is not None:
            raise self._error
        hits = [page for page in self._pages if query and query.strip()]
        return hits[: self.limit], self.retrieved_at


class HttpWebSearch:
    """Approved search provider behind the same contract; only reachable after the egress gate."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 8.0,
        limit: int = MAX_WEB_RESULTS,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout)
        self.timeout = timeout
        self.limit = limit

    def search(self, query: str, *, host: str | None = None) -> tuple[list[WebPage], str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.client.post(
                self.endpoint,
                json={"query": query, "limit": self.limit},
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise RetrievalError("web_search_timeout") from exc
        except httpx.HTTPError as exc:
            raise RetrievalError("web_search_failed") from exc
        if response.status_code != 200:
            raise RetrievalError(f"web_search_http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError("web_search_invalid_json") from exc
        items = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RetrievalError("web_search_invalid_payload")
        pages: list[WebPage] = []
        for index, item in enumerate(items[: self.limit], start=1):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            pages.append(
                WebPage(
                    url=str(item["url"]),
                    title=str(item.get("title") or item["url"]),
                    text=str(item.get("text") or item.get("snippet") or ""),
                    rank=int(item.get("rank") or index),
                    published_at=item.get("published_at"),
                    provider=str(item.get("provider") or "http"),
                )
            )
        retrieved_at = str((payload or {}).get("retrieved_at") or "")
        return pages, retrieved_at


@dataclass(frozen=True)
class WebSearchOutcome:
    candidates: list[EvidenceCandidate] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    retrieved_at: str | None = None


def web_candidates(
    pages: Iterable[WebPage],
    terms: set[str],
    *,
    allowed_domains: Iterable[str] = (),
    retrieved_at: str | None = None,
    limit: int = MAX_WEB_RESULTS,
) -> WebSearchOutcome:
    """Convert approved pages into evidence; unapproved domains are dropped, never silently kept."""
    allowed = [domain.lower() for domain in allowed_domains if domain]
    candidates: list[EvidenceCandidate] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for page in pages:
        if allowed and not any(
            page.domain == domain or page.domain.endswith(f".{domain}") for domain in allowed
        ):
            dropped.append(f"domain_not_allowed:{page.domain}")
            continue
        text = (page.text or "").strip()
        if not text:
            dropped.append(f"empty_text:{page.url}")
            continue
        if page.url in seen:
            dropped.append(f"duplicate_url:{page.url}")
            continue
        seen.add(page.url)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        candidates.append(
            EvidenceCandidate(
                citation_id=stable_citation_id(
                    page.url, retrieved_at or page.published_at or "", content_hash[:12]
                ),
                source_type="approved_web",
                title=page.title or page.url,
                source_version=retrieved_at or page.published_at or "unknown",
                excerpt=excerpt_for(text, terms),
                locator={
                    "url": page.url,
                    "domain": page.domain,
                    "retrieved_at": retrieved_at,
                    "provider": page.provider,
                    "rank": page.rank,
                    "content_hash": content_hash[:16],
                },
                source_text=text[:MAX_SOURCE_TEXT],
                source_id=page.url,
                chunk_id=content_hash[:12],
                score=1.0 / max(page.rank, 1),
            )
        )
        if len(candidates) >= limit:
            break
    return WebSearchOutcome(candidates=candidates, dropped=dropped, retrieved_at=retrieved_at)


def merge_layers(
    *layers: Iterable[EvidenceCandidate], limit: int = MAX_EVIDENCE
) -> list[EvidenceCandidate]:
    """Merge retrieval layers, de-duplicating identical sources and keeping the best score."""
    best: dict[tuple[str, str, str], EvidenceCandidate] = {}
    order: list[tuple[str, str, str]] = []
    for layer in layers:
        for candidate in layer:
            locator = candidate.locator or {}
            key = (
                candidate.source_type,
                str(candidate.source_id or locator.get("url") or candidate.version_id or ""),
                str(candidate.chunk_id or locator.get("content_hash") or ""),
            )
            current = best.get(key)
            if current is None:
                best[key] = candidate
                order.append(key)
            elif candidate.score > current.score:
                best[key] = candidate
    merged = [best[key] for key in order]
    merged.sort(key=lambda candidate: (candidate.source_type == "approved_web", -candidate.score))
    if len(merged) > limit and limit > 0:
        web_first = next(
            (candidate for candidate in merged if candidate.source_type == "approved_web"), None
        )
        merged = [*merged[: limit - 1], web_first] if web_first is not None else merged[:limit]
    return merged[:limit]
class RagHttpAdapter:
    """Second local layer: an internal RAG service behind the same RetrieverPort shape."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 5.0,
        top_k: int = 6,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout)
        self.timeout = timeout
        self.top_k = top_k

    def search(
        self, principal: Principal, workspace_id: str, plan: Any, applicable_on: str | None
    ) -> list[EvidenceCandidate]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "query": plan.question,
            "terms": list(plan.retrieval_terms),
            "locale": plan.language,
            "applicable_on": applicable_on or plan.applicable_on,
            "top_k": self.top_k,
            # Workspace scope is sent as an opaque scope id; no user identity leaves the service.
            "scope": workspace_id,
        }
        try:
            response = self.client.post(self.endpoint, json=body, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise RetrievalError("rag_timeout") from exc
        except httpx.HTTPError as exc:
            raise RetrievalError("rag_unavailable") from exc
        if response.status_code != 200:
            raise RetrievalError(f"rag_http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RetrievalError("rag_invalid_json") from exc
        items = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RetrievalError("rag_invalid_payload")

        terms = set(plan.retrieval_terms)
        candidates: list[EvidenceCandidate] = []
        for item in items[: self.top_k]:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            source_id = str(item.get("source_id") or item.get("url") or "")
            version_id = str(item.get("version_id") or item.get("version") or "")
            chunk_id = str(
                item.get("chunk_id") or hashlib.sha1(str(item["text"]).encode()).hexdigest()[:12]
            )
            source_type = str(item.get("source_type") or "trade_rule")
            if source_type not in ("product_manual", "trade_rule", "internal_policy", "approved_web"):
                source_type = "trade_rule"
            candidates.append(
                EvidenceCandidate(
                    citation_id=stable_citation_id(source_id, version_id, chunk_id),
                    source_type=source_type,  # type: ignore[arg-type]
                    title=str(item.get("title") or source_id or "rag"),
                    source_version=str(item.get("source_version") or version_id or "unknown"),
                    excerpt=excerpt_for(str(item["text"]), terms),
                    locator=dict(item.get("locator") or {}),
                    source_text=str(item["text"])[:MAX_SOURCE_TEXT],
                    source_id=source_id or None,
                    version_id=version_id or None,
                    chunk_id=chunk_id,
                    effective_from=item.get("effective_from"),
                    effective_to=item.get("effective_to"),
                    score=float(item.get("score") or 0.0),
                )
            )
        return candidates


__all__ = [
    "FixtureWebSearch",
    "HttpWebSearch",
    "MAX_EVIDENCE",
    "MAX_WEB_RESULTS",
    "RagHttpAdapter",
    "RetrievalError",
    "WebPage",
    "WebSearchOutcome",
    "merge_layers",
]
