"""L3 eval against Agent 3's REAL output (task 8.3 / 8.4 / 8.5).

Calls `regulatory_node` in-process: real remote `/retrieve` + local `ExtractiveAnswerer`
+ `cite_check` + coverage. No `/v1/chat` — that endpoint is not on Agent 3's path.

Produces:
  eval/citations_50.csv        50 claim-level judgments from legal.claims
  eval/citations_report.md     support rates
  eval/refusal_agent3.md       10 out-of-scope docs -> coverage / escalate verdicts

    SMART_EDIT_RAG=http://... SMART_EDIT_RAG_TOKEN=... \
    .venv/Scripts/python.exe scripts/rag_eval_agent3.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.regulatory.node import regulatory_node  # noqa: E402
from tests.helpers import make_doc  # noqa: E402

OUT_CSV = ROOT / "eval" / "citations_50.csv"
# Machine-generated numbers go to *_metrics.md. The human analysis files
# (citations_report.md / refusal_agent3.md) are intentionally NEVER overwritten —
# `eval/run_eval.py` calls this script on every re-run.
OUT_CITE = ROOT / "eval" / "citations_metrics.md"
OUT_REFUSAL = ROOT / "eval" / "refusal_metrics.md"

IN_SCOPE_DOCS = [
    "进口货物的完税价格由哪些项目组成？海关审定完税价格规定",
    "办理海关事务担保应当提交书面申请及财产权利凭证",
    "独立保函载明见索即付，适用URDG758统一惯例",
    "反倾销调查立案申请与损害证据审查程序",
    "CISG国际货物销售合同货物不符的通知期限与损害赔偿",
    "美国海关完税价格估价方法与成交价格审查",
    "WTO贸易便利化协定预裁定与进口许可程序透明度",
    "非优惠原产地规则判定货物原产国标准",
    "两用物项出口管制清单与出口许可证管理",
    "OFAC制裁名单资产冻结与出口管制许可例外",
    "海关行政处罚与关税征收程序规定",
    "WTO保障措施与反倾销协定条款适用",
]

OUT_OF_SCOPE_DOCS = [
    "个人所得税专项附加扣除的适用范围与标准",
    "离婚时夫妻共同财产分割的认定与比例",
    "交通事故人身损害赔偿项目和计算标准",
    "发明专利侵权诉讼法定赔偿数额的确定",
    "食品安全法对生产经营者的罚款起罚标准",
    "用人单位违法解除劳动合同经济赔偿金计算",
    "环保部门对企业超标排污按日连续处罚的适用",
    "医疗损害责任纠纷中医疗机构举证责任",
    "商品房买卖合同纠纷买受人退房条件",
    "公司注册资本认缴制下股东出资加速到期条件",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def run_node(text: str) -> dict:
    if not os.environ.get("SMART_EDIT_RAG"):
        raise RuntimeError("set SMART_EDIT_RAG / SMART_EDIT_RAG_TOKEN first")
    state = {"docs": [make_doc(text)], "findings": [], "trail": [], "stages": []}
    return regulatory_node(state)


def claim_rows() -> list[dict]:
    rows: list[dict] = []
    for index, text in enumerate(IN_SCOPE_DOCS, start=1):
        update = run_node(text)
        legal = update.get("legal") or {}
        retrieved = update.get("retrieved") or []
        claims = legal.get("claims") or []
        by_id = {c.get("chunk_id"): c for c in retrieved}
        stage = (update.get("stages") or [{}])[0]
        print(f"[in-scope {index:02d}] stage={stage.get('status')} chunks={len(retrieved)} claims={len(claims)}")
        for claim in claims:
            chunk_id = claim.get("chunk_id")
            chunk = by_id.get(chunk_id)
            quote = _norm(claim.get("text") or claim.get("quote") or "")
            chunk_text = _norm(chunk.get("text") or "") if chunk else ""
            if chunk is None:
                label, detail = "unsupported", "chunk_id not in retrieved"
            elif quote and quote in chunk_text:
                label, detail = "supported", "claim text found verbatim in cited chunk"
            elif quote[:40] and quote[:40] in chunk_text:
                label, detail = "partial", "claim prefix found (fragment)"
            else:
                label, detail = "unsupported", "claim text not found in cited chunk"
            rows.append({
                "source": "agent3.legal.claims",
                "document": text,
                "claim_text": (claim.get("text") or "")[:120],
                "chunk_id": chunk_id,
                "support_field": claim.get("support"),
                "label": label,
                "check": detail,
            })
    return rows


def refusal_rows() -> list[dict]:
    rows = []
    for text in OUT_OF_SCOPE_DOCS:
        update = run_node(text)
        legal = update.get("legal") or {}
        coverage = legal.get("coverage") or {}
        stage = (update.get("stages") or [{}])[0]
        rows.append({
            "document": text,
            "stage": stage.get("status"),
            "coverage_unavailable": coverage.get("unavailable"),
            "business_type_uncertain": coverage.get("business_type_uncertain"),
            "escalate_to_human": legal.get("escalate_to_human"),
            "notes": " | ".join(coverage.get("notes") or []),
            "chunks": len(update.get("retrieved") or []),
            "claims": len(legal.get("claims") or []),
        })
        r = rows[-1]
        print(
            f"[out-scope] unavailable={r['coverage_unavailable']} escalate={r['escalate_to_human']} "
            f"chunks={r['chunks']} claims={r['claims']} :: {text[:24]}"
        )
    return rows


def main() -> int:
    rows = claim_rows()[:50]
    total = len(rows)
    supported = sum(1 for r in rows if r["label"] == "supported")
    partial = sum(1 for r in rows if r["label"] == "partial")
    unsupported = total - supported - partial
    print(f"\nclaims collected: {total} (target 50)")

    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    cite_report = [
        "# L3 引用支持评测（Agent 3 真实输出 · 任务 8.3 / 8.4）",
        "",
        "- **信号源**：`regulatory_node()` 的 `legal.claims`（本地 `ExtractiveAnswerer` + `cite_check`），不是 `/v1/chat`",
        "- 检索后端：远程 `/retrieve`（生产 `HttpRetriever`，鉴权含在内）",
        f"- 样本：{len(IN_SCOPE_DOCS)} 份域内文本，取前 {total} 条 claim",
        f"- **citation_support_rate = {supported / total:.3f}** ｜ **partial_support_rate = {partial / total:.3f}** ｜ unsupported = {unsupported}",
        "",
        "核验：claim 的 `chunk_id` 必须在本次 `retrieved` 中，且 claim 文本能在被引 chunk 原文定位。",
        "程序初判不能替代 spec 要求的人工语义判定——`eval/report.md` §5 仍列出人工抽检区。",
        "",
        "| 标签 | 条数 |",
        "|---|---|",
        f"| supported | {supported} |",
        f"| partial | {partial} |",
        f"| unsupported | {unsupported} |",
        "",
        "明细：`eval/citations_50.csv`（UTF-8 BOM）。双口径正式结论见 `eval/citations_report.md`（人工分析，本脚本不覆盖）。",
    ]
    OUT_CITE.write_text("\n".join(cite_report), encoding="utf-8")

    refusals = refusal_rows()
    unavailable = sum(1 for r in refusals if r["coverage_unavailable"])
    escalated = sum(1 for r in refusals if r["escalate_to_human"])
    n = len(refusals)
    lines = [
        "# L3 拒答评测（Agent 3 真实输出 · 任务 8.5）",
        "",
        "- **信号源**：`regulatory_node()` 的 `legal.coverage` / `escalate_to_human`，不是 `/v1/chat` 的 answer_status",
        f"- 10 份超纲文本 → `coverage.unavailable=true` 的有 **{unavailable}/{n}**；`escalate_to_human=true` 的有 **{escalated}/{n}**",
        "",
        "| # | 文本 | stage | unavailable | escalate | chunks | claims | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for index, r in enumerate(refusals, start=1):
        lines.append(
            f"| {index} | {r['document']} | {r['stage']} | {r['coverage_unavailable']} "
            f"| {r['escalate_to_human']} | {r['chunks']} | {r['claims']} | {r['notes']} |"
        )
    lines += [
        "",
        "## spec 口径结论",
        f"- spec.md:155 要求检查 `coverage.unavailable` → 实测 **{unavailable}/{n}**（覆盖率 {unavailable / n:.2f}）",
        f"- 原因：`answer.py:122` 的 `unavailable = not retrieved`，而远程 BM25 对超纲文本仍返回 {refusals[0]['chunks']} 条无关 chunk",
        f"- 替代诚实信号：`escalate_to_human` **{escalated}/{n}** + coverage.notes 声明缺口",
        "- **登记为 spec 判据与实现不匹配的偏离**，待 owner 定夺；不得用 `/v1/chat` 结果冒充本项验收",
        "",
        "原始数据见 `eval/refusal_agent3.json`。",
    ]
    OUT_REFUSAL.write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "eval" / "refusal_agent3.json").write_text(
        json.dumps(refusals, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n-> {OUT_CSV}\n-> {OUT_CITE}\n-> {OUT_REFUSAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

