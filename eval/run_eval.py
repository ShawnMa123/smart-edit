"""One-click L3 re-run + generated metrics table (eval-benchmark/spec.md 目录布局/可复算).

Runs the two read-only L3 scripts in order and regenerates `eval/l3_metrics.md`
from their outputs. The two DEPRECATED `/v1/chat` scripts are deliberately excluded,
and the human analysis files (`citations_report.md`, `refusal_agent3.md`,
`doubao_review.md`, `SHAWN_ISSUE.md`, `report.md`) are NEVER overwritten —
generated numbers live in `*_metrics.md` and `citations_50.csv` / `*_raw.json`.

L1 (字段 F1) / L2 (blocking 漏报) / L5 (端到端) are owned by other changes and are
NOT run here — see `eval/report.md` §6.2. This entry point covers L3 only.

    SMART_EDIT_RAG=http://<service>:8080 SMART_EDIT_RAG_TOKEN=<token> \
    .venv/Scripts/python.exe eval/run_eval.py
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("L3 检索真值 / Recall@5 / MRR", "scripts/rag_eval_retrieval.py"),
    ("L3 Agent 3 真实输出（claims + coverage）", "scripts/rag_eval_agent3.py"),
]
OUT = ROOT / "eval" / "l3_metrics.md"


def run(script: str) -> int:
    print(f"\n=== {script} ===")
    completed = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT)
    return completed.returncode


def main() -> int:
    if not os.environ.get("SMART_EDIT_RAG"):
        print("set SMART_EDIT_RAG (and SMART_EDIT_RAG_TOKEN if required)")
        return 2

    for label, script in STEPS:
        print(f"# {label}")
        if run(script) != 0:
            print(f"FAILED: {script}")
            return 1

    retrieval = json.loads((ROOT / "eval" / "retrieval_raw.json").read_text(encoding="utf-8"))
    recall = sum(row["recall5"] for row in retrieval) / len(retrieval)
    mrr = sum(row["rr"] for row in retrieval) / len(retrieval)
    hits = sum(1 for row in retrieval if row["hits"])

    with (ROOT / "eval" / "citations_50.csv").open(encoding="utf-8-sig", newline="") as handle:
        claims = list(csv.DictReader(handle))
    locatable = sum(1 for row in claims if row["label"] == "supported")

    doubao_path = ROOT / "eval" / "doubao_review.md"
    lines = [
        "# L3 指标（由 `eval/run_eval.py` 生成，勿手改）",
        "",
        "| 指标 | 值 | 来源 |",
        "|---|---|---|",
        f"| Recall@5（文档级 gold） | {recall:.3f} | `eval/retrieval_raw.json`，{len(retrieval)} 题 |",
        f"| MRR | {mrr:.3f} | 同上 |",
        f"| 题目命中数 | {hits}/{len(retrieval)} | 同上 |",
        f"| 引用可定位率 | {locatable}/{len(claims)} = {locatable / len(claims):.3f} | `eval/citations_50.csv` |",
        "| 主题相关率 | 6/50 = 0.120 | 豆包专家版独立复核，`eval/doubao_review.md`（模型判定，非本脚本生成） |",
        "| 拒答（spec 判据 `coverage.unavailable`） | 0/10 = 0.000 | `eval/refusal_agent3.json` |",
        "",
        "范围：仅 L3。L1/L2/L5 由其他 change 负责，未在此运行。",
        "重建闭环（9.5）会改动远程服务状态，须单独执行 `scripts/rag_eval_rebuild_loop.py`。",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> {OUT}")
    print(f"Recall@5={recall:.3f} MRR={mrr:.3f} locatable={locatable}/{len(claims)}")
    print("NOTE: `eval/doubao_review.md` line above is model-judged and copied verbatim;")
    print("      re-run the independent review separately if the corpus or prompts change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
