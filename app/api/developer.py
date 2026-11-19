"""Developer HTTP surface: API keys, request logs, usage (`/developer`)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from app.identity.bootstrap import IdentityServices
from app.identity.schemas import ApiKeyCreate

router = APIRouter(prefix="/developer", tags=["developer"])


def _services(request: Request) -> IdentityServices:
    services = request.app.state.identity
    services.require_pg()
    return services


def _principal(request: Request):
    return _services(request).principal.resolve(request)


@router.get("/organizations/{org_id}/keys")
def list_keys(org_id: str, request: Request) -> list[dict]:
    return _services(request).developer.list_keys(_principal(request), org_id)


@router.post("/organizations/{org_id}/keys", status_code=201)
def create_key(org_id: str, request: Request, payload: ApiKeyCreate) -> dict:
    return _services(request).developer.create_key(
        _principal(request), org_id, payload.model_dump()
    )


@router.delete("/organizations/{org_id}/keys/{key_id}", status_code=204)
def revoke_key(org_id: str, key_id: str, request: Request, response: Response) -> None:
    _services(request).developer.revoke_key(_principal(request), org_id, key_id)
    response.status_code = 204


@router.get("/organizations/{org_id}/request-logs")
def request_logs(
    org_id: str,
    request: Request,
    key_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return _services(request).developer.logs(
        _principal(request), org_id, key_id=key_id, since=since, until=until, limit=limit, offset=offset
    )


@router.get("/organizations/{org_id}/usage")
def usage(
    org_id: str,
    request: Request,
    days: int = Query(default=7, ge=1, le=365),
    key_id: str | None = None,
) -> list[dict]:
    return _services(request).developer.usage(
        _principal(request), org_id, days=days, key_id=key_id
    )


__all__ = ["router"]