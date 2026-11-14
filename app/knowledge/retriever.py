"""Deterministic lexical retriever (design D6). C replaces it behind `RetrieverPort`.

Filtering happens before scoring: only published, currently effective, scope-permitted versions are
passed in by the store, and the retriever never widens that set.
"""

from __future__ import annotations

from app.assistant.domain.evidence import build_candidate
from app.assistant.domain.query import HELP_SOURCE_IDS, QueryPlan
from app.assistant.ports import EvidenceCandidate, Principal
from app.knowledge.models import DEFAULT_ALLOWED_SCOPES
from app.knowledge.text import normalize, tokens

MAX_EVIDENCE = 8

__all__ = ["LexicalRetriever"]


class LexicalRetriever:
    def __init__(self, store) -> None:
        self.store = store

    def search(
        self, principal: Principal, workspace_id: str, plan: QueryPlan, applicable_on: str | None
    ) -> list[EvidenceCandidate]:
        rows = self.store.published_chunks(
            applicable_on or plan.applicable_on,
            allowed_scopes=DEFAULT_ALLOWED_SCOPES,
            organization_id=None,
        )
        # Help text contains generic words (提交/审批/文档) that would otherwise pollute ordinary
        # answers. Capability-help runs see only the language-matched help source; all other runs
        # exclude every help source. Language isolation comes first so Chinese and English corpora
        # never compete or conflict in the same answer.
        rows = [row for row in rows if row.get("language") == plan.language]
        help_ids = set(HELP_SOURCE_IDS.values())
        if plan.capability_help:
            help_id = plan.help_source_id or HELP_SOURCE_IDS.get(plan.language)
            rows = [row for row in rows if row["source_id"] == help_id]
        else:
            rows = [row for row in rows if row["source_id"] not in help_ids]
        terms = set(plan.retrieval_terms)
        if not terms:
            return []
        scored: list[tuple[float, dict]] = []
        for row in rows:
            title = normalize(row.get("title") or "").lower()
            body = normalize(row.get("text") or "").lower()
            text_terms = set(tokens(body))
            title_terms = set(tokens(title))
            overlap = terms & (text_terms | title_terms)
            if not overlap:
                continue
            score = sum(1.0 for term in overlap if term in text_terms)
            score += 3.0 * sum(1.0 for term in overlap if term in title_terms)
            score += 0.2 * sum(body.count(term) for term in overlap)
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)

        results: list[EvidenceCandidate] = []
        for score, row in scored[:MAX_EVIDENCE]:
            candidate = build_candidate(row, terms)
            candidate.score = score
            results.append(candidate)
        return results