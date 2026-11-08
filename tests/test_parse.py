"""Parsing behavior (tasks 3.1-3.5).

The **implementation** of `parse` / `extract` / `normalize` lives in the shared layer
(`poc-skeleton` 3.x); this file verifies the behavior `agent-normalize` declares.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.parsing.parse import NO_TEXT_LAYER, parse, parse_file


def _make_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Generate a PDF with a text layer (ASCII only, to avoid missing CJK fonts)."""
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    for lines in pages:
        page = document.new_page()
        y = 72
        for line in lines:
            page.insert_text((72, y), line, fontsize=12)
            y += 18
    document.save(str(path))
    document.close()
    return path


def _make_blank_pdf(path: Path) -> Path:
    """Generate a PDF with no text layer, simulating a scanned document."""
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    document.new_page()
    document.save(str(path))
    document.close()
    return path


def _source(path: Path, file_id: str) -> dict:
    return {
        "file_id": file_id,
        "filename": path.name,
        "mime": "application/pdf" if path.suffix == ".pdf" else "text/plain",
        "path": str(path),
        "sha256": "deadbeef",
    }


def test_pdf_blocks_have_page(tmp_path):
    """3.1 A text-layer PDF produces `page`, plus `bbox` when available."""
    pdf = _make_pdf(tmp_path / "guarantee.pdf", [["GUARANTEE NO: BG-2026-0001"], ["AMOUNT: USD 500,000.00"]])
    doc = parse_file(_source(pdf, "F-1"))

    assert doc["errors"] == []
    assert doc["form"] == "pdf_text"
    assert [block["page"] for block in doc["blocks"]] == [1, 2]
    assert all(block["bbox"] is not None and len(block["bbox"]) == 4 for block in doc["blocks"])
    # text matches the source verbatim: no whitespace folding, no rewriting
    assert "GUARANTEE NO: BG-2026-0001" in doc["blocks"][0]["text"]


def test_plain_text_blocks_have_no_page(tmp_path):
    """3.2 Pasted text and plain-text email have `page` / `bbox` set to `null`."""
    plain = tmp_path / "mail.txt"
    plain.write_text("申请人：ABC Trading Pte Ltd\n\n金额：USD 500K\n", encoding="utf-8")
    doc = parse_file(_source(plain, "F-2"))

    assert doc["errors"] == []
    assert doc["form"] == "plain_text"
    assert doc["blocks"], "plain text must produce blocks too"
    assert all(block["page"] is None and block["bbox"] is None for block in doc["blocks"])
    # a blank line splits paragraphs: two blocks
    assert len(doc["blocks"]) == 2


def test_scan_like_pdf_raises_not_silent(tmp_path):
    """3.3 A scanned PDF is OCR'd; when that cannot produce text it says so, never empty success.

    `document-import` changed the route (a missing text layer now goes to OCR instead of dead-ending),
    so the guarantee is checked at the level that must never change: **no text ⇒ an error, never a
    `done` with an empty `full_text`**.
    """
    blank = _make_blank_pdf(tmp_path / "scan.pdf")
    doc = parse_file(_source(blank, "F-3"))

    assert doc["errors"], "a scan that produced no text must be reported"
    assert doc["errors"][0].startswith(
        ("ocr_engine_missing", "no_text_recognized", "ocr_failed")
    )
    assert doc["errors"][0] != NO_TEXT_LAYER, "the dead end was replaced by an OCR attempt"
    assert doc["full_text"] == ""
    assert doc["blocks"] == []


def test_partial_failure_continues(tmp_path):
    """3.4 One failing file does not affect the others (recorded in `errors`, summarised into the trail)."""
    good = _make_pdf(tmp_path / "ok.pdf", [["BENEFICIARY: XYZ IMPORTER PTE LTD"]])
    missing = tmp_path / "gone.pdf"

    docs, trail_entries, model_calls = parse(
        [_source(good, "F-OK"), _source(missing, "F-BAD")]
    )

    assert model_calls == 0, "parse makes zero model calls"
    assert [doc["file_id"] for doc in docs] == ["F-OK", "F-BAD"]
    assert docs[0]["errors"] == [] and docs[0]["blocks"]
    assert docs[1]["errors"] and "file_not_found" in docs[1]["errors"][0]
    assert trail_entries[0]["op"] == "read"
    assert trail_entries[0]["detail"]["failed"] == ["F-BAD"]


def test_same_pdf_two_paths_identical_blocks(tmp_path):
    """3.5 The same PDF through both call paths yields block-by-block identical `blocks`."""
    pdf = _make_pdf(tmp_path / "twice.pdf", [["A: 1", "B: 2"]])
    direct = parse_file(_source(pdf, "F-1"))
    via_batch, _, _ = parse([_source(pdf, "F-1")])

    assert direct["blocks"] == via_batch[0]["blocks"]
    assert direct["full_text"] == via_batch[0]["full_text"]


def test_unsupported_mime_is_explicit(tmp_path):
    """Input outside the supported range must fail explicitly, never silently return an empty result."""
    weird = tmp_path / "data.bin"
    weird.write_bytes(b"\x00\x01")
    doc = parse_file(
        {
            "file_id": "F-4",
            "filename": "data.bin",
            "mime": "application/octet-stream",
            "path": str(weird),
            "sha256": "deadbeef",
        }
    )

    assert doc["errors"] and "unsupported_mime" in doc["errors"][0]
    assert doc["full_text"] == ""