"""My submissions across documents: the applicant's inbox survives a page refresh."""

from __future__ import annotations

from app.approval.service import ApprovalService
from app.documents.bootstrap import build_host_services
from app.shared.ports import Principal


class _Authorizer:
    """PG authorizer stub: every document is readable in this unit test."""

    def authorize(self, principal, action, document) -> None:  # noqa: ANN001 - port signature
        return None

    def organization(self, workspace_id: str) -> dict:
        return {"org_id": "org_1", "workspace_id": workspace_id}


def test_my_submissions_spans_every_document(tmp_path):
    host = build_host_services(db_path=tmp_path / "host.db", mode="test")
    store = host.store
    for document_id, title in (("doc-a", "Guarantee"), ("doc-b", "Commercial invoice")):
        store.create_document(
            workspace_id="ws_demo_01",
            owner_user_id="usr_app",
            title=title,
            text=f"{title} body",
            document_id=document_id,
        )
        draft = store.find_draft_by_document(document_id)
        assert draft is not None
        lock = store.acquire_lock(
            draft_id=draft["draft_id"], owner_user_id="usr_app", lease_seconds=120
        )
        store.create_submission(
            document_id=document_id,
            draft_id=draft["draft_id"],
            submitted_by="usr_app",
            lock_id=lock["lock_id"],
            fencing_token=lock["fencing_token"],
            expected_revision=int(draft["revision"]),
            expected_sha256=draft["text_sha256"],
        )

    service = ApprovalService(store, _Authorizer(), ids=None)
    principal = Principal(
        user_id="usr_app",
        workspace_id="ws_demo_01",
        roles=("applicant",),
        capabilities=("read", "approval.submit"),
    )

    items = service.my_submissions(principal)

    assert {item["document_id"] for item in items} == {"doc-a", "doc-b"}
    assert {item["title"] for item in items} == {"Guarantee", "Commercial invoice"}
    assert all(item["status"] == "pending_first" for item in items)
    assert all(item["submitted_by"] == "usr_app" for item in items)