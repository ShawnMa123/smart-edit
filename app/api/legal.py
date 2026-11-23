"""HTTP surface for the legal review module (`/legal/*`).

L1 slice: synchronous, deterministic-only, in-memory. The async worker and persistence
are L2. `facts` is carried on the request body for the demo only — the real pipeline will
resolve it from `facts_version_id` against the host (spec §4.1).
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import Field

from app.api.errors import ApiFailure
from app.legal_review.contracts import ReviewCreate, ReviewReport, ReviewRun
from app.legal_review.service import LegalRequestError, LegalService
from app.legal_review.store import LegalStore
from app.shared.ports import Principal

router = APIRouter(prefix="/legal", tags=["legal"])

# Bare-router embeddings (tests) get a process-local service; the full app injects one built with
# the document host, the statute retriever and the composer (`app/api/main.py`).
_DEFAULT: LegalService | None = None


class ReviewSubmit(ReviewCreate):
    # Temporary demo field; the host resolves facts from facts_version_id in the real flow.
    facts: dict = Field(default_factory=dict)


def _default_service() -> LegalService:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = LegalService(store=LegalStore(":memory:"))
    return _DEFAULT


def _service(request: Request) -> LegalService:
    service = getattr(request.app.state, "legal", None)
    if service is None:
        service = _default_service()
        request.app.state.legal = service
    return service


def _principal(request: Request, workspace_id: str) -> Principal:
    principal = getattr(request.state, "principal", None)
    return principal or Principal(user_id="user_demo_01", workspace_id=workspace_id)


def _failure(exc: LegalRequestError) -> ApiFailure:
    return ApiFailure(exc.status, exc.code, exc.message, exc.detail or None)


@router.post("/reviews", status_code=202, response_model=ReviewRun)
def submit_review(
    submit: ReviewSubmit,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> ReviewRun:
    service = _service(request)
    principal = _principal(request, submit.workspace_id)
    key = (request.headers.get("Idempotency-Key") or "").strip() or None
    try:
        run, needs_scan = service.submit(
            submit, submit.facts, principal=principal, idempotency_key=key
        )
    except LegalRequestError as exc:
        raise _failure(exc) from exc
    if needs_scan:
        # A document scan is 8-20 s: it runs in the background and the client polls the run.
        background_tasks.add_task(service.execute_document_scan, run.run_id, submit, principal)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/legal/reports/{run.report_id}" if run.report_id else f"/legal/runs/{run.run_id}"
    )
    return run


@router.get("/runs/{run_id}", response_model=ReviewRun)
def get_run(run_id: str, request: Request, response: Response) -> ReviewRun:
    try:
        run = _service(request).get_run(run_id)
    except LegalRequestError as exc:
        raise _failure(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    return run


@router.get("/reports/{report_id}", response_model=ReviewReport)
def get_report(report_id: str, request: Request, response: Response) -> ReviewReport:
    service = _service(request)
    try:
        report = service.get_report(report_id)
    except LegalRequestError as exc:
        raise _failure(exc) from exc
    principal = getattr(request.state, "principal", None)
    workspace = service.report_workspace(report_id)
    if principal is not None and workspace and principal.workspace_id != workspace:
        # Same shape as "not found": never confirm a report exists in another workspace.
        raise ApiFailure(404, "resource_unavailable", "legal report not found")
    response.headers["Cache-Control"] = "no-store"
    return report
