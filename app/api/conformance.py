"""HTTP surface for the template-conformance audit (`/conformance/*`).

The review is asynchronous: `POST /conformance/reviews` answers 202 with a run, the panel polls the
run, then reads the report. That matches the legal scan (a model call takes tens of seconds) and
keeps a page reload safe.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.api.errors import ApiFailure
from app.conformance.contracts import (
    ConfigDetail,
    ConfigSummary,
    ConformanceRequest,
    Report,
    Run,
)
from app.conformance.service import ConformanceError, ConformanceService
from app.conformance.store import ConformanceStore
from app.shared.ports import Principal

router = APIRouter(prefix="/conformance", tags=["conformance"])

# Bare-router embeddings (tests) get a process-local service; the full app injects one built with the
# document host, the approved Doubao composer and a persistent store (`app/api/main.py`).
_DEFAULT: ConformanceService | None = None


def _default_service() -> ConformanceService:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ConformanceService(store=ConformanceStore(":memory:"))
    return _DEFAULT


def _service(request: Request) -> ConformanceService:
    service = getattr(request.app.state, "conformance", None)
    if service is None:
        service = _default_service()
        request.app.state.conformance = service
    return service


def _principal(request: Request, workspace_id: str) -> Principal:
    principal = getattr(request.state, "principal", None)
    return principal or Principal(user_id="user_demo_01", workspace_id=workspace_id)


def _failure(exc: ConformanceError) -> ApiFailure:
    return ApiFailure(exc.status, exc.code, exc.message, exc.detail or None)


@router.get("/configs", response_model=list[ConfigSummary])
def list_configs(request: Request, response: Response) -> list[ConfigSummary]:
    """Published calibration configs the panel can offer; never a draft or an unpublished one."""
    response.headers["Cache-Control"] = "no-store"
    return _service(request).list_configs()


@router.get("/configs/{config_id}", response_model=ConfigDetail)
def get_config_detail(config_id: str, request: Request, response: Response) -> ConfigDetail:
    """Read-only inspector: requirement titles/wording, required fields and generation limits."""
    try:
        detail = _service(request).config_detail(config_id)
    except ConformanceError as exc:
        raise _failure(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    return detail


@router.post("/reviews", status_code=202, response_model=Run)
def submit_review(
    submit: ConformanceRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> Run:
    service = _service(request)
    principal = _principal(request, submit.workspace_id)
    key = (request.headers.get("Idempotency-Key") or "").strip() or None
    try:
        run, needs_run = service.submit(submit, principal=principal, idempotency_key=key)
    except ConformanceError as exc:
        raise _failure(exc) from exc
    if needs_run:
        background_tasks.add_task(service.execute, run.run_id, submit, principal)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/conformance/reports/{run.report_id}" if run.report_id else f"/conformance/runs/{run.run_id}"
    )
    return run


@router.get("/runs/{run_id}", response_model=Run)
def get_run(run_id: str, request: Request, response: Response) -> Run:
    try:
        run = _service(request).get_run(run_id)
    except ConformanceError as exc:
        raise _failure(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    return run


@router.get("/reports/{report_id}", response_model=Report)
def get_report(report_id: str, request: Request, response: Response) -> Report:
    service = _service(request)
    try:
        report = service.get_report(report_id)
    except ConformanceError as exc:
        raise _failure(exc) from exc
    principal = getattr(request.state, "principal", None)
    workspace = service.report_workspace(report_id)
    if principal is not None and workspace and principal.workspace_id != workspace:
        # Same shape as "not found": never confirm a report exists in another workspace.
        raise ApiFailure(404, "resource_unavailable", "conformance report not found")
    response.headers["Cache-Control"] = "no-store"
    return report


__all__ = ["router"]