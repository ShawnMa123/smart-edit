"""Optional live RAG smoke (skipped unless explicitly enabled).

The default suite is deterministic and offline. This module answers the one question a fake
cannot: "does the deployed mercatoria service accept our client as built — auth included?"

    SMART_EDIT_LIVE_RAG=1 \
    SMART_EDIT_RAG=http://<your-service>:8080 \
    SMART_EDIT_RAG_TOKEN=<token> \
    .venv/Scripts/python.exe -m pytest tests/test_live_rag_optional.py -q

Not a regression test: the service is third-party operated (index versions and corpus content
change without notice). It asserts only contract properties: a reachable, ready health endpoint;
citable chunks plus a non-empty `corpus` block through the real `HttpRetriever`; and a 401 for
unauthenticated calls — an auth failure must stay an exception, never an empty success.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

from app.regulatory.retriever import HttpRetriever, RetrievalUnavailable

pytestmark = pytest.mark.skipif(
    os.environ.get("SMART_EDIT_LIVE_RAG") != "1",
    reason="set SMART_EDIT_LIVE_RAG=1 to call the configured retrieval service",
)

BASE = (os.environ.get("SMART_EDIT_RAG") or "").strip().rstrip("/")
TOKEN = (os.environ.get("SMART_EDIT_RAG_TOKEN") or "").strip()

if os.environ.get("SMART_EDIT_LIVE_RAG") == "1" and not BASE:
    raise RuntimeError("SMART_EDIT_LIVE_RAG=1 requires SMART_EDIT_RAG=<service base url>")


def test_health_reports_a_ready_index():
    with urllib.request.urlopen(f"{BASE}/health", timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["status"] == "ready"
    assert int(payload["index"]["documents"]) > 0
    assert int(payload["index"]["chunks"]) > 0


def test_retrieve_returns_citable_chunks_with_token():
    retriever = HttpRetriever(BASE, timeout=60, token=TOKEN)
    payload = retriever.retrieve(["guarantee URDG 758 extension notice"], {}, top_k=3)
    assert payload["chunks"], "the live service must return citable chunks"
    assert int(payload["corpus"]["documents"]) > 0


def test_retrieve_without_token_is_unauthorized_not_empty():
    retriever = HttpRetriever(BASE, timeout=30, token=None)
    with pytest.raises(RetrievalUnavailable) as excinfo:
        retriever.retrieve(["guarantee"], {}, top_k=1)
    assert "HTTP 401" in str(excinfo.value)
