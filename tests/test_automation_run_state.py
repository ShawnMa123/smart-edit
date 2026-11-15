"""Run contracts and pure state rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.automation.run_schemas import AutomationRun, RunCreate
from app.automation.run_state import can_transition, is_terminal, stage_after


def test_run_state_allows_only_declared_transitions():
    assert can_transition("queued", "running")
    assert can_transition("queued", "cancelled")
    assert can_transition("running", "succeeded")
    assert can_transition("running", "timed_out")
    assert not can_transition("succeeded", "running")
    assert not can_transition("cancelled", "succeeded")
    assert is_terminal("succeeded")
    assert not is_terminal("running")
    assert stage_after("context") == "planning"
    assert stage_after("done") == "done"


def test_run_create_is_strict_and_accepts_all_task_types_then_service_rejects():
    payload = RunCreate(
        task_type="rewrite",
        document_id="doc-1",
        draft_id="draft-1",
        input={"intent": "replace_text"},
    )
    assert payload.task_type == "rewrite"
    with pytest.raises(ValidationError):
        RunCreate(
            task_type="rewrite",
            document_id="doc-1",
            draft_id="draft-1",
            input={},
            unknown=True,
        )
    assert RunCreate(
        task_type="compare", document_id="doc-1", draft_id="draft-1", input={}
    ).task_type == "compare"


def test_automation_run_rejects_an_unknown_stage():
    with pytest.raises(ValidationError):
        AutomationRun(
            run_id="run-1",
            task_type="rewrite",
            document_id="doc-1",
            draft_id="draft-1",
            status="queued",
            stage="not-a-stage",
            revision=1,
            created_at="2026-01-01T00:00:00+00:00",
            deadline_at="2026-01-01T00:02:00+00:00",
        )