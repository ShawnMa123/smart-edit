"""Server-side activity feed (design D7, tasks 7.1-7.2).

Writers call `safe_record` after the domain action; an activity failure must not roll back the
business change. Payloads are filtered so document text, passwords and tokens can never land in the
feed. Readers only see events their department roles allow.
"""

from __future__ import annotations

import logging
from typing import Any

from app.identity import permissions as perm
from app.identity.errors import Forbidden
from app.identity.store import IdentityStore, new_id
from app.shared.ports import Principal

logger = logging.getLogger("identity.activity")

_SENSITIVE = (
    "password",
    "token",
    "secret",
    "content",
    "body",
    "text",
    "key",
    "authorization",
    "cookie",
)
_MAX_STRING = 160


def _sanitize(detail: dict[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (detail or {}).items():
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE):
            continue
        if isinstance(value, str):
            clean[key] = value[:_MAX_STRING]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list):
            clean[key] = [item for item in value[:20] if isinstance(item, (str, int, float, bool))]
        # Nested structures are not needed for audit and are the easiest place to leak content.
    return clean


class ActivityService:
    def __init__(self, store: IdentityStore) -> None:
        self.store = store

    def record(
        self,
        *,
        org_id: str,
        department_id: str | None,
        actor_user_id: str | None,
        actor_label: str | None,
        kind: str,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.append_activity(
            event_id=new_id("evt"),
            org_id=org_id,
            department_id=department_id,
            actor_user_id=actor_user_id,
            actor_label=actor_label,
            kind=kind,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=_sanitize(detail),
        )

    def safe_record(self, **kwargs: Any) -> None:
        try:
            self.record(**kwargs)
        except Exception:  # noqa: BLE001 - activity must never break the business action
            logger.exception("activity write failed: %s", kwargs.get("action"))

    # --- reads --------------------------------------------------------------------------------
    def _require_reader(self, principal: Principal, org_id: str) -> None:
        if principal.auth_kind == "api_key":
            if perm.ACTIVITY_READ not in principal.permissions:
                raise Forbidden()
            return
        # Org-level events are visible to every active member; department events are filtered below.
        if not self.store.has_active_membership(org_id, principal.user_id):
            raise Forbidden()

    def _departments(
        self, principal: Principal, org_id: str, scope: str
    ) -> tuple[list[str] | None, bool]:
        if scope != "my_department":
            return None, False
        membership = self.store.get_membership(org_id, principal.user_id) or {}
        department_id = membership.get("department_id")
        if not department_id:
            return [], False
        return self.store.department_descendants(department_id), True

    def list(
        self,
        principal: Principal | None,
        org_id: str,
        *,
        scope: str = "all",
        unread: bool = False,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if principal is None:
            raise Forbidden()
        self._require_reader(principal, org_id)
        departments, include_org_level = self._departments(principal, org_id, scope)
        page = self.store.list_activity(
            principal.user_id,
            org_id,
            department_ids=departments,
            unread=unread,
            limit=limit,
            cursor=cursor,
            include_org_level=include_org_level,
        )
        unread_count = self.store.count_activity(
            principal.user_id,
            org_id,
            department_ids=departments,
            unread=True,
            include_org_level=include_org_level,
        )
        return {
            "items": [_view(item) for item in page["items"]],
            "next_cursor": page["next_cursor"],
            "unread_count": unread_count,
        }

    def unread_count(self, principal: Principal | None, org_id: str, scope: str = "all") -> int:
        if principal is None:
            raise Forbidden()
        self._require_reader(principal, org_id)
        departments, include_org_level = self._departments(principal, org_id, scope)
        return self.store.count_activity(
            principal.user_id,
            org_id,
            department_ids=departments,
            unread=True,
            include_org_level=include_org_level,
        )

    def mark_read(self, principal: Principal | None, org_id: str, event_id: str) -> None:
        if principal is None:
            raise Forbidden()
        self._require_reader(principal, org_id)
        if not self.store.mark_activity_read(principal.user_id, event_id):
            raise Forbidden()

    def mark_all_read(self, principal: Principal | None, org_id: str, scope: str = "all") -> int:
        if principal is None:
            raise Forbidden()
        self._require_reader(principal, org_id)
        departments, include_org_level = self._departments(principal, org_id, scope)
        return self.store.mark_all_activity_read(
            principal.user_id,
            org_id,
            department_ids=departments,
            include_org_level=include_org_level,
        )


def _view(row: dict[str, Any]) -> dict[str, Any]:
    actor_label = row.get("actor_display_name") or row.get("actor_label")
    return {
        "event_id": row.get("event_id"),
        "kind": row.get("kind"),
        "action": row.get("action"),
        "resource_type": row.get("resource_type"),
        "resource_id": row.get("resource_id"),
        "detail": row.get("detail_json") or {},
        "created_at": row.get("created_at"),
        "is_read": bool(row.get("is_read")),
        # A removed member keeps their history; the UI shows “removed user”, never a blank row.
        "actor": {
            "user_id": row.get("actor_user_id"),
            "label": actor_label if actor_label else "Removed user",
            "removed": actor_label is None and bool(row.get("actor_user_id")),
        },
        "department_id": row.get("department_id"),
    }


__all__ = ["ActivityService"]