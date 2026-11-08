"""Parsing (`SourceFile` -> `ParsedDoc`).

Sources: `openspec/changes/agent-normalize/design.md` §5,
contract signatures: `openspec/changes/poc-skeleton/design.md` §6.

**Zero model calls**, pure functions. Three hard requirements:
1. A single failing file **must not raise**: it is recorded in `ParsedDoc.errors` and the rest continue
2. No text layer (scanned document) -> an explicit error; **MUST NOT** return an empty `full_text`
   pretending success
3. `text` matches the source verbatim: no whitespace folding, no rewriting
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.state import ParsedBlock, ParsedDoc, SourceFile

PDF_MIME = "application/pdf"
NO_TEXT_LAYER = "no_text_layer: looks like a scanned document, OCR required (not supported in the POC)"


def sha256_of(path: str) -> str | None:
    """File fingerprint, used for `docs` reuse (reuse when the `(file_id, sha256)` sets match)."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _form_for(src: SourceFile) -> str | None:
    mime = (src.get("mime") or "").lower()
    name = (src.get("filename") or "").lower()
    if mime == PDF_MIME or name.endswith(".pdf"):
        return "pdf_text"
    if name.endswith(".eml"):
        return "email"
    if mime.startswith("text/") or name.endswith((".txt", ".md")):
        return "plain_text"
    return None


def _blocks_from_pdf(path: str, file_id: str) -> tuple[list[ParsedBlock], list[str]]:
    """Text-layer PDF -> blocks (with `page` and, when available, `bbox`)."""
    import fitz  # pymupdf, imported lazily: non-PDF paths do not need it

    blocks: list[ParsedBlock] = []
    try:
        document = fitz.open(path)
    except Exception as exc:  # pymupdf raises a mixed bag; degrade everything to `errors`
        return [], [f"pdf_open_failed: {exc}"]
    try:
        for page_index, page in enumerate(document, start=1):
            for raw in page.get_text("blocks"):
                text = str(raw[4]).strip("\n")
                if not text.strip():
                    continue
                blocks.append(
                    {
                        "file_id": file_id,
                        "page": page_index,
                        "bbox": [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])],
                        "text": text,
                        "kind": "paragraph",
                    }
                )
    finally:
        document.close()
    return blocks, []


def _blocks_from_text(text: str, file_id: str) -> list[ParsedBlock]:
    """Plain text / email body -> blocks (no position info: `page` / `bbox` are always `None`)."""
    blocks: list[ParsedBlock] = []
    chunk: list[str] = []
    for line in text.splitlines():
        if line.strip():
            chunk.append(line)
            continue
        if chunk:
            blocks.append(_text_block(file_id, "\n".join(chunk)))
            chunk = []
    if chunk:
        blocks.append(_text_block(file_id, "\n".join(chunk)))
    return blocks


def _text_block(file_id: str, text: str) -> ParsedBlock:
    return {
        "file_id": file_id,
        "page": None,
        "bbox": None,
        "text": text,
        "kind": "paragraph",
    }


def parse_file(src: SourceFile) -> ParsedDoc:
    """Parse a single file, **without raising**.

    On failure `errors` is non-empty, `blocks=[]` and `full_text=""`; `parse_node` then aggregates
    it into `StageReport(partial)` or `failed`. An empty `full_text` never counts as success on its
    own.
    """
    file_id = src.get("file_id", "")
    filename = src.get("filename", "")
    mime = src.get("mime", "")
    doc: ParsedDoc = {
        "file_id": file_id,
        "filename": filename,
        "mime": mime,
        "form": "plain_text",
        "blocks": [],
        "full_text": "",
        "errors": [],
    }

    form = _form_for(src)
    if form is None:
        doc["errors"] = [f"unsupported_mime: {mime or filename} is outside the POC's supported range"]
        return doc
    doc["form"] = form  # type: ignore[typeddict-item]

    path = src.get("path") or ""
    if not path or not Path(path).is_file():
        doc["errors"] = [f"file_not_found: {path}"]
        return doc

    errors: list[str] = []
    if form == "pdf_text":
        blocks, errors = _blocks_from_pdf(path, file_id)
    else:
        try:
            blocks = _blocks_from_text(Path(path).read_text(encoding="utf-8"), file_id)
        except (OSError, UnicodeDecodeError) as exc:
            return {**doc, "errors": [f"read_failed: {exc}"]}

    doc["blocks"] = blocks
    # blocks in order, **verbatim**, consumed directly by Agent 3 (seam A -> C)
    doc["full_text"] = "\n".join(block["text"] for block in blocks)
    doc["errors"] = errors
    if not errors and not doc["full_text"].strip():
        # Scanned document: with no text layer we must never return an empty full_text as success
        doc["errors"] = [NO_TEXT_LAYER]
    fingerprint = sha256_of(path)
    if fingerprint:
        doc["sha256"] = fingerprint
    return doc


def parse(files: list[SourceFile]) -> tuple[list[ParsedDoc], list[dict], int]:
    """Contract signature: returns `(docs, trail_entries, model_calls)`; `model_calls` is always 0.

    A single failing file does not affect the others; failures all land in `ParsedDoc.errors` and
    are summarised here as one `op="read"` trail entry (`detail.failed` lists the failed files) —
    **never** a silent `continue`.
    """
    docs: list[ParsedDoc] = []
    failed: list[str] = []
    for src in files or []:
        doc = parse_file(src)
        docs.append(doc)
        if doc["errors"]:
            failed.append(doc["file_id"])
    total_blocks = sum(len(doc["blocks"]) for doc in docs)
    trail_entries = [
        {
            "op": "read",
            "before": None,
            "after": f"{len(docs)} docs / {total_blocks} blocks",
            "ref": None,
            "detail": {"failed": failed},
        }
    ]
    return docs, trail_entries, 0