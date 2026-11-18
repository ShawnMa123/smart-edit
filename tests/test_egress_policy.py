"""Outbound egress policy (knowledge-egress-policy / design D3–D4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.assistant.audit_events import query_digest
from app.assistant.egress import EgressInput, EgressPolicy, demo_policy


def search(question: str, **kwargs) -> EgressInput:
    return EgressInput(
        purpose="search", question=question, candidate_query=question, **kwargs
    )


def test_generic_question_is_allowed_and_keeps_the_rule_id():
    decision = demo_policy().check(search("What does URDG 758 require for claims?"))

    assert decision.action == "allow"
    assert decision.outbound_query == "What does URDG 758 require for claims?"
    assert decision.policy_version == "test-1"


def test_missing_policy_denies_every_search():
    decision = EgressPolicy.from_file(Path("/definitely/not/here.yaml")).check(search("hello"))

    assert decision.action == "deny"
    assert decision.reason_code == "policy_unavailable"


def test_broken_policy_file_denies(tmp_path):
    broken = tmp_path / "egress.yaml"
    broken.write_text("allowed_domains: [oops", encoding="utf-8")

    decision = EgressPolicy.from_file(broken).check(search("hello"))

    assert decision.action == "deny"
    assert decision.reason_code == "policy_unavailable"


def test_selection_text_in_the_question_is_refused():
    selection = (
        "The aggregate liability under this guarantee shall not exceed USD 500,000.00 and is "
        "payable on first written demand."
    )
    decision = demo_policy().check(
        search(f"Explain this: {selection}", selection_text=selection)
    )

    assert decision.action == "deny"
    assert decision.reason_code == "contains_selection"


def test_amounts_and_references_are_redacted_not_sent():
    decision = demo_policy().check(
        search("Claim under BG-2026-0001 for USD 500,000.00 per URDG 758")
    )

    assert decision.action == "redact"
    assert "500,000" not in (decision.outbound_query or "")
    assert "BG-2026-0001" not in (decision.outbound_query or "")
    assert "[redacted]" in (decision.outbound_query or "")
    # The public standard id must survive: it is the search key.
    assert "URDG 758" in (decision.outbound_query or "")
    assert "amount_present" in decision.redactions


def test_long_queries_are_refused():
    decision = demo_policy(max_query_chars=60).check(search("x" * 61))

    assert decision.action == "deny"
    assert decision.reason_code == "query_too_long"


def test_variable_placeholders_alone_are_refused():
    decision = demo_policy().check(search("{{guarantee_amount}}"))

    assert decision.action == "deny"
    assert decision.reason_code == "query_empty_after_redaction"


def test_unapproved_provider_host_is_refused():
    decision = demo_policy().check(search("latest ICC opinion", provider_host="evil.example"))

    assert decision.action == "deny"
    assert decision.reason_code == "domain_not_allowed"


def test_compose_requires_an_approved_processor():
    unapproved = EgressInput(
        purpose="compose", question="q", candidate_query="q", provider="doubao:x"
    )
    decision = demo_policy().check(unapproved)
    assert decision.action == "deny"
    assert decision.reason_code == "processor_not_approved"

    approved = EgressInput(
        purpose="compose",
        question="q",
        candidate_query="q",
        provider="doubao:x",
        provider_approved=True,
    )
    assert demo_policy().check(approved).action == "allow"


def test_policy_failures_fail_closed(monkeypatch):
    policy = demo_policy()

    def boom(_payload):
        raise TimeoutError("policy backend timed out")

    monkeypatch.setattr(policy, "_decide", boom)
    decision = policy.check(search("hello"))

    assert decision.action == "deny"
    assert decision.reason_code == "policy_unavailable"


def test_entities_are_removed_and_empty_results_denied():
    decision = demo_policy().check(
        search("What is Alpha Tech Ltd status", entities=("Alpha Tech Ltd",))
    )
    assert decision.action == "redact"
    assert "Alpha Tech" not in (decision.outbound_query or "")

    tiny = demo_policy().check(search("Alpha Tech Ltd", entities=("Alpha Tech Ltd",)))
    assert tiny.action == "deny"


def test_query_digest_is_irreversible_and_stable():
    assert query_digest("same") == query_digest("same")
    assert query_digest("same") != query_digest("other")
    assert query_digest("") is None


def test_tool_search_requires_the_channel_and_an_approved_processor():
    def tool_search(enabled: bool, approved: bool) -> EgressInput:
        return EgressInput(
            purpose="tool_search",
            question="what is new today",
            candidate_query="what is new today",
            provider="doubao:x",
            provider_approved=approved,
            tool_search_enabled=enabled,
        )

    closed = demo_policy().check(tool_search(False, True))
    assert closed.action == "deny"
    assert closed.reason_code == "tool_search_disabled"

    unapproved = demo_policy().check(tool_search(True, False))
    assert unapproved.action == "deny"
    assert unapproved.reason_code == "processor_not_approved"

    allowed = demo_policy().check(tool_search(True, True))
    assert allowed.action == "allow"


def test_tool_search_keeps_the_selection_guard():
    selection = (
        "The aggregate liability under this guarantee shall not exceed USD 500,000.00 and is "
        "payable on first written demand."
    )
    decision = demo_policy().check(
        EgressInput(
            purpose="tool_search",
            question=f"explain {selection}",
            candidate_query=f"explain {selection}",
            selection_text=selection,
            provider_approved=True,
            tool_search_enabled=True,
        )
    )

    assert decision.action == "deny"
    assert decision.reason_code == "contains_selection"