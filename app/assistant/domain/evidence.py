"""Evidence building shared by the retriever and the document path (task 3.2).

A citation id is derived from `(source, version, chunk)` so the same evidence keeps the same id
across runs, instead of an index that changes with the result order. Conflicts are surfaced, not
resolved: the composer must abstain or state the limitation.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.assistant.ports import EvidenceCandidate
from app.knowledge.text import RULE_RE, normalize, tokens


def stable_citation_id(source_id: str, version_id: str, chunk_id: str) -> str:
    digest = hashlib.sha1(f"{source_id}|{version_id}|{chunk_id}".encode("utf-8")).hexdigest()
    return f"cite_{digest[:12]}"


def document_citation_id(snapshot_id: str, start: int, end: int) -> str:
    digest = hashlib.sha1(f"{snapshot_id}|{start}|{end}".encode("utf-8")).hexdigest()
    return f"cite_doc_{digest[:12]}"


def excerpt_for(text: str, terms: set[str]) -> str:
    """The allowed excerpt: the best-matching sentence, never the whole source."""
    sentences = [
        part.strip()
        for part in normalize(text).replace("。", ". ").replace("；", ". ").split(".")
        if part.strip()
    ]
    if not sentences:
        return normalize(text)[:600]
    scored = sorted(
        sentences,
        key=lambda sentence: sum(1 for term in terms if term in sentence.lower()),
        reverse=True,
    )
    return (scored[0] if scored else sentences[0])[:800]


def build_candidate(row: dict[str, Any], terms: set[str]) -> EvidenceCandidate:
    locator = dict(row.get("locator") or {})
    locator.setdefault("section", row.get("section"))
    if row.get("page") is not None:
        locator.setdefault("page", row.get("page"))
    return EvidenceCandidate(
        citation_id=stable_citation_id(
            str(row.get("source_id")), str(row.get("version_id")), str(row.get("chunk_id"))
        ),
        source_type=row["source_type"],
        title=row["title"],
        source_version=row.get("version_label") or row["version_id"],
        excerpt=excerpt_for(row["text"], terms),
        locator=locator,
        source_text=row["text"],
        source_id=row.get("source_id"),
        version_id=row.get("version_id"),
        chunk_id=row.get("chunk_id"),
        synthetic=bool(row.get("synthetic")),
        effective_from=row.get("effective_from"),
        effective_to=row.get("effective_to"),
    )


def rule_entities(text: str) -> set[str]:
    return {match.group(0).lower().replace(" ", "") for match in RULE_RE.finditer(text or "")}


def detect_conflicts(candidates: list[EvidenceCandidate]) -> list[dict[str, Any]]:
    """Two authorized sources citing the same rule but saying different things are a conflict."""
    groups: dict[str, list[EvidenceCandidate]] = {}
    for candidate in candidates:
        for entity in rule_entities(f"{candidate.title} {candidate.excerpt}"):
            groups.setdefault(entity, []).append(candidate)
    conflicts: list[dict[str, Any]] = []
    for entity, group in groups.items():
        by_source: dict[str, EvidenceCandidate] = {}
        for candidate in group:
            by_source.setdefault(str(candidate.source_id), candidate)
        if len(by_source) < 2:
            continue
        texts = {normalize(candidate.excerpt) for candidate in by_source.values()}
        if len(texts) < 2:
            continue
        conflicts.append(
            {
                "entity": entity,
                "citation_ids": [candidate.citation_id for candidate in by_source.values()],
                "source_ids": sorted(by_source),
                "explanation": f"来源对 {entity.upper()} 的表述不一致，不能自动选择其一。",
            }
        )
    return conflicts


def claim_supported(claim_text: str, candidate: EvidenceCandidate) -> bool:
    """A claim is supported only when its tokens appear in the cited excerpt, not just in the id."""
    claim_tokens = set(tokens(claim_text))
    excerpt_tokens = set(tokens(candidate.excerpt))
    return bool(claim_tokens & excerpt_tokens)


__all__ = [
    "build_candidate",
    "claim_supported",
    "detect_conflicts",
    "document_citation_id",
    "excerpt_for",
    "rule_entities",
    "stable_citation_id",
]