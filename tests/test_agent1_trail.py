"""Trail (tasks 8.x): every field traceable, model calls carry `model` + `prompt_hash`, no overreach op."""

from __future__ import annotations

from app.nodes.extract import extract_node
from app.nodes.normalize import normalize_node
from app.nodes.parse import parse_node
from app.parsing.extract import extract
from app.parsing.normalize import build_fields
from app.parsing.parse import NO_TEXT_LAYER
from app.state import OVERREACH_OPS
from app.trail import overreach_entries, record
from tests.helpers import apply_update, candidate, make_doc


def _llm_returning(payload):
    return lambda prompt: payload


def test_every_extracted_field_has_trail_entry(fields_yaml):
    """Any produced field -> at least one `transform` with before / after / ref (task 8.1)."""
    docs = [make_doc("保函金额：USD 500K")]
    result = build_fields(
        [candidate("guarantee_amount", "USD 500K", "USD 500K")], docs, fields_yaml=fields_yaml
    )
    transforms = [
        entry
        for entry in result.trail_entries
        if entry["op"] == "transform" and entry["detail"].get("key") == "guarantee_amount"
    ]

    assert transforms
    assert transforms[0]["before"] == "USD 500K"
    assert transforms[0]["after"] == "500000.00"
    assert transforms[0]["ref"]


def test_llm_call_has_model_and_prompt_hash():
    """Model calls record `model` and `prompt_hash` (task 8.2)."""
    docs = [make_doc("AMOUNT: USD 500.00")]
    result = extract(
        docs,
        ["guarantee_amount"],
        llm=_llm_returning(
            [
                {
                    "key": "guarantee_amount",
                    "raw_value": "USD 500.00",
                    "span": "USD 500.00",
                    "confidence": 0.9,
                }
            ]
        ),
    )

    call = [entry for entry in result.trail_entries if entry["op"] == "llm_call"][0]
    assert call["model"] == "gpt-4o"
    assert call["prompt_hash"]
    assert call["detail"]["range"] == [0, 0]
    assert call["detail"]["blocks"] == 1


def test_failed_parse_file_is_recorded_as_pass():
    """A file that failed to parse is not extracted, but must be recorded (task 8.3, never a silent continue)."""
    failed_doc = {
        "file_id": "F-BAD",
        "filename": "scan.pdf",
        "mime": "application/pdf",
        "form": "pdf_text",
        "blocks": [],
        "full_text": "",
        "errors": [NO_TEXT_LAYER],
    }
    result = extract([failed_doc], ["guarantee_amount"], llm=_llm_returning([]))

    assert result.candidates == []
    assert result.trail_entries[0]["op"] == "pass"
    assert "failed to parse" in result.trail_entries[0]["detail"]["reason"]


def test_extract_retries_once_then_marks_batch_failed():
    """A schema violation -> retry once -> a second failure lands in `failed_batches` (task 4.6)."""
    calls: list[str] = []

    def bad_llm(prompt: str):
        calls.append(prompt)
        return "this is not JSON"

    result = extract([make_doc("AMOUNT: USD 500.00")], ["guarantee_amount"], llm=bad_llm)

    assert len(calls) == 2, "exactly one retry is required"
    assert result.model_calls == 2
    assert result.failed_batches == ["F-1#0"]
    assert result.candidates == []


def test_rerun_keeps_append_only_trail():
    """After a rerun `trail` only grows and ids increment per agent (task 8.5)."""
    state = {"trail": []}
    first = record(state, agent="agent1", stage="normalize", op="pass", detail={"round": 1})
    state["trail"] = first["trail"]
    second = record(state, agent="agent1", stage="normalize", op="pass", detail={"round": 2})

    ids = [entry["id"] for entry in state["trail"] + second["trail"]]
    assert ids == ["agent1.normalize#001", "agent1.normalize#002"]


def test_full_run_has_no_overreach_ops(tmp_path, fields_yaml):
    """No `summarize` / `rewrite` / `drop` anywhere in the full run (task 8.4)."""
    mail = tmp_path / "mail.txt"
    mail.write_text("保函金额：USD 500K\n适用规则：URDG 758", encoding="utf-8")
    state: dict = {
        "files": [
            {
                "file_id": "F-1",
                "filename": mail.name,
                "mime": "text/plain",
                "path": str(mail),
                "sha256": "abc",
            }
        ],
        "trail": [],
        "stages": [],
        "findings": [],
    }

    apply_update(state, parse_node(state))
    extract_update = extract_node(
        state,
        llm=_llm_returning(
            [
                {
                    "key": "guarantee_amount",
                    "raw_value": "USD 500K",
                    "span": "USD 500K",
                    "confidence": 0.95,
                }
            ]
        ),
        field_keys=list(fields_yaml),
    )
    assert "fields" not in extract_update, "extract must not write fields"
    apply_update(state, extract_update)

    apply_update(state, normalize_node(state, fields_yaml=fields_yaml))

    assert state["fields"]["guarantee_amount"]["value"] == "500000.00"
    assert overreach_entries(state) == []
    assert not (OVERREACH_OPS & {entry["op"] for entry in state["trail"]})
    assert state["_candidates"] == [], "_candidates is cleared right after use"