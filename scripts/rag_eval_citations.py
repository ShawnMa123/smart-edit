"""DEPRECATED — replaced by `scripts/rag_eval_agent3.py`.

This script judges `/v1/chat` citations, which are the remote service's generated
output and not on Agent 3's execution path. Running it overwrites `eval/citations_50.csv`
with the wrong signal. Kept for provenance only; do not use for task 8.3/8.4 acceptance.

---
L3 citation-support eval (task 8.3 / 8.4): in-scope questions via /v1/chat.

Collects >= 50 citations, verifies each programmatically: (1) chunk_id must be in this
response's retrieved chunks; (2) the quote must be locatable in the cited chunk text.
Labels: supported / partial / unsupported. This is a pre-check, not a substitute for the
required human review.

    SMART_EDIT_RAG=http://... SMART_EDIT_RAG_TOKEN=... \
    .venv/Scripts/python.exe scripts/rag_eval_citations.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (os.environ.get("SMART_EDIT_RAG") or "").strip()
TOKEN = (os.environ.get("SMART_EDIT_RAG_TOKEN") or "").strip() or None
TARGET = 50
OUT_CSV = ROOT / "eval" / "citations_50.csv"
OUT_MD = ROOT / "eval" / "citations_report.md"

QUESTIONS = [
    "进口货物的完税价格由哪些项目组成？",
    "办理海关事务担保应当提交哪些材料？",
    "哪些情形下人民法院应认定当事人开立的独立保函？",
    "WTO反倾销协定下反倾销调查应如何发起？",
    "中国反倾销调查的立案条件和程序是什么？",
    "CISG下卖方交付的货物不符合同，买方应在多长时间内通知？",
    "CISG对损害赔偿额如何计算？",
    "美国海关对进口货物完税价格的估价方法有哪些？",
    "日本关税定率法对关税估价是如何规定的？",
    "WTO贸易便利化协定对预裁定有什么要求？",
    "非优惠原产地规则下如何判定货物的原产国？",
    "中国两用物项出口管制如何管理管制清单？",
    "OFAC经济制裁的资产冻结（SDN名单）如何执行？",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def chat(question: str) -> dict:
    body = json.dumps({"question": question, "top_k": 5}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{BASE}/v1/chat", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    if not BASE:
        print("set SMART_EDIT_RAG (and SMART_EDIT_RAG_TOKEN) first")
        return 2
    rows = []
    for question in QUESTIONS:
        if len(rows) >= TARGET:
            break
        payload = chat(question)
        chunks = {c.get("chunk_id"): c for c in payload.get("chunks") or []}
        status = payload.get("answer_status")
        citations = payload.get("citations") or []
        print(f"[{status}] {question} -> {len(citations)} citations")
        for citation in citations:
            chunk_id = citation.get("chunk_id")
            chunk = chunks.get(chunk_id)
            quote = _norm(citation.get("quote") or "")
            chunk_text = _norm(chunk.get("text") or "") if chunk else ""
            if chunk is None:
                label, detail = "unsupported", "chunk_id not in retrieved chunks"
            elif quote and quote in chunk_text:
                label, detail = "supported", "quote found verbatim"
            elif quote and quote[:40] in chunk_text:
                label, detail = "partial", "quote prefix found (fragment)"
            else:
                label, detail = "unsupported", "quote not found in cited chunk"
            rows.append({
                "question": question,
                "answer_status": status,
                "chunk_id": chunk_id,
                "article_id": citation.get("article_id"),
                "source_doc": citation.get("source_doc"),
                "label": label,
                "check": detail,
                "quote": (citation.get("quote") or "")[:120],
            })
    total = len(rows)
    supported = sum(1 for r in rows if r["label"] == "supported")
    partial = sum(1 for r in rows if r["label"] == "partial")
    unsupported = total - supported - partial
    support_rate = supported / total if total else 0.0
    partial_rate = partial / total if total else 0.0
    print(f"total={total} supported={supported} partial={partial} unsupported={unsupported}")
    print(f"citation_support_rate={support_rate:.3f} partial_support_rate={partial_rate:.3f}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    report = [
        "# L3 引用支持评测（任务 8.3 / 8.4）",
        "",
        f"- 样本：{len(QUESTIONS)} 个域内问题，`/v1/chat`，共 {total} 条 citation",
        f"- **citation_support_rate = {support_rate:.3f}** ｜ **partial_support_rate = {partial_rate:.3f}** ｜ unsupported = {unsupported}",
        "",
        "核验方法（程序化预检，人工复核仍必需）：",
        "1. chunk_id 必须出现在本次响应的 chunks 中（防编造 id）",
        "2. quote 归一空白后须能在被引 chunk 原文中定位（supported=逐字命中；partial=前缀命中/截断）",
        "",
        "| 标签 | 条数 | 说明 |",
        "|---|---|---|",
        f"| supported | {supported} | quote 逐字出现在被引条文 |",
        f"| partial | {partial} | quote 为片段/被截断 |",
        f"| unsupported | {unsupported} | id 编造或 quote 无法定位 |",
        "",
        "- 明细见 `eval/citations_50.csv`（UTF-8 BOM，Excel 可直接开）",
        "- 本判定为程序初判：语义级「引用是否真的支持该结论」仍需人工抽检（建议 ≥10 条）",
    ]
    OUT_MD.write_text("\n".join(report), encoding="utf-8")
    print(f"-> {OUT_CSV} / {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
