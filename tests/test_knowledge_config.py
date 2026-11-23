"""Configurable knowledge presets (`knowledge-simple-ask`): loader, guardrails, budget."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.assistant.egress import (
    DEFAULT_REDACTION_BUDGET_MS,
    MAX_PATTERN_CHARS,
    MAX_REDACTION_RULES,
    EgressInput,
    EgressPolicy,
    compile_redactions,
)


def search(question: str, **kwargs) -> EgressInput:
    return EgressInput(purpose="search", question=question, candidate_query=question, **kwargs)


def write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def config(**egress) -> dict:
    base = {
        "version": "test-1",
        "egress": {
            "allowed_domains": ["example.org"],
            "max_query_chars": 400,
            "selection_overlap_chars": 40,
            "redactions": [
                {"reason": "amount_present", "pattern": r"(?i)USD\s?[\d,]+"},
                {"reason": "email_present", "pattern": r"[\w.+-]+@[\w-]+\.[\w.]+"},
            ],
        },
        "scope_presets": {"jurisdictions": ["CN", "EU"]},
        "suggested_questions": ["What rules apply to customs value?"],
    }
    base["egress"].update(egress)
    return base


# --- loader ---------------------------------------------------------------------------------


def test_a_json_config_supplies_rules_and_presets(tmp_path):
    policy = EgressPolicy.from_file(write(tmp_path, "knowledge.json", config()))

    assert policy.loaded is True
    assert policy.version == "test-1"
    assert policy.allowed_domains == ["example.org"]
    assert policy.jurisdictions == ["CN", "EU"]
    assert policy.suggested_questions == ["What rules apply to customs value?"]


def test_the_legacy_yaml_file_still_loads(tmp_path):
    path = tmp_path / "egress.yaml"
    path.write_text(
        "version: legacy-1\nallowed_domains: [iccwbo.org]\nmax_query_chars: 200\n",
        encoding="utf-8",
    )

    policy = EgressPolicy.from_file(path)

    assert policy.loaded is True
    assert policy.version == "legacy-1"
    assert policy.max_query_chars == 200
    # No `redactions` configured → the built-in presets are used, never "no redaction".
    assert policy.redactions


def test_a_missing_file_denies_everything(tmp_path):
    policy = EgressPolicy.from_file(tmp_path / "nope.json")

    assert policy.loaded is False
    assert policy.check(search("hello")).reason_code == "policy_unavailable"


def test_a_broken_json_file_denies_everything(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    policy = EgressPolicy.from_file(path)

    assert policy.loaded is False
    assert policy.check(search("hello")).reason_code == "policy_unavailable"


def test_an_explicit_path_wins_over_the_shipped_sample(tmp_path):
    explicit = write(tmp_path, "mine.json", config(allowed_domains=["mine.example"]))

    policy = EgressPolicy.load(explicit)

    assert policy.allowed_domains == ["mine.example"]


def test_without_an_explicit_path_the_shipped_sample_is_used():
    policy = EgressPolicy.load(None)

    assert policy.loaded is True
    assert "wto.org" in policy.allowed_domains
    assert policy.jurisdictions  # presets ship with the sample


def test_an_explicit_missing_path_does_not_fall_back_to_the_sample(tmp_path):
    # Absence is the only case that may fall through; the sample is reached because the path is gone.
    policy = EgressPolicy.load(tmp_path / "absent.json")

    assert policy.loaded is True  # fell through to the sample on purpose
    assert policy.allowed_domains != ["absent.example"]


# --- guardrails -----------------------------------------------------------------------------


def test_a_pattern_that_does_not_compile_fails_loudly(tmp_path):
    payload = config(redactions=[{"reason": "bad", "pattern": "([unclosed"}])

    with pytest.raises(ValueError, match="not a valid regex"):
        EgressPolicy.from_file(write(tmp_path, "bad.json", payload))


def test_too_many_rules_are_refused():
    rules = [{"reason": f"r{index}", "pattern": "x"} for index in range(MAX_REDACTION_RULES + 1)]

    with pytest.raises(ValueError, match="at most"):
        compile_redactions(rules)


def test_an_over_long_pattern_is_refused():
    rules = [{"reason": "long", "pattern": "x" * (MAX_PATTERN_CHARS + 1)}]

    with pytest.raises(ValueError, match="the limit is"):
        compile_redactions(rules)


def test_an_exemption_field_cannot_whitelist_an_amount(tmp_path):
    payload = config()
    payload["egress"]["protected_patterns"] = [r"(?i)USD\s?[\d,]+"]
    payload["egress"]["exempt"] = [r"(?i)USD\s?[\d,]+"]

    policy = EgressPolicy.from_file(write(tmp_path, "exempt.json", payload))
    decision = policy.check(search("Payment of USD 1,000,000 under the guarantee"))

    assert "USD 1,000,000" not in (decision.outbound_query or "")
    assert decision.reason_code == "amount_present"


def test_a_rule_id_always_survives_redaction(tmp_path):
    policy = EgressPolicy.from_file(write(tmp_path, "rules.json", config()))

    decision = policy.check(search("What does URDG 758 require for USD 1,000,000 claims?"))

    assert "URDG 758" in (decision.outbound_query or "")


# --- time budget ----------------------------------------------------------------------------


def test_the_budget_is_armed_by_default():
    policy = EgressPolicy(loaded=True, allowed_domains=["example.org"])

    assert policy.redaction_budget_ms == DEFAULT_REDACTION_BUDGET_MS


def test_exceeding_the_budget_denies_instead_of_letting_a_pattern_run():
    policy = EgressPolicy(loaded=True, allowed_domains=["example.org"], redaction_budget_ms=0)

    decision = policy.check(search("What does URDG 758 require for claims?"))

    assert decision.action == "deny"
    assert decision.reason_code == "pattern_timeout"