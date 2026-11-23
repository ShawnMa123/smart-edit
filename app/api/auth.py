"""Auth HTTP surface (`/auth`) — tasks 2.2/2.3/3.3.

The raw session token leaves the server only as an HttpOnly cookie; no response body repeats it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.identity.cookies import clear_session_cookie, set_session_cookie
from app.identity.schemas import LoginRequest, RegisterRequest, SwitchOrgRequest
from app.identity.bootstrap import IdentityServices

router = APIRouter(prefix="/auth", tags=["auth"])


def _services(request: Request) -> IdentityServices:
    return request.app.state.identity


@router.post("/register", status_code=201)
def register(request: Request, response: Response, payload: RegisterRequest) -> dict:
    services = _services(request)
    services.require_pg()
    result = services.auth.register(request, payload.model_dump())
    token = result.pop("session_token")
    set_session_cookie(response, token, services.settings)
    return result


@router.post("/login")
def login(request: Request, response: Response, payload: LoginRequest) -> dict:
    services = _services(request)
    services.require_pg()
    result = services.auth.login(request, payload.model_dump())
    token = result.pop("session_token")
    set_session_cookie(response, token, services.settings)
    return result


@router.get("/me")
def me(request: Request) -> dict:
    services = _services(request)
    services.require_pg()
    principal = services.principal.resolve(request)
    return services.auth.me(principal)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    services = _services(request)
    services.require_pg()
    services.auth.logout(request)
    clear_session_cookie(response, services.settings)
    return {"status": "signed_out"}


@router.post("/logout-all")
def logout_all(request: Request, response: Response) -> dict:
    services = _services(request)
    services.require_pg()
    principal = services.principal.resolve(request)
    count = services.auth.logout_all(principal)
    clear_session_cookie(response, services.settings)
    return {"status": "signed_out", "revoked_sessions": count}


@router.post("/active-org")
def switch_org(request: Request, payload: SwitchOrgRequest) -> dict:
    services = _services(request)
    services.require_pg()
    principal = services.principal.resolve(request)
    return services.auth.switch_org(request, principal, payload.org_id)


__all__ = ["router"]