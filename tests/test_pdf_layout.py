"""Tasks 10.1-10.3 and 13.1-13.2 - visual rows inside one PDF block, and layout gaps."""

from __future__ import annotations

import pytest

from app.parsing.pdf_layout import (
    block_text,
    clean_text,
    horizontal_rules,
    row_fragments,
    row_layout,
    visual_rows,
)
from app.parsing.rich_pdf import _text_nodes


def _line(
    text: str,
    *,
    x0: float = 0.0,
    x1: float = 100.0,
    y0: float = 100.0,
    y1: float = 110.0,
    font: str = "helv",
    flags: int = 0,
    size: float = 9.0,
) -> dict:
    return {
        "bbox": (x0, y0, x1, y1),
        "spans": [{"text": text, "size": size, "font": font, "flags": flags}],
    }


def _block(*lines: dict) -> dict:
    return {"lines": list(lines)}


# --- 10.1 grouping --------------------------------------------------------------------------------


def test_fragments_on_one_band_become_one_row():
    """A title and its right-aligned page number share one visual row."""
    block = _block(
        _line("4", x0=556.0, x1=561.0),
        _line("Tender Guarantee Standard", x0=34.0, x1=157.0),
    )

    rows = visual_rows(block)

    assert len(rows) == 1
    assert [row_fragments(row) for row in rows] == [["Tender Guarantee Standard", "4"]]
    assert block_text(block) == "Tender Guarantee Standard 4"


def test_stacked_lines_stay_two_rows():
    block = _block(_line("one", y0=100.0, y1=110.0), _line("two", y0=120.0, y1=130.0))

    assert len(visual_rows(block)) == 2
    assert block_text(block) == "one\ntwo"


def test_a_single_line_is_one_row():
    block = _block(_line("plain words"))

    assert len(visual_rows(block)) == 1
    assert block_text(block) == "plain words"


def test_49_percent_overlap_is_not_the_same_row():
    """The threshold is exclusive: just under half the shorter height stays two rows."""
    block = _block(_line("upper", y0=100.0, y1=110.0), _line("lower", y0=105.1, y1=115.1))

    assert len(visual_rows(block)) == 2
    assert block_text(block) == "upper\nlower"


def test_rows_never_cross_blocks():
    """The function is block-scoped: two blocks at the same y stay two texts."""
    left = _block(_line("left", x0=34.0, x1=100.0))
    right = _block(_line("right", x0=300.0, x1=400.0))

    assert block_text(left) == "left"
    assert block_text(right) == "right"


# --- 10.2 joining ----------------------------------------------------------------------------------


def test_fragments_join_with_one_space_and_rows_with_one_newline():
    block = _block(
        _line("  We are informed by ", x1=150.0),
        _line(" (the “Tenderer”) that they are submitting an offer ", x0=300.0),
        _line("next row", y0=120.0, y1=130.0),
    )

    assert block_text(block) == (
        "We are informed by (the “Tenderer”) that they are submitting an offer\nnext row"
    )


def test_empty_fragments_are_skipped():
    block = _block(_line("Title"), _line("   ", x0=200.0), _line("\x08", x0=300.0))

    assert block_text(block) == "Title"
    assert len(visual_rows(block)) == 1


# --- 10.3 control characters ----------------------------------------------------------------------


def test_control_characters_are_removed_and_tab_becomes_a_space():
    assert clean_text("a\x08b\x07c\td") == "abc d"


def test_a_title_control_mark_does_not_break_the_row():
    block = _block(
        _line("Tender Guarantee Standard\x08", x1=157.0),
        _line("4", x0=556.0, x1=561.0),
    )

    assert block_text(block) == "Tender Guarantee Standard 4"


def test_visible_whitespace_is_kept():
    assert clean_text("Trade\xa0Solutions\u3000Ltd") == "Trade\xa0Solutions\u3000Ltd"
    assert block_text(_block(_line("\xa0Title\xa0"))) == "\xa0Title\xa0"


# --- 10.2 / D18 the two layers must agree ---------------------------------------------------------


def test_rich_nodes_project_to_exactly_the_block_text():
    block = {
        "lines": [
            {
                "bbox": (34.0, 100.0, 300.0, 110.0),
                "spans": [
                    {"text": "Amount: ", "size": 9.0, "font": "helv", "flags": 0},
                    {"text": "USD 500.00", "size": 9.0, "font": "Helvetica-Bold", "flags": 0},
                ],
            },
            {
                "bbox": (556.0, 100.0, 561.0, 110.0),
                "spans": [{"text": "4", "size": 9.0, "font": "helv", "flags": 0}],
            },
        ]
    }

    nodes = _text_nodes(block)

    assert "".join(node["text"] for node in nodes) == block_text(block)
    assert block_text(block) == "Amount: USD 500.00 4"
    assert any("bold" in (node.get("marks") or []) for node in nodes)


# --- 13.1 / 13.2 layout planning ------------------------------------------------------------------


def test_horizontal_rules_keep_only_thin_wide_strokes():
    drawings = [
        {"rect": (10.0, 100.0, 200.0, 100.2)},
        {"rect": (10.0, 100.0, 10.3, 200.0)},  # vertical
        {"rect": (10.0, 100.0, 200.0, 120.0)},  # thick box
    ]

    assert horizontal_rules(drawings) == [(10.0, 100.0, 200.0, 100.2)]


def test_a_trailing_rule_becomes_a_visible_gap():
    row = visual_rows(_block(_line("Beneficiary:", x0=34.0, x1=83.0, y0=100.0, y1=112.0)))[0]

    items = row_layout(row, [(82.2, 110.5, 561.3, 110.7)])

    assert "line" in items[0]
    assert items[1]["rule"] is True
    assert items[1]["grow"] == pytest.approx(479.1)


def test_a_leading_rule_becomes_a_visible_gap_before_the_text():
    row = visual_rows(
        _block(_line("[Name and Address of Purchaser]", x0=419.4, x1=558.5, y0=100.0, y1=112.0))
    )[0]

    items = row_layout(row, [(34.0, 110.5, 419.5, 110.7)])

    assert items[0]["rule"] is True
    assert items[0]["grow"] == pytest.approx(385.5)
    assert "line" in items[1]


def test_a_large_gap_without_a_rule_is_an_invisible_spacer():
    row = visual_rows(
        _block(
            _line("Tender Guarantee Standard", x0=34.0, x1=157.0),
            _line("4", x0=556.0, x1=561.0),
        )
    )[0]

    items = row_layout(row, [])

    assert [("line" in item) for item in items] == [True, False, True]
    assert items[1]["rule"] is False
    assert items[1]["grow"] == pytest.approx(399.0)


def test_a_rule_between_two_fragments_is_visible():
    row = visual_rows(
        _block(
            _line("We are informed by ", x0=34.0, x1=115.0),
            _line(" (the “Tenderer”) that they are submitting", x0=284.9, x1=538.7),
        )
    )[0]

    items = row_layout(row, [(115.0, 110.5, 284.9, 110.7)])

    assert [("line" in item) for item in items] == [True, False, True]
    assert items[1]["rule"] is True
    assert items[1]["grow"] == pytest.approx(169.9)


def test_a_rule_under_the_text_itself_is_not_a_blank():
    row = visual_rows(_block(_line("Section", x0=34.0, x1=200.0)))[0]

    items = row_layout(row, [(34.0, 110.5, 200.0, 110.7)])

    assert len(items) == 1
    assert "line" in items[0]