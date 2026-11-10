"""Parsing (`SourceFile` -> `ParsedDoc`).

Sources: `openspec/changes/agent-normalize/design.md` §5,
contract signatures: `openspec/changes/poc-skeleton/design.md` §6.

**Zero model calls**, pure functions. Three hard requirements:
1. A single failing file **must not raise**: it is recorded in `ParsedDoc.errors` and the rest continue
2. No text layer (scanned document) -> an explicit error; **MUST NOT** return an empty `full_text`
   pretending success
3. `text` keeps the source's **visible** characters verbatim: no rewriting. Invisible control marks are
   dropped and a block's fragments are reflowed into visual rows (design D17-D19); `\xa0` and the
   full-width space are visible and stay.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.parsing.pdf_layout import block_text
from app.parsing.rich_docx import RichDocError, document_to_rich as document_to_rich_docx
from app.parsing.rich_pdf import RichPdfError, document_to_rich as document_to_rich_pdf
from app.state import ParsedBlock, ParsedDoc, SourceFile

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_MIMES = ("image/png", "image/jpeg", "image/jpg")
NO_TEXT_LAYER = "no_text_layer: looks like a scanned document, OCR required (not supported in the POC)"

# WordprocessingML namespace — we read the OOXML zip directly, never through an office suite.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Import limits (design D9): OCR is synchronous and slow, so a single request must stay bounded.
MAX_BYTES = 20 * 1024 * 1024
MAX_OCR_PAGES = 30
OCR_DPI = 300
OCR_LANGS = os.environ.get("SMART_EDIT_OCR_LANGS", "chi_sim+eng")


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
    if mime == DOCX_MIME or name.endswith(".docx"):
        return "docx_text"
    if mime in IMAGE_MIMES or name.endswith((".png", ".jpg", ".jpeg")):
        return "image_ocr"
    if name.endswith(".eml"):
        return "email"
    if mime.startswith("text/") or name.endswith((".txt", ".md")):
        return "plain_text"
    # `.doc` (binary Word) lands here on purpose: it is not OOXML and we do not open it.
    return None


def _blocks_from_pdf(path: str, file_id: str) -> tuple[list[ParsedBlock], list[str]]:
    """Text-layer PDF -> blocks (with `page` and, when available, `bbox`).

    Text comes from ``get_text("dict")`` so the shared visual-row layer can put a title and its
    right-aligned page number on one line (design D17-D19). ``get_text("blocks")`` and this mode
    produce the same block text for the shipped sample; the difference is only the row reflow.
    """
    import fitz  # pymupdf, imported lazily: non-PDF paths do not need it

    blocks: list[ParsedBlock] = []
    try:
        document = fitz.open(path)
    except Exception as exc:  # pymupdf raises a mixed bag; degrade everything to `errors`
        return [], [f"pdf_open_failed: {exc}"]
    try:
        for page_index, page in enumerate(document, start=1):
            for raw in page.get_text("dict").get("blocks", []):
                if raw.get("type") != 0:  # 0 = text block; images are not this path's business
                    continue
                text = block_text(raw)
                if not text.strip():
                    continue
                x0, y0, x1, y1 = raw["bbox"]
                blocks.append(
                    {
                        "file_id": file_id,
                        "page": page_index,
                        "bbox": [float(x0), float(y0), float(x1), float(y1)],
                        "text": text,
                        "kind": "paragraph",
                    }
                )
    finally:
        document.close()
    return blocks, []


def _blocks_from_docx(path: str, file_id: str) -> tuple[list[ParsedBlock], list[str]]:
    """DOCX -> blocks, reading the OOXML zip directly (task 1.2).

    Only `word/document.xml` is read: no styles, no macros (`vbaProject.bin`), no external links, no
    embedded objects. Body order is preserved — paragraphs as `paragraph`, table cells as `table_cell`.
    A nested table inside a cell is *not* walked further (documented POC limit, design Non-Goals).
    """
    import xml.etree.ElementTree as ET
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            try:
                payload = archive.read("word/document.xml")
            except KeyError:
                return [], ["docx_unreadable: missing word/document.xml"]
    except (zipfile.BadZipFile, OSError) as exc:
        return [], [f"docx_unreadable: {exc}"]

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        return [], [f"docx_unreadable: {exc}"]

    body = root.find(f"{_W}body")
    if body is None:
        return [], ["docx_unreadable: no body element"]

    blocks: list[ParsedBlock] = []
    for child in body:
        if child.tag == f"{_W}p":
            text = _docx_text(child)
            if text.strip():
                blocks.append(_positional_block(file_id, text, kind="paragraph"))
        elif child.tag == f"{_W}tbl":
            _table_blocks(child, file_id, blocks)
    return blocks, []


def _children(element, tag: str) -> list:
    """Direct children only: `cell.iter()` would descend into a nested table and duplicate it."""
    return [child for child in list(element) if child.tag == tag]


def _paragraph_text(paragraph) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{_W}t"))


def _table_blocks(table, file_id: str, blocks: list[ParsedBlock]) -> None:
    """Emit direct cells in document order, then recurse into each cell's nested table once."""
    for row in _children(table, f"{_W}tr"):
        for cell in _children(row, f"{_W}tc"):
            text = _docx_text(cell)
            if text.strip():
                blocks.append(_positional_block(file_id, text, kind="table_cell"))
            for nested in _children(cell, f"{_W}tbl"):
                _table_blocks(nested, file_id, blocks)


