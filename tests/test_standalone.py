"""Standalone triggering (design §13 / tasks 9.4-9.9)."""

from __future__ import annotations

from app.standalone import clear_previous_outputs, plan_standalone


def _state(**overrides) -> dict:
    state = {
        "files": [{"file_id": "F-1", "filename": "a.txt", "mime": "text/plain", "path": "a.txt"}],
        "findings": [],
        "trail": [],
        "stages": [],
    }
    state.update(overrides)
    return state


def test_unknown_target_is_refused_not_widened():
    plan = plan_standalone("agent9", _state())
    assert plan["status"] == 409
    assert plan["error"] == "unknown_stage"
    assert "parse" in plan["registered"]


def test_parse_without_files_is_refused():
    plan = plan_standalone("parse", _state(files=[]))
    assert plan["status"] == 409
    assert plan["error"] == "missing_prerequisite"
    assert plan["missing"] == ["files"]
    assert plan["refused"] is True
    assert plan["agent"] == "parse"
    assert plan["reason"]


def test_extract_and_normalize_backfill_in_order():
    assert plan_standalone("extract", _state())["chain"] == ["parse", "extract"]
    assert plan_standalone("normalize", _state())["chain"] == [
        "parse",
        "extract",
        "normalize",
    ]


def test_agent3_defaults_to_raw_and_only_backfills_parse():
    plan = plan_standalone("agent3", _state())
    assert plan["status"] == 200
    assert plan["input_mode"] == "raw"
    assert plan["chain"] == ["parse", "agent3"]


def test_agent3_enriched_backfills_the_shared_layer():
    plan = plan_standalone("agent3", _state(), input_mode="enriched")
    assert plan["status"] == 200
    assert plan["input_mode"] == "enriched"
    assert plan["chain"] == ["parse", "extract", "normalize", "agent3"]


def test_unknown_input_mode_is_refused():
    plan = plan_standalone("agent3", _state(), input_mode="partial")
    assert plan["status"] == 409
    assert plan["error"] == "REFUSED"


def test_agent4_resolves_to_audit_and_backfills_the_shared_layer():
    plan = plan_standalone("agent4", _state())
    assert plan["status"] == 200
    assert plan["target"] == "audit"
    assert plan["chain"] == ["parse", "extract", "normalize", "audit"]


def test_done_stages_are_not_backfilled_again():
    state = _state(
        stages=[
            {"stage": "parse", "status": "done"},
            {"stage": "extract", "status": "done"},
            {"stage": "normalize", "status": "done"},
        ]
    )
    plan = plan_standalone("agent3", state, input_mode="enriched")
    assert plan["chain"] == ["agent3"]


def test_clear_previous_outputs_only_touches_the_target():
    state = _state(
        findings=[
            {"id": "N-001", "source": "normalization"},
            {"id": "B-001", "source": "business"},
            {"id": "R-001", "source": "regulatory"},
        ],
        legal={"summary": "old"},
        retrieved=[{"chunk_id": "c1"}],
        verification={"verdict": "pass"},
        gate={"verdict": "pass"},
        export={"version_no": 1},
        fields={"a": {"value": "1"}},
    )

    legal_clear = clear_previous_outputs(state, "agent3")
    assert [f["id"] for f in legal_clear["findings"]] == ["N-001", "B-001"]
    assert legal_clear["legal"] is None
    assert legal_clear["retrieved"] == []
    assert "stages" not in legal_clear and "trail" not in legal_clear

    audit_clear = clear_previous_outputs(state, "audit")
    assert audit_clear["verification"] is None
    assert audit_clear["gate"] is None
    assert audit_clear["export"] is None

    normalize_clear = clear_previous_outputs(state, "normalize")
    assert normalize_clear["fields"] == {}
    assert [f["id"] for f in normalize_clear["findings"]] == ["B-001", "R-001"]
