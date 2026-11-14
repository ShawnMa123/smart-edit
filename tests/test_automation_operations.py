"""Projection, anchor validation, fixture proposal and inverse operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.automation.operations import (
    apply_operations,
    build_fixture_proposal,
    build_inverse_operations,
    validate_operations,
)
from app.automation.schemas import (
    Anchor,
    ChangeProposal,
    FixtureProposalCreate,
    ProposalContext,
    ProposalPreview,
    ReplaceTextOperation,
    ReviewReceipt,
)
from app.documents.errors import HostError
from app.documents.projection import project_document, quote_sha256
from app.documents.store import HostStore


def _doc() -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "page one"}]},
            {"type": "pageBreak"},
            {"type": "paragraph", "content": [{"type": "text", "text": "Amount: USD 500,000.00"}]},
        ],
    }


def test_projection_skips_page_breaks_and_uses_code_points():
    projection = project_document(_doc())
    assert projection.text == "page one\n\nAmount: USD 500,000.00"
    assert [block.node_id for block in projection.blocks] == ["b0", "b2"]
    assert projection.blocks[0].start_cp == 0
    assert projection.blocks[1].start_cp == len("page one\n\n")

    emoji = project_document(
        {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "A😀B"}]}]}
    )
    assert emoji.text == "A😀B"
    assert emoji.text[1:2] == "😀"
    assert emoji.blocks[0].end_cp == 3


def _draft(tmp_path) -> dict:
    store = HostStore(tmp_path / "host.db")
    return store.create_document(
        workspace_id="ws_demo_01", owner_user_id="user_a", title="G", content=_doc()
    )


def _proposal(draft: dict, replacement: str = "Reviewed amount") -> ChangeProposal:
    return build_fixture_proposal(
        draft,
        FixtureProposalCreate(
            document_id=draft["document_id"],
            draft_id=draft["draft_id"],
            search_text="Amount: USD 500,000.00",
            replacement_text=replacement,
        ),
        proposal_id="prop_1",
    )


def test_fixture_proposal_is_valid_and_round_trips(tmp_path):
    draft = _draft(tmp_path)
    proposal = _proposal(draft)
    validate_operations(proposal, draft)

    updated, new_text = apply_operations(_doc(), draft["text"], proposal.operations)
    assert new_text == "page one\n\nReviewed amount"
    inverse = build_inverse_operations(draft["text"], new_text, proposal.operations)
    assert inverse[0]["replacement_text"] == "Amount: USD 500,000.00"

    inverse_model = ChangeProposal(
        proposal_id="prop_1",
        context=ProposalContext(
            document_id=draft["document_id"],
            draft_id=draft["draft_id"],
            revision=2,
            content_sha256=__import__("hashlib").sha256(new_text.encode()).hexdigest(),
            variables_version=1,
            authorization_version="auth-demo-1",
        ),
        operations=[ReplaceTextOperation(**item) for item in inverse],
        preview=ProposalPreview(before_text=new_text, after_text=draft["text"]),
        risk_flags=[],
        review_receipt=ReviewReceipt(receipt_id="r", verdict="pass", validator_version="v1"),
        expires_at="9999-01-01T00:00:00+00:00",
    )
    restored, restored_text = apply_operations(updated, new_text, inverse_model.operations)
    assert restored_text == "page one\n\nAmount: USD 500,000.00"
    assert project_document(restored).text == draft["text"]


def test_wrong_quote_is_rejected(tmp_path):
    draft = _draft(tmp_path)
    proposal = _proposal(draft)
    proposal.operations[0].anchor.quote_sha256 = "0" * 64
    with pytest.raises(HostError) as error:
        validate_operations(proposal, draft)
    assert error.value.code == "anchor_mismatch"


def test_overlapping_operations_are_rejected(tmp_path):
    draft = _draft(tmp_path)
    proposal = _proposal(draft)
    original = proposal.operations[0]
    second = original.model_copy(deep=True)
    second.anchor.start_cp += 1
    shifted_quote = draft["text"][second.anchor.start_cp:second.anchor.end_cp]
    second.anchor.quote_sha256 = __import__("hashlib").sha256(shifted_quote.encode()).hexdigest()
    proposal.operations.append(second)
    with pytest.raises(HostError) as error:
        validate_operations(proposal, draft)
    assert error.value.code == "overlapping_operations"


def test_missing_review_is_rejected(tmp_path):
    draft = _draft(tmp_path)
    proposal = _proposal(draft)
    proposal.review_receipt.verdict = "abstain"
    with pytest.raises(HostError) as error:
        validate_operations(proposal, draft)
    assert error.value.code == "review_required"


def test_automation_does_not_import_assistant():
    root = Path(__file__).resolve().parents[1] / "app" / "automation"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from app.assistant" not in text
        assert "import app.assistant" not in text