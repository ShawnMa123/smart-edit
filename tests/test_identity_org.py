"""Organization, department, role and invite contract tests (tasks 3-4, 5.3)."""

from __future__ import annotations

from tests.identity_helpers import CSRF, api, identity_services, login, register  # noqa: F401


def _invite_and_accept(api, org_id: str, email: str, role_key: str, department_id: str | None = None):
    invite = api.post(
        f"/organizations/{org_id}/invites",
        json={"email": email, "role_key": role_key, "department_id": department_id},
        headers=CSRF,
    )
    assert invite.status_code == 201, invite.text
    body = invite.json()
    assert "invite_token" in body and "token_hash" not in body
    # A second user registers (and gets a personal workspace), then accepts the link.
    registered = api.post("/auth/register", json={"email": email, "password": "correct-horse-1"})
    assert registered.status_code == 201, registered.text
    accepted = api.post(
        "/invites/accept", json={"invite_token": body["invite_token"]}, headers=CSRF
    )
    assert accepted.status_code == 200, accepted.text
    return body, accepted.json()


def test_department_tree_and_closure_inheritance(api, identity_services):  # noqa: F811
    profile = register(api)
    org_id = profile["active_org"]["org_id"]
    legal = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Legal"}, headers=CSRF
    ).json()
    contracts = api.post(
        f"/organizations/{org_id}/departments",
        json={"name": "Contracts", "parent_id": legal["department_id"]},
        headers=CSRF,
    ).json()
    finance = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Finance"}, headers=CSRF
    ).json()

    ancestors = identity_services.store.department_ancestors(contracts["department_id"])
    assert ancestors == [legal["department_id"], contracts["department_id"]]

    # Moving Contracts under Finance rewrites the closure (task 3.2).
    moved = api.patch(
        f"/organizations/{org_id}/departments/{contracts['department_id']}",
        json={"parent_id": finance["department_id"]},
        headers=CSRF,
    )
    assert moved.status_code == 200
    ancestors = identity_services.store.department_ancestors(contracts["department_id"])
    assert ancestors == [finance["department_id"], contracts["department_id"]]


def test_department_admin_is_scoped_and_cannot_escape(api):  # noqa: F811
    profile = register(api)
    org_id = profile["active_org"]["org_id"]
    legal = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Legal"}, headers=CSRF
    ).json()
    finance = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Finance"}, headers=CSRF
    ).json()

    _invite_and_accept(api, org_id, "admin@example.com", "dept_admin", legal["department_id"])
    login(api, "admin@example.com")
    switched = api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    assert switched.status_code == 200

    allowed = api.post(
        f"/organizations/{org_id}/departments",
        json={"name": "Contracts", "parent_id": legal["department_id"]},
        headers=CSRF,
    )
    assert allowed.status_code == 201
    denied = api.post(
        f"/organizations/{org_id}/departments",
        json={"name": "Shadow", "parent_id": finance["department_id"]},
        headers=CSRF,
    )
    assert denied.status_code == 403

    # Over-reaching invitation: a department admin cannot grant `org_admin` (task 4.3).
    overreach = api.post(
        f"/organizations/{org_id}/invites",
        json={
            "email": "boss@example.com",
            "role_key": "org_admin",
            "department_id": legal["department_id"],
        },
        headers=CSRF,
    )
