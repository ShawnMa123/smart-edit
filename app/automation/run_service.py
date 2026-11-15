"""Automation run use-cases: async execution, results, cancellation and dependencies."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from app.automation.pipeline import build_rewrite
from app.automation.reviewer import review_proposal
from app.automation.run_schemas import (
    AutomationResult,
    AutomationRun,
    OutcomeDetails,
    RewriteInput,
    RunCreate,
)
from app.automation.store import AutomationStore
from app.documents.errors import HostError, HostNotFound
from app.documents.projection import sha256_text
from app.documents.store import HostStore
from app.shared.ports import Principal

GENERATOR_VERSION = "fixture-v1"
REVIEWER_VERSION = "review-v1"


class AutomationRunService:
    def __init__(
        self,
        host: HostStore,
        store: AutomationStore,
        identity: Any,
        clock: Any,
        ids: Any,
        *,
        deadline_seconds: int = 120,
    ) -> None:
        self.host = host
        self.store = store
        self.identity = identity
        self.clock = clock
        self.ids = ids
        self.deadline_seconds = deadline_seconds

    def principal(self, request) -> Principal:
        return self.identity.resolve(request)

    def _require(self, principal: Principal, capability: str) -> None:
        if not principal.has(capability):
            raise HostError(403, "capability_denied", f"the principal lacks {capability}")

    def _draft(self, principal: Principal, document_id: str, draft_id: str) -> dict[str, Any]:
        document = self.host.get_document(document_id)
        if (
            not document
            or document["owner_user_id"] != principal.user_id
            or document["workspace_id"] != principal.workspace_id
        ):
            raise HostNotFound("document not found")
        draft = self.host.get_draft(draft_id)
        if not draft or draft["document_id"] != document_id:
            raise HostNotFound("draft not found")
        return draft

    def _dependencies(self, draft: dict[str, Any], principal: Principal) -> list[dict[str, Any]]:
        return [
            {"resource_type": "draft_revision", "resource_id": draft["draft_id"],
             "version": str(draft["revision"])},
            {"resource_type": "draft_content_sha256", "resource_id": draft["draft_id"],
             "version": draft["text_sha256"]},
            {"resource_type": "variables_version", "resource_id": draft["draft_id"],
             "version": str(draft["variables_version"])},
            {"resource_type": "authorization", "resource_id": principal.user_id,
             "version": principal.authorization_version},
            {"resource_type": "generator", "resource_id": "fixture", "version": GENERATOR_VERSION},
            {"resource_type": "reviewer", "resource_id": "deterministic", "version": REVIEWER_VERSION},
        ]

    def _run_model(self, row: dict[str, Any]) -> AutomationRun:
        return AutomationRun.model_validate(self.store.run_view(row))

    def _require_run(self, principal: Principal, run_id: str) -> dict[str, Any]:
        row = self.store.get_run(run_id)
        if (
            not row
            or row["owner_user_id"] != principal.user_id
            or row["workspace_id"] != principal.workspace_id
        ):
            raise HostNotFound("run not found")
        return row

    def create(
        self, principal: Principal, payload: RunCreate, idempotency_key: str | None, request_id: str
    ) -> AutomationRun:
        self._require(principal, "read")
        self._require(principal, "use_ai")
        if payload.task_type != "rewrite":
            raise HostError(
                422, "not_implemented", f"task_type {payload.task_type!r} is not implemented"
            )
        rewrite = RewriteInput.model_validate(payload.input)
        if rewrite.intent != "replace_text":
            raise HostError(422, "not_implemented", "only replace_text rewrite is implemented")
        if not idempotency_key:
            raise HostError(400, "invalid_request", "this operation requires an Idempotency-Key")

        draft = self._draft(principal, payload.document_id, payload.draft_id)
        deadline = (
            datetime.fromisoformat(self.clock.now()) + timedelta(seconds=self.deadline_seconds)
        ).isoformat()
        body = payload.model_dump(mode="json")
        request_json = json.dumps(body, sort_keys=True, ensure_ascii=False)
        request_hash = sha256_text(request_json)
        idempotency = {
            "principal": principal.user_id,
            "method": "POST",
            "path": "/automation/runs",
            "key": idempotency_key,
            "request_hash": request_hash,
        }
        try:
            row = self.store.create_run(
                task_type=payload.task_type,
                document_id=payload.document_id,
                draft_id=payload.draft_id,
                owner_user_id=principal.user_id,
                workspace_id=principal.workspace_id,
                deadline_at=deadline,
                request_json=request_json,
                dependencies=self._dependencies(draft, principal),
                idempotency=idempotency,
            )
        except sqlite3.IntegrityError:
            existing = self.host.get_idempotency(
                principal.user_id, "POST", "/automation/runs", idempotency_key
            )
            if not existing or existing["request_hash"] != request_hash:
                raise HostError(
                    409, "idempotency_conflict", "the same key was reused with another request"
                )
            return AutomationRun.model_validate(json.loads(existing["response_json"]))
        self.host.append_audit(
            request_id=request_id,
            event_type="automation_run_created",
            actor=principal.user_id,
            payload={"run_id": row["run_id"], "task_type": payload.task_type},
        )
        return self._run_model(row)

    def get(self, principal: Principal, run_id: str) -> AutomationRun:
        self._require(principal, "read")
        return self._run_model(self._require_run(principal, run_id))

    def list(self, principal: Principal, document_id: str) -> list[AutomationRun]:
        self._require(principal, "read")
        rows = self.store.list_runs(
            document_id=document_id,
            owner_user_id=principal.user_id,
            workspace_id=principal.workspace_id,
        )
        return [self._run_model(row) for row in rows]

    def cancel(
        self, principal: Principal, run_id: str, expected_revision: int, reason: str | None
    ) -> AutomationRun:
        self._require(principal, "read")
        row = self._require_run(principal, run_id)
        if int(row["revision"]) != expected_revision:
            raise HostError(412, "version_mismatch", "the run revision moved")
        if not self.store.cancel_run(run_id, reason=reason):
            current = self.store.get_run(run_id) or row
            return self._run_model(current)
        return self._run_model(self.store.get_run(run_id) or row)

    def result(self, principal: Principal, result_id: str) -> AutomationResult:
        self._require(principal, "read")
        row = self.store.get_result(result_id)
        if not row:
            raise HostNotFound("result not found")
        self._require_run(principal, row["run_id"])
        return AutomationResult.model_validate(self.store.result_view(row))

    def _context_stale(self, run: dict[str, Any], draft: dict[str, Any]) -> bool:
        for dependency in self.store.list_dependencies("run", run["run_id"]):
            kind = dependency["resource_type"]
            version = dependency.get("version")
            if kind == "draft_revision" and str(draft["revision"]) != str(version):
                return True
            if kind == "draft_content_sha256" and draft["text_sha256"] != version:
                return True
            if kind == "variables_version" and str(draft["variables_version"]) != str(version):
                return True
        return False

    def execute(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if not run or run["status"] != "queued":
            return
        if datetime.fromisoformat(run["deadline_at"]) <= datetime.fromisoformat(self.clock.now()):
            self.store.transition_run(run_id, ("queued",), "timed_out", "done", finished_at=self.clock.now())
            return
        if not self.store.transition_run(
            run_id, ("queued",), "running", "context", started_at=self.clock.now()
        ):
            return
        try:
            payload = json.loads(run["request_json"])
            draft = self.host.get_draft(run["draft_id"])
            if not draft:
                raise HostError(409, "stale_context", "the draft no longer exists")
            if self._context_stale(run, draft):
                raise HostError(409, "stale_context", "the draft changed before the run started")
            proposal_id = self.ids.new("prop")
            outcome = build_rewrite(draft, payload["input"], proposal_id=proposal_id)
            dependencies = [
                {
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "version": row.get("version"),
                }
                for row in self.store.list_dependencies("run", run_id)
            ]
            limitations = [
                {
                    "code": "fixture_backed",
                    "message": "deterministic fixture generator; no model or external source verified the content",
                }
            ]
            if outcome.proposal is None:
                self.store.publish_result(
                    run_id=run_id,
                    completion="complete",
                    outcome=outcome.outcome,
                    payload=(outcome.details or OutcomeDetails()).model_dump(mode="json"),
                    limitations=limitations,
                    proposal=None,
                    review=None,
                    dependencies=dependencies,
                    request_id="",
                )
                return

            proposal = outcome.proposal
            self.store.transition_run(run_id, ("running",), "running", "reviewing")
            review = review_proposal(proposal, draft)
            if not review.passed or review.receipt is None:
                details = OutcomeDetails(reason_codes=list(review.issues) or ["review_failed"])
                self.store.publish_result(
                    run_id=run_id,
                    completion="complete",
                    outcome="unable_to_process",
                    payload=details.model_dump(mode="json"),
                    limitations=limitations,
                    proposal=None,
                    review=None,
                    dependencies=dependencies,
                    request_id="",
                )
                return
            proposal.review_receipt = review.receipt
            if datetime.fromisoformat(run["deadline_at"]) <= datetime.fromisoformat(self.clock.now()):
                self.store.transition_run(
                    run_id, ("running",), "timed_out", "done", finished_at=self.clock.now()
                )
                return
            self.store.transition_run(run_id, ("running",), "running", "publishing")
            self.store.publish_result(
                run_id=run_id,
                completion="complete",
                outcome="proposal_ready",
                payload=proposal.model_dump(mode="json"),
                limitations=limitations,
                proposal=proposal,
                review=review.receipt,
                dependencies=dependencies,
                request_id="",
            )
        except HostError as error:
            if error.code != "run_not_running":
                self.store.fail_run(run_id, error.code, error.message)
        except Exception as error:  # noqa: BLE001 - technical failure must be visible
            self.store.fail_run(run_id, "AUTOMATION_FAILED", str(error))


__all__ = ["AutomationRunService"]