"""Permission catalog and role definitions (design D3 / task 4.1).

`authorize()` checks permission names, never role names, so a new role only changes this catalog.
Inheritance is additive: effective permissions are the union of org-level assignments and
assignments on the resource department's ancestor chain. There is deliberately no deny list.
"""

from __future__ import annotations

# --- permissions -----------------------------------------------------------------------------
ORG_MANAGE = "org.manage"
DEPARTMENT_MANAGE = "department.manage"
MEMBER_MANAGE = "member.manage"
ROLE_MANAGE = "role.manage"
INVITE_MANAGE = "invite.manage"
DOCUMENT_READ = "document.read"
DOCUMENT_CREATE = "document.create"
DOCUMENT_EDIT = "document.edit"
DOCUMENT_LOCK = "document.lock"
DOCUMENT_SHARE = "document.share"
DOCUMENT_EXPORT = "document.export"
AUTOMATION_USE = "automation.use"
AUTOMATION_APPLY = "automation.apply"
ASSISTANT_USE = "assistant.use"
ACTIVITY_READ = "activity.read"
DEVELOPER_MANAGE = "developer.manage"
AUDIT_READ = "audit.read"

PERMISSIONS: tuple[str, ...] = (
    ORG_MANAGE,
    DEPARTMENT_MANAGE,
    MEMBER_MANAGE,
    ROLE_MANAGE,
    INVITE_MANAGE,
    DOCUMENT_READ,
    DOCUMENT_CREATE,
    DOCUMENT_EDIT,
    DOCUMENT_LOCK,
    DOCUMENT_SHARE,
    DOCUMENT_EXPORT,
    AUTOMATION_USE,
    AUTOMATION_APPLY,
    ASSISTANT_USE,
    ACTIVITY_READ,
    DEVELOPER_MANAGE,
    AUDIT_READ,
)

# Document-level permissions a department-scoped resource can require.
DOCUMENT_PERMISSIONS = frozenset(
    {
        DOCUMENT_READ,
        DOCUMENT_CREATE,
        DOCUMENT_EDIT,
        DOCUMENT_LOCK,
        DOCUMENT_SHARE,
        DOCUMENT_EXPORT,
    }
)

# API Key scopes are a subset of the same catalog, so a Key can never exceed a permission.
API_KEY_SCOPES = tuple(
    permission
    for permission in PERMISSIONS
    if permission
    in {
        DOCUMENT_READ,
        DOCUMENT_CREATE,
        DOCUMENT_EDIT,
        DOCUMENT_LOCK,
        DOCUMENT_EXPORT,
        AUTOMATION_USE,
        AUTOMATION_APPLY,
        ASSISTANT_USE,
        ACTIVITY_READ,
    }
)

ROLE_ORG_ADMIN = "org_admin"
ROLE_DEPT_ADMIN = "dept_admin"
ROLE_MEMBER = "member"
ROLE_AUDITOR = "auditor"

ROLE_CATALOG: dict[str, dict] = {
    ROLE_ORG_ADMIN: {
        "name": "Organisation administrator",
        "scope_level": "org",
        "permissions": PERMISSIONS,
    },
    ROLE_DEPT_ADMIN: {
        "name": "Department administrator",
        "scope_level": "department",
        "permissions": (
            DEPARTMENT_MANAGE,
            MEMBER_MANAGE,
            ROLE_MANAGE,
            INVITE_MANAGE,
            DOCUMENT_READ,
            DOCUMENT_CREATE,
            DOCUMENT_EDIT,
            DOCUMENT_LOCK,
            DOCUMENT_SHARE,
            DOCUMENT_EXPORT,
            AUTOMATION_USE,
            AUTOMATION_APPLY,
            ASSISTANT_USE,
            ACTIVITY_READ,
            AUDIT_READ,
        ),
    },
    ROLE_MEMBER: {
        "name": "Member",
        "scope_level": "department",
        "permissions": (
            DOCUMENT_READ,
            DOCUMENT_CREATE,
            DOCUMENT_EDIT,
            DOCUMENT_LOCK,
            DOCUMENT_EXPORT,
            AUTOMATION_USE,
            AUTOMATION_APPLY,
            ASSISTANT_USE,
            ACTIVITY_READ,
        ),
    },
    ROLE_AUDITOR: {
        "name": "Auditor",
        "scope_level": "department",
        "permissions": (DOCUMENT_READ, ACTIVITY_READ, AUDIT_READ),
    },
}

ROLE_KEYS = tuple(ROLE_CATALOG)

# Fine-grained role grants an inviter must own before handing the role out (task 4.3).
ROLE_GRANT_PERMISSION = ROLE_MANAGE


def role_permissions(role_key: str) -> tuple[str, ...]:
    role = ROLE_CATALOG.get(role_key)
    return tuple(role["permissions"]) if role else ()


def is_known_role(role_key: str) -> bool:
    return role_key in ROLE_CATALOG


def is_known_permission(permission: str) -> bool:
    return permission in PERMISSIONS


__all__ = [
    "ACTIVITY_READ",
    "API_KEY_SCOPES",
    "ASSISTANT_USE",
    "AUDIT_READ",
    "AUTOMATION_APPLY",
    "AUTOMATION_USE",
    "DEPARTMENT_MANAGE",
    "DEVELOPER_MANAGE",
    "DOCUMENT_CREATE",
    "DOCUMENT_EDIT",
    "DOCUMENT_EXPORT",
    "DOCUMENT_LOCK",
    "DOCUMENT_PERMISSIONS",
    "DOCUMENT_READ",
    "DOCUMENT_SHARE",
    "INVITE_MANAGE",
    "MEMBER_MANAGE",
    "ORG_MANAGE",
    "PERMISSIONS",
    "ROLE_AUDITOR",
    "ROLE_CATALOG",
    "ROLE_DEPT_ADMIN",
    "ROLE_GRANT_PERMISSION",
    "ROLE_KEYS",
    "ROLE_MEMBER",
    "ROLE_ORG_ADMIN",
    "ROLE_MANAGE",
    "is_known_permission",
    "is_known_role",
    "role_permissions",
]