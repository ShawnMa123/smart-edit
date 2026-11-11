"""HTTP adapter tests: request shape, response validation, failure mapping."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from app.regulatory.retriever import (
    HttpRetriever,
    InProcessRetriever,
    RetrievalInvalidResponse,
    RetrievalUnavailable,
    resolve_retriever,
    to_chunks,
)

URL = "http://127.0.0.1:8100/retrieve"


class _Response:
    def __init__(self, payload: dict | bytes):
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _payload() -> dict:
    return {
        "chunks": [
            {
                "chunk_id": "c1",
                "doc_id": "customs-act",
                "source_doc": "Customs Act 1901",
                "text": "第464条 保函 USD 500,000.00",
                "score": 0.87,
                "articles": ["第464条"],
                "effective_from": "1901-01-01",
                "effective_to": None,
                "jurisdictions": ["AU"],
                "applies_to": ["customs"],
            }
        ],
        "corpus": {
            "version": "2026-11-09.1",
            "documents": 92,
            "jurisdictions": ["AU", "CN"],
            "built_at": "2026-11-09T00:00:00Z",
        },
    }


def test_http_retriever_maps_chunks_and_corpus():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(_payload())

    with patch("app.regulatory.retriever.urllib.request.urlopen", fake_urlopen):
        result = HttpRetriever("http://127.0.0.1:8100/", timeout=3.5).retrieve(
            ["保函 展期"], {"applies_to": ["guarantee"]}, top_k=7
        )

    body = json.loads(captured["request"].data.decode("utf-8"))
    assert captured["request"].full_url == URL
    assert captured["timeout"] == 3.5
    assert body == {
        "queries": ["保函 展期"],
        "top_k": 7,
        "filters": {"applies_to": ["guarantee"]},
    }
    assert result["corpus"]["documents"] == 92

    chunks = to_chunks(result["chunks"])
    assert chunks[0]["chunk_id"] == "c1"
    assert chunks[0]["source_doc"] == "Customs Act 1901"
    assert chunks[0]["source_type"] == "kb"
    assert chunks[0]["articles"] == ["第464条"]
    assert chunks[0]["jurisdictions"] == ["AU"]


def test_http_retriever_raises_on_missing_corpus():
    with patch(
        "app.regulatory.retriever.urllib.request.urlopen",
        lambda request, timeout: _Response({"chunks": []}),
    ):
        with pytest.raises(RetrievalInvalidResponse):
            HttpRetriever("http://127.0.0.1:8100").retrieve(["q"], {})


def test_http_retriever_raises_on_non_2xx():
    error = urllib.error.HTTPError(URL, 503, "unavailable", hdrs=None, fp=io.BytesIO(b"down"))
    with patch("app.regulatory.retriever.urllib.request.urlopen", side_effect=error):
        with pytest.raises(RetrievalUnavailable) as excinfo:
            HttpRetriever("http://127.0.0.1:8100").retrieve(["q"], {})
    assert "HTTP 503" in str(excinfo.value)


def test_http_retriever_raises_on_connection_error():
    error = urllib.error.URLError("connection refused")
    with patch("app.regulatory.retriever.urllib.request.urlopen", side_effect=error):
        with pytest.raises(RetrievalUnavailable):
            HttpRetriever("http://127.0.0.1:8100").retrieve(["q"], {})


def test_resolve_retriever_reads_environment():
    assert resolve_retriever({"SMART_EDIT_RAG": "off"}) is None
    assert isinstance(resolve_retriever({}), InProcessRetriever)
    retriever = resolve_retriever(
        {"SMART_EDIT_RAG": "http://127.0.0.1:8100/", "SMART_EDIT_RAG_TIMEOUT": "2.5"}
    )
    assert isinstance(retriever, HttpRetriever)
    assert retriever.base_url == "http://127.0.0.1:8100"
    assert retriever.timeout == 2.5
