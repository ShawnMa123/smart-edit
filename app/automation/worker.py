"""Automatic dispatch worker: final approval → one job per matching rule → shadow/review/send.

The worker is deliberately a separate process (single instance: the host store is a single SQLite
writer). It never trusts the live draft: the body is built from the approved submission snapshot.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.automation.jobs import (
    auto_send_enabled,
    delivery_status_for_document,
    record_delivery_event,
)
from app.automation.registry import AutomationRegistry
from app.automation.registry_schemas import DispatchRequest
from app.documents.errors import HostError
from app.documents.store import HostStore, new_id, now_iso
from app.shared.ports import Principal

SYSTEM_USER_ID = "system:automation"
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (60, 300, 1800)


def retryable(error_code: str | None, status_code: int | None) -> bool:
    """5xx, timeout and transport errors are worth a retry; refusals and contract errors are not."""
    if status_code is not None and status_code >= 500:
        return True
    code = error_code or ""
    return code == "timeout" or code.startswith("transport_error")


class AutomationWorker:
    def __init__(
        self,
        store: HostStore,
        registry: AutomationRegistry,
        *,
        auto_send: bool | None = None,
        activity: Any | None = None,
        authorizer: Any | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.auto_send = auto_send_enabled() if auto_send is None else auto_send
        # Optional activity feed / org resolver (PG mode); activity is always best effort.
        self.activity = activity
        self.authorizer = authorizer

    def run_once(self) -> dict[str, int]:
        return {"events": self.consume_approvals(), "jobs": self.run_due()}

    # --- 1. final approval → jobs -------------------------------------------------------------
    def consume_approvals(self) -> int:
        events = self.store.pending_approval_events()
        for event in events:
            payload = json.loads(event["payload_json"] or "{}")
            self.plan_submission(payload.get("request_id"), payload.get("status"))
        self.store.mark_outbox_delivered([event["id"] for event in events])
        return len(events)

    def plan_submission(self, request_id: str | None, status: str | None) -> int:
        if not request_id or status != "approved":
            return 0
        request = self.store.one(
            "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
        )
        if request is None or request["status"] != "approved":
            return 0
        submission = self.store.one(
            "SELECT * FROM document_submissions WHERE submission_id = ?",
            (request["submission_id"],),
        )
        document = self.store.one(
            "SELECT * FROM documents WHERE document_id = ?", (request["document_id"],)
        )
        if submission is None or document is None:
            return 0
        workspace = str(request["workspace_id"])
        binding = self.store.document_template(str(document["document_id"])) or {}
        if not binding.get("template_id") or not document.get("template_name"):
            self._skip(workspace, document, submission, "no_binding")
            return 0
        rules = self.matching_rules(workspace, document)
        if not rules:
            self._skip(workspace, document, submission, "no_rule")
            return 0
        created = 0
        seen_connectors: set[str] = set()
        for rule in rules:
            connector_id = str(rule["connector_id"])
            if connector_id in seen_connectors:
                # Two rules may point at the same downstream; one submission sends to it once.
                continue
            seen_connectors.add(connector_id)
            initial = "needs_review" if rule["mode"] == "needs_review" else "queued"
            self.store.create_automation_job(
                job_id=new_id("job"),
                workspace_id=workspace,
                rule_id=rule["rule_id"],
                document_id=str(document["document_id"]),
                submission_id=str(submission["submission_id"]),
                template_id=str(document["template_id"]),
                connector_id=connector_id,
                status=initial,
                mode=rule["mode"],
                required=bool(int(rule.get("required") if rule.get("required") is not None else 1)),
                idempotency_key=f"auto:{rule['rule_id']}:{submission['submission_id']}",
                request_json=json.dumps(
                    {"template_name": document["template_name"], "rule": rule["name"]},
                    ensure_ascii=False,
                ),
            )
            created += 1
        self.store.record_audit(
            event_type="automation_jobs_planned",
            actor=SYSTEM_USER_ID,
            payload={
                "document_id": document["document_id"],
                "submission_id": submission["submission_id"],
                "rules": [rule["rule_id"] for rule in rules],
            },
        )
        return created

    def matching_rules(self, workspace: str, document: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.store.all(
            "SELECT * FROM automation_rules WHERE workspace_id = ? AND enabled = 1 "
            "AND disabled_at IS NULL AND template_name = ? AND trigger = 'final_approval' "
            "ORDER BY priority ASC, created_at ASC",
            (workspace, document.get("template_name")),
        )
        department = document.get("department_id")
        return [row for row in rows if row.get("department_id") in (None, department)]

    def _skip(
        self,
        workspace: str,
        document: dict[str, Any],
        submission: dict[str, Any],
        reason: str,
    ) -> None:
        self.store.create_automation_job(
            job_id=new_id("job"),
            workspace_id=workspace,
            rule_id="",
            document_id=str(document["document_id"]),
            submission_id=str(submission["submission_id"]),
            template_id=str(document.get("template_id") or ""),
            connector_id="",
            status="skipped",
            mode="auto_send",
            idempotency_key=f"skip:{submission['submission_id']}:{reason}",
            request_json=json.dumps({"reason": reason}, ensure_ascii=False),
            error_code=reason,
        )
        self.store.record_audit(
            event_type="automation_skipped",
            actor=SYSTEM_USER_ID,
            payload={
                "document_id": document["document_id"],
                "submission_id": submission["submission_id"],
                "reason": reason,
            },
        )

    # --- 2. jobs → dispatch -------------------------------------------------------------------
    def run_due(self) -> int:
        jobs = self.store.due_automation_jobs(now_iso())
        for job in jobs:
            before = self._delivery_status(job)
            self._execute(job)
            after = self._delivery_status(job)
            if after != before:
                self._record_delivery(job, after)
        return len(jobs)

    def _delivery_status(self, job: dict[str, Any]) -> str:
        return delivery_status_for_document(
            self.store, str(job["workspace_id"]), str(job["document_id"])
        )

    def _record_delivery(self, job: dict[str, Any], status: str) -> None:
        document = self.store.get_document(str(job["document_id"])) or {}
        record_delivery_event(
            self.activity,
            self.authorizer,
            job={**job, "document_department_id": document.get("department_id")},
            status=status,
            actor_user_id=SYSTEM_USER_ID,
            actor_label="Automation",
        )

    def _execute(self, job: dict[str, Any]) -> None:
        mode = str(job["mode"])
        # A `needs_review` job only waits while it is still in that state; after a release the
        # operator has taken responsibility, so it sends even when the tier is not `auto_send`.
        if mode == "needs_review" and job["status"] == "needs_review":
            return
        principal = self._principal(str(job["workspace_id"]))
        text = self._snapshot(str(job["submission_id"]))
        if text is None:
            self._fail(job, "submission_missing")
            return
        values = self.registry.prepare_values(principal, str(job["template_id"]), text)
        # The kill switch only degrades `auto_send`: shadow stays shadow and a released
        # needs_review job is an explicit human action.
        if mode == "shadow" or (mode == "auto_send" and not self.auto_send):
            self._shadow(job, principal, values, text)
        else:
            self._send(job, principal, values, text)

    def _snapshot(self, submission_id: str) -> str | None:
        row = self.store.one(
            "SELECT text FROM document_submissions WHERE submission_id = ?", (submission_id,)
        )
        return None if row is None else str(row["text"])

    def _shadow(
        self,
        job: dict[str, Any],
        principal: Principal,
        values: dict[str, str],
        text: str,
    ) -> None:
        preview = self.registry.preview(
            principal,
            DispatchRequest(
                template_id=str(job["template_id"]),
                connector_id=str(job["connector_id"]),
                document_id=None,
                text=text,
                values=values,
            ),
        )
        detail = {
            "url": preview.url,
            "body": preview.body,
            "issues": [issue.model_dump() for issue in preview.issues],
            "refusal": preview.refusal,
        }
        self.store.update_automation_job(
            str(job["job_id"]),
            status="shadowed",
            request_json=json.dumps(detail, ensure_ascii=False),
        )
        self.store.append_automation_job_event(
            str(job["job_id"]), str(job["status"]), "shadowed", {"mode": "shadow"}
        )

    def _send(
        self,
        job: dict[str, Any],
        principal: Principal,
        values: dict[str, str],
        text: str,
    ) -> None:
        attempt = int(job["attempts"]) + 1
        # The job's unique key prevents a second job; the attempt suffix lets a recorded 5xx retry.
        key = f"{job['idempotency_key']}#{attempt}"
        self.store.update_automation_job(
            str(job["job_id"]), status="sending", attempts=attempt
        )
        self.store.append_automation_job_event(
            str(job["job_id"]), str(job["status"]), "sending", {"attempt": attempt}
        )
        try:
            receipt = self.registry.dispatch(
                principal,
                DispatchRequest(
                    template_id=str(job["template_id"]),
                    connector_id=str(job["connector_id"]),
                    document_id=str(job["document_id"]),
                    values=values,
                    idempotency_key=key,
                ),
                job_id=str(job["job_id"]),
                rule_id=str(job["rule_id"]) or None,
                trigger="final_approval",
                submission_id=str(job["submission_id"]),
                text=text,
            )
        except HostError as error:
            self._fail(job, error.code, attempts=attempt)
            return
        if receipt.status == "succeeded":
            self._finish(job, "sent", receipt, attempt)
        elif retryable(receipt.error_code, receipt.status_code) and attempt < MAX_ATTEMPTS:
            self._retry(job, receipt, attempt)
        else:
            self._finish(job, "needs_attention", receipt, attempt)

    def _finish(self, job: dict[str, Any], status: str, receipt: Any, attempt: int) -> None:
        self.store.update_automation_job(
            str(job["job_id"]),
            status=status,
            attempts=attempt,
            receipt_id=receipt.dispatch_id,
            response_excerpt=receipt.response_excerpt,
            error_code=receipt.error_code,
            next_attempt_at=None,
        )
        self.store.append_automation_job_event(
            str(job["job_id"]),
            "sending",
            status,
            {"receipt_id": receipt.dispatch_id, "status_code": receipt.status_code},
        )
        self.store.record_audit(
            event_type=f"automation_job_{status}",
            actor=SYSTEM_USER_ID,
            payload={
                "job_id": job["job_id"],
                "document_id": job["document_id"],
                "connector_id": job["connector_id"],
                "status_code": receipt.status_code,
            },
        )

    def _retry(self, job: dict[str, Any], receipt: Any, attempt: int) -> None:
        delay = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
        next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        self.store.update_automation_job(
            str(job["job_id"]),
            status="queued",
            attempts=attempt,
            receipt_id=receipt.dispatch_id,
            error_code=receipt.error_code,
            next_attempt_at=next_at,
        )
        self.store.append_automation_job_event(
            str(job["job_id"]),
            "sending",
            "queued",
            {"retry_in_seconds": delay, "error": receipt.error_code},
        )

    def _fail(self, job: dict[str, Any], code: str | None, attempts: int | None = None) -> None:
        self.store.update_automation_job(
            str(job["job_id"]),
            status="needs_attention",
            attempts=attempts if attempts is not None else int(job["attempts"]),
            error_code=code,
        )
        self.store.append_automation_job_event(
            str(job["job_id"]),
            str(job["status"]),
            "needs_attention",
            {"error": code},
        )

    @staticmethod
    def _principal(workspace: str) -> Principal:
        return Principal(
            user_id=SYSTEM_USER_ID,
            workspace_id=workspace,
            roles=("bank_ops",),
            capabilities=(
                "read",
                "automation_view",
                "automation_configure",
                "automation_dispatch",
                "automation_audit",
            ),
            auth_kind="system",
        )


def main(argv: list[str] | None = None) -> int:
    """`python -m app.automation.worker [--once] [--interval 5]` — single instance only."""
    import argparse
    import time

    from app.documents.bootstrap import build_host_services

    parser = argparse.ArgumentParser(description="smart-edit automation worker")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args(argv)
    if (os.environ.get("SMART_EDIT_AUTOMATION_WORKER") or "1") != "1":
        print("automation worker disabled (SMART_EDIT_AUTOMATION_WORKER != 1)")
        return 0
    host = build_host_services()
    registry = AutomationRegistry(host.store, documents=host.documents)
    # Delivery status changes land in the Activity feed (`kind: automation`) when PG identity is
    # configured; a fake/test identity has no org to write to, so the worker keeps running.
    activity = None
    authorizer = None
    try:
        from app.identity.bootstrap import build_identity_services
        from app.identity.resources import DocumentAccess

        identity = build_identity_services()
        if identity.enabled and identity.store is not None and identity.authorization is not None:
            activity = identity.activity
            authorizer = DocumentAccess(identity.store, host.store, identity.authorization)
    except Exception as error:  # noqa: BLE001 - dispatch must not depend on the activity feed
        print(f"activity events disabled (identity stack unavailable): {error}")
    worker = AutomationWorker(
        host.store, registry, activity=activity, authorizer=authorizer
    )
    if args.once:
        print(json.dumps(worker.run_once()))
        return 0
    while True:
        try:
            worker.run_once()
        except Exception as error:  # keep the process alive; the job rows carry the failure
            print(f"worker iteration failed: {error}")
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())