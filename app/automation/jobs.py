"""Automatic-dispatch jobs: run history, delivery state and the manual fallback actions.

The worker writes jobs; this service is the read/act side behind `/automation/jobs`. Delivery state
is always derived from the jobs (never stored separately), so a retry or a release is reflected the
moment the job row changes.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.automation.job_schemas import (
    AutomationSettings,
    DeliveryRow,
    DocumentDelivery,
    JobDetailView,
    JobEventView,
    JobPage,
    JobView,
)
from app.automation.registry import AutomationRegistry
from app.documents.errors import HostError, HostNotFound
from app.documents.store import HostStore
from app.shared.ports import Principal

RETRYABLE_STATUSES = ("needs_attention", "cancelled")
CANCELLABLE_STATUSES = ("queued", "needs_review", "needs_attention")


def auto_send_enabled() -> bool:
    """Global kill switch: off means every `auto_send` rule behaves like `shadow`."""
    raw = (os.environ.get("SMART_EDIT_AUTOMATION_AUTO_SEND") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def aggregate_delivery(jobs: list[dict[str, Any]]) -> str:
    """Document-level delivery status (`automation-auto-dispatch`: sent = all required sent)."""
    real = [job for job in jobs if job.get("status") != "skipped"]
    if not real:
        return "not_configured"
    required = [job for job in real if int(job.get("required") or 0)]
    if any(job["status"] in {"needs_attention", "cancelled"} for job in required):
        return "needs_attention"
    if required and all(job["status"] == "sent" for job in required):
        return "sent"
    if not required:
        if any(job["status"] == "sent" for job in real):
            return "sent"
        if any(job["status"] in {"needs_attention", "cancelled"} for job in real):
            return "needs_attention"
    if all(job["status"] == "shadowed" for job in real):
        return "shadowed"
    if any(job["status"] == "sending" for job in real):
        return "sending"
    if any(job["status"] == "needs_review" for job in real):
        return "needs_review"
    sent = any(job["status"] == "sent" for job in real)
    if any(job["status"] == "queued" for job in real):
        return "partial" if sent else "queued"
    if sent:
        return "partial"
    return "needs_attention"


def latest_submission_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the newest submission's jobs: re-approving a document starts a new delivery state."""
    if not jobs:
        return jobs
    latest = jobs[0]["submission_id"]
    return [job for job in jobs if job["submission_id"] == latest]


def delivery_status_for_document(
    store: HostStore, workspace_id: str, document_id: str
) -> str:
    """Aggregate the open document's delivery state from its newest submission's jobs."""
    jobs = store.automation_jobs(workspace_id, document_id=document_id, limit=1000)
    return aggregate_delivery(latest_submission_jobs(jobs))


def org_id_for(authorizer: Any | None, workspace_id: str) -> str | None:
    if authorizer is None:
        return None
    try:
        organization = authorizer.organization(workspace_id)
    except Exception:  # noqa: BLE001 - activity is best effort, never a business failure
        return None
    return organization["org_id"] if organization else None


def record_delivery_event(
    activity: Any | None,
    authorizer: Any | None,
    *,
    job: dict[str, Any],
    status: str,
    actor_user_id: str,
    actor_label: str,
) -> None:
    """Write one `kind: automation` activity row for a document delivery status change."""
    if activity is None:
        return
    workspace = str(job.get("workspace_id") or "")
    org_id = org_id_for(authorizer, workspace)
    if not org_id:
        return
    activity.safe_record(
        org_id=org_id,
        department_id=job.get("document_department_id"),
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        kind="automation",
        action=f"delivery.{status}",
        resource_type="document",
        resource_id=job.get("document_id"),
        detail={
            "document_id": job.get("document_id"),
            "job_id": job.get("job_id"),
            "rule_id": job.get("rule_id"),
            "connector_id": job.get("connector_id"),
            "status": status,
        },
    )


def _json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


