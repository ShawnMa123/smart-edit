"""PG schema, migration idempotency and startup failure tests (tasks 1.2-1.3, 3.1)."""

from __future__ import annotations

import pytest

from app.identity.db import MigrationRunner, PgDatabase
from app.identity.errors import DatabaseUnavailable
from app.identity.settings import AuthSettings

from tests.identity_helpers import identity_services  # noqa: F401


def test_migrations_create_tables_and_are_idempotent(identity_services):  # noqa: F811
    store = identity_services.store
    tables = {
        row["table_name"]
        for row in store.db.fetchall(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    assert {
        "users",
        "sessions",
        "organizations",
        "departments",
        "department_closure",
        "memberships",
        "roles",
        "role_permissions",
        "role_assignments",
        "invites",
        "activity_events",
        "activity_reads",
        "api_keys",
        "api_request_logs",
    } <= tables
    # Re-running the runner is a no-op (task 1.2).
    assert MigrationRunner(identity_services.db).migrate() == []
    assert MigrationRunner(identity_services.db).current_version() == 3


def test_demo_workspace_is_seeded_and_role_catalog_is_synced(identity_services):  # noqa: F811
    demo = identity_services.store.get_org_by_workspace("ws_demo_01")
    assert demo and demo["org_id"] == "ws_demo_01"
    roles = {
        row["role_key"]
        for row in identity_services.store.db.fetchall("SELECT role_key FROM roles")
    }
    assert roles == {"org_admin", "dept_admin", "member", "auditor"}
    permissions = identity_services.store.db.fetchall(
        "SELECT permission FROM role_permissions WHERE role_key = 'org_admin'"
    )
    assert "developer.manage" in {row["permission"] for row in permissions}


def test_unreachable_pg_fails_at_startup_with_actionable_message():
    settings = AuthSettings.from_env(
        {"SMART_EDIT_AUTH_MODE": "pg", "SMART_EDIT_DATABASE_URL": "postgresql://u:p@127.0.0.1:1/none"}
    )
    database = PgDatabase(settings.database_url or "", settings=settings)
    with pytest.raises(DatabaseUnavailable) as raised:
        database.open(timeout=2)
    message = str(raised.value)
    assert "SMART_EDIT_DATABASE_URL" in message
    assert "team04-pg" in message
    assert "p:" not in message  # the password is never echoed