"""The one deterministic rich-document projection used by the document host.

Mirrors `web/src/rich/projection.ts`:

- blocks are joined with one blank line (`\\n\\n`);
- a `pageBreak` contributes no character and no separator;
- headings keep their `#` markers, lists their markers, tables one line per row;
- spans are measured in Unicode code points, never UTF-16 code units.

`node_id` is scoped to one snapshot (`b3`, `b3.r1.c2`); it is not promised across edits.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BlockSpan:
    node_id: str
    start_cp: int
    end_cp: int
    sha256: str


@dataclass(frozen=True)
class Projection:
    text: str
    blocks: tuple[BlockSpan, ...]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def quote_sha256(value: str) -> str:
    return sha256_text(value)


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _inline_text(nodes: list[dict[str, Any]]) -> str:
    text = ""
    for node in nodes:
        if not _is_record(node):
            continue
        if node.get("type") == "text":
            piece = str(node.get("text") or "")
        elif node.get("type") == "variableReference":
            attrs = node.get("attrs") or {}
            value = attrs.get("displayValue")
            piece = str(value) if value not in (None, "") else "{{" + str(attrs.get("label") or "variable") + "}}"
        else:
            piece = _inline_text(list(node.get("content") or []))
        if not piece:
            continue
        # Adjacent text runs are one sentence split only by marks: joining them must not invent a
        # character. A filled blank (variable atom) is a separate token, so keep one readable space
        # at its boundary when neither side already carries whitespace.
        is_gap = node.get("type") != "text"
        if (
            is_gap
            and text
            and not text.endswith(tuple(" \t\n"))
            and not piece.startswith(tuple(" \t\n"))
        ):
            text += " "
        text += piece
    return text


def _paragraph_text(block: dict[str, Any]) -> str:
    return _inline_text(list(block.get("content") or []))


def _list_text(block: dict[str, Any], marker: str) -> str:
    items: list[str] = []
    for index, item in enumerate(block.get("content") or []):
        paragraphs = list(item.get("content") or []) if _is_record(item) else []
        text = " ".join(_paragraph_text(paragraph) for paragraph in paragraphs)
        items.append(f"{marker.format(index=index + 1)}{text}")
    return "\n".join(items)


def _table_text(block: dict[str, Any]) -> str:
    rows: list[str] = []
    for row in block.get("content") or []:
        if not _is_record(row):
            continue
        cells: list[str] = []
        for cell in row.get("content") or []:
            paragraphs = list(cell.get("content") or []) if _is_record(cell) else []
            cells.append(" ".join(_paragraph_text(paragraph) for paragraph in paragraphs))
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _project_block(block: dict[str, Any]) -> str | None:
    kind = block.get("type")
    if kind == "pageBreak":
        return None
    if kind == "paragraph":
        return _paragraph_text(block)
    if kind == "heading":
        level = int((block.get("attrs") or {}).get("level") or 1)
        level = max(1, min(6, level))
        return f"{'#' * level} {_paragraph_text(block)}"
    if kind == "bulletList":
        return _list_text(block, "- ")
    if kind == "orderedList":
        return _list_text(block, "{index}. ")
    if kind == "table":
        return _table_text(block)
    return ""


def _sub_spans(block: dict[str, Any], node_id: str, text: str, start: int) -> list[BlockSpan]:
    """Add table/list sub-spans relative to `text` (the block span stays authoritative)."""
    spans: list[BlockSpan] = []
    kind = block.get("type")
    cursor = 0
    if kind == "table":
        for row_index, row in enumerate(block.get("content") or []):
            if not _is_record(row):
                continue
            row_text = _table_text({"type": "table", "content": [row]})
            row_start = cursor
            cursor += len(row_text)
            spans.append(
                BlockSpan(
                    f"{node_id}.r{row_index + 1}",
                    start + row_start,
                    start + cursor,
                    sha256_text(row_text),
                )
            )
            cell_cursor = row_start
            for cell_index, cell in enumerate(row.get("content") or []):
                paragraphs = list(cell.get("content") or []) if _is_record(cell) else []
                cell_text = " ".join(_paragraph_text(paragraph) for paragraph in paragraphs)
                spans.append(
                    BlockSpan(
                        f"{node_id}.r{row_index + 1}.c{cell_index + 1}",
                        start + cell_cursor,
                        start + cell_cursor + len(cell_text),
                        sha256_text(cell_text),
                    )
                )
                cell_cursor += len(cell_text) + 3  # " | " separator
            cursor += 1  # "\n" between rows
    elif kind in ("bulletList", "orderedList"):
        for item_index, item in enumerate(block.get("content") or []):
            paragraphs = list(item.get("content") or []) if _is_record(item) else []
            item_text = " ".join(_paragraph_text(paragraph) for paragraph in paragraphs)
            marker_len = 2 if kind == "bulletList" else len(f"{item_index + 1}. ")
            spans.append(
                BlockSpan(
                    f"{node_id}.i{item_index + 1}",
                    start + cursor + marker_len,
                    start + cursor + marker_len + len(item_text),
                    sha256_text(item_text),
                )
            )
            cursor += marker_len + len(item_text) + 1
    return spans


def project_document(document: dict[str, Any] | None) -> Projection:
    """Project a rich document into canonical text plus code-point spans."""
    if not document or not isinstance(document.get("content"), list):
        return Projection("", ())

    parts: list[str] = []
    blocks: list[BlockSpan] = []
    current = 0
    first = True
    for index, block in enumerate(document["content"]):
        if not _is_record(block):
            continue
        node_id = f"b{index}"
        projected = _project_block(block)
        if projected is None:
            continue
        if not first:
            current += 2  # the "\n\n" join separator
        start = current
        parts.append(projected)
        current += len(projected)
        blocks.append(BlockSpan(node_id, start, current, sha256_text(projected)))
        blocks.extend(_sub_spans(block, node_id, projected, start))
        first = False

    return Projection("".join(_join_parts(parts)), tuple(blocks))


def _join_parts(parts: list[str]) -> list[str]:
    joined: list[str] = []
    for index, part in enumerate(parts):
        if index:
            joined.append("\n\n")
        joined.append(part)
    return joined


def plain_text_document(text: str) -> dict[str, Any]:
    """Legacy/plain text -> paragraphs, matching the client's `plainTextToDocument`."""
    blocks = (text or "").split("\n\n")
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": block}] if block else [],
            }
            for block in blocks
        ],
    }


