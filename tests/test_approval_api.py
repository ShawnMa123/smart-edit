"""Submission and two-stage approval API tests (document-submission-approval)."""

from __future__ import annotations

from tests.identity_helpers import CSRF, api, identity_services, login, register  # noqa: F401

PASSWORD = "correct-horse-1"


def _invite(api, org_id: str, email: str, role_key: str):
    invite = api.post(
        f"/organizations/{org_id}/invites",
        json={"email": email, "role_key": role_key},
        headers=CSRF,
    )
    assert invite.status_code == 201, invite.text
    registered = api.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201, registered.text
    accepted = api.post(
        "/invites/accept", json={"invite_token": invite.json()["invite_token"]}, headers=CSRF
    )
    assert accepted.status_code == 200, accepted.text


def _bootstrap(api):
    owner = register(api, "owner@example.com")
    org_id = owner["active_org"]["org_id"]
    for email, role in (
        ("applicant@example.com", "applicant"),
        ("bankops@example.com", "bank_ops"),
        ("compliance@example.com", "compliance"),
        ("member@example.com", "member"),
    ):
        login(api, "owner@example.com")
        _invite(api, org_id, email, role)
    return owner, org_id


def _as(api, email: str, org_id: str):
    login(api, email)
    switched = api.post("/auth/active-org", json={"org_id": org_id}, headers=CSRF)
    assert switched.status_code == 200, switched.text


def _document(api) -> dict:
    created = api.post(
        "/documents",
        json={"title": "Guarantee application", "text": "Amount: USD 250,000.00"},
        headers=CSRF,
    )
    assert created.status_code == 201, created.text
    return created.json()


def _lock(api, document: dict) -> dict:
    lock = api.post(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
        json={"lease_seconds": 60},
        headers=CSRF,
    )
    assert lock.status_code == 201, lock.text
    return lock.json()


def _code(response) -> str | None:
    body = response.json()
    return body.get("code") or (body.get("error") or {}).get("code")


