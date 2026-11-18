"""DEPRECATED — service-side reference only, NOT an Agent 3 acceptance test.

This script probes `/v1/chat`, an endpoint Agent 3 never calls. Its `answer_status`
numbers are not the task 8.5 verdict. Use `scripts/rag_eval_agent3.py` instead
(see `eval/refusal_agent3.md`). Kept only to document the remote service behaviour
recorded in `eval/refusal_report.md`.

---
L3 refusal eval: 10 out-of-scope questions (task 8.5).

Out-of-scope = topics with no corresponding law in the corpus. Verified against
/v1/corpus/documents: all 143 docs are trade / customs / export-control / sanctions / CISG;
none covers the domains below.

Refusal = `answer_status` is "unsupported" or "unavailable" (no supporting citation — the
service must decline instead of fabricating). Target: refusal_rate >= 0.9.

Usage:
    SMART_EDIT_RAG=http://59.110.213.187:8080 \
    SMART_EDIT_RAG_TOKEN=<token> \
    .venv/Scripts/python.exe scripts/rag_eval_refusal.py
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BASE = (os.environ.get("SMART_EDIT_RAG") or "").strip()
TOKEN = (os.environ.get("SMART_EDIT_RAG_TOKEN") or "").strip() or None
OUT = ROOT / "eval" / "refusal_report.md"

QUESTIONS = [
    "个人所得税的专项附加扣除有哪些？",
    "离婚时夫妻共同财产应当如何分割？",
    "交通事故人身损害赔偿的项目和计算标准是什么？",
    "发明专利侵权诉讼的法定赔偿数额如何确定？",
    "食品安全法对生产经营者的罚款起罚标准是什么？",
    "用人单位违法解除劳动合同的经济赔偿金如何计算？",
    "环保部门对企业超标排污的按日连续处罚如何适用？",
    "医疗损害责任纠纷中医疗机构的举证责任是什么？",
    "商品房买卖合同纠纷中买受人可以退房的条件有哪些？",
    "公司注册资本认缴制下股东出资加速到期的条件是什么？",
]

REFUSAL_STATUS = {"unsupported", "unavailable"}
HEDGES = ("未找到", "无相关", "无法", "不涉及", "没有找到", "未检索到")


def chat(question: str) -> dict:
    body = json.dumps({"question": question, "top_k": 5}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{BASE}/v1/chat", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    if not BASE:
        print("set SMART_EDIT_RAG (and SMART_EDIT_RAG_TOKEN) first")
        return 2

    rows = []
    refusals = 0
    for index, question in enumerate(QUESTIONS, start=1):
        payload = chat(question)
        status = str(payload.get("answer_status") or "unknown")
        answer = str(payload.get("answer") or "")
        hedged = any(word in answer for word in HEDGES)
        cited = len(payload.get("citations") or [])
        is_refusal = status in REFUSAL_STATUS
        if is_refusal:
            refusals += 1
        rows.append(
            {
                "q": question,
                "answer_status": status,
                "citations": cited,
                "answer_hedged": hedged,
                "refusal": is_refusal,
            }
        )
        print(
            f"[{index:02d}] {status:<12} citations={cited} hedged={hedged} "
            f"refusal={is_refusal} :: {question}"
        )

    rate = refusals / len(QUESTIONS)
    verdict = "PASS (>= 0.9)" if rate >= 0.9 else "FAIL (< 0.9)"
    print()
    print(f"refusal_rate = {rate:.2f}  {verdict}")

    report = [
        "# L3 拒答评测（10 个超纲问题 · 任务 8.5）",
        "",
        f"- 服务：`{BASE}` 的 `/v1/chat`（带鉴权，answer 生成开启）",
        "- 拒答定义：`answer_status in (unsupported, unavailable)`——依据不足时必须拒绝作答，不得编造",
        f"- 结果：**refusal_rate = {rate:.2f}** → {verdict}",
        "",
        "| # | 问题 | answer_status | citations | 回答含拒绝措辞 | 判为拒答 |",
        "|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        report.append(
            f"| {index} | {row['q']} | {row['answer_status']} | {row['citations']} "
            f"| {row['answer_hedged']} | {row['refusal']} |"
        )
    report += [
        "",
        "## 限制声明",
        "- 超纲题按语料清单人工核对（143 部均为贸易/海关/出口管制/制裁领域，不含所问领域）",
        "- answer_status 由服务端判定（基于 citations 支持度）；本脚本只统计，不复判语义",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(report), encoding="utf-8")
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
