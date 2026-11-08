"""Tasks 1.1-1.3 and 2.1-2.5 — DOCX and local-OCR parsing (no network, no office library)."""

from __future__ import annotations

import base64
import sys
import zipfile
from pathlib import Path

import pytest

from app.parsing import parse as parse_module
from app.parsing.parse import MAX_BYTES, MAX_OCR_PAGES, OCR_LANGS, parse, parse_file

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _source(path: Path, file_id: str, mime: str = "") -> dict:
    return {
        "file_id": file_id,
        "filename": path.name,
        "mime": mime,
        "path": str(path),
        "sha256": "0" * 64,
    }


def _make_docx(path: Path, *, body_xml: str, extra_files: dict[str, bytes] | None = None) -> Path:
    """Build a minimal, valid OOXML package (a DOCX is a zip with `word/document.xml`)."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body_xml}</w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        for name, payload in (extra_files or {}).items():
            archive.writestr(name, payload)
    return path


def _paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _table(rows: list[list[str]]) -> str:
    cells = "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>" for cell in row) + "</w:tr>"
        for row in rows
    )
    return f"<w:tbl>{cells}</w:tbl>"


def test_docx_is_recognised_by_extension_and_mime(tmp_path):
    """1.1 `.docx` and its MIME map to `docx_text`; binary `.doc` stays unsupported."""
    by_name = _make_docx(tmp_path / "draft.docx", body_xml=_paragraph("AMOUNT: USD 500,000.00"))
    by_mime = _make_docx(tmp_path / "noextension", body_xml=_paragraph("hello"))
    legacy = tmp_path / "old.doc"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0not-ooxml")

    docx_named = parse_file(_source(by_name, "F-1"))
    docx_mimed = parse_file(
        _source(
            by_mime,
            "F-2",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    )
    old = parse_file(_source(legacy, "F-3", mime="application/msword"))

    assert docx_named["form"] == "docx_text"
    assert docx_named["errors"] == []
    assert docx_mimed["form"] == "docx_text"
    assert old["errors"] and old["errors"][0].startswith("unsupported_mime")


def test_docx_blocks_keep_body_order(tmp_path):
    """1.2 Paragraphs and table cells come back in document order."""
    body = (
        _paragraph("DEMAND GUARANTEE")
        + _table([["Beneficiary", "Adidas AG"]])
        + _paragraph("Payment shall be made in USD.")
    )
    path = _make_docx(tmp_path / "order.docx", body_xml=body)

    doc = parse_file(_source(path, "F-1"))

    assert [block["kind"] for block in doc["blocks"]] == [
        "paragraph",
        "table_cell",
        "table_cell",
        "paragraph",
    ]
    assert [block["text"] for block in doc["blocks"]] == [
        "DEMAND GUARANTEE",
        "Beneficiary",
        "Adidas AG",
        "Payment shall be made in USD.",
    ]
    assert doc["full_text"] == "\n".join(block["text"] for block in doc["blocks"])
    assert all(block["page"] is None and block["bbox"] is None for block in doc["blocks"])


def test_docx_failures_are_named(tmp_path):
    """1.3 A broken package/missing part is a reported error, never an empty success."""
    missing_part = tmp_path / "nopart.docx"
    with zipfile.ZipFile(missing_part, "w") as archive:
        archive.writestr("docProps/core.xml", "<x/>")
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip at all")

    no_part = parse_file(_source(missing_part, "F-1"))
    not_a_zip = parse_file(_source(broken, "F-2"))

    assert no_part["errors"] == ["docx_unreadable: missing word/document.xml"]
    assert no_part["full_text"] == ""
    assert not_a_zip["errors"][0].startswith("docx_unreadable")
    assert not_a_zip["full_text"] == ""


def test_ocr_values_never_reach_the_audit_as_confirmed():
    """2.1/2.3 The form is what a reviewer sees; nothing here claims the text was read cleanly."""
    assert parse_module._form_for(
        {"file_id": "F-1", "filename": "scan.png", "mime": "image/png"}
    ) == "image_ocr"
    assert parse_module._form_for(
        {"file_id": "F-2", "filename": "photo", "mime": "image/jpeg"}
    ) == "image_ocr"


# A 1x1 PNG — enough for pymupdf to open as a one-page document, no imaging library involved.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def _png(tmp_path, name: str = "scan.png") -> Path:
    path = tmp_path / name
    path.write_bytes(_PNG_1X1)
    return path


def _stub_ocr(monkeypatch, blocks: list[tuple]):
    """Make pymupdf's OCR layer return `blocks` without needing a real Tesseract install."""
    monkeypatch.setattr("pymupdf.Page.get_textpage_ocr", lambda self, **kwargs: None)
    monkeypatch.setattr(
        "pymupdf.Page.get_text", lambda self, option, textpage=None: list(blocks)
    )


