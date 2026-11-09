"""Tasks 7.1-7.7 — PDF layout fidelity: size-ranked levels, bookmarks, marks, page boundaries, no loss."""

from __future__ import annotations

import pytest

from app.parsing.parse import parse_file
from app.parsing.rich_pdf import PAGE_BREAK, RichPdfError, document_to_rich


def _page_text(page, x: float, y: float, text: str, size: float, font: str = "helv") -> None:
    page.insert_text((x, y), text, fontsize=size, fontname=font)


def _pdf(path, pages: list[list[tuple[str, float, str | None]]], *, toc=None, gap: float | None = None):
    """pages -> list of `(text, size, font)` triples, laid out top to bottom."""
    fitz = pytest.importorskip("pymupdf")
    document = fitz.open()
    for entries in pages:
        page = document.new_page()
        y = 72.0
        for text, size, font in entries:
            _page_text(page, 72.0, y, text, size, font or "helv")
            y += gap if gap is not None else size + 24
    if toc:
        document.set_toc(toc)
    document.save(str(path))
    document.close()
    return str(path)


def _blocks(rich: dict) -> list[dict]:
    return [block for block in rich["content"] if block["type"] != PAGE_BREAK]


def _text(block: dict) -> str:
    return "".join(node.get("text", "") for node in block.get("content") or [])


def _levels(rich: dict) -> list[int]:
    return [block["attrs"]["level"] for block in rich["content"] if block["type"] == "heading"]


# --- 7.1 font-size ranking -----------------------------------------------------------------------


def test_cover_section_and_subtitle_get_three_distinct_levels(tmp_path):
    """7.1 A 48/20/14/9 document must not flatten its cover and its sections into one level."""
    path = _pdf(
        tmp_path / "levels.pdf",
        [
            [
                ("BOOKLET", 48.0, None),
                ("Section One", 20.0, None),
                ("Published July 2025", 14.0, None),
                ("body text", 9.0, None),
            ]
        ],
    )

    rich = document_to_rich(path)

    assert _levels(rich) == [1, 2, 3]
    body = [block for block in rich["content"] if block["type"] == "paragraph"]
    assert [_text(block) for block in body] == ["body text"]


def test_same_size_means_same_level(tmp_path):
    """7.1 Level comes from the size, not from the order in which a block appears."""
    path = _pdf(
        tmp_path / "same.pdf",
        [
            [
                ("Chapter A", 20.0, None),
                ("body one", 9.0, None),
                ("body two", 9.0, None),
                ("Chapter B", 20.0, None),
            ]
        ],
    )

    rich = document_to_rich(path)

    assert _levels(rich) == [1, 1], "both 20pt blocks share one level"


def test_a_single_font_size_produces_no_headings(tmp_path):
    """7.1 One size everywhere → no heading is invented."""
    path = _pdf(tmp_path / "flat.pdf", [[("line a", 11.0, None), ("line b", 11.0, None)]])

    rich = document_to_rich(path)

    assert _levels(rich) == []
    assert all(block["type"] == "paragraph" for block in rich["content"])


# --- 7.2 bookmarks beat sizes --------------------------------------------------------------------


def test_bookmarks_decide_the_levels_when_present(tmp_path):
    """7.2 The author's own outline wins: a body-size block can still be a heading if the PDF says so."""
    path = _pdf(
        tmp_path / "toc.pdf",
        [
            [("Cover", 20.0, None), ("body text", 9.0, None)],
            [("Subsection", 9.0, None)],
        ],
        toc=[[1, "Cover", 1], [2, "Subsection", 2]],
    )

    rich = document_to_rich(path)

    assert _levels(rich) == [1, 2], "the 9pt block is a heading because the bookmark says level 2"
    assert "bookmarks" in rich["provenanceNote"]


def test_without_bookmarks_the_size_rank_is_used(tmp_path):
    path = _pdf(tmp_path / "notoc.pdf", [[("Title", 20.0, None), ("body", 9.0, None)]])

    rich = document_to_rich(path)

    assert "font-size rank" in rich["provenanceNote"]
    assert _levels(rich) == [1]


# --- 7.3 bold / italic from the font -------------------------------------------------------------


