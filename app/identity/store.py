"""PostgreSQL data access for identity, organizations, activity and developer keys.

Every write that changes membership/roles/departments also bumps `organizations.authorization_version`
in the same transaction, so a long-running automation/assistant context cannot keep old permissions
(design D5). Only token hashes are stored (design D1/D8).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb

from app.identity import permissions as perm
from app.identity.db import PgDatabase
from app.identity.errors import Conflict


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def row_iso(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: iso(value) for key, value in row.items()}


class IdentityStore:
    def __init__(self, db: PgDatabase) -> None:
        self.db = db

    # --- catalog -----------------------------------------------------------------------------
    def sync_role_catalog(self) -> None:
        """Keep roles/role_permissions aligned with `permissions.ROLE_CATALOG` (task 4.1)."""
        with self.db.transaction() as conn:
            for key, role in perm.ROLE_CATALOG.items():
                conn.execute(
                    "INSERT INTO roles (role_key, name, scope_level) VALUES (%s, %s, %s) "
                    "ON CONFLICT (role_key) DO UPDATE SET name = EXCLUDED.name, "
                    "scope_level = EXCLUDED.scope_level",
                    (key, role["name"], role["scope_level"]),
                )
                conn.execute("DELETE FROM role_permissions WHERE role_key = %s", (key,))
                for permission in role["permissions"]:
                    conn.execute(
                        "INSERT INTO role_permissions (role_key, permission) VALUES (%s, %s) "
                        "ON CONFLICT DO NOTHING",
                        (key, permission),
                    )

    # --- users -------------------------------------------------------------------------------
    def create_user(
        self, *, user_id: str, email: str, password_hash: str, display_name: str
    ) -> dict[str, Any]:
        try:
            row = self.db.fetchone(
                "INSERT INTO users (user_id, email, password_hash, display_name) "
                "VALUES (%s, %s, %s, %s) RETURNING *",
                (user_id, email, password_hash, display_name),
            )
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict("email_taken", "an account with this email already exists") from exc
        return row_iso(row) or {}

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return row_iso(self.db.fetchone("SELECT * FROM users WHERE user_id = %s", (user_id,)))

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone("SELECT * FROM users WHERE lower(email) = lower(%s)", (email,))
        )

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        self.db.execute(
            "UPDATE users SET password_hash = %s, updated_at = now() WHERE user_id = %s",
            (password_hash, user_id),
        )

    # --- sessions ----------------------------------------------------------------------------
    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        active_org_id: str | None,
        expires_at: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> dict[str, Any]:
        row = self.db.fetchone(
            "INSERT INTO sessions (session_id, user_id, token_hash, active_org_id, expires_at, "
            "user_agent, ip) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (session_id, user_id, token_hash, active_org_id, expires_at, user_agent, ip),
        )
        return row_iso(row) or {}

    def get_session_by_token(self, token_hash: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone(
                "SELECT * FROM sessions WHERE token_hash = %s AND revoked_at IS NULL",
                (token_hash,),
            )
        )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return row_iso(self.db.fetchone("SELECT * FROM sessions WHERE session_id = %s", (session_id,)))

    def set_active_org(self, session_id: str, org_id: str) -> None:
        self.db.execute(
            "UPDATE sessions SET active_org_id = %s WHERE session_id = %s", (org_id, session_id)
        )

    def revoke_session(self, session_id: str) -> None:
        self.db.execute(
            "UPDATE sessions SET revoked_at = now() WHERE session_id = %s AND revoked_at IS NULL",
            (session_id,),
        )

    def revoke_all_sessions(self, user_id: str) -> int:
        return self.db.execute(
            "UPDATE sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
            (user_id,),
        )

    # --- login rate limit --------------------------------------------------------------------
    def record_login_failure(self, ip: str, email: str) -> None:
        self.db.execute(
            "INSERT INTO login_attempts (ip, email) VALUES (%s, %s)", (ip, email.lower())
        )

    def recent_failure_count(self, ip: str, email: str, since: datetime) -> int:
        row = self.db.fetchone(
            "SELECT count(*) AS count FROM login_attempts "
            "WHERE ip = %s AND lower(email) = lower(%s) AND failed_at >= %s",
            (ip, email, since),
        )
        return int(row["count"]) if row else 0

    def clear_login_failures(self, ip: str, email: str) -> None:
        self.db.execute(
            "DELETE FROM login_attempts WHERE ip = %s AND lower(email) = lower(%s)",
            (ip, email),
        )

    # --- organizations -----------------------------------------------------------------------
    def create_organization(
        self,
        *,
        org_id: str,
        workspace_id: str | None = None,
        name: str,
        slug: str | None,
        owner_user_id: str,
    ) -> dict[str, Any]:
        # `workspace_id = org_id` (design D2); legacy data keeps the seeded `ws_demo_01`.
        workspace_id = workspace_id or org_id
        try:
            with self.db.transaction() as conn:
                row = conn.execute(
                    "INSERT INTO organizations (org_id, workspace_id, name, slug) "
                    "VALUES (%s, %s, %s, %s) RETURNING *",
                    (org_id, workspace_id, name, slug),
                ).fetchone()
                conn.execute(
                    "INSERT INTO memberships (membership_id, org_id, user_id, status) "
                    "VALUES (%s, %s, %s, 'active')",
                    (new_id("mem"), org_id, owner_user_id),
                )
                conn.execute(
                    "INSERT INTO role_assignments "
                    "(assignment_id, org_id, user_id, scope_type, scope_id, role_key, granted_by) "
                    "VALUES (%s, %s, %s, 'org', %s, %s, %s)",
                    (new_id("asg"), org_id, owner_user_id, org_id, perm.ROLE_ORG_ADMIN, owner_user_id),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict("workspace_taken", "that workspace id is already in use") from exc
        return row_iso(row) or {}

    def get_organization(self, org_id: str) -> dict[str, Any] | None:
        return row_iso(self.db.fetchone("SELECT * FROM organizations WHERE org_id = %s", (org_id,)))

    def get_org_by_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone(
                "SELECT * FROM organizations WHERE workspace_id = %s", (workspace_id,)
            )
        )

    def list_organizations_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT o.*, m.status AS membership_status FROM organizations o "
            "JOIN memberships m ON m.org_id = o.org_id "
            "WHERE m.user_id = %s AND m.status = 'active' ORDER BY o.name",
            (user_id,),
        )
        return [row_iso(row) or {} for row in rows]

    def authorization_version(self, org_id: str) -> int | None:
        row = self.db.fetchone(
            "SELECT authorization_version FROM organizations WHERE org_id = %s", (org_id,)
        )
        return int(row["authorization_version"]) if row else None

    def update_organization(
        self, org_id: str, *, name: str | None = None, slug: str | None = None
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "UPDATE organizations SET name = COALESCE(%s, name), slug = COALESCE(%s, slug) "
            "WHERE org_id = %s RETURNING *",
            (name, slug, org_id),
        )
        return row_iso(row)

    def delete_organization(self, org_id: str) -> bool:
        return (
            self.db.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,)) > 0
        )

    @staticmethod
    def bump_authorization_version(conn: psycopg.Connection, org_id: str) -> int:
        row = conn.execute(
            "UPDATE organizations SET authorization_version = authorization_version + 1 "
            "WHERE org_id = %s RETURNING authorization_version",
            (org_id,),
        ).fetchone()
        return int(row["authorization_version"]) if row else 0

    # --- departments -------------------------------------------------------------------------
    def create_department(
        self, *, department_id: str, org_id: str, parent_id: str | None, name: str
    ) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO departments (department_id, org_id, parent_id, name) "
                "VALUES (%s, %s, %s, %s) RETURNING *",
                (department_id, org_id, parent_id, name),
            ).fetchone()
            conn.execute(
                "INSERT INTO department_closure (ancestor_id, descendant_id, depth) "
                "VALUES (%s, %s, 0)",
                (department_id, department_id),
            )
            if parent_id:
                # Every ancestor of the parent becomes an ancestor of the new node.
                conn.execute(
                    "INSERT INTO department_closure (ancestor_id, descendant_id, depth) "
                    "SELECT ancestor_id, %s, depth + 1 FROM department_closure "
                    "WHERE descendant_id = %s",
                    (department_id, parent_id),
                )
            self.bump_authorization_version(conn, org_id)
        return row_iso(row) or {}

    def get_department(self, department_id: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone("SELECT * FROM departments WHERE department_id = %s", (department_id,))
        )

    def list_departments(self, org_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM departments WHERE org_id = %s ORDER BY name", (org_id,)
        )
        return [row_iso(row) or {} for row in rows]

    def department_ancestors(self, department_id: str) -> list[str]:
        rows = self.db.fetchall(
            "SELECT ancestor_id FROM department_closure WHERE descendant_id = %s "
            "ORDER BY depth DESC",
            (department_id,),
        )
        return [row["ancestor_id"] for row in rows]

    def department_descendants(self, department_id: str) -> list[str]:
        rows = self.db.fetchall(
            "SELECT descendant_id FROM department_closure WHERE ancestor_id = %s",
            (department_id,),
        )
        return [row["descendant_id"] for row in rows]

    def move_department(self, department_id: str, new_parent_id: str | None) -> dict[str, Any]:
        """Move a subtree: the closure is rewritten in one transaction (task 3.2)."""
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT * FROM departments WHERE department_id = %s", (department_id,)
            ).fetchone()
            if current is None:
                return {}
            if new_parent_id:
                if new_parent_id == department_id:
                    raise Conflict("invalid_parent", "a department cannot be its own parent")
                descendants = {
                    row["descendant_id"]
                    for row in conn.execute(
                        "SELECT descendant_id FROM department_closure WHERE ancestor_id = %s",
                        (department_id,),
                    ).fetchall()
                }
                if new_parent_id in descendants:
                    raise Conflict(
                        "invalid_parent", "a department cannot move under one of its descendants"
                    )
            conn.execute(
                "UPDATE departments SET parent_id = %s WHERE department_id = %s",
                (new_parent_id, department_id),
            )
            # Drop links whose ancestor is outside the moved subtree and descendant inside it.
            conn.execute(
                "DELETE FROM department_closure c USING department_closure d "
                "WHERE c.descendant_id = d.descendant_id AND d.ancestor_id = %s "
                "AND c.ancestor_id NOT IN ("
                "  SELECT descendant_id FROM department_closure WHERE ancestor_id = %s)",
                (department_id, department_id),
            )
            if new_parent_id:
                conn.execute(
                    "INSERT INTO department_closure (ancestor_id, descendant_id, depth) "
                    "SELECT sup.ancestor_id, sub.descendant_id, sup.depth + sub.depth + 1 "
                    "FROM department_closure sup, department_closure sub "
                    "WHERE sup.descendant_id = %s AND sub.ancestor_id = %s "
                    "ON CONFLICT DO NOTHING",
                    (new_parent_id, department_id),
                )
            self.bump_authorization_version(conn, current["org_id"])
        return row_iso(
            self.db.fetchone("SELECT * FROM departments WHERE department_id = %s", (department_id,))
        ) or {}

    def delete_department(self, department_id: str) -> bool:
        department = self.db.fetchone(
            "SELECT * FROM departments WHERE department_id = %s", (department_id,)
        )
        if not department:
            return False
        with self.db.transaction() as conn:
            # Children are re-parented to the deleted node's parent before the node goes away.
            conn.execute(
                "UPDATE departments SET parent_id = %s WHERE parent_id = %s",
                (department["parent_id"], department_id),
            )
            conn.execute("DELETE FROM departments WHERE department_id = %s", (department_id,))
            self.bump_authorization_version(conn, department["org_id"])
        self.rebuild_closure(department["org_id"])
        return True

    def rebuild_closure(self, org_id: str) -> None:
        """Maintenance path: recompute the closure from `parent_id` alone."""
        with self.db.transaction() as conn:
            departments = conn.execute(
                "SELECT department_id, parent_id FROM departments WHERE org_id = %s", (org_id,)
            ).fetchall()
            conn.execute(
                "DELETE FROM department_closure WHERE ancestor_id IN "
                "(SELECT department_id FROM departments WHERE org_id = %s)",
                (org_id,),
            )
            parents = {row["department_id"]: row["parent_id"] for row in departments}
            for department_id in parents:
                depth = 0
                cursor = department_id
                seen: set[str] = set()
                while cursor is not None and cursor not in seen:
                    seen.add(cursor)
                    conn.execute(
                        "INSERT INTO department_closure (ancestor_id, descendant_id, depth) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (cursor, department_id, depth),
                    )
                    cursor = parents.get(cursor)
# --- memberships -------------------------------------------------------------------------
    def add_membership(
        self,
        *,
        org_id: str,
        user_id: str,
        department_id: str | None,
        status: str = "active",
    ) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO memberships (membership_id, org_id, user_id, department_id, status) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (org_id, user_id) DO UPDATE SET status = EXCLUDED.status, "
                "department_id = EXCLUDED.department_id, updated_at = now() RETURNING *",
                (new_id("mem"), org_id, user_id, department_id, status),
            ).fetchone()
            self.bump_authorization_version(conn, org_id)
        return row_iso(row) or {}

    def get_membership(self, org_id: str, user_id: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone(
                "SELECT * FROM memberships WHERE org_id = %s AND user_id = %s", (org_id, user_id)
            )
        )

    def get_membership_by_id(self, membership_id: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone("SELECT * FROM memberships WHERE membership_id = %s", (membership_id,))
        )

    def has_active_membership(self, org_id: str, user_id: str) -> bool:
        row = self.db.fetchone(
            "SELECT 1 AS ok FROM memberships WHERE org_id = %s AND user_id = %s AND status = 'active'",
            (org_id, user_id),
        )
        return row is not None

    def list_members(self, org_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT m.*, u.email, u.display_name, d.name AS department_name "
            "FROM memberships m JOIN users u ON u.user_id = m.user_id "
            "LEFT JOIN departments d ON d.department_id = m.department_id "
            "WHERE m.org_id = %s ORDER BY u.display_name",
            (org_id,),
        )
        return [row_iso(row) or {} for row in rows]

    def set_membership_status(
        self, *, org_id: str, user_id: str, status: str, department_id: str | None = None
    ) -> dict[str, Any] | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "UPDATE memberships SET status = %s, "
                "department_id = COALESCE(%s, department_id), updated_at = now() "
                "WHERE org_id = %s AND user_id = %s RETURNING *",
                (status, department_id, org_id, user_id),
            ).fetchone()
            if row is not None:
                self.bump_authorization_version(conn, org_id)
        return row_iso(row)

    def count_active_org_admins(self, org_id: str) -> int:
        row = self.db.fetchone(
            "SELECT count(DISTINCT m.user_id) AS count FROM memberships m "
            "JOIN role_assignments ra ON ra.user_id = m.user_id AND ra.org_id = m.org_id "
            "WHERE m.org_id = %s AND m.status = 'active' AND ra.role_key = %s "
            "AND ra.scope_type = 'org'",
            (org_id, perm.ROLE_ORG_ADMIN),
        )
        return int(row["count"]) if row else 0

    # --- roles -------------------------------------------------------------------------------
    def create_assignment(
        self,
        *,
        org_id: str,
        user_id: str,
        scope_type: str,
        scope_id: str,
        role_key: str,
        granted_by: str | None,
    ) -> dict[str, Any]:
        try:
            with self.db.transaction() as conn:
                row = conn.execute(
                    "INSERT INTO role_assignments "
                    "(assignment_id, org_id, user_id, scope_type, scope_id, role_key, granted_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
                    (new_id("asg"), org_id, user_id, scope_type, scope_id, role_key, granted_by),
                ).fetchone()
                self.bump_authorization_version(conn, org_id)
        except psycopg.errors.UniqueViolation as exc:
            raise Conflict("assignment_exists", "this role is already assigned on that scope") from exc
        return row_iso(row) or {}

    def delete_assignment(self, org_id: str, assignment_id: str) -> dict[str, Any] | None:
        with self.db.transaction() as conn:
            row = conn.execute(
                "DELETE FROM role_assignments WHERE org_id = %s AND assignment_id = %s "
                "RETURNING *",
                (org_id, assignment_id),
            ).fetchone()
            if row is not None:
                self.bump_authorization_version(conn, org_id)
        return row_iso(row)

    def list_assignments(self, org_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT ra.*, r.name AS role_name, r.scope_level FROM role_assignments ra "
            "JOIN roles r ON r.role_key = ra.role_key WHERE ra.org_id = %s"
        )
        params: list[Any] = [org_id]
        if user_id:
            sql += " AND ra.user_id = %s"
            params.append(user_id)
        rows = self.db.fetchall(sql + " ORDER BY ra.created_at", tuple(params))
        return [row_iso(row) or {} for row in rows]

    def permissions_for(
        self, user_id: str, org_id: str, department_id: str | None = None
    ) -> set[str]:
        """Additive union: org-level grants + grants on the department's ancestor chain."""
        rows = self.db.fetchall(
            "SELECT DISTINCT rp.permission FROM role_assignments ra "
            "JOIN role_permissions rp ON rp.role_key = ra.role_key "
            "WHERE ra.user_id = %s AND ra.org_id = %s AND ("
            "  ra.scope_type = 'org' OR ("
            "    %s::text IS NOT NULL AND ra.scope_type = 'department' AND ra.scope_id IN ("
            "      SELECT ancestor_id FROM department_closure WHERE descendant_id = %s"
            "    )"
            "  )"
            ")",
            (user_id, org_id, department_id, department_id),
        )
        return {row["permission"] for row in rows}

    def roles_for(self, user_id: str, org_id: str) -> list[str]:
        rows = self.db.fetchall(
            "SELECT DISTINCT role_key FROM role_assignments WHERE user_id = %s AND org_id = %s",
            (user_id, org_id),
        )
        return [row["role_key"] for row in rows]

    # --- invites -----------------------------------------------------------------------------
    def create_invite(
        self,
        *,
        invite_id: str,
        org_id: str,
        department_id: str | None,
        email: str,
        role_key: str,
        invited_by: str,
        token_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        row = self.db.fetchone(
            "INSERT INTO invites (invite_id, org_id, department_id, email, role_key, invited_by, "
            "token_hash, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                invite_id,
                org_id,
                department_id,
                email.lower(),
                role_key,
                invited_by,
                token_hash,
                expires_at,
            ),
        )
        return row_iso(row) or {}

    def get_invite_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone("SELECT * FROM invites WHERE token_hash = %s", (token_hash,))
        )

    def list_invites(self, org_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT * FROM invites WHERE org_id = %s ORDER BY created_at DESC", (org_id,)
        )
        return [row_iso(row) or {} for row in rows]

    def revoke_invite(self, org_id: str, invite_id: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone(
                "UPDATE invites SET revoked_at = now() WHERE org_id = %s AND invite_id = %s "
                "AND accepted_at IS NULL RETURNING *",
                (org_id, invite_id),
            )
        )

    def accept_invite(
        self,
        invite_id: str,
        user_id: str,
        membership_id: str,
    ) -> dict[str, Any] | None:
        """Single consumption; returns None when the invite was already used or revoked."""
        with self.db.transaction() as conn:
            invite = conn.execute(
                "SELECT * FROM invites WHERE invite_id = %s FOR UPDATE", (invite_id,)
            ).fetchone()
            if invite is None:
                return None
            if invite["accepted_at"] is not None or invite["revoked_at"] is not None:
                return None
            if invite["expires_at"] <= now():
                return None
            conn.execute(
                "UPDATE invites SET accepted_at = now(), accepted_by = %s WHERE invite_id = %s",
                (user_id, invite_id),
            )
            conn.execute(
                "INSERT INTO memberships (membership_id, org_id, user_id, department_id, status) "
                "VALUES (%s, %s, %s, %s, 'active') "
                "ON CONFLICT (org_id, user_id) DO UPDATE SET status = 'active', "
                "department_id = EXCLUDED.department_id, updated_at = now()",
                (membership_id, invite["org_id"], user_id, invite["department_id"]),
            )
            scope_type = "department" if invite["department_id"] else "org"
            scope_id = invite["department_id"] or invite["org_id"]
            conn.execute(
                "INSERT INTO role_assignments "
                "(assignment_id, org_id, user_id, scope_type, scope_id, role_key, granted_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    new_id("asg"),
                    invite["org_id"],
                    user_id,
                    scope_type,
                    scope_id,
                    invite["role_key"],
                    invite["invited_by"],
                ),
            )
            self.bump_authorization_version(conn, invite["org_id"])
        return row_iso(dict(invite))

    # --- activity ----------------------------------------------------------------------------
    def append_activity(
        self,
        *,
        event_id: str,
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
        """Event write is server-side only; `detail` never carries text/token/password."""
        row = self.db.fetchone(
            "INSERT INTO activity_events (event_id, org_id, department_id, actor_user_id, "
            "actor_label, kind, action, resource_type, resource_id, detail_json) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                event_id,
                org_id,
                department_id,
                actor_user_id,
                actor_label,
                kind,
                action,
                resource_type,
                resource_id,
                Jsonb(detail or {}),
            ),
        )
        return row_iso(row) or {}

    def activity_visibility(self, user_id: str, org_id: str) -> tuple[bool, set[str]]:
        """`(org_wide, department_ids)`: org-level `activity.read` sees everything."""
        org_row = self.db.fetchone(
            "SELECT 1 AS ok FROM role_assignments ra "
            "JOIN role_permissions rp ON rp.role_key = ra.role_key "
            "WHERE ra.user_id = %s AND ra.org_id = %s AND ra.scope_type = 'org' "
            "AND rp.permission = 'activity.read'",
            (user_id, org_id),
        )
        if org_row:
            return True, set()
        rows = self.db.fetchall(
            "SELECT DISTINCT c.descendant_id AS department_id FROM role_assignments ra "
            "JOIN role_permissions rp ON rp.role_key = ra.role_key "
            "AND rp.permission = 'activity.read' "
            "JOIN department_closure c ON c.ancestor_id = ra.scope_id "
            "WHERE ra.user_id = %s AND ra.org_id = %s AND ra.scope_type = 'department'",
            (user_id, org_id),
        )
        return False, {row["department_id"] for row in rows}

    def _activity_filter(
        self,
        user_id: str,
        org_id: str,
        *,
        department_ids: Iterable[str] | None,
        unread: bool,
        cursor: str | None,
        include_org_level: bool = False,
    ) -> tuple[str, list[Any]] | None:
        org_wide, visible_departments = self.activity_visibility(user_id, org_id)
        clauses = ["e.org_id = %s"]
        params: list[Any] = [org_id]
        if not org_wide:
            # Organisation-level events are visible to every active member; department events only
            # on the readable ancestor chains (design D7).
            if visible_departments:
                clauses.append("(e.department_id IS NULL OR e.department_id = ANY(%s))")
                params.append(list(visible_departments))
            else:
                clauses.append("e.department_id IS NULL")
        if department_ids is not None:
            scoped = list(department_ids)
            if not scoped:
                return None
            if include_org_level:
                clauses.append("(e.department_id IS NULL OR e.department_id = ANY(%s))")
            else:
                clauses.append("e.department_id = ANY(%s)")
            params.append(scoped)
        if unread:
            clauses.append("ar.event_id IS NULL")
        if cursor:
            clauses.append(
                "(e.created_at, e.event_id) < "
                "(SELECT created_at, event_id FROM activity_events WHERE event_id = %s)"
            )
            params.append(cursor)
        return " AND ".join(clauses), params

    def list_activity(
        self,
        user_id: str,
        org_id: str,
        *,
        department_ids: Iterable[str] | None = None,
        unread: bool = False,
        limit: int = 20,
        cursor: str | None = None,
        include_org_level: bool = False,
    ) -> dict[str, Any]:
        built = self._activity_filter(
            user_id,
            org_id,
            department_ids=department_ids,
            unread=unread,
            cursor=cursor,
            include_org_level=include_org_level,
        )
        if built is None:
            return {"items": [], "next_cursor": None}
        where, params = built
        rows = self.db.fetchall(
            "SELECT e.*, (ar.event_id IS NOT NULL) AS is_read, "
            "u.display_name AS actor_display_name "
            "FROM activity_events e "
            "LEFT JOIN activity_reads ar ON ar.event_id = e.event_id AND ar.user_id = %s "
            "LEFT JOIN users u ON u.user_id = e.actor_user_id "
            f"WHERE {where} ORDER BY e.created_at DESC, e.event_id DESC LIMIT %s",
            tuple([user_id, *params, limit + 1]),
        )
        items = [row_iso(row) or {} for row in rows[:limit]]
        next_cursor = str(rows[limit - 1]["event_id"]) if len(rows) > limit else None
        return {"items": items, "next_cursor": next_cursor}

    def count_activity(
        self,
        user_id: str,
        org_id: str,
        *,
        department_ids: Iterable[str] | None = None,
        unread: bool = False,
        include_org_level: bool = False,
    ) -> int:
        built = self._activity_filter(
            user_id,
            org_id,
            department_ids=department_ids,
            unread=unread,
            cursor=None,
            include_org_level=include_org_level,
        )
        if built is None:
            return 0
        where, params = built
        row = self.db.fetchone(
            "SELECT count(*) AS count FROM activity_events e "
            "LEFT JOIN activity_reads ar ON ar.event_id = e.event_id AND ar.user_id = %s "
            f"WHERE {where}",
            tuple([user_id, *params]),
        )
        return int(row["count"]) if row else 0

    def can_see_event(self, user_id: str, event_id: str) -> bool:
        event = self.db.fetchone(
            "SELECT org_id, department_id FROM activity_events WHERE event_id = %s", (event_id,)
        )
        if not event:
            return False
        org_wide, departments = self.activity_visibility(user_id, event["org_id"])
        if event["department_id"] is None:
            return self.has_active_membership(event["org_id"], user_id)
        return org_wide or event["department_id"] in departments

    def mark_activity_read(self, user_id: str, event_id: str) -> bool:
        if not self.can_see_event(user_id, event_id):
            return False
        self.db.execute(
            "INSERT INTO activity_reads (user_id, event_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (user_id, event_id),
        )
        return True

    def mark_all_activity_read(
        self,
        user_id: str,
        org_id: str,
        *,
        department_ids: Iterable[str] | None = None,
        include_org_level: bool = False,
    ) -> int:
        built = self._activity_filter(
            user_id,
            org_id,
            department_ids=department_ids,
            unread=False,
            cursor=None,
            include_org_level=include_org_level,
        )
        if built is None:
            return 0
        where, params = built
        return self.db.execute(
            "INSERT INTO activity_reads (user_id, event_id) "
            f"SELECT %s, e.event_id FROM activity_events e WHERE {where} "
            "ON CONFLICT DO NOTHING",
            tuple([user_id, *params]),
        )

    # --- developer ---------------------------------------------------------------------------
    def create_api_key(
        self,
        *,
        key_id: str,
        org_id: str,
        department_id: str | None,
        name: str,
        key_hash: str,
        prefix: str,
        scopes: list[str],
        created_by: str,
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        row = self.db.fetchone(
            "INSERT INTO api_keys (key_id, org_id, department_id, name, key_hash, prefix, "
            "scopes_json, created_by, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                key_id,
                org_id,
                department_id,
                name,
                key_hash,
                prefix,
                Jsonb(scopes),
                created_by,
                expires_at,
            ),
        )
        return row_iso(row) or {}

    def list_api_keys(self, org_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT key_id, org_id, department_id, name, prefix, scopes_json, created_by, "
            "expires_at, last_used_at, revoked_at, created_at FROM api_keys "
            "WHERE org_id = %s ORDER BY created_at DESC",
            (org_id,),
        )
        return [row_iso(row) or {} for row in rows]

    def get_api_key(self, org_id: str, key_id: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone(
                "SELECT * FROM api_keys WHERE org_id = %s AND key_id = %s", (org_id, key_id)
            )
        )

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        return row_iso(self.db.fetchone("SELECT * FROM api_keys WHERE key_hash = %s", (key_hash,)))

    def revoke_api_key(self, org_id: str, key_id: str) -> dict[str, Any] | None:
        return row_iso(
            self.db.fetchone(
                "UPDATE api_keys SET revoked_at = now() WHERE org_id = %s AND key_id = %s "
                "AND revoked_at IS NULL RETURNING *",
                (org_id, key_id),
            )
        )

    def touch_api_key(self, key_id: str) -> None:
        self.db.execute("UPDATE api_keys SET last_used_at = now() WHERE key_id = %s", (key_id,))

    def append_request_log(
        self,
        *,
        api_key_id: str,
        org_id: str,
        method: str,
        path: str,
        status: int,
        latency_ms: int,
    ) -> None:
        self.db.execute(
            "INSERT INTO api_request_logs (api_key_id, org_id, method, path, status, latency_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (api_key_id, org_id, method, path, status, latency_ms),
        )

    def list_request_logs(
        self,
        org_id: str,
        *,
        key_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses = ["org_id = %s"]
        params: list[Any] = [org_id]
        if key_id:
            clauses.append("api_key_id = %s")
            params.append(key_id)
        if since:
            clauses.append("created_at >= %s")
            params.append(since)
        if until:
            clauses.append("created_at <= %s")
            params.append(until)
        where = " AND ".join(clauses)
        total_row = self.db.fetchone(
            f"SELECT count(*) AS count FROM api_request_logs WHERE {where}", tuple(params)
        )
        rows = self.db.fetchall(
            f"SELECT * FROM api_request_logs WHERE {where} "
            "ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple([*params, limit, offset]),
        )
        return {
            "items": [row_iso(row) or {} for row in rows],
            "total": int(total_row["count"]) if total_row else 0,
        }

    def usage(
        self,
        org_id: str,
        *,
        days: int = 7,
        key_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["org_id = %s", "created_at >= now() - (%s || ' days')::interval"]
        params: list[Any] = [org_id, str(max(1, days))]
        if key_id:
            clauses.append("api_key_id = %s")
            params.append(key_id)
        rows = self.db.fetchall(
            "SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day, "
            "api_key_id, status, count(*) AS requests, "
            "round(avg(latency_ms))::int AS avg_latency_ms "
            f"FROM api_request_logs WHERE {' AND '.join(clauses)} "
            "GROUP BY day, api_key_id, status ORDER BY day DESC, api_key_id, status",
            tuple(params),
        )
        return [row_iso(row) or {} for row in rows]


__all__ = ["IdentityStore", "iso", "new_id", "now", "row_iso"]