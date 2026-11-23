"""Call Mercatoria's `/v1/chat` directly (retrieval + optional generation with citations).

The assistant also uses `/v1/chat`, but as a two-stage flow: the chat draft is handed to Doubao for
structuring/polish and then reviewed by the service. This script bypasses that: it calls the corpus
service directly and prints its own answer/citations, which is useful for comparison and debugging.

Usage:
    .venv/bin/python scripts/mercatoria_chat.py "在wto里，什么是guarantee"
    .venv/bin/python scripts/mercatoria_chat.py "独立保函的定义是什么" --json
    .venv/bin/python scripts/mercatoria_chat.py "URDG 758 第20条" --no-answer --top-k 3
    .venv/bin/python scripts/mercatoria_chat.py "guarantee" --jurisdiction WTO --as-of 2026-01-01

Reads MERCATORIA_BASE_URL / MERCATORIA_API_TOKEN from the environment, falling back to `.env`.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def _load_env_file(path: Path) -> None:
    """Fill only missing variables, so an exported shell value still wins."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_body(args: argparse.Namespace) -> dict[str, Any]:
    body: dict[str, Any] = {"question": args.question, "top_k": args.top_k}
    if args.retrieval_query:
        body["retrieval_query"] = args.retrieval_query
    if args.no_rewrite:
        body["rewrite_query"] = False
    if args.no_answer:
        body["answer"] = {"enabled": False}
    filters: dict[str, Any] = {}
    if args.jurisdiction:
        filters["jurisdictions"] = args.jurisdiction
    if args.as_of:
        filters["as_of"] = args.as_of
    if filters:
        body["filters"] = filters
    if args.messages:
        body["messages"] = [
            {"role": role, "content": content}
            for role, _, content in (item.partition("=") for item in args.messages)
            if role in ("user", "assistant") and content
        ]
    return body


def render(data: dict[str, Any]) -> None:
    print("answer_status:", data.get("answer_status"))
    if data.get("answer"):
        print("\nanswer:\n" + str(data["answer"]))
    print("\nretrieval_query:", data.get("retrieval_query"))
    print("coverage:", json.dumps(data.get("coverage") or {}, ensure_ascii=False))
    print("diagnostics:", json.dumps(
        {k: (data.get("diagnostics") or {}).get(k) for k in ("confidence", "zero_reason", "degraded")},
        ensure_ascii=False,
    ))
    references = data.get("references") or []
    print(f"\nreferences ({len(references)}):")
    for ref in references:
        print(
            f"  - {ref.get('doc_id')} | {ref.get('article_label')} | {ref.get('jurisdiction')} | "
            f"score={ref.get('score')} | cited={ref.get('cited')}"
        )
    citations = data.get("citations") or []
    print(f"\ncitations ({len(citations)}):")
    for citation in citations:
        print(
            f"  - {citation.get('doc_id')} | {citation.get('article_label')} | "
            f"chunk={citation.get('chunk_id')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Call Mercatoria POST /v1/chat")
    parser.add_argument("question")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--token", default=None, help="prefer MERCATORIA_API_TOKEN / .env")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--jurisdiction", action="append", default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--retrieval-query", default=None)
    parser.add_argument("--no-rewrite", action="store_true")
    parser.add_argument("--no-answer", action="store_true", help="retrieval only")
    parser.add_argument(
        "--messages",
        action="append",
        default=None,
        metavar="ROLE=TEXT",
        help="prior turn, e.g. --messages 'user=上一问' --messages 'assistant=上一答'",
    )
    parser.add_argument("--json", action="store_true", help="print the raw response")
    args = parser.parse_args()

    _load_env_file(ENV_FILE)
    base = (args.base_url or os.environ.get("MERCATORIA_BASE_URL") or "").rstrip("/")
    token = (args.token or os.environ.get("MERCATORIA_API_TOKEN") or "").strip()
    if not base or not token:
        print("MERCATORIA_BASE_URL and MERCATORIA_API_TOKEN are required (env or .env)")
        return 2

    try:
        response = httpx.post(
            f"{base}/v1/chat",
            json=build_body(args),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=90.0,
        )
    except httpx.HTTPError as exc:
        print(f"request failed: {type(exc).__name__}")
        return 1

    if response.status_code != 200:
        print(f"HTTP {response.status_code}: {response.text[:500]}")
        return 1
    data = response.json()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        render(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())