def test_a_bold_font_produces_a_bold_mark_and_the_same_text(tmp_path):
    """7.3 Emphasis is recovered; the characters are untouched."""
    plain_path = _pdf(tmp_path / "plain.pdf", [[("Amount: USD 500.00", 9.0, None)]])
    bold_path = _pdf(tmp_path / "bold.pdf", [[("Amount: USD 500.00", 9.0, "hebo")]])

    plain = document_to_rich(plain_path)
    bold = document_to_rich(bold_path)

    marks = [
        mark
        for block in bold["content"]
        for node in block.get("content") or []
        for mark in node.get("marks") or []
    ]
    assert "bold" in marks
    assert _text(_blocks(bold)[0]) == _text(_blocks(plain)[0])
    assert not any(
        node.get("marks") for block in plain["content"] for node in block.get("content") or []
    )


# --- 7.4 display attributes ----------------------------------------------------------------------


def test_blocks_carry_display_attributes(tmp_path):
    """7.4 Size, font and page travel with the block so the editor can draw the original look."""
    path = _pdf(tmp_path / "attrs.pdf", [[("body text", 9.0, None)]])

    block = _blocks(document_to_rich(path))[0]

    assert block["attrs"]["fontSize"] == 9.0
    assert "Helvetica" in block["attrs"]["fontFamily"]
    assert block["attrs"]["page"] == 1


# --- 7.5 page boundaries -------------------------------------------------------------------------


def test_a_page_boundary_is_marked_without_adding_text(tmp_path):
    """7.5 N pages → N-1 boundaries, and the boundary contributes no characters to the audit text."""
    path = _pdf(
        tmp_path / "pages.pdf",
        [[("page one body", 9.0, None)], [("page two body", 9.0, None)], [("page three body", 9.0, None)]],
    )

    rich = document_to_rich(path)
    markers = [block for block in rich["content"] if block["type"] == PAGE_BREAK]

    assert len(markers) == 2
    assert "2 page breaks" in rich["provenanceNote"]
    assert all("content" not in marker for marker in markers), "a marker must not carry text"


# --- 7.6 page furniture kept ---------------------------------------------------------------------


def test_page_numbers_and_footers_are_kept_as_their_own_blocks(tmp_path):
    """7.6 Nothing is deleted: the page number and the footer survive, as separate blocks."""
    path = _pdf(
        tmp_path / "furniture.pdf",
        [
            [
                ("body text of page one", 9.0, None),
                ("12", 9.0, None),
                ("CMBLIT112 - all rights reserved", 7.0, None),
            ],
            [("body text of page two", 9.0, None), ("13", 9.0, None)],
        ],
    )

    rich = document_to_rich(path)
    texts = [_text(block) for block in _blocks(rich)]

    assert "12" in texts and "13" in texts, "page numbers must not be removed"
    assert "CMBLIT112 - all rights reserved" in texts
    assert not any("body text of page one12" in text for text in texts), "no block is glued together"


# --- 7.7 conservation ----------------------------------------------------------------------------


def test_the_rich_document_keeps_every_character_of_the_parsed_text(tmp_path):
    """7.7 Projecting the rich document back must reproduce `full_text` exactly (block for block)."""
    path = _pdf(
        tmp_path / "conservation.pdf",
        [
            [("DEMAND GUARANTEE", 20.0, None), ("Amount: USD 500,000.00", 9.0, None)],
            [("Beneficiary: Adidas AG", 9.0, None), ("7", 9.0, None)],
        ],
    )

    parsed = parse_file(
        {"file_id": "F-1", "filename": "c.pdf", "mime": "application/pdf", "path": path, "sha256": "x"}
    )
    rich = document_to_rich(path)
    from_rich = "\n".join(_text(block) for block in _blocks(rich))

    assert parsed["errors"] == []
    assert from_rich == parsed["full_text"], "no block, and no character, may be dropped or rewritten"
    assert len(_blocks(rich)) == len(parsed["blocks"])


def test_a_block_that_mixes_sizes_is_not_promoted_to_a_heading():
    """7.1 guard: a block whose lines differ in size must not restyle its body as a title."""
    from app.parsing import rich_pdf

    def block(*sizes: float) -> dict:
        return {
            "lines": [
                {"spans": [{"size": size, "text": "x", "font": "helv", "flags": 0}]} for size in sizes
            ]
        }

    assert rich_pdf._is_uniform(block(20.0)) is True
    assert rich_pdf._is_uniform(block(20.0, 9.0)) is False