def _docx_text(element) -> str:
    """Text of one OOXML element, preserving paragraph boundaries as raw newlines.

    Concatenating every `w:t` descends into nested tables and glues `Alpha` + `Beta` into
    `AlphaBeta`; paragraph boundaries are a layout fact the normalizer relies on.
    """
    if element.tag == f"{_W}p":
        return _paragraph_text(element)
    paragraphs = _children(element, f"{_W}p")
    return "\n".join(_paragraph_text(paragraph) for paragraph in paragraphs)


def _positional_block(file_id: str, text: str, *, kind: str) -> ParsedBlock:
    return {"file_id": file_id, "page": None, "bbox": None, "text": text, "kind": kind}


_NO_TEXT_RECOGNIZED = "no_text_recognized: the OCR engine produced no usable text"
_NO_TEXT_FOUND = "no_text_found: the document contains no text"
_OCR_ENGINE_MISSING = (
    "ocr_engine_missing: local OCR engine unavailable (install tesseract plus its language data)"
)
_ENGINE_TOKENS = ("tesseract", "tessdata", "leptonica", "no ocr")

# An empty text is never success; the reason depends on how it was read.
_EMPTY_REASON = {
    "pdf_text": NO_TEXT_LAYER,
    "docx_text": _NO_TEXT_FOUND,
    "image_ocr": _NO_TEXT_RECOGNIZED,
    "plain_text": _NO_TEXT_FOUND,
    "email": _NO_TEXT_FOUND,
}


def _looks_like_missing_engine(exc: Exception) -> bool:
    """Tesseract absence surfaces as a message, not a distinct exception type."""
    text = str(exc).lower()
    return any(token in text for token in _ENGINE_TOKENS)


def _ocr_page(
    page, file_id: str, *, page_number: int, languages: str | None, dpi: int | None
) -> tuple[list[ParsedBlock], list[str]]:
    """OCR one page and return its blocks (`bbox` stays in the page's own coordinate space)."""
    try:
        textpage = page.get_textpage_ocr(
            language=languages or OCR_LANGS, dpi=dpi or OCR_DPI, full=True
        )
        raw_blocks = page.get_text("blocks", textpage=textpage)
    except Exception as exc:  # a missing engine must be a reported problem, never a crash
        if _looks_like_missing_engine(exc):
            return [], [_OCR_ENGINE_MISSING]
        return [], [f"ocr_failed: {exc}"]

    blocks: list[ParsedBlock] = []
    for raw in raw_blocks or []:
        text = str(raw[4]).strip("\n")
        if not text.strip():
            continue
        blocks.append(
            {
                "file_id": file_id,
                "page": page_number,
                "bbox": [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])],
                "text": text,
                "kind": "paragraph",
            }
        )
    return blocks, []