class AutomationJobService:
    """Runs API + delivery aggregate + retry/cancel/release (design D5/D6/D8)."""

    def __init__(
        self,
        store: HostStore,
        registry: AutomationRegistry,
        *,
        activity: Any | None = None,
        authorizer: Any | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.activity = activity
        self.authorizer = authorizer

    # --- helpers ------------------------------------------------------------------------------
    @staticmethod
    def _workspace(principal: Principal) -> str:
        return AutomationRegistry._workspace(principal)

    def _job_rows(
        self,
        principal: Principal,
        *,
        document_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT j.*, d.department_id AS document_department_id, d.title AS document_title,"
            " r.name AS rule_name, c.name AS connector_name"
            " FROM automation_jobs j"
            " LEFT JOIN documents d ON d.document_id = j.document_id"
            " LEFT JOIN automation_rules r ON r.rule_id = j.rule_id"
            " LEFT JOIN automation_connectors c ON c.connector_id = j.connector_id"
            " WHERE j.workspace_id = ?"
        )
        params: list[Any] = [self._workspace(principal)]
        if document_id:
            sql += " AND j.document_id = ?"
            params.append(document_id)
        sql += " ORDER BY j.created_at DESC"
        rows = self.store.all(sql, tuple(params))
        visible = [
            row
            for row in rows
            if AutomationRegistry._can_view_department(
                principal, row.get("document_department_id")
            )
        ]
        return visible[:limit]

    def _row(self, principal: Principal, job_id: str, *, write: bool = False) -> dict[str, Any]:
        rows = [row for row in self._job_rows(principal, limit=1000) if row["job_id"] == job_id]
        if not rows:
            raise HostNotFound("automation job not found")
        row = rows[0]
        if write and not AutomationRegistry._can_write_department(
            principal, row.get("document_department_id")
        ):
            raise HostError(
                403,
                "department_scope_denied",
                "a department administrator cannot act on another department's delivery",
            )
        return row

    @staticmethod
    def _view(row: dict[str, Any]) -> JobView:
        mode = row.get("mode")
        return JobView(
            job_id=str(row["job_id"]),
            rule_id=str(row.get("rule_id") or ""),
            rule_name=row.get("rule_name"),
            document_id=str(row["document_id"]),
            document_title=row.get("document_title"),
            submission_id=str(row.get("submission_id") or ""),
            template_id=str(row.get("template_id") or ""),
            connector_id=str(row.get("connector_id") or ""),
            connector_name=row.get("connector_name"),
            status=row["status"],
            mode=mode if mode in {"shadow", "needs_review", "auto_send"} else "shadow",
            required=bool(int(row.get("required") or 0)),
            attempts=int(row.get("attempts") or 0),
            next_attempt_at=row.get("next_attempt_at"),
            error_code=row.get("error_code"),
            receipt_id=row.get("receipt_id"),
            request=_json(row.get("request_json")),
            response_excerpt=row.get("response_excerpt"),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _transition(
        self,
        principal: Principal,
        row: dict[str, Any],
        *,
        to_status: str,
        event: str,
        **fields: Any,
    ) -> dict[str, Any]:
        self.store.update_automation_job(str(row["job_id"]), status=to_status, **fields)
        self.store.append_automation_job_event(
            str(row["job_id"]),
            str(row["status"]),
            to_status,
            {"by": principal.user_id, "action": event},
        )
        self.store.record_audit(
            event_type=event,
            actor=principal.user_id,
            payload={
                "job_id": row["job_id"],
                "document_id": row["document_id"],
                "from": row["status"],
                "to": to_status,
            },
        )
        updated = self.store.automation_job(str(row["job_id"]))
        assert updated is not None
        return updated

    # --- reads --------------------------------------------------------------------------------
    def list(
        self,
        principal: Principal,
        *,
        document_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> JobPage:
        self.registry._require(principal, "automation_view")
        rows = self._job_rows(principal, document_id=document_id, limit=limit)
        if status:
            rows = [row for row in rows if row["status"] == status]
        return JobPage(items=[self._view(row) for row in rows])

    def detail(self, principal: Principal, job_id: str) -> JobDetailView:
        self.registry._require(principal, "automation_view")
        row = self._row(principal, job_id)
        events = [
            JobEventView(
                event_id=str(event["event_id"]),
                from_status=event.get("from_status"),
                to_status=str(event["to_status"]),
                detail=_json(event.get("detail_json")) or {},
                created_at=str(event["created_at"]),
            )
            for event in self.store.automation_job_events(job_id)
        ]
        return JobDetailView(**self._view(row).model_dump(), events=events)

    def settings(self, principal: Principal) -> AutomationSettings:
        self.registry._require(principal, "automation_view")
        return AutomationSettings(auto_send_enabled=auto_send_enabled())

    def document_delivery(self, principal: Principal, document_id: str) -> DocumentDelivery:
        self.registry._require(principal, "automation_view")
        document = self.store.get_document(document_id)
        if (
            document is None
            or document.get("workspace_id") != self._workspace(principal)
            or not AutomationRegistry._can_view_department(
                principal, document.get("department_id")
            )
        ):
            raise HostNotFound("document not found")
        jobs = self.store.automation_jobs(
            self._workspace(principal), document_id=document_id, limit=1000
        )
        # A document can be approved again after a rejection or a new revision: delivery state is
        # the state of the latest submission, not of every historical attempt.
        jobs = latest_submission_jobs(jobs)
        status = aggregate_delivery(jobs)
        skipped = [job for job in jobs if job.get("status") == "skipped"]
        skipped_reason = (
            str(skipped[0].get("error_code"))
            if skipped and all(job.get("status") == "skipped" for job in jobs)
            else None
        )
        names = {
            row["connector_id"]: row["name"]
            for row in self.store.all(
                "SELECT connector_id, name FROM automation_connectors WHERE workspace_id = ?",
                (self._workspace(principal),),
            )
        }
        rows = [
            DeliveryRow(
                job_id=str(job["job_id"]),
                rule_id=str(job.get("rule_id") or ""),
                connector_id=str(job.get("connector_id") or ""),
                connector_name=names.get(str(job.get("connector_id") or "")),
                status=job["status"],
                mode=(
                    job.get("mode")
                    if job.get("mode") in {"shadow", "needs_review", "auto_send"}
                    else "shadow"
                ),
                required=bool(int(job.get("required") or 0)),
                attempts=int(job.get("attempts") or 0),
                error_code=job.get("error_code"),
                receipt_id=job.get("receipt_id"),
                updated_at=str(job["updated_at"]),
            )
            for job in jobs
            if job.get("status") != "skipped"
        ]
        return DocumentDelivery(
            document_id=document_id,
            status=status,
            auto_send_enabled=auto_send_enabled(),
            skipped_reason=skipped_reason,
            rows=rows,
        )

    # --- manual fallback ----------------------------------------------------------------------
    def release(self, principal: Principal, job_id: str) -> JobView:
        """`needs_review` → `queued`: the operator takes responsibility for this send."""
        self.registry._require(principal, "automation_dispatch")
        row = self._row(principal, job_id, write=True)
        if row["status"] != "needs_review":
            raise HostError(409, "job_not_releasable", "only a needs_review job can be released")
        updated = self._transition(
            principal, row, to_status="queued", event="automation_job_released"
        )
        return self._view(updated)

    def retry(self, principal: Principal, job_id: str) -> JobView:
        self.registry._require(principal, "automation_dispatch")
        row = self._row(principal, job_id, write=True)
        if row["status"] not in RETRYABLE_STATUSES:
            raise HostError(
                409, "job_not_retryable", "only a failed or cancelled job can be retried"
            )
        # Keep `attempts` so the worker's idempotency key moves on to a new attempt suffix.
        updated = self._transition(
            principal,
            row,
            to_status="queued",
            event="automation_job_retried",
            next_attempt_at=None,
            error_code=None,
        )
        return self._view(updated)

    def cancel(self, principal: Principal, job_id: str) -> JobView:
        self.registry._require(principal, "automation_dispatch")
        row = self._row(principal, job_id, write=True)
        if row["status"] not in CANCELLABLE_STATUSES:
            raise HostError(
                409, "job_not_cancellable", "a sent or in-flight job cannot be cancelled"
            )
        updated = self._transition(
            principal,
            row,
            to_status="cancelled",
            event="automation_job_cancelled",
            next_attempt_at=None,
        )
        return self._view(updated)


__all__ = [
    "AutomationJobService",
    "aggregate_delivery",
    "auto_send_enabled",
    "delivery_status_for_document",
    "latest_submission_jobs",
    "record_delivery_event",
]