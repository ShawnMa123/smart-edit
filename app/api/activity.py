"""Activity feed HTTP surface (design D7, task 7.2)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.identity.bootstrap import IdentityServices

router = APIRouter(prefix="/activity", tags=["activity"])


def _services(request: Request) -> IdentityServices:
    services = request.app.state.identity
    services.require_pg()
    return services


def _principal(request: Request):
    return _services(request).principal.resolve(request)


@router.get("")
def list_activity(
    request: Request,
    org_id: str,
    scope: str = Query(default="all", pattern="^(all|my_department)$"),
    unread: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    return _services(request).activity.list(
        _principal(request), org_id, scope=scope, unread=unread, cursor=cursor, limit=limit
    )


@router.get("/unread-count")
def unread_count(
    request: Request,
    org_id: str,
    scope: str = Query(default="all", pattern="^(all|my_department)$"),
) -> dict:
    return {
        "unread_count": _services(request).activity.unread_count(
            _principal(request), org_id, scope=scope
        )
    }


@router.post("/{event_id}/read")
def mark_read(event_id: str, request: Request, org_id: str) -> dict:
    _services(request).activity.mark_read(_principal(request), org_id, event_id)
    return {"status": "read"}


@router.post("/read-all")
def mark_all_read(
    request: Request,
    org_id: str,
    scope: str = Query(default="all", pattern="^(all|my_department)$"),
) -> dict:
    marked = _services(request).activity.mark_all_read(_principal(request), org_id, scope=scope)
    return {"marked_read": marked}


__all__ = ["router"]