def _blocks_from_pdf_ocr(path: str, file_id: str) -> tuple[list[ParsedBlock], list[str]]:
    """No text layer -> OCR every page (task 2.2); bounded by `MAX_OCR_PAGES`."""
    import pymupdf

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        return [], [f"pdf_open_failed: {exc}"]
    try:
        if document.page_count > MAX_OCR_PAGES:
            return [], [
                f"too_many_pages: {document.page_count} pages exceeds the {MAX_OCR_PAGES}-page OCR limit"
            ]
        blocks: list[ParsedBlock] = []
        for page_index, page in enumerate(document, start=1):
            page_blocks, errors = _ocr_page(
                page, file_id, page_number=page_index, languages=None, dpi=None
            )
            if errors:
                return [], errors
            blocks.extend(page_blocks)
    finally:
        document.close()
    return blocks, []


def _blocks_from_image(
    path: str, file_id: str, *, languages: str | None = None, dpi: int | None = None
) -> tuple[list[ParsedBlock], list[str]]:
    """Image -> blocks via the local OCR engine (task 2.1).

    PyMuPDF opens a PNG/JPEG as a one-page document and drives Tesseract itself, so this needs no
    Python imaging dependency. `bbox` is in the image's own coordinate space, which is what a reviewer
    needs to look at the original region.
    """
    import pymupdf

    try:
        document = pymupdf.open(path)
        try:
            page = document[0]  # a corrupt file fails here, not at open(): pymupdf loads lazily
            blocks, errors = _ocr_page(
                page, file_id, page_number=1, languages=languages, dpi=dpi
            )
        finally:
            document.close()
    except Exception as exc:  # pymupdf raises a mixed bag
        return [], [f"image_open_failed: {exc}"]
    if not blocks and not errors:
        return [], [_NO_TEXT_RECOGNIZED]
    return blocks, errors


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


def _fallback_rich(blocks: list[ParsedBlock], full_text: str, reason: str) -> dict:
    """Everything the deterministic/heuristic builders could not handle becomes plain paragraphs."""
    content = (
        [{"type": "paragraph", "content": [{"type": "text", "text": block["text"]}]} for block in blocks]
        if blocks
        else (
            [{"type": "paragraph", "content": [{"type": "text", "text": full_text}]}]
            if full_text.strip()
            else []
        )
    )
    return {
        "type": "doc",
        "content": content,
        "provenance": "fallback",
        "provenanceNote": reason,
    }


def _rich_for(path: str, form: str, blocks: list[ParsedBlock], full_text: str) -> dict:
    """Rich structure for the editor (design D4/D5). Never fails an import: it degrades instead."""
    try:
        if form == "docx_text":
            return document_to_rich_docx(path)
        if form == "pdf_text":
            return document_to_rich_pdf(path)
    except (RichDocError, RichPdfError) as exc:
        return _fallback_rich(blocks, full_text, f"{form}: {exc}")
    except Exception as exc:  # a broken builder must not cost the user their text
        return _fallback_rich(blocks, full_text, f"{form}: {type(exc).__name__}")
    return _fallback_rich(blocks, full_text, f"{form}: no structural mapping in this build")


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

    try:
        size = Path(path).stat().st_size
    except OSError as exc:
        doc["errors"] = [f"file_not_found: {exc}"]
        return doc
    if size > MAX_BYTES:
        doc["errors"] = [
            f"file_too_large: {size} bytes exceeds the {MAX_BYTES}-byte import limit"
        ]
        return doc

    errors: list[str] = []
    if form == "pdf_text":
        blocks, errors = _blocks_from_pdf(path, file_id)
        if not blocks and not errors:
            # No text layer: OCR it instead of dead-ending (task 2.2). A missing engine is reported.
            blocks, errors = _blocks_from_pdf_ocr(path, file_id)
            if blocks:
                # The text did not come from a PDF text layer; never present it as `pdf_text`.
                doc["form"] = "image_ocr"  # type: ignore[typeddict-item]
                form = "image_ocr"
    elif form == "docx_text":
        blocks, errors = _blocks_from_docx(path, file_id)
    elif form == "image_ocr":
        blocks, errors = _blocks_from_image(path, file_id)
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
        # An empty text is never a success. The message names why it is empty for this form.
        doc["errors"] = [_EMPTY_REASON.get(form, NO_TEXT_LAYER)]
    fingerprint = sha256_of(path)
    if fingerprint:
        doc["sha256"] = fingerprint
    # Only when the file produced text: a failed file has nothing to render, and a rich structure for
    # an empty document would look like a successfully read file.
    if doc["full_text"].strip():
        doc["rich"] = _rich_for(path, form, blocks, doc["full_text"])
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