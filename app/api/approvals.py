"""Approval inbox, detail and decisions (`/approvals`)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from app.documents.schemas import ApprovalDecision

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _approvals(request: Request):
    return request.app.state.host.approvals


def _principal(request: Request):
    return request.app.state.host.documents.principal(request)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


@router.get("")
def list_approvals(
    request: Request,
    response: Response,
    stage: str | None = Query(default=None, pattern="^(first|second)$"),
) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    return _approvals(request).inbox(_principal(request), stage=stage)


@router.get("/{request_id}")
def get_approval(request_id: str, request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return _approvals(request).detail(_principal(request), request_id)


@router.post("/{request_id}/decisions", status_code=201)
def decide_approval(
    request_id: str, request: Request, response: Response, payload: ApprovalDecision
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return _approvals(request).decide(
        _principal(request), request_id, payload.model_dump(), _request_id(request)
    )


__all__ = ["router"]