"""Document-scope authorization (design D4/D5, task 5.3).

The resource row decides the scope: `department_id` comes from the database, never from the client.
`department_id=None` is organisation-level and readable by every active member.
"""

from __future__ import annotations

from typing import Any

from app.identity import permissions as perm
from app.identity.authorization import AuthorizationService, ResourceScope
from app.identity.errors import AuthRequired, Forbidden
from app.identity.store import IdentityStore
from app.shared.ports import Principal


class DocumentAccess:
    def __init__(self, store: IdentityStore, host: Any, authorization: AuthorizationService) -> None:
        self.store = store
        self.host = host
        self.authorization = authorization

    def organization(self, workspace_id: str) -> dict[str, Any] | None:
        return self.store.get_org_by_workspace(workspace_id)

    def scope(self, document: dict[str, Any]) -> ResourceScope:
        organization = self.organization(document["workspace_id"])
        if not organization:
            raise Forbidden()
        return ResourceScope(
            org_id=organization["org_id"],
            department_id=document.get("department_id"),
            workspace_id=document["workspace_id"],
        )

    def authorize(
        self, principal: Principal | None, action: str, document: dict[str, Any]
    ) -> None:
        if principal is None:
            raise AuthRequired()
        scope = self.scope(document)
        if document.get("department_id") is None and action == perm.DOCUMENT_READ:
            # Organisation-level documents: any active member may read (design D4).
            if principal.auth_kind == "api_key":
                if perm.DOCUMENT_READ not in principal.permissions:
                    raise Forbidden()
                return
            if self.store.has_active_membership(scope.org_id, principal.user_id):
                return
            raise Forbidden()
        self.authorization.authorize(principal, action, scope)

    def can_read(self, principal: Principal | None, document_id: str | None) -> bool:
        """Evidence filter: unknown ids (knowledge corpus/web) are not document-scoped."""
        if not document_id:
            return True
        document = self.host.get_document(document_id)
        if not document:
            return True
        try:
            self.authorize(principal, perm.DOCUMENT_READ, document)
        except (AuthRequired, Forbidden):
            return False
        return True


__all__ = ["DocumentAccess"]