def block_for_range(projection: Projection, start_cp: int, end_cp: int) -> BlockSpan | None:
    """The smallest block span that fully contains the range, or `None` when it crosses blocks."""
    candidates = [
        block
        for block in projection.blocks
        if block.start_cp <= start_cp and end_cp <= block.end_cp
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda block: (block.start_cp, -block.end_cp))


def replace_text_in_document(
    document: dict[str, Any], start_cp: int, end_cp: int, replacement: str
) -> dict[str, Any]:
    """Replace one range inside a single paragraph/heading block, preserving every other block."""
    projection = project_document(document)
    block = block_for_range(projection, start_cp, end_cp)
    if block is None:
        raise ValueError("range must stay inside one block")
    if block.node_id.count("."):
        raise ValueError("only top-level paragraph/heading ranges are supported in this build")

    index = int(block.node_id[1:])
    content = list(document.get("content") or [])
    target = content[index]
    if target.get("type") not in ("paragraph", "heading"):
        raise ValueError("only paragraph/heading ranges are supported in this build")

    before = projection.text[block.start_cp:start_cp]
    after = projection.text[end_cp:block.end_cp]
    if target.get("type") == "heading":
        level = int((target.get("attrs") or {}).get("level") or 1)
        prefix = f"{'#' * max(1, min(6, level))} "
        before = before.removeprefix(prefix)
    new_text = before + replacement + after

    updated = dict(target)
    updated["content"] = [{"type": "text", "text": new_text}] if new_text else []
    new_content = list(content)
    new_content[index] = updated
    return {**document, "content": new_content}


__all__ = [
    "BlockSpan",
    "Projection",
    "block_for_range",
    "plain_text_document",
    "project_document",
    "quote_sha256",
    "replace_text_in_document",
    "sha256_text",
]