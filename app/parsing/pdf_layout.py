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
RULE_EDGE_MARGIN = 40.0  # a blank may start/end a little outside the text it belongs to


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


# --- layout (design D21-D23) ----------------------------------------------------------------------

HorizontalRule = tuple[float, float, float, float]  # x0, y0, x1, y1


def horizontal_rules(drawings: list[dict]) -> list[HorizontalRule]:
    """The page's drawn horizontal rules: thin, wide strokes (a blank runs along one of these)."""
    rules: list[HorizontalRule] = []
    for drawing in drawings:
        rect = drawing.get("rect")
        if rect is None:
            continue
        x0, y0, x1, y1 = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
        if x1 - x0 > 20 and y1 - y0 < 1.5:
            rules.append((x0, y0, x1, y1))
    return rules


def _overlaps_text(rule: HorizontalRule, line: dict, tolerance: float = 2.0) -> bool:
    """A rule under the text itself is not a blank; only rules between/after fragments are.

    An empty fragment (e.g. a lone ``\\x07`` used as a form marker) has a bbox but no visible text;
    it must not hide the rule that fills the blank.
    """
    if not _line_text(line).strip(EDGE_WHITESPACE):
        return False
    rx0, _, rx1, _ = rule
    lx0, lx1 = float(line["bbox"][0]), float(line["bbox"][2])
    return min(rx1, lx1) - max(rx0, lx0) > tolerance


def row_layout(
    row: list[dict], rules: list[HorizontalRule], gap_threshold: float = 20.0
) -> list[dict]:
    """Describe one visual row as text fragments and display gaps, left to right.

    Each item is either ``{"line": line}`` or ``{"rule": bool, "grow": float}``. A gap with a drawn
    rule becomes a visible blank; a large gap without a rule becomes an invisible spacer (which is
    what pushes a TOC page number to the right edge).
    """
    fragments = sorted(row, key=lambda line: float(line["bbox"][0]))
    if not fragments:
        return []

    y0 = min(float(line["bbox"][1]) for line in fragments)
    y1 = max(float(line["bbox"][3]) for line in fragments)
    x0 = min(float(line["bbox"][0]) for line in fragments)
    x1 = max(float(line["bbox"][2]) for line in fragments)
    relevant = [
        rule
        for rule in rules
        if rule[1] >= y0 - 3
        and rule[3] <= y1 + 3
        and rule[2] >= x0 - RULE_EDGE_MARGIN
        and rule[0] <= x1 + RULE_EDGE_MARGIN
        and not any(_overlaps_text(rule, line) for line in fragments)
    ]

    used: set[int] = set()
    items: list[dict] = []

    # A rule that ends before the first fragment is a leading blank.
    for index, rule in enumerate(relevant):
        if rule[2] <= float(fragments[0]["bbox"][0]) + 3:
            items.append({"rule": True, "grow": max(rule[2] - rule[0], 1.0)})
            used.add(index)

    for position, line in enumerate(fragments):
        if position:
            left = fragments[position - 1]
            gap_start = float(left["bbox"][2])
            gap_end = float(line["bbox"][0])
            if gap_end - gap_start > gap_threshold:
                covering = [
                    index
                    for index, rule in enumerate(relevant)
                    if index not in used
                    and min(rule[2], gap_end) - max(rule[0], gap_start)
                    > 0.5 * (gap_end - gap_start)
                ]
                if covering:
                    index = covering[0]
                    rule = relevant[index]
                    items.append(
                        {"rule": True, "grow": max(rule[2] - rule[0], gap_end - gap_start, 1.0)}
                    )
                    used.add(index)
                else:
                    items.append({"rule": False, "grow": max(gap_end - gap_start, 1.0)})
        items.append({"line": line})

    # A rule that starts after the last fragment is a trailing blank (e.g. "Beneficiary: ____").
    last_x1 = float(fragments[-1]["bbox"][2])
    for index, rule in enumerate(relevant):
        if index in used:
            continue
        if rule[0] >= last_x1 - 3:
            items.append({"rule": True, "grow": max(rule[2] - rule[0], 1.0)})
            used.add(index)
    return items