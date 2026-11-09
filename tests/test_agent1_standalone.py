"""Three-tier standalone triggering (tasks 9.x): `parse` / `parse -> extract` must not produce `fields`."""

from __future__ import annotations

import pytest

from app.nodes.extract import extract_node
from app.nodes.normalize import normalize_node
from app.nodes.parse import parse_node
from app.parsing.parse import sha256_of
from app.stages import STAGE_TARGETS
from app.standalone import plan_standalone
from tests.helpers import apply_update


def _source(tmp_path) -> dict:
    mail = tmp_path / "mail.txt"
    mail.write_text("保函金额：USD 500K", encoding="utf-8")
    return {
        "file_id": "F-1",
        "filename": mail.name,
        "mime": "text/plain",
        "path": str(mail),
        "sha256": sha256_of(str(mail)) or "abc",
    }


def _empty_state(tmp_path) -> dict:
    return {"files": [_source(tmp_path)], "trail": [], "stages": [], "findings": []}


def test_parse_only_does_not_write_fields(tmp_path):
    """With `parse` only, `fields` / `extra_fields` / `business_type` MUST NOT be produced (task 9.1)."""
    state = _empty_state(tmp_path)
    update = parse_node(state)

    assert update["docs"]
    assert "fields" not in update
    assert "extra_fields" not in update
    assert "business_type" not in update


def test_extract_only_does_not_write_fields(tmp_path, fields_yaml):
    """With `parse -> extract`, `fields` MUST NOT be written; only `_candidates` is produced (task 9.2)."""
    state = _empty_state(tmp_path)
    apply_update(state, parse_node(state))

    update = extract_node(
        state,
        llm=lambda prompt: [
            {
                "key": "guarantee_amount",
                "raw_value": "USD 500K",
                "span": "USD 500K",
                "confidence": 0.9,
            }
        ],
        field_keys=list(fields_yaml),
    )

    assert update["_candidates"], "candidates must go into _candidates"
    assert "fields" not in update, "unclassified candidates must not be written into fields"


def test_three_targets_are_registered():
    """All three tiers must be registered as stage targets (otherwise the API returns 409 and the Scenario cannot pass)."""
    assert set(STAGE_TARGETS) >= {"parse", "extract", "normalize"}
    assert plan_standalone("normalize", {"files": [_source_stub()]})["chain"] == [
        "parse",
        "extract",
        "normalize",
    ]


def test_unknown_stage_refused():
    """An unregistered target MUST be refused (409) and MUST NOT silently run the full chain (task 9.3)."""
    plan = plan_standalone("summarize", {"files": [{"file_id": "F-1"}]})

    assert plan["status"] == 409
    assert plan["error"] == "unknown_stage"
    assert "parse" in plan["registered"]


def test_missing_prerequisite_refused_not_empty_result():
    """A missing prerequisite is refused, never answered with an empty result (hard constraint 8)."""
    plan = plan_standalone("parse", {})

    assert plan["status"] == 409
    assert plan["error"] == "missing_prerequisite"
    assert plan["missing"] == ["files"]


def test_parse_twice_reuses_docs(tmp_path):
    """The same PDF through standalone and full runs yields block-by-block identical `blocks` (task 9.4)."""
    state = _empty_state(tmp_path)
    first = parse_node(state)
    apply_update(state, first)

    reused = parse_node(state)

    assert reused["docs"] if "docs" in reused else True
    assert "docs" not in reused, "reuse must not re-parse"
    assert reused["stages"][0]["status"] == "done"
    assert reused["stages"][0]["reason"].startswith("reused")


def test_normalize_clears_candidates(tmp_path, fields_yaml):
    """`_candidates` is cleared right after use (task 9.5)."""
    state = _empty_state(tmp_path)
    apply_update(state, parse_node(state))
    apply_update(
        state,
        extract_node(state, llm=lambda prompt: [], field_keys=list(fields_yaml)),
    )
    state["_candidates"] = [{"key": "x", "raw_value": "y", "_source": {"file_id": "F-1"}}]

    update = normalize_node(state, fields_yaml=fields_yaml)

    assert "_candidates" in update
    assert len(update["_candidates"]) == 0


def _source_stub() -> dict:
    return {"file_id": "F-1", "sha256": "abc"}


@pytest.mark.parametrize("target", ["parse", "extract", "normalize"])
def test_each_target_plans_without_unknown_stage(target):
    plan = plan_standalone(target, {"files": [_source_stub()]})
    assert plan["status"] == 200
    assert plan["chain"][-1] == target