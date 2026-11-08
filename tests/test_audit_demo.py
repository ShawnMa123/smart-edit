"""Task 14.2 — the demo script's template scenarios, run in-process (no HTTP, no files written)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path("scripts/audit_demo.py")


def _demo():
    spec = importlib.util.spec_from_file_location("audit_demo_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_demo_reports_a_matched_template_and_an_ambiguous_one():
    """14.2 "template matched" passes; "two templates match" refuses to choose."""
    payload = _demo().build_report()
    runs = {run["label"]: run for run in payload["template_runs"]}

    matched = runs["template matched"]
    assert matched["template_id"] == "adidas-guarantee"
    assert matched["version"] == "1.0.0"
    assert matched["synthetic"] is True
    assert matched["planned"] == 58
    assert matched["template_units"] == 6
    assert matched["outcome"] == "no_findings"
    assert matched["conflicts"] == []
    assert matched["findings"] == []

    ambiguous = runs["two templates match"]
    assert ambiguous["template_id"] is None
    assert ambiguous["reason"] == "ambiguous_template"
    assert sorted(ambiguous["candidates"]) == [
        "adidas-guarantee",
        "adidas-guarantee-second",
    ]
    assert ambiguous["outcome"] == "unable_to_assess"
    assert ambiguous["template_units"] == 1, "only the resolution unit is planned"


def test_the_demo_still_reports_the_untemplated_baseline():
    """14.2 The three rule-bundle scenarios are untouched by the template work."""
    payload = _demo().build_report()

    assert [run["planned"] for run in payload["runs"]] == [51, 51, 51]
    assert [run["outcome"] for run in payload["runs"]] == [
        "no_findings",
        "findings_present",
        "needs_input",
    ]
    assert payload["stale_after_edit"]["decision"] == "indeterminate"