"""The frozen contract (design §4 / tasks 2.10).

These assertions are deliberately about *shape and semantics*, not about any agent's output:
they must stay green when Agent 1/2/3 change their business rules, and go red when someone
renames a key, changes an enum or adds an optional field as required.
"""

from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Annotated, NotRequired, get_args, get_origin, get_type_hints

import pytest

from app import state
from app.findings import materialize_findings
from app.stages import stage_report

SCHEMAS = Path("schemas")


def _hints(name: str) -> dict:
    return get_type_hints(getattr(state, name), include_extras=True)


def test_enum_constants_are_the_contract():
    assert state.AGENT_IDS == ("agent1", "agent2", "agent3", "agent4")
    assert state.STAGE_STATUS == ("done", "skipped", "partial", "failed")
    assert state.FINDING_SOURCES == ("normalization", "business", "regulatory")
    assert state.SEVERITIES == ("critical", "warn", "info")
    assert state.TRAIL_OPS == (
        "read",
        "llm_call",
        "transform",
        "emit",
        "pass",
        "summarize",
        "rewrite",
        "drop",
    )
    assert state.OVERREACH_OPS == frozenset({"summarize", "rewrite", "drop"})
    assert state.FINDING_PREFIX == {
        "normalization": "N",
        "business": "B",
        "regulatory": "R",
    }
    assert state.SHARED_STAGE_OWNER == "agent1"


def test_required_keys_of_frozen_structures():
    required = {
        "ParsedBlock": {"file_id", "page", "bbox", "text", "kind"},
        "Source": {"file_id", "page", "bbox", "span", "form_label"},
        "FieldValue": {
            "key",
            "value",
            "status",
            "confirmed",
            "edited_by_user",
            "source",
            "normalized_from",
            "label",
            "doc_type",
            "notes",
        },
        "StageReport": {"stage", "agent", "status", "reason", "produced", "model_calls"},
        "TrailEntry": {
            "id",
            "agent",
            "stage",
            "op",
            "before",
            "after",
            "ref",
            "model",
            "prompt_hash",
            "detail",
        },
        "SourceFile": {"file_id", "filename", "mime", "path", "sha256"},
    }
    for name, keys in required.items():
        hints = _hints(name)
        assert keys <= set(hints), f"{name} lost a required key"
        for key in keys:
            assert get_origin(hints[key]) is not NotRequired, f"{name}.{key} became optional"


def test_new_fields_must_be_optional():
    """Contract §5.1: later additions are `NotRequired`, never a required key."""
    for name, optional in {
        "ParsedDoc": {"sha256", "rich"},
        "Finding": {"confidence", "needs_review"},
        "VerificationReport": {"audit"},
        "Chunk": {"articles", "jurisdictions", "applies_to"},
    }.items():
        hints = _hints(name)
        for key in optional:
            assert get_origin(hints[key]) is NotRequired, f"{name}.{key} must stay optional"


def test_edit_state_is_total_false_and_only_three_reducers():
    assert state.EditState.__total__ is False
    hints = get_type_hints(state.EditState, include_extras=True)
    reducer_keys = {
        key
        for key, value in hints.items()
        if get_origin(value) is Annotated and operator.add in get_args(value)[1:]
    }
    assert reducer_keys == {"findings", "trail", "stages"}


def test_finding_prefix_must_match_source():
    state_dict = {"findings": [], "trail": []}
    materialized = materialize_findings(
        state_dict,
        [
            {
                "source": "business",
                "kind": "missing",
                "rule_id": "R-1",
                "severity": "warn",
                "blocking": False,
                "resolved": False,
                "resolution": None,
                "field_keys": [],
                "message": "m",
                "evidence": None,
                "citation": None,
                "suggestion": None,
            }
        ],
    )
    assert materialized["findings"][0]["id"] == "B-001"
    assert materialized["findings"][0]["field_keys"] == []


def test_stage_report_done_zero_is_not_the_same_as_failed_zero():
    done = stage_report("agent2", status="done", produced=0)
    failed = stage_report("agent2", status="failed", produced=0, reason="not checked")
    assert done["status"] == "done" and done["produced"] == 0
    assert failed["status"] == "failed" and failed["produced"] == 0
    assert done["reason"] is None
    assert failed["reason"] == "not checked"


def test_stage_report_rejects_unknown_status_and_missing_reason():
    with pytest.raises(ValueError):
        stage_report("x", status="ok")
    for status in ("skipped", "partial", "failed"):
        with pytest.raises(ValueError):
            stage_report("x", status=status)


def test_schema_files_are_valid_json_and_describe_agent_outputs():
    files = {
        "candidates.json",
        "fields.json",
        "legal_opinion.json",
        "verification.json",
    }
    for filename in files:
        path = SCHEMAS / filename
        assert path.is_file(), f"missing schema {filename}"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["type"] in ("array", "object")
        assert payload.get("title")
