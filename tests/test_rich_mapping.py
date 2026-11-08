"""Tasks 1.2-1.4 — rich structures from DOCX (deterministic) and PDF (heuristic), plus fallback."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.parsing import parse as parse_module
from app.parsing.parse import parse_file
from app.parsing.rich_docx import RichDocError, document_to_rich as docx_to_rich
from app.parsing.rich_pdf import document_to_rich as pdf_to_rich

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _source(path: Path, file_id: str = "F-1", mime: str = "") -> dict:
    return {
        "file_id": file_id,
        "filename": path.name,
        "mime": mime,
        "path": str(path),
        "sha256": "0" * 64,
    }


def _docx(path: Path, body: str) -> Path:
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    return path


def _p(text: str, *, style: str | None = None, bold: bool = False) -> str:
    props = f'<w:pStyle w:val="{style}"/>' if style else ""
    paragraph_props = f"<w:pPr>{props}</w:pPr>" if props else ""
    run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f"<w:p>{paragraph_props}<w:r>{run_props}<w:t>{text}</w:t></w:r></w:p>"


def _tbl(rows: list[list[str]]) -> str:
    cells = "".join(
        "<w:tr>"
        + "".join(f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>" for cell in row)
        + "</w:tr>"
        for row in rows
    )
    return f"<w:tbl>{cells}</w:tbl>"


def _blank_pdf(path: Path, *, pages: int = 1) -> Path:
    fitz = pytest.importorskip("pymupdf")
    document = fitz.open()
    for _ in range(pages):
        document.new_page()
    document.save(str(path))
    document.close()
    return path


def _text_pdf(path: Path, lines: list[tuple[str, float]]) -> Path:
    """A PDF with one text block per `(text, font_size)` — enough to exercise the heuristics."""
    fitz = pytest.importorskip("pymupdf")
    document = fitz.open()
    page = document.new_page()
    y = 72.0
    for text, size in lines:
        page.insert_text((72, y), text, fontsize=size)
        y += size * 2
    document.save(str(path))
    document.close()
    return path


# --- DOCX: deterministic mapping ---------------------------------------------------------------


def test_docx_styles_become_headings_and_marks(tmp_path):
    """1.2 `w:pStyle` and `w:b` are read as structure, and the document says `deterministic`."""
    path = _docx(
        tmp_path / "styled.docx",
        _p("DEMAND GUARANTEE", style="Heading1")
        + _p("Beneficiary: Adidas AG", bold=True)
        + _p("plain paragraph"),
    )

    rich = docx_to_rich(path)

    assert rich["provenance"] == "deterministic"
    assert [block["type"] for block in rich["content"]] == ["heading", "paragraph", "paragraph"]
    assert rich["content"][0]["attrs"] == {"level": 1}
    assert rich["content"][0]["content"][0]["text"] == "DEMAND GUARANTEE"
    assert rich["content"][1]["content"][0]["marks"] == ["bold"]
    assert "marks" not in rich["content"][2]["content"][0]


def test_docx_unknown_style_is_never_guessed_as_a_heading(tmp_path):
    """1.2 An unrecognised style stays a paragraph — we do not invent a level."""
    path = _docx(tmp_path / "unknown.docx", _p("Some caption", style="MyCustomStyle"))

    rich = docx_to_rich(path)

    assert rich["content"][0]["type"] == "paragraph"


def test_docx_table_keeps_rows_cells_and_a_header_row(tmp_path):
    """1.2 A table becomes a table, first row marked as header."""
    path = _docx(
        tmp_path / "table.docx", _tbl([["Beneficiary", "Adidas AG"], ["Amount", "USD 500.00"]])
    )

    rich = docx_to_rich(path)
    table = rich["content"][0]

    assert table["type"] == "table"
    assert len(table["content"]) == 2
    assert table["content"][0]["content"][0]["attrs"] == {"header": True}
    assert "attrs" not in table["content"][1]["content"][0]


def test_a_broken_docx_raises_rather_than_returning_an_empty_document(tmp_path):
    """1.2 The builder's failure is a typed error; the caller degrades (see 1.4)."""
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")

    with pytest.raises(RichDocError):
        docx_to_rich(broken)


# --- PDF: heuristic mapping ---------------------------------------------------------------------


def test_pdf_large_font_becomes_a_heading_and_says_heuristic(tmp_path):
    """1.3 A block far above the body size is a candidate heading, tagged `heuristic`."""
    path = _text_pdf(
        tmp_path / "sized.pdf",
        [("DEMAND GUARANTEE", 24.0), ("body line one", 10.0), ("body line two", 10.0)],
    )

    rich = pdf_to_rich(str(path))

    assert rich["provenance"] == "heuristic"
    assert rich["provenanceNote"].startswith("heuristic:")
    assert any(block["type"] == "heading" for block in rich["content"])
    heading = next(block for block in rich["content"] if block["type"] == "heading")
    assert heading["content"][0]["text"] == "DEMAND GUARANTEE"
    assert heading["attrs"]["level"] in (1, 2, 3)


def test_pdf_with_uniform_font_invents_no_headings(tmp_path):
    """1.3 Same size everywhere → everything is a paragraph (no guessing)."""
    path = _text_pdf(
        tmp_path / "flat.pdf", [("line a", 11.0), ("line b", 11.0), ("line c", 11.0)]
    )

    rich = pdf_to_rich(str(path))

    assert rich["provenance"] == "heuristic"
    assert all(block["type"] == "paragraph" for block in rich["content"])


def test_pdf_text_is_never_altered(tmp_path):
    """1.3 Structure may be inferred; the characters may not change."""
    path = _text_pdf(
        tmp_path / "exact.pdf", [("Amount: USD 500,000.00", 12.0), ("body", 10.0)]
    )

    rich = pdf_to_rich(str(path))
    joined = "\n".join(
        "".join(node["text"] for node in block.get("content") or []) for block in rich["content"]
    )

    assert "Amount: USD 500,000.00" in joined


# --- degradation (1.4) --------------------------------------------------------------------------


def test_plain_text_still_parses_and_degrades_with_a_reason(tmp_path):
    """1.4 Text with no structure keeps working, and the document says `fallback`."""
    path = tmp_path / "note.txt"
    path.write_text("AMOUNT: USD 500.00\nBENEFICIARY: Adidas AG", encoding="utf-8")

    document = parse_file(_source(path))

    assert document["errors"] == []
    assert document["full_text"].strip(), "text extraction is unchanged"
    assert document["rich"]["provenance"] == "fallback"
    assert "no structural mapping" in document["rich"]["provenanceNote"]


def test_a_failing_builder_degrades_instead_of_failing_the_import(tmp_path, monkeypatch):
    """1.4 A broken rich builder costs the formatting, never the text."""
    path = _docx(tmp_path / "ok.docx", _p("DEMAND GUARANTEE", style="Heading1"))

    def explode(*args, **kwargs):
        raise RuntimeError("builder exploded")

    monkeypatch.setattr(parse_module, "document_to_rich_docx", explode)

    document = parse_file(_source(path))

    assert document["errors"] == []
    assert "DEMAND GUARANTEE" in document["full_text"]
    assert document["rich"]["provenance"] == "fallback"
    assert "RuntimeError" in document["rich"]["provenanceNote"]


def test_a_file_with_no_text_gets_no_rich_document(tmp_path):
    """1.4 An empty result must not look like a successfully rendered document."""
    path = _blank_pdf(tmp_path / "blank.pdf", pages=1)

    document = parse_file(_source(path))

    assert document["errors"], "an empty scan is still an error"
    assert "rich" not in document