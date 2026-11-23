"""Rebuild `department_closure` for every organisation (task 3.2 maintenance script).

Usage:
    SMART_EDIT_AUTH_MODE=pg SMART_EDIT_DATABASE_URL=... \
        .venv/bin/python scripts/identity_rebuild_closure.py

The normal create/move/delete paths maintain the closure inside their transaction; this script is the
recovery path after manual SQL edits or an interrupted migration.
"""

from __future__ import annotations

import sys

from app.identity.db import PgDatabase
from app.identity.settings import AuthSettings
from app.identity.store import IdentityStore


def main() -> int:
    settings = AuthSettings.from_env()
    if not settings.is_pg or not settings.database_url:
        print("SMART_EDIT_AUTH_MODE=pg and SMART_EDIT_DATABASE_URL are required", file=sys.stderr)
        return 2
    database = PgDatabase(settings.database_url, settings=settings).open()
    try:
        store = IdentityStore(database)
        organizations = database.fetchall("SELECT org_id, name FROM organizations ORDER BY org_id")
        for organization in organizations:
            store.rebuild_closure(organization["org_id"])
            depth_rows = database.fetchone(
                "SELECT count(*) AS count FROM department_closure c "
                "JOIN departments d ON d.department_id = c.ancestor_id WHERE d.org_id = %s",
                (organization["org_id"],),
            )
            print(f"{organization['org_id']}\t{organization['name']}\t{depth_rows['count']} links")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())