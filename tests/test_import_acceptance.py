"""Tasks 9.1, 11.2 and 13.x - the real 25-page booklet: the numbers the customer complained about."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app.parsing.parse import parse_file
from app.parsing.pdf_layout import horizontal_rules, row_layout, visual_rows
from app.parsing.rich_pdf import PAGE_BREAK, document_to_rich

SAMPLE = Path("fixtures/imports/guarantee-and-standby-letters-of-credit-wording.pdf")


def _rich():
    return document_to_rich(str(SAMPLE))


def _page_blocks(rich, page: int) -> list[dict]:
    return [
        block
        for block in rich["content"]
        if block["type"] != PAGE_BREAK and (block.get("attrs") or {}).get("page") == page
    ]


def _block_text(block: dict) -> str:
    return "".join(node.get("text", "") for node in block.get("content") or [])


def _gaps(block: dict) -> list[dict]:
    return [node for node in block.get("content") or [] if node.get("type") == "pdfGap"]


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
    """9.1, 11.2 Every parsed block and every visible character must survive the conversion."""
    parsed = parse_file(
        {"file_id": "F-1", "filename": SAMPLE.name, "mime": "application/pdf", "path": str(SAMPLE), "sha256": "x"}
    )
    rich = _rich()
    blocks = [block for block in rich["content"] if block["type"] != PAGE_BREAK]
    from_rich = "\n".join(
        "".join(node.get("text", "") for node in block.get("content") or []) for block in blocks
    )
    full_text = parsed["full_text"]

    assert parsed["errors"] == []
    assert len(blocks) == len(parsed["blocks"]) == 715
    assert from_rich == full_text
    assert "HSBC" in full_text

    # 11.2 The row reflow and the control-mark cleanup, measured on this sample.
    assert len(full_text) == 50022
    assert full_text.count("\n") == 735
    for control in ("\x07", "\x08", "\t"):
        assert control not in full_text
    assert "\xa0" in full_text, "a visible no-break space must survive"
    assert (
        "We are informed by (the “Tenderer”) that they are submitting an offer to you for the"
        in full_text
    ), "a sentence cut by an underlined blank stays one line"


def test_the_contents_page_keeps_each_number_on_its_title_row():
    """11.2 The complaint: the page number sat on the line below the chapter title."""
    page_three = [
        "".join(node.get("text", "") for node in block.get("content") or [])
        for block in _rich()["content"]
        if (block.get("attrs") or {}).get("page") == 3
    ]

    assert "Tender Guarantee Standard 4" in page_three
    assert "Tender Guarantee World Bank Tender 5" in page_three
    assert "Facility Guarantee 15" in page_three
    assert "Tender Guarantee Standard" not in page_three, "the title no longer stands alone"
    assert "4" not in page_three, "the number is no longer its own line"


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


# --- 13.2 / 13.3 layout on the real sample --------------------------------------------------------


def test_the_beneficiary_blank_is_a_visible_gap():
    """13.2 The customer's example: 'Beneficiary:' followed by a drawn rule."""
    blocks = _page_blocks(_rich(), 5)
    beneficiary = next(block for block in blocks if _block_text(block) == "Beneficiary:")

    assert beneficiary["attrs"]["row"] is True
    gaps = _gaps(beneficiary)
    assert gaps and gaps[-1]["attrs"]["rule"] is True
    assert gaps[-1]["attrs"]["grow"] > 100
    assert _block_text(beneficiary) == "Beneficiary:", "the gap adds no characters"


def test_the_placeholder_line_starts_with_a_visible_rule():
    """13.2 The second line of the same form: a leading rule then the placeholder."""
    blocks = _page_blocks(_rich(), 5)
    placeholder = next(
        block for block in blocks if "Name and Address of Purchaser" in _block_text(block)
    )

    assert placeholder["attrs"]["row"] is True
    gaps = _gaps(placeholder)
    assert gaps and gaps[0]["attrs"]["rule"] is True
    assert gaps[0]["attrs"]["grow"] > 100


def test_a_second_form_variant_keeps_its_rule():
    """13.6 Page 22 has the same 'Beneficiary:' blank at a different position."""
    blocks = _page_blocks(_rich(), 22)
    beneficiary = next(block for block in blocks if _block_text(block) == "Beneficiary:")

    assert beneficiary["attrs"]["row"] is True
    gaps = _gaps(beneficiary)
    assert gaps and gaps[-1]["attrs"]["rule"] is True


def test_the_contents_row_pushes_the_page_number_right():
    """13.3 Title left, page number right: an invisible flexible gap."""
    blocks = _page_blocks(_rich(), 3)
    row = next(
        block for block in blocks if _block_text(block) == "Tender Guarantee Standard 4"
    )

    assert row["attrs"]["row"] is True
    gaps = _gaps(row)
    assert gaps and gaps[0]["attrs"]["rule"] is False
    assert gaps[0]["attrs"]["grow"] == pytest.approx(399.3, abs=1.0)
    assert _block_text(row) == "Tender Guarantee Standard 4"


def test_page_numbers_and_the_page_header_are_right_aligned():
    """13.3 A single fragment hugging the right edge gets `align=right`."""
    page_two = _page_blocks(_rich(), 2)
    number = next(block for block in page_two if _block_text(block) == "2")
    page_three = _page_blocks(_rich(), 3)
    header = next(block for block in page_three if _block_text(block) == "Page")

    assert number["attrs"]["align"] == "right"
    assert header["attrs"]["align"] == "right"


def test_the_sample_has_the_layout_the_fourth_round_targets():
    """13.1 The numbers the design was based on: 226 rules, 171 blank rows, 0 multi-row layout."""
    fitz = pytest.importorskip("pymupdf")
    document = fitz.open(str(SAMPLE))
    rules = 0
    rows_with_rule = 0
    multi_row_layout = 0
    try:
        for page in document:
            page_rules = horizontal_rules(page.get_drawings())
            rules += len(page_rules)
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                rows = visual_rows(block)
                has_rule = any(
                    any(item.get("rule") for item in row_layout(row, page_rules)) for row in rows
                )
                if has_rule:
                    if len(rows) == 1:
                        rows_with_rule += 1
                    else:
                        multi_row_layout += 1
    finally:
        document.close()

    assert rules == 226
    assert rows_with_rule == 171
    assert multi_row_layout == 0