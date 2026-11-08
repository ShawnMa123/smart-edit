"""Model provider adapter (tasks 2.1-2.6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import load_fields_config
from app.llm import resolve_llm
from app.parsing.extract import extract
from app.parsing.normalize import build_fields
from app.parsing.parse import parse_file

FIXTURE = Path("fixtures/llm/extract_sample.json")
SAMPLE_DOC = Path("fixtures/llm/sample_document.txt")


def test_unset_returns_none(monkeypatch):
    """2.1 No configuration means no provider — never a silent stub."""
    monkeypatch.delenv("SMART_EDIT_LLM", raising=False)
    assert resolve_llm() is None
    assert resolve_llm("") is None


def test_fixture_replays_candidates_and_carries_label():
    """2.2 The fixture callable replays its file and names itself."""
    llm = resolve_llm(f"fixture:{FIXTURE}")

    candidates = llm("ignored prompt")
    assert len(candidates) == 8
    for item in candidates:
        for key in ("key", "raw_value", "span", "confidence"):
            assert key in item
    assert FIXTURE.as_posix() in llm.provider


def test_openai_is_reserved_not_silently_faked():
    """2.3 An unimplemented provider raises instead of falling back."""
    with pytest.raises(NotImplementedError, match="not implemented"):
        resolve_llm("openai:gpt-4o")


def test_unrecognised_value_raises():
    with pytest.raises(ValueError, match="SMART_EDIT_LLM"):
        resolve_llm("openrouter:whatever")


def test_missing_fixture_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_llm(f"fixture:{tmp_path / 'nope.json'}")


def test_fixture_satisfies_the_candidate_schema():
    """2.6 The committed fixture obeys `schemas/candidates.json` constraints."""
    schema = json.loads(Path("schemas/candidates.json").read_text(encoding="utf-8"))
    required = set(schema["items"]["required"])
    span_cap = schema["items"]["properties"]["span"]["maxLength"]

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, list) and payload
    for item in payload:
        assert required <= set(item), f"missing {required - set(item)}"
        assert isinstance(item["raw_value"], str) and isinstance(item["span"], str)
        assert len(item["span"]) <= span_cap
        assert 0 <= float(item["confidence"]) <= 1
        assert set(item) <= set(schema["items"]["properties"]), "no extra keys in the contract"


def test_fixture_run_produces_locatable_extracted_fields(fields_yaml):
    """2.6 Replaying the fixture over the sample document yields real `extracted` fields."""
    doc = parse_file(
        {
            "file_id": "F-1",
            "filename": SAMPLE_DOC.name,
            "mime": "text/plain",
            "path": str(SAMPLE_DOC),
            "sha256": "abc",
        }
    )
    assert doc["errors"] == []

    llm = resolve_llm(f"fixture:{FIXTURE}")
    result = extract([doc], list(fields_yaml), llm=llm)
    assert result.failed_batches == []
    assert len(result.candidates) == 8

    normalized = build_fields(result.candidates, [doc], fields_yaml=fields_yaml)
    amount = normalized.fields["guarantee_amount"]
    assert amount["value"] == "500000.00"
    assert amount["status"] == "extracted"
    assert normalized.fields["issue_date"]["value"] == "2026-03-12"
    assert normalized.findings == [], "the sample document triggers no truncation finding"


def test_fields_yaml_is_the_real_config():
    assert len(load_fields_config()) >= 12