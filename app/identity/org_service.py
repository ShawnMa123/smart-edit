"""Organizations, departments, members, roles and invites (design D2/D3/D11, tasks 3-4).

Every mutation goes through `AuthorizationService`, and inviting/granting a role requires the caller to
already own every permission that role carries — no one can grant themselves up the hierarchy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.identity import permissions as perm
from app.identity.activity_service import ActivityService
from app.identity.authorization import AuthorizationService, ResourceScope
from app.identity.errors import (
    AuthRequired,
    Conflict,
    Forbidden,
    InvalidRequest,
    NotFound,
)
from app.identity.settings import AuthSettings
from app.identity.store import IdentityStore, new_id
from app.identity.tokens import hash_token, new_token
from app.shared.ports import Principal


class OrganizationService:
    def __init__(
        self,
        store: IdentityStore,
        authorization: AuthorizationService,
        activity: ActivityService | None = None,
        settings: AuthSettings | None = None,
    ) -> None:
        self.store = store
        self.authorization = authorization
        self.activity = activity
        self.settings = settings

    # --- helpers ------------------------------------------------------------------------------
    def _org(self, org_id: str) -> dict[str, Any]:
        organization = self.store.get_organization(org_id)
        if not organization:
            raise NotFound("organisation not found")
        return organization

    def _scope(self, org_id: str, department_id: str | None = None) -> ResourceScope:
        organization = self._org(org_id)
        return ResourceScope(
            org_id=org_id,
            department_id=department_id,
            workspace_id=organization["workspace_id"],
        )

    def _member(self, principal: Principal | None, org_id: str) -> None:
        self.authorization.require_member(principal, org_id)

    def _record(
        self,
        org_id: str,
        department_id: str | None,
        principal: Principal,
        action: str,
        resource_type: str,
        resource_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if self.activity is None:
            return
        self.activity.safe_record(
            org_id=org_id,
            department_id=department_id,
            actor_user_id=principal.user_id,
            actor_label=None,
            kind="organization",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )

    # --- organizations ------------------------------------------------------------------------
    def create(self, principal: Principal | None, payload: dict[str, Any]) -> dict[str, Any]:
        if principal is None:
            raise AuthRequired()
        name = (payload.get("name") or "").strip()
        if not name:
            raise InvalidRequest("organisation name is required")
        return self.store.create_organization(
            org_id=new_id("org"),
            name=name,
            slug=(payload.get("slug") or "").strip() or None,
            owner_user_id=principal.user_id,
        )

    def list(self, principal: Principal | None) -> list[dict[str, Any]]:
        if principal is None:
            raise AuthRequired()
        return self.store.list_organizations_for_user(principal.user_id)

    def get(self, principal: Principal | None, org_id: str) -> dict[str, Any]:
        self._member(principal, org_id)
        return self._org(org_id)

    def update(
        self, principal: Principal | None, org_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.authorization.authorize(principal, perm.ORG_MANAGE, self._scope(org_id))
        name = (payload.get("name") or "").strip() or None
        slug = (payload.get("slug") or "").strip() or None
        updated = self.store.update_organization(org_id, name=name, slug=slug)
        if not updated:
            raise NotFound("organisation not found")
        return updated

    def delete(self, principal: Principal | None, org_id: str) -> None:
        self.authorization.authorize(principal, perm.ORG_MANAGE, self._scope(org_id))
        if not self.store.delete_organization(org_id):
            raise NotFound("organisation not found")

    # --- departments --------------------------------------------------------------------------
    def departments(self, principal: Principal | None, org_id: str) -> list[dict[str, Any]]:
        self._member(principal, org_id)
        return self.store.list_departments(org_id)

    def create_department(
        self, principal: Principal | None, org_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        name = (payload.get("name") or "").strip()
        if not name:
            raise InvalidRequest("department name is required")
        parent_id = (payload.get("parent_id") or "").strip() or None
        if parent_id:
            parent = self.store.get_department(parent_id)
            if not parent or parent["org_id"] != org_id:
                raise InvalidRequest("parent department is not in this organisation")
        self.authorization.authorize(
            principal, perm.DEPARTMENT_MANAGE, self._scope(org_id, parent_id)
        )
        department = self.store.create_department(
            department_id=new_id("dept"), org_id=org_id, parent_id=parent_id, name=name
        )
        self._record(
            org_id,
            parent_id,
            principal,
            "department created",
            "department",
            department["department_id"],
            {"name": name},
        )
        return department

    def update_department(
        self,
        principal: Principal | None,
        org_id: str,
        department_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        department = self.store.get_department(department_id)
        if not department or department["org_id"] != org_id:
            raise NotFound("department not found")
        self.authorization.authorize(
            principal, perm.DEPARTMENT_MANAGE, self._scope(org_id, department_id)
        )
        if "name" in payload:
            name = (payload.get("name") or "").strip()
            if not name:
                raise InvalidRequest("department name is required")
            self.store.db.execute(
                "UPDATE departments SET name = %s WHERE department_id = %s", (name, department_id)
            )
        if "parent_id" in payload:
            parent_id = (payload.get("parent_id") or "").strip() or None
            if parent_id:
                parent = self.store.get_department(parent_id)
                if not parent or parent["org_id"] != org_id:
                    raise InvalidRequest("parent department is not in this organisation")
            self.store.move_department(department_id, parent_id)
        self._record(
            org_id, department_id, principal, "department updated", "department", department_id
        )
        return self.store.get_department(department_id) or {}

    def delete_department(
        self, principal: Principal | None, org_id: str, department_id: str
    ) -> None:
        department = self.store.get_department(department_id)
        if not department or department["org_id"] != org_id:
            raise NotFound("department not found")
        self.authorization.authorize(
            principal, perm.DEPARTMENT_MANAGE, self._scope(org_id, department_id)
        )
        self.store.delete_department(department_id)
        self._record(org_id, None, principal, "department deleted", "department", department_id)
# --- members & roles ----------------------------------------------------------------------
    def members(self, principal: Principal | None, org_id: str) -> list[dict[str, Any]]:
        self._member(principal, org_id)
        assignments = self.store.list_assignments(org_id)
        by_user: dict[str, list[dict[str, Any]]] = {}
        for assignment in assignments:
            by_user.setdefault(assignment["user_id"], []).append(assignment)
        items = []
        for member in self.store.list_members(org_id):
            items.append({**member, "role_assignments": by_user.get(member["user_id"], [])})
        return items

    def _can_grant(
        self, principal: Principal | None, org_id: str, role_key: str, department_id: str | None
    ) -> None:
        if not perm.is_known_role(role_key):
            raise InvalidRequest(f"unknown role {role_key!r}")
        scope = self._scope(org_id, department_id)
        needed = set(perm.role_permissions(role_key))
        available = self.authorization.permissions(principal, scope)
        if not needed <= available:
            raise Forbidden("you cannot grant a role that exceeds your own permissions")

    def assign_role(
        self, principal: Principal | None, org_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        user_id = (payload.get("user_id") or "").strip()
        role_key = (payload.get("role_key") or "").strip()
        scope_type = (payload.get("scope_type") or "org").strip()
        scope_id = (payload.get("scope_id") or "").strip() or org_id
        if not user_id:
            raise InvalidRequest("user_id is required")
        if scope_type not in {"org", "department"}:
            raise InvalidRequest("scope_type must be org or department")
        membership = self.store.get_membership(org_id, user_id)
        if not membership or membership["status"] != "active":
            raise InvalidRequest("the target user is not an active member")
        department_id: str | None = None
        if scope_type == "department":
            department = self.store.get_department(scope_id)
            if not department or department["org_id"] != org_id:
                raise InvalidRequest("department is not in this organisation")
            department_id = scope_id
        else:
            scope_id = org_id
        self.authorization.authorize(principal, perm.ROLE_MANAGE, self._scope(org_id, department_id))
        self._can_grant(principal, org_id, role_key, department_id)
        assignment = self.store.create_assignment(
            org_id=org_id,
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            role_key=role_key,
            granted_by=principal.user_id if principal else None,
        )
        self._record(
            org_id,
            department_id,
            principal,
            "role assigned",
            "role_assignment",
            assignment["assignment_id"],
            {"role_key": role_key, "user_id": user_id},
        )
        return assignment

    def remove_assignment(
        self, principal: Principal | None, org_id: str, assignment_id: str
    ) -> None:
        assignment = next(
            (a for a in self.store.list_assignments(org_id) if a["assignment_id"] == assignment_id),
            None,
        )
        if not assignment:
            raise NotFound("role assignment not found")
        department_id = assignment["scope_id"] if assignment["scope_type"] == "department" else None
        self.authorization.authorize(principal, perm.ROLE_MANAGE, self._scope(org_id, department_id))
        self._guard_last_admin(org_id, assignment["user_id"], assignment["role_key"])
        self.store.delete_assignment(org_id, assignment_id)
        self._record(
            org_id,
            department_id,
            principal,
            "role revoked",
            "role_assignment",
            assignment_id,
            {"role_key": assignment["role_key"], "user_id": assignment["user_id"]},
        )

    def _guard_last_admin(self, org_id: str, user_id: str, role_key: str | None = None) -> None:
        if role_key != perm.ROLE_ORG_ADMIN:
            return
        if self.store.count_active_org_admins(org_id) <= 1:
            raise Conflict(
                "last_admin",
                "the organisation must keep at least one active organisation administrator",
            )

    def set_member_status(
        self, principal: Principal | None, org_id: str, user_id: str, status: str
    ) -> dict[str, Any]:
        if status not in {"active", "suspended", "removed"}:
            raise InvalidRequest("status must be active, suspended or removed")
        membership = self.store.get_membership(org_id, user_id)
        if not membership:
            raise NotFound("member not found")
        scope_department = membership.get("department_id")
        self.authorization.authorize(
            principal, perm.MEMBER_MANAGE, self._scope(org_id, scope_department)
        )
        assignments = self.store.list_assignments(org_id, user_id)
        is_org_admin = any(
            item["role_key"] == perm.ROLE_ORG_ADMIN and item["scope_type"] == "org"
            for item in assignments
        )
        if status != "active" and is_org_admin:
            self._guard_last_admin(org_id, user_id, perm.ROLE_ORG_ADMIN)
        updated = self.store.set_membership_status(org_id=org_id, user_id=user_id, status=status)
        if status != "active":
            # Revoking a membership revokes its grants; additive-only means deleting assignments.
            for assignment in assignments:
                self.store.delete_assignment(org_id, assignment["assignment_id"])
        self._record(
            org_id,
            scope_department,
            principal,
            f"member {status}",
            "membership",
            user_id,
        )
        return updated or {}
# --- invites (v1: copyable link, no email) ------------------------------------------------
    def invite(
        self, principal: Principal | None, org_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        email = (payload.get("email") or "").strip().lower()
        role_key = (payload.get("role_key") or "").strip()
        department_id = (payload.get("department_id") or "").strip() or None
        if "@" not in email or " " in email:
            raise InvalidRequest("a valid email address is required")
        if department_id:
            department = self.store.get_department(department_id)
            if not department or department["org_id"] != org_id:
                raise InvalidRequest("department is not in this organisation")
        self.authorization.authorize(
            principal, perm.INVITE_MANAGE, self._scope(org_id, department_id)
        )
        self._can_grant(principal, org_id, role_key, department_id)
        token = new_token()
        ttl = self.settings.invite_ttl_seconds if self.settings else 72 * 3600
        invite = self.store.create_invite(
            invite_id=new_id("inv"),
            org_id=org_id,
            department_id=department_id,
            email=email,
            role_key=role_key,
            invited_by=principal.user_id if principal else "",
            token_hash=hash_token(token),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )
        self._record(
            org_id,
            department_id,
            principal,
            "invite created",
            "invite",
            invite["invite_id"],
            {"email": email, "role_key": role_key},
        )
        # The raw token is returned exactly once; only its hash is stored.
        return {
            **{key: value for key, value in invite.items() if key != "token_hash"},
            "invite_token": token,
            "accept_path": f"/invites/{token}",
            "expires_in_seconds": ttl,
        }

    def invites(self, principal: Principal | None, org_id: str) -> list[dict[str, Any]]:
        self.authorization.authorize(principal, perm.INVITE_MANAGE, self._scope(org_id))
        return [
            {key: value for key, value in row.items() if key != "token_hash"}
            for row in self.store.list_invites(org_id)
        ]

    def revoke_invite(self, principal: Principal | None, org_id: str, invite_id: str) -> None:
        self.authorization.authorize(principal, perm.INVITE_MANAGE, self._scope(org_id))
        if not self.store.revoke_invite(org_id, invite_id):
            raise NotFound("invite not found or already accepted")

    def accept_invite(self, principal: Principal | None, token: str) -> dict[str, Any]:
        if principal is None:
            raise AuthRequired()
        invite = self.store.get_invite_by_hash(hash_token(token))
        if not invite:
            raise NotFound("invite not found")
        if invite.get("accepted_at"):
            raise Conflict("invite_used", "this invite has already been accepted")
        if invite.get("revoked_at"):
            raise Conflict("invite_revoked", "this invite has been revoked")
        try:
            expires = datetime.fromisoformat(invite["expires_at"])
        except (KeyError, ValueError):
            raise Conflict("invite_expired", "this invite is no longer valid") from None
        if expires <= datetime.now(timezone.utc):
            raise Conflict("invite_expired", "this invite is no longer valid")
        user = self.store.get_user(principal.user_id)
        if not user:
            raise AuthRequired()
        if user["email"].lower() != invite["email"].lower():
            raise Forbidden("this invite was issued to another email address")
        accepted = self.store.accept_invite(
            invite["invite_id"], principal.user_id, new_id("mem")
        )
        if not accepted:
            raise Conflict("invite_used", "this invite has already been accepted")
        self._record(
            invite["org_id"],
            invite.get("department_id"),
            principal,
            "invite accepted",
            "membership",
            principal.user_id,
            {"role_key": invite["role_key"]},
        )
        return {
            "org_id": invite["org_id"],
            "department_id": invite.get("department_id"),
            "role_key": invite["role_key"],
        }


__all__ = ["OrganizationService"]