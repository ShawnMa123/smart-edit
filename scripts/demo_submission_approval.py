#!/usr/bin/env python
"""End-to-end submission/approval demo against a running PG-mode server.

Requires the seeded accounts (`scripts/seed_identity_users.py --reset`) and the dev server.

    .venv/bin/python scripts/demo_submission_approval.py
"""

from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("SMART_EDIT_BASE_URL", "http://127.0.0.1:8000")
PASSWORD = {
    "applicant@atlas-trade.test": "Applicant!2026",
    "bankops@atlas-trade.test": "BankOps!2026",
    "compliance@atlas-trade.test": "Compliance!2026",
}
HEADERS = {"X-Requested-With": "smart-edit"}


def client(email: str) -> httpx.Client:
    http = httpx.Client(base_url=BASE, headers=HEADERS, timeout=30)
    login = http.post("/auth/login", json={"email": email, "password": PASSWORD[email]})
    if login.status_code != 200:
        raise SystemExit(f"login failed for {email}: {login.status_code} {login.text}")
    return http


def code(response: httpx.Response) -> str:
    body = response.json()
    return body.get("code") or (body.get("error") or {}).get("code") or ""


def create_document(http: httpx.Client, title: str) -> dict:
    response = http.post(
        "/documents",
        json={"title": title, "text": "Amount: USD 250,000.00\nExpiry: 2027-06-30"},
    )
    if response.status_code != 201:
        raise SystemExit(f"create document failed: {response.status_code} {response.text}")
    return response.json()


def lock_document(http: httpx.Client, document: dict) -> dict:
    response = http.post(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
        json={"lease_seconds": 60},
    )
    if response.status_code != 201:
        raise SystemExit(f"lock failed: {response.status_code} {response.text}")
    return response.json()


def submit(http: httpx.Client, document: dict, lock: dict) -> dict:
    response = http.post(
        f"/documents/{document['document_id']}/submissions",
        json={
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
            "expected_revision": document["revision"],
            "content_sha256": document["content_sha256"],
        },
    )
    if response.status_code != 201:
        raise SystemExit(f"submit failed: {response.status_code} {response.text}")
    return response.json()


def decide(http: httpx.Client, request_id: str, decision: str, comment: str) -> dict:
    detail = http.get(f"/approvals/{request_id}").json()
    response = http.post(
        f"/approvals/{request_id}/decisions",
        json={
            "decision": decision,
            "comment": comment,
            "expected_revision": detail["approval_revision"],
        },
    )
    if response.status_code != 201:
        raise SystemExit(f"decision failed: {response.status_code} {response.text}")
    return response.json()


def main() -> int:
    applicant = client("applicant@atlas-trade.test")
    bankops = client("bankops@atlas-trade.test")
    compliance = client("compliance@atlas-trade.test")

    document = create_document(applicant, "Approval demo")
    submission = submit(applicant, document, lock_document(applicant, document))
    request_id = submission["request"]["request_id"]
    print(f"1. submitted {submission['submission']['submission_id']} status={submission['submission']['status']}")

    pending = applicant.post(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
        json={"lease_seconds": 60},
    )
    assert pending.status_code == 409 and code(pending) == "submission_pending"
    print("2. applicant lock while pending -> 409 submission_pending")

    first = decide(bankops, request_id, "approve", "first check ok")
    print(f"3. bank operations approve -> {first['status']}")
    second = decide(compliance, request_id, "approve", "compliance ok")
    print(f"4. compliance approve -> {second['status']}")

    approved = applicant.get(f"/documents/{document['document_id']}").json()
    assert approved["submission_status"] == "approved"
    locked = applicant.post(
        f"/documents/{document['document_id']}/drafts/{document['draft_id']}/lock",
        json={"lease_seconds": 60},
    )
    assert locked.status_code == 409
    print("5. approved document is read-only (lock -> 409)")

    returned_document = create_document(applicant, "Returned demo")
    returned_submission = submit(
        applicant, returned_document, lock_document(applicant, returned_document)
    )
    returned = decide(
        bankops,
        returned_submission["request"]["request_id"],
        "return",
        "add the expiry date",
    )
    print(f"6. bank operations return -> {returned['status']}")
    assert returned["status"] == "returned"
    relock = lock_document(applicant, returned_document)
    saved = applicant.put(
        f"/documents/{returned_document['document_id']}/drafts/{returned_document['draft_id']}",
        headers={"If-Match": f'"draft-{returned_document["revision"]}"'},
        json={
            "text": "Amount: USD 250,000.00\nExpiry: 2027-06-30",
            "lock_id": relock["lock_id"],
            "fencing_token": relock["fencing_token"],
        },
    )
    assert saved.status_code == 200
    again = submit(applicant, saved.json(), relock)
    print(f"7. returned -> edit -> resubmit {again['submission']['submission_id']}")
    history = applicant.get(
        f"/documents/{returned_document['document_id']}/submissions"
    ).json()
    assert len(history) == 2

    activity = applicant.get(
        f"/activity?org_id={applicant.get('/auth/me').json()['active_org']['org_id']}"
    ).json()
    actions = [item["action"] for item in activity["items"]]
    print("8. activity:", ", ".join(sorted(set(actions))))
    applicant.close()
    bankops.close()
    compliance.close()
    print("OK: two-stage approval, read-only, return and resubmission all verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())