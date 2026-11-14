"""Assistant service: session/run orchestration and the A pipeline (tasks 0–4).

The service depends only on the ports in `ports.py`; the local fakes/SQLite are injected by
`app/api/assistant.py`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Callable

from pydantic import BaseModel

from app.assistant.adapters import AssistantServices, FakeIdentity
from app.assistant.domain.evidence import detect_conflicts, document_citation_id
from app.assistant.domain.query import analyze
from app.assistant.domain.state_machine import validate_answer
from app.assistant.errors import AssistantError
from app.assistant.pipeline import review_answer
from app.assistant.ports import EvidenceBundle, EvidenceCandidate, Principal
from app.assistant.schemas import (
    Answer,
    CancelDecision,
    ErrorBody,
    EvidenceDetail,
    Feedback,
    FeedbackInput,
    Message,
    Run,
    RunAccepted,
    RunCreate,
    Session,
    SessionCreate,
    Snapshot,
    SnapshotCreate,
)
from app.assistant.store import SessionBusy


class AssistantService:
    def __init__(self, services: AssistantServices, *, deadline_seconds: int = 120) -> None:
        self.store = services.store
        self.identity: FakeIdentity = services.identity
        self.authorization = services.authorization
        self.snapshots = services.snapshots
        self.audit = services.audit
        self.clock = services.clock
        self.retriever = services.retriever
        self.gateway = services.gateway
        self.ids = services.ids
        self.mode = services.mode
        self.deadline_seconds = deadline_seconds

    # --- helpers ----------------------------------------------------------------------------
    def principal(self, request) -> Principal:
        return self.identity.resolve(request)

    def _authorize(self, principal: Principal, workspace_id: str) -> None:
        try:
            self.authorization.resolve(principal, workspace_id)
        except PermissionError as exc:
            raise AssistantError(404, "RESOURCE_NOT_FOUND", "workspace not found") from exc

    def _session_for(self, principal: Principal, session_id: str) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        if (
            not session
            or session["owner_user_id"] != principal.user_id
            or session["workspace_id"] != principal.workspace_id
        ):
            raise AssistantError(404, "RESOURCE_NOT_FOUND", "session not found")
        return session

    def _run_for(self, principal: Principal, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        run = self.store.get_run(run_id)
        if not run:
            raise AssistantError(404, "RESOURCE_NOT_FOUND", "run not found")
        session = self._session_for(principal, run["session_id"])
        return run, session

    @staticmethod
    def _hash(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()

    def _idempotent(
        self, *, principal: Principal, method: str, path: str, key: str | None,
        payload: Any, action: Callable[[], BaseModel], model: type[BaseModel],
    ) -> BaseModel:
        if not key:
            raise AssistantError(400, "INVALID_REQUEST", "Idempotency-Key header is required")
        digest = self._hash(payload)
        existing = self.store.get_idempotency(principal.user_id, method, path, key)
        if existing:
            if existing["request_hash"] != digest:
                raise AssistantError(409, "IDEMPOTENCY_CONFLICT", "same key with a different request")
            return model.model_validate_json(existing["response_json"])
        response = action()
        self.store.put_idempotency(
            principal.user_id, method, path, key, digest, response.model_dump(mode="json")
        )
        return response

    def _deadline(self) -> str:
        now = datetime.fromisoformat(self.clock.now())
        return (now + timedelta(seconds=self.deadline_seconds)).isoformat()

    def _session_model(self, row: dict[str, Any], *, context_stale: bool = False) -> Session:
        return Session(
            id=row["id"], workspace_id=row["workspace_id"], owner_user_id=row["owner_user_id"],
            document_id=row.get("document_id"), snapshot_id=row.get("snapshot_id"),
            attachment_ids=json.loads(row.get("attachment_ids_json") or "[]"),
            locale=row["locale"], status=row["status"], context_stale=context_stale,
            created_at=row["created_at"],
        )

    # --- snapshots ----------------------------------------------------------------------------
    def create_snapshot(self, principal: Principal, payload: SnapshotCreate, request_id: str) -> Snapshot:
        self._authorize(principal, principal.workspace_id)
        row = self.store.create_snapshot(
            workspace_id=principal.workspace_id, document_id=payload.document_id, text=payload.text,
            content_sha256=payload.content_sha256, created_by=principal.user_id,
            version_label=payload.version_label,
        )
        self.audit.append(
            request_id, None, "snapshot_registered", principal.user_id,
            {"snapshot_id": row["id"], "document_id": payload.document_id,
             "content_sha256": payload.content_sha256},
        )
        return Snapshot(
            id=row["id"], workspace_id=row["workspace_id"], document_id=row["document_id"],
            content_sha256=row["content_sha256"], version_label=row["version_label"],
            created_by=row["created_by"], created_at=row["created_at"],
        )

    # --- sessions -----------------------------------------------------------------------------
    def create_session(
        self, principal: Principal, payload: SessionCreate, idempotency_key: str | None,
        request_id: str,
    ) -> Session:
        self._authorize(principal, payload.workspace_id)
        if payload.snapshot_id:
            snapshot = self.snapshots.get(payload.snapshot_id, principal)
            if not snapshot:
                raise AssistantError(404, "RESOURCE_NOT_FOUND", "snapshot not found")
            if payload.document_id != snapshot["document_id"]:
                raise AssistantError(400, "INVALID_REQUEST", "document_id does not match snapshot")

        def action() -> Session:
            row = self.store.create_session(
                workspace_id=payload.workspace_id, owner_user_id=principal.user_id,
                document_id=payload.document_id, snapshot_id=payload.snapshot_id,
                attachment_ids=payload.attachment_ids, locale=payload.locale,
            )
            self.audit.append(
                request_id, None, "session_created", principal.user_id, {"session_id": row["id"]}
            )
            return self._session_model(row)

        return self._idempotent(
            principal=principal, method="POST", path="/assistant/sessions",
            key=idempotency_key, payload=payload.model_dump(mode="json"), action=action, model=Session,
        )  # type: ignore[return-value]

    def list_sessions(self, principal: Principal, workspace_id: str) -> list[Session]:
        self._authorize(principal, workspace_id)
        rows = self.store.list_sessions(principal.user_id, workspace_id)
        return [self._session_model(row, context_stale=self._stale(row)) for row in rows]

    def _stale(self, row: dict[str, Any]) -> bool:
        if not row.get("document_id"):
            return False
        latest = self.store.latest_snapshot(row["document_id"])
        return bool(latest and latest["id"] != row.get("snapshot_id"))

    def get_session(self, principal: Principal, session_id: str) -> Session:
        row = self._session_for(principal, session_id)
        return self._session_model(row, context_stale=self._stale(row))

    # --- runs ---------------------------------------------------------------------------------
    def _run_model(self, row: dict[str, Any]) -> Run:
        result = Answer.model_validate_json(row["result_json"]) if row.get("result_json") else None
        error = ErrorBody.model_validate_json(row["error_json"]) if row.get("error_json") else None
        return Run(
            id=row["id"], session_id=row["session_id"], user_message_id=row["user_message_id"],
            status=row["status"], stage=row["stage"], attempt=int(row.get("attempt") or 0),
            created_at=row["created_at"], deadline_at=row["deadline_at"],
            started_at=row.get("started_at"), finished_at=row.get("finished_at"),
            assistant_message_id=row.get("assistant_message_id"), result=result, error=error,
        )

    def create_run(
        self, principal: Principal, session_id: str, payload: RunCreate,
        idempotency_key: str | None, request_id: str,
    ) -> RunAccepted:
        session = self._session_for(principal, session_id)
        self._authorize(principal, session["workspace_id"])
        if payload.selection:
            if not session.get("snapshot_id"):
                raise AssistantError(409, "CONTEXT_NOT_READY", "a selection requires a bound snapshot")
            snapshot = self.snapshots.get(session["snapshot_id"], principal)
            if not snapshot:
                raise AssistantError(409, "CONTEXT_NOT_READY", "the bound snapshot is unavailable")
            start, end = payload.selection.start_offset, payload.selection.end_offset
            if snapshot["text"][start:end] != payload.selection.selected_text:
                raise AssistantError(409, "ANCHOR_MISMATCH", "selection does not match the snapshot text")

        request_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)

        def action() -> RunAccepted:
            run_id = self.ids.new("run")
            message_id = self.ids.new("msg")
            try:
                message = self.store.create_user_message(
                    session_id, run_id, payload.question, message_id=message_id
                )
                row = self.store.create_run(
                    session_id, message["id"], self._deadline(), request_json, run_id=run_id
                )
            except SessionBusy as exc:
                raise AssistantError(409, "SESSION_BUSY", "this session already has an active run") from exc
            self.audit.append(
                request_id, row["id"], "run_created", principal.user_id, {"session_id": session_id}
            )
            return RunAccepted(**self._run_model(row).model_dump(), poll_after_ms=500)

        return self._idempotent(
            principal=principal, method="POST", path=f"/assistant/sessions/{session_id}/runs",
            key=idempotency_key, payload=payload.model_dump(mode="json"), action=action,
            model=RunAccepted,
        )  # type: ignore[return-value]

    def get_run(self, principal: Principal, run_id: str) -> Run:
        run, _ = self._run_for(principal, run_id)
        return self._run_model(run)

    def cancel_run(
        self, principal: Principal, run_id: str, idempotency_key: str | None, request_id: str
    ) -> CancelDecision:
        run, _ = self._run_for(principal, run_id)
        if run["status"] == "cancelled":
            return CancelDecision(
                run_id=run_id, status="cancelled", cancelled_at=run["finished_at"] or self.clock.now()
            )
        if run["status"] not in ("queued", "running"):
            raise AssistantError(409, "RUN_TERMINAL", "this run already reached a terminal state")

        def action() -> CancelDecision:
            stamp = self.clock.now()
            if not self.store.cancel_run(run_id, stamp):
                latest = self.store.get_run(run_id)
                if latest and latest["status"] == "cancelled":
                    return CancelDecision(
                        run_id=run_id, status="cancelled",
                        cancelled_at=latest["finished_at"] or stamp,
                    )
                raise AssistantError(409, "RUN_TERMINAL", "this run already reached a terminal state")
            self.audit.append(
                request_id, run_id, "run_cancelled", principal.user_id, {"session_id": run["session_id"]}
            )
            return CancelDecision(run_id=run_id, status="cancelled", cancelled_at=stamp)

        return self._idempotent(
            principal=principal, method="POST", path=f"/assistant/runs/{run_id}/cancel",
            key=idempotency_key, payload={}, action=action, model=CancelDecision,
        )  # type: ignore[return-value]

    # --- execution ----------------------------------------------------------------------------
    def execute_run(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if not run or run["status"] != "queued":
            return
        stamp = self.clock.now()
        if not self.store.transition_run(
            run_id, ("queued",), "running", stage="resolving_context",
            started_at=stamp, attempt=int(run.get("attempt") or 0) + 1,
        ):
            return
        self.audit.append("", run_id, "run_started", run["session_id"], {})
        try:
            if datetime.fromisoformat(run["deadline_at"]) < datetime.fromisoformat(self.clock.now()):
                self.store.transition_run(
                    run_id, ("running",), "timed_out", stage="timed_out", finished_at=self.clock.now()
                )
                self.audit.append("", run_id, "run_timed_out", "", {})
                return
            session = self.store.get_session(run["session_id"])
            if not session:
                raise AssistantError(410, "SESSION_MISSING", "the bound session no longer exists")
            principal = Principal(session["owner_user_id"], session["workspace_id"])
            snapshot = None
            if session.get("snapshot_id"):
                snapshot = self.store.get_snapshot(session["snapshot_id"])
                if not snapshot:
                    raise AssistantError(409, "CONTEXT_NOT_READY", "the bound snapshot is unavailable")
            payload = RunCreate.model_validate_json(run.get("request_json") or "{}")
            plan = analyze(
                payload.question,
                selection_text=payload.selection.selected_text if payload.selection else None,
                has_snapshot=bool(snapshot), applicable_on=payload.applicable_on,
                jurisdiction_codes=payload.jurisdiction_codes, rule_version=payload.rule_version,
            )

            if plan.intent == "document_explanation" and payload.selection and snapshot:
                selection = payload.selection
                bundle = EvidenceBundle([
                    EvidenceCandidate(
                        citation_id=document_citation_id(
                            snapshot["id"], selection.start_offset, selection.end_offset
                        ),
                        source_type="document_snapshot",
                        title=session.get("document_id") or "document",
                        source_version=snapshot.get("version_label") or snapshot["id"],
                        excerpt=selection.selected_text,
                        locator={"node_id": selection.node_id, "start_offset": selection.start_offset,
                                 "end_offset": selection.end_offset},
                        source_text=snapshot["text"], source_id=snapshot["id"], version_id=snapshot["id"],
                        document_id=session.get("document_id"), snapshot_id=snapshot["id"],
                        start_offset=selection.start_offset, end_offset=selection.end_offset,
                    )
                ])
            elif plan.handoff_target or plan.needs_clarification or plan.intent == "out_of_scope":
                bundle = EvidenceBundle([])
            else:
                bundle = EvidenceBundle(
                    self.retriever.search(principal, session["workspace_id"], plan, payload.applicable_on)
                )

            if plan.capability_help and not bundle.candidates:
                help_source = self.store.get_knowledge_source(plan.help_source_id or "")
                if not help_source:
                    raise AssistantError(
                        503,
                        "HELP_SOURCE_UNAVAILABLE",
                        f"help source {plan.help_source_id or 'unknown'} is not loaded",
                    )

            conflicts = detect_conflicts(bundle.candidates)
            composition = self.gateway.compose(
                plan, bundle, {"snapshot": snapshot, "session": session, "conflicts": conflicts}
            )
            answer, issues = review_answer(composition.answer, bundle, snapshot)
            if issues:
                self.audit.append(
                    "", run_id, "run_review_issues", "",
                    {"issues": issues, "conflict_count": len(conflicts)},
                )
            problems = validate_answer(answer)
            if problems:
                raise AssistantError(500, "REVIEW_FAILED", ";".join(problems))
            if datetime.fromisoformat(run["deadline_at"]) < datetime.fromisoformat(self.clock.now()):
                self.store.transition_run(
                    run_id, ("running",), "timed_out", stage="timed_out", finished_at=self.clock.now()
                )
                self.audit.append("", run_id, "run_timed_out", "", {})
                return

            citations: list[dict[str, Any]] = []
            dependencies: list[dict[str, Any]] = []
            if snapshot:
                dependencies.append({
                    "resource_type": "snapshot", "resource_id": snapshot["id"],
                    "resource_version": snapshot.get("version_label"),
                })
            for citation in answer.citations:
                candidate = composition.details.get(citation.id) or bundle.by_id().get(citation.id)
                if not candidate:
                    continue
                citations.append({
                    "citation_id": citation.id, "source_type": citation.source_type,
                    "title": citation.title, "source_version": citation.source_version,
                    "locator": citation.locator, "excerpt": candidate.excerpt,
                    "source_id": candidate.source_id, "version_id": candidate.version_id,
                    "chunk_id": candidate.chunk_id, "effective_from": candidate.effective_from,
                    "effective_to": candidate.effective_to, "synthetic": candidate.synthetic,
                })
                if candidate.source_id:
                    dependencies.append({
                        "resource_type": "knowledge_source", "resource_id": candidate.source_id,
                        "resource_version": candidate.version_id,
                    })
            # Publish-time checks: authorization is re-evaluated and every cited knowledge version
            # must still be published. If either changed during the run, nothing is written.
            self._authorize(principal, session["workspace_id"])
            for citation in citations:
                version_id = citation.get("version_id")
                if citation["source_type"] == "document_snapshot" or not version_id:
                    continue
                version = self.store.get_knowledge_version(version_id)
                if not version or version["status"] != "published":
                    raise AssistantError(
                        409, "CONTEXT_NOT_READY", "a cited knowledge source is no longer published"
                    )
            self.store.commit_answer(
                run_id=run_id, answer=answer.model_dump(mode="json"), citations=citations,
                dependencies=dependencies, finished_at=self.clock.now(),
                audit={
                    "request_id": "", "event_type": "run_succeeded",
                    "actor": session["owner_user_id"],
                    "payload": {
                        "outcome": answer.outcome, "support_level": answer.support_level,
                        "citation_ids": [citation["citation_id"] for citation in citations],
                        "synthetic": any(citation["synthetic"] for citation in citations),
                    },
                },
            )
        except AssistantError as exc:
            self.store.fail_run(run_id, exc.code, exc.message, self.clock.now())
            self.audit.append("", run_id, "run_failed", "", {"code": exc.code})
        except Exception:
            self.store.fail_run(run_id, "ASSISTANT_FAILED", "assistant run failed", self.clock.now())
            self.audit.append("", run_id, "run_failed", "", {"code": "ASSISTANT_FAILED"})

    # --- history / citations / feedback -------------------------------------------------------
    def _message_view(self, principal: Principal, row: dict[str, Any]) -> Message:
        if row["role"] == "assistant" and row.get("answer_json"):
            answer = Answer.model_validate_json(row["answer_json"])
            redacted = False
            for citation in self.store.list_citations(row["id"]):
                if citation["source_type"] == "document_snapshot":
                    snapshot = self.store.get_snapshot(citation.get("source_id") or "")
                    redacted = redacted or not snapshot or snapshot["created_by"] != principal.user_id
                else:
                    version = self.store.get_knowledge_version(citation.get("version_id") or "")
                    redacted = redacted or not version or version["status"] == "withdrawn"
            if redacted:
                return Message(
                    id=row["id"], session_id=row["session_id"], run_id=row["run_id"],
                    role="assistant", visibility="redacted", answer=None, created_at=row["created_at"],
                )
            return Message(
                id=row["id"], session_id=row["session_id"], run_id=row["run_id"],
                role="assistant", answer=answer, created_at=row["created_at"],
            )
        return Message(
            id=row["id"], session_id=row["session_id"], run_id=row["run_id"], role="user",
            question=row.get("question"), created_at=row["created_at"],
        )

    def list_messages(self, principal: Principal, session_id: str) -> list[Message]:
        self._session_for(principal, session_id)
        return [self._message_view(principal, row) for row in self.store.list_messages(session_id)]

    def citation_detail(self, principal: Principal, message_id: str, citation_id: str) -> EvidenceDetail:
        message = self.store.get_message(message_id)
        if not message:
            raise AssistantError(404, "RESOURCE_NOT_FOUND", "citation not found")
        self._session_for(principal, message["session_id"])
        citation = self.store.get_citation(message_id, citation_id)
        if not citation:
            raise AssistantError(404, "RESOURCE_NOT_FOUND", "citation not found")
        if citation["source_type"] == "document_snapshot":
            snapshot = self.store.get_snapshot(citation.get("source_id") or "")
            if not snapshot or snapshot["created_by"] != principal.user_id:
                raise AssistantError(404, "RESOURCE_NOT_FOUND", "citation not found")
            effective_from = effective_to = None
        else:
            version = self.store.get_knowledge_version(citation.get("version_id") or "")
            if not version or version["status"] == "withdrawn":
                raise AssistantError(404, "RESOURCE_NOT_FOUND", "citation not found")
            effective_from = version.get("effective_from")
            effective_to = version.get("effective_to")
        return EvidenceDetail(
            citation_id=citation_id, source_type=citation["source_type"], title=citation["title"],
            source_version=citation["source_version"], excerpt=citation["excerpt"],
            locator=json.loads(citation.get("locator_json") or "{}"),
            effective_from=effective_from, effective_to=effective_to,
        )

    def feedback(
        self, principal: Principal, message_id: str, payload: FeedbackInput
    ) -> Feedback:
        message = self.store.get_message(message_id)
        if not message:
            raise AssistantError(404, "RESOURCE_NOT_FOUND", "message not found")
        self._session_for(principal, message["session_id"])
        if message["role"] != "assistant":
            raise AssistantError(400, "INVALID_REQUEST", "feedback is only accepted on assistant messages")
        row = self.store.upsert_feedback(
            user_id=principal.user_id, message_id=message_id, rating=payload.rating,
            categories=list(payload.categories), comment=payload.comment,
        )
        return Feedback(
            id=row["id"], message_id=row["message_id"], rating=row["rating"],
            categories=json.loads(row.get("categories_json") or "[]"), comment=row.get("comment"),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )