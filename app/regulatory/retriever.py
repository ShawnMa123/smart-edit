"""Retrieval adapter for the external `mercatoria` service.

The node never talks HTTP directly: it depends on the `Retriever` protocol, so tests and Agent 4
fixtures can swap in `FakeRetriever` without starting a service.

Contract (docs/rag-service-handoff.md §5, docs/agent3-regulatory-handoff.md §4):

    POST {SMART_EDIT_RAG}/retrieve
    {"queries": [...], "top_k": 5, "filters": {...}}
    -> {"chunks": [...], "corpus": {...}}

`corpus` is mandatory: "I found nothing" and "I never checked" must remain distinguishable.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

DEFAULT_TIMEOUT = 10.0
DEFAULT_TOP_K = 5

# Vendored mercatoria data/config. Paths in the JSON are relative to the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_CONFIG = PROJECT_ROOT / "data" / "regulatory" / "config.json"
LOCAL_CONFIG_ENV = "SMART_EDIT_RAG_CONFIG"
LOCAL_KEYWORD_ONLY_ENV = "SMART_EDIT_RAG_KEYWORD_ONLY"
_DISABLED_VALUES = {"off", "none", "disabled", "0"}


class RetrievalError(RuntimeError):
    """Base class for every honest retrieval failure."""


class RetrievalNotConfigured(RetrievalError):
    """Retrieval is explicitly disabled (`SMART_EDIT_RAG=off`) or the vendored package is missing."""


class RetrievalUnavailable(RetrievalError):
    """Connection / timeout / non-2xx response."""


class RetrievalInvalidResponse(RetrievalError):
    """The service answered, but the response cannot be used as citations."""


class KnowledgeBaseEmpty(RetrievalError):
    """The index exists as a service but contains no documents/chunks."""


class Retriever(Protocol):
    def retrieve(self, queries: list[str], filters: dict, top_k: int = DEFAULT_TOP_K) -> dict: ...


def _documents(corpus: dict) -> int:
    value = corpus.get("documents")
    if value is None:
        value = corpus.get("doc_count")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def validate_response(payload: Any) -> dict:
    """Validate the service envelope; returns it unchanged when usable."""
    if not isinstance(payload, dict):
        raise RetrievalInvalidResponse("response is not a JSON object")
    chunks = payload.get("chunks")
    corpus = payload.get("corpus")
    if not isinstance(chunks, list):
        raise RetrievalInvalidResponse("response has no `chunks` list")
    if not isinstance(corpus, dict):
        raise RetrievalInvalidResponse("response has no `corpus` block")
    if _documents(corpus) == 0:
        raise KnowledgeBaseEmpty("corpus.documents is 0; the knowledge base is not built")
    return payload


def to_chunks(raw_chunks: list[dict]) -> list[dict]:
    """Map the service's chunk objects to `app.state.Chunk` without rewriting `text`."""
    out: list[dict] = []
    for raw in raw_chunks:
        if not isinstance(raw, dict):
            raise RetrievalInvalidResponse("chunk is not an object")
        chunk_id = raw.get("chunk_id")
        text = raw.get("text")
        if not isinstance(chunk_id, str) or not chunk_id or not isinstance(text, str):
            raise RetrievalInvalidResponse("chunk missing `chunk_id` or `text`")
        source_doc = raw.get("source_doc")
        doc_id = raw.get("doc_id") or source_doc or chunk_id
        title = raw.get("title") or source_doc or doc_id
        source_doc = source_doc or doc_id
        try:
            score = float(raw.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        chunk = {
            "chunk_id": chunk_id,
            "doc_id": str(doc_id),
            "title": str(title),
            "text": text,
            "score": score,
            "source_type": "kb",
            "source_doc": source_doc,
            "articles": list(raw.get("articles") or []),
            "effective_from": raw.get("effective_from"),
            "effective_to": raw.get("effective_to"),
            "jurisdictions": list(raw.get("jurisdictions") or []),
            "applies_to": list(raw.get("applies_to") or []),
        }
        out.append(chunk)
    return out


class HttpRetriever:
    """Stdlib JSON-over-HTTP client. No hidden retries: a failure is reported, not papered over."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def retrieve(self, queries: list[str], filters: dict, top_k: int = DEFAULT_TOP_K) -> dict:
        body = json.dumps(
            {"queries": list(queries), "top_k": int(top_k), "filters": dict(filters or {})},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/retrieve",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise RetrievalUnavailable(f"HTTP {exc.code} from {self.base_url}/retrieve") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise RetrievalUnavailable(
                f"cannot reach {self.base_url}/retrieve: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RetrievalInvalidResponse(f"response is not valid UTF-8 JSON: {exc}") from exc
        return validate_response(payload)


class FakeRetriever:
    """Deterministic retriever for tests and offline demos.

    It follows the same validation path as the HTTP adapter, so an empty corpus can never look like
    a successful empty search.
    """

    def __init__(
        self,
        chunks: list[dict] | None = None,
        corpus: dict | None = None,
        *,
        error: Exception | None = None,
    ):
        self.chunks = list(chunks or [])
        self.corpus = dict(corpus or {})
        self.error = error
        self.calls: list[dict] = []

    def retrieve(self, queries: list[str], filters: dict, top_k: int = DEFAULT_TOP_K) -> dict:
        self.calls.append({"queries": list(queries), "filters": dict(filters or {}), "top_k": top_k})
        if self.error is not None:
            raise self.error
        return validate_response({"chunks": self.chunks, "corpus": self.corpus})


class InProcessRetriever:
    """Use the vendored `mercatoria` package and the checked-in local index.

    No external repo or service is required. If the embedding gateway is unavailable, the vendored
    retriever falls back to BM25 automatically (diagnostics carry `embedding_fallback`).
    """

    def __init__(self, config_path: str | Path | None = None, *, keyword_only: bool = False):
        self.config_path = Path(config_path or DEFAULT_LOCAL_CONFIG)
        self.keyword_only = keyword_only
        self._lock = threading.Lock()
        self._retriever = None
        self._signature: tuple[str, float] | None = None

    def _close(self) -> None:
        index = getattr(self._retriever, "index", None)
        if index is not None:
            index.close()
        self._retriever = None
        self._signature = None

    def _load(self):
        try:
            from mercatoria.config import load_config
            from mercatoria.retrieve import Retriever as LocalRetriever
            from mercatoria.store import CorpusUnavailable, IndexNotFound, open_current
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise RetrievalNotConfigured(f"vendored mercatoria is unavailable: {exc}") from exc

        cfg = load_config(self.config_path)
        index_dir = cfg.resolved_index_dir()
        current = index_dir / "current.txt"
        signature = (str(current), current.stat().st_mtime if current.is_file() else 0.0)
        if self._retriever is not None and signature == self._signature:
            return self._retriever
        self._close()
        try:
            index = open_current(index_dir)
        except IndexNotFound as exc:
            raise KnowledgeBaseEmpty(f"local index is not built: {exc}") from exc
        except CorpusUnavailable as exc:
            raise KnowledgeBaseEmpty(str(exc)) from exc
        self._retriever = LocalRetriever(index, cfg)
        self._signature = signature
        return self._retriever

    def retrieve(self, queries: list[str], filters: dict, top_k: int = DEFAULT_TOP_K) -> dict:
        with self._lock:
            retriever = self._load()
            try:
                payload = retriever.retrieve(
                    queries, top_k=top_k, filters=filters, keyword_only=self.keyword_only
                )
            except ValueError as exc:
                raise RetrievalInvalidResponse(str(exc)) from exc
            except (KnowledgeBaseEmpty, RetrievalError):
                raise
            except Exception as exc:
                raise RetrievalUnavailable(
                    f"local retrieval failed: {type(exc).__name__}: {exc}"
                ) from exc
        payload = validate_response(payload)
        # BM25-only / hybrid min-max always hands the top hit 1.0 and can include 0.0 tails when a
        # query matches fewer chunks than `top_k`; a zero-score chunk is not a citation.
        chunks = payload.get("chunks") or []
        positive = [chunk for chunk in chunks if float(chunk.get("score") or 0.0) > 0.0]
        if len(positive) != len(chunks):
            payload = {**payload, "chunks": positive}
        return payload


def _keyword_only(env: dict[str, str]) -> bool:
    raw = (env.get(LOCAL_KEYWORD_ONLY_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def resolve_retriever(env: dict[str, str] | None = None) -> Retriever | None:
    """HTTP when `SMART_EDIT_RAG` is a URL; otherwise the vendored local index.

    `SMART_EDIT_RAG=off` is the explicit "no retriever" switch (used by tests and deployments that
    want the honest `retrieval_not_configured` failure).
    """
    values = os.environ if env is None else env
    base_url = (values.get("SMART_EDIT_RAG") or "").strip()
    if base_url.lower() in _DISABLED_VALUES:
        return None
    if base_url:
        raw_timeout = (values.get("SMART_EDIT_RAG_TIMEOUT") or "").strip()
        try:
            timeout = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT
        except ValueError:
            timeout = DEFAULT_TIMEOUT
        return HttpRetriever(base_url, timeout=timeout)

    config_path = (values.get(LOCAL_CONFIG_ENV) or "").strip() or None
    return InProcessRetriever(config_path, keyword_only=_keyword_only(values))
