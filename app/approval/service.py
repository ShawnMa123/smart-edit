"""Document submission and two-stage approval service (document-submission-approval)."""

from __future__ import annotations

import json
from typing import Any

from app.documents.errors import HostError, HostNotFound
from app.documents.store import HostStore
from app.identity import permissions as perm
from app.identity.authorization import ResourceScope
from app.identity.errors import IdentityError
from app.shared.ports import Principal


class ApprovalService:
    """Owns submission snapshots and the first/second approval state machine."""

    def __init__(
        self,
        store: HostStore,
        authorizer: Any | None,
        ids: Any,
        activity: Any | None = None,
    ) -> None:
        self.store = store
        self.authorizer = authorizer
        self.ids = ids
        self.activity = activity

    # --- helpers ------------------------------------------------------------------------------
    def _require_authorizer(self) -> Any:
        if self.authorizer is None:
            raise HostError(
                409,
                "AUTH_MODE_FAKE",
                "submission and approval require SMART_EDIT_AUTH_MODE=pg",
            )
        return self.authorizer

    def _document(self, document_id: str) -> dict[str, Any]:
        document = self.store.get_document(document_id)
        if not document:
            raise HostNotFound("document not found")
        return document

    def _can(self, principal: Principal, action: str, document: dict[str, Any]) -> bool:
        try:
            self._require_authorizer().authorize(principal, action, document)
        except IdentityError:
            return False
        return True

    def _require(self, principal: Principal, action: str, document: dict[str, Any]) -> None:
        try:
            self._require_authorizer().authorize(principal, action, document)
        except IdentityError as exc:
            raise HostError(exc.status, exc.code, exc.message, exc.detail) from exc

    def _org_id(self, workspace_id: str) -> str | None:
        organization = self._require_authorizer().organization(workspace_id)
        return organization["org_id"] if organization else None

    def _record(
        self,
        *,
        action: str,
        submission: dict[str, Any],
        actor_user_id: str,
        detail: dict[str, Any],
    ) -> None:
        if self.activity is None:
            return
        org_id = self._org_id(submission["workspace_id"])
        if not org_id:
            return
        self.activity.safe_record(
            org_id=org_id,
            department_id=submission.get("department_id"),
            actor_user_id=actor_user_id,
            actor_label=None,
            kind="approval",
            action=action,
            resource_type="approval_request",
            resource_id=submission.get("request_id"),
            detail=detail,
        )

    def _latest_step(self, request_id: str) -> dict[str, Any] | None:
        steps = self.store.list_steps(request_id)
        return steps[-1] if steps else None

    def _summary(self, submission: dict[str, Any], request: dict[str, Any] | None) -> dict[str, Any]:
        step = self._latest_step(request["request_id"]) if request else None
        return {
            "submission_id": submission["submission_id"],
            "document_id": submission["document_id"],
            "revision": int(submission["revision"]),
            "content_sha256": submission["content_sha256"],
            "status": submission["status"],
            "submitted_by": submission["submitted_by"],
            "created_at": submission["created_at"],
            "request_id": submission.get("request_id"),
            "current_stage": (request or {}).get("current_stage"),
            "approval_revision": int((request or {}).get("revision") or 0),
            "latest_comment": (step or {}).get("comment"),
            "latest_decision": (step or {}).get("decision"),
            "latest_actor": (step or {}).get("actor_user_id"),
            "latest_decided_at": (step or {}).get("decided_at"),
        }

    def _detail(self, request: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
        steps = self.store.list_steps(request["request_id"])
        return {
            **self._summary(submission, request),
            "workspace_id": submission["workspace_id"],
            "department_id": submission.get("department_id"),
            "content": json.loads(submission["content_json"]),
            "text": submission["text"],
            "variables": json.loads(submission.get("variables_json") or "{}"),
            "variables_version": int(submission["variables_version"]),
            "steps": steps,
        }

    # --- reads ---------------------------------------------------------------------------------
    def _has_permission(self, principal: Principal, action: str) -> bool:
        authorizer = self._require_authorizer()
        organization = authorizer.organization(principal.workspace_id)
        if not organization:
            return False
        return action in authorizer.authorization.permissions(
            principal,
            ResourceScope(
                org_id=organization["org_id"],
                department_id=principal.department_id,
                workspace_id=principal.workspace_id,
            ),
        )

    def status(self, document_id: str) -> dict[str, Any] | None:
        submission = self.store.latest_submission(document_id)
        if not submission:
            return None
        request = self.store.get_request(submission.get("request_id") or "")
        return self._summary(submission, request)

    # --- commands -----------------------------------------------------------------------------
    def submit(
        self,
        principal: Principal,
        document_id: str,
        payload: dict[str, Any],
        request_id: str = "",
    ) -> dict[str, Any]:
        document = self._document(document_id)
        self._require(principal, perm.APPROVAL_SUBMIT, document)
        draft = self.store.find_draft_by_document(document_id)
        if not draft:
            raise HostNotFound("draft not found")
        result = self.store.create_submission(
            document_id=document_id,
            draft_id=draft["draft_id"],
            submitted_by=principal.user_id,
            lock_id=payload["lock_id"],
            fencing_token=int(payload["fencing_token"]),
            expected_revision=int(payload["expected_revision"]),
            expected_sha256=payload.get("content_sha256"),
            audit_request_id=request_id,
        )
        submission = result["submission"]
        request = result["request"]
        self._record(
            action="submission.created",
            submission=submission,
            actor_user_id=principal.user_id,
            detail={
                "submission_id": submission["submission_id"],
                "request_id": request["request_id"],
                "revision": int(submission["revision"]),
                "status": "pending_first",
            },
        )
        return {"submission": self._summary(submission, request), "request": request}

    def submissions(self, principal: Principal, document_id: str) -> list[dict[str, Any]]:
        document = self._document(document_id)
        try:
            self._require_authorizer().authorize(principal, perm.DOCUMENT_READ, document)
        except IdentityError as exc:
            raise HostError(exc.status, exc.code, exc.message, exc.detail) from exc
        rows = self.store.list_submissions(document_id)
        own = [row for row in rows if row["submitted_by"] == principal.user_id]
        if not own and not (
            self._can(principal, perm.APPROVAL_FIRST, document)
            or self._can(principal, perm.APPROVAL_SECOND, document)
        ):
            raise HostError(403, "FORBIDDEN", "you do not have permission for these submissions")
        visible = own or rows
        return [
            self._summary(row, self.store.get_request(row.get("request_id") or ""))
            for row in visible
        ]

    def inbox(self, principal: Principal, stage: str | None = None) -> list[dict[str, Any]]:
        authorizer = self._require_authorizer()
        organization = authorizer.organization(principal.workspace_id)
        if not organization:
            raise HostError(403, "FORBIDDEN", "you do not have permission for approvals")
        if stage not in (None, "first", "second"):
            raise HostError(422, "invalid_stage", "stage must be first or second")
        if stage == "first":
            if not self._has_permission(principal, perm.APPROVAL_FIRST):
                raise HostError(403, "FORBIDDEN", "you do not have permission for first approval")
            statuses = ("pending_first",)
        elif stage == "second":
            if not self._has_permission(principal, perm.APPROVAL_SECOND):
                raise HostError(403, "FORBIDDEN", "you do not have permission for second approval")
            statuses = ("pending_second",)
        else:
            if not (
                self._has_permission(principal, perm.APPROVAL_FIRST)
                or self._has_permission(principal, perm.APPROVAL_SECOND)
            ):
                raise HostError(403, "FORBIDDEN", "you do not have permission for approvals")
            statuses = ("pending_first", "pending_second")
        rows = self.store.list_pending_approvals(principal.workspace_id or "", statuses)
        visible: list[dict[str, Any]] = []
        for row in rows:
            document = self.store.get_document(row["document_id"])
            if not document:
                continue
            action = perm.APPROVAL_FIRST if row["status"] == "pending_first" else perm.APPROVAL_SECOND
            if not self._can(principal, action, document):
                continue
            submission = self.store.get_submission(row["submission_id"]) or {}
            visible.append(
                {
                    **self._summary(submission, row),
                    "title": row.get("title"),
                    "snapshot_revision": row.get("snapshot_revision"),
                    "snapshot_sha256": row.get("snapshot_sha256"),
                    "department_id": row.get("department_id"),
                }
            )
        return visible

    def detail(self, principal: Principal, request_id: str) -> dict[str, Any]:
        request = self.store.get_request(request_id)
        if not request:
            raise HostNotFound("approval request not found")
        submission = self.store.get_submission(request["submission_id"]) or {}
        document = self.store.get_document(request["document_id"])
        if not document or not submission:
            raise HostNotFound("approval request not found")
        allowed = request["submitted_by"] == principal.user_id or self._can(
            principal, perm.APPROVAL_FIRST, document
        ) or self._can(principal, perm.APPROVAL_SECOND, document)
        if not allowed:
            raise HostError(403, "FORBIDDEN", "you do not have permission for this approval")
        detail = self._detail(request, submission)
        detail["title"] = document.get("title")
        detail["can_decide"] = (
            request["status"] == f"pending_{request['current_stage']}"
            and request["submitted_by"] != principal.user_id
            and self._can(
                principal,
                perm.APPROVAL_FIRST
                if request["current_stage"] == "first"
                else perm.APPROVAL_SECOND,
                document,
            )
        )
        return detail

    def decide(
        self,
        principal: Principal,
        request_id: str,
        payload: dict[str, Any],
        audit_request_id: str = "",
    ) -> dict[str, Any]:
        request = self.store.get_request(request_id)
        if not request:
            raise HostNotFound("approval request not found")
        submission = self.store.get_submission(request["submission_id"]) or {}
        document = self.store.get_document(request["document_id"])
        if not document or not submission:
            raise HostNotFound("approval request not found")
        stage = request["current_stage"]
        action = perm.APPROVAL_FIRST if stage == "first" else perm.APPROVAL_SECOND
        other = perm.APPROVAL_SECOND if stage == "first" else perm.APPROVAL_FIRST
        if not self._can(principal, action, document):
            if self._can(principal, other, document):
                raise HostError(
                    409,
                    "wrong_stage",
                    "this decision does not belong to the current approval stage",
                    {"stage": stage},
                )
            self._require(principal, action, document)
        if principal.user_id == request["submitted_by"]:
            raise HostError(403, "self_approval", "you cannot decide your own submission")
        decision = payload["decision"]
        result = self.store.decide_approval(
            request_id=request_id,
            stage=stage,
            decision=decision,
            actor_user_id=principal.user_id,
            comment=payload.get("comment"),
            expected_revision=int(payload["expected_revision"]),
            audit_request_id=audit_request_id,
        )
        event = {
            "approve": f"approval.{stage}.approved",
            "return": "approval.returned",
            "reject": "approval.rejected",
        }[decision]
        self._record(
            action=event,
            submission={**submission, "request_id": request_id},
            actor_user_id=principal.user_id,
            detail={
                "request_id": request_id,
                "submission_id": submission["submission_id"],
                "stage": stage,
                "decision": decision,
                "status": result["request"]["status"],
            },
        )
        return self.detail(principal, request_id)