def test_image_ocr_keeps_the_block_geometry(tmp_path, monkeypatch):
    """2.1 Recognised text keeps its position, so a reviewer can look at the region."""
    _stub_ocr(monkeypatch, [(10.0, 20.0, 110.0, 40.0, "DEMAND GUARANTEE\n", 0, 0)])
    path = _png(tmp_path)

    doc = parse_file(_source(path, "F-1"))

    assert doc["form"] == "image_ocr"
    assert doc["errors"] == []
    assert doc["blocks"] == [
        {
            "file_id": "F-1",
            "page": 1,
            "bbox": [10.0, 20.0, 110.0, 40.0],
            "text": "DEMAND GUARANTEE",
            "kind": "paragraph",
        }
    ]
    assert doc["full_text"] == "DEMAND GUARANTEE"


def test_scanned_pdf_falls_back_to_ocr_with_real_page_numbers(tmp_path, monkeypatch):
    """2.2 A PDF with no text layer is OCR'd page by page instead of dead-ending."""
    fitz = pytest.importorskip("pymupdf")
    path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(str(path))
    document.close()
    _stub_ocr(monkeypatch, [(0.0, 0.0, 50.0, 10.0, "AMOUNT: USD 500,000.00\n", 0, 0)])

    doc = parse_file(_source(path, "F-1"))

    assert doc["form"] == "pdf_text", "the file is still a PDF; OCR is how its text was obtained"
    assert doc["errors"] == []
    assert [block["page"] for block in doc["blocks"]] == [1, 2]
    assert doc["full_text"].count("AMOUNT: USD 500,000.00") == 2


def test_ocr_page_limit_is_reported(tmp_path, monkeypatch):
    """2.2/2.5 A huge scan is refused with a named reason, not left running."""
    fitz = pytest.importorskip("pymupdf")
    path = tmp_path / "long.pdf"
    document = fitz.open()
    document.new_page()
    document.save(str(path))
    document.close()
    monkeypatch.setattr(parse_module, "MAX_OCR_PAGES", 0)

    doc = parse_file(_source(path, "F-1"))

    assert doc["errors"][0].startswith("too_many_pages")
    assert doc["full_text"] == ""


def test_missing_ocr_engine_is_reported_not_crashed(tmp_path):
    """2.3 Without Tesseract the import says so; it never pretends the image was empty."""
    path = _png(tmp_path)

    doc = parse_file(_source(path, "F-1"))

    assert doc["errors"], "a missing engine must be reported"
    assert doc["errors"][0].startswith(("ocr_engine_missing", "ocr_failed"))
    assert doc["full_text"] == ""


def test_ocr_with_no_text_is_reported(tmp_path, monkeypatch):
    """2.4 A blank scan is `no_text_recognized`, not a silent success."""
    _stub_ocr(monkeypatch, [])
    path = _png(tmp_path)

    doc = parse_file(_source(path, "F-1"))

    assert doc["errors"] == [parse_module._NO_TEXT_RECOGNIZED]
    assert doc["full_text"] == ""


def test_an_unopenable_image_is_named(tmp_path):
    """2.4 A corrupt image reports `image_open_failed`."""
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")

    doc = parse_file(_source(path, "F-1"))

    assert doc["errors"][0].startswith("image_open_failed")
    assert doc["full_text"] == ""


