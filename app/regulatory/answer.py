"""Turn retrieved chunks into `Claim` / `ApplicableRule` / `coverage` / `summary`.

Today's default is `ExtractiveAnswerer`: it quotes the source and says no more than the source
supports. It never produces a risk conclusion and never invents a `chunk_id`.

`LLMAnswerer` is intentionally only a skeleton: without a real provider, a fixture-generated legal
answer would be indistinguishable from a fabricated one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.regulatory.query import build_query, infer_business_type

Mode = Literal["enriched", "raw"]

_FORBIDDEN = ("未发现问题", "无适用规则", "合法合规")
# Order matters: "不合规" contains "合规"; replace the longer verdicts first.
_CONCLUSION_REPLACEMENTS = (
    ("未发现问题", "未覆盖"),
    ("无适用规则", "未覆盖"),
    ("合法合规", "需人工复核"),
    ("不合规", "需人工复核"),
    ("合规", "需人工复核"),
    ("不可做", "需人工复核"),
    ("可做", "需人工复核"),
)
_STANDARD_MARKERS = ("URDG", "UCP", "ISP", "WTO", "CISG", "INCOTERMS", "GATT", "TBT", "SPS", "TFA")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z0-9]{2,}")


@dataclass
class AnswerResult:
    legal: dict
    trail_entries: list[dict] = field(default_factory=list)
    model_calls: int = 0


class Answerer(Protocol):
    def answer(
        self,
        *,
        state: dict,
        mode: Mode,
        retrieved: list[dict],
        corpus: dict,
    ) -> AnswerResult: ...


def _terms(queries: list[str]) -> set[str]:
    terms: set[str] = set()
    for query in queries:
        for word in _WORD.findall(query):
            terms.add(word.casefold())
        for run in _CJK.findall(query):
            if len(run) >= 2:
                terms.add(run)
            for index in range(len(run) - 1):
                terms.add(run[index : index + 2])
    return terms


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def _quote(text: str, terms: set[str]) -> str:
    """The source sentence that shares the most query terms; fall back to the first 300 chars."""
    best: str | None = None
    best_score = 0
    for sentence in _sentences(text):
        lowered = sentence.casefold()
        score = sum(1 for term in terms if term in lowered)
        if score > best_score:
            best, best_score = sentence, score
    if best is None:
        return text.strip()[:300]
    return best[:400]


def _coverage(
    *,
    state: dict,
    mode: Mode,
    retrieved: list[dict],
    corpus: dict,
) -> dict:
    jurisdictions = sorted(
        {
            str(value)
            for chunk in retrieved
            for value in (chunk.get("jurisdictions") or [])
            if value
        }
    )
    standards = sorted(
        {
            str(chunk.get("title") or chunk.get("source_doc") or "")
            for chunk in retrieved
            if any(marker in str(chunk.get("title") or chunk.get("source_doc") or "").upper() for marker in _STANDARD_MARKERS)
        }
    )
    notes: list[str] = []
    inferred_type = state.get("business_type") or infer_business_type(state)
    if mode == "raw":
        notes.append("基于正文检索，未使用字段表")
    if not retrieved:
        notes.append("本次检索未返回可引用条文")
    return {
        "jurisdictions": jurisdictions,
        "standards": standards,
        "unavailable": not retrieved,
        "business_type_uncertain": mode == "raw" and not inferred_type,
        "inferred_business_type": inferred_type,
        "notes": notes,
        "corpus": {
            "version": corpus.get("version"),
            "documents": corpus.get("documents"),
            "jurisdictions": list(corpus.get("jurisdictions") or []),
            "built_at": corpus.get("built_at"),
        },
    }


def _applicable_rules(retrieved: list[dict], corpus: dict) -> list[dict]:
    version = str(corpus.get("version") or "unknown")
    rules: list[dict] = []
    for chunk in retrieved:
        articles = list(chunk.get("articles") or [])
        source_doc = chunk.get("source_doc") or chunk.get("doc_id") or chunk.get("chunk_id")
        rule_id = f"{source_doc}#{articles[0]}" if articles else str(chunk.get("chunk_id"))
        rules.append(
            {
                "rule_id": str(rule_id),
                "title": str(chunk.get("title") or source_doc or chunk.get("chunk_id")),
                "version": version,
                "effective_from": chunk.get("effective_from"),
                "chunk_id": str(chunk.get("chunk_id")),
            }
        )
    return rules


class ExtractiveAnswerer:
    """Quote-only answerer: one applicable-rule claim per chunk, no legal characterisation."""

    def answer(
        self,
        *,
        state: dict,
        mode: Mode,
        retrieved: list[dict],
        corpus: dict,
    ) -> AnswerResult:
        queries, _ = build_query(state, mode)
        terms = _terms(queries)
        claims = [
            {
                "text": _quote(str(chunk.get("text") or ""), terms),
                "chunk_id": str(chunk.get("chunk_id")),
                "kind": "applicable_rule",
                "support": "supported",
            }
            for chunk in retrieved
        ]
        if retrieved:
            summary = f"检索到 {len(retrieved)} 条相关条文；仅指出适用规则与差异候选，不构成法律结论。"
        else:
            summary = "法规建议未覆盖：本次检索未返回可引用条文，需人工复核。"
        for phrase in _FORBIDDEN:
            if phrase in summary:  # defensive: a future edit cannot reintroduce the forbidden claim
                summary = summary.replace(phrase, "未覆盖")
        coverage = _coverage(state=state, mode=mode, retrieved=retrieved, corpus=corpus)
        legal = {
            "input_mode": mode,
            "applicable_rules": _applicable_rules(retrieved, corpus),
            "claims": claims,
            "coverage": coverage,
            "escalate_to_human": bool(coverage["unavailable"] or coverage["business_type_uncertain"]),
            "summary": summary,
        }
        return AnswerResult(
            legal=legal,
            trail_entries=[
                {
                    "op": "pass",
                    "before": None,
                    "after": f"claims={len(claims)}",
                    "ref": None,
                    "model": "extractive",
                    "prompt_hash": None,
                    "detail": {
                        "answerer": "extractive",
                        "claim_count": len(claims),
                        "chunk_count": len(retrieved),
                        "semantic_entailment": False,
                    },
                }
            ],
            model_calls=0,
        )


class ChatError(RuntimeError):
    """The optional answer model could not be reached or returned unusable text."""


class OpenAIChat:
    """Small OpenAI-compatible chat client (stdlib only)."""

    def __init__(
        self,
        base: str,
        model: str,
        api_key: str = "",
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 120.0,
    ):
        self.base = base.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def __call__(self, messages: list[dict[str, str]]) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(
            f"{self.base}/chat/completions", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return str(payload["choices"][0]["message"]["content"] or "")
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ChatError(f"chat request failed: {type(exc).__name__}: {exc}") from exc


def _sanitize_summary(summary: str) -> str:
    return _sanitize_text(summary)


def _sanitize_text(value: str) -> str:
    """Remove legal conclusions from model output (spec: point out issues, never decide)."""
    cleaned = value.strip()
    for phrase, replacement in _CONCLUSION_REPLACEMENTS:
        cleaned = cleaned.replace(phrase, replacement)
    return cleaned


def _parse_json_object(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ChatError("model response is not a JSON object")
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ChatError(f"model response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ChatError("model response is not a JSON object")
    return payload


def _prompt(queries: list[str], chunks: list[dict], max_context_chunks: int) -> list[dict[str, str]]:
    blocks = []
    for chunk in chunks[:max_context_chunks]:
        cid = chunk.get("chunk_id")
        source = chunk.get("source_doc") or chunk.get("title") or ""
        articles = ", ".join(str(item) for item in (chunk.get("articles") or []))
        text = str(chunk.get("text") or "")[:3000]
        blocks.append(f"[{cid}] ({source} / {articles})\n{text}")
    system = (
        "你是贸易融资法规检索助手。只允许逐字引用用户给出的条文，不得改写、概括或补充法条。"
        "输出严格 JSON：{\"claims\":[{\"text\":\"条文原文连续片段\",\"chunk_id\":\"...\","
        "\"kind\":\"applicable_rule|condition|risk\"}],\"summary\":\"...\"}。"
        "chunk_id 必须逐字来自条文列表。找不到可引用条文时 claims 为空，summary 写"
        "“法规建议未覆盖：本次检索未返回可引用条文，需人工复核。”。"
        "禁止输出“合规/不合规”“可做/不可做”或任何法律定性。"
    )
    user = (
        "问题/检索式：\n"
        + "\n".join(f"- {query}" for query in queries)
        + "\n\n可用条文：\n\n"
        + "\n\n---\n\n".join(blocks)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


class LLMAnswerer:
    """Optional provider-backed answerer. The default remains extractive.

    The model only selects verbatim source spans and cites a this-retrieval `chunk_id`; every claim
    still passes `cite_check`. If the provider fails, the extractive answerer runs instead and the
    trail records why.
    """

    def __init__(
        self,
        chat,
        *,
        model: str = "llm",
        max_context_chunks: int = 12,
        fallback: Answerer | None = None,
    ):
        if chat is None:
            raise NotImplementedError("LLMAnswerer needs a chat callable")
        self.chat = chat
        self.model = model
        self.max_context_chunks = max_context_chunks
        self.fallback = fallback or ExtractiveAnswerer()

    def answer(
        self,
        *,
        state: dict,
        mode: Mode,
        retrieved: list[dict],
        corpus: dict,
    ) -> AnswerResult:
        queries, _ = build_query(state, mode)
        messages = _prompt(queries, retrieved, self.max_context_chunks)
        prompt_hash = hashlib.sha256(
            "\n".join(message["content"] for message in messages).encode("utf-8")
        ).hexdigest()[:16]
        try:
            raw = self.chat(messages)
            payload = _parse_json_object(raw)
        except Exception as exc:
            fallback = self.fallback.answer(
                state=state, mode=mode, retrieved=retrieved, corpus=corpus
            )
            fallback.trail_entries.append(
                {
                    "op": "pass",
                    "before": None,
                    "after": "extractive_fallback",
                    "ref": None,
                    "model": self.model,
                    "prompt_hash": prompt_hash,
                    "detail": {
                        "reason": f"llm_failed: {type(exc).__name__}: {exc}",
                        "answerer": "llm",
                    },
                }
            )
            fallback.model_calls = 1
            return fallback

        by_id = {str(chunk.get("chunk_id")): chunk for chunk in retrieved}
        claims: list[dict] = []
        for item in payload.get("claims") or []:
            if not isinstance(item, dict):
                continue
            text = _sanitize_text(str(item.get("text") or ""))
            if not text:
                continue
            cid = item.get("chunk_id")
            cid = str(cid) if cid is not None and str(cid) in by_id else None
            kind = item.get("kind")
            claims.append(
                {
                    "text": text,
                    "chunk_id": cid,
                    "kind": kind if kind in {"applicable_rule", "risk", "condition"} else "applicable_rule",
                    "support": "supported" if cid is not None else "insufficient",
                }
            )

        summary = _sanitize_summary(str(payload.get("summary") or ""))
        if not summary:
            summary = (
                f"检索到 {len(retrieved)} 条相关条文；仅指出适用规则与差异候选，不构成法律结论。"
                if retrieved
                else "法规建议未覆盖：本次检索未返回可引用条文，需人工复核。"
            )
        coverage = _coverage(state=state, mode=mode, retrieved=retrieved, corpus=corpus)
        legal = {
            "input_mode": mode,
            "applicable_rules": _applicable_rules(retrieved, corpus),
            "claims": claims,
            "coverage": coverage,
            "escalate_to_human": bool(coverage["unavailable"] or coverage["business_type_uncertain"]),
            "summary": summary,
        }
        return AnswerResult(
            legal=legal,
            trail_entries=[
                {
                    "op": "llm_call",
                    "before": None,
                    "after": f"claims={len(claims)}",
                    "ref": None,
                    "model": self.model,
                    "prompt_hash": prompt_hash,
                    "detail": {
                        "answerer": "llm",
                        "claim_count": len(claims),
                        "chunk_count": len(retrieved),
                        "semantic_entailment": False,
                    },
                }
            ],
            model_calls=1,
        )


def resolve_answerer(env: dict[str, str] | None = None) -> Answerer:
    """`extractive` by default; `llm` wires the configured OpenAI-compatible chat endpoint."""
    values = os.environ if env is None else env
    choice = (values.get("SMART_EDIT_ANSWERER") or "extractive").strip().lower()
    if choice in {"", "extractive", "deterministic", "none"}:
        return ExtractiveAnswerer()
    if not (choice == "llm" or choice.startswith("openai:")):
        return ExtractiveAnswerer()

    model = (
        choice.split(":", 1)[1]
        if choice.startswith("openai:")
        else (values.get("SMART_EDIT_ANSWER_MODEL") or values.get("SMART_EDIT_LLM_MODEL") or "")
    )
    model = model.strip() or "local-wb/cn:deepseek-v4.1-flash"
    base = (
        values.get("SMART_EDIT_ANSWER_BASE")
        or values.get("SMART_EDIT_LLM_BASE")
        or "http://localhost:3425/v1"
    ).strip()
    api_key = (
        values.get("SMART_EDIT_ANSWER_API_KEY") or values.get("SMART_EDIT_LLM_API_KEY") or ""
    ).strip()
    return LLMAnswerer(OpenAIChat(base, model, api_key), model=model)


__all__ = [
    "Answerer",
    "AnswerResult",
    "ExtractiveAnswerer",
    "LLMAnswerer",
    "OpenAIChat",
    "resolve_answerer",
]
