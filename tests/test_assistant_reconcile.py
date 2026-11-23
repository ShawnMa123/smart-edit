"""Structurally reconciling model answers (REVIEW_FAILED guard / design D3)."""

from __future__ import annotations

from app.assistant.domain.state_machine import validate_answer
from app.assistant.pipeline import reconcile_answer
from app.assistant.schemas import Answer, Citation, Claim

CITATION = Citation(
    id="cite_1",
    source_type="trade_rule",
    title="Guide",
    source_version="v1",
    locator={},
)


def answer(**overrides) -> Answer:
    base = {
        "outcome": "answered",
        "language": "en",
        "support_level": "strong",
        "claims": [
            Claim(id="c1", text="Supported claim.", kind="fact", citation_ids=["cite_1"])
        ],
        "citations": [CITATION],
    }
    base.update(overrides)
    return Answer(**base)


def test_answered_without_claims_becomes_insufficient():
    reconciled = reconcile_answer(answer(claims=[], citations=[]))

    assert reconciled.outcome == "insufficient_evidence"
    assert reconciled.support_level == "insufficient"
    assert reconciled.claims == []
    assert reconciled.limitations
    assert validate_answer(reconciled) == []


def test_non_answered_with_claims_drops_the_claims():
    reconciled = reconcile_answer(answer(outcome="insufficient_evidence", support_level="insufficient"))

    assert reconciled.outcome == "insufficient_evidence"
    assert reconciled.claims == [] and reconciled.citations == []
    assert validate_answer(reconciled) == []


def test_clarification_questions_on_another_outcome_are_cleared():
    reconciled = reconcile_answer(
        answer(
            outcome="unable_to_assess",
            support_level="insufficient",
            clarification_questions=["Which rule version?"],
        )
    )

    assert reconciled.clarification_questions == []
    assert validate_answer(reconciled) == []


def test_needs_clarification_without_questions_downgrades():
    reconciled = reconcile_answer(
        answer(outcome="needs_clarification", support_level="not_applicable", clarification_questions=[])
    )

    assert reconciled.outcome == "unable_to_assess"
    assert reconciled.support_level == "insufficient"
    assert validate_answer(reconciled) == []


def test_answered_support_level_is_capped_to_a_publishable_value():
    reconciled = reconcile_answer(answer(support_level="insufficient"))

    assert reconciled.support_level == "qualified"
    assert validate_answer(reconciled) == []


def test_handoff_without_target_downgrades():
    reconciled = reconcile_answer(answer(outcome="needs_handoff", support_level="not_applicable"))

    assert reconciled.outcome == "unable_to_assess"
    assert validate_answer(reconciled) == []