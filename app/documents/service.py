"""Use-cases for the local document host (drafts, checkpoints, locks)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.documents.errors import HostError, HostNotFound, LockConflict
from app.documents.schemas import DocumentCreate, DraftSave, Heartbeat, LockCreate
from app.documents.store import HostStore
from app.identity.errors import IdentityError
from app.shared.ports import IdsPort, Principal


class DocumentService:
    def __init__(
        self,
        store: HostStore,
        identity: Any,
        clock: Any,
        ids: IdsPort,
        authorizer: Any | None = None,
        activity: Any | None = None,
    ) -> None:
        self.store = store
        self.identity = identity
        self.clock = clock
        self.ids = ids
        # PG mode only: document scope lives in the database, never in the request (design D5).
        self.authorizer = authorizer
        self.activity = activity

    def _org_id(self, principal: Principal) -> str | None:
        if principal.org_id:
            return principal.org_id
        if self.authorizer is not None:
            organization = self.authorizer.organization(principal.workspace_id)
            return organization["org_id"] if organization else None
        return None

    def _record(
        self,
        principal: Principal,
        action: str,
        document_id: str,
        department_id: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if self.activity is None:
            return
        org_id = self._org_id(principal)
        if not org_id:
            return
        self.activity.safe_record(
            org_id=org_id,
            department_id=department_id,
            actor_user_id=principal.user_id,
            actor_label=None,
            kind="document",
            action=action,
            resource_type="document",
            resource_id=document_id,
            detail=detail,
        )

    def principal(self, request) -> Principal:
        return self.identity.resolve(request)

    # --- views ---------------------------------------------------------------------------------
    def _require_capability(self, principal: Principal, capability: str) -> None:
        if not principal.has(capability):
            raise HostError(403, "capability_denied", f"the principal lacks {capability}")

    def _draft_view(self, draft: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
        submission = self.store.latest_submission(draft["document_id"])
        request = self.store.get_request(submission["request_id"]) if submission else None
        steps = self.store.list_steps(request["request_id"]) if request else []
        latest = steps[-1] if steps else None
        return {
            "document_id": draft["document_id"],
            "draft_id": draft["draft_id"],
            "title": document.get("title"),
            "revision": int(draft["revision"]),
            "etag": f"draft-{int(draft['revision'])}",
            "content": json.loads(draft["content_json"]),
            "text": draft["text"],
            "content_sha256": draft["text_sha256"],
            "variables": json.loads(draft.get("variables_json") or "{}"),
            "variables_version": int(draft.get("variables_version") or 1),
            "updated_at": draft.get("updated_at"),
            "submission_status": submission["status"] if submission else "draft",
            "submission": (
                {
                    "submission_id": submission["submission_id"],
                    "request_id": submission["request_id"],
                    "status": submission["status"],
                    "revision": int(submission["revision"]),
                    "current_stage": (request or {}).get("current_stage"),
                    "route": (request or {}).get("route") or "bank_first",
                    "approval_revision": int((request or {}).get("revision") or 0),
                    "latest_decision": (latest or {}).get("decision"),
                    "latest_comment": (latest or {}).get("comment"),
                    "latest_actor": (latest or {}).get("actor_user_id"),
                    "latest_decided_at": (latest or {}).get("decided_at"),
                    "created_at": submission["created_at"],
                }
                if submission
                else None
            ),
        }

    def _block_if_submitted(self, document_id: str) -> None:
        submission = self.store.blocking_submission(document_id)
        if submission:
            raise HostError(
                409,
                "submission_pending",
                "this document is under approval and cannot be edited",
                {"status": submission["status"], "request_id": submission["request_id"]},
            )

    def _document(
        self, principal: Principal, document_id: str, action: str = "document.read"
    ) -> dict[str, Any]:
        document = self.store.get_document(document_id)
        if not document:
            raise HostNotFound("document not found")
        if self.authorizer is not None:
            self.authorizer.authorize(principal, action, document)
            return document
        if (
            document["owner_user_id"] != principal.user_id
            or document["workspace_id"] != principal.workspace_id
        ):
            raise HostNotFound("document not found")
        return document

    def _draft(
        self,
        principal: Principal,
        document_id: str,
        draft_id: str,
        action: str = "document.read",
    ) -> tuple[dict, dict]:
        document = self._document(principal, document_id, action)
        draft = self.store.get_draft(draft_id)
        if not draft or draft["document_id"] != document_id:
            raise HostNotFound("draft not found")
        return document, draft

    def view(self, principal: Principal, document_id: str, draft_id: str) -> dict[str, Any]:
        document, draft = self._draft(principal, document_id, draft_id)
        return self._draft_view(draft, document)

    def document_view(self, principal: Principal, document_id: str) -> dict[str, Any]:
        document = self._document(principal, document_id)
        draft = self.store.find_draft_by_document(document_id)
        if not draft:
            raise HostNotFound("draft not found")
        return self._draft_view(draft, document)

    def list_documents(self, principal: Principal, *, limit: int = 100) -> list[dict[str, Any]]:
        """Documents the principal may open, newest first (multi-document entry point)."""
        rows = self.store.list_documents(principal.workspace_id or "", limit=limit)
        visible: list[dict[str, Any]] = []
        for row in rows:
            if self.authorizer is not None:
                try:
                    self.authorizer.authorize(principal, "document.read", row)
                except IdentityError:
                    continue
            elif row["owner_user_id"] != principal.user_id:
                continue
            visible.append(
                {
                    "document_id": row["document_id"],
                    "title": row["title"],
                    "revision": int(row.get("revision") or 0),
                    "draft_id": row.get("draft_id"),
                    "submission_status": row.get("submission_status") or "draft",
                    "updated_at": row.get("draft_updated_at") or row.get("created_at"),
                    "owner_user_id": row["owner_user_id"],
                    "department_id": row.get("department_id"),
                }
            )
        return visible

    # --- commands ------------------------------------------------------------------------------
    def create_document(
        self, principal: Principal, payload: DocumentCreate, request_id: str
    ) -> dict[str, Any]:
        document_id = payload.document_id or self.ids.new("doc")
        if self.store.get_document(document_id):
            raise HostError(409, "document_exists", "a document with this id already exists")
        if self.authorizer is not None:
            self.authorizer.authorize(
                principal,
                "document.create",
                {
                    "workspace_id": principal.workspace_id,
                    "department_id": payload.department_id,
                },
            )
        draft = self.store.create_document(
            workspace_id=principal.workspace_id,
            owner_user_id=principal.user_id,
            title=payload.title,
            content=payload.content,
            text=payload.text,
            variables=payload.variables,
            document_id=document_id,
            created_by=principal.user_id,
            department_id=payload.department_id,
        )
        document = self._document(principal, document_id)
        self._record(
            principal,
            "document created",
            document_id,
            payload.department_id,
            {"title": payload.title},
        )
        return self._draft_view(draft, document)

    def save_draft(
        self,
        principal: Principal,
        document_id: str,
        draft_id: str,
        expected_revision: int,
        payload: DraftSave,
        request_id: str,
    ) -> dict[str, Any]:
        document, _ = self._draft(principal, document_id, draft_id, "document.edit")
        self._block_if_submitted(document_id)
        self._require_capability(principal, "edit")
        self.store.validate_lock(
            draft_id=draft_id,
            lock_id=payload.lock_id,
            owner_user_id=principal.user_id,
            fencing_token=payload.fencing_token,
        )
        draft = self.store.save_draft(
            draft_id=draft_id,
            expected_revision=expected_revision,
            content=payload.content,
            text=payload.text,
            actor=principal.user_id,
            request_id=request_id,
        )
        return self._draft_view(draft, document)

    def update_variables(
        self,
        principal: Principal,
        document_id: str,
        draft_id: str,
        expected_variables_version: int,
        payload: Any,
        request_id: str,
    ) -> dict[str, Any]:
        document, _ = self._draft(principal, document_id, draft_id, "document.edit")
        self._block_if_submitted(document_id)
        self._require_capability(principal, "edit")
        self.store.validate_lock(
            draft_id=draft_id,
            lock_id=payload.lock_id,
            owner_user_id=principal.user_id,
            fencing_token=payload.fencing_token,
        )
        draft = self.store.update_variables(
            draft_id=draft_id,
            expected_variables_version=expected_variables_version,
            variables=payload.variables,
            actor=principal.user_id,
            request_id=request_id,
        )
        return self._draft_view(draft, document)

    def restore_checkpoint(
        self,
        principal: Principal,
        document_id: str,
        draft_id: str,
        checkpoint_id: str,
        expected_revision: int,
        request_id: str,
    ) -> dict[str, Any]:
        document, _ = self._draft(principal, document_id, draft_id, "document.edit")
        self._block_if_submitted(document_id)
        draft = self.store.restore_checkpoint(
            draft_id=draft_id,
            checkpoint_id=checkpoint_id,
            expected_revision=expected_revision,
            actor=principal.user_id,
            request_id=request_id,
        )
        return self._draft_view(draft, document)

    def acquire_lock(
        self, principal: Principal, document_id: str, draft_id: str, payload: LockCreate
    ) -> dict[str, Any]:
        document, _ = self._draft(principal, document_id, draft_id, "document.lock")
        self._block_if_submitted(document_id)
        lock = self.store.acquire_lock(
            draft_id=draft_id,
            owner_user_id=principal.user_id,
            session_id=payload.session_id,
            lease_seconds=payload.lease_seconds,
        )
        self._record(
            principal, "document locked", document_id, document.get("department_id")
        )
        return lock

    def heartbeat(
        self, principal: Principal, document_id: str, lock_id: str, payload: Heartbeat
    ) -> dict[str, Any]:
        lock = self.store.one("SELECT * FROM document_locks WHERE lock_id = ?", (lock_id,))
        if not lock:
            raise HostNotFound("lock not found")
        self._draft(principal, document_id, lock["draft_id"], "document.lock")
        return self.store.heartbeat_lock(
            lock_id=lock_id, owner_user_id=principal.user_id, lease_seconds=payload.lease_seconds
        )

    def lock_status(
        self, principal: Principal, document_id: str, draft_id: str
    ) -> dict[str, Any]:
        """Read the active lock without taking it (document.read is enough)."""
        self._draft(principal, document_id, draft_id, "document.read")
        return {"lock": self.store.active_lock(draft_id)}

    def release(
        self, principal: Principal, document_id: str, lock_id: str, *, stale: bool = False
    ) -> dict[str, Any]:
        lock = self.store.one("SELECT * FROM document_locks WHERE lock_id = ?", (lock_id,))
        if not lock:
            raise HostNotFound("lock not found")
        document, _ = self._draft(principal, document_id, lock["draft_id"], "document.lock")
        if stale:
            lease = datetime.fromisoformat(str(lock["lease_until"]))
            if lease.tzinfo is None:
                lease = lease.replace(tzinfo=timezone.utc)
            if lease > datetime.now(timezone.utc):
                raise LockConflict(
                    "the lock is still active; release it from the window that holds it"
                )
            released = self.store.force_release_lock(lock_id=lock_id)
            self._record(
                principal,
                "stale lock released",
                document_id,
                document.get("department_id"),
                {"lock_id": lock_id, "owner_user_id": lock["owner_user_id"]},
            )
            return released
        return self.store.release_lock(lock_id=lock_id, owner_user_id=principal.user_id)


__all__ = ["DocumentService"]