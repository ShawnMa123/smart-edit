"""HTTP surface for automation proposals, apply and undo (`/automation`)."""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.automation.run_schemas import AutomationResult, AutomationRun, RunCancel, RunCreate, RunPage
from app.automation.schemas import (
    ApplyRequest,
    ProposalDecision,
    UndoRequest,
)
from app.automation.service import AutomationService
from app.documents.errors import HostError, PreconditionRequired
from app.documents.projection import sha256_text

router = APIRouter(prefix="/automation", tags=["automation"])


def _service(request: Request) -> AutomationService:
    return request.app.state.host.automation


def _runs(request: Request):
    return request.app.state.host.runs


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


def _key(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if not key:
        raise HostError(400, "invalid_request", "this operation requires an Idempotency-Key")
    return key


def _revision(request: Request, prefix: str) -> int:
    header = request.headers.get("if-match")
    if not header:
        raise PreconditionRequired(f"If-Match must look like \"{prefix}-<revision>\"")
    value = header.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    expected = f"{prefix}-"
    if not value.startswith(expected):
        raise PreconditionRequired(f"If-Match must look like \"{prefix}-<revision>\"")
    try:
        return int(value[len(expected):])
    except ValueError as exc:
        raise PreconditionRequired("If-Match revision is not a number") from exc


def _hash(payload: dict[str, Any]) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _idempotent(
    request: Request,
    service: AutomationService,
    path: str,
    payload: dict[str, Any],
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    principal = service.principal(request)
    key = _key(request)
    existing = service.host.get_idempotency(principal.user_id, "POST", path, key)
    if existing:
        if existing["request_hash"] != _hash(payload):
            raise HostError(
                409, "idempotency_conflict", "the same idempotency key was reused with another request"
            )
        return json.loads(existing["response_json"])
    result = action()
    service.host.put_idempotency(principal.user_id, "POST", path, key, _hash(payload), result)
    return result


def _headers(response: Response, etag: str) -> None:
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "no-store"


@router.post("/runs", status_code=202)
def create_run(
    request: Request,
    response: Response,
    payload: RunCreate,
    background_tasks: BackgroundTasks,
) -> AutomationRun:
    service = _runs(request)
    run = service.create(
        service.principal(request), payload, request.headers.get("idempotency-key"), _request_id(request)
    )
    _headers(response, f"run-{run.revision}")
    response.headers["Location"] = f"/automation/runs/{run.run_id}"
    background_tasks.add_task(service.execute, run.run_id)
    return run


@router.get("/runs", response_model=RunPage)
def list_runs(document_id: str, request: Request) -> RunPage:
    service = _runs(request)
    return RunPage(items=service.list(service.principal(request), document_id))


@router.get("/runs/{run_id}", response_model=AutomationRun)
def get_run(run_id: str, request: Request, response: Response) -> AutomationRun:
    service = _runs(request)
    run = service.get(service.principal(request), run_id)
    _headers(response, f"run-{run.revision}")
    return run


@router.post("/runs/{run_id}/cancel", response_model=AutomationRun)
def cancel_run(
    run_id: str, request: Request, response: Response, payload: RunCancel
) -> AutomationRun:
    service = _runs(request)
    run = service.cancel(
        service.principal(request), run_id, _revision(request, "run"), payload.reason
    )
    _headers(response, f"run-{run.revision}")
    return run


@router.get("/results/{result_id}", response_model=AutomationResult)
def get_result(result_id: str, request: Request, response: Response) -> AutomationResult:
    service = _runs(request)
    result = service.result(service.principal(request), result_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, request: Request, response: Response) -> dict:
    service = _service(request)
    model = service.get(service.principal(request), proposal_id)
    _headers(response, f"proposal-{model.revision}")
    return model.model_dump(mode="json")


@router.post("/proposals/{proposal_id}/decisions", status_code=201)
def decide_proposal(
    proposal_id: str, request: Request, response: Response, payload: ProposalDecision
) -> dict:
    service = _service(request)
    expected = _revision(request, "proposal")
    path = f"/automation/proposals/{proposal_id}/decisions"
    model = _idempotent(
        request,
        service,
        path,
        payload.model_dump(mode="json"),
        lambda: service.decide(
            service.principal(request), proposal_id, payload, expected, _request_id(request)
        ).model_dump(mode="json"),
    )
    _headers(response, f"proposal-{model['revision']}")
    return model


@router.post("/proposals/{proposal_id}/apply", status_code=201)
def apply_proposal(
    proposal_id: str, request: Request, response: Response, payload: ApplyRequest
) -> dict:
    service = _service(request)
    expected = _revision(request, "draft")
    if expected != payload.expected_draft_revision:
        raise HostError(412, "version_mismatch", "If-Match does not match expected_draft_revision")
    receipt = service.apply(
        service.principal(request),
        proposal_id,
        payload,
        request.headers.get("idempotency-key"),
        _request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/automation/applications/{receipt['receipt_id']}"
    return receipt


@router.post("/applications/{receipt_id}/undo", status_code=201)
def undo_application(
    receipt_id: str, request: Request, response: Response, payload: UndoRequest
) -> dict:
    service = _service(request)
    expected = _revision(request, "draft")
    if expected != payload.expected_draft_revision:
        raise HostError(412, "version_mismatch", "If-Match does not match expected_draft_revision")
    receipt = service.undo(
        service.principal(request),
        receipt_id,
        payload,
        request.headers.get("idempotency-key"),
        _request_id(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return receipt


@router.get("/applications/{receipt_id}")
def get_application(receipt_id: str, request: Request, response: Response) -> dict:
    service = _service(request)
    receipt = service.get_receipt(service.principal(request), receipt_id)
    response.headers["Cache-Control"] = "no-store"
    return receipt


__all__ = ["router"]