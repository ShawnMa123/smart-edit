"""PDF -> rich document, built to keep the page looking like the page (design D11-D16).

A PDF carries no semantics, but it does carry *evidence of layout*: font size, font name, font flags
(bold/italic) and coordinates. This module uses exactly that and nothing else:

- **heading levels by font-size rank** (D11): sizes are deduplicated and ranked, so a 48pt cover and a
  20pt section title stop collapsing into the same level;
- **PDF bookmarks win over sizes** when the file has them (D12) — the author's outline beats a guess;
- **bold/italic from font flags or font name** (D13), never from size;
- **display attributes** (`fontSize` / `fontFamily` / `page`) so the editor can render the original look (D14);
- **page breaks as a non-text node**, page numbers and footers kept as their own blocks (D15) — nothing is
  deleted, because "look like the original" and "quietly tidy up" are opposites;
- **visual rows inside a block** (D17-D19): a title and its right-aligned page number, or a sentence
  split by an underlined blank, share one row and are joined with a single space;
- **drawn blanks and right alignment** (D21-D23): thin horizontal rules become visible `pdfGap` nodes,
  large gaps without a rule become invisible spacers (which push a TOC page number to the right), and
  a right-aligned single fragment gets `align: "right"` — all display-only, no characters;
- **nothing is rewritten** (D16): every block's *visible* characters survive, including `\\xa0`; the
  invisible `\\x07` / `\\x08` marks are dropped and a tab becomes one space.
"""

from __future__ import annotations

from collections import Counter

from app.parsing.pdf_layout import (
    block_text,
    clean_text,
    horizontal_rules,
    row_layout,
    visual_rows,
)

HEADING_RANKS = 3
PAGE_BREAK = "pageBreak"

_BOLD_HINTS = ("bold", "black", "heavy", "semibold", "demibold")
_ITALIC_HINTS = ("italic", "oblique")


class RichPdfError(ValueError):
    """The PDF could not be turned into a rich structure."""


def _spans(block: dict) -> list[dict]:
    return [span for line in block.get("lines") or [] for span in line.get("spans") or []]


def _marks(span: dict) -> list[str]:
    """Bold/italic from the flag bits **or** the font name — either is evidence, neither is a guess."""
    marks: list[str] = []
    flags = int(span.get("flags") or 0)
    font = str(span.get("font") or "").lower()
    if flags & 16 or any(hint in font for hint in _BOLD_HINTS):  # 16 = PyMuPDF TEXT_FONT_BOLD
        marks.append("bold")
    if flags & 2 or any(hint in font for hint in _ITALIC_HINTS):  # 2 = TEXT_FONT_ITALIC
        marks.append("italic")
    return marks


def _fragment_nodes(line: dict) -> list[dict]:
    """One node per span (marks kept), with the fragment's ASCII edges trimmed across spans."""
    nodes: list[dict] = []
    for span in line.get("spans") or []:
        text = clean_text(str(span.get("text") or ""))
        if not text:
            continue
        node: dict = {"type": "text", "text": text}
        marks = _marks(span)
        if marks:
            node["marks"] = marks
        nodes.append(node)

    while nodes:
        nodes[0]["text"] = nodes[0]["text"].lstrip(" \t\r\n\f\v")
        if nodes[0]["text"]:
            break
        nodes.pop(0)
    while nodes:
        nodes[-1]["text"] = nodes[-1]["text"].rstrip(" \t\r\n\f\v")
        if nodes[-1]["text"]:
            break
        nodes.pop()
    return nodes


def _text_nodes(block: dict) -> list[dict]:
    """Visual rows: fragments on one row join with a space; row breaks ride as `\\n`."""
    rows: list[list[list[dict]]] = []
    for row in visual_rows(block):
        fragments = [_fragment_nodes(line) for line in row]
        fragments = [fragment for fragment in fragments if fragment]
        if fragments:
            rows.append(fragments)

    nodes: list[dict] = []
    for row_index, fragments in enumerate(rows):
        for fragment_index, fragment in enumerate(fragments):
            if fragment_index:
                nodes.append({"type": "text", "text": " "})
            nodes.extend(fragment)
        if row_index < len(rows) - 1:
            nodes[-1]["text"] += "\n"
    return nodes


def _layout_nodes(items: list[dict]) -> list[dict]:
    """Text nodes plus display-only gaps; the gaps contribute no characters to the projection."""
    nodes: list[dict] = []
    seen_text = False
    for item in items:
        if "line" in item:
            if seen_text:
                nodes.append({"type": "text", "text": " "})
            nodes.extend(_fragment_nodes(item["line"]))
            seen_text = True
        else:
            nodes.append(
                {
                    "type": "pdfGap",
                    "attrs": {"rule": bool(item["rule"]), "grow": round(float(item["grow"]), 1)},
                }
            )
    return nodes


def _is_right_aligned(row: list[dict], content_right: float, page_width: float) -> bool:
    """A single fragment hugging the page's right edge (a page number, 'Page', a right-side label)."""
    if len(row) != 1:
        return False
    x0 = float(row[0]["bbox"][0])
    x1 = float(row[0]["bbox"][2])
    return content_right > 0 and x1 >= content_right - 6 and x0 > page_width * 0.5


def _block_size(block: dict) -> float:
    sizes = [float(span.get("size") or 0) for span in _spans(block)]
    return max(sizes) if sizes else 0.0


