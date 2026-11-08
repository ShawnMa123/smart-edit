"""PDF -> rich document (design D5): heuristic, and it says so.

A PDF has font sizes and coordinates, not semantics. So:

- font size well above the body baseline -> candidate heading (mapped to H1..H3, never invented levels
  beyond that);
- blocks that sit side by side on the same horizontal band -> one row, joined with ` | `, which is what
  keeps a table's header next to its value in the plain text;
- everything is tagged `provenance: "heuristic"` with a reason, and **no character is ever changed**.
"""

from __future__ import annotations

from statistics import median

HEADING_RATIO = 1.3
_TOLERANCE = 0.55  # fraction of the median block height that still counts as "the same row"


class RichPdfError(ValueError):
    """The PDF could not be turned into a rich structure."""


def _level_for(ratio: float) -> int:
    if ratio >= 2.0:
        return 1
    if ratio >= 1.6:
        return 2
    return 3


def _span_size(block: dict) -> float:
    sizes = [
        float(span.get("size") or 0)
        for line in block.get("lines") or []
        for span in line.get("spans") or []
    ]
    return max(sizes) if sizes else 0.0


def _block_text(block: dict) -> str:
    return "\n".join(
        "".join(span.get("text") or "" for span in line.get("spans") or [])
        for line in block.get("lines") or []
    ).strip("\n")


def _center(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[1] + bbox[3]) / 2


def _rows(blocks: list[dict], tolerance: float) -> list[list[dict]]:
    """Group blocks that share a horizontal band, left to right."""
    ordered = sorted(blocks, key=lambda item: (_center(item["bbox"]), item["bbox"][0]))
    groups: list[list[dict]] = []
    for block in ordered:
        if groups and abs(_center(block["bbox"]) - _center(groups[-1][0]["bbox"])) <= tolerance:
            groups[-1].append(block)
        else:
            groups.append([block])
    return [sorted(group, key=lambda item: item["bbox"][0]) for group in groups]


def _document(page_blocks: list[dict], baseline: float) -> dict:
    content: list[dict] = []
    for page in page_blocks:
        blocks = page["blocks"]
        if not blocks:
            continue
        heights = [block["bbox"][3] - block["bbox"][1] for block in blocks]
        tolerance = max(median(heights) * _TOLERANCE, 1.0)
        for group in _rows(blocks, tolerance):
            texts = [block["text"] for block in group if block["text"].strip()]
            if not texts:
                continue
            if len(texts) == 1:
                # One block keeps its own line breaks: that is exactly what `full_text` has, and
                # flattening it would silently reflow the document.
                joined = texts[0]
            else:
                # Side-by-side blocks are one visual row; flatten each cell so the row stays one line.
                joined = " | ".join(part.replace("\n", " ") for part in texts)
            biggest = max(block["size"] for block in group)
            ratio = biggest / baseline if baseline else 1.0
            if len(group) == 1 and ratio >= HEADING_RATIO:
                content.append(
                    {
                        "type": "heading",
                        "attrs": {"level": _level_for(ratio)},
                        "content": [{"type": "text", "text": joined}],
                    }
                )
            else:
                content.append(
                    {"type": "paragraph", "content": [{"type": "text", "text": joined}]}
                )
    provenance_note = (
        f"heuristic: font baseline {baseline:.1f}pt, heading when >= {HEADING_RATIO}x"
        if baseline
        else "heuristic: no font information, everything read as paragraphs"
    )
    return {
        "type": "doc",
        "content": content,
        "provenance": "heuristic",
        "provenanceNote": provenance_note,
    }


def document_to_rich(path: str) -> dict:
    """Return a rich document built from font size and position (never from meaning)."""
    import pymupdf

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise RichPdfError(f"pdf_open_failed: {exc}") from exc

    try:
        pages: list[dict] = []
        sizes: list[float] = []
        for page in document:
            blocks: list[dict] = []
            for raw in page.get_text("dict").get("blocks", []):
                if raw.get("type") != 0:  # 0 = text block; images are not our business here
                    continue
                text = _block_text(raw)
                if not text.strip():
                    continue
                size = _span_size(raw)
                sizes.append(round(size, 1))
                blocks.append({"text": text, "bbox": tuple(raw["bbox"]), "size": size})
            pages.append({"blocks": blocks})
    finally:
        document.close()

    if not sizes:
        raise RichPdfError("no_text_layer: nothing to structure")
    baseline = median(sizes)
    return _document(pages, baseline)