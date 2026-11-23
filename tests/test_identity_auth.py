"""Auth contract tests (tasks 2.2-2.5, 3.3)."""

from __future__ import annotations

from app.identity.tokens import hash_token

from tests.identity_helpers import CSRF, api, identity_services, login, register  # noqa: F401


def test_register_sets_httponly_cookie_and_me(api, identity_services):  # noqa: F811
    response = api.post(
        "/auth/register",
        json={"email": "owner@example.com", "password": "correct-horse-1", "display_name": "Owner"},
    )
    assert response.status_code == 201
    assert "session_token" not in response.json()
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    profile = api.get("/auth/me").json()
    assert profile["user"]["email"] == "owner@example.com"
    assert profile["active_org"]["org_id"] == profile["active_org"]["workspace_id"]
    # Only the hash is stored.
    token = api.cookies.get("smart_edit_session")
    row = identity_services.store.get_session_by_token(hash_token(token))
    assert row and row["session_id"]


def test_login_rejects_wrong_password_and_unknown_email_identically(api):  # noqa: F811
    register(api)
    wrong = login(api, "owner@example.com", "not-the-password")
    unknown = login(api, "missing@example.com", "whatever-123")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["message"] == unknown.json()["message"]


def test_unauthenticated_requests_return_401(api):  # noqa: F811
    api.cookies.clear()
    assert api.get("/documents/anything").status_code == 401
    assert api.get("/organizations").status_code == 401


def test_logout_revokes_session_and_logout_all(api):  # noqa: F811
    from fastapi.testclient import TestClient

    register(api)
    token = api.cookies.get("smart_edit_session")
    assert api.post("/auth/logout", headers=CSRF).status_code == 200
    probe = TestClient(api.app)
    probe.cookies.set("smart_edit_session", token)
    assert probe.get("/auth/me").status_code == 401

    login(api, "owner@example.com")
    token = api.cookies.get("smart_edit_session")
    assert api.post("/auth/logout-all", headers=CSRF).status_code == 200
    probe = TestClient(api.app)
    probe.cookies.set("smart_edit_session", token)
    assert probe.get("/auth/me").status_code == 401


def test_write_without_csrf_header_is_rejected(api):  # noqa: F811
    register(api)
    response = api.post("/organizations", json={"name": "No CSRF"})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_REJECTED"
    ok = api.post("/organizations", json={"name": "With CSRF"}, headers=CSRF)
    assert ok.status_code == 201


def test_login_failures_are_rate_limited(api):  # noqa: F811
    register(api)
    for _ in range(3):
        assert login(api, "owner@example.com", "wrong-password").status_code == 401
    limited = login(api, "owner@example.com", "wrong-password")
    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"


def test_register_duplicate_email_is_explicit(api):  # noqa: F811
    register(api)
    duplicate = api.post(
        "/auth/register", json={"email": "owner@example.com", "password": "correct-horse-1"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "email_taken"


def test_switch_org_requires_active_membership(api):  # noqa: F811
    first = api.post(
        "/auth/register",
        json={"email": "first@example.com", "password": "correct-horse-1", "organization_name": "A"},
        headers=CSRF,
    )
    assert first.status_code == 201
    api.post("/organizations", json={"name": "Other"}, headers=CSRF)
    other_user = api.post(
        "/auth/register",
        json={"email": "second@example.com", "password": "correct-horse-1", "organization_name": "B"},
    )
    assert other_user.status_code == 201
    foreign_org = other_user.json()["active_org"]["org_id"]

    # Back to the first user (its cookie was replaced by the second registration).
    login(api, "first@example.com")
    denied = api.post("/auth/active-org", json={"org_id": foreign_org}, headers=CSRF)
    assert denied.status_code == 403
    still = api.get("/auth/me").json()
    assert still["active_org"]["org_id"] != foreign_org