def _block_font(block: dict) -> str | None:
    names = Counter(str(span.get("font") or "") for span in _spans(block) if span.get("font"))
    return names.most_common(1)[0][0] if names else None


def _heading_ranks(sizes: list[float]) -> dict[float, int]:
    """Distinct sizes ranked largest-first; the body size never becomes a heading.

    The body size is the most frequent one. On a tie — a tiny test document, or a cover with one line at
    each size — the **smallest** tied size is the body: body text is what fills a page, headings are the
    exception.
    """
    if not sizes:
        return {}
    rounded = [round(size, 1) for size in sizes]
    counts = Counter(rounded)
    most = max(counts.values())
    body = min(size for size, count in counts.items() if count == most)
    heading_sizes = sorted({size for size in rounded if size > body}, reverse=True)
    return {size: min(index + 1, HEADING_RANKS) for index, size in enumerate(heading_sizes)}


def _normalise(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split()).casefold()


def _toc_entries(document) -> list[tuple[str, int, int]]:
    """`[(normalised title, level, page)]` from the PDF's own outline; empty when it has none."""
    try:
        toc = document.get_toc() or []
    except Exception:  # a damaged outline must not cost the import
        return []
    entries: list[tuple[str, int, int]] = []
    for entry in toc:
        if len(entry) < 3:
            continue
        level, title, page = entry[0], str(entry[1]), entry[2]
        entries.append((_normalise(title), min(int(level), HEADING_RANKS), int(page)))
    return entries


def _toc_level_for(text: str, page: int, toc: list[tuple[str, int, int]]) -> int | None:
    target = _normalise(text)
    if not target:
        return None
    for title, level, entry_page in toc:
        if entry_page == page and (target == title or target.startswith(title) or title in target):
            return level
    return None


def _block_attrs(block: dict, page: int) -> dict:
    attrs: dict = {"page": page}
    size = _block_size(block)
    if size:
        attrs["fontSize"] = round(size, 1)
    font = _block_font(block)
    if font:
        attrs["fontFamily"] = font
    return attrs


def _is_uniform(block: dict) -> bool:
    """True when every span in the block shares one size — the only case safe to call a heading."""
    sizes = {round(float(span.get("size") or 0), 1) for span in _spans(block)}
    return len(sizes) <= 1


def document_to_rich(path: str) -> dict:
    """Return a rich document that preserves the page's own hierarchy, marks and page boundaries."""
    import pymupdf

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise RichPdfError(f"pdf_open_failed: {exc}") from exc

    try:
        pages: list[dict] = []
        every_size: list[float] = []
        for page_number, page in enumerate(document, start=1):
            blocks: list[dict] = []
            content_right = 0.0
            for raw in page.get_text("dict").get("blocks", []):
                if raw.get("type") != 0:  # 0 = text block; images are not this module's business
                    continue
                if not block_text(raw).strip():
                    continue
                size = _block_size(raw)
                blocks.append({"raw": raw, "size": size})
                every_size.append(size)
                for line in raw.get("lines") or []:
                    content_right = max(content_right, float(line["bbox"][2]))
            pages.append(
                {
                    "page": page_number,
                    "blocks": blocks,
                    "rules": horizontal_rules(page.get_drawings()),
                    "content_right": content_right,
                    "page_width": float(page.rect.width),
                }
            )
        toc = _toc_entries(document)
    finally:
        document.close()

    if not every_size:
        raise RichPdfError("no_text_layer: nothing to structure")

    ranks = _heading_ranks(every_size)
    content: list[dict] = []
    heading_count = 0
    page_breaks = 0
    previous_page: int | None = None

    for page in pages:
        if page["page"] != previous_page and previous_page is not None:
            content.append({"type": PAGE_BREAK})
            page_breaks += 1
        previous_page = page["page"]

        for block in page["blocks"]:
            raw = block["raw"]
            rows = visual_rows(raw)
            nodes = _text_nodes(raw)
            attrs = _block_attrs(raw, page["page"])
            if len(rows) == 1:
                items = row_layout(rows[0], page["rules"])
                if any("rule" in item for item in items):
                    nodes = _layout_nodes(items)
                    attrs["row"] = True
                if _is_right_aligned(rows[0], page["content_right"], page["page_width"]):
                    attrs["align"] = "right"
            text = "".join(node["text"] for node in nodes if node["type"] == "text")
            level = _toc_level_for(text, page["page"], toc)
            if level is None and _is_uniform(raw):
                # A block that mixes sizes is not a heading: promoting it would turn a paragraph that
                # merely starts with a large line into a title (and silently restyle its body text).
                level = ranks.get(round(block["size"], 1))
            if level:
                content.append(
                    {"type": "heading", "attrs": {"level": level, **attrs}, "content": nodes}
                )
                heading_count += 1
            else:
                content.append({"type": "paragraph", "attrs": attrs, "content": nodes})

    parts = [
        f"{len(pages)} pages",
        "levels from PDF bookmarks" if toc else "levels from font-size rank",
        f"{heading_count} headings",
        f"{page_breaks} page breaks",
        "page numbers and footers kept",
    ]
    return {
        "type": "doc",
        "content": content,
        "provenance": "heuristic",
        "provenanceNote": "heuristic: " + ", ".join(parts),
    }