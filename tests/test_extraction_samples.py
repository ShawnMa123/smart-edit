"""Task 5.3 — three deterministic regression samples, no network and no model."""

from __future__ import annotations

from pathlib import Path

from app.parsing.extraction_profile import load_profile_by_id
from app.runtime import execute_chain
from tests.helpers import make_doc

SAMPLES = Path("fixtures/extraction")
AUDIT_AS_OF = "2026-11-19"


def _run(name: str, fields_yaml) -> dict:
    text = (SAMPLES / f"{name}.txt").read_text(encoding="utf-8")
    profile = load_profile_by_id("guarantee-default", fields_config=fields_yaml)
    state = {
        "run_id": f"R-{name}",
        "docs": [make_doc(text, file_id="F-1")],
        "trail": [],
        "stages": [],
        "findings": [],
    }
    execute_chain(
        state,
        ["extract", "normalize", "audit"],
        llm=None,  # deterministic profile: no provider is needed
        fields_yaml=fields_yaml,
        profile=profile,
        as_of=AUDIT_AS_OF,
    )
    return state


def _rule_ids(state: dict) -> set[str]:
    return {finding["rule_id"] for finding in state["findings"]}


def test_the_normal_sample_is_read_from_the_current_text(fields_yaml):
    state = _run("normal", fields_yaml)

    extract = next(report for report in state["stages"] if report["stage"] == "extract")
    assert extract["reason"] == "deterministic profile guarantee-default@1.0.0"
    assert extract["model_calls"] == 0
    assert state["verification"]["extraction"]["source"] == "deterministic"
    assert state["fields"]["guarantee_amount"]["value"] == "500000.00"
    assert state["fields"]["issue_date"]["value"] == "2026-11-19"
    assert state["fields"]["governing_rules"]["value"] == "URDG 758"
    assert "CO-ISSUE-NOT-PAST" not in _rule_ids(state)
    assert "GR-AMOUNT-POSITIVE" not in _rule_ids(state)


def test_an_issue_date_in_the_past_produces_the_company_finding(fields_yaml):
    state = _run("issue-date-past", fields_yaml)

    assert state["fields"]["issue_date"]["value"] == "2026-11-18"
    assert "CO-ISSUE-NOT-PAST" in _rule_ids(state)


def test_a_negative_amount_produces_the_positive_amount_finding(fields_yaml):
    state = _run("amount-negative", fields_yaml)

    assert state["fields"]["guarantee_amount"]["value"] == "-500.00"
    assert "GR-AMOUNT-POSITIVE" in _rule_ids(state)