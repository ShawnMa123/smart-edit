"""Organizations, departments, members, roles and invites (`/organizations`)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.identity.bootstrap import IdentityServices
from app.identity.schemas import (
    DepartmentCreate,
    DepartmentUpdate,
    InviteAccept,
    InviteCreate,
    MemberStatusUpdate,
    OrganizationCreate,
    OrganizationUpdate,
    RoleAssignmentCreate,
)

router = APIRouter(tags=["organizations"])


def _services(request: Request) -> IdentityServices:
    services = request.app.state.identity
    services.require_pg()
    return services


def _principal(request: Request):
    return _services(request).principal.resolve(request)


@router.get("/organizations")
def list_organizations(request: Request) -> list[dict]:
    return _services(request).organizations.list(_principal(request))


@router.post("/organizations", status_code=201)
def create_organization(request: Request, payload: OrganizationCreate) -> dict:
    return _services(request).organizations.create(_principal(request), payload.model_dump())


@router.patch("/organizations/{org_id}")
def update_organization(org_id: str, request: Request, payload: OrganizationUpdate) -> dict:
    return _services(request).organizations.update(
        _principal(request), org_id, payload.model_dump(exclude_unset=True)
    )


@router.delete("/organizations/{org_id}", status_code=204)
def delete_organization(org_id: str, request: Request, response: Response) -> None:
    _services(request).organizations.delete(_principal(request), org_id)
    response.status_code = 204


@router.get("/organizations/{org_id}")
def get_organization(org_id: str, request: Request) -> dict:
    return _services(request).organizations.get(_principal(request), org_id)


@router.get("/organizations/{org_id}/departments")
def list_departments(org_id: str, request: Request) -> list[dict]:
    return _services(request).organizations.departments(_principal(request), org_id)


@router.post("/organizations/{org_id}/departments", status_code=201)
def create_department(org_id: str, request: Request, payload: DepartmentCreate) -> dict:
    return _services(request).organizations.create_department(
        _principal(request), org_id, payload.model_dump()
    )


@router.patch("/organizations/{org_id}/departments/{department_id}")
def update_department(
    org_id: str, department_id: str, request: Request, payload: DepartmentUpdate
) -> dict:
    return _services(request).organizations.update_department(
        _principal(request), org_id, department_id, payload.model_dump(exclude_unset=True)
    )


@router.delete("/organizations/{org_id}/departments/{department_id}", status_code=204)
def delete_department(org_id: str, department_id: str, request: Request, response: Response) -> None:
    _services(request).organizations.delete_department(_principal(request), org_id, department_id)
    response.status_code = 204


@router.get("/organizations/{org_id}/members")
def list_members(org_id: str, request: Request) -> list[dict]:
    return _services(request).organizations.members(_principal(request), org_id)


@router.patch("/organizations/{org_id}/members/{user_id}")
def update_member(
    org_id: str, user_id: str, request: Request, payload: MemberStatusUpdate
) -> dict:
    return _services(request).organizations.set_member_status(
        _principal(request), org_id, user_id, payload.status
    )


@router.post("/organizations/{org_id}/role-assignments", status_code=201)
def assign_role(org_id: str, request: Request, payload: RoleAssignmentCreate) -> dict:
    return _services(request).organizations.assign_role(
        _principal(request), org_id, payload.model_dump()
    )


@router.delete("/organizations/{org_id}/role-assignments/{assignment_id}", status_code=204)
def remove_role_assignment(
    org_id: str, assignment_id: str, request: Request, response: Response
) -> None:
    _services(request).organizations.remove_assignment(
        _principal(request), org_id, assignment_id
    )
    response.status_code = 204


@router.get("/organizations/{org_id}/invites")
def list_invites(org_id: str, request: Request) -> list[dict]:
    return _services(request).organizations.invites(_principal(request), org_id)


@router.post("/organizations/{org_id}/invites", status_code=201)
def create_invite(org_id: str, request: Request, payload: InviteCreate) -> dict:
    return _services(request).organizations.invite(
        _principal(request), org_id, payload.model_dump()
    )


@router.delete("/organizations/{org_id}/invites/{invite_id}", status_code=204)
def revoke_invite(
    org_id: str, invite_id: str, request: Request, response: Response
) -> None:
    _services(request).organizations.revoke_invite(_principal(request), org_id, invite_id)
    response.status_code = 204


@router.post("/invites/accept")
def accept_invite(request: Request, payload: InviteAccept) -> dict:
    return _services(request).organizations.accept_invite(
        _principal(request), payload.invite_token
    )


__all__ = ["router"]