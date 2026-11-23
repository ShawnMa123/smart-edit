"""Developer platform: API keys and request logs (design D8, tasks 8.1-8.3).

The raw key is returned exactly once; only its hash and a display prefix are stored. Usage and logs are
read-only and never include request/response bodies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.identity import permissions as perm
from app.identity.activity_service import ActivityService
from app.identity.authorization import AuthorizationService, ResourceScope
from app.identity.errors import AuthRequired, InvalidRequest, NotFound
from app.identity.store import IdentityStore, new_id
from app.identity.tokens import apikey_lookup, new_api_key, token_prefix
from app.shared.ports import Principal


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidRequest("timestamps must be ISO-8601") from exc


class DeveloperService:
    def __init__(
        self,
        store: IdentityStore,
        authorization: AuthorizationService,
        activity: ActivityService | None = None,
    ) -> None:
        self.store = store
        self.authorization = authorization
        self.activity = activity

    def _scope(self, org_id: str, department_id: str | None = None) -> ResourceScope:
        org = self.store.get_organization(org_id)
        return ResourceScope(
            org_id=org_id,
            department_id=department_id,
            workspace_id=org["workspace_id"] if org else None,
        )

    def _require(self, principal: Principal | None, org_id: str) -> None:
        # `developer.manage` is an organisation-level permission (design D3).
        self.authorization.authorize(principal, perm.DEVELOPER_MANAGE, self._scope(org_id))

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key not in {"key_hash", "token_hash"}}

    def create_key(
        self, principal: Principal | None, org_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if principal is None:
            raise AuthRequired()
        self._require(principal, org_id)
        name = (payload.get("name") or "").strip()
        if not name:
            raise InvalidRequest("key name is required")
        department_id = (payload.get("department_id") or "").strip() or None
        if department_id:
            department = self.store.get_department(department_id)
            if not department or department["org_id"] != org_id:
                raise InvalidRequest("department is not in this organisation")
        scopes = payload.get("scopes") or list(perm.API_KEY_SCOPES)
        if not isinstance(scopes, list) or any(scope not in perm.API_KEY_SCOPES for scope in scopes):
            raise InvalidRequest("scopes must be a subset of the developer scope catalog")
        # A Key never carries more than its creator can do right now (task 8.2).
        available = self.authorization.permissions(principal, self._scope(org_id, department_id))
        if not set(scopes) <= available:
            raise InvalidRequest("scopes must not exceed your own permissions")
        token = new_api_key()
        row = self.store.create_api_key(
            key_id=new_id("key"),
            org_id=org_id,
            department_id=department_id,
            name=name,
            key_hash=apikey_lookup(token),
            prefix=token_prefix(token),
            scopes=scopes,
            created_by=principal.user_id,
            expires_at=_parse_time(payload.get("expires_at")),
        )
        if self.activity:
            self.activity.safe_record(
                org_id=org_id,
                department_id=department_id,
                actor_user_id=principal.user_id,
                actor_label=None,
                kind="developer",
                action="api key created",
                resource_type="api_key",
                resource_id=row["key_id"],
                detail={"name": name, "scopes": scopes},
            )
        return {**self._view(row), "key_token": token}

    def list_keys(self, principal: Principal | None, org_id: str) -> list[dict[str, Any]]:
        self._require(principal, org_id)
        return [self._view(row) for row in self.store.list_api_keys(org_id)]

    def revoke_key(self, principal: Principal | None, org_id: str, key_id: str) -> None:
        self._require(principal, org_id)
        row = self.store.revoke_api_key(org_id, key_id)
        if not row:
            raise NotFound("API key not found or already revoked")
        if self.activity:
            self.activity.safe_record(
                org_id=org_id,
                department_id=row.get("department_id"),
                actor_user_id=principal.user_id if principal else None,
                actor_label=None,
                kind="developer",
                action="api key revoked",
                resource_type="api_key",
                resource_id=key_id,
            )

    # --- logs & usage -------------------------------------------------------------------------
    def logs(
        self,
        principal: Principal | None,
        org_id: str,
        *,
        key_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._require(principal, org_id)
        return self.store.list_request_logs(
            org_id,
            key_id=key_id,
            since=_parse_time(since),
            until=_parse_time(until),
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    def usage(
        self,
        principal: Principal | None,
        org_id: str,
        *,
        days: int = 7,
        key_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require(principal, org_id)
        return self.store.usage(org_id, days=max(1, min(days, 365)), key_id=key_id)


__all__ = ["DeveloperService"]