"""Developer platform tests (tasks 8.1-8.4)."""

from __future__ import annotations

from tests.identity_helpers import CSRF, api, identity_services, login, register  # noqa: F401


def test_api_key_is_shown_once_logged_and_revoked(api, identity_services):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]
    document = api.post("/documents", json={"title": "Doc", "text": "hello"}, headers=CSRF).json()

    created = api.post(
        f"/developer/organizations/{org_id}/keys",
        json={"name": "CI key", "scopes": ["document.read"]},
        headers=CSRF,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    token = body["key_token"]
    assert token.startswith("sk_live_") and body["prefix"] == token[:12]
    listed = api.get(f"/developer/organizations/{org_id}/keys").json()
    assert all("key_token" not in row and "key_hash" not in row for row in listed)

    owner_session = api.cookies.get("smart_edit_session")
    api.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert api.get(f"/documents/{document['document_id']}", headers=headers).status_code == 200
    api.cookies.set("smart_edit_session", owner_session)
    logs = api.get(f"/developer/organizations/{org_id}/request-logs").json()
    assert logs["total"] >= 1
    entry = logs["items"][0]
    assert entry["status"] == 200 and entry["method"] == "GET"
    assert set(entry) == {
        "log_id",
        "api_key_id",
        "org_id",
        "method",
        "path",
        "status",
        "latency_ms",
        "created_at",
    }

    # Revocation is immediate.
    login(api, owner["user"]["email"])
    revoked = api.delete(
        f"/developer/organizations/{org_id}/keys/{body['key_id']}", headers=CSRF
    )
    assert revoked.status_code == 204
    assert api.get(f"/documents/{document['document_id']}", headers=headers).status_code == 401
    after = api.get(f"/developer/organizations/{org_id}/request-logs").json()
    assert after["total"] >= logs["total"] + 1
    assert after["items"][0]["status"] == 401


def test_api_key_scopes_and_creator_permissions_are_intersected(api, identity_services):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]
    document = api.post("/documents", json={"title": "Doc", "text": "hello"}, headers=CSRF).json()
    created = api.post(
        f"/developer/organizations/{org_id}/keys",
        json={"name": "Activity key", "scopes": ["activity.read"]},
        headers=CSRF,
    ).json()

    api.cookies.clear()
    headers = {"Authorization": f"Bearer {created['key_token']}"}
    assert api.get(f"/activity?org_id={org_id}", headers=headers).status_code == 200
    assert api.get(f"/documents/{document['document_id']}", headers=headers).status_code == 403

    # Without `developer.manage` the page and endpoints are closed (task 8.4).
    login(api, owner["user"]["email"])
    api.post(
        f"/organizations/{org_id}/invites",
        json={"email": "member@example.com", "role_key": "member"},
        headers=CSRF,
    )
    api.post("/auth/register", json={"email": "member@example.com", "password": "correct-horse-1"})
    login(api, "member@example.com")
    api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    assert api.get(f"/developer/organizations/{org_id}/keys").status_code == 403


def test_legacy_automation_api_key_scopes_only_read_and_send(api, identity_services):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]
    created = api.post(
        f"/developer/organizations/{org_id}/keys",
        json={"name": "Legacy automation key", "scopes": ["automation.use", "automation.apply"]},
        headers=CSRF,
    )
    assert created.status_code == 201, created.text

    api.cookies.clear()
    headers = {"Authorization": f"Bearer {created.json()['key_token']}"}

    assert api.get("/automation/templates", headers=headers).status_code == 200
    # The legacy scopes keep working for sending (a missing connector is 404, not 403).
    assert (
        api.post(
            "/automation/dispatches",
            json={"template_id": "tpl_missing", "connector_id": "con_missing"},
            headers=headers,
        ).status_code
        != 403
    )
    # But they never grant configuration.
    assert (
        api.post(
            "/automation/templates",
            json={"name": "x", "text": "Amount: 1", "source_kind": "imported"},
            headers=headers,
        ).status_code
        == 403
    )


def test_usage_aggregates_by_day_key_and_status(api, identity_services):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]
    created = api.post(
        f"/developer/organizations/{org_id}/keys",
        json={"name": "Usage key", "scopes": ["activity.read"]},
        headers=CSRF,
    ).json()
    api.cookies.clear()
    headers = {"Authorization": f"Bearer {created['key_token']}"}
    assert api.get(f"/activity?org_id={org_id}", headers=headers).status_code == 200
    empty = api.get("/activity?org_id=missing", headers=headers)
    assert empty.status_code == 200 and empty.json()["items"] == []

    login(api, owner["user"]["email"])
    usage = api.get(f"/developer/organizations/{org_id}/usage?days=7").json()
    assert usage
    assert {"day", "api_key_id", "status", "requests", "avg_latency_ms"} <= set(usage[0])