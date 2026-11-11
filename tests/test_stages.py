"""Stage registry and prerequisite semantics (design §7 / tasks 4.1-4.5)."""

from __future__ import annotations

import pytest

from app.stages import (
    AGENT_SPECS,
    AGENT_TARGETS,
    ENRICHED_CHAIN,
    STAGE_TARGETS,
    latest_stage,
    refusal,
    require,
    resolve_input_mode,
    stage_is_done,
    stage_report,
    stages_done,
)


def test_every_agent_declares_its_dependencies():
    for agent, spec in AGENT_SPECS.items():
        assert spec.agent_id == agent
        assert isinstance(spec.requires_stages, tuple)
        assert isinstance(spec.requires_keys, tuple)
        assert isinstance(spec.produces, tuple)
    assert AGENT_SPECS["agent2"].requires_stages == ("normalize",)
    assert AGENT_SPECS["agent4"].requires_stages == ("merge",)
    assert AGENT_SPECS["agent4"].standalone is True  # reaches the audit through `audit`


def test_shared_layer_targets_are_registered():
    assert {"parse", "extract", "normalize"} <= set(STAGE_TARGETS)
    assert STAGE_TARGETS["extract"].requires_stages == ("parse",)
    assert STAGE_TARGETS["normalize"].requires_stages == ("parse", "extract")
    assert ENRICHED_CHAIN == ("parse", "extract", "normalize")


def test_agent4_resolves_to_the_audit_target():
    assert AGENT_TARGETS["agent4"] == "audit"
    assert STAGE_TARGETS["audit"].requires_stages == ENRICHED_CHAIN


def test_latest_stage_takes_the_last_report_not_the_first():
    stages = [
        stage_report("agent2", status="done", agent="agent2"),
        stage_report("agent2", status="failed", reason="second run failed", agent="agent2"),
        stage_report("agent3", status="done", agent="agent3"),
    ]
    latest = latest_stage(stages, "agent2")
    assert latest is not None
    assert latest["status"] == "failed"
    assert latest_stage(stages, "parse") is None


def test_require_refuses_instead_of_returning_an_empty_result():
    refusal = require({"fields": {}}, "fields", "business_type")
    assert refusal == {"refused": True, "missing": ["fields", "business_type"]}
    assert require({"fields": {"a": 1}, "business_type": "guarantee"}, "fields") is None


def test_stage_report_requires_reason_for_every_non_done_status():
    for status in ("skipped", "partial", "failed"):
        with pytest.raises(ValueError):
            stage_report("parse", status=status)
        report = stage_report("parse", status=status, reason="why")
        assert report["reason"] == "why"
    with pytest.raises(ValueError):
        stage_report("parse", status="unknown")


def test_stage_is_done_reads_the_last_report():
    stages = [stage_report("parse", status="done")]
    assert stage_is_done(stages, "parse")
    stages.append(stage_report("parse", status="failed", reason="second run failed"))
    assert not stage_is_done(stages, "parse")
    assert not stages_done(stages, ("parse",))


def test_resolve_input_mode_requires_a_done_normalize_report():
    fields = {"a": {"value": "1"}}
    stages = [stage_report("normalize", status="done")]
    assert resolve_input_mode({"fields": fields, "business_type": "guarantee", "stages": stages}) == "enriched"
    assert resolve_input_mode({"fields": fields, "business_type": "guarantee", "stages": []}) == "raw"
    assert (
        resolve_input_mode(
            {
                "fields": fields,
                "business_type": "guarantee",
                "stages": [stage_report("normalize", status="failed", reason="x")],
            }
        )
        == "raw"
    )


def test_refusal_has_the_uniform_shape():
    assert refusal(["fields"], agent="agent2", reason="missing") == {
        "refused": True,
        "missing": ["fields"],
        "agent": "agent2",
        "reason": "missing",
    }
