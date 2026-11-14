"""Reproducible synthetic evaluation for the A slice (task 6.4).

The report measures exactly what A can measure: lexical citation hit, outcome correctness and
clarification correctness. It does **not** measure embedding recall, reranking or model quality —
those do not exist in A and the report says so instead of implying otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.assistant.ports import Principal
from app.assistant.schemas import RunCreate, SessionCreate
from app.assistant.service import AssistantService

EVAL_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "assistant" / "eval_questions.json"
)
WORKSPACE = "ws_demo_01"
EVAL_USER = "user_eval"

NOTES = (
    "词法检索（英文 casefold + 中文 n-gram），未使用向量/重排/真实模型；"
    "引用命中只统计被引用的 fixture chunk，弃答/澄清正确率按 outcome 比较。"
)


def load_cases(path: str | Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads(Path(path or EVAL_FIXTURE).read_text(encoding="utf-8"))
    return list(payload["questions"])


def run_eval(
    service: AssistantService, *, cases: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    principal = Principal(user_id=EVAL_USER, workspace_id=WORKSPACE)
    rows: list[dict[str, Any]] = []
    for case in cases or load_cases():
        session = service.create_session(
            principal,
            SessionCreate(workspace_id=WORKSPACE, locale="zh-CN"),
            f"eval-session-{case['id']}",
            f"eval-req-{case['id']}",
        )
        accepted = service.create_run(
            principal,
            session.id,
            RunCreate(question=case["question"]),
            f"eval-run-{case['id']}",
            f"eval-req-{case['id']}",
        )
        service.execute_run(accepted.id)
        run = service.get_run(principal, accepted.id)
        outcome = run.result.outcome if run.result else "failed"
        chunk_ids: list[str] = []
        if run.assistant_message_id:
            chunk_ids = [
                citation["chunk_id"]
                for citation in service.store.list_citations(run.assistant_message_id)
                if citation.get("chunk_id")
            ]
        expected_chunk = case.get("expected_chunk")
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "outcome": outcome,
                "expected_outcome": case["expected_outcome"],
                "outcome_ok": outcome == case["expected_outcome"],
                "citation_chunk_ids": chunk_ids,
                "expected_chunk": expected_chunk,
                "citation_hit": expected_chunk is None or expected_chunk in chunk_ids,
            }
        )

    total = len(rows) or 1
    answered = [row for row in rows if row["expected_outcome"] != "needs_clarification"]
    clarification = [row for row in rows if row["expected_outcome"] == "needs_clarification"]
    return {
        "total": len(rows),
        "outcome_accuracy": round(sum(row["outcome_ok"] for row in rows) / total, 3),
        "citation_hit_rate": round(sum(row["citation_hit"] for row in rows) / total, 3),
        "answered_total": len(answered),
        "answered_citation_hit_rate": round(
            sum(row["citation_hit"] for row in answered) / (len(answered) or 1), 3
        ),
        "clarification_total": len(clarification),
        "clarification_accuracy": round(
            sum(row["outcome_ok"] for row in clarification) / (len(clarification) or 1), 3
        ),
        "notes": NOTES,
        "cases": rows,
    }


__all__ = ["EVAL_FIXTURE", "load_cases", "run_eval"]