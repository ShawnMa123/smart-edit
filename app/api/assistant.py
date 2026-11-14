"""Assistant HTTP surface (tasks 4.1). Paths/DTOs mirror `AI_assistance_reqirement.md` §8."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.assistant.errors import AssistantError
from app.assistant.schemas import (
    CancelDecision,
    EvidenceDetail,
    Feedback,
    FeedbackInput,
    MessagePage,
    Run,
    RunAccepted,
    RunCreate,
    Session,
    SessionCreate,
    SessionPage,
    Snapshot,
    SnapshotCreate,
)
from app.assistant.service import AssistantService

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _service(request: Request) -> AssistantService:
    return request.app.state.assistant


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


def _idempotency_key(request: Request) -> str | None:
    return request.headers.get("Idempotency-Key")


@router.post("/snapshots", response_model=Snapshot, status_code=201)
def create_snapshot(request: Request, payload: SnapshotCreate) -> Snapshot:
    return _service(request).create_snapshot(
        _service(request).principal(request), payload, _request_id(request)
    )


@router.post("/sessions", response_model=Session, status_code=201)
def create_session(request: Request, payload: SessionCreate) -> Session:
    service = _service(request)
    return service.create_session(
        service.principal(request), payload, _idempotency_key(request), _request_id(request)
    )


@router.get("/sessions", response_model=SessionPage)
def list_sessions(request: Request, workspace_id: str) -> SessionPage:
    service = _service(request)
    return SessionPage(items=service.list_sessions(service.principal(request), workspace_id))


@router.get("/sessions/{session_id}", response_model=Session)
def get_session(request: Request, session_id: str) -> Session:
    service = _service(request)
    return service.get_session(service.principal(request), session_id)


@router.post("/sessions/{session_id}/runs", response_model=RunAccepted, status_code=202)
def create_run(
    request: Request, response: Response, session_id: str, payload: RunCreate,
    background_tasks: BackgroundTasks,
) -> RunAccepted:
    service = _service(request)
    accepted = service.create_run(
        service.principal(request), session_id, payload, _idempotency_key(request), _request_id(request)
    )
    response.headers["Location"] = f"/assistant/runs/{accepted.id}"
    background_tasks.add_task(service.execute_run, accepted.id)
    return accepted


@router.get("/runs/{run_id}", response_model=Run)
def get_run(request: Request, run_id: str) -> Run:
    service = _service(request)
    return service.get_run(service.principal(request), run_id)


@router.post("/runs/{run_id}/cancel", response_model=CancelDecision)
def cancel_run(request: Request, run_id: str) -> CancelDecision:
    service = _service(request)
    return service.cancel_run(
        service.principal(request), run_id, _idempotency_key(request), _request_id(request)
    )


@router.get("/sessions/{session_id}/messages", response_model=MessagePage)
def list_messages(request: Request, session_id: str) -> MessagePage:
    service = _service(request)
    return MessagePage(items=service.list_messages(service.principal(request), session_id))


@router.get("/messages/{message_id}/citations/{citation_id}", response_model=EvidenceDetail)
def citation_detail(request: Request, message_id: str, citation_id: str) -> EvidenceDetail:
    service = _service(request)
    return service.citation_detail(service.principal(request), message_id, citation_id)


@router.put("/messages/{message_id}/feedback", response_model=Feedback)
def put_feedback(request: Request, message_id: str, payload: FeedbackInput) -> Feedback:
    service = _service(request)
    return service.feedback(service.principal(request), message_id, payload)


__all__ = ["AssistantError", "router"]