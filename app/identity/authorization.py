"""Unified authorization (design D5 / task 5.1).

Every business API calls `authorize(actor, action, resource_scope)`. Resource ids never come from
client claims: the route resolves the resource first, then asks this service with the stored scope.
Results are cached per request through a `ContextVar` so a single request cannot see two answers for
the same scope.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.identity import permissions as perm
from app.identity.errors import AuthRequired, Forbidden
from app.identity.store import IdentityStore
from app.shared.ports import Principal


@dataclass(frozen=True)
class ResourceScope:
    """`department_id=None` means organisation-level (Option B, design D4)."""

    org_id: str
    department_id: str | None = None
    workspace_id: str | None = None


_cache: ContextVar[dict[tuple[str, str, str | None], set[str]] | None] = ContextVar(
    "identity_authorization_cache", default=None
)


def begin_request_cache() -> None:
    _cache.set({})


def end_request_cache() -> None:
    _cache.set(None)


def invalidate_request_cache() -> None:
    _cache.set({})


@dataclass
class AuthorizationService:
    store: IdentityStore
    # Fake mode keeps the pre-existing capability contract; no PG queries are made.
    fake: bool = False

    def permissions(self, principal: Principal, scope: ResourceScope) -> set[str]:
        if self.fake:
            return set(principal.capabilities)
        if principal.user_id.startswith("key:"):
            # Key permissions were intersected with the creator's current grants at authentication.
            return set(principal.permissions)
        if principal.workspace_id != scope.workspace_id and scope.workspace_id is not None:
            return set()
        cache = _cache.get()
        key = (principal.user_id, scope.org_id, scope.department_id)
        if cache is not None and key in cache:
            return cache[key]
        permissions = self.store.permissions_for(
            principal.user_id, scope.org_id, scope.department_id
        )
        if cache is not None:
            cache[key] = permissions
        return permissions

    def authorize(
        self, principal: Principal | None, action: str, scope: ResourceScope
    ) -> None:
        if principal is None:
            raise AuthRequired()
        permissions = self.permissions(principal, scope)
        if action not in permissions:
            raise Forbidden()
        if principal.user_id.startswith("key:"):
            # A department-scoped Key does not extend to sibling departments (task 8.2).
            key_department = principal.department_id
            if key_department and scope.department_id:
                ancestors = self.store.department_ancestors(scope.department_id)
                if key_department not in ancestors:
                    raise Forbidden()

    def can(self, principal: Principal | None, action: str, scope: ResourceScope) -> bool:
        try:
            self.authorize(principal, action, scope)
        except (AuthRequired, Forbidden):
            return False
        return True

    def require_member(self, principal: Principal | None, org_id: str) -> None:
        if principal is None:
            raise AuthRequired()
        if self.fake:
            return
        if not self.store.has_active_membership(org_id, principal.user_id):
            raise Forbidden()


__all__ = [
    "AuthorizationService",
    "ResourceScope",
    "begin_request_cache",
    "end_request_cache",
    "invalidate_request_cache",
]