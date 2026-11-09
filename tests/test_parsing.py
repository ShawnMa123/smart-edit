"""Shared parsing layer (design §6 / tasks 3.10-3.12)."""

from __future__ import annotations

from pathlib import Path

from app.nodes.parse import parse_node
from app.parsing.normalize import (
    MAX_SPAN_LEN,
    locate_span,
    normalize_ws,
    span_locatable,
)
from app.parsing.parse import parse


def test_max_span_len_is_defined_once():
    assert MAX_SPAN_LEN == 200


def test_normalize_ws_covers_full_width_zero_width_hyphens_and_quotes():
    assert normalize_ws("ＡＢＣ　１２３") == "ABC 123"
    assert normalize_ws("A\u200bB\ufeffC") == "ABC"
    assert normalize_ws("URDG\u2011758") == "URDG-758"
    assert normalize_ws("“quoted” «guillemets» 「cjk」") == '"quoted" "guillemets" "cjk"'
    assert normalize_ws("a\t\n  b") == "a b"


def test_normalize_ws_preserves_case_and_spelling():
    assert normalize_ws("ABC Trading Pte Ltd") == "ABC Trading Pte Ltd"
    assert normalize_ws("ABC") != normalize_ws("abc")


def test_locate_span_uses_the_shared_benchmark():
    assert locate_span("金额：ＵＳＤ 500", "USD 500")
    assert not locate_span("金额：USD 500", "EUR 500")


def test_span_locatable_is_single_file_only():
    docs = [
        {"file_id": "F-1", "full_text": "alpha"},
        {"file_id": "F-2", "full_text": "beta"},
    ]
    assert span_locatable({"file_id": "F-1", "span": "alpha"}, docs)
    assert not span_locatable({"file_id": "F-1", "span": "beta"}, docs)


def _text_file(tmp_path: Path) -> dict:
    path = tmp_path / "doc.txt"
    path.write_text("保函编号：BG-2026-0001\n金额：USD 500\n", encoding="utf-8")
    return {
        "file_id": "F-1",
        "filename": path.name,
        "mime": "text/plain",
        "path": str(path),
        "sha256": "sha-1",
    }


def test_two_parse_paths_produce_identical_blocks(tmp_path):
    """Direct `parse()` and `parse_node()` must not drift (daily-green rule)."""
    source = _text_file(tmp_path)
    direct, direct_trail, calls = parse([source])
    node_update = parse_node({"files": [source]})
    via_node = node_update["docs"]

    assert calls == 0
    assert direct_trail
    assert [block for block in direct[0]["blocks"]] == [
        block for block in via_node[0]["blocks"]
    ]
    assert direct[0]["full_text"] == via_node[0]["full_text"]
    assert node_update["stages"][-1]["status"] == "done"


def test_parse_failure_is_data_not_an_exception(tmp_path):
    missing = {
        "file_id": "F-missing",
        "filename": "missing.txt",
        "mime": "text/plain",
        "path": str(tmp_path / "missing.txt"),
        "sha256": "sha-missing",
    }
    docs, trail, calls = parse([missing])
    assert calls == 0
    assert docs[0]["errors"]
    assert docs[0]["full_text"] == ""
    assert trail
