"""Importable test builders (no fixtures here, so conftest is never imported twice)."""

from __future__ import annotations


def make_doc(
    text: str,
    *,
    file_id: str = "F-1",
    page: int | None = None,
    mime: str = "text/plain",
) -> dict:
    """Build a `ParsedDoc` from plain text (one block per line, convenient for locating)."""
    lines = [line for line in text.splitlines() if line.strip()]
    blocks = [
        {
            "file_id": file_id,
            "page": page,
            "bbox": None,
            "text": line,
            "kind": "paragraph",
        }
        for line in lines
    ]
    return {
        "file_id": file_id,
        "filename": f"{file_id}.txt",
        "mime": mime,
        "form": "plain_text",
        "blocks": blocks,
        "full_text": "\n".join(block["text"] for block in blocks),
        "errors": [],
    }


def candidate(
    key: str,
    raw_value: str,
    span: str,
    *,
    file_id: str = "F-1",
    page: int | None = None,
    confidence: float = 0.9,
    label: str | None = None,
    doc_type: str | None = None,
) -> dict:
    """Build one extract-style candidate (including `_source`)."""
    return {
        "key": key,
        "raw_value": raw_value,
        "label": label,
        "confidence": confidence,
        "doc_type": doc_type,
        "_source": {
            "file_id": file_id,
            "page": page,
            "bbox": None,
            "span": span,
            "form_label": None,
        },
    }


GUARANTEE_TEXT = """保函编号：BG-2026-0001
保函金额：USD 500K
币种：usd
申请人：ABC Trading Pte Ltd
受益人：XYZ IMPORTER PTE LTD
开立日期：12/03/26
适用规则：URDG 758"""

# The three reducer-backed keys in the contract: merging state must **append**, not overwrite
REDUCER_KEYS = ("findings", "trail", "stages")


def apply_update(state: dict, update: dict) -> dict:
    """Emulate langgraph's reducer semantics for node-chaining tests without a graph."""
    for key, value in update.items():
        if key in REDUCER_KEYS:
            state[key] = (state.get(key) or []) + value
        else:
            state[key] = value
    return state