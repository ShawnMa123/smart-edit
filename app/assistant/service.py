"""Assistant service: session/run orchestration and the A pipeline (tasks 0–4).

The service depends only on the ports in `ports.py`; the local fakes/SQLite are injected by
`app/api/assistant.py`.
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from pydantic import BaseModel

from app.assistant import audit_events
from app.assistant.adapters import AssistantServices, FakeIdentity
from app.assistant.domain.evidence import detect_conflicts, document_citation_id
from app.assistant.domain.query import QueryPlan, analyze
from app.assistant.domain.state_machine import validate_answer
from app.assistant.egress import EgressDecision, EgressInput, EgressPolicy
from app.assistant.errors import AssistantError
from app.assistant.gateway import DoubaoGateway, ModelGatewayError
from app.assistant.pipeline import (
    WEB_BLOCKED_EN,
    WEB_BLOCKED_ZH,
    WEB_INCOMPLETE_EN,
    WEB_INCOMPLETE_ZH,
    GENERAL_WEB_FALLBACK_EN,
    GENERAL_WEB_FALLBACK_ZH,
    CHAT_STRUCTURE_FAILED,
    CHAT_STRUCTURE_FAILED_EN,
    CHAT_EVIDENCE_FALLBACK,
    CHAT_EVIDENCE_FALLBACK_EN,
    NO_EVIDENCE_ANYWHERE_EN,
    NO_EVIDENCE_ANYWHERE_ZH,
    WEB_EMPTY_EN,
    WEB_EMPTY_ZH,
    WEB_SKIPPED_EN,
    WEB_SKIPPED_ZH,
    WEB_TOOL_NOT_OPEN_EN,
    WEB_TOOL_NOT_OPEN_ZH,
    EvidenceComposer,
    FixtureComposer,
    apply_general_web_policy,
    apply_layer_policy,
    reconcile_answer,
    review_answer,
    review_general_answer,
)
from app.assistant.ports import Composition, EvidenceBundle, EvidenceCandidate, Principal
from app.assistant.retrieval import (
    MAX_EVIDENCE,
    RetrievalError,
    merge_layers,
    web_candidates,
)
from app.assistant.schemas import (
    Answer,
    CancelDecision,
    Capabilities,
    Citation,
    EgressCapability,
    LayerCapability,
    ModelCapability,
    StatuteCapability,
    KnowledgePresets,
    WebCapability,
    WebSummary,
    ErrorBody,
    EvidenceDetail,
    Feedback,
    FeedbackInput,
    Message,
    RetrievalLayer,
    Run,
    RunAccepted,
    RunCreate,
    Session,
    SessionCreate,
    Snapshot,
    SnapshotCreate,
)
from app.assistant.store import SessionBusy
from app.logging_setup import get_logger


WEB_HINTS = {
    "web_unavailable": "This server has no web provider configured.",
    "statute_answered": "RAG returned results, so the web was not searched.",
    "tool_search_disabled": "General web is disabled on this server.",
    "processor_not_approved": "The model provider is not approved for outbound content.",
    "contains_selection": "Remove the document passage, then ask again.",
    "query_too_long": "Shorten the question before retrying.",
    "domain_not_allowed": "The web provider returned a domain outside the approved list.",
    "query_empty_after_redaction": "The question only contained content that may not leave the service.",
    "TOOL_NOT_OPEN": (
        "Web search is not enabled for this model account; activate the web_search plugin in the "
        "Volcengine console."
    ),
    "timeout": "Web search did not complete.",
}


# Statute layer notes (`knowledge-statute-retrieval`). Every failure mode keeps its own wording so
# "we could not check" never reads as "there is no such rule".
STATUTE_TIMEOUT_EN = "Statute search timed out — this answer does not cover statutes."
STATUTE_TIMEOUT_ZH = "法规检索超时，本回答未覆盖法规。"
STATUTE_UPDATING_EN = (
    "The statute corpus is being rebuilt — statutes are not covered in this answer."
)
STATUTE_UPDATING_ZH = "法规库正在重建，本回答未覆盖法规。"
STATUTE_UNAVAILABLE_EN = "Statute search is unavailable — this answer does not cover statutes."
STATUTE_UNAVAILABLE_ZH = "法规检索不可用，本回答未覆盖法规。"
STATUTE_UNCOVERED_EN = "The requested jurisdiction is not covered by the statute corpus."
STATUTE_UNCOVERED_ZH = "所请求的法域未被法规语料覆盖。"
STATUTE_NONE_EN = "No statute matched this question."
STATUTE_NONE_ZH = "没有匹配到相关法规。"
STATUTE_SUPERSEDED_EN = "A cited statute has been superseded; this answer is qualified."
STATUTE_SUPERSEDED_ZH = "引用的法规已被替代，本回答的可信度为有保留。"
STATUTE_LOW_CONFIDENCE_EN = (
    "The statute corpus returned {count} match(es) at low confidence; use them as a reference only."
)
STATUTE_LOW_CONFIDENCE_ZH = "法规语料命中 {count} 条，置信度低，仅供参考。"
STATUTE_PARTIAL_EN = (
    "The statute service returned a partial answer: its cited evidence does not cover every part "
    "of the question."
)
STATUTE_PARTIAL_ZH = "法规服务只给出部分依据，未覆盖问题的全部内容。"
STATUTE_CHAT_UNUSABLE_EN = (
    "The statute service did not return a usable answer; this response does not rely on statutes."
)
STATUTE_CHAT_UNUSABLE_ZH = "法规服务未给出可用答案，本回答未依赖法规。"
STATUTE_CHAT_EVIDENCE_ONLY_EN = (
    "The statute service's own answer was unavailable; this response uses only the statute "
    "excerpts it returned."
)
STATUTE_CHAT_EVIDENCE_ONLY_ZH = "法规服务自身的回答不可用；本回答仅基于其返回的法规条文证据。"
STATUTE_INTERNAL_EN = "This answer relies on internal sources only."
STATUTE_INTERNAL_ZH = "本回答仅基于系统内部来源。"
STATUTE_BLOCKED_EN = (
    "Statute search was not run because outbound screening blocked the question; this answer does "
    "not cover statutes."
)
STATUTE_BLOCKED_ZH = "因出站策略未通过，本次未查询法规，本回答未覆盖法规。"

# RAG runs for rule questions and explicitly scoped questions. `/v1/chat` generates an answer from
# the legal corpus, which would be wrong for product FAQs, so those stay on the local corpus.
STATUTE_INTENTS = frozenset({"trade_rule_explanation"})


@dataclass(frozen=True)
class LocalOutcome:
    """Local-layer result: the evidence plus the layer records this attempt produced."""

    candidates: list[EvidenceCandidate] = field(default_factory=list)
    layers: list[Any] = field(default_factory=list)
    # `/v1/chat` draft (`knowledge-statute-chat`): carried to the composition stage.
    draft: str | None = None
    answer_status: str | None = None
    cited_ids: tuple[str, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)


class AssistantService:
    def __init__(self, services: AssistantServices, *, deadline_seconds: int = 120) -> None:
        self.store = services.store
        self.identity: FakeIdentity = services.identity
        self.logger = get_logger("assistant")
        self.authorization = services.authorization
        self.snapshots = services.snapshots
        self.audit = services.audit
        self.clock = services.clock
        self.retriever = services.retriever
        self.statute = getattr(services, "statute", None)
        self.gateway = services.gateway
        self.fixture_composer = FixtureComposer()
        self.evidence_composer = EvidenceComposer()
        self.ids = services.ids
        self.mode = services.mode
        self.deadline_seconds = deadline_seconds
        settings = getattr(services, "settings", None)
        self.settings = settings
        self.web = getattr(services, "web", None)
        egress = getattr(services, "egress", None)
        configured_policy = getattr(settings, "egress_policy", None) if settings else None
        self.egress = egress if egress is not None else EgressPolicy.load(configured_policy)
        # `user-management`: evidence filtering, permission checks and activity writes.
        self.resource_authorization = getattr(services, "resource_authorization", None)
        self.evidence_authorizer = getattr(services, "evidence_authorizer", None)
        self.activity = getattr(services, "activity", None)
        self.auth_mode = getattr(services, "auth_mode", "fake")

    # --- helpers ----------------------------------------------------------------------------
    def principal(self, request) -> Principal:
        return self.identity.resolve(request)

    def _authorize(self, principal: Principal, workspace_id: str) -> None:
        if self.resource_authorization is not None:
            # PG mode: the session's organisation is checked against a real permission.
            from app.identity.authorization import ResourceScope

            organization = self.resource_authorization.organization(workspace_id)
            if not organization:
                raise AssistantError(404, "RESOURCE_NOT_FOUND", "workspace not found")
            try:
                self.resource_authorization.authorization.authorize(
                    principal,
                    "assistant.use",
                    ResourceScope(
                        org_id=organization["org_id"],
                        department_id=principal.department_id,
                        workspace_id=workspace_id,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - identity errors map onto the assistant contract
                raise AssistantError(
                    int(getattr(exc, "status", 403)),
                    str(getattr(exc, "code", "FORBIDDEN")),
                    str(getattr(exc, "message", "you do not have permission")),
                ) from exc
            return
        try:
            self.authorization.resolve(principal, workspace_id)
        except PermissionError as exc:
            raise AssistantError(404, "RESOURCE_NOT_FOUND", "workspace not found") from exc

    def _filter_evidence(self, principal: Principal, bundle: EvidenceBundle) -> EvidenceBundle:
        """Drop document evidence the user cannot read *before* composition (design D6)."""
        if self.evidence_authorizer is None:
            return bundle
        kept = [
            candidate
            for candidate in bundle.candidates
            if self.evidence_authorizer.can_read(
                principal, getattr(candidate, "document_id", None)
            )
        ]
        if len(kept) != len(bundle.candidates):
            self.logger.info(
                "evidence filtered by document scope: kept=%d dropped=%d",
                len(kept), len(bundle.candidates) - len(kept),
            )
        return EvidenceBundle(kept)

    def _record_run_activity(self, session: dict[str, Any], run_id: str, outcome: str) -> None:
        if self.activity is None or self.resource_authorization is None:
            return
        organization = self.resource_authorization.organization(session["workspace_id"])
        if not organization:
            return
        self.activity.safe_record(
            org_id=organization["org_id"],
            department_id=None,
            actor_user_id=session["owner_user_id"],
            actor_label=None,
            kind="assistant",
            action="assistant run completed",
            resource_type="assistant_run",
            resource_id=run_id,
            detail={"outcome": outcome},
        )

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
            self.logger.info(
                "run queued run=%s session=%s chars=%d web_search=%s selection=%s",
                row["id"], session_id, len(payload.question), payload.web_search,
                bool(payload.selection),
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

    # --- retrieval layers and outbound gate (knowledge-retrieval-layers / egress) -------------
    def _local_layer_name(self) -> str:
        return "rag" if type(self.retriever).__name__.startswith("Rag") else "local"

    def _audit_decision(
        self,
        run_id: str,
        purpose: str,
        decision: EgressDecision,
        *,
        endpoint: str | None = None,
    ) -> None:
        payload = {
            "purpose": purpose,
            "action": decision.action,
            "reason": decision.reason_code,
            "policy_version": decision.policy_version,
            "query_digest": audit_events.query_digest(decision.outbound_query),
        }
        if endpoint:
            payload["endpoint"] = endpoint
        self.audit.append(
            "",
            run_id,
            audit_events.EGRESS_ALLOWED if decision.allowed else audit_events.EGRESS_BLOCKED,
            "",
            payload,
        )

    def _search_decision(
        self, plan: QueryPlan, payload: RunCreate, run_id: str
    ) -> EgressDecision:
        selection = payload.selection.selected_text if payload.selection else None
        decision = self.egress.check(
            EgressInput(
                purpose="search",
                question=payload.question,
                candidate_query=payload.question,
                selection_text=selection,
                entities=tuple(plan.entities),
                provider=type(self.web).__name__ if self.web is not None else None,
                provider_host=getattr(self.web, "host", None),
            )
        )
        self._audit_decision(run_id, "search", decision)
        return decision

    def _statute_decision(
        self, plan: QueryPlan, selection_text: str | None, run_id: str
    ) -> EgressDecision:
        """Screen the user text before it reaches the statute corpus (`knowledge-statute-live` D2).

        The expanded query is built from configuration inside the adapter, so the gate runs on the
        question itself. A missing policy denies: "we did not check" must never look like "no rule".
        """
        if self.egress is None:
            decision = EgressDecision("deny", "policy_unavailable", None, "unset")
        else:
            decision = self.egress.check(
                EgressInput(
                    purpose="statute",
                    question=plan.question,
                    candidate_query=plan.question,
                    selection_text=selection_text,
                    entities=tuple(plan.entities),
                    provider="statute",
                )
            )
        self._audit_decision(run_id, "statute", decision, endpoint="chat")
        return decision

    def _compose(
        self,
        plan: QueryPlan,
        bundle: EvidenceBundle,
        snapshot: dict[str, Any] | None,
        session: dict[str, Any],
        run_id: str,
        payload: RunCreate,
        *,
        draft: str | None = None,
        draft_answer_status: str | None = None,
        draft_cited_ids: tuple[str, ...] = (),
        draft_coverage: dict[str, Any] | None = None,
        chat_evidence: bool = False,
        deadline_at: str | None = None,
    ) -> Composition:
        external = bool(getattr(self.settings, "model", None)) and isinstance(
            self.gateway, DoubaoGateway
        )
        context = {
            "snapshot": snapshot,
            "session": session,
            "conflicts": detect_conflicts(bundle.candidates),
            # `/v1/chat` draft (`knowledge-statute-chat`): the composer may restructure it but
            # must keep citations on the evidence ids.
            "draft": draft,
            "draft_answer_status": draft_answer_status,
            "draft_cited_ids": list(draft_cited_ids),
            "draft_coverage": dict(draft_coverage or {}),
            "chat_evidence": chat_evidence,
        }
        if not external:
            self.logger.info(
                "compose provider=fixture intent=%s evidence=%d",
                plan.intent, len(bundle.candidates),
            )
            return self.gateway.compose(plan, bundle, context)
        if plan.handoff_target or plan.needs_clarification or plan.intent == "out_of_scope":
            # Routing outcomes are control flow, not knowledge: they must not depend on what an
            # external model chooses to say. The deterministic composer owns handoff/clarification
            # and the "no general channel" outcome even when a real provider is configured.
            self.logger.info(
                "compose provider=deterministic intent=%s handoff=%s clarify=%s",
                plan.intent, plan.handoff_target, plan.needs_clarification,
            )
            return self.fixture_composer.compose(plan, bundle, context)
        decision = self.egress.check(
            EgressInput(
                purpose="compose",
                question=payload.question,
                candidate_query=payload.question,
                provider=getattr(self.settings, "model", None),
                provider_approved=bool(getattr(self.settings, "approved_processor", False)),
            )
        )
        self._audit_decision(run_id, "compose", decision)
        if not decision.allowed:
            self.logger.warning(
                "compose blocked run=%s reason=%s", run_id, decision.reason_code
            )
            raise AssistantError(
                403, "EGRESS_BLOCKED", f"model provider not approved: {decision.reason_code}"
            )
        self.logger.info(
            "compose provider=doubao intent=%s evidence=%d draft=%s",
            plan.intent, len(bundle.candidates), "yes" if draft else "no",
        )
        if (draft or chat_evidence) and not self._polish_allowed(deadline_at):
            # Two model calls must fit inside the run deadline; skip the second one if it cannot.
            self.logger.info("compose polish skipped run=%s reason=deadline", run_id)
            return self._evidence_fallback(
                plan,
                bundle,
                context,
                run_id,
                note=(
                    CHAT_STRUCTURE_FAILED_EN
                    if draft and plan.language == "en"
                    else CHAT_STRUCTURE_FAILED
                    if draft
                    else CHAT_EVIDENCE_FALLBACK_EN
                    if plan.language == "en"
                    else CHAT_EVIDENCE_FALLBACK
                ),
                event="chat_polish_skipped",
                metadata={"reason": "deadline"},
            )
        try:
            return self.gateway.compose(plan, bundle, context)
        except ModelGatewayError as exc:
            if not bundle.candidates:
                raise
            if draft is not None:
                # The chat draft exists, so a failed structuring pass must not lose the evidence.
                self.logger.warning(
                    "chat draft could not be structured run=%s code=%s", run_id, exc.code
                )
                return self._evidence_fallback(
                    plan,
                    bundle,
                    context,
                    run_id,
                    note=(
                        CHAT_STRUCTURE_FAILED_EN
                        if plan.language == "en"
                        else CHAT_STRUCTURE_FAILED
                    ),
                    event="chat_structure_failed",
                    metadata={"code": exc.code},
                )
            if chat_evidence:
                # Chat returned evidence but no draft (its own answer was unavailable/unsupported).
                self.logger.warning(
                    "chat evidence could not be structured run=%s code=%s", run_id, exc.code
                )
                return self._evidence_fallback(
                    plan,
                    bundle,
                    context,
                    run_id,
                    note=(
                        CHAT_EVIDENCE_FALLBACK_EN
                        if plan.language == "en"
                        else CHAT_EVIDENCE_FALLBACK
                    ),
                    event="chat_structure_failed",
                    metadata={"code": exc.code},
                )
            # `knowledge-rag-first-fallback`: evidence exists, so a refusal must not reach the user.
            if exc.code != "MODEL_REFUSED_EVIDENCE":
                raise
            self.logger.warning(
                "model refused despite evidence run=%s evidence=%d; quoting evidence",
                run_id, len(bundle.candidates),
            )
            return self._evidence_fallback(
                plan,
                bundle,
                context,
                run_id,
                note=None,
                event="model_refused_evidence",
                metadata={},
            )

    def _evidence_fallback(
        self,
        plan: QueryPlan,
        bundle: EvidenceBundle,
        context: dict[str, Any],
        run_id: str,
        *,
        note: str | None,
        event: str,
        metadata: dict[str, Any],
    ) -> Composition:
        """Quote the evidence when the model cannot produce (or structure) the answer."""
        composition = self.evidence_composer.compose(plan, bundle, context, note=note)
        self.audit.append(
            "", run_id, event, "", {**metadata, "evidence": len(bundle.candidates)}
        )
        return composition

    def _polish_allowed(self, deadline_at: str | None) -> bool:
        if not deadline_at:
            return True
        try:
            remaining = (
                datetime.fromisoformat(deadline_at) - datetime.fromisoformat(self.clock.now())
            ).total_seconds()
        except ValueError:
            return True
        return remaining >= 20

    def _local_layer_budget(self) -> float:
        """Local worker budget: `/v1/chat` needs its own timeout plus retrieval margin."""
        return max(5.0, float(getattr(self.settings, "chat_timeout", 60.0)) + 10.0)

    def _processor_label(self) -> str:
        external = bool(getattr(self.settings, "model", None)) and isinstance(
            self.gateway, DoubaoGateway
        )
        return getattr(self.settings, "processor_label", "fixture") if external else "fixture"

    def _route_for(
        self,
        plan: QueryPlan,
        general_route: bool,
        snapshot: dict[str, Any] | None,
        payload: RunCreate,
        answer: Answer,
    ) -> str:
        """Where this answer came from (design D4). Never derived from the model's own claims."""
        if plan.handoff_target or answer.outcome == "needs_handoff":
            return "handoff"
        if general_route:
            return "general_web"
        # Citations decide the route: a low-confidence statute answer is still a statute answer,
        # and an answer with any citation must never report `none` (`knowledge-rag-first` D5).
        if answer.citations:
            if any(citation.source_type == "statute" for citation in answer.citations):
                return "statute"
            if plan.intent == "document_explanation" and payload.selection and snapshot:
                return "document"
            return "published"
        return "none"

    @staticmethod
    def _web_summary(payload: RunCreate, layers: list[RetrievalLayer]) -> WebSummary:
        """Explain the web layer's outcome (design D5), including the reason and a UI hint."""
        if not payload.web_search:
            return WebSummary(requested=False, status="off")
        layer = next((item for item in layers if item.layer == "web"), None)
        if layer is None:
            return WebSummary(
                requested=True,
                status="skipped",
                reason="web_unavailable",
                hint=WEB_HINTS["web_unavailable"],
            )
        if layer.status == "ok":
            return WebSummary(requested=True, status="ok")
        reason = layer.detail or ("denied" if layer.status == "blocked" else "not_used")
        hint = WEB_HINTS.get(reason) or "Web search was not used for this answer."
        status = "blocked" if layer.status == "blocked" else "failed" if layer.status == "failed" else "skipped"
        return WebSummary(requested=True, status=status, reason=reason, hint=hint)

    def capabilities(self) -> Capabilities:
        """Deployment capability view (assistant-capabilities); no secrets, no user identifiers."""
        settings = self.settings
        model_configured = bool(getattr(settings, "model", None))
        approved = bool(getattr(settings, "approved_processor", False))
        general = (
            bool(getattr(settings, "general_web", False))
            and bool(getattr(self.gateway, "supports_tool_search", False))
            and self.egress is not None
        )
        provider = getattr(settings, "web", "off")
        if provider not in ("off", "fixture", "http"):
            provider = "off"
        policy = self.egress
        statute_view = StatuteCapability(enabled=self.statute is not None)
        if self.statute is not None:
            info = self.statute.health()
            statute_view = StatuteCapability(
                enabled=True,
                reachable=bool(info.get("reachable")),
                documents=info.get("documents"),
                chunks=info.get("chunks"),
                index_version=info.get("index_version"),
                # Passed through untouched: `None` must stay "not measured" all the way to the UI.
                jurisdictions=info.get("jurisdictions"),
            )
        return Capabilities(
            model=ModelCapability(
                configured=model_configured,
                label=getattr(settings, "processor_label", None) if model_configured else None,
                approved_processor=approved,
            ),
            layers=LayerCapability(
                local=True,
                approved_web=self.web is not None,
                general_web=general,
                statute=self.statute is not None,
            ),
            egress=EgressCapability(
                policy_version=str(getattr(policy, "version", "unset")),
                allowed_domains=len(getattr(policy, "allowed_domains", []) or []),
                loaded=bool(getattr(policy, "loaded", False)),
            ),
            web=WebCapability(  # type: ignore[arg-type]
                provider=provider,
                default_on=bool(getattr(settings, "web_default", False)),
            ),
            statute=statute_view,
            presets=KnowledgePresets(
                jurisdictions=getattr(policy, "jurisdictions", None),
                suggested_questions=getattr(policy, "suggested_questions", None),
            ),
        )

    @staticmethod
    def _scope_declared(payload: RunCreate) -> bool:
        """True when the user explicitly narrowed the question (jurisdiction, trade date or rule).

        This is the strongest intent signal we have, so it also decides whether the statute leg is
        allowed to run for questions the keyword classifier sent elsewhere.
        """
        return bool(payload.jurisdiction_codes or payload.applicable_on or payload.rule_version)

    def _should_try_statute(self, plan: QueryPlan, *, scope_declared: bool) -> bool:
        """RAG runs first for every knowledge question, never for a passage-only question.

        The selected passage is the subject of `document_explanation`: answering it from a statute
        corpus would replace what the user pointed at (`knowledge-rag-first-fallback` D1).
        """
        return (
            self.statute is not None
            and plan.handoff_target is None
            and not (plan.intent == "document_explanation" and plan.selection_text)
            and (plan.intent in STATUTE_INTENTS or scope_declared)
        )

    def _general_available(self) -> bool:
        return (
            bool(getattr(self.settings, "general_web", False))
            and bool(getattr(self.gateway, "supports_tool_search", False))
            and self.egress is not None
        )

    @staticmethod
    def _statute_layer(layers: list[RetrievalLayer]) -> RetrievalLayer | None:
        return next((item for item in layers if item.layer == "statute"), None)

    def _rag_returned_nothing(
        self, bundle: EvidenceBundle, layers: list[RetrievalLayer]
    ) -> bool:
        """True only when RAG was attempted this run and produced no evidence text.

        The layer's `hits` is the service's own count and stubs may omit it, so the evidence bundle
        decides: any statute candidate means RAG returned text (`knowledge-rag-first-fallback` D4).
        """
        if self._statute_layer(layers) is None:
            return False
        return not any(
            candidate.source_type == "statute" for candidate in bundle.candidates
        )

    def _should_fallback(
        self,
        plan: QueryPlan,
        payload: RunCreate,
        answer: Answer,
        layers: list[RetrievalLayer],
        bundle: EvidenceBundle,
    ) -> bool:
        """General web runs when RAG returned no text, or when nothing citable exists at all.

        Once RAG returned any text, the web must not run: the answer comes from that evidence and
        its caveats (`knowledge-rag-first-fallback` D4). Without a RAG attempt the old rule stays:
        only an empty, uncited answer falls back.
        """
        if not (
            payload.web_search
            and plan.handoff_target is None
            and plan.intent
            in (
                "trade_rule_explanation",
                "product_faq",
                "document_explanation",
            )
            and self._general_available()
        ):
            return False
        if self._statute_layer(layers) is not None:
            return self._rag_returned_nothing(bundle, layers)
        return answer.outcome in ("insufficient_evidence", "unable_to_assess") and not answer.citations

    def _general_route(self, plan: QueryPlan, payload: RunCreate) -> bool:
        """The general channel: out-of-scope, not a handoff, explicitly enabled, and configured.

        An explicitly scoped question never arrives here: it is relabelled to a rule question before
        routing, so it gets a statute attempt first (design D6).
        """
        return (
            payload.web_search
            and bool(getattr(self.settings, "general_web", False))
            and bool(getattr(self.gateway, "supports_tool_search", False))
            and self.egress is not None
            and plan.intent == "out_of_scope"
            and plan.handoff_target is None
            and not plan.needs_clarification
        )

    def _general_decision(
        self, plan: QueryPlan, payload: RunCreate, run_id: str
    ) -> EgressDecision:
        selection = payload.selection.selected_text if payload.selection else None
        decision = self.egress.check(
            EgressInput(
                purpose="tool_search",
                question=payload.question,
                candidate_query=payload.question,
                selection_text=selection,
                entities=tuple(plan.entities),
                provider=getattr(self.settings, "model", None),
                provider_approved=bool(getattr(self.settings, "approved_processor", False)),
                tool_search_enabled=bool(getattr(self.settings, "general_web", False)),
            )
        )
        self._audit_decision(run_id, "tool_search", decision)
        return decision

    @staticmethod
    def _domain_allowed(host: str, allowed: list[str]) -> bool:
        if not host or not allowed:
            return False
        return any(host == domain or host.endswith(f".{domain}") for domain in allowed)

    def _run_general_web(
        self, plan: QueryPlan, payload: RunCreate, run: dict[str, Any]
    ) -> tuple[Answer, list[RetrievalLayer], EvidenceBundle]:
        """One read-only web_search call, post-hoc domain filtering, capped and labelled answer."""
        run_id = run["id"]
        english = plan.language == "en"
        started = time.monotonic()
        self.logger.info(
            "general_web start run=%s max_keyword=%d", run_id,
            int(getattr(self.settings, "web_search_max_keyword", 3)),
        )

        decision = self._general_decision(plan, payload, run_id)
        if not decision.allowed:
            self.logger.warning(
                "general_web blocked run=%s reason=%s", run_id, decision.reason_code
            )
            answer = Answer(
                outcome="unable_to_assess",
                language=plan.language,
                support_level="insufficient",
                limitations=[WEB_BLOCKED_EN if english else WEB_BLOCKED_ZH],
            )
            return (
                answer,
                [RetrievalLayer(layer="web", status="blocked", detail=decision.reason_code)],
                EvidenceBundle([]),
            )

        try:
            result = self.gateway.general_web(
                decision.outbound_query or payload.question,
                max_keyword=int(getattr(self.settings, "web_search_max_keyword", 3)),
                language=plan.language,
            )
        except ModelGatewayError as exc:
            self.logger.error(
                "general_web failed run=%s code=%s duration_ms=%d",
                run_id, exc.code, int((time.monotonic() - started) * 1000),
            )
            self.audit.append(
                "", run_id, audit_events.WEB_SEARCH_FAILED, "",
                {"code": exc.code, "channel": "general_web"},
            )
            limitation = (
                WEB_TOOL_NOT_OPEN_EN
                if english and exc.code == "TOOL_NOT_OPEN"
                else WEB_TOOL_NOT_OPEN_ZH
                if exc.code == "TOOL_NOT_OPEN"
                else WEB_INCOMPLETE_EN
                if english
                else WEB_INCOMPLETE_ZH
            )
            answer = Answer(
                outcome="unable_to_assess",
                language=plan.language,
                support_level="insufficient",
                limitations=[limitation],
            )
            return (
                answer,
                [RetrievalLayer(layer="web", status="failed", detail=exc.code)],
                EvidenceBundle([]),
            )

        retrieved_at = self.clock.now()
        annotations = {
            str(annotation.get("url")): annotation
            for annotation in result.annotations
            if annotation.get("url")
        }
        kept: list[Citation] = []
        candidates: list[EvidenceCandidate] = []
        # `general_web` is the unverified channel: any publicly reachable link is citable, and the
        # unverified label carries the trust signal. Only `approved_web` filters by allowed domain
        # (`general-web-citations`).
        unusable_hosts: list[str] = []
        for citation in result.answer.citations:
            locator = dict(citation.locator or {})
            url = str(locator.get("url") or "")
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in ("http", "https") or not host:
                unusable_hosts.append(host or "<no-link>")
                continue
            annotation = annotations.get(url, {})
            locator.update(
                {
                    "url": url,
                    "domain": host,
                    "retrieved_at": retrieved_at,
                    "annotation_start": annotation.get("start_index"),
                    "annotation_end": annotation.get("end_index"),
                }
            )
            labelled = citation.model_copy(
                update={"source_type": "general_web", "locator": locator}
            )
            kept.append(labelled)
            snippet = str(annotation.get("title") or labelled.title or url)
            candidates.append(
                EvidenceCandidate(
                    citation_id=labelled.id,
                    source_type="general_web",
                    title=labelled.title,
                    source_version=labelled.source_version or retrieved_at,
                    excerpt=snippet[:300],
                    locator=locator,
                    source_text=snippet,
                    chunk_id=labelled.id,
                )
            )

        answer = result.answer.model_copy(update={"citations": kept})
        answer, removed = review_general_answer(answer, {citation.id for citation in kept})
        answer = apply_general_web_policy(
            answer, has_url_citation=bool(kept), language=plan.language
        )
        if unusable_hosts:
            self.audit.append(
                "", run_id, audit_events.WEB_EVIDENCE_DROPPED, "",
                {"channel": "general_web", "hosts": sorted(set(unusable_hosts))},
            )
        if removed:
            self.audit.append(
                "", run_id, "run_review_issues", "",
                {"issues": [{"code": "general_web_claim_removed", "count": removed}]},
            )
        layers = [
            RetrievalLayer(layer="web", status="ok", detail="general_web", retrieved_at=retrieved_at)
        ]
        self.logger.info(
            "general_web done run=%s citations=%d unusable=%d removed=%d outcome=%s duration_ms=%d",
            run_id, len(kept), len(unusable_hosts), removed, answer.outcome,
            int((time.monotonic() - started) * 1000),
        )
        return answer, layers, EvidenceBundle(candidates)

    def _annotate_layers(
        self, answer: Answer, layers: list[RetrievalLayer], payload: RunCreate
    ) -> Answer:
        """State the web layer's outcome; never let a failed search read as 'verified online'."""
        english = answer.language == "en"
        if not payload.web_search:
            # With the fallback off by default no longer true, an empty answer must say *why* it stayed
            # internal — otherwise it reads as "there is nothing to find" (`knowledge-simple-ask`).
            if answer.outcome in ("insufficient_evidence", "unable_to_assess"):
                note = WEB_SKIPPED_EN if english else WEB_SKIPPED_ZH
                return answer.model_copy(
                    update={"limitations": list(dict.fromkeys([*answer.limitations, note]))}
                )
            return answer
        notes: list[str] = []
        for layer in layers:
            if layer.layer != "web":
                continue
            if layer.status == "failed":
                notes.append(WEB_INCOMPLETE_EN if english else WEB_INCOMPLETE_ZH)
            elif layer.status == "blocked":
                notes.append(WEB_BLOCKED_EN if english else WEB_BLOCKED_ZH)
            elif layer.status == "skipped":
                notes.append(WEB_SKIPPED_EN if english else WEB_SKIPPED_ZH)
        if not notes:
            return answer
        deduped = list(dict.fromkeys([*answer.limitations, *notes]))
        return answer.model_copy(update={"limitations": deduped})

    def _annotate_statute(self, answer: Answer, layers: list[Any]) -> Answer:
        """State what the statute layer actually did; a failure must never read as "no such rule".

        Transparency is unconditional (`statute-recall`): if the statute leg ran and was not usable,
        the answer says so **even when the local corpus answered** — otherwise the reader cannot tell
        "we did not look" from "we looked and rejected it".
        """
        layer = next((item for item in layers if item.layer == "statute"), None)
        if layer is None:
            return answer
        english = answer.language == "en"
        detail = layer.detail or ""
        hits = layer.hits if isinstance(layer.hits, int) else None
        notes: list[str] = []
        downgrade = False
        statute_cited = any(
            citation.source_type == "statute" for citation in answer.citations
        )
        if detail in ("unsupported", "unavailable", "error") and statute_cited:
            # The service's own answer was unusable, but its references were used as evidence.
            notes.append(
                STATUTE_CHAT_EVIDENCE_ONLY_EN if english else STATUTE_CHAT_EVIDENCE_ONLY_ZH
            )
        elif detail == "superseded":
            notes.append(STATUTE_SUPERSEDED_EN if english else STATUTE_SUPERSEDED_ZH)
            downgrade = True
        elif layer.status == "blocked":
            notes.append(STATUTE_BLOCKED_EN if english else STATUTE_BLOCKED_ZH)
        elif layer.status == "failed":
            if detail == "corpus_updating":
                notes.append(STATUTE_UPDATING_EN if english else STATUTE_UPDATING_ZH)
            elif detail == "timeout":
                notes.append(STATUTE_TIMEOUT_EN if english else STATUTE_TIMEOUT_ZH)
            else:
                notes.append(STATUTE_UNAVAILABLE_EN if english else STATUTE_UNAVAILABLE_ZH)
        elif detail.startswith("uncovered:"):
            notes.append(STATUTE_UNCOVERED_EN if english else STATUTE_UNCOVERED_ZH)
        elif detail == "zero:no_jurisdiction":
            # A filter excluded everything: that is "not covered", not "no such rule".
            notes.append(STATUTE_UNCOVERED_EN if english else STATUTE_UNCOVERED_ZH)
        elif detail == "degraded:keyword_only":
            notes.append(
                "Statute search ran keyword-only — semantic matching was unavailable."
                if english
                else "法规检索降级为关键词匹配，语义匹配不可用。"
            )
        elif detail == "low_confidence":
            template = STATUTE_LOW_CONFIDENCE_EN if english else STATUTE_LOW_CONFIDENCE_ZH
            notes.append(template.format(count=hits if hits is not None else "some"))
        elif detail == "partial":
            notes.append(STATUTE_PARTIAL_EN if english else STATUTE_PARTIAL_ZH)
        elif detail in ("unsupported", "unavailable", "error"):
            notes.append(STATUTE_CHAT_UNUSABLE_EN if english else STATUTE_CHAT_UNUSABLE_ZH)
        elif detail.startswith("zero:"):
            notes.append(STATUTE_NONE_EN if english else STATUTE_NONE_ZH)
        if notes and answer.citations:
            # The answer exists, but it does not come from statutes — say that explicitly.
            notes.append(STATUTE_INTERNAL_EN if english else STATUTE_INTERNAL_ZH)
        updates: dict[str, Any] = {}
        if notes:
            updates["limitations"] = list(dict.fromkeys([*answer.limitations, *notes]))
        if downgrade and answer.support_level == "strong":
            updates["support_level"] = "qualified"
        return answer.model_copy(update=updates) if updates else answer

    @staticmethod
    def _canonical_citations(answer: Answer, bundle: EvidenceBundle) -> Answer:
        """Citations are server-derived: a model may choose ids, never text, titles or locators.

        Composed answers echo whatever the provider wrote into `locator` (usually `{}`), which would
        strip the jurisdiction / effective range / precision a statute citation is supposed to show.
        Providers also sometimes cite an evidence id in a claim but omit that citation object; the
        server completes it from the bundle instead of failing the run
        (`claim_unknown_citation`).
        """
        by_id = bundle.by_id()
        citations = []
        for citation in answer.citations:
            candidate = by_id.get(citation.id)
            if candidate is None:
                citations.append(citation)
                continue
            citations.append(
                citation.model_copy(
                    update={
                        "source_type": candidate.source_type,
                        "title": candidate.title,
                        "source_version": candidate.source_version,
                        "locator": candidate.locator,
                    }
                )
            )
        present = {citation.id for citation in citations}
        for claim in answer.claims:
            for citation_id in claim.citation_ids:
                if citation_id in present:
                    continue
                candidate = by_id.get(citation_id)
                if candidate is None:
                    # Unknown ids are rejected by the gateway; leave them for the reviewer.
                    continue
                citations.append(Citation(**bundle.citation(candidate)))
                present.add(citation_id)
        return answer.model_copy(update={"citations": citations})

    # --- layer workers (run inside a thread pool) -------------------------------------------
    def _run_local(
        self,
        principal: Principal,
        workspace_id: str,
        plan: QueryPlan,
        applicable_on: str | None,
        scope_declared: bool = False,
        run_id: str = "",
        selection_text: str | None = None,
    ) -> LocalOutcome:
        """`/v1/chat` first for rule questions; the local corpus stays the fallback and the default.

        A chat answer that is not usable (`unsupported/unavailable/error`) is *not* an error: it
        means "no statute evidence", so the caller sees no citations and the existing general-web
        fallback decides what is next. A blocked outbound decision is different again: the request
        is never sent, and the layer says why (`knowledge-statute-live` D2).
        """
        statute = self.statute
        if self._should_try_statute(plan, scope_declared=scope_declared):
            decision = self._statute_decision(plan, selection_text, run_id)
            layers: list[RetrievalLayer] = []
            if not decision.allowed:
                layers.append(
                    RetrievalLayer(layer="statute", status="blocked", detail=decision.reason_code)
                )
                local = list(self.retriever.search(principal, workspace_id, plan, applicable_on))
                layers.append(
                    RetrievalLayer(
                        layer=self._local_layer_name(), status="ok", detail="statute_blocked"
                    )
                )
                return LocalOutcome(local, layers)
            call_plan = plan
            if decision.outbound_query and decision.outbound_query != plan.question:
                # `/v1/chat` builds its retrieval query from the screened question; only the
                # user's text is screened, expansion terms come from configuration.
                call_plan = replace(plan, question=decision.outbound_query)
            outcome = statute.chat_detailed(principal, workspace_id, call_plan, applicable_on)
            status = "failed" if outcome.status == "failed" else "ok"
            # Failures keep their transport reason (`timeout`/`corpus_updating`); successful calls
            # expose the chat `answer_status` (`answered`/`partial`/`unsupported`).
            detail = (
                outcome.reason
                if outcome.status == "failed"
                else (outcome.answer_status or outcome.reason)
            )
            layers = [
                RetrievalLayer(layer="statute", status=status, detail=detail, hits=outcome.hits)
            ]
            # Which status the chat service reported and how many references came back: without
            # this "RAG returned nothing" cannot be verified from the logs.
            self.logger.info(
                "retrieval chat run=%s status=%s answer_status=%s hits=%d",
                run_id, status, detail, outcome.hits,
            )
            if outcome.expansions:
                self.audit.append(
                    "", run_id, "statute_expanded", "",
                    {"expansions": list(outcome.expansions)},
                )
            if outcome.candidates:
                return LocalOutcome(
                    list(outcome.candidates),
                    layers,
                    draft=outcome.draft,
                    answer_status=outcome.answer_status,
                    cited_ids=outcome.cited_ids,
                    coverage=dict(outcome.coverage),
                )
            # Keep the run useful: fall back to the published corpus, but say statutes were not used.
            local = list(self.retriever.search(principal, workspace_id, plan, applicable_on))
            layers.append(
                RetrievalLayer(
                    layer=self._local_layer_name(), status="ok", detail="statute_unavailable"
                )
            )
            return LocalOutcome(
                local,
                layers,
                answer_status=outcome.answer_status,
                coverage=dict(outcome.coverage),
            )
        return LocalOutcome(
            list(self.retriever.search(principal, workspace_id, plan, applicable_on)),
            [RetrievalLayer(layer=self._local_layer_name(), status="ok")],
        )

    def _run_web(self, plan: QueryPlan, decision: EgressDecision):
        pages, retrieved_at = self.web.search(decision.outbound_query or "")
        allowed = getattr(self.egress, "allowed_domains", []) if self.egress is not None else []
        return web_candidates(
            pages,
            set(plan.retrieval_terms),
            allowed_domains=allowed,
            retrieved_at=retrieved_at or None,
        )

    def _retrieve_layers(
        self,
        principal: Principal,
        session: dict[str, Any],
        plan: QueryPlan,
        payload: RunCreate,
        run_id: str,
        web_decision: EgressDecision | None,
    ) -> tuple[EvidenceBundle, list[RetrievalLayer], dict[str, Any]]:
        """Run the local and web layers after the gate, in parallel, with per-layer budgets."""
        local_name = self._local_layer_name()
        layers: list[RetrievalLayer] = []
        local_candidates: list[EvidenceCandidate] = []
        web_found: list[EvidenceCandidate] = []
        local_error: Exception | None = None
        retrieval_meta: dict[str, Any] = {}
        # `/v1/chat` runs a server-side LLM, so the local worker needs a larger budget than the
        # old 5s retrieval allowance (`knowledge-statute-chat` D6).
        local_budget = self._local_layer_budget()
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            local_future = pool.submit(
                self._run_local,
                principal,
                session["workspace_id"],
                plan,
                payload.applicable_on,
                self._scope_declared(payload),
                run_id,
                payload.selection.selected_text if payload.selection else None,
            )
            web_future = None
            if web_decision is not None and web_decision.allowed:
                web_future = pool.submit(self._run_web, plan, web_decision)
            try:
                local_outcome = local_future.result(timeout=local_budget)
                local_candidates = local_outcome.candidates
                layers.extend(local_outcome.layers)
                retrieval_meta = {
                    "draft": local_outcome.draft,
                    "answer_status": local_outcome.answer_status,
                    "cited_ids": local_outcome.cited_ids,
                    "coverage": dict(local_outcome.coverage),
                    # Chat produced evidence even if its own answer was unavailable/unsupported;
                    # the composer must still structure it (and fall back to quotes on failure).
                    "chat_evidence": local_outcome.answer_status is not None
                    and any(
                        candidate.source_type == "statute"
                        for candidate in local_outcome.candidates
                    ),
                }
            except FutureTimeout as exc:
                local_error = exc
                layers.append(RetrievalLayer(layer=local_name, status="failed", detail="timeout"))
            except RetrievalError as exc:
                local_error = exc
                layers.append(RetrievalLayer(layer=local_name, status="failed", detail=exc.code))
            except Exception as exc:  # noqa: BLE001 - one layer failing must not hide the other
                local_error = exc
                layers.append(
                    RetrievalLayer(layer=local_name, status="failed", detail="retrieval_failed")
                )
            if web_future is not None:
                try:
                    outcome = web_future.result(timeout=8)
                    web_found = outcome.candidates
                    layers.append(
                        RetrievalLayer(layer="web", status="ok", retrieved_at=outcome.retrieved_at)
                    )
                    if outcome.dropped:
                        self.audit.append(
                            "", run_id, audit_events.WEB_EVIDENCE_DROPPED, "",
                            {"dropped": outcome.dropped[:10]},
                        )
                except FutureTimeout:
                    layers.append(RetrievalLayer(layer="web", status="failed", detail="timeout"))
                    self.audit.append(
                        "", run_id, audit_events.WEB_SEARCH_FAILED, "", {"code": "timeout"}
                    )
                except RetrievalError as exc:
                    layers.append(RetrievalLayer(layer="web", status="failed", detail=exc.code))
                    self.audit.append(
                        "", run_id, audit_events.WEB_SEARCH_FAILED, "", {"code": exc.code}
                    )
                except Exception:  # noqa: BLE001
                    layers.append(
                        RetrievalLayer(layer="web", status="failed", detail="web_search_failed")
                    )
                    self.audit.append(
                        "", run_id, audit_events.WEB_SEARCH_FAILED, "", {"code": "web_search_failed"}
                    )
            elif web_decision is not None:
                layers.append(
                    RetrievalLayer(layer="web", status="blocked", detail=web_decision.reason_code)
                )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if local_error is not None and not local_candidates and not web_found:
            # A backend failure is not "no evidence": keep the old guarantee and fail the run.
            raise local_error
        bundle = EvidenceBundle(merge_layers(local_candidates, web_found))
        bundle = self._filter_evidence(principal, bundle)
        self.logger.info(
            "retrieval run=%s local=%d web=%d candidates=%d layers=%s",
            run_id, len(local_candidates), len(web_found), len(bundle.candidates),
            ",".join(f"{layer.layer}:{layer.status}" for layer in layers) or "none",
        )
        if local_error is not None:
            self.logger.warning(
                "retrieval local layer failed run=%s error=%s",
                run_id, type(local_error).__name__,
            )
        return bundle, layers, retrieval_meta

    def _standard_answer(
        self,
        principal: Principal,
        session: dict[str, Any],
        plan: QueryPlan,
        payload: RunCreate,
        snapshot: dict[str, Any] | None,
        run: dict[str, Any],
    ) -> tuple[Answer, list[RetrievalLayer], EvidenceBundle, list[dict[str, Any]], list[dict[str, Any]]]:
        """The in-scope path: local/public retrieval, compose, review (unchanged behaviour)."""
        run_id = run["id"]
        layers: list[RetrievalLayer] = []
        web_decision: EgressDecision | None = None
        retrieval_meta: dict[str, Any] = {}
        if payload.web_search:
            if self.web is None:
                layers.append(
                    RetrievalLayer(layer="web", status="skipped", detail="web_unavailable")
                )
                self.logger.info(
                    "web layer skipped run=%s reason=web_unavailable (no approved web provider)",
                    run["id"],
                )
            else:
                web_decision = self._search_decision(plan, payload, run_id)
                if web_decision.allowed:
                    # The stored question is no longer byte-identical to what left the service.
                    self.store.mark_message_redacted(run["user_message_id"])
                else:
                    self.logger.info(
                        "web layer blocked run=%s reason=%s",
                        run["id"], web_decision.reason_code,
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
            bundle = self._filter_evidence(principal, bundle)
            layers.append(RetrievalLayer(layer="local", status="ok", detail="document_snapshot"))
            if web_decision is not None:
                blocked = not web_decision.allowed
                layers.append(
                    RetrievalLayer(
                        layer="web",
                        status="blocked" if blocked else "skipped",
                        detail=web_decision.reason_code if blocked else "document_selection",
                    )
                )
        elif plan.handoff_target or plan.needs_clarification or plan.intent == "out_of_scope":
            bundle = EvidenceBundle([])
            layers.append(RetrievalLayer(layer="local", status="skipped", detail="no_retrieval"))
            if web_decision is not None:
                blocked = not web_decision.allowed
                layers.append(
                    RetrievalLayer(
                        layer="web",
                        status="blocked" if blocked else "skipped",
                        detail=web_decision.reason_code if blocked else "no_retrieval",
                    )
                )
        else:
            bundle, layer_reports, retrieval_meta = self._retrieve_layers(
                principal, session, plan, payload, run_id, web_decision
            )
            layers.extend(layer_reports)

        if plan.capability_help and not bundle.candidates:
            help_source = self.store.get_knowledge_source(plan.help_source_id or "")
            if not help_source:
                raise AssistantError(
                    503,
                    "HELP_SOURCE_UNAVAILABLE",
                    f"help source {plan.help_source_id or 'unknown'} is not loaded",
                )

        conflicts = detect_conflicts(bundle.candidates)
        composition = self._compose(
            plan,
            bundle,
            snapshot,
            session,
            run_id,
            payload,
            draft=retrieval_meta.get("draft"),
            draft_answer_status=retrieval_meta.get("answer_status"),
            draft_cited_ids=tuple(retrieval_meta.get("cited_ids") or ()),
            draft_coverage=retrieval_meta.get("coverage") or {},
            chat_evidence=bool(retrieval_meta.get("chat_evidence")),
            deadline_at=run.get("deadline_at"),
        )
        answer, issues = review_answer(composition.answer, bundle, snapshot)
        answer = self._canonical_citations(answer, bundle)
        answer = apply_layer_policy(answer, plan, bundle)
        annotated = self._annotate_statute(self._annotate_layers(answer, layers, payload), layers)
        coverage_notes = [
            str(note)
            for note in (retrieval_meta.get("coverage") or {}).get("notes") or []
        ]
        if coverage_notes:
            annotated = annotated.model_copy(
                update={
                    "limitations": list(
                        dict.fromkeys([*annotated.limitations, *coverage_notes])
                    )
                }
            )
        answer = annotated.model_copy(
            update={"retrieval": layers, "processor": self._processor_label()}
        )
        return answer, layers, bundle, conflicts, issues

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
        started = time.monotonic()
        self.logger.info("run started run=%s session=%s", run_id, run["session_id"])
        try:
            if datetime.fromisoformat(run["deadline_at"]) < datetime.fromisoformat(self.clock.now()):
                self.store.transition_run(
                    run_id, ("running",), "timed_out", stage="timed_out", finished_at=self.clock.now()
                )
                self.audit.append("", run_id, "run_timed_out", "", {})
                self.logger.warning("run timed out before start run=%s", run_id)
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
            self.logger.info(
                "run plan run=%s intent=%s language=%s web_search=%s",
                run_id, plan.intent, plan.language, payload.web_search,
            )
            # An explicitly scoped question *is* a rule question. Relabelling here (instead of
            # patching every downstream branch) is what lets it retrieve, compose and fall back
            # like any other rule question (`knowledge-scope-inputs` design D6).
            if (
                self._scope_declared(payload)
                and plan.intent == "out_of_scope"
                and plan.handoff_target is None
                and not plan.needs_clarification
            ):
                plan = replace(plan, intent="trade_rule_explanation")
                self.logger.info(
                    "run scope boosted run=%s jurisdictions=%s as_of=%s rule=%s",
                    run_id,
                    payload.jurisdiction_codes,
                    payload.applicable_on,
                    payload.rule_version,
                )

            general_route = self._general_route(plan, payload)
            web_fallback_reason: str | None = None
            if general_route:
                answer, layers, bundle = self._run_general_web(plan, payload, run)
                conflicts: list[dict[str, Any]] = []
                issues: list[dict[str, Any]] = []
            else:
                answer, layers, bundle, conflicts, issues = self._standard_answer(
                    principal, session, plan, payload, snapshot, run
                )
                rag_empty = self._rag_returned_nothing(bundle, layers)
                if self._should_fallback(plan, payload, answer, layers, bundle):
                    self.logger.info(
                        "general_web fallback run=%s reason=%s",
                        run_id, "rag_empty" if rag_empty else "corpus_insufficient",
                    )
                    fallback_answer, fallback_layers, fallback_bundle = self._run_general_web(
                        plan, payload, run
                    )
                    if rag_empty:
                        # The UI needs to say the web was searched *because* RAG was empty,
                        # whether or not the web produced citations.
                        web_fallback_reason = "rag_empty"
                    if fallback_answer.citations:
                        note = (
                            GENERAL_WEB_FALLBACK_EN
                            if plan.language == "en"
                            else GENERAL_WEB_FALLBACK_ZH
                        )
                        answer = fallback_answer.model_copy(
                            update={"limitations": [*fallback_answer.limitations, note]}
                        )
                        # Keep the statute/local report: "RAG failed / returned nothing" must stay
                        # visible even when the web fallback answers.
                        layers = [
                            *fallback_layers,
                            *(item for item in layers if item.layer != "web"),
                        ]
                        bundle = fallback_bundle
                        general_route = True
                        self.logger.info(
                            "general_web fallback used run=%s citations=%d",
                            run_id, len(fallback_answer.citations),
                        )
                    else:
                        # Keep the corpus-level answer, but report why the fallback did not help.
                        stale = {WEB_SKIPPED_EN, WEB_SKIPPED_ZH}
                        english = plan.language == "en"
                        notes = [
                            item for item in answer.limitations if item not in stale
                        ]
                        notes.extend(fallback_answer.limitations)
                        if rag_empty:
                            notes.append(WEB_EMPTY_EN if english else WEB_EMPTY_ZH)
                        if not answer.citations:
                            notes.append(
                                NO_EVIDENCE_ANYWHERE_EN if english else NO_EVIDENCE_ANYWHERE_ZH
                            )
                        answer = answer.model_copy(
                            update={"limitations": list(dict.fromkeys(notes))}
                        )
                        layers = [
                            *fallback_layers,
                            *(item for item in layers if item.layer != "web"),
                        ]
            answer = reconcile_answer(answer)
            web_summary = self._web_summary(payload, layers)
            if (
                web_summary.reason == "web_unavailable"
                and payload.web_search
                and self._statute_layer(layers) is not None
                and not self._rag_returned_nothing(bundle, layers)
            ):
                # RAG answered, so the web was skipped on purpose — not because no provider exists.
                web_summary = web_summary.model_copy(
                    update={
                        "reason": "statute_answered",
                        "hint": WEB_HINTS["statute_answered"],
                    }
                )
            if web_fallback_reason:
                # The UI shows "RAG returned nothing — searched the web" from this marker.
                web_summary = web_summary.model_copy(update={"reason": web_fallback_reason})
            answer = answer.model_copy(
                update={
                    "retrieval": layers,
                    "processor": self._processor_label(),
                    "route": self._route_for(plan, general_route, snapshot, payload, answer),
                    "web": web_summary,
                }
            )
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
                self.logger.warning(
                    "run timed out run=%s duration_ms=%d",
                    run_id, int((time.monotonic() - started) * 1000),
                )
                return

            citations: list[dict[str, Any]] = []
            dependencies: list[dict[str, Any]] = []
            if snapshot:
                dependencies.append({
                    "resource_type": "snapshot", "resource_id": snapshot["id"],
                    "resource_version": snapshot.get("version_label"),
                })
            for citation in answer.citations:
                candidate = bundle.by_id().get(citation.id)
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
                if candidate.source_id and candidate.source_type != "statute":
                    # Statute evidence lives in an external corpus: it cannot be revoked locally, and
                    # its freshness is re-checked by that service on every retrieval (as_of + superseded).
                    dependencies.append({
                        "resource_type": "knowledge_source", "resource_id": candidate.source_id,
                        "resource_version": candidate.version_id,
                    })
            # Publish-time checks: authorization is re-evaluated and every cited knowledge version
            # must still be published. If either changed during the run, nothing is written.
            self._authorize(principal, session["workspace_id"])
            for citation in citations:
                version_id = citation.get("version_id")
                if citation["source_type"] in ("document_snapshot", "statute") or not version_id:
                    # Statute ids are not local knowledge versions; the external corpus owns their state.
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
                        # Who allowed the outbound search this run (`knowledge-simple-ask`).
                        "web_search": payload.web_search,
                        "web_source": payload.web_search_source or "unknown",
                    },
                },
            )
            self.logger.info(
                "run succeeded run=%s outcome=%s support=%s route=%s citations=%d "
                "synthetic=%s duration_ms=%d",
                run_id, answer.outcome, answer.support_level, answer.route, len(citations),
                any(citation["synthetic"] for citation in citations),
                int((time.monotonic() - started) * 1000),
            )
            self._record_run_activity(session, run_id, answer.outcome)
        except AssistantError as exc:
            self.store.fail_run(run_id, exc.code, exc.message, self.clock.now())
            self.audit.append("", run_id, "run_failed", "", {"code": exc.code})
            self.logger.warning(
                "run failed run=%s code=%s message=%s duration_ms=%d",
                run_id, exc.code, exc.message, int((time.monotonic() - started) * 1000),
            )
        except ModelGatewayError as exc:
            # Surface the provider/model failure by its own code instead of a generic one.
            self.store.fail_run(run_id, exc.code, "model provider failed", self.clock.now())
            self.audit.append("", run_id, "run_failed", "", {"code": exc.code})
            self.logger.error(
                "run failed run=%s code=%s provider=doubao duration_ms=%d",
                run_id, exc.code, int((time.monotonic() - started) * 1000),
            )
        except Exception:
            self.store.fail_run(run_id, "ASSISTANT_FAILED", "assistant run failed", self.clock.now())
            self.audit.append("", run_id, "run_failed", "", {"code": "ASSISTANT_FAILED"})
            self.logger.exception("run failed run=%s code=ASSISTANT_FAILED", run_id)

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
            visibility=row.get("visibility") or "visible",
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