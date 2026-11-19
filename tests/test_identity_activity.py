"""Activity feed tests (tasks 7.1-7.2)."""

from __future__ import annotations

from tests.identity_helpers import CSRF, api, identity_services, login, register  # noqa: F401


def _department(api, org_id: str, name: str) -> dict:
    response = api.post(f"/organizations/{org_id}/departments", json={"name": name}, headers=CSRF)
    assert response.status_code == 201, response.text
    return response.json()


def _invite(api, org_id: str, email: str, role_key: str, department_id: str | None = None):
    body = api.post(
        f"/organizations/{org_id}/invites",
        json={"email": email, "role_key": role_key, "department_id": department_id},
        headers=CSRF,
    ).json()
    api.post("/auth/register", json={"email": email, "password": "correct-horse-1"})
    accepted = api.post(
        "/invites/accept", json={"invite_token": body["invite_token"]}, headers=CSRF
    )
    assert accepted.status_code == 200, accepted.text


def test_activity_visibility_and_per_user_reads(api, identity_services):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]
    finance = _department(api, org_id, "Finance")
    legal = _department(api, org_id, "Legal")
    finance_doc = api.post(
        "/documents",
        json={"title": "Finance doc", "text": "f", "department_id": finance["department_id"]},
        headers=CSRF,
    ).json()
    legal_doc = api.post(
        "/documents",
        json={"title": "Legal doc", "text": "l", "department_id": legal["department_id"]},
        headers=CSRF,
    ).json()
    for document in (finance_doc, legal_doc):
        lock = api.post(
            f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
            json={"lease_seconds": 60},
            headers=CSRF,
        )
        assert lock.status_code == 201, lock.text

    _invite(api, org_id, "finance@example.com", "member", finance["department_id"])
    login(api, "finance@example.com")
    api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    page = api.get(f"/activity?org_id={org_id}").json()
    locked = [item for item in page["items"] if item["action"] == "document locked"]
    assert [item["resource_id"] for item in locked] == [finance_doc["document_id"]]
    assert page["unread_count"] >= 1

    event = locked[0]["event_id"]
    assert api.post(f"/activity/{event}/read?org_id={org_id}", headers=CSRF).status_code == 200
    assert api.get(f"/activity/unread-count?org_id={org_id}").json()["unread_count"] == (
        page["unread_count"] - 1
    )

    # The owner's read state for the same event is untouched.
    login(api, owner["user"]["email"])
    owner_page = api.get(f"/activity?org_id={org_id}").json()
    owner_event = next(item for item in owner_page["items"] if item["event_id"] == event)
    assert owner_event["is_read"] is False

    marked = api.post(f"/activity/read-all?org_id={org_id}", headers=CSRF).json()
    assert marked["marked_read"] >= 1
    assert api.get(f"/activity/unread-count?org_id={org_id}").json()["unread_count"] == 0


def test_activity_payload_never_contains_sensitive_content(identity_services):  # noqa: F811
    store = identity_services.store
    store.db.execute(
        "INSERT INTO users (user_id, email, password_hash, display_name) "
        "VALUES ('u1', 'u1@example.com', 'x', 'User')"
    )
    store.db.execute(
        "INSERT INTO organizations (org_id, workspace_id, name) VALUES ('o1', 'o1', 'Org')"
    )
    event = identity_services.activity.record(
        org_id="o1",
        department_id=None,
        actor_user_id="u1",
        actor_label="User",
        kind="document",
        action="document submitted",
        detail={
            "document_id": "doc_1",
            "revision": 3,
            "text": "confidential clause",
            "password": "hunter2",
            "session_token": "secret",
        },
    )
    detail = store.db.fetchone(
        "SELECT detail_json FROM activity_events WHERE event_id = %s", (event["event_id"],)
    )["detail_json"]
    assert detail == {"document_id": "doc_1", "revision": 3}


def test_removed_member_history_is_kept(api):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]
    body = api.post(
        f"/organizations/{org_id}/invites",
        json={"email": "leaver@example.com", "role_key": "member"},
        headers=CSRF,
    ).json()
    api.post("/auth/register", json={"email": "leaver@example.com", "password": "correct-horse-1"})
    api.post("/invites/accept", json={"invite_token": body["invite_token"]}, headers=CSRF)
    members = api.get(f"/organizations/{org_id}/members").json()
    leaver = next(row for row in members if row["email"] == "leaver@example.com")
    login(api, owner["user"]["email"])
    removed = api.patch(
        f"/organizations/{org_id}/members/{leaver['user_id']}",
        json={"status": "removed"},
        headers=CSRF,
    )
    assert removed.status_code == 200
    page = api.get(f"/activity?org_id={org_id}").json()
    assert any(item["action"] == "member removed" for item in page["items"])