"""Offline statute-decision evaluation (knowledge-statute-retrieval tasks 7.1 / 7.2).

No network and no model: each fixture case is a *recorded* response shape from the legal-corpus
service, and this report measures the availability judge plus how often a statute-backed answer is
even possible. That keeps the numbers reproducible offline and separate from the 33-question
synthetic baseline (`scripts/assistant_eval.py`), which measures the local corpus instead.

Usage:
    .venv/bin/python scripts/statute_eval.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.assistant.statute import StatuteRetriever

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "assistant" / "statute_eval.json"

NOTES = (
    "决定层评测：每个用例是法规服务响应的录制形状，离线重放可用性判定；"
    "不调用法规服务、不调用模型。statute_citation_rate = 能给出法规引用的用例占比。"
)


def _payload(case: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the service response shape this case stands for."""
    text = case.get("text")
    chunks: list[dict[str, Any]] = []
    if text:
        matched = str(case.get("matched") or "")
        start = text.find(matched) if matched else -1
        doc_id = case.get("doc_id", defaults["doc_id"])
        chunks.append(
            {
                "chunk_id": f"chunk_{case['id']}",
                "doc_id": doc_id,
                "source_doc": case.get("source_doc", defaults["source_doc"]),
                "text": text,
                "score": float(case.get("score") or 0.0),
                "articles": [case.get("article_label", defaults["article_label"])],
                "article_ids": [f"{doc_id}:{case['id']}"],
                "jurisdictions": [case.get("jurisdiction", defaults["jurisdiction"])],
                "effective_from": case.get("effective_from", defaults["effective_from"]),
                "effective_to": None,
                "superseded_by": case.get("superseded_by"),
                "matched_terms": (
                    [{"term": matched, "start": start, "end": start + len(matched)}]
                    if start >= 0
                    else []
                ),
            }
        )
    reason = str(case["expected_reason"])
    zero_reason = reason[len("zero:") :] if reason.startswith("zero:") else None
    jurisdiction = case.get("jurisdiction", defaults["jurisdiction"])
    return {
        "chunks": chunks,
        "diagnostics": {
            "confidence": case.get("confidence", "high"),
            "zero_reason": zero_reason,
            "degraded": list(case.get("degraded") or []),
        },
        "corpus": {"precision": {jurisdiction: case.get("precision", defaults["precision"])}},
        "field_matches": {"requested_uncovered": case.get("uncovered") or {}},
    }


def run(path: str | Path | None = None) -> dict[str, Any]:
    data = json.loads(Path(path or FIXTURE).read_text(encoding="utf-8"))
    defaults = data.get("defaults") or {}
    judge = StatuteRetriever(base_url="http://offline.invalid", api_token="offline")

    rows: list[dict[str, Any]] = []
    for case in data["cases"]:
        terms = {case["matched"]} if case.get("matched") else set()
        outcome = judge.judge(_payload(case, defaults), terms=terms)
        rows.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "question": case["question"],
                "expected_reason": case["expected_reason"],
                "actual_reason": outcome.reason,
                "reason_ok": outcome.reason == case["expected_reason"],
                "statute_backed": outcome.usable,
                "status": outcome.status,
                "citations": len(outcome.candidates),
            }
        )

    total = len(rows) or 1
    unusable = [row["actual_reason"] for row in rows if not row["statute_backed"]]
    return {
        "cases": len(rows),
        "reason_accuracy": round(sum(1 for row in rows if row["reason_ok"]) / total, 3),
        "statute_citation_rate": round(sum(1 for row in rows if row["statute_backed"]) / total, 3),
        "reasons": dict(sorted(Counter(row["actual_reason"] for row in rows).items())),
        "unusable_reasons": dict(sorted(Counter(unusable).items())),
        "notes": NOTES,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline statute-decision evaluation")
    parser.add_argument("--fixture", default=None, help="path to statute_eval.json")
    args = parser.parse_args()

    report = run(args.fixture)
    summary = {key: value for key, value in report.items() if key != "rows"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for row in report["rows"]:
        mark = "ok  " if row["reason_ok"] else "MISS"
        print(
            f"{row['id']} {mark} kind={row['kind']:<14} expected={row['expected_reason']:<18} "
            f"actual={row['actual_reason']:<18} citations={row['citations']}"
        )
    return 0 if report["reason_accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())