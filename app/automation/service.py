"""Automation use-cases: fixture proposal, accept, atomic apply, undo."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.automation.operations import (
    apply_operations,
    build_inverse_operations,
    validate_operations,
)
from app.automation.schemas import (
    ApplyReceipt,
    ApplyRequest,
    ChangeProposal,
    ProposalContext,
    ProposalDecision,
    ProposalPreview,
    ReplaceTextOperation,
    ReviewReceipt,
    UndoRequest,
)
from app.automation.store import AutomationStore
from app.documents.errors import HostError, HostNotFound
from app.documents.projection import sha256_text
from app.documents.store import HostStore, new_id, now_iso
from app.shared.ports import Principal


class AutomationService:
    def __init__(
        self, host: HostStore, store: AutomationStore, identity: Any, clock: Any, ids: Any
    ) -> None:
        self.host = host
        self.store = store
        self.identity = identity
        self.clock = clock
        self.ids = ids

    def principal(self, request) -> Principal:
        return self.identity.resolve(request)

    def _require(self, principal: Principal, capability: str) -> None:
        if not principal.has(capability):
            raise HostError(403, "capability_denied", f"the principal lacks {capability}")

    def _check_dependencies(
        self, proposal: ChangeProposal, draft: dict[str, Any], principal: Principal
    ) -> None:
        dependencies = self.store.list_dependencies("proposal", proposal.proposal_id)
        if not dependencies:
            raise HostError(409, "stale_context", "the proposal has no recorded dependencies")
        for dependency in dependencies:
            kind = dependency["resource_type"]
            version = dependency.get("version")
            if kind == "draft_revision" and str(draft["revision"]) != str(version):
                raise HostError(409, "stale_context", "the draft revision changed")
            if kind == "draft_content_sha256" and draft["text_sha256"] != version:
                raise HostError(409, "stale_context", "the draft content changed")
            if kind == "variables_version" and str(draft["variables_version"]) != str(version):
                raise HostError(409, "stale_context", "the variables changed")
            if kind == "authorization" and principal.authorization_version != version:
                raise HostError(409, "stale_context", "the authorization version changed")
            if kind == "generator" and version != "fixture-v1":
                raise HostError(409, "stale_context", "the generator version changed")
            if kind == "reviewer" and version != "review-v1":
                raise HostError(409, "stale_context", "the reviewer version changed")

    def _check_review(self, proposal: ChangeProposal) -> None:
        review = self.store.get_review(proposal.review_receipt.receipt_id)
        context_hash = json.dumps(proposal.context.model_dump(mode="json"), sort_keys=True)
        if (
            not review
            or review["proposal_id"] != proposal.proposal_id
            or review["context_hash"] != context_hash
            or review["verdict"] != "pass"
        ):
            raise HostError(409, "review_required", "the proposal has no matching passing review")

    # --- helpers -------------------------------------------------------------------------------
    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))

    def _idempotent(
        self, principal: Principal, method: str, path: str, key: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing = self.host.get_idempotency(principal.user_id, method, path, key)
        if not existing:
            return None
        if existing["request_hash"] != self._hash(payload):
            raise HostError(
                409, "idempotency_conflict", "the same idempotency key was reused with another request"
            )
        return json.loads(existing["response_json"])

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

    def _proposal_row(self, principal: Principal, proposal_id: str) -> dict[str, Any]:
        row = self.store.get_proposal(proposal_id)
        if (
            not row
            or row["owner_user_id"] != principal.user_id
            or row["workspace_id"] != principal.workspace_id
        ):
            raise HostNotFound("proposal not found")
        return row

    def _applicability(self, model: ChangeProposal, draft: dict[str, Any] | None) -> str:
        if draft is None:
            return "unavailable"
        try:
            expires = datetime.fromisoformat(model.expires_at)
        except ValueError:
            return "unavailable"
        if expires <= datetime.now(timezone.utc):
            return "expired"
        if model.context.revision != int(draft["revision"]):
            return "stale"
        if model.context.content_sha256 != draft["text_sha256"]:
            return "stale"
        if model.context.variables_version != int(draft["variables_version"]):
            return "stale"
        if model.context.authorization_version != "auth-demo-1":
            return "unavailable"
        return "current"

    def _model(self, row: dict[str, Any]) -> ChangeProposal:
        model = self.store.to_model(row)
        draft = self.host.get_draft(model.context.draft_id)
        model.applicability = self._applicability(model, draft)  # type: ignore[assignment]
        return model

    def _receipt(self, row: dict[str, Any]) -> dict[str, Any]:
        return ApplyReceipt(
            receipt_id=row["receipt_id"],
            proposal_id=row["proposal_id"],
            previous_revision=int(row["previous_revision"]),
            new_revision=int(row["new_revision"]),
            new_checkpoint_id=row["new_checkpoint_id"],
            content_sha256=row["content_sha256"],
            variables_version=int(row["variables_version"]),
            actor_user_id=row["actor_user_id"],
            applied_at=row["applied_at"],
            reversal_of_receipt_id=row.get("reversal_of_receipt_id"),
        ).model_dump()

    # --- commands ------------------------------------------------------------------------------
    def get(self, principal: Principal, proposal_id: str) -> ChangeProposal:
        return self._model(self._proposal_row(principal, proposal_id))

    def get_receipt(self, principal: Principal, receipt_id: str) -> dict[str, Any]:
        receipt = self.store.get_application(receipt_id)
        if not receipt:
            raise HostNotFound("application receipt not found")
        self._proposal_row(principal, receipt["proposal_id"])
        return self._receipt(receipt)

    def decide(
        self,
        principal: Principal,
        proposal_id: str,
        payload: ProposalDecision,
        expected_revision: int,
        request_id: str,
    ) -> ChangeProposal:
        self._proposal_row(principal, proposal_id)
        row = self.store.record_decision(
            proposal_id=proposal_id,
            decision=payload.decision,
            actor=principal.user_id,
            reason=payload.reason,
            expected_revision=expected_revision,
        )
        self.host.append_audit(
            request_id=request_id,
            event_type="proposal_decided",
            actor=principal.user_id,
            payload={"proposal_id": proposal_id, "decision": payload.decision},
        )
        return self._model(row)

    def _require_key(self, key: str | None) -> str:
        if not key:
            raise HostError(400, "invalid_request", "this operation requires an Idempotency-Key")
        return key

    def apply(
        self,
        principal: Principal,
        proposal_id: str,
        payload: ApplyRequest,
        idempotency_key: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        key = self._require_key(idempotency_key)
        path = f"/automation/proposals/{proposal_id}/apply"
        body = payload.model_dump(mode="json")
        cached = self._idempotent(principal, "POST", path, key, body)
        if cached is not None:
            return cached

        row = self._proposal_row(principal, proposal_id)
        self._require(principal, "edit")
        model = self._model(row)
        if model.disposition != "accepted":
            raise HostError(409, "proposal_not_accepted", "accept the proposal before applying it")
        existing = self.store.get_application_by_proposal(proposal_id)
        if existing or model.application_status != "not_applied":
            raise HostError(
                409,
                "already_applied",
                "this proposal already has an application",
                {"existing_receipt_id": (existing or {}).get("receipt_id")},
            )
        if model.applicability != "current":
            raise HostError(
                409,
                "stale_context",
                "the draft head, variables, authorization or expiry changed",
                {"applicability": model.applicability},
            )
        if payload.expected_snapshot_id != model.context.content_sha256:
            raise HostError(409, "stale_context", "expected_snapshot_id does not match the baseline")
        if payload.expected_draft_revision != model.context.revision:
            raise HostError(412, "version_mismatch", "expected_draft_revision does not match the baseline")

        missing = sorted(set(model.risk_flags) - set(payload.acknowledged_risk_codes))
        if missing:
            raise HostError(
                409, "risk_ack_required", "required risks were not acknowledged", {"missing": missing}
            )

        draft = self.host.get_draft(model.context.draft_id)
        if not draft:
            raise HostNotFound("draft not found")
        self._check_review(model)
        self._check_dependencies(model, draft, principal)
        self.host.validate_lock(
            draft_id=draft["draft_id"],
            lock_id=payload.lock_id,
            owner_user_id=principal.user_id,
            fencing_token=payload.fencing_token,
        )
        validate_operations(model, draft)

        updated_doc, new_text = apply_operations(
            json.loads(draft["content_json"]), draft["text"], model.operations
        )
        inverse = build_inverse_operations(draft["text"], new_text, model.operations)
        stamp = now_iso()
        new_revision = int(draft["revision"]) + 1
        new_checkpoint_id = new_id("ckpt")
        receipt_id = new_id("receipt")
        new_sha = sha256_text(new_text)
        new_variables_version = int(draft["variables_version"]) + 1
        receipt = ApplyReceipt(
            receipt_id=receipt_id,
            proposal_id=proposal_id,
            previous_revision=int(draft["revision"]),
            new_revision=new_revision,
            new_checkpoint_id=new_checkpoint_id,
            content_sha256=new_sha,
            variables_version=new_variables_version,
            actor_user_id=principal.user_id,
            applied_at=stamp,
        ).model_dump()

        try:
            with self.host.transaction() as conn:
                current = conn.execute(
                    "SELECT * FROM document_drafts WHERE draft_id = ?", (draft["draft_id"],)
                ).fetchone()
                current = dict(current) if current else {}
                if (
                    current.get("revision") != draft["revision"]
                    or current.get("text_sha256") != draft["text_sha256"]
                    or current.get("variables_json") != draft["variables_json"]
                ):
                    raise HostError(412, "version_mismatch", "the draft moved during apply")
                self.host.validate_lock(
                    draft_id=draft["draft_id"],
                    lock_id=payload.lock_id,
                    owner_user_id=principal.user_id,
                    fencing_token=payload.fencing_token,
                )
                updated = conn.execute(
                    "UPDATE document_drafts SET revision=?, content_json=?, text=?, text_sha256=?,"
                    " variables_version=variables_version+1, updated_at=?"
                    " WHERE draft_id=? AND revision=? AND text_sha256=? AND variables_json=?",
                    (
                        new_revision,
                        json.dumps(updated_doc, ensure_ascii=False),
                        new_text,
                        new_sha,
                        stamp,
                        draft["draft_id"],
                        draft["revision"],
                        draft["text_sha256"],
                        draft["variables_json"],
                    ),
                )
                if updated.rowcount != 1:
                    raise HostError(412, "version_mismatch", "the draft moved during apply")
                conn.execute(
                    "INSERT INTO document_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_checkpoint_id,
                        draft["draft_id"],
                        new_revision,
                        json.dumps(updated_doc, ensure_ascii=False),
                        new_text,
                        new_sha,
                        draft["variables_json"],
                        new_variables_version,
                        principal.user_id,
                        stamp,
                    ),
                )
                consumed = conn.execute(
                    "UPDATE automation_proposals SET application_status='applied', revision=revision+1"
                    " WHERE proposal_id=? AND application_status='not_applied' AND disposition='accepted'",
                    (proposal_id,),
                )
                if consumed.rowcount != 1:
                    raise HostError(409, "already_applied", "the proposal was consumed by another apply")
                conn.execute(
                    "INSERT INTO automation_applications (receipt_id,proposal_id,draft_id,"
                    "actor_user_id,previous_revision,new_revision,new_checkpoint_id,content_sha256,"
                    "variables_version,inverse_operations_json,status,reversal_of_receipt_id,applied_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,'applied',NULL,?)",
                    (
                        receipt_id,
                        proposal_id,
                        draft["draft_id"],
                        principal.user_id,
                        int(draft["revision"]),
                        new_revision,
                        new_checkpoint_id,
                        new_sha,
                        new_variables_version,
                        json.dumps(inverse, ensure_ascii=False),
                        stamp,
                    ),
                )
                self.host._audit(
                    conn,
                    request_id,
                    "proposal_applied",
                    principal.user_id,
                    {
                        "proposal_id": proposal_id,
                        "receipt_id": receipt_id,
                        "previous_revision": int(draft["revision"]),
                        "new_revision": new_revision,
                    },
                )
                self.host._enqueue(
                    conn,
                    "automation.applied",
                    {
                        "proposal_id": proposal_id,
                        "receipt_id": receipt_id,
                        "new_revision": new_revision,
                    },
                )
                self.host.put_idempotency_conn(
                    conn, principal.user_id, "POST", path, key, self._hash(body), receipt
                )
        except sqlite3.IntegrityError:
            existing = self.store.get_application_by_proposal(proposal_id)
            if existing:
                raise HostError(
                    409,
                    "already_applied",
                    "this proposal already has an application",
                    {"existing_receipt_id": existing["receipt_id"]},
                )
            replay = self._idempotent(principal, "POST", path, key, body)
            if replay is not None:
                return replay
            raise
        return receipt

    def undo(
        self,
        principal: Principal,
        receipt_id: str,
        payload: UndoRequest,
        idempotency_key: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        key = self._require_key(idempotency_key)
        path = f"/automation/applications/{receipt_id}/undo"
        body = payload.model_dump(mode="json")
        cached = self._idempotent(principal, "POST", path, key, body)
        if cached is not None:
            return cached

        receipt = self.store.get_application(receipt_id)
        if not receipt:
            raise HostNotFound("application receipt not found")
        proposal_row = self._proposal_row(principal, receipt["proposal_id"])
        self._model(proposal_row)
        if receipt["status"] != "applied":
            raise HostError(409, "undo_conflict", "this application is no longer the current head")
        draft = self.host.get_draft(receipt["draft_id"])
        if not draft:
            raise HostNotFound("draft not found")
        if int(draft["revision"]) != int(receipt["new_revision"]):
            raise HostError(
                409,
                "undo_conflict",
                "the draft changed after this application, so it cannot be undone",
                {
                    "current_revision": int(draft["revision"]),
                    "receipt_new_revision": int(receipt["new_revision"]),
                },
            )
        if payload.expected_draft_revision != int(draft["revision"]):
            raise HostError(412, "version_mismatch", "expected_draft_revision does not match the head")
        self.host.validate_lock(
            draft_id=draft["draft_id"],
            lock_id=payload.lock_id,
            owner_user_id=principal.user_id,
            fencing_token=payload.fencing_token,
        )

        inverse_data = json.loads(receipt["inverse_operations_json"])
        inverse_model = ChangeProposal(
            proposal_id=receipt["proposal_id"],
            context=ProposalContext(
                document_id=draft["document_id"],
                draft_id=draft["draft_id"],
                revision=int(draft["revision"]),
                content_sha256=draft["text_sha256"],
                variables_version=int(draft["variables_version"]),
                authorization_version="auth-demo-1",
            ),
            operations=[ReplaceTextOperation(**item) for item in inverse_data],
            preview=ProposalPreview(before_text=draft["text"], after_text="", summary="undo"),
            risk_flags=[],
            review_receipt=ReviewReceipt(
                receipt_id="review_undo_01",
                verdict="pass",
                validator_version="undo-v1",
            ),
            expires_at=datetime.now(timezone.utc).replace(year=9999).isoformat(),
        )
        validate_operations(inverse_model, draft)
        updated_doc, new_text = apply_operations(
            json.loads(draft["content_json"]), draft["text"], inverse_model.operations
        )

        stamp = now_iso()
        new_revision = int(draft["revision"]) + 1
        new_checkpoint_id = new_id("ckpt")
        reversal_receipt_id = new_id("receipt")
        new_sha = sha256_text(new_text)
        new_variables_version = int(draft["variables_version"]) + 1
        reversal = ApplyReceipt(
            receipt_id=reversal_receipt_id,
            proposal_id=receipt["proposal_id"],
            previous_revision=int(draft["revision"]),
            new_revision=new_revision,
            new_checkpoint_id=new_checkpoint_id,
            content_sha256=new_sha,
            variables_version=new_variables_version,
            actor_user_id=principal.user_id,
            applied_at=stamp,
            reversal_of_receipt_id=receipt_id,
        ).model_dump()

        with self.host.transaction() as conn:
            current = conn.execute(
                "SELECT * FROM document_drafts WHERE draft_id = ?", (draft["draft_id"],)
            ).fetchone()
            current = dict(current) if current else {}
            if current.get("revision") != int(receipt["new_revision"]):
                raise HostError(409, "undo_conflict", "the draft changed during undo")
            self.host.validate_lock(
                draft_id=draft["draft_id"],
                lock_id=payload.lock_id,
                owner_user_id=principal.user_id,
                fencing_token=payload.fencing_token,
            )
            updated = conn.execute(
                "UPDATE document_drafts SET revision=?, content_json=?, text=?, text_sha256=?,"
                " variables_version=variables_version+1, updated_at=?"
                " WHERE draft_id=? AND revision=? AND text_sha256=?",
                (
                    new_revision,
                    json.dumps(updated_doc, ensure_ascii=False),
                    new_text,
                    new_sha,
                    stamp,
                    draft["draft_id"],
                    int(receipt["new_revision"]),
                    draft["text_sha256"],
                ),
            )
            if updated.rowcount != 1:
                raise HostError(409, "undo_conflict", "the draft changed during undo")
            conn.execute(
                "INSERT INTO document_checkpoints VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    new_checkpoint_id,
                    draft["draft_id"],
                    new_revision,
                    json.dumps(updated_doc, ensure_ascii=False),
                    new_text,
                    new_sha,
                    draft["variables_json"],
                    new_variables_version,
                    principal.user_id,
                    stamp,
                ),
            )
            conn.execute(
                "INSERT INTO automation_applications (receipt_id,proposal_id,draft_id,"
                "actor_user_id,previous_revision,new_revision,new_checkpoint_id,content_sha256,"
                "variables_version,inverse_operations_json,status,reversal_of_receipt_id,applied_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,'reversal',?,?)",
                (
                    reversal_receipt_id,
                    receipt["proposal_id"],
                    draft["draft_id"],
                    principal.user_id,
                    int(draft["revision"]),
                    new_revision,
                    new_checkpoint_id,
                    new_sha,
                    new_variables_version,
                    json.dumps(inverse_data, ensure_ascii=False),
                    receipt_id,
                    stamp,
                ),
            )
            conn.execute(
                "UPDATE automation_applications SET status='undone' WHERE receipt_id=?",
                (receipt_id,),
            )
            conn.execute(
                "UPDATE automation_proposals SET application_status='undone', revision=revision+1"
                " WHERE proposal_id=?",
                (receipt["proposal_id"],),
            )
            self.host._audit(
                conn,
                request_id,
                "proposal_undone",
                principal.user_id,
                {
                    "proposal_id": receipt["proposal_id"],
                    "reversal_receipt_id": reversal_receipt_id,
                    "new_revision": new_revision,
                },
            )
            self.host._enqueue(
                conn,
                "automation.undone",
                {"proposal_id": receipt["proposal_id"], "receipt_id": reversal_receipt_id},
            )
            self.host.put_idempotency_conn(
                conn, principal.user_id, "POST", path, key, self._hash(body), reversal
            )
        return reversal


__all__ = ["AutomationService"]