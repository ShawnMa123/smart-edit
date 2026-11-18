"""Record Doubao's independent L3 review and cross-check against our labels.

Doubao judged TOPIC relevance (claim vs input document); our program judged
LOCATABILITY (claim text verbatim inside the cited chunk). They are different
questions — this script makes the divergence explicit instead of hiding it.

    .venv/Scripts/python.exe eval/doubao_review.py
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "eval" / "citations_50.csv"
OUT_CMP = ROOT / "eval" / "doubao_comparison.csv"
OUT_MD = ROOT / "eval" / "doubao_review.md"

# Doubao task B verdicts, rows 1-50
VERDICTS = [
    "supported", "unsupported", "unsupported", "unsupported", "supported",
    "unsupported", "unsupported", "unsupported", "unsupported", "supported",
    "unsupported", "supported", "supported", "supported", "unsupported",
    "unsupported", "unsupported", "unsupported", "unsupported", "unsupported",
    "unsupported", "unsupported", "unsupported", "unsupported", "unsupported",
    "unsupported", "unsupported", "unsupported", "unsupported", "unsupported",
    "partial", "unsupported", "unsupported", "unsupported", "unsupported",
    "unsupported", "unsupported", "unsupported", "unsupported", "unsupported",
    "unsupported", "unsupported", "unsupported", "unsupported", "unsupported",
    "unsupported", "unsupported", "unsupported", "unsupported", "unsupported",
]

with CSV.open(encoding="utf-8-sig", newline="") as handle:
    rows = list(csv.DictReader(handle))

lines = [
    "# 豆包独立复核结果（2026-11-19）",
    "",
    "复核材料：`eval/for_doubao.txt`（不含任何既有结论与标签）。豆包遵守约束，",
    "任务 A 第 15 题主动标 UNDECIDED，任务 C 全判「是」，未输出综合分数。",
    "",
    "## 任务 A：gold 20 题",
    "",
    "- **19/20 与现有 gold 一致**（含 Q12/Q13 已修正的 doc_id 笔误，豆包也判一致）",
    "- **第 15 题 UNDECIDED**：题目「WTO保障措施的实施条件是什么？」明确限定 WTO，",
    "  但 gold 里还有 `cn-safeguard-2004`（中国国内保障措施）。豆包无法判断是否该包含国内法。",
    "- 实测该 gold 下检索返回 `['cn-safeguard-2004','wto-safeg']`，R@5=1.00 RR=1.00；",
    "  若把 gold 收窄为只 `wto-safeg`，RR 变为 0.50 → 全局 MRR 从 0.817 降为约 0.792。",
    "  **需 owner 终裁**：收窄 gold（题目限定 WTO，倾向收窄）还是放宽题目措辞。",
    "",
    "## 任务 B：50 条 claim —— 两个判据测的不是同一件事",
    "",
    "| 判据 | 谁在用 | 问的问题 | 结果 |",
    "|---|---|---|---|",
    "| 可定位性 | 我们的程序 | claim 文本能否逐字在被引 chunk 原文中找到 | 50/50 supported |",
    "| 主题相关性 | 豆包（prompt 指定） | claim 与输入文档是不是同一话题 | 6 supported / 1 partial / 43 unsupported |",
    "",
    "**不能直接说谁对谁错**：`ExtractiveAnswerer` 的 claim 本来就是从 chunk 逐字摘的，",
    "所以「逐字可定位」近乎结构性必然；而 spec §L3 的 `supported` 定义是「引用片段确实支持这句话」，",
    "更接近语义口径。**两个数字都要报，不能只留好看的那个。**",
    "",
    "豆包判定暴露的真实问题：43/50 条 claim 与输入文档主题无关（问完税价格却摘到",
    "「海关扣留期限」, 问 OFAC 却摘到「独立保函定义」）。这不是数据造假，是**远程检索对",
    "这些中文输入召回不准**，与 Recall@5 中「中文问美国法」2 个失败同源。",
    "",
    "## 任务 C：10 条超纲文本",
    "",
    "10/10 判定为超出语料覆盖范围，与我们的 `refusal_agent3.md` 前提一致。",
    "",
    "## 待 owner 终裁清单",
    "",
    "1. 任务 A 第 15 题 gold 口径（收窄 / 改题目 / 保持）",
    "2. 任务 B 采用哪个判据作为 `citation_support_rate` 的正式口径：",
    "   - 可定位性 1.000（程序） / 主题相关性 0.12（豆包：6/50）/ 还是补一轮按 spec 语义的人工判",
    "3. 43 条主题无关 claim 是否登记为**检索质量缺口**（影响 8.4 能否勾）",
    "",
    "逐条对照见 `eval/doubao_comparison.csv`。原 `eval/citations_50.csv` 的 label 未被改动。",
]

with OUT_CMP.open("w", newline="", encoding="utf-8-sig") as handle:
    writer = csv.writer(handle)
    writer.writerow(["row", "document", "claim_text", "our_label", "doubao_verdict", "divergent"])
    for index, (row, verdict) in enumerate(zip(rows, VERDICTS), start=1):
        writer.writerow([
            index, row["document"], row["claim_text"], row["label"], verdict,
            "YES" if row["label"] != verdict else "",
        ])

OUT_MD.write_text("\n".join(lines), encoding="utf-8")
print(f"doubao: supported={VERDICTS.count('supported')} partial={VERDICTS.count('partial')} unsupported={VERDICTS.count('unsupported')}")
print(f"divergent rows: {sum(1 for r, v in zip(rows, VERDICTS) if r['label'] != v)} / {len(rows)}")
print(f"-> {OUT_MD}\n-> {OUT_CMP}")
