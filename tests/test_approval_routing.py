"""Approval routing: bank-originated drafts are reviewed by the counterparty first."""

from __future__ import annotations

import pytest

from app.approval.service import (
    ROUTE_BANK_FIRST,
    ROUTE_COUNTERPARTY_FIRST,
    ApprovalService,
)
from app.documents.bootstrap import build_host_services
from app.documents.errors import HostError
from app.identity.errors import Forbidden
from app.shared.ports import Principal


class _Permissions:
    def permissions(self, principal: Principal, scope) -> set[str]:  # noqa: ANN001 - port shape
        return set(principal.capabilities)


class _Authorizer:
    def __init__(self) -> None:
        self.authorization = _Permissions()

    def organization(self, workspace_id: str) -> dict:
        return {"org_id": "org_1", "workspace_id": workspace_id}

    def authorize(self, principal: Principal, action: str, document) -> None:  # noqa: ANN001
        if action not in principal.capabilities:
            raise Forbidden()


def _principal(user_id: str, roles: tuple[str, ...], capabilities: tuple[str, ...]) -> Principal:
    return Principal(
        user_id=user_id,
        workspace_id="ws_demo_01",
        roles=roles,
        capabilities=(*capabilities, "document.read"),
    )


BANK = _principal(
    "usr_bank",
    ("bank_ops",),
    ("document.edit", "document.lock", "approval.submit", "approval.first"),
)
BANK_COLLEAGUE = _principal(
    "usr_bank_2",
    ("bank_ops",),
    ("document.edit", "document.lock", "approval.submit", "approval.first"),
)
CUSTOMER = _principal(
    "usr_customer",
    ("applicant",),
    ("document.edit", "document.lock", "approval.submit", "approval.counterparty"),
)
COMPLIANCE = _principal(
    "usr_compliance",
    ("compliance",),
    ("approval.second",),
)


def _submit(host, service: ApprovalService, principal: Principal, document_id: str) -> dict:
    host.store.create_document(
        workspace_id="ws_demo_01",
        owner_user_id=principal.user_id,
        title=document_id,
        text="Amount: USD 1.00",
        document_id=document_id,
    )
    draft = host.store.find_draft_by_document(document_id)
    assert draft is not None
    lock = host.store.acquire_lock(
        draft_id=draft["draft_id"], owner_user_id=principal.user_id, lease_seconds=120
    )
    result = service.submit(
        principal,
        document_id,
        {
            "lock_id": lock["lock_id"],
            "fencing_token": lock["fencing_token"],
            "expected_revision": int(draft["revision"]),
            "content_sha256": draft["text_sha256"],
        },
    )
    return result["request"]


def test_the_route_follows_the_submitters_side(tmp_path):
    host = build_host_services(db_path=tmp_path / "host.db", mode="test")
    service = ApprovalService(host.store, _Authorizer(), ids=None)

    bank_request = _submit(host, service, BANK, "doc-bank")
    assert bank_request["route"] == ROUTE_COUNTERPARTY_FIRST

    customer_request = _submit(host, service, CUSTOMER, "doc-customer")
    assert customer_request["route"] == ROUTE_BANK_FIRST


def test_each_side_only_sees_its_own_first_stage_inbox(tmp_path):
    host = build_host_services(db_path=tmp_path / "host.db", mode="test")
    service = ApprovalService(host.store, _Authorizer(), ids=None)
    bank_request = _submit(host, service, BANK, "doc-bank")
    customer_request = _submit(host, service, CUSTOMER, "doc-customer")

    bank_inbox = service.inbox(BANK, "first")
    assert [row["request_id"] for row in bank_inbox] == [customer_request["request_id"]]
    assert bank_inbox[0]["route"] == ROUTE_BANK_FIRST

    customer_inbox = service.inbox(CUSTOMER, "first")
    assert [row["request_id"] for row in customer_inbox] == [bank_request["request_id"]]
    assert customer_inbox[0]["route"] == ROUTE_COUNTERPARTY_FIRST


def test_the_wrong_party_cannot_decide_the_first_stage(tmp_path):
    host = build_host_services(db_path=tmp_path / "host.db", mode="test")
    service = ApprovalService(host.store, _Authorizer(), ids=None)
    # A colleague submits for the bank side, so the request is not blocked by self-approval.
    request = _submit(host, service, BANK_COLLEAGUE, "doc-bank")

    with pytest.raises(HostError) as failure:
        service.decide(
            BANK,
            request["request_id"],
            {"decision": "approve", "expected_revision": 1},
        )
    assert failure.value.status == 409
    assert failure.value.code == "wrong_approver"

    approved = service.decide(
        CUSTOMER,
        request["request_id"],
        {"decision": "approve", "expected_revision": 1},
    )
    assert approved["status"] == "pending_second"

    # Compliance remains the second stage for both routes.
    final = service.decide(
        COMPLIANCE,
        request["request_id"],
        {"decision": "approve", "expected_revision": 2},
    )
    assert final["status"] == "approved"