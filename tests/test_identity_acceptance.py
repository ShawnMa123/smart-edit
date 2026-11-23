"""PG acceptance path (task 9.3): login → org/dept → invite → isolation → activity → key/logs."""

from __future__ import annotations

from tests.identity_helpers import CSRF, api, identity_services, login, register  # noqa: F401


def test_pg_mode_acceptance_path(api, identity_services):  # noqa: F811
    owner = register(api)
    org_id = owner["active_org"]["org_id"]

    legal = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Legal"}, headers=CSRF
    ).json()
    finance = api.post(
        f"/organizations/{org_id}/departments", json={"name": "Finance"}, headers=CSRF
    ).json()
    legal_doc = api.post(
        "/documents",
        json={"title": "Legal memo", "text": "privileged", "department_id": legal["department_id"]},
        headers=CSRF,
    ).json()
    finance_doc = api.post(
        "/documents",
        json={"title": "Finance memo", "text": "numbers", "department_id": finance["department_id"]},
        headers=CSRF,
    ).json()
    for document in (legal_doc, finance_doc):
        assert (
            api.post(
                f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
                json={"lease_seconds": 60},
                headers=CSRF,
            ).status_code
            == 201
        )

    invite = api.post(
        f"/organizations/{org_id}/invites",
        json={"email": "finance@example.com", "role_key": "member", "department_id": finance["department_id"]},
        headers=CSRF,
    ).json()
    api.post("/auth/register", json={"email": "finance@example.com", "password": "correct-horse-1"})
    accepted = api.post("/invites/accept", json={"invite_token": invite["invite_token"]}, headers=CSRF)
    assert accepted.status_code == 200

    login(api, "finance@example.com")
    api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    assert api.get(f"/documents/{legal_doc['document_id']}").status_code == 403
    assert api.get(f"/documents/{finance_doc['document_id']}").status_code == 200
    activity = api.get(f"/activity?org_id={org_id}").json()
    locked = [item for item in activity["items"] if item["action"] == "document locked"]
    assert [item["resource_id"] for item in locked] == [finance_doc["document_id"]]

    login(api, owner["user"]["email"])
    key = api.post(
        f"/developer/organizations/{org_id}/keys",
        json={
            "name": "acceptance",
            "scopes": ["document.read"],
            "department_id": finance["department_id"],
        },
        headers=CSRF,
    ).json()
    api.cookies.clear()
    headers = {"Authorization": f"Bearer {key['key_token']}"}
    assert api.get(f"/documents/{legal_doc['document_id']}", headers=headers).status_code == 403
    assert api.get(f"/documents/{finance_doc['document_id']}", headers=headers).status_code == 200
    login(api, owner["user"]["email"])
    logs = api.get(f"/developer/organizations/{org_id}/request-logs").json()
    assert logs["total"] >= 2
    assert all("body" not in item for item in logs["items"])