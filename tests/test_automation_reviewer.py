"""Rewrite pipeline and server-side Reviewer."""

from __future__ import annotations

import json

from app.automation.operations import build_fixture_proposal
from app.automation.pipeline import build_rewrite
from app.automation.reviewer import review_proposal
from app.automation.schemas import FixtureProposalCreate
from app.documents.store import HostStore


def _draft(tmp_path) -> dict:
    store = HostStore(tmp_path / "host.db")
    return store.create_document(
        workspace_id="ws_demo_01",
        owner_user_id="user_a",
        title="G",
        text="Amount: USD 500,000.00",
    )


def test_reviewer_passes_a_valid_proposal(tmp_path):
    draft = _draft(tmp_path)
    proposal = build_fixture_proposal(
        draft,
        FixtureProposalCreate(
            document_id=draft["document_id"],
            draft_id=draft["draft_id"],
            search_text="Amount:",
            replacement_text="Reviewed amount:",
        ),
        proposal_id="prop-1",
    )
    result = review_proposal(proposal, draft)
    assert result.passed
    assert result.receipt and result.receipt.verdict == "pass"


def test_reviewer_abstains_on_a_tampered_anchor(tmp_path):
    draft = _draft(tmp_path)
    proposal = build_fixture_proposal(
        draft,
        FixtureProposalCreate(
            document_id=draft["document_id"],
            draft_id=draft["draft_id"],
            search_text="USD 500,000.00",
            replacement_text="USD 600,000.00",
        ),
        proposal_id="prop-1",
    )
    proposal.operations[0].anchor.quote_sha256 = "0" * 64
    result = review_proposal(proposal, draft)
    assert not result.passed
    assert "anchor_mismatch" in result.issues


def test_polish_with_a_fact_change_returns_clarification(tmp_path):
    draft = _draft(tmp_path)
    outcome = build_rewrite(
        draft,
        {
            "intent": "polish",
            "search_text": "USD 500,000.00",
            "replacement_text": "USD 600,000.00",
        },
        proposal_id="prop-1",
    )
    assert outcome.outcome == "needs_clarification"
    assert outcome.proposal is None
    assert outcome.details and "protected_fact_change" in outcome.details.reason_codes


def test_replace_text_with_a_fact_change_carries_risk_flags(tmp_path):
    draft = _draft(tmp_path)
    outcome = build_rewrite(
        draft,
        {
            "intent": "replace_text",
            "search_text": "USD 500,000.00",
            "replacement_text": "USD 600,000.00",
        },
        proposal_id="prop-1",
    )
    assert outcome.outcome == "proposal_ready"
    assert outcome.proposal is not None
    assert "substantive_change" in outcome.proposal.risk_flags
    assert "changed_amount" in outcome.proposal.risk_flags


def test_proposal_context_is_bound_to_the_draft(tmp_path):
    draft = _draft(tmp_path)
    outcome = build_rewrite(
        draft,
        {"intent": "replace_text", "search_text": "Amount:", "replacement_text": "Reviewed amount:"},
        proposal_id="prop-1",
    )
    assert outcome.proposal is not None
    assert outcome.proposal.context.content_sha256 == draft["text_sha256"]
    assert outcome.proposal.context.variables_version == draft["variables_version"]
    assert json.loads(draft["content_json"])["type"] == "doc"