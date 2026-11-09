"""DOCX -> rich document (design D4): deterministic mapping, no guessing.

Only OOXML structure is read (`w:pStyle`, `w:rPr/w:b|i|u`, `w:tbl`). An unknown style becomes a
paragraph — we never invent a heading level, because "which heading is this" is a claim about the
document, not something we can infer from a name we do not recognise.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Word's built-in style ids, plus the localised `标题 1` variants Word writes for zh documents.
_HEADING_LEVELS = {
    "Heading1": 1,
    "Heading2": 2,
    "Heading3": 3,
    "heading1": 1,
    "heading2": 2,
    "heading3": 3,
    "标题1": 1,
    "标题2": 2,
    "标题3": 3,
    "Title": 1,
}


class RichDocError(ValueError):
    """The document could not be turned into a rich structure."""


def _marks(run) -> list[str]:
    marks: list[str] = []
    props = run.find(f"{_W}rPr")
    if props is None:
        return marks
    if props.find(f"{_W}b") is not None:
        marks.append("bold")
    if props.find(f"{_W}i") is not None:
        marks.append("italic")
    underline = props.find(f"{_W}u")
    if underline is not None and underline.get(f"{_W}val") not in (None, "none"):
        marks.append("underline")
    return marks


def _text_of(element) -> list[dict]:
    """One text node per run, carrying its marks; empty runs are dropped."""
    nodes: list[dict] = []
    for run in element.iter(f"{_W}r"):
        text = "".join(node.text or "" for node in run.iter(f"{_W}t"))
        if not text:
            continue
        node: dict = {"type": "text", "text": text}
        marks = _marks(run)
        if marks:
            node["marks"] = marks
        nodes.append(node)
    return nodes


def _paragraph(element) -> dict:
    nodes = _text_of(element)
    props = element.find(f"{_W}pPr/{_W}pStyle")
    style = None if props is None else props.get(f"{_W}val")
    level = _HEADING_LEVELS.get(str(style)) if style else None
    if level:
        return {"type": "heading", "attrs": {"level": level}, "content": nodes}
    return {"type": "paragraph", "content": nodes}


def _table(element) -> dict:
    rows: list[dict] = []
    for row_index, row in enumerate(element.iter(f"{_W}tr")):
        cells: list[dict] = []
        for cell in row.iter(f"{_W}tc"):
            blocks = [_paragraph(item) for item in cell.iter(f"{_W}p")]
            blocks = [block for block in blocks if block["content"]]
            if not blocks:  # a cell must hold at least one block for the editor's schema
                blocks = [{"type": "paragraph", "content": []}]
            node: dict = {"type": "tableCell", "content": blocks}
            if row_index == 0:
                node["attrs"] = {"header": True}
            cells.append(node)
        rows.append({"type": "tableRow", "content": cells})
    return {"type": "table", "content": rows}


def document_to_rich(path: str | Path) -> dict:
    """Return `{type: 'doc', content: [...], provenance: 'deterministic'}` or raise `RichDocError`."""
    try:
        with zipfile.ZipFile(path) as archive:
            payload = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise RichDocError(f"docx_unreadable: {exc}") from exc

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RichDocError(f"docx_unreadable: {exc}") from exc

    body = root.find(f"{_W}body")
    if body is None:
        raise RichDocError("docx_unreadable: no body element")

    content: list[dict] = []
    for child in body:
        if child.tag == f"{_W}p":
            paragraph = _paragraph(child)
            if paragraph["content"]:
                content.append(paragraph)
        elif child.tag == f"{_W}tbl":
            content.append(_table(child))
    return {"type": "doc", "content": content, "provenance": "deterministic"}