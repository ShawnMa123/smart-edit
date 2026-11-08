"""Business-type detection (tasks 7.x)."""

from __future__ import annotations

from pathlib import Path

from app.parsing.normalize import build_fields, decide_business_type, detect_business_type
from tests.helpers import make_doc


def test_explicit_urdg_758_is_guarantee():
    """An explicit marker wins (`explicit_independence_clause`)."""
    decision = decide_business_type([make_doc("This guarantee is subject to URDG 758.")])

    assert decision.business_type == "guarantee"
    assert decision.reason == "explicit_independence_clause"
    assert decision.evidence and "URDG 758" in decision.evidence


def test_general_keyword_is_guarantee():
    decision = decide_business_type([make_doc("兹出具保函一份，见保函正文。")])

    assert decision.business_type == "guarantee"
    assert decision.reason == "explicit_keyword"


def test_strong_indicator_wins_over_general_keyword():
    """A step-1 hit must not be overridden by step 2."""
    decision = decide_business_type([make_doc("本保函为独立保函，适用 URDG 758。")])
    assert decision.reason == "explicit_independence_clause"


def test_invoice_only_is_unsupported():
    """Evidence exists but the type is unsupported -> must be distinguished from "no evidence"."""
    decision = decide_business_type([make_doc("INVOICE NO: 2026-0001")])

    assert decision.business_type == "unsupported"
    assert decision.reason == "business_type_not_supported"


def test_no_evidence_is_unsupported_not_guessed():
    """With no evidence we **must not** invent a type just to keep downstream running (task 7.3)."""
    decision = decide_business_type([make_doc("The weather is fine today; material to follow.")])

    assert decision.business_type == "unsupported"
    assert decision.reason == "no_evidence"


def test_decision_recorded_in_trail(fields_yaml):
    """The decision and its evidence must be recorded (task 7.2)."""
    docs = [make_doc("本保函适用 URDG 758。")]
    result = build_fields([], docs, fields_yaml=fields_yaml)

    assert result.business_type == "guarantee"
    decisions = [
        entry
        for entry in result.trail_entries
        if entry["op"] == "pass" and entry["detail"].get("business_type")
    ]
    assert decisions, "the business_type decision must write one pass entry"
    assert decisions[-1]["detail"]["reason"] == "explicit_independence_clause"
    assert decisions[-1]["detail"]["evidence"]


def test_detect_business_type_contract_signature():
    """The contract signature only answers the type (`str`)."""
    assert detect_business_type([make_doc("保函")]) == "guarantee"
    assert detect_business_type([make_doc("unrelated text")]) == "unsupported"


def test_business_type_has_a_single_write_point():
    """11.10 `business_type` has exactly one write point in the codebase (`normalize`)."""
    root = Path(__file__).resolve().parent.parent / "app"
    writers = []
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith('"business_type":'):
                continue
            # two locations are allowed: the pure function (parsing) and the node write-back (nodes)
            writers.append(path.relative_to(root).as_posix())

    assert sorted(set(writers)) == ["nodes/normalize.py", "parsing/normalize.py"], (
        f"business_type write points found in {sorted(set(writers))}, only normalize is allowed"
    )