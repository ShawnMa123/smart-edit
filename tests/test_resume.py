"""Resume semantics (design §11 / tasks 8.6)."""

from __future__ import annotations

from app.runner import Runner
from app.runs import RunStore
from app.store import RunStore as Ledger
from tests.graph_helpers import FakeLLM, initial_state, sample_source, build_test_graph


def _runner(tmp_path, *, llm=None):
    runs = RunStore(runs_dir=tmp_path / "runs")
    thread_id, state = runs.create()
    state.update(initial_state(tmp_path))
    # `create()` already set run_id/files; make the source path point at this test's file.
    state["files"] = [sample_source(tmp_path)]
    runner = Runner(
        runs,
        graph=build_test_graph(llm or FakeLLM()),
        ledger=Ledger(tmp_path / "ledger.sqlite"),
    )
    return runner, thread_id, state


def test_resume_does_not_rerun_parse_or_extract(tmp_path):
    llm = FakeLLM()
    runner, thread_id, state = _runner(tmp_path, llm=llm)
    first = runner.start(thread_id)
    assert first["status"] == "interrupted"
    calls_before = llm.calls
    stages_before = [report["stage"] for report in state["stages"]]
    assert stages_before.count("parse") == 1
    assert stages_before.count("extract") == 1

    runner.resume(thread_id, {"edits": [], "recheck": False})

    assert llm.calls == calls_before
    assert [report["stage"] for report in state["stages"]].count("parse") == 1
    assert [report["stage"] for report in state["stages"]].count("extract") == 1


def test_resume_edits_keep_old_value_and_write_a_transform_trail(tmp_path):
    runner, thread_id, state = _runner(tmp_path)
    runner.start(thread_id)
    old = state["fields"]["currency"]["value"]

    result = runner.resume(
        thread_id,
        {"edits": [{"key": "currency", "value": "EUR"}], "recheck": False},
    )

    assert result["status"] == "complete"
    field = state["fields"]["currency"]
    assert field["value"] == "EUR"
    assert field["confirmed"] is True
    assert field["edited_by_user"] is True
    assert field["normalized_from"] == old

    transforms = [
        entry
        for entry in state["trail"]
        if entry["stage"] == "hitl" and entry["op"] == "transform"
    ]
    assert len(transforms) == 1
    assert transforms[0]["before"] == old
    assert transforms[0]["after"] == "EUR"
    assert transforms[0]["ref"] == "currency"


def test_repeated_edits_to_one_field_keep_the_first_original_value(tmp_path):
    runner, thread_id, state = _runner(tmp_path)
    runner.start(thread_id)
    original = state["fields"]["currency"]["value"]

    runner.resume(
        thread_id,
        {
            "edits": [
                {"key": "currency", "value": "EUR"},
                {"key": "currency", "value": "GBP"},
            ],
            "recheck": False,
        },
    )

    field = state["fields"]["currency"]
    assert field["value"] == "GBP"
    assert field["normalized_from"] == original


def test_duplicate_resume_is_applied_once(tmp_path):
    runner, thread_id, state = _runner(tmp_path)
    runner.start(thread_id)
    payload = {"edits": [{"key": "currency", "value": "EUR"}], "recheck": False}

    first = runner.resume(thread_id, payload)
    hitl_after_first = [r for r in state["stages"] if r["stage"] == "hitl"]
    trail_after_first = len(state["trail"])
    second = runner.resume(thread_id, payload)

    assert first["status"] == "complete"
    assert second["status"] == "complete"
    assert len([r for r in state["stages"] if r["stage"] == "hitl"]) == len(hitl_after_first)
    assert len(state["trail"]) == trail_after_first
    assert state["fields"]["currency"]["value"] == "EUR"


def test_recheck_returns_to_the_review_panel_without_reparsing(tmp_path):
    llm = FakeLLM()
    runner, thread_id, state = _runner(tmp_path, llm=llm)
    runner.start(thread_id)
    calls_before = llm.calls
    parse_before = [r for r in state["stages"] if r["stage"] == "parse"]

    result = runner.resume(
        thread_id, {"edits": [{"key": "currency", "value": "EUR"}], "recheck": True}
    )

    assert result["status"] == "interrupted"
    assert llm.calls == calls_before
    assert [r for r in state["stages"] if r["stage"] == "parse"] == parse_before
    assert int(state["recheck_count"]) == 1
    # The second review round is a new interrupt with a fresh payload.
    assert result["interrupt"]["run_id"] == state["run_id"]


def test_events_reconstruct_node_stage_and_trail_views(tmp_path):
    runner, thread_id, state = _runner(tmp_path)
    runner.start(thread_id)
    runner.resume(thread_id, {"edits": [], "recheck": False})

    events = runner.events(thread_id)
    kinds = {event["type"] for event in events}
    assert {"node", "stage", "trail"} <= kinds
    node_names = [event["node"] for event in events if event["type"] == "node"]
    assert "parse" in node_names
    assert "hitl" in node_names
    stage_names = [event["stage"] for event in events if event["type"] == "stage"]
    assert "normalize" in stage_names
    trail_events = [event for event in events if event["type"] == "trail"]
    assert trail_events
    assert any(event["stage"] == "hitl" for event in trail_events)
    assert all(event["id"] for event in trail_events)


def test_recheck_loop_is_bounded_before_the_gate():
    from app.graph import route_after_hitl

    assert route_after_hitl({"recheck": True, "recheck_count": 1}) == "reset"
    assert route_after_hitl({"recheck": True, "recheck_count": 2}) == "reset"
    assert route_after_hitl({"recheck": True, "recheck_count": 3}) == "gate"
    assert route_after_hitl({"recheck": False, "recheck_count": 1}) == "gate"