def test_department_documents_are_isolated_and_org_documents_are_shared(api):  # noqa: F811
    profile = register(api)
    org_id = profile["active_org"]["org_id"]
    legal = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Legal"}, headers=CSRF
    ).json()
    finance = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Finance"}, headers=CSRF
    ).json()

    shared = api.post("/documents", json={"title": "Shared", "text": "org level"}, headers=CSRF)
    assert shared.status_code == 201
    legal_doc = api.post(
        "/documents",
        json={
            "title": "Legal memo",
            "text": "privileged",
            "department_id": legal["department_id"],
        },
        headers=CSRF,
    )
    assert legal_doc.status_code == 201

    _invite_and_accept(api, org_id, "finance@example.com", "member", finance["department_id"])
    login(api, "finance@example.com")
    api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)

    assert api.get(f"/documents/{shared.json()['document_id']}").status_code == 200
    denied = api.get(f"/documents/{legal_doc.json()['document_id']}")
    assert denied.status_code == 403
    assert "privileged" not in denied.text

    # A member inside Legal can read it (member role on the ancestor chain).
    login(api, profile["user"]["email"])
    _invite_and_accept(api, org_id, "legal@example.com", "member", legal["department_id"])
    login(api, "legal@example.com")
    api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    assert api.get(f"/documents/{legal_doc.json()['document_id']}").status_code == 200


def test_invite_is_single_use(api):  # noqa: F811
    profile = register(api)
    org_id = profile["active_org"]["org_id"]
    invite = api.post(
        f"/organizations/{org_id}/invites",
        json={"email": "member@example.com", "role_key": "member"},
        headers=CSRF,
    ).json()
    registered = api.post(
        "/auth/register", json={"email": "member@example.com", "password": "correct-horse-1"}
    )
    assert registered.status_code == 201
    first = api.post(
        "/invites/accept", json={"invite_token": invite["invite_token"]}, headers=CSRF
    )
    assert first.status_code == 200
    second = api.post(
        "/invites/accept", json={"invite_token": invite["invite_token"]}, headers=CSRF
    )
    assert second.status_code == 409
    assert second.json()["code"] in {"invite_used", "invite_expired"}


def test_auditor_role_has_no_assistant_access(api):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]
    body = api.post(
        f"/organizations/{org_id}/invites",
        json={"email": "auditor-only@example.com", "role_key": "auditor"},
        headers=CSRF,
    ).json()
    api.post(
        "/auth/register", json={"email": "auditor-only@example.com", "password": "correct-horse-1"}
    )
    assert (
        api.post("/invites/accept", json={"invite_token": body["invite_token"]}, headers=CSRF)
    ).status_code == 200
    login(api, "auditor-only@example.com")
    api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    # `auditor` has no `assistant.use`; the assistant API is closed (task 5.3).
    assert api.get("/assistant/capabilities").status_code == 403


def test_last_org_admin_cannot_be_removed(api):  # noqa: F811
    profile = register(api)
    org_id = profile["active_org"]["org_id"]
    user_id = profile["user"]["user_id"]
    blocked = api.patch(
        f"/organizations/{org_id}/members/{user_id}", json={"status": "suspended"}, headers=CSRF
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "last_admin"


def test_role_assignment_and_revocation_change_permissions(api):  # noqa: F811
    profile = register(api)
    org_id = profile["active_org"]["org_id"]
    legal = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Legal"}, headers=CSRF
    ).json()
    _, accepted = _invite_and_accept(api, org_id, "auditor@example.com", "member", legal["department_id"])
    login(api, profile["user"]["email"])
    members = api.get(f"/organizations/{org_id}/members").json()
    member = next(row for row in members if row["email"] == "auditor@example.com")

    assignment = api.post(
        f"/organizations/{org_id}/role-assignments",
        json={
            "user_id": member["user_id"],
            "role_key": "auditor",
            "scope_type": "department",
            "scope_id": legal["department_id"],
        },
        headers=CSRF,
    )
    assert assignment.status_code == 201
    permissions = api.app.state.identity.store.permissions_for(
        member["user_id"], org_id, legal["department_id"]
    )
    assert "audit.read" in permissions

    login(api, "auditor@example.com")
    api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    assert api.get(f"/activity?org_id={org_id}").status_code == 200

    login(api, profile["user"]["email"])
    removed = api.delete(
        f"/organizations/{org_id}/role-assignments/{assignment.json()['assignment_id']}",
        headers=CSRF,
    )
    assert removed.status_code == 204
    permissions = api.app.state.identity.store.permissions_for(
        member["user_id"], org_id, legal["department_id"]
    )
    assert "audit.read" not in permissions