def test_size_limit_is_enforced(tmp_path, monkeypatch):
    """2.5 The byte cap is a reported refusal."""
    path = tmp_path / "big.txt"
    path.write_text("x" * 64, encoding="utf-8")
    monkeypatch.setattr(parse_module, "MAX_BYTES", 16)

    doc = parse_file(_source(path, "F-1"))

    assert doc["errors"][0].startswith("file_too_large")
    assert doc["full_text"] == ""


def test_the_text_path_never_touches_the_ocr_engine(tmp_path, monkeypatch):
    """3.2 Plain text and DOCX must not call the OCR engine at all."""

    def explode(*args, **kwargs):  # pragma: no cover - it must never run
        raise AssertionError("OCR must not run for text-only formats")

    monkeypatch.setattr(parse_module, "_ocr_page", explode)
    monkeypatch.setattr(parse_module, "_blocks_from_pdf_ocr", explode)
    plain = tmp_path / "note.txt"
    plain.write_text("AMOUNT: USD 500.00", encoding="utf-8")
    docx = _make_docx(tmp_path / "note.docx", body_xml=_paragraph("AMOUNT: USD 500.00"))

    text_doc = parse_file(_source(plain, "F-1"))
    docx_doc = parse_file(_source(docx, "F-2"))

    assert text_doc["errors"] == [] and text_doc["form"] == "plain_text"
    assert docx_doc["errors"] == [] and docx_doc["form"] == "docx_text"


def test_partial_import_names_the_failed_file(tmp_path, monkeypatch):
    """3.1 One good file plus one unreadable scan → `partial`, and the reason names the culprit."""
    from app.nodes.parse import parse_node

    good = _make_docx(tmp_path / "good.docx", body_xml=_paragraph("BENEFICIARY: Adidas AG"))
    scan = tmp_path / "scan.png"
    scan.write_bytes(_PNG_1X1)  # no engine on CI → `ocr_engine_missing`
    state = {
        "files": [
            {**_source(good, "F-GOOD", mime="application/octet-stream"), "sha256": "a" * 64},
            {**_source(scan, "F-SCAN", mime="image/png"), "sha256": "b" * 64},
        ],
        "stages": [],
        "trail": [],
    }

    update = parse_node(state)

    report = update["stages"][0]
    assert report["status"] == "partial"
    assert report["produced"] == 1
    assert "F-SCAN" in report["reason"]
    assert "Traceback" not in report["reason"], "internal details never leak into the reason"


def test_all_files_failing_is_failed_not_partial(tmp_path):
    """3.1 Nothing parsed → `failed`; the editor then offers re-upload or start-blank."""
    from app.nodes.parse import parse_node

    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"nope")
    state = {
        "files": [{**_source(broken, "F-BAD"), "sha256": "c" * 64}],
        "stages": [],
        "trail": [],
    }

    update = parse_node(state)

    assert update["stages"][0]["status"] == "failed"
    assert update["stages"][0]["produced"] == 0
    assert update["docs"][0]["errors"][0].startswith("docx_unreadable")


def test_ocr_settings_have_documented_defaults():
    """2.5 Language, dpi and limits are explicit, not hidden constants."""
    assert parse_module.OCR_DPI == 300
    assert MAX_OCR_PAGES == 30
    assert MAX_BYTES == 20 * 1024 * 1024
    assert "chi_sim" in OCR_LANGS and "eng" in OCR_LANGS


def test_docx_with_macros_is_read_without_executing_anything(tmp_path):
    """1.3 A macro-enabled package still yields its text, and no office library is imported."""
    path = _make_docx(
        tmp_path / "macro.docx",
        body_xml=_paragraph("本保函适用 URDG 758"),
        extra_files={"word/vbaProject.bin": b"\x00macro-bytes\x00"},
    )

    doc = parse_file(_source(path, "F-1"))

    assert doc["form"] == "docx_text"
    assert doc["errors"] == []
    assert "URDG 758" in doc["full_text"]
    assert "docx" not in sys.modules, "python-docx must never be involved"
    assert "win32com" not in sys.modules and "pythoncom" not in sys.modules