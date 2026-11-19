"""Request -> Principal resolution (design D1/D10, tasks 2.5 and 8.2).

`AUTH_MODE=fake` keeps the old `X-Demo-User` behaviour. `AUTH_MODE=pg` reads the opaque session
cookie (or an `Authorization: Bearer` API key) and ignores `X-Demo-User` completely.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.identity import permissions as perm
from app.identity.cookies import session_token
from app.identity.errors import AuthRequired
from app.identity.settings import CSRF_REQUEST_VALUE, AuthSettings
from app.identity.store import IdentityStore
from app.identity.tokens import hash_token
from app.shared.adapters import DEFAULT_WORKSPACE
from app.shared.ports import Principal

# Legacy capability names the document/automation/assistant services still call `has()` with.
_CAPABILITY_PERMISSIONS = {
    "read": perm.DOCUMENT_READ,
    "edit": perm.DOCUMENT_EDIT,
    "apply": perm.AUTOMATION_APPLY,
    "use_ai": perm.ASSISTANT_USE,
    "confirm_fields": perm.DOCUMENT_EDIT,
}


def _capabilities(permissions: set[str]) -> tuple[str, ...]:
    found = tuple(
        capability
        for capability, permission in _CAPABILITY_PERMISSIONS.items()
        if permission in permissions
    )
    return found or ("read",)


def _expired(value: str | None) -> bool:
    """None means \"no expiry\" for API keys; session checks require an explicit timestamp."""
    if not value:
        return False
    try:
        return datetime.fromisoformat(value) <= datetime.now(timezone.utc)
    except ValueError:
        return True


class PrincipalAdapter:
    """Implements the `IdentityPort.resolve(request)` shape used by every service."""

    def __init__(self, settings: AuthSettings, store: IdentityStore | None) -> None:
        self.settings = settings
        self.store = store

    def _fake(self, request) -> Principal:
        user = (request.headers.get("x-demo-user") or "user_demo_01").strip() or "user_demo_01"
        raw = request.headers.get("x-demo-capabilities")
        if raw is None:
            capabilities = ("read", "use_ai", "confirm_fields", "edit", "apply")
        else:
            capabilities = tuple(part.strip() for part in raw.split(",") if part.strip())
        return Principal(
            user_id=user,
            workspace_id=DEFAULT_WORKSPACE,
            capabilities=capabilities,
            auth_kind="fake",
        )

    def _api_key(self, request, token: str) -> Principal:
        assert self.store is not None
        row = self.store.get_api_key_by_hash(hash_token(token))
        if not row:
            raise AuthRequired("API key is invalid or revoked")
        if row.get("revoked_at") or _expired(row.get("expires_at")):
            # Attribute the failed request to the key so the developer log shows the 401.
            request.state.api_key = row
            raise AuthRequired("API key is invalid or revoked")
        creator_id = row["created_by"]
        user = self.store.get_user(creator_id)
        if not user or user.get("status") != "active":
            raise AuthRequired("API key owner is no longer active")
        if not self.store.has_active_membership(row["org_id"], creator_id):
            raise AuthRequired("API key owner is no longer an active member")
        org = self.store.get_organization(row["org_id"])
        if not org:
            raise AuthRequired("API key organisation is unavailable")
        # Intersection: scopes ∩ creator's *current* grants (task 8.2). No inherited history.
        creator_permissions = self.store.permissions_for(
            creator_id, row["org_id"], row.get("department_id")
        )
        scopes = set(row.get("scopes_json") or [])
        effective = scopes & creator_permissions
        version = self.store.authorization_version(row["org_id"]) or 0
        self.store.touch_api_key(row["key_id"])
        request.state.api_key = row
        return Principal(
            user_id=f"key:{row['key_id']}",
            workspace_id=org["workspace_id"],
            roles=(),
            authorization_version=f"org:{row['org_id']}:{version}",
            capabilities=_capabilities(effective),
            org_id=row["org_id"],
            department_id=row.get("department_id"),
            auth_kind="api_key",
            permissions=tuple(sorted(effective)),
        )

    def _session(self, request, token: str) -> Principal:
        assert self.store is not None
        session = self.store.get_session_by_token(hash_token(token))
        if not session or not session.get("expires_at") or _expired(session["expires_at"]):
            raise AuthRequired()
        user = self.store.get_user(session["user_id"])
        if not user or user.get("status") != "active":
            raise AuthRequired()
        org_id = session.get("active_org_id")
        if not org_id:
            organizations = self.store.list_organizations_for_user(user["user_id"])
            if not organizations:
                raise AuthRequired("this account has no active organisation")
            org_id = organizations[0]["org_id"]
            self.store.set_active_org(session["session_id"], org_id)
        if not self.store.has_active_membership(org_id, user["user_id"]):
            raise AuthRequired("your membership in this organisation is not active")
        org = self.store.get_organization(org_id)
        if not org:
            raise AuthRequired()
        membership = self.store.get_membership(org_id, user["user_id"]) or {}
        permissions = self.store.permissions_for(user["user_id"], org_id, None)
        version = self.store.authorization_version(org_id) or 0
        request.state.session = session
        return Principal(
            user_id=user["user_id"],
            workspace_id=org["workspace_id"],
            roles=tuple(self.store.roles_for(user["user_id"], org_id)),
            authorization_version=f"org:{org_id}:{version}",
            capabilities=_capabilities(permissions),
            org_id=org_id,
            department_id=membership.get("department_id"),
            auth_kind="user",
            permissions=tuple(sorted(permissions)),
        )

    # --- entry point -------------------------------------------------------------------------
    def resolve(self, request) -> Principal:
        cached = getattr(request.state, "principal", None)
        if cached is not None:
            return cached
        if not self.settings.is_pg:
            principal = self._fake(request)
            request.state.principal = principal
            return principal

        authorization = request.headers.get("authorization") or ""
        if authorization.lower().startswith("bearer "):
            principal = self._api_key(request, authorization.split(" ", 1)[1].strip())
            request.state.principal = principal
            return principal

        token = session_token(request)
        if not token:
            raise AuthRequired()
        principal = self._session(request, token)
        request.state.principal = principal
        return principal


def is_public_path(path: str, method: str) -> bool:
    if path in {"/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}:
        return True
    if method == "POST" and path in {"/auth/register", "/auth/login"}:
        return True
    return False


def requires_csrf(method: str, request) -> bool:
    """Unsafe methods authenticated by cookie need the explicit CSRF signal (design D12)."""
    if method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return False
    if (request.headers.get("authorization") or "").lower().startswith("bearer "):
        return False
    return True


def has_csrf_signal(request) -> bool:
    value = (request.headers.get("x-requested-with") or "").strip().lower()
    return value == CSRF_REQUEST_VALUE


__all__ = ["PrincipalAdapter", "has_csrf_signal", "is_public_path", "requires_csrf"]