def _submit(api, document: dict, lock: dict) -> dict:
    response = api.post(
        f"/documents/{document['document_id']}/submissions",
        json={
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
            "expected_revision": document["revision"],
            "content_sha256": document["content_sha256"],
        },
        headers=CSRF,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_two_stage_approval_makes_the_document_read_only(api, identity_services):  # noqa: F811
    _, org_id = _bootstrap(api)
    _as(api, "applicant@example.com", org_id)
    document = _document(api)
    lock = _lock(api, document)
    stale = api.post(
        f"/documents/{document['document_id']}/submissions",
        json={
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
            "expected_revision": document["revision"] + 1,
            "content_sha256": document["content_sha256"],
        },
        headers=CSRF,
    )
    assert stale.status_code == 409
    assert _code(stale) == "stale_revision"
    bad_token = api.post(
        f"/documents/{document['document_id']}/submissions",
        json={
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"] + 1,
            "expected_revision": document["revision"],
            "content_sha256": document["content_sha256"],
        },
        headers=CSRF,
    )
    assert bad_token.status_code == 409
    assert _code(bad_token) == "lock_conflict"
    missing_lock = api.post(
        f"/documents/{document['document_id']}/submissions",
        json={
            "lock_id": "lock_missing",
            "fencing_token": lock["fencing_token"],
            "expected_revision": document["revision"],
            "content_sha256": document["content_sha256"],
        },
        headers=CSRF,
    )
    assert missing_lock.status_code == 409
    assert _code(missing_lock) == "lock_conflict"

    submitted = _submit(api, document, lock)
    assert submitted["submission"]["status"] == "pending_first"

    pending_lock = api.post(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
        json={"lease_seconds": 60},
        headers=CSRF,
    )
    assert pending_lock.status_code == 409
    assert _code(pending_lock) == "submission_pending"
    pending_save = api.put(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}",
        headers={"If-Match": f'"draft-{document["revision"]}"', "X-Requested-With": "smart-edit"},
        json={
            "text": "changed while pending",
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
    )
    assert pending_save.status_code == 409
    assert _code(pending_save) == "submission_pending"

    _as(api, "compliance@example.com", org_id)
    early = api.post(
        f"/approvals/{submitted['request']['request_id']}/decisions",
        json={"decision": "approve", "expected_revision": 1},
        headers=CSRF,
    )
    assert early.status_code == 409
    assert _code(early) == "wrong_stage"

    _as(api, "bankops@example.com", org_id)
    inbox = api.get("/approvals?stage=first").json()
    assert len(inbox) == 1
    request_id = inbox[0]["request_id"]
    detail = api.get(f"/approvals/{request_id}").json()
    assert detail["can_decide"] is True
    assert "Amount: USD 250,000.00" in detail["text"]
    first = api.post(
        f"/approvals/{request_id}/decisions",
        json={
            "decision": "approve",
            "comment": "first check ok",
            "expected_revision": detail["approval_revision"],
        },
        headers=CSRF,
    )
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "pending_second"

    _as(api, "compliance@example.com", org_id)
    detail = api.get(f"/approvals/{request_id}").json()
    second = api.post(
        f"/approvals/{request_id}/decisions",
        json={
            "decision": "approve",
            "comment": "compliance ok",
            "expected_revision": detail["approval_revision"],
        },
        headers=CSRF,
    )
    assert second.status_code == 201, second.text
    assert second.json()["status"] == "approved"

    _as(api, "applicant@example.com", org_id)
    view = api.get(f"/documents/{document['document_id']}").json()
    assert view["submission_status"] == "approved"
    locked = api.post(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
        json={"lease_seconds": 60},
        headers=CSRF,
    )
    assert locked.status_code == 409
    assert _code(locked) == "submission_pending"

    activity = api.get(f"/activity?org_id={org_id}").json()
    actions = [item["action"] for item in activity["items"]]
    assert "submission.created" in actions
    assert "approval.first.approved" in actions
    assert "approval.second.approved" in actions
def test_return_allows_edit_and_resubmission_keeps_history(api, identity_services):  # noqa: F811
    _, org_id = _bootstrap(api)
    _as(api, "applicant@example.com", org_id)
    document = _document(api)
    first = _submit(api, document, _lock(api, document))

    _as(api, "bankops@example.com", org_id)
    detail = api.get(f"/approvals/{first['request']['request_id']}").json()
    returned = api.post(
        f"/approvals/{first['request']['request_id']}/decisions",
        json={
            "decision": "return",
            "comment": "please add the expiry date",
            "expected_revision": detail["approval_revision"],
        },
        headers=CSRF,
    )
    assert returned.status_code == 201, returned.text
    assert returned.json()["status"] == "returned"

    _as(api, "applicant@example.com", org_id)
    view = api.get(f"/documents/{document['document_id']}").json()
    assert view["submission_status"] == "returned"
    assert view["submission"]["latest_comment"] == "please add the expiry date"
    lock = _lock(api, document)
    saved = api.put(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}",
        headers={"If-Match": f'"draft-{document["revision"]}"', "X-Requested-With": "smart-edit"},
        json={
            "text": "Amount: USD 250,000.00\nExpiry: 2027-06-30",
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
        },
    )
    assert saved.status_code == 200, saved.text
    second = _submit(api, saved.json(), lock)
    assert second["submission"]["submission_id"] != first["submission"]["submission_id"]

    history = api.get(f"/documents/{document['document_id']}/submissions").json()
    assert len(history) == 2
    assert {row["status"] for row in history} == {"returned", "pending_first"}


def test_approval_permissions_self_approval_and_comments(api, identity_services):  # noqa: F811
    _, org_id = _bootstrap(api)
    _as(api, "applicant@example.com", org_id)
    document = _document(api)
    submitted = _submit(api, document, _lock(api, document))
    request_id = submitted["request"]["request_id"]

    _as(api, "member@example.com", org_id)
    assert api.get(f"/approvals/{request_id}").status_code == 403
    assert api.get(f"/documents/{document['document_id']}/submissions").status_code == 403
    denied = api.post(
        f"/approvals/{request_id}/decisions",
        json={"decision": "approve", "expected_revision": 1},
        headers=CSRF,
    )
    assert denied.status_code == 403

    _as(api, "bankops@example.com", org_id)
    missing = api.post(
        f"/approvals/{request_id}/decisions",
        json={"decision": "return", "comment": "", "expected_revision": 1},
        headers=CSRF,
    )
    assert missing.status_code == 422
    assert _code(missing) == "comment_required"

    # Admin can submit, but cannot approve their own request even with approval.first.
    _as(api, "owner@example.com", org_id)
    own = _document(api)
    own_submission = _submit(api, own, _lock(api, own))
    self_decision = api.post(
        f"/approvals/{own_submission['request']['request_id']}/decisions",
        json={"decision": "approve", "expected_revision": 1},
        headers=CSRF,
    )
    assert self_decision.status_code == 403
    assert _code(self_decision) == "self_approval"