"""Visual rows inside one PDF text block (design D17-D19).

PyMuPDF's ``line`` is a text-extraction unit, not a visual line. A title and its right-aligned page
number, or a sentence split by an underlined blank, arrive as two or more ``line`` objects that share
one vertical band. Treating each ``line`` as a text line puts the page number on its own row; this
module groups those fragments into the row a reader actually sees.

Only *within* a block: PyMuPDF already keeps separate columns in separate blocks, and merging across
blocks would change the block count that the import guarantees.
"""

from __future__ import annotations

ROW_OVERLAP = 0.5  # fraction of the shorter line's height that still counts as "the same row"
CONTROL_CHARS = ("\x07", "\x08")  # PDF tab/leader marks: invisible, never part of the text
EDGE_WHITESPACE = " \t\r\n\f\v"  # ASCII only: `\xa0` and the full-width space are visible content


def clean_text(text: str) -> str:
    """Drop invisible control marks and turn a tab into one space; keep visible whitespace."""
    for control in CONTROL_CHARS:
        text = text.replace(control, "")
    return text.replace("\t", " ")


def _line_text(line: dict) -> str:
    return clean_text("".join(str(span.get("text") or "") for span in line.get("spans") or []))


def _overlaps(a: dict, b: dict) -> bool:
    a0, a1 = float(a["bbox"][1]), float(a["bbox"][3])
    b0, b1 = float(b["bbox"][1]), float(b["bbox"][3])
    shorter = min(a1 - a0, b1 - b0)
    if shorter <= 0:
        return a0 == b0
    return min(a1, b1) - max(a0, b0) > ROW_OVERLAP * shorter


def visual_rows(block: dict) -> list[list[dict]]:
    """Group the block's non-empty ``line`` objects into rows, top-to-bottom and left-to-right."""
    lines = [line for line in block.get("lines") or [] if _line_text(line).strip(EDGE_WHITESPACE)]
    lines.sort(key=lambda line: (float(line["bbox"][1]), float(line["bbox"][0])))

    rows: list[list[dict]] = []
    for line in lines:
        # Pairwise, not via the row's union: a union can chain two stacked rows into one.
        for row in rows:
            if all(_overlaps(line, member) for member in row):
                row.append(line)
                break
        else:
            rows.append([line])

    rows.sort(key=lambda row: min(float(line["bbox"][1]) for line in row))
    return [sorted(row, key=lambda line: float(line["bbox"][0])) for row in rows]


def row_fragments(row: list[dict]) -> list[str]:
    """The row's non-empty fragments, left to right, with their ASCII edges trimmed."""
    texts = [_line_text(line).strip(EDGE_WHITESPACE) for line in row]
    return [text for text in texts if text]


def block_text(block: dict) -> str:
    """One visual row per line; fragments inside a row are joined with a single space."""
    rows = [" ".join(row_fragments(row)) for row in visual_rows(block)]
    return "\n".join(text for text in rows if text).strip("\n")