"""Tasks 12.1-12.3 — clause and declaration checks: presence, exact text, semantic stays out."""

from __future__ import annotations

from pathlib import Path

from app.audit.clauses import (
    CLAUSE_NOT_FOUND,
    CONTROLLED_TEXT_DIFFERS,
    DECLARATION_MISSING,
    NO_DOCUMENT_TEXT,
    OPTIONAL_CLAUSE_ABSENT,
    SEMANTIC_NOT_IMPLEMENTED,
    check_id,
    evaluate_clause_unit,
    evaluate_declaration_unit,
)
from app.rules.templates import (
    ClauseRequirement,
    DeclarationRequirement,
    load_template,
)
from app.rules.types import FINDING, NOT_APPLICABLE, PASS, UNABLE_TO_ASSESS, Unit

PACK = load_template(Path("app/templates/adidas-guarantee.yaml"))


def _unit(kind: str, item_id: str) -> Unit:
    return Unit(check_id=check_id(PACK, kind, item_id), family="template")


def _state(*texts: str) -> dict:
    return {
        "docs": [{"file_id": f"F-{index}", "full_text": text} for index, text in enumerate(texts)]
    }


PAYMENT = ClauseRequirement(
    clause_id="payment",
    requirement="required",
    text="Payment shall be made in USD within 30 days of presentation.",
    gate_type="hard_block",
    severity="critical",
)
CONTROLLED = ClauseRequirement(
    clause_id="law",
    requirement="controlled",
    text="This guarantee is governed by the laws of England and Wales.",
    gate_type="hard_block",
    severity="critical",
)
OPTIONAL = ClauseRequirement(
    clause_id="optional-one",
    requirement="optional",
    text="Notices shall be given by courier.",
    gate_type="advisory",
    severity="warn",
)
SEMANTIC = ClauseRequirement(
    clause_id="semantic-one",
    requirement="semantic_equivalent",
    text="Payment shall be made promptly.",
    gate_type="human_review",
    severity="warn",
)
DECLARATION = DeclarationRequirement(
    declaration_id="lawful-source",
    text="We confirm the funds are from lawful sources.",
    gate_type="human_review",
    severity="warn",
    waivable=True,
)


def test_a_required_clause_is_found_or_reported_missing():
    """12.1 Presence is the first, coarsest question."""
    present = evaluate_clause_unit(
        _unit("clause", "payment"),
        PAYMENT,
        PACK,
        _state("... Payment shall be made in USD within 30 days of presentation. ..."),
    )
    missing = evaluate_clause_unit(_unit("clause", "payment"), PAYMENT, PACK, _state("nothing here"))

    assert present.status == PASS
    assert missing.status == FINDING
    assert missing.detail["reason"] == CLAUSE_NOT_FOUND
    assert missing.finding["gate_type"] == "hard_block"
    assert "Payment shall be made" in missing.finding["evidence"]


def test_a_controlled_clause_must_match_verbatim():
    """12.1 "Reworded" is never "equivalent" — it is a finding with its own reason."""
    reworded = evaluate_clause_unit(
        _unit("clause", "law"),
        CONTROLLED,
        PACK,
        _state("This guarantee is governed by the laws of England."),
    )

    assert reworded.status == FINDING
    assert reworded.detail["reason"] == CONTROLLED_TEXT_DIFFERS
    assert "equivalent" not in reworded.finding["title"].lower()


def test_whitespace_and_full_width_differences_still_match():
    """12.1 Fixed normalization absorbs spacing and full-width forms, nothing more."""
    text = "This guarantee is governed by  the laws of England and Wales.  "
    loose = ClauseRequirement(
        clause_id="law",
        requirement="controlled",
        text="This guarantee is governed by the laws of England and Wales.",
        gate_type="hard_block",
        severity="critical",
    )

    result = evaluate_clause_unit(_unit("clause", "law"), loose, PACK, _state(text))

    assert result.status == PASS


def test_an_absent_optional_clause_is_not_a_defect():
    """12.1 Optional means optional: `not_applicable`, not a finding."""
    result = evaluate_clause_unit(_unit("clause", "optional-one"), OPTIONAL, PACK, _state("nothing"))

    assert result.status == NOT_APPLICABLE
    assert result.reason_code == OPTIONAL_CLAUSE_ABSENT
    assert result.finding is None


def test_semantic_equivalence_is_never_judged():
    """12.2 The one thing this build must not fake: keyword matching dressed up as equivalence."""
    for text in ("Payment shall be made promptly.", "Payment shall be made promptly!", "unrelated"):
        result = evaluate_clause_unit(_unit("clause", "semantic-one"), SEMANTIC, PACK, _state(text))

        assert result.status == UNABLE_TO_ASSESS
        assert result.reason_code == SEMANTIC_NOT_IMPLEMENTED
        assert result.finding is None, "an undecidable clause must not accuse the document"


def test_a_missing_declaration_is_a_finding():
    """12.3 Internal policy judges presence only."""
    result = evaluate_declaration_unit(
        _unit("declaration", "lawful-source"), DECLARATION, PACK, _state("a guarantee without it")
    )

    assert result.status == FINDING
    assert result.detail["reason"] == DECLARATION_MISSING
    assert result.detail["waivable"] is True, "waivability comes from the template, not from severity"
    assert result.finding["category"] == "internal_policy"


def test_a_present_declaration_passes_without_claiming_legality():
    """12.3 "The declaration is there" is all this check may say."""
    result = evaluate_declaration_unit(
        _unit("declaration", "lawful-source"),
        DECLARATION,
        PACK,
        _state("We confirm the funds are from lawful sources."),
    )

    assert result.status == PASS
    assert result.finding is None


def test_no_document_text_is_unable_to_assess():
    """12.1 Without text there is nothing to search, so nothing may pass."""
    result = evaluate_clause_unit(_unit("clause", "payment"), PAYMENT, PACK, {"docs": []})

    assert result.status == UNABLE_TO_ASSESS
    assert result.reason_code == NO_DOCUMENT_TEXT