"""Clear identity mock data and seed real workflow users (Applicant / approvers).

Usage:
    SMART_EDIT_AUTH_MODE=pg \
    .venv/bin/python scripts/seed_identity_users.py --reset

Without `--reset` the script is idempotent: existing users keep their id, passwords are reset to the
values below, and missing memberships/roles/departments are added.

The plaintext passwords are printed and also written to `runs/dev/test-users.md` (gitignored); the
database only receives argon2id hashes. The demo document is recreated under `ws_demo_01` so the UI
editor has something the applicant can edit and the reviewers can open read-only.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.documents.store import HostStore
from app.identity import permissions as perm
from app.identity.bootstrap import build_identity_services
from app.identity.settings import AuthSettings
from app.identity.store import new_id

ROOT = Path(__file__).resolve().parents[1]
ORG_ID = "ws_demo_01"  # keep the legacy workspace id so existing document rows stay reachable
ORG_NAME = "Atlas Trade Bank"
ORG_SLUG = "atlas-trade"
DOCUMENT_ID = "demo-document"
SAMPLE_TEXT = (
    "DEMAND GUARANTEE APPLICATION\n"
    "Applicant: Atlas Trading Ltd\n"
    "Beneficiary: Meridian Exports Pte Ltd\n"
    "Amount: USD 250,000.00\n"
    "Governing rules: URDG 758\n"
    "Expiry: 2027-06-30\n"
    "Requested by: Applicant\n"
)

# (email, password, display name, role, department)
USERS = [
    ("admin@atlas-trade.test", "AtlasAdmin!2026", "Atlas Admin", perm.ROLE_ORG_ADMIN, None),
    (
        "applicant@atlas-trade.test",
        "Applicant!2026",
        "Applicant User",
        perm.ROLE_APPLICANT,
        "Trade Operations",
    ),
    (
        "bankops@atlas-trade.test",
        "BankOps!2026",
        "Bank Operations",
        perm.ROLE_BANK_OPS,
        "Bank Operations",
    ),
    (
        "compliance@atlas-trade.test",
        "Compliance!2026",
        "Compliance Officer",
        perm.ROLE_COMPLIANCE,
        "Compliance",
    ),
    ("auditor@atlas-trade.test", "Auditor!2026", "Internal Auditor", perm.ROLE_AUDITOR, None),
]
DEPARTMENTS = ["Trade Operations", "Bank Operations", "Compliance"]
TABLES = (
    "api_request_logs",
    "api_keys",
    "activity_reads",
    "activity_events",
    "invites",
    "role_assignments",
    "role_permissions",
    "roles",
    "memberships",
    "department_closure",
    "departments",
    "organizations",
    "login_attempts",
    "sessions",
    "users",
)


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and " " not in key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def reset_identity(store) -> None:
    with store.db.connection() as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
    store.sync_role_catalog()


def ensure_user(store, hasher, email: str, password: str, display_name: str) -> dict:
    user = store.get_user_by_email(email)
    if user:
        store.update_password_hash(user["user_id"], hasher.hash(password))
        store.db.execute(
            "UPDATE users SET display_name = %s, status = 'active', updated_at = now() "
            "WHERE user_id = %s",
            (display_name, user["user_id"]),
        )
        return store.get_user(user["user_id"]) or user
    return store.create_user(
        user_id=new_id("usr"),
        email=email,
        password_hash=hasher.hash(password),
        display_name=display_name,
    )


def ensure_organization(store, admin_id: str) -> dict:
    organization = store.get_org_by_workspace(ORG_ID)
    if organization:
        return organization
    return store.create_organization(
        org_id=ORG_ID,
        workspace_id=ORG_ID,
        name=ORG_NAME,
        slug=ORG_SLUG,
        owner_user_id=admin_id,
    )


def ensure_departments(store, org_id: str) -> dict[str, str]:
    existing = {row["name"]: row["department_id"] for row in store.list_departments(org_id)}
    for name in DEPARTMENTS:
        if name not in existing:
            created = store.create_department(
                department_id=new_id("dept"), org_id=org_id, parent_id=None, name=name
            )
            existing[name] = created["department_id"]
    return existing


def ensure_membership(store, org_id: str, user_id: str, department_id: str | None) -> None:
    membership = store.get_membership(org_id, user_id)
    if membership and membership["status"] == "active":
        store.db.execute(
            "UPDATE memberships SET department_id = %s, updated_at = now() "
            "WHERE org_id = %s AND user_id = %s",
            (department_id, org_id, user_id),
        )
        return
    store.add_membership(org_id=org_id, user_id=user_id, department_id=department_id)


def ensure_assignment(store, org_id: str, user_id: str, role_key: str, granted_by: str) -> None:
    existing = store.list_assignments(org_id, user_id)
    if any(item["role_key"] == role_key and item["scope_type"] == "org" for item in existing):
        return
    store.create_assignment(
        org_id=org_id,
        user_id=user_id,
        scope_type="org",
        scope_id=org_id,
        role_key=role_key,
        granted_by=granted_by,
    )


def reset_demo_document(host: HostStore, owner_id: str) -> None:
    with host.transaction() as conn:
        draft_ids = [
            row["draft_id"]
            for row in conn.execute(
                "SELECT draft_id FROM document_drafts WHERE document_id = ?", (DOCUMENT_ID,)
            ).fetchall()
        ]
        for draft_id in draft_ids:
            conn.execute("DELETE FROM document_checkpoints WHERE draft_id = ?", (draft_id,))
            conn.execute("DELETE FROM document_locks WHERE draft_id = ?", (draft_id,))
            conn.execute(
                "DELETE FROM automation_proposal_events WHERE proposal_id IN "
                "(SELECT proposal_id FROM automation_proposals WHERE draft_id = ?)",
                (draft_id,),
            )
            conn.execute(
                "DELETE FROM automation_applications WHERE proposal_id IN "
                "(SELECT proposal_id FROM automation_proposals WHERE draft_id = ?)",
                (draft_id,),
            )
            conn.execute(
                "DELETE FROM automation_reviews WHERE proposal_id IN "
                "(SELECT proposal_id FROM automation_proposals WHERE draft_id = ?)",
                (draft_id,),
            )
            conn.execute("DELETE FROM automation_proposals WHERE draft_id = ?", (draft_id,))
        conn.execute("DELETE FROM document_drafts WHERE document_id = ?", (DOCUMENT_ID,))
        conn.execute("DELETE FROM documents WHERE document_id = ?", (DOCUMENT_ID,))
    host.create_document(
        workspace_id=ORG_ID,
        owner_user_id=owner_id,
        title="Demand Guarantee Application",
        text=SAMPLE_TEXT,
        document_id=DOCUMENT_ID,
    )
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="truncate identity tables first")
    args = parser.parse_args()

    load_env()
    os.environ.setdefault("SMART_EDIT_AUTH_MODE", "pg")
    settings = AuthSettings.from_env()
    if not settings.is_pg:
        print("SMART_EDIT_AUTH_MODE=pg and SMART_EDIT_DATABASE_URL are required")
        return 2

    services = build_identity_services(settings)
    assert services.store is not None and services.hasher is not None
    store, hasher = services.store, services.hasher
    try:
        if args.reset:
            reset_identity(store)
        store.sync_role_catalog()

        admin = ensure_user(store, hasher, *USERS[0][:3])
        organization = ensure_organization(store, admin["user_id"])
        org_id = organization["org_id"]
        departments = ensure_departments(store, org_id)

        created: list[tuple[str, str, str, str, str]] = []
        owner_id = admin["user_id"]
        for email, password, display_name, role_key, department_name in USERS:
            user = ensure_user(store, hasher, email, password, display_name)
            department_id = departments.get(department_name) if department_name else None
            ensure_membership(store, org_id, user["user_id"], department_id)
            ensure_assignment(store, org_id, user["user_id"], role_key, admin["user_id"])
            if role_key == perm.ROLE_APPLICANT:
                owner_id = user["user_id"]
            created.append(
                (
                    email,
                    password,
                    display_name,
                    perm.ROLE_CATALOG[role_key]["name"],
                    department_name or "—",
                )
            )

        host = HostStore(os.environ.get("SMART_EDIT_HOST_DB", str(ROOT / "runs/host.db")))
        reset_demo_document(host, owner_id)

        lines = [
            "# Test users (generated by scripts/seed_identity_users.py)",
            "",
            f"- Organisation: **{ORG_NAME}** (`{org_id}` / workspace `{ORG_ID}`)",
            f"- Demo document: `{DOCUMENT_ID}` (applicant owns it; reviewers can open it read-only)",
            "- Database stores argon2id hashes only; these plaintext values are for local testing.",
            "",
            "| Email | Password | Display name | Role | Department |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines += [f"| {row[0]} | `{row[1]}` | {row[2]} | {row[3]} | {row[4]} |" for row in created]
        table = "\n".join(lines)
        print(table)
        out = ROOT / "runs/dev/test-users.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(table + "\n", encoding="utf-8")
        print(f"\nwritten: {out}")
        return 0
    finally:
        services.close()


if __name__ == "__main__":
    raise SystemExit(main())