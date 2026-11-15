"""HTTP surface for the local document host (`/documents`)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.documents.errors import PreconditionRequired
from app.documents.schemas import DocumentCreate, DraftSave, Heartbeat, LockCreate, VariablesUpdate
from app.documents.service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


def _service(request: Request) -> DocumentService:
    return request.app.state.host.documents


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "req_unknown"))


def _revision(request: Request, prefix: str = "draft") -> int:
    header = request.headers.get("if-match")
    if not header:
        raise PreconditionRequired()
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


def _headers(response: Response, etag: str) -> None:
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "no-store"


def _variables_revision(request: Request) -> int:
    return _revision(request, "variables")


@router.post("", status_code=201)
def create_document(request: Request, response: Response, payload: DocumentCreate) -> dict:
    service = _service(request)
    view = service.create_document(service.principal(request), payload, _request_id(request))
    _headers(response, view["etag"])
    response.headers["Location"] = f"/documents/{view['document_id']}/drafts/{view['draft_id']}"
    return view


@router.get("/{document_id}")
def read_document(document_id: str, request: Request, response: Response) -> dict:
    service = _service(request)
    view = service.document_view(service.principal(request), document_id)
    _headers(response, view["etag"])
    return view


@router.get("/{document_id}/drafts/{draft_id}")
def read_draft(document_id: str, draft_id: str, request: Request, response: Response) -> dict:
    service = _service(request)
    view = service.view(service.principal(request), document_id, draft_id)
    _headers(response, view["etag"])
    return view


@router.put("/{document_id}/drafts/{draft_id}")
def save_draft(
    document_id: str, draft_id: str, request: Request, response: Response, payload: DraftSave
) -> dict:
    service = _service(request)
    view = service.save_draft(
        service.principal(request),
        document_id,
        draft_id,
        _revision(request),
        payload,
        _request_id(request),
    )
    _headers(response, view["etag"])
    return view


@router.patch("/{document_id}/drafts/{draft_id}/variables")
def update_variables(
    document_id: str,
    draft_id: str,
    request: Request,
    response: Response,
    payload: VariablesUpdate,
) -> dict:
    service = _service(request)
    view = service.update_variables(
        service.principal(request),
        document_id,
        draft_id,
        _variables_revision(request),
        payload,
        _request_id(request),
    )
    response.headers["ETag"] = f'"variables-{view["variables_version"]}"'
    response.headers["Cache-Control"] = "no-store"
    return view


@router.post("/{document_id}/drafts/{draft_id}/checkpoints/{checkpoint_id}/restore")
def restore_checkpoint(
    document_id: str,
    draft_id: str,
    checkpoint_id: str,
    request: Request,
    response: Response,
) -> dict:
    service = _service(request)
    view = service.restore_checkpoint(
        service.principal(request),
        document_id,
        draft_id,
        checkpoint_id,
        _revision(request),
        _request_id(request),
    )
    _headers(response, view["etag"])
    return view


@router.post("/{document_id}/drafts/{draft_id}/lock", status_code=201)
def acquire_lock(
    document_id: str, draft_id: str, request: Request, response: Response, payload: LockCreate
) -> dict:
    service = _service(request)
    lock = service.acquire_lock(service.principal(request), document_id, draft_id, payload)
    response.headers["Cache-Control"] = "no-store"
    return lock


@router.post("/{document_id}/locks/{lock_id}/heartbeat")
def heartbeat_lock(
    document_id: str, lock_id: str, request: Request, response: Response, payload: Heartbeat
) -> dict:
    service = _service(request)
    lock = service.heartbeat(service.principal(request), document_id, lock_id, payload)
    response.headers["Cache-Control"] = "no-store"
    return lock


@router.post("/{document_id}/locks/{lock_id}/release")
def release_lock(document_id: str, lock_id: str, request: Request, response: Response) -> dict:
    service = _service(request)
    lock = service.release(service.principal(request), document_id, lock_id)
    response.headers["Cache-Control"] = "no-store"
    return lock


__all__ = ["router"]