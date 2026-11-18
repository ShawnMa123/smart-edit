"""Build a single paste-ready text blob for Doubao (or any chat-window LLM) review.

Doubao cannot read local files, so it must receive the material inline. This script emits
`eval/for_doubao.txt`: a self-contained prompt + only the whitelisted data, with every
conclusion / label deliberately excluded (anti-anchoring).

    .venv/Scripts/python.exe eval/for_doubao.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "gold_retrieval.json"
CSV = ROOT / "eval" / "citations_50.csv"
SCRIPT = ROOT / "scripts" / "rag_eval_agent3.py"
SPEC = ROOT / "openspec" / "changes" / "agent-verify" / "specs" / "eval-benchmark" / "spec.md"
OUT = ROOT / "eval" / "for_doubao.txt"

spec_lines = SPEC.read_text(encoding="utf-8").splitlines()
l3_excerpt = "\n".join(spec_lines[115:157])  # 标注口径 + L3 检索/引用/拒答判据

gold = json.loads(GOLD.read_text(encoding="utf-8"))
gold_rows = [
    f"{i}. {item['question']} | gold={', '.join(item['gold_docs'])}"
    for i, item in enumerate(gold["questions"], start=1)
]

with CSV.open(encoding="utf-8-sig", newline="") as handle:
    rows = list(csv.DictReader(handle))
claim_rows = [
    f"{i}. document={r['document']} | chunk_id={r['chunk_id']} | claim={r['claim_text']}"
    for i, r in enumerate(rows, start=1)
]

source = SCRIPT.read_text(encoding="utf-8")


def extract_list(name: str) -> list[str]:
    marker = f"{name} = ["
    start = source.index(marker) + len(marker)
    end = source.index("]", start)
    return [
        line.strip().strip('",') for line in source[start:end].splitlines() if line.strip().startswith('"')
    ]


out_of_scope = extract_list("OUT_OF_SCOPE_DOCS")

parts = [
    "你是独立评测复核员。任务：不看任何已有结论，独立产出判定表。",
    "",
    "【硬性约束】",
    "- 只使用下面我贴给你的材料；不要联网搜索，不要假设存在其他文件，不要读取工作区。",
    "- 材料里没有 gold 标签、没有 supported/partial/unsupported 判定、没有任何指标数字；",
    "  如果哪里看起来像结论，那是原始数据的一部分，不要当答案。",
    "- 只判「主题是否相符 / 文档 ID 是否像真的」，不判法规条文的实质法律含义。",
    "- 不修改任何文件，只输出判定表；不要给综合分数或「通过/不通过」结论。",
    "- 无法独立判断的条目请明确标 UNDECIDED，留给人工终裁。",
    "",
    "【材料 1：L3 判据节选（spec 原文）】",
    l3_excerpt,
    "",
    "【材料 2：语料范围】",
    "语料共 143 部法规，领域为：贸易 / 海关 / 进出口 / 出口管制 / 制裁 / CISG / WTO 协定。",
    "法域：AU、CN、EU、INT、JP、US、WTO。文档 ID 形如 cn-customs-law-2021、wto-adp、",
    "us-cfr-19-152、au-export-control-act-2020、au-autonomous-sanctions-act-2011。",
    "不包含：个人所得税、婚姻家庭、交通事故、专利诉讼、食品安全、劳动法、环保、",
    "医疗损害、商品房买卖、公司法等领域。",
    "",
    "【材料 3：20 道评测题 + 待复核的 gold 文档 ID】",
    *gold_rows,
    "",
    "【材料 4：50 条 claim（只含 document / chunk_id / claim_text，不含任何判定标签）】",
    *claim_rows,
    "",
    "【材料 5：10 条超纲文本】",
    *[f"{i}. {t}" for i, t in enumerate(out_of_scope, start=1)],
    "",
    "【任务 A：gold 独立复核（20 题）】",
    "逐题判断 gold 文档 ID 是否与问题主题相符，并检查 ID 是否像真实语料 ID（拼写/多词缺漏）。",
    "输出：题号 | 你判定的 gold 文档 | 与材料中写的是否一致 | 理由一句话。",
    "",
    "【任务 B：claim 独立复核（50 条）】",
    "逐条判断 claim 文本与 document 主题是否属同一话题。",
    "三档：supported（同话题且内容相关）/ partial（沾边但不直接相关）/ unsupported（明显无关）。",
    "输出：行号 | 判定 | 理由一句话。",
    "注意：不要因为文本看起来像法规原文就判 supported——判断的是「和这份文档的话题对不对得上」。",
    "",
    "【任务 C：超纲核对（10 条）】",
    "结合材料 2 的语料范围，判断每条是否真的超出覆盖范围。输出：编号 | 是/否 | 一句话理由。",
    "",
    "【结尾】只输出三张判定表 + 一个 UNDECIDED 编号列表。不要总结、不要打分。",
]

OUT.write_text("\n".join(parts), encoding="utf-8")
print(f"wrote {OUT} ({OUT.stat().st_size} chars)")
print(f"gold={len(gold_rows)} claims={len(claim_rows)} out_of_scope={len(out_of_scope)}")
