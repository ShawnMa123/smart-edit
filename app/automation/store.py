"""Storage facade for automation proposals and application receipts.

The tables live in the host database. This class reuses the host store's connection so proposal
state, draft state, receipts, audit and outbox can share one transaction.
"""

from __future__ import annotations

import json
from typing import Any

from app.automation.schemas import ChangeProposal
from app.documents.errors import HostNotFound
from app.documents.store import HostStore, new_id, now_iso


class AutomationStore:
    def __init__(self, host: HostStore) -> None:
        self.host = host

    def create_proposal(self, proposal: ChangeProposal) -> dict[str, Any]:
        row = {
            "proposal_id": proposal.proposal_id,
            "document_id": proposal.context.document_id,
            "draft_id": proposal.context.draft_id,
            "owner_user_id": "",
            "workspace_id": "",
            "context_json": json.dumps(proposal.context.model_dump(mode="json"), ensure_ascii=False),
            "operations_json": json.dumps(
                [operation.model_dump(mode="json") for operation in proposal.operations],
                ensure_ascii=False,
            ),
            "preview_json": json.dumps(proposal.preview.model_dump(mode="json"), ensure_ascii=False),
            "risk_flags_json": json.dumps(proposal.risk_flags, ensure_ascii=False),
            "review_json": json.dumps(proposal.review_receipt.model_dump(mode="json"), ensure_ascii=False),
            "disposition": proposal.disposition,
            "application_status": proposal.application_status,
            "revision": proposal.revision,
            "expires_at": proposal.expires_at,
            "created_at": now_iso(),
        }
        with self.host.transaction() as conn:
            conn.execute(
                "INSERT INTO automation_proposals VALUES (:proposal_id,:document_id,:draft_id,"
                ":owner_user_id,:workspace_id,:context_json,:operations_json,:preview_json,"
                ":risk_flags_json,:review_json,:disposition,:application_status,:revision,"
                ":expires_at,:created_at)",
                row,
            )
        return self.get_proposal(proposal.proposal_id) or {}

    def set_owner(self, proposal_id: str, owner_user_id: str, workspace_id: str) -> None:
        with self.host.transaction() as conn:
            conn.execute(
                "UPDATE automation_proposals SET owner_user_id=?, workspace_id=? WHERE proposal_id=?",
                (owner_user_id, workspace_id, proposal_id),
            )

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        return self.host.one(
            "SELECT * FROM automation_proposals WHERE proposal_id = ?", (proposal_id,)
        )

    def to_model(self, row: dict[str, Any]) -> ChangeProposal:
        return ChangeProposal(
            proposal_id=row["proposal_id"],
            context=json.loads(row["context_json"]),
            operations=json.loads(row["operations_json"]),
            preview=json.loads(row["preview_json"]),
            risk_flags=json.loads(row["risk_flags_json"] or "[]"),
            review_receipt=json.loads(row["review_json"]),
            expires_at=row["expires_at"],
            disposition=row["disposition"],
            application_status=row["application_status"],
            revision=int(row["revision"]),
        )

    def record_decision(
        self,
        *,
        proposal_id: str,
        decision: str,
        actor: str,
        reason: str | None,
        expected_revision: int,
    ) -> dict[str, Any]:
        stamp = now_iso()
        with self.host.transaction() as conn:
            result = conn.execute(
                "UPDATE automation_proposals SET disposition=?, revision=revision+1"
                " WHERE proposal_id=? AND revision=? AND application_status='not_applied'",
                (decision, proposal_id, expected_revision),
            )
            if result.rowcount != 1:
                raise HostNotFound("proposal not found or no longer open")
            conn.execute(
                "INSERT INTO automation_proposal_events VALUES (?,?,?,?,?,?)",
                (new_id("pevent"), proposal_id, decision, actor, reason, stamp),
            )
        return self.get_proposal(proposal_id) or {}

    def get_application_by_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        return self.host.one(
            "SELECT * FROM automation_applications WHERE proposal_id = ?", (proposal_id,)
        )

    def get_application(self, receipt_id: str) -> dict[str, Any] | None:
        return self.host.one(
            "SELECT * FROM automation_applications WHERE receipt_id = ?", (receipt_id,)
        )

    def list_events(self, proposal_id: str) -> list[dict[str, Any]]:
        return self.host.all(
            "SELECT * FROM automation_proposal_events WHERE proposal_id = ? ORDER BY created_at ASC",
            (proposal_id,),
        )


__all__ = ["AutomationStore"]