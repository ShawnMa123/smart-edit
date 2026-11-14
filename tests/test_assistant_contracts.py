"""Task 0.1-0.3 — DTOs, ports/modes and the pure run/answer state rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.assistant.adapters import (
    FakeAuthorization,
    FakeIdentity,
    assert_safe_mode,
    resolve_mode,
)
from app.assistant.bootstrap import build_services
from app.assistant.domain.state_machine import (
    can_transition,
    is_active,
    is_terminal,
    validate_answer,
)
from app.assistant.ports import Principal
from app.assistant.schemas import (
    Answer,
    Claim,
    Citation,
    Run,
    RunCreate,
    Selection,
    SessionCreate,
    SnapshotCreate,
)


def _claim(**overrides) -> dict:
    payload = {"id": "c1", "text": "提交成功后释放编辑锁", "kind": "fact", "citation_ids": ["cite_1"]}
    payload.update(overrides)
    return payload


def _answer(**overrides) -> Answer:
    payload = {
        "outcome": "answered",
        "language": "zh-CN",
        "support_level": "strong",
        "claims": [_claim()],
        "citations": [
            {
                "id": "cite_1",
                "source_type": "product_manual",
                "title": "合成产品手册",
                "source_version": "demo-1",
                "locator": {"section": "提交与锁"},
            }
        ],
    }
    payload.update(overrides)
    return Answer(**payload)


# --- 0.1 DTOs ---------------------------------------------------------------------------------


def test_answer_success_shape_parses():
    answer = _answer()
    assert answer.schema_version == "1.0"
    assert answer.claims[0].citation_ids == ["cite_1"]


def test_unknown_field_is_rejected_instead_of_ignored():
    with pytest.raises(ValidationError):
        Answer(**{**_answer().model_dump(), "model": "gpt-x"})
    with pytest.raises(ValidationError):
        Claim(**_claim(owner_user_id="user_b"))


def test_illegal_enum_is_rejected():
    with pytest.raises(ValidationError):
        Answer(**{**_answer().model_dump(), "outcome": "answered-ish"})
    with pytest.raises(ValidationError):
        Citation(id="cite_1", source_type="web", title="t", source_version="v", locator={})


def test_selection_and_session_pair_rules():
    with pytest.raises(ValidationError):
        Selection(node_id="n1", start_offset=4, end_offset=4, selected_text="x")
    with pytest.raises(ValidationError):
        SessionCreate(workspace_id="ws", locale="en", document_id="doc-1")
    with pytest.raises(ValidationError):
        SessionCreate(
            workspace_id="ws", locale="en", document_id="doc-1", snapshot_id="s1",
            attachment_ids=["a1", "a1"],
        )
    assert SessionCreate(workspace_id="ws", locale="en").document_id is None


def test_run_input_bounds_and_snapshot_digest():
    with pytest.raises(ValidationError):
        RunCreate(question="")
    with pytest.raises(ValidationError):
        SnapshotCreate(document_id="d", text="x", content_sha256="short")
    run = Run(
        id="run_1", session_id="sess_1", user_message_id="msg_1", status="queued",
        stage="queued", created_at="2026-01-01T00:00:00+00:00",
        deadline_at="2026-01-01T00:02:00+00:00",
    )
    assert run.result is None and run.attempt == 0


def test_dto_schemas_are_exported_in_openapi(tmp_path):
    """The DTOs are the API contract, so FastAPI must publish them as components."""
    from app.api.main import create_app
    from tests.assistant_helpers import make_services

    app = create_app(
        llm=None,
        runs_dir=tmp_path / "runs",
        assistant_services=make_services(tmp_path),
    )
    schemas = app.openapi()["components"]["schemas"]
    for name in ("Answer", "Session", "Run", "RunAccepted", "EvidenceDetail", "Feedback"):
        assert name in schemas, f"{name} is missing from the OpenAPI contract"
    assert "/assistant/sessions/{session_id}/runs" in app.openapi()["paths"]


# --- 0.2 ports / modes ------------------------------------------------------------------------


class _Request:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_mode_resolution_and_production_fail_closed():
    assert resolve_mode("local") == "local"
    assert resolve_mode("test") == "test"
    with pytest.raises(ValueError):
        resolve_mode("staging")
    with pytest.raises(RuntimeError):
        assert_safe_mode("production")
    with pytest.raises(RuntimeError):
        build_services(db_path=":memory:", mode="production")


def test_local_services_expose_every_port(tmp_path):
    services = build_services(db_path=tmp_path / "a.db", mode="test")
    assert services.knowledge_admin is not None
    assert services.ids.new("run").startswith("run_")
    assert services.identity.resolve(_Request({"x-demo-user": "user_b"})).user_id == "user_b"
    with pytest.raises(PermissionError):
        FakeAuthorization().resolve(
            Principal(user_id="user_a", workspace_id="ws-other"), "ws_demo_01"
        )


def test_fake_identity_defaults_to_one_principal():
    principal = FakeIdentity().resolve(_Request({}))
    assert principal.user_id == "user_demo_01"
    assert principal.workspace_id == "ws_demo_01"


# --- 0.3 run / answer invariants ---------------------------------------------------------------


def test_only_documented_run_transitions_are_legal():
    assert can_transition("queued", "running")
    assert can_transition("running", "succeeded")
    assert can_transition("running", "timed_out")
    assert not can_transition("succeeded", "running")
    assert not can_transition("cancelled", "succeeded")
    assert is_terminal("failed") and not is_active("failed")
    assert is_active("queued") and is_active("running")


def test_answered_answer_must_carry_supported_claims():
    assert validate_answer(_answer()) == []
    assert "answered_without_claims" in validate_answer(_answer(claims=[], citations=[]))
    assert "answered_support_level" in validate_answer(_answer(support_level="insufficient"))
    assert "claim_unknown_citation" in "".join(
        validate_answer(_answer(claims=[_claim(citation_ids=["cite_missing"])]))
    )
    assert "claim_without_citation" in "".join(
        validate_answer(_answer(claims=[_claim(citation_ids=[])]))
    )


def test_clarification_handoff_and_insufficient_invariants():
    clarification = _answer(
        outcome="needs_clarification", support_level="not_applicable", claims=[], citations=[],
        clarification_questions=["请确认规则版本"],
    )
    assert validate_answer(clarification) == []
    assert "clarification_support_level" in validate_answer(
        clarification.model_copy(update={"support_level": "strong"})
    )
    assert "handoff_without_target" in validate_answer(
        clarification.model_copy(
            update={"outcome": "needs_handoff", "clarification_questions": [], "handoff_target": None}
        )
    )
    assert "insufficient_support_level" in validate_answer(
        _answer(outcome="insufficient_evidence", support_level="qualified", claims=[], citations=[])
    )