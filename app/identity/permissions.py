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
# Fine-grained Automation (bank-ops back office) capabilities. The legacy `use` / `apply` scopes are
# still accepted for API keys, but they no longer grant configuration.
AUTOMATION_VIEW = "automation.view"
AUTOMATION_CONFIGURE = "automation.configure"
AUTOMATION_DISPATCH = "automation.dispatch"
AUTOMATION_AUDIT = "automation.audit"
ASSISTANT_USE = "assistant.use"
ACTIVITY_READ = "activity.read"
DEVELOPER_MANAGE = "developer.manage"
AUDIT_READ = "audit.read"
APPROVAL_SUBMIT = "approval.submit"
APPROVAL_FIRST = "approval.first"
APPROVAL_SECOND = "approval.second"
# The counterparty's first review: used when the bank side submits a document, the other company
# (the applicant account in this POC) approves it first, then Compliance.
APPROVAL_COUNTERPARTY = "approval.counterparty"

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
    AUTOMATION_VIEW,
    AUTOMATION_CONFIGURE,
    AUTOMATION_DISPATCH,
    AUTOMATION_AUDIT,
    ASSISTANT_USE,
    ACTIVITY_READ,
    DEVELOPER_MANAGE,
    AUDIT_READ,
    APPROVAL_SUBMIT,
    APPROVAL_FIRST,
    APPROVAL_SECOND,
    APPROVAL_COUNTERPARTY,
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
# Trade-finance workflow roles (`user-management` seed): they are real RBAC roles, not UI labels.
ROLE_APPLICANT = "applicant"
ROLE_BANK_OPS = "bank_ops"
ROLE_COMPLIANCE = "compliance"

ROLE_CATALOG: dict[str, dict] = {
    ROLE_APPLICANT: {
        "name": "Applicant",
        "scope_level": "org",
        "permissions": (
            DOCUMENT_READ,
            DOCUMENT_CREATE,
            DOCUMENT_EDIT,
            DOCUMENT_LOCK,
            DOCUMENT_EXPORT,
            ASSISTANT_USE,
            ACTIVITY_READ,
            APPROVAL_SUBMIT,
            APPROVAL_COUNTERPARTY,
        ),
    },
    ROLE_BANK_OPS: {
        "name": "Bank Operations (First Approver)",
        "scope_level": "org",
        # Bank Operations participates in the shared document workflow: it can create drafts, edit them
        # (and edit after a return), but submitted snapshots stay frozen (the host rejects saves while
        # a submission is pending/approved, for every role). Submission stays with `approval.submit`.
        "permissions": (
            DOCUMENT_READ,
            DOCUMENT_CREATE,
            DOCUMENT_EDIT,
            DOCUMENT_LOCK,
            DOCUMENT_EXPORT,
            AUDIT_READ,
            ACTIVITY_READ,
            ASSISTANT_USE,
            AUTOMATION_VIEW,
            AUTOMATION_CONFIGURE,
            AUTOMATION_DISPATCH,
            AUTOMATION_AUDIT,
            APPROVAL_SUBMIT,
            APPROVAL_FIRST,
        ),
    },
    ROLE_COMPLIANCE: {
        "name": "Compliance (Second Approver)",
        "scope_level": "org",
        "permissions": (
            DOCUMENT_READ,
            DOCUMENT_LOCK,
            DOCUMENT_EXPORT,
            AUDIT_READ,
            ACTIVITY_READ,
            ASSISTANT_USE,
            AUTOMATION_VIEW,
            AUTOMATION_AUDIT,
            APPROVAL_SECOND,
        ),
    },
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
            AUTOMATION_VIEW,
            AUTOMATION_CONFIGURE,
            AUTOMATION_DISPATCH,
            AUTOMATION_AUDIT,
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
    "APPROVAL_FIRST",
    "APPROVAL_SECOND",
    "APPROVAL_SUBMIT",
    "APPROVAL_COUNTERPARTY",
    "ASSISTANT_USE",
    "AUDIT_READ",
    "AUTOMATION_APPLY",
    "AUTOMATION_AUDIT",
    "AUTOMATION_CONFIGURE",
    "AUTOMATION_DISPATCH",
    "AUTOMATION_USE",
    "AUTOMATION_VIEW",
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
    "ROLE_APPLICANT",
    "ROLE_BANK_OPS",
    "ROLE_CATALOG",
    "ROLE_COMPLIANCE",
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