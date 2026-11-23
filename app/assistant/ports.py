"""Ports and small data contracts for the assistant (task 0.2 / design D2).

The concrete A implementations live in `adapters.py` (fake/local) and `store.py` (SQLite). C replaces
them with host/PG adapters; the service layer imports only these protocols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.assistant.schemas import Answer, EvidenceDetail, Run, RunCreate
from app.shared.ports import AccessContext, AuditPort, ClockPort, IdsPort, Principal


@dataclass
class EvidenceCandidate:
    """One authorized, current evidence fragment plus everything a citation needs."""

    citation_id: str
    source_type: str
    title: str
    source_version: str
    excerpt: str
    locator: dict[str, Any]
    source_text: str = ""
    source_id: str | None = None
    version_id: str | None = None
    chunk_id: str | None = None
    synthetic: bool = False
    effective_from: str | None = None
    effective_to: str | None = None
    score: float = 0.0
    document_id: str | None = None
    snapshot_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass
class EvidenceBundle:
    candidates: list[EvidenceCandidate] = field(default_factory=list)

    def by_id(self) -> dict[str, EvidenceCandidate]:
        return {candidate.citation_id: candidate for candidate in self.candidates}

    def citation(self, candidate: EvidenceCandidate) -> dict[str, Any]:
        return {
            "id": candidate.citation_id,
            "source_type": candidate.source_type,
            "title": candidate.title,
            "source_version": candidate.source_version,
            "locator": candidate.locator,
        }

    def detail(self, candidate: EvidenceCandidate) -> EvidenceDetail:
        return EvidenceDetail(
            citation_id=candidate.citation_id,
            source_type=candidate.source_type,  # type: ignore[arg-type]
            title=candidate.title,
            source_version=candidate.source_version,
            excerpt=candidate.excerpt,
            locator=candidate.locator,
            effective_from=candidate.effective_from,
            effective_to=candidate.effective_to,
        )


@dataclass
class Composition:
    """Composer output: the answer plus the evidence that backs each citation id."""

    answer: Answer
    details: dict[str, EvidenceCandidate]


class IdentityPort(Protocol):
    def resolve(self, request: Any) -> Principal: ...


class AuthorizationPort(Protocol):
    def resolve(self, principal: Principal, workspace_id: str) -> AccessContext: ...


class SnapshotPort(Protocol):
    def get(self, snapshot_id: str, principal: Principal) -> dict[str, Any] | None: ...


class StorePort(Protocol):
    """The subset the service layer needs; SQLite and PostgreSQL implement the same methods."""

    def latest_snapshot(self, document_id: str) -> dict[str, Any] | None: ...
    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None: ...
    def create_session(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    def list_sessions(self, owner_user_id: str, workspace_id: str) -> list[dict[str, Any]]: ...
    def create_user_message(self, session_id: str, run_id: str, question: str) -> dict[str, Any]: ...
    def create_run(self, session_id: str, user_message_id: str, deadline_at: str) -> dict[str, Any]: ...
    def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    def transition_run(
        self, run_id: str, from_statuses: tuple[str, ...], to_status: str, **fields: Any
    ) -> bool: ...
    def cancel_run(self, run_id: str, cancelled_at: str) -> bool: ...
    def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...
    def get_message(self, message_id: str) -> dict[str, Any] | None: ...
    def get_citation(self, message_id: str, citation_id: str) -> dict[str, Any] | None: ...
    def upsert_feedback(self, **kwargs: Any) -> dict[str, Any]: ...
    def published_chunks(self, applicable_on: str | None = None) -> list[dict[str, Any]]: ...
    def get_knowledge_version(self, version_id: str) -> dict[str, Any] | None: ...
    def commit_answer(self, **kwargs: Any) -> dict[str, Any] | None: ...
    def fail_run(self, run_id: str, code: str, message: str, finished_at: str) -> bool: ...
    def append_audit(self, **kwargs: Any) -> None: ...
    def get_idempotency(self, principal: str, method: str, path: str, key: str) -> dict[str, Any] | None: ...
    def put_idempotency(
        self, principal: str, method: str, path: str, key: str, request_hash: str, response: dict[str, Any]
    ) -> None: ...


class RetrieverPort(Protocol):
    def search(
        self, principal: Principal, workspace_id: str, plan: Any, applicable_on: str | None
    ) -> list[EvidenceCandidate]: ...


class ModelGateway(Protocol):
    def compose(self, plan: Any, bundle: EvidenceBundle, context: dict[str, Any]) -> Composition: ...


class KnowledgeAdminPort(Protocol):
    """Minimal import/review/publish/withdraw seam (A: `app/knowledge/service.py`; C: admin API)."""

    def import_document(self, payload: dict[str, Any], *, submitted_by: str) -> dict[str, Any]: ...
    def review(self, version_id: str, decision: str, reviewer: str, reason: str) -> dict[str, Any]: ...
    def withdraw(self, source_id: str, version_id: str, reason: str, actor: str) -> dict[str, Any]: ...


__all__ = [
    "AccessContext",
    "AuditPort",
    "AuthorizationPort",
    "ClockPort",
    "Composition",
    "EvidenceBundle",
    "EvidenceCandidate",
    "IdentityPort",
    "IdsPort",
    "KnowledgeAdminPort",
    "ModelGateway",
    "Principal",
    "RetrieverPort",
    "Run",
    "RunCreate",
    "SnapshotPort",
    "StorePort",
]