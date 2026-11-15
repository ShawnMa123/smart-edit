"""Storage facade for automation proposals and application receipts.

The tables live in the host database. This class reuses the host store's connection so proposal
state, draft state, receipts, audit and outbox can share one transaction.
"""

from __future__ import annotations

import json
from typing import Any

from app.automation.schemas import ChangeProposal
from app.documents.errors import HostError, HostNotFound
from app.documents.store import HostStore, new_id, now_iso


class AutomationStore:
    def __init__(self, host: HostStore) -> None:
        self.host = host

    def _proposal_row(
        self, proposal: ChangeProposal, owner_user_id: str = "", workspace_id: str = ""
    ) -> dict[str, Any]:
        return {
            "proposal_id": proposal.proposal_id,
            "document_id": proposal.context.document_id,
            "draft_id": proposal.context.draft_id,
            "owner_user_id": owner_user_id,
            "workspace_id": workspace_id,
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

    def _insert_proposal(
        self, conn, proposal: ChangeProposal, owner_user_id: str, workspace_id: str
    ) -> None:
        conn.execute(
            "INSERT INTO automation_proposals VALUES (:proposal_id,:document_id,:draft_id,"
            ":owner_user_id,:workspace_id,:context_json,:operations_json,:preview_json,"
            ":risk_flags_json,:review_json,:disposition,:application_status,:revision,"
            ":expires_at,:created_at)",
            self._proposal_row(proposal, owner_user_id, workspace_id),
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

    # --- runs / results / dependencies / reviews ------------------------------------------------
    @staticmethod
    def run_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "task_type": row["task_type"],
            "document_id": row["document_id"],
            "draft_id": row["draft_id"],
            "status": row["status"],
            "stage": row["stage"],
            "revision": int(row["revision"]),
            "created_at": row["created_at"],
            "deadline_at": row["deadline_at"],
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "result_id": row.get("result_id"),
            "error": json.loads(row["error_json"]) if row.get("error_json") else None,
        }

    @staticmethod
    def result_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "result_id": row["result_id"],
            "run_id": row["run_id"],
            "completion": row["completion"],
            "outcome": row["outcome"],
            "payload": json.loads(row["payload_json"]),
            "limitations": json.loads(row.get("limitations_json") or "[]"),
            "created_at": row["created_at"],
        }

    def create_run(
        self,
        *,
        task_type: str,
        document_id: str,
        draft_id: str,
        owner_user_id: str,
        workspace_id: str,
        deadline_at: str,
        request_json: str,
        dependencies: list[dict[str, Any]],
        idempotency: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        run_id = new_id("run")
        stamp = now_iso()
        with self.host.transaction() as conn:
            if idempotency:
                conn.execute(
                    "INSERT INTO idempotency_records VALUES (?,?,?,?,?,?,?)",
                    (
                        idempotency["principal"],
                        idempotency["method"],
                        idempotency["path"],
                        idempotency["key"],
                        idempotency["request_hash"],
                        "{}",
                        stamp,
                    ),
                )
            conn.execute(
                "INSERT INTO automation_runs (run_id,task_type,document_id,draft_id,owner_user_id,"
                "workspace_id,status,stage,revision,created_at,deadline_at,request_json)"
                " VALUES (?,?,?,?,?,?,'queued','queued',1,?,?,?)",
                (
                    run_id,
                    task_type,
                    document_id,
                    draft_id,
                    owner_user_id,
                    workspace_id,
                    stamp,
                    deadline_at,
                    request_json,
                ),
            )
            for dependency in dependencies:
                conn.execute(
                    "INSERT OR REPLACE INTO automation_dependencies VALUES (?,?,?,?,?,?)",
                    (
                        "run",
                        run_id,
                        dependency["resource_type"],
                        dependency["resource_id"],
                        dependency.get("version"),
                        stamp,
                    ),
                )
            row = dict(
                conn.execute("SELECT * FROM automation_runs WHERE run_id = ?", (run_id,)).fetchone()
            )
            if idempotency:
                conn.execute(
                    "UPDATE idempotency_records SET response_json=? WHERE principal=? AND method=?"
                    " AND path=? AND key=?",
                    (
                        json.dumps(self.run_view(row), ensure_ascii=False),
                        idempotency["principal"],
                        idempotency["method"],
                        idempotency["path"],
                        idempotency["key"],
                    ),
                )
        return self.get_run(run_id) or {}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.host.one("SELECT * FROM automation_runs WHERE run_id = ?", (run_id,))

    def list_runs(
        self, *, document_id: str, owner_user_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        return self.host.all(
            "SELECT * FROM automation_runs WHERE document_id=? AND owner_user_id=? AND workspace_id=?"
            " ORDER BY created_at DESC",
            (document_id, owner_user_id, workspace_id),
        )

    def transition_run(
        self, run_id: str, from_statuses: tuple[str, ...], to_status: str, stage: str, **fields: Any
    ) -> bool:
        allowed = {"started_at", "finished_at", "result_id", "error_json"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        assignments = ", ".join(f"{key}=?" for key in updates)
        if assignments:
            assignments += ", "
        placeholders = ",".join("?" for _ in from_statuses)
        with self.host.transaction() as conn:
            result = conn.execute(
                f"UPDATE automation_runs SET {assignments}status=?, stage=?, revision=revision+1"
                f" WHERE run_id=? AND status IN ({placeholders})",
                (*updates.values(), to_status, stage, run_id, *from_statuses),
            )
        return result.rowcount == 1

    def cancel_run(self, run_id: str, *, reason: str | None = None) -> bool:
        error = json.dumps({"code": "RUN_CANCELLED", "message": reason or "cancelled"})
        return self.transition_run(
            run_id,
            ("queued", "running"),
            "cancelled",
            "done",
            finished_at=now_iso(),
            error_json=error,
        )

    def fail_run(self, run_id: str, code: str, message: str) -> bool:
        error = json.dumps({"code": code, "message": message})
        return self.transition_run(
            run_id, ("queued", "running"), "failed", "done", finished_at=now_iso(), error_json=error
        )

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        return self.host.one("SELECT * FROM automation_results WHERE result_id = ?", (result_id,))

    def get_result_by_run(self, run_id: str) -> dict[str, Any] | None:
        return self.host.one("SELECT * FROM automation_results WHERE run_id = ?", (run_id,))

    def list_dependencies(self, owner_type: str, owner_id: str) -> list[dict[str, Any]]:
        return self.host.all(
            "SELECT * FROM automation_dependencies WHERE owner_type=? AND owner_id=?",
            (owner_type, owner_id),
        )

    def publish_result(
        self,
        *,
        run_id: str,
        completion: str,
        outcome: str,
        payload: dict[str, Any],
        limitations: list[dict[str, Any]],
        proposal: ChangeProposal | None,
        review,
        dependencies: list[dict[str, Any]],
        request_id: str,
    ) -> dict[str, Any]:
        result_id = new_id("result")
        stamp = now_iso()
        with self.host.transaction() as conn:
            run = conn.execute("SELECT * FROM automation_runs WHERE run_id = ?", (run_id,)).fetchone()
            if not run or run["status"] != "running":
                raise HostError(409, "run_not_running", "the run is no longer running")
            conn.execute(
                "INSERT INTO automation_results VALUES (?,?,?,?,?,?,?)",
                (
                    result_id,
                    run_id,
                    completion,
                    outcome,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(limitations, ensure_ascii=False),
                    stamp,
                ),
            )
            if proposal is not None:
                self._insert_proposal(conn, proposal, run["owner_user_id"], run["workspace_id"])
                if review is not None:
                    conn.execute(
                        "INSERT INTO automation_reviews VALUES (?,?,?,?,?,?,?)",
                        (
                            review.receipt_id,
                            proposal.proposal_id,
                            json.dumps(proposal.context.model_dump(mode="json"), sort_keys=True),
                            review.verdict,
                            review.validator_version,
                            json.dumps(review.checked_claim_ids, ensure_ascii=False),
                            stamp,
                        ),
                    )
            for dependency in dependencies:
                conn.execute(
                    "INSERT OR REPLACE INTO automation_dependencies VALUES (?,?,?,?,?,?)",
                    (
                        "run",
                        run_id,
                        dependency["resource_type"],
                        dependency["resource_id"],
                        dependency.get("version"),
                        stamp,
                    ),
                )
                if proposal is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO automation_dependencies VALUES (?,?,?,?,?,?)",
                        (
                            "proposal",
                            proposal.proposal_id,
                            dependency["resource_type"],
                            dependency["resource_id"],
                            dependency.get("version"),
                            stamp,
                        ),
                    )
            updated = conn.execute(
                "UPDATE automation_runs SET status='succeeded', stage='done', result_id=?,"
                " finished_at=?, revision=revision+1 WHERE run_id=? AND status='running'",
                (result_id, stamp, run_id),
            )
            if updated.rowcount != 1:
                raise HostError(409, "run_not_running", "the run is no longer running")
            self.host._audit(
                conn,
                request_id,
                "automation_run_succeeded",
                run["owner_user_id"],
                {"run_id": run_id, "result_id": result_id, "outcome": outcome},
            )
            self.host._enqueue(
                conn, "automation.run_succeeded", {"run_id": run_id, "result_id": result_id}
            )
        return self.get_result(result_id) or {}

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        return self.host.one("SELECT * FROM automation_reviews WHERE review_id = ?", (review_id,))

    def recover_runs(self) -> None:
        stamp = now_iso()
        with self.host.transaction() as conn:
            conn.execute(
                "UPDATE automation_runs SET status='timed_out', stage='done', finished_at=?,"
                " revision=revision+1, error_json=? WHERE status IN ('queued','running')"
                " AND deadline_at < ?",
                (stamp, json.dumps({"code": "RUN_TIMEOUT", "message": "deadline passed"}), stamp),
            )
            conn.execute(
                "UPDATE automation_runs SET status='failed', stage='done', finished_at=?,"
                " revision=revision+1, error_json=? WHERE status IN ('queued','running')",
                (stamp, json.dumps({"code": "RUN_INTERRUPTED", "message": "worker interrupted"})),
            )


__all__ = ["AutomationStore"]