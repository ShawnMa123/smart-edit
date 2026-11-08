"""Extract node: no provider and fixture labelling (tasks 2.4-2.5)."""

from __future__ import annotations

from pathlib import Path

from app.llm import resolve_llm
from app.nodes.extract import extract_node
from tests.helpers import make_doc

FIXTURE = Path("fixtures/llm/extract_sample.json")


def _state() -> dict:
    return {"docs": [make_doc("Amount: USD 500,000.00")], "trail": [], "stages": []}


def test_no_provider_fails_the_stage_loudly():
    """2.4 No provider ⇒ failed stage, no candidates invented."""
    update = extract_node(_state(), llm=None, field_keys=["guarantee_amount"])

    report = update["stages"][0]
    assert report["stage"] == "extract"
    assert report["status"] == "failed"
    assert "no model provider configured" in report["reason"]
    assert update["_candidates"] == []


def test_no_provider_records_a_pass_entry():
    """2.4 The refusal is traceable, not silent."""
    update = extract_node(_state(), llm=None, field_keys=[])
    entry = update["trail"][0]
    assert entry["op"] == "pass"
    assert "no model provider" in entry["detail"]["reason"]


def test_fixture_provider_is_labelled_in_the_stage_reason():
    """2.5 A fixture-backed run is distinguishable from a provider run."""
    llm = resolve_llm(f"fixture:{FIXTURE}")
    update = extract_node(_state(), llm=llm, field_keys=["guarantee_amount"])

    report = update["stages"][0]
    assert report["status"] == "done"
    assert "fixture:" in report["reason"]
    assert update["_candidates"], "the fixture does replay candidates"


def test_plain_provider_has_no_fixture_label():
    """2.5 A provider without the attribute leaves the reason empty."""
    update = extract_node(_state(), llm=lambda prompt: [], field_keys=["guarantee_amount"])

    report = update["stages"][0]
    assert report["status"] == "done"
    assert report["reason"] is None