"""Task 6.4/6.4a + onboarding — reproducible synthetic evaluation (33 questions, lexical only)."""

from __future__ import annotations

from app.assistant.eval import load_cases, run_eval
from tests.assistant_helpers import make_service


def _report(tmp_path):
    return run_eval(make_service(tmp_path))


def test_thirty_three_question_eval_is_reproducible_and_reports_its_limits(tmp_path):
    first = _report(tmp_path / "one")
    second = _report(tmp_path / "two")

    assert first["total"] == 33
    assert [case["id"] for case in load_cases()] == [row["id"] for row in first["cases"]]
    assert first["outcome_accuracy"] >= 0.95
    assert first["citation_hit_rate"] >= 0.9
    assert first["clarification_accuracy"] == 1.0
    assert "未使用向量" in first["notes"] and "重排" in first["notes"]

    # Same corpus + same questions ⇒ same numbers, not a one-off demo result.
    assert first["outcome_accuracy"] == second["outcome_accuracy"]
    assert first["citation_hit_rate"] == second["citation_hit_rate"]
    assert first["clarification_accuracy"] == second["clarification_accuracy"]


def test_every_answered_case_cites_the_expected_fixture_chunk(tmp_path):
    report = _report(tmp_path)
    misses = [
        row for row in report["cases"] if row["expected_outcome"] == "answered" and not row["citation_hit"]
    ]
    assert misses == []
    assert all(row["outcome"] == row["expected_outcome"] for row in report["cases"])