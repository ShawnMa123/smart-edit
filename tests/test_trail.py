"""Operation trail semantics (design §8 / tasks 4.6)."""

from __future__ import annotations

import pytest

from app.trail import overreach_entries, record, record_many

BASE = {"trail": []}


def test_ids_increment_per_agent_and_stage():
    first = record(BASE, agent="agent1", stage="extract", op="read")
    state = {"trail": [*first["trail"]]}
    second = record(state, agent="agent1", stage="extract", op="read")
    state["trail"].extend(second["trail"])
    other_agent = record(state, agent="agent3", stage="extract", op="read")

    assert first["trail"][0]["id"] == "agent1.extract#001"
    assert second["trail"][0]["id"] == "agent1.extract#002"
    assert other_agent["trail"][0]["id"] == "agent3.extract#001"


def test_record_many_fills_agent_and_stage_and_keeps_order():
    update = record_many(
        BASE,
        agent="agent1",
        stage="normalize",
        entries=[
            {"op": "transform", "before": "a", "after": "b", "detail": {}},
            {"op": "emit", "after": "F-1", "ref": "F-1", "detail": {}},
        ],
    )
    assert [entry["id"] for entry in update["trail"]] == [
        "agent1.normalize#001",
        "agent1.normalize#002",
    ]
    assert all(entry["agent"] == "agent1" for entry in update["trail"])
    assert all(entry["stage"] == "normalize" for entry in update["trail"])


def test_overreach_ops_are_recordable_and_detectable():
    state = {"trail": []}
    for op in ("summarize", "rewrite", "drop"):
        state["trail"].extend(
            record(state, agent="agent1", stage="normalize", op=op)["trail"]
        )
    assert {entry["op"] for entry in overreach_entries(state)} == {
        "summarize",
        "rewrite",
        "drop",
    }


def test_unknown_agent_or_op_is_a_bug_not_a_log_line():
    with pytest.raises(ValueError):
        record(BASE, agent="agent9", stage="x", op="read")
    with pytest.raises(ValueError):
        record(BASE, agent="agent1", stage="x", op="invent")
