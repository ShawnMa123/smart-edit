"""Task 9.1 — the real 25-page booklet: the numbers the customer complained about."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.parsing.parse import parse_file
from app.parsing.rich_pdf import PAGE_BREAK, document_to_rich

SAMPLE = Path("fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf")


def _rich():
    return document_to_rich(str(SAMPLE))


def test_the_sections_are_no_longer_all_level_one():
    """9.1 The complaint was "25 pages, 25 H1s"."""
    levels = Counter(
        block["attrs"]["level"] for block in _rich()["content"] if block["type"] == "heading"
    )

    assert levels[1] == 1, "the cover title is the only level-1 heading"
    assert levels[2] >= 20, "the section titles dropped to level 2"
    assert levels[3] <= 2


def test_emphasis_and_page_boundaries_survive():
    """9.1 Bold text comes back, and every page boundary is marked."""
    rich = _rich()
    bold_nodes = sum(
        1
        for block in rich["content"]
        for node in block.get("content") or []
        if "bold" in (node.get("marks") or [])
    )
    breaks = sum(1 for block in rich["content"] if block["type"] == PAGE_BREAK)

    assert bold_nodes > 0, "the PDF carries emphasis; we must not lose all of it"
    assert breaks == 24, "25 pages → 24 boundaries"
    assert "page numbers and footers kept" in rich["provenanceNote"]


def test_nothing_is_dropped_or_reworded():
    """9.1, 7.7 Every parsed block and every character must survive the conversion."""
    parsed = parse_file(
        {"file_id": "F-1", "filename": SAMPLE.name, "mime": "application/pdf", "path": str(SAMPLE), "sha256": "x"}
    )
    rich = _rich()
    blocks = [block for block in rich["content"] if block["type"] != PAGE_BREAK]
    from_rich = "\n".join(
        "".join(node["text"] for node in block.get("content") or []) for block in blocks
    )

    assert parsed["errors"] == []
    assert len(blocks) == len(parsed["blocks"]) == 715
    assert from_rich == parsed["full_text"]
    assert "HSBC" in parsed["full_text"]


@pytest.mark.parametrize("size", [9.0, 14.0, 20.0, 48.0])
def test_each_font_size_in_the_sample_keeps_its_own_band(size):
    """9.1 The four sizes present must map to four distinct roles (three levels + body)."""
    rich = _rich()
    with_size = [
        block
        for block in rich["content"]
        if (block.get("attrs") or {}).get("fontSize") == size and block["type"] != PAGE_BREAK
    ]

    assert with_size, f"no block carries fontSize {size}"
    if size == 9.0:
        assert all(block["type"] == "paragraph" for block in with_size), "body text is not a heading"
    else:
        assert all(block["type"] == "heading" for block in with_size), "larger sizes are headings"