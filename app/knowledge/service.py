"""Minimal knowledge import/review/publish/withdraw service (task 2.3).

This is the `KnowledgeAdminPort` implementation for A. It only orchestrates repository calls and
state rules: the version is `processing` while chunks are written, becomes `pending_review` only
when every chunk exists, and is published by a reviewer who is not the submitter.
"""

from __future__ import annotations

from typing import Any

from app.knowledge.models import (
    KnowledgeError,
    can_transition,
    parse_chunks,
    parse_source,
)


class KnowledgeService:
    def __init__(self, store) -> None:
        self.store = store

    # --- import -------------------------------------------------------------------------------
    def import_document(self, payload: dict[str, Any], *, submitted_by: str) -> dict[str, Any]:
        """Import one source version. A failure never publishes a partial version."""
        source = parse_source(payload.get("source") or {})
        chunks = parse_chunks(list(payload.get("chunks") or []))
        title = str(payload.get("title") or "").strip()
        version_label = str(payload.get("version_label") or "").strip()
        if not title or not version_label:
            raise KnowledgeError("title and version_label are required")
        version_id = str(
            payload.get("version_id") or f"KV-{source.source_id}-{version_label}"
        ).strip()
        existing = self.store.get_knowledge_version(version_id)
        if existing:
            raise KnowledgeError(f"version {version_id!r} already exists")

        self.store.create_knowledge_source(
            source_id=source.source_id,
            source_type=source.source_type,
            publisher=source.publisher,
            language=source.language,
            scope=source.scope,
            organization_id=source.organization_id,
            license_reference=source.license_reference,
            synthetic=source.synthetic,
            jurisdictions=list(source.jurisdictions),
        )
        self.store.create_knowledge_version(
            version_id=version_id,
            source_id=source.source_id,
            title=title,
            version_label=version_label,
            effective_from=payload.get("effective_from"),
            effective_to=payload.get("effective_to"),
            submitted_by=submitted_by,
        )
        # `add_knowledge_chunks` is transactional: a bad chunk leaves the version in `processing`,
        # which is not retrievable, so a partial import can never be mistaken for published content.
        self.store.add_knowledge_chunks(
            version_id,
            source.source_id,
            [
                {
                    "chunk_id": chunk.chunk_id,
                    "section": chunk.section,
                    "page": chunk.page,
                    "title_path": chunk.title_path,
                    "text": chunk.text,
                    "locator": chunk.locator,
                }
                for chunk in chunks
            ],
        )
        return self.store.mark_pending_review(version_id)

    # --- review / publish ---------------------------------------------------------------------
    def review(self, version_id: str, decision: str, reviewer: str, reason: str) -> dict[str, Any]:
        version = self.store.get_knowledge_version(version_id)
        if not version:
            raise KnowledgeError("unknown knowledge version")
        target = "published" if decision == "publish" else "rejected"
        if not can_transition(version["status"], target):
            raise KnowledgeError(
                f"cannot move {version['status']} to {target}; review needs pending_review"
            )
        if version.get("submitted_by") == reviewer:
            raise KnowledgeError("the submitter cannot review their own version")
        if not reviewer.strip() or not reason.strip():
            raise KnowledgeError("reviewer and reason are required")
        return self.store.review_knowledge_version(version_id, decision, reviewer, reason)

    # --- withdraw -----------------------------------------------------------------------------
    def withdraw(
        self, source_id: str, version_id: str | None, reason: str, actor: str
    ) -> dict[str, Any]:
        if not reason.strip() or not actor.strip():
            raise KnowledgeError("reason and actor are required")
        if version_id:
            try:
                return self.store.withdraw_knowledge_version(source_id, version_id, reason, actor)
            except KeyError as exc:
                raise KnowledgeError("unknown knowledge version") from exc
            except ValueError as exc:
                raise KnowledgeError(str(exc)) from exc
        try:
            versions = self.store.withdraw_knowledge_source(source_id, reason, actor)
        except KeyError as exc:
            raise KnowledgeError("no withdrawable knowledge version") from exc
        return {"source_id": source_id, "withdrawn_versions": [row["version_id"] for row in versions]}

    # --- read helpers (CLI / tests) -----------------------------------------------------------
    def list_versions(self, source_id: str | None = None) -> list[dict[str, Any]]:
        if source_id:
            return self.store.list_knowledge_versions(source_id)
        return self.store.list_knowledge_versions_all()

    def seed(self, **kwargs: Any) -> dict[str, int]:
        from app.knowledge.seed import seed_knowledge

        return seed_knowledge(self.store, **kwargs)


__all__ = ["KnowledgeService"]