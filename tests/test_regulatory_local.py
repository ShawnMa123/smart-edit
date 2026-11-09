"""The vendored mercatoria index must work with no external repo or service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.regulatory.index import build, status
from app.regulatory.node import regulatory_node
from app.regulatory.retriever import InProcessRetriever, KnowledgeBaseEmpty, to_chunks
from tests.helpers import make_doc

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / "data" / "regulatory" / "config.json"


def test_default_local_index_retrieves_without_a_service():
    retriever = InProcessRetriever(keyword_only=True)

    payload = retriever.retrieve(
        ["海关 完税价格", "保函 展期"], {"jurisdictions": ["CN"], "applies_to": ["customs"]}, top_k=2
    )

    assert payload["corpus"]["documents"] == 92
    assert payload["corpus"]["chunk_count"] == 7196
    assert payload["chunks"], "the checked-in index must return citable chunks"
    assert all(float(chunk["score"]) > 0 for chunk in payload["chunks"])
    assert to_chunks(payload["chunks"])[0]["source_type"] == "kb"


def test_regulatory_node_uses_the_local_index_without_external_config(monkeypatch):
    monkeypatch.delenv("SMART_EDIT_RAG", raising=False)
    monkeypatch.setenv("SMART_EDIT_RAG_KEYWORD_ONLY", "1")
    state = {
        "docs": [
            make_doc(
                "保函编号 BG-2026-0001\n金额 USD 500,000.00\n申请人中国\n适用规则 URDG 758"
            )
        ],
        "findings": [],
        "trail": [],
        "stages": [],
    }

    update = regulatory_node(state)

    assert update["stages"][0]["status"] == "done"
    assert update["legal"]["input_mode"] == "raw"
    assert update["retrieved"], "the default local retriever must return chunks"
    assert update["legal"]["coverage"]["corpus"]["documents"] == 92


def test_missing_local_index_is_reported_as_empty(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"index_dir": str(tmp_path / "empty-index")}), encoding="utf-8"
    )
    retriever = InProcessRetriever(config, keyword_only=True)

    with pytest.raises(KnowledgeBaseEmpty):
        retriever.retrieve(["保函"], {})


def test_keyword_only_build_creates_a_usable_index(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "corpus_dir": str(ROOT / "data" / "regulatory" / "corpus"),
                "manifest_path": str(ROOT / "data" / "regulatory" / "corpus" / "manifest.json"),
                "index_dir": str(tmp_path / "index"),
            }
        ),
        encoding="utf-8",
    )

    result = build(config_path=str(config), limit=2, keyword_only=True)

    assert result["documents"] == 2
    assert result["chunks"] > 0
    assert result["embedding_dim"] == 0
    info = status(config_path=str(config))
    assert info["documents"] == 2
    assert info["chunk_count"] == result["chunks"]

    retriever = InProcessRetriever(config, keyword_only=True)
    payload = retriever.retrieve(["customs"], {}, top_k=3)
    assert payload["chunks"]
    assert payload["diagnostics"]["keyword_only"] is True
