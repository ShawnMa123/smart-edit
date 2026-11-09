"""Controlled repair (design §12)."""

from __future__ import annotations

from app.nodes.repair import (
    repair_node,
    repair_targets,
    route_after_repair,
    route_after_verifier,
)


def _verification(*checks: dict, score: float | None = None) -> dict:
    return {
        "checks": list(checks),
        "verdict": "fail",
        "credibility": {},
        "score": score,
    }


def test_low_score_does_not_trigger_a_rerun():
    verification = _verification(score=0.01)
    verification["verdict"] = "pass"
    state = {"verification": verification, "repair_count": 0}
    assert route_after_verifier(state) == "hitl"


def test_fixable_failure_routes_to_repair():
    state = {
        "verification": _verification(
            {
                "checker": "evidence_locatable",
                "level": "fail",
                "finding_ids": ["B-001"],
                "detail": "span missing",
                "location": "applicant_name",
            }
        ),
        "repair_count": 0,
    }
    assert route_after_verifier(state) == "repair"


def test_unrepairable_failure_goes_to_a_human():
    state = {
        "verification": _verification(
            {"checker": "source_missing", "level": "fail", "finding_ids": [], "detail": "x"}
        ),
        "repair_count": 0,
    }
    assert route_after_verifier(state) == "hitl"
    assert repair_targets(state["verification"]) == (set(), [])


def test_budget_exhausted_goes_to_a_human():
    state = {
        "verification": _verification(
            {"checker": "span_locatable", "level": "fail", "finding_ids": ["B-1"]}
        ),
        "repair_count": 1,
    }
    assert route_after_verifier(state) == "hitl"


def test_unknown_failure_is_not_assumed_repairable():
    feedback_targets, _ = repair_targets(
        _verification({"checker": "some_new_checker", "level": "fail"})
    )
    assert feedback_targets == set()


def test_repair_clears_only_the_failing_branch_and_keeps_feedback():
    state = {
        "findings": [
            {"id": "N-001", "source": "normalization"},
            {"id": "B-001", "source": "business"},
            {"id": "R-001", "source": "regulatory"},
        ],
        "legal": {"summary": "old"},
        "retrieved": [{"chunk_id": "c1"}],
        "verification": _verification(
            {
                "checker": "citation_present",
                "level": "fail",
                "finding_ids": ["R-001"],
                "detail": "no citation",
                "location": "R-001",
            }
        ),
        "repair_count": 0,
        "trail": [],
    }
    update = repair_node(state)

    assert update["requested_stages"] == ["agent3"]
    assert [f["id"] for f in update["findings"].value] == ["N-001", "B-001"]
    assert update["legal"] is None
    assert update["retrieved"] == []
    assert update["repair_count"] == 1
    assert "verification" not in update, "verification stays as feedback"
    feedback = update["trail"][0]["detail"]["feedback"][0]
    assert feedback["location"] == "R-001"
    assert "expect" in feedback


def test_repair_router_prefers_agent2_then_agent3():
    assert route_after_repair({"requested_stages": ["agent2", "agent3"]}) == "agent2"
    assert route_after_repair({"requested_stages": ["agent3"]}) == "agent3"
    assert route_after_repair({"requested_stages": []}) == "hitl"


def test_repair_without_targets_returns_no_branch():
    update = repair_node({"verification": _verification(), "repair_count": 0})
    assert update == {"requested_stages": []}
