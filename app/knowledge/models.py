"""Knowledge source/version/chunk contracts and applicability metadata (task 2.1).

The SQLite rows are the storage form; these dataclasses are what the knowledge service and the
retriever pass around. Missing applicability metadata is returned as an explicit `None` plus a
reason, never as an empty string or a silently defaulted scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceType = Literal[
    "product_manual",
    "trade_rule",
    "internal_policy",
    "document_snapshot",
    "attachment",
    "approved_web",
]
KnowledgeStatus = Literal[
    "processing", "pending_review", "published", "superseded", "withdrawn", "rejected"
]

# Every transition the knowledge service accepts. `published -> superseded` happens atomically when a
# newer version of the same source is published; `withdrawn` is terminal for retrieval.
TRANSITIONS: dict[str, frozenset[str]] = {
    "processing": frozenset({"pending_review"}),
    "pending_review": frozenset({"published", "rejected"}),
    "published": frozenset({"superseded", "withdrawn"}),
    "superseded": frozenset({"withdrawn"}),
    "rejected": frozenset(),
    "withdrawn": frozenset(),
}

DEFAULT_ALLOWED_SCOPES = ("public", "organization", "bank_internal")
SOURCE_TYPES = (
    "product_manual",
    "trade_rule",
    "internal_policy",
    "document_snapshot",
    "attachment",
    "approved_web",
)


class KnowledgeError(ValueError):
    """Invalid import/review input; callers must not publish anything."""


@dataclass(frozen=True)
class KnowledgeSource:
    source_id: str
    source_type: SourceType
    publisher: str
    language: str = "zh-CN"
    scope: str = "organization"
    organization_id: str | None = None
    jurisdictions: tuple[str, ...] = ()
    license_reference: str = "synthetic-demo"
    synthetic: bool = True


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    text: str
    section: str | None = None
    page: int | None = None
    title_path: str = ""
    locator: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeVersion:
    version_id: str
    source_id: str
    title: str
    version_label: str
    effective_from: str | None
    effective_to: str | None
    submitted_by: str
    status: KnowledgeStatus = "processing"
    reviewed_by: str | None = None
    review_reason: str | None = None
    chunks: tuple[KnowledgeChunk, ...] = ()


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def parse_source(raw: dict[str, Any]) -> KnowledgeSource:
    try:
        source = KnowledgeSource(
            source_id=str(raw["source_id"]),
            source_type=raw["source_type"],
            publisher=str(raw["publisher"]),
            language=str(raw.get("language", "zh-CN")),
            scope=str(raw.get("scope", "organization")),
            organization_id=raw.get("organization_id"),
            jurisdictions=tuple(raw.get("jurisdictions") or ()),
            license_reference=str(raw.get("license_reference", "synthetic-demo")),
            synthetic=bool(raw.get("synthetic", True)),
        )
    except KeyError as exc:
        raise KnowledgeError(f"source is missing {exc.args[0]}") from exc
    if not source.source_id.strip():
        raise KnowledgeError("source_id must not be empty")
    if source.source_type not in SOURCE_TYPES:
        raise KnowledgeError(f"source_type must be one of {SOURCE_TYPES}")
    return source


def parse_chunks(raw_chunks: list[dict[str, Any]]) -> tuple[KnowledgeChunk, ...]:
    if not raw_chunks:
        raise KnowledgeError("a knowledge version needs at least one chunk")
    chunks: list[KnowledgeChunk] = []
    seen: set[str] = set()
    for raw in raw_chunks:
        chunk_id = str(raw.get("chunk_id") or "").strip()
        text = str(raw.get("text") or "").strip()
        if not chunk_id or not text:
            raise KnowledgeError("every chunk needs chunk_id and non-empty text")
        if chunk_id in seen:
            raise KnowledgeError(f"duplicate chunk_id {chunk_id!r}")
        seen.add(chunk_id)
        page = raw.get("page")
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                text=text,
                section=raw.get("section"),
                page=int(page) if page is not None else None,
                title_path=str(raw.get("title_path") or ""),
                locator=dict(raw.get("locator") or {}),
            )
        )
    return tuple(chunks)


def applicability(
    version: dict[str, Any] | KnowledgeVersion, source: dict[str, Any] | KnowledgeSource
) -> dict[str, Any]:
    """Explicit applicability metadata, with a reason for every gap instead of an invented value."""
    if isinstance(version, KnowledgeVersion):
        version_data: dict[str, Any] = {
            "effective_from": version.effective_from,
            "effective_to": version.effective_to,
            "version_label": version.version_label,
        }
    else:
        version_data = version
    if isinstance(source, KnowledgeSource):
        source_data: dict[str, Any] = {
            "jurisdictions": list(source.jurisdictions),
            "scope": source.scope,
            "language": source.language,
        }
    else:
        source_data = dict(source)
        source_data.setdefault("jurisdictions", [])
    missing: list[str] = []
    if not version_data.get("version_label"):
        missing.append("version_label: 来源没有版本标识")
    if not source_data.get("jurisdictions"):
        missing.append("jurisdictions: 来源没有声明适用法域，适用性无法判断")
    if source_data.get("scope") is None:
        missing.append("scope: 来源没有声明访问范围")
    if version_data.get("effective_from") is None and version_data.get("effective_to") is None:
        missing.append("effective_range: 来源没有声明生效区间")
    return {
        "jurisdictions": source_data.get("jurisdictions") or None,
        "scope": source_data.get("scope"),
        "language": source_data.get("language"),
        "version_label": version_data.get("version_label"),
        "effective_from": version_data.get("effective_from"),
        "effective_to": version_data.get("effective_to"),
        "missing": missing,
    }


__all__ = [
    "DEFAULT_ALLOWED_SCOPES",
    "KnowledgeChunk",
    "KnowledgeError",
    "KnowledgeSource",
    "KnowledgeStatus",
    "KnowledgeVersion",
    "SourceType",
    "TRANSITIONS",
    "applicability",
    "can_transition",
    "parse_chunks",
    